"""EV-13: install round trip over a temporary HOME for every remedy kind x agent (user scope).

Each cell runs plan -> preview -> apply -> revert through the real InstallService and checks
markers, preservation of seeded user content, byte-identical revert, refusal after a user edit,
stale-digest rejection and the append-only ledger. Nothing is written outside ``ctx.tmp``.
"""

from __future__ import annotations

import json
import os
import pwd
import subprocess
from pathlib import Path

from ..contract import Check, EvalContext, SuiteResult

ID = "install_roundtrip"
TITLE = "Install round trip (apply / revert byte-identical)"
EV = ("EV-13",)

def _agents() -> tuple[str, ...]:
    """Every agent with install support (install/env.py FULL_SUPPORT), not a hand-kept list."""
    from ...install.env import AGENTS as KNOWN  # noqa: PLC0415
    from ...install.env import FULL_SUPPORT

    return tuple(a for a in KNOWN if a in FULL_SUPPORT)


AGENTS = _agents()
MARK = "orbit-eval"
SPECS = {
    "rule": {"kind": "rule", "id": "ev-rule", "payload": {"text": f"- {MARK}: prefer small commits"}},
    "permission": {"kind": "permission_rule", "id": "ev-perm", "payload": {"allow": ["git status"]}},
    "hook": {"kind": "hook", "id": "ev-hook",
             "payload": {"event": "Stop", "command": f"echo {MARK}"}},
    "skill": {"kind": "skill", "id": "ev-skill",
              "payload": {"name": f"{MARK}-skill",
                          "files": [{"rel": "SKILL.md",
                                     "text": f"---\nname: {MARK}-skill\n---\n\nBody.\n"}]}},
    "mcp": {"kind": "mcp", "id": "ev-mcp",
            "payload": {"name": f"{MARK}-mcp", "command": "npx", "args": ["-y", "docs"]}},
}
# Substring an installed file must contain, and the user edit that touches only our unit.
MARKERS = {("permission", "claude_code"): "Bash(git status:*)",
           ("permission", "codex"): '"git","status"',
           ("permission", "opencode"): "git status *"}
SEED = {
    ".claude/settings.json": json.dumps({"theme": "dark", "env": {"FOO": "bar"}}, indent=2) + "\n",
    ".claude/CLAUDE.md": "# My notes\n\nKeep me exactly.\n",
    ".claude.json": json.dumps({"numStartups": 7, "mcpServers": {}}, indent=2) + "\n",
    ".codex/config.toml": 'model = "x"  # mine\n',
    ".codex/AGENTS.md": "# agents\n\nmine\n",
    ".codex/hooks.json": "{}\n",
    ".config/opencode/opencode.json": json.dumps({"theme": "mine"}, indent=2) + "\n",
    ".pi/agent/mcp.json": json.dumps({"mcpServers": {}}, indent=2) + "\n",
}
# Each cell seeds only its own agent's files: a seeded ~/.claude/CLAUDE.md would (rightly) shadow
# OpenCode's global rules file and turn its rule cell into context_file_shadowed.
SEED_OWNER = {".claude/": "claude_code", ".claude.json": "claude_code", ".codex/": "codex",
              ".config/opencode/": "opencode", ".pi/": "pi"}


def _seed_for(agent: str | None) -> dict[str, str]:
    if agent is None:
        return dict(SEED)
    return {rel: text for rel, text in SEED.items()
            if next((a for prefix, a in SEED_OWNER.items() if rel.startswith(prefix)), agent) == agent}
# Codex no longer reads ~/.codex/prompts (install/env.py SUPPORTED), so it is not seeded.
DIRS = (".claude/skills", ".claude/agents", ".claude/commands", ".codex/rules", ".codex/skills",
        ".agents/skills", ".dsh/skills", ".pi/agent/skills", ".pi/agent/prompts", ".hermes/skills",
        ".local/share/opencode", ".config/opencode/skills", ".config/opencode/commands")
# Fake ``--version`` answers per binary (install/env.py AGENTS binary names).
VERSIONS = {"claude": "2.1.3 (Claude Code)", "codex": "codex-cli 0.80.0", "dsh": "dsh 0.1.1",
            "pi": "0.99.1", "hermes": "Hermes Agent v0.9.0", "opencode": "1.2.3"}


def _fake_run(argv, **_kw):
    out = VERSIONS.get(Path(argv[0]).name)
    return subprocess.CompletedProcess(argv, 0 if out else 1, out or "", "")


def _make_home(root: Path, agent: str | None = None) -> tuple[Path, object]:
    from ...install.env import Env  # noqa: PLC0415

    home, bin_dir = root / "home", root / "bin"
    for rel, text in _seed_for(agent).items():
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text(text, "utf-8")
    for rel in DIRS:
        (home / rel).mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in VERSIONS:
        (bin_dir / name).write_text("#!/bin/sh\nexit 0\n")
        (bin_dir / name).chmod(0o755)
    env = Env(home=home, environ={"PATH": str(bin_dir), "HOME": str(home)}, search_dirs=[bin_dir],
              run=_fake_run)
    return home, env


def _service(root: Path, agent: str | None = None):
    from ...appdb import AppDB  # noqa: PLC0415
    from ...install.service import InstallService  # noqa: PLC0415

    home, env = _make_home(root, agent)
    db = AppDB(root / "orbit" / "app.db")
    return home, db, InstallService(db, root / "orbit", env=env)


def _snapshot(home: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(home.rglob("*")) if p.is_file()}


def _marker(name: str, agent: str) -> str:
    return MARKERS.get((name, agent), MARK)


def _preserved(path: Path, before: bytes | None) -> bool:
    if before is None:
        return True
    old, new = before.decode(), path.read_text()
    if path.suffix == ".json":
        a, b = json.loads(old), json.loads(new)
        return all(b.get(k) == v for k, v in a.items() if k not in ("mcpServers", "hooks"))
    return old.rstrip("\n") in new


def _cell(root: Path, name: str, agent: str, checks: list[Check]) -> list[str]:
    """Run one matrix cell; return the target paths it wrote."""
    from ...install import store  # noqa: PLC0415
    from ...install.errors import StaleError  # noqa: PLC0415
    from ...install.targets import lookup  # noqa: PLC0415

    spec = SPECS[name]
    cid = f"install.{name}.{agent}"
    row = lookup(spec["kind"], agent, "user")
    home, db, svc = _service(root / "a", agent)
    try:
        plan = svc.plan({"type": "spec", "spec": spec}, agents=[agent])
        if row is None or row.reason:
            listed = [t for t in plan["targets"] if not t["mappable"] and t["reason"]]
            checks.append(Check(f"{cid}.unsupported", bool(listed) and plan["status"] == "unmappable",
                                detail=listed[0]["reason"] if listed else "not listed as unmappable"))
            return []
        if not plan["targets"] or not all(t["mappable"] for t in plan["targets"]):
            checks.append(Check(f"{cid}.mappable", False, detail=json.dumps(plan["targets"])[:300]))
            return []
        before = _snapshot(home)
        preview = svc.preview(plan["plan_id"])
        try:
            svc.apply(plan["plan_id"], "sha256:" + "0" * 64)
            checks.append(Check(f"{cid}.stale_rejected", False, detail="stale digest accepted"))
        except StaleError as error:
            checks.append(Check(f"{cid}.stale_rejected", error.code == "preview_stale"))
        result = svc.apply(plan["plan_id"], preview["preview_digest"])
        paths = [w["path"] for w in result["written"]]
        missing = [p for p in paths if _marker(name, agent) not in Path(p).read_text()]
        checks.append(Check(f"{cid}.markers", bool(paths) and not missing, detail=", ".join(missing)))
        broken = [p for p in paths if not _preserved(Path(p), before.get(p))]
        checks.append(Check(f"{cid}.preserved", not broken, detail=", ".join(broken)))
        install_id = result["install_id"]
        ledger_before = store.ledger_for(svc.appdb, install_id)
        reverted = svc.revert(install_id)
        after_rev = _snapshot(home)
        diff = sorted(p for p in set(before) | set(after_rev) if before.get(p) != after_rev.get(p))
        checks.append(Check(f"{cid}.roundtrip", reverted["ok"] and not diff,
                            detail=", ".join(diff) or str([r["status"] for r in reverted["results"]])))
        ledger = store.ledger_for(svc.appdb, install_id)
        idxs = [w["idx"] for w in result["written"]]
        per = {a: sorted(r["target_idx"] for r in ledger if r["action"] == a)
               for a in ("install_begin", "install", "revert")}
        ok = ledger[: len(ledger_before)] == ledger_before and all(v == sorted(idxs) for v in per.values())
        checks.append(Check(f"{cid}.ledger", ok, detail=json.dumps(per)))
    finally:
        db.close()
    _edit_refused(root / "b", name, agent, checks)
    return paths


def _edit_refused(root: Path, name: str, agent: str, checks: list[Check]) -> None:
    cid = f"install.{name}.{agent}.edit_refused"
    home, db, svc = _service(root, agent)
    try:
        plan = svc.plan({"type": "spec", "spec": SPECS[name]}, agents=[agent])
        result = svc.apply(plan["plan_id"], svc.preview(plan["plan_id"])["preview_digest"])
        mark = _marker(name, agent)
        path = next((Path(w["path"]) for w in result["written"] if mark in Path(w["path"]).read_text()),
                    None)
        if path is None:
            checks.append(Check(cid, False, detail="no written file carries the marker"))
            return
        edited = path.read_text().replace(mark, mark.replace("status", "status --short")
                                          if "status" in mark else mark + "-user-edit")
        path.write_text(edited)
        res = svc.revert(result["install_id"])
        statuses = [r["status"] for r in res["results"] if r["path"] == str(path)]
        ok = bool(statuses) and "reverted" not in statuses and path.read_text() == edited
        checks.append(Check(cid, ok, detail=str(statuses)))
    finally:
        db.close()


def _real_paths(paths: list[str], tmp_home: Path) -> list[Path]:
    real = Path(pwd.getpwuid(os.getuid()).pw_dir)
    out = []
    for p in paths:
        rel = Path(p).relative_to(tmp_home)
        if rel.parts and rel.parts[0] != ".claude.json":  # rewritten by live agents constantly
            out.append(real / rel)
    return out


def _stamp(paths: list[Path]) -> dict[str, float | None]:
    return {str(p): (p.stat().st_mtime if p.exists() else None) for p in paths}


def run(ctx: EvalContext) -> SuiteResult:
    try:
        from ...install.service import InstallService  # noqa: F401, PLC0415
    except ImportError as error:
        return SuiteResult(ID, skipped=f"install service unavailable: {error}")
    checks: list[Check] = []
    written: list[tuple[Path, str]] = []
    probe = [Path(pwd.getpwuid(os.getuid()).pw_dir) / rel for rel in (*SEED, *DIRS)]
    probe += [Path(pwd.getpwuid(os.getuid()).pw_dir) / ".claude/skills" / f"{MARK}-skill"]
    stamps = _stamp(probe)
    for name in SPECS:
        for agent in AGENTS:
            root = ctx.tmp / "install" / f"{name}-{agent}"
            written += [(root / "a" / "home", p) for p in _cell(root, name, agent, checks)]
    outside = [p for home, p in written if not p.startswith(str(home) + os.sep)]
    real = [p for home, p in written for p in _real_paths([p], home)] if not outside else []
    changed = [k for k, v in _stamp(probe + real).items() if stamps.get(k, v) != v]
    checks.append(Check("install.real_home_untouched", not outside and not changed,
                        detail=", ".join(outside + changed)))
    cells = len(SPECS) * len(AGENTS)
    # A real-machine smoke run is not implemented; report that as a metric, never as a passed check.
    metrics = {"cells": cells, "written": len(written)}
    if ctx.real:
        metrics["real_smoke"] = "not_implemented"
    return SuiteResult(ID, checks, metrics=metrics)

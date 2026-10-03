"""RC-12 plan builder: turn a candidate, catalog item, AI artifact or direct spec into an
InstallSpec, resolve its landing targets (IN-01) and store the plan in ``app.db``.

Other modules are reached only through ``app.db`` tables or lazy imports with a fallback:
install never imports recommend/ai code to build a plan.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import PurePosixPath

from . import collect, store
from . import targets as targets_mod
from .env import FULL_SUPPORT, inventory_names
from .errors import PlanError
from .fetch import FetchError, fetch_source, read_tree
from .templates import READONLY_ALLOWLIST, READONLY_VOCAB, render_template

REQUIRED = {"permission_rule": ("allow",), "rule": ("text",), "skill": ("name", "files"),
            "subagent": ("name", "text"), "command": ("name", "text"), "hook": ("event", "command"),
            "mcp": ("name",), "plugin": ("plugin", "marketplace"), "setting": ("settings",)}
FILE_KINDS = ("skill", "subagent", "command", "rule")
INVENTORY_KIND = {"skill": "skill", "mcp": "mcp", "hook": "hook", "plugin": "plugin", "rule": "rule"}
SUMMARY_KEYS = ("idx", "agent", "scope", "display", "action", "mappable", "reason", "reason_text", "requires_trust",
                "shared_layer", "note", "group")


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()


def digest(value) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9-]+", "-", str(text).lower()).strip("-")[:64].strip("-")
    return out or "item"


# ---- spec validation ----------------------------------------------------------------------------

def validate_spec(spec: dict) -> dict:
    """Check kind/slug/payload fields and fill defaults. Raises ``invalid_spec`` (422)."""
    if not isinstance(spec, dict):
        raise PlanError("invalid_spec", "spec 必须是对象")
    kind = spec.get("kind")
    if kind not in REQUIRED:
        raise PlanError("invalid_spec", f"未知 kind：{kind!r}")
    sid = spec.get("id")
    if not isinstance(sid, str) or not targets_mod.SLUG.fullmatch(sid):
        raise PlanError("invalid_spec", f"id 须匹配 [a-z0-9][a-z0-9-]{{0,63}}：{sid!r}")
    payload = spec.get("payload")
    if not isinstance(payload, dict):
        raise PlanError("invalid_spec", "payload 必须是对象")
    missing = [f for f in REQUIRED[kind] if payload.get(f) in (None, "", [], {})]
    if kind == "hook" and payload.get("event_bindings") and "event" in missing:
        missing.remove("event")
    if kind == "mcp" and not (payload.get("command") or payload.get("url")):
        missing.append("command|url")
    if missing:
        raise PlanError("invalid_spec", f"{kind} 缺少字段：{', '.join(missing)}", detail={"missing": missing})
    source = {"type": "spec", "id": None, "template": None, "license": None, "sha256": None,
              **(spec.get("source") or {})}
    return {"title": spec.get("title") or sid, "agents": spec.get("agents") or None,
            "scope": spec.get("scope") or "user", "project_path": spec.get("project_path"),
            "ai_ranges": spec.get("ai_ranges"), "evidence_refs": list(spec.get("evidence_refs") or []),
            **{k: v for k, v in spec.items() if v is not None and k != "source"}, "kind": kind, "id": sid,
            "payload": payload, "source": source}


# ---- catalog --------------------------------------------------------------------------------------

def _license(value) -> dict | None:
    if isinstance(value, dict):
        return value if value.get("spdx") or value.get("status") else None
    if isinstance(value, str) and value and value not in ("NOASSERTION", "NONE"):
        return {"spdx": value, "status": "ok"}
    return None


def _legacy_item(entry: dict) -> dict:
    """Map a ``legacy_catalog`` seed onto the catalog item shape install expects."""
    url = entry.get("url") or ""
    repo = url.split("github.com/", 1)[1].strip("/") if "github.com/" in url else None
    kind = entry.get("kind") or "skill"
    path = entry.get("source_path") or ""
    if kind == "skill":
        path = str(PurePosixPath(path).parent) if path else ""
        path = "" if path == "." else path
    source = {"type": "github", "repo": repo, "ref": entry.get("verified_sha") or "HEAD",
              "path": path} if repo else None
    return {"id": entry["id"], "kind": kind, "name": entry.get("name") or entry["id"],
            "description": entry.get("summary"), "url": url, "source": source, "install": None,
            "license": entry.get("license"), "agents": entry.get("agents") or ["claude_code"]}


_GITHUB = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?(?:/|$)")


def _mcp_from_manifest(manifest: dict) -> dict | None:
    """MCP registry ``server.json`` → install payload: a remote URL, else an npm/pypi package."""
    name = slug(str(manifest.get("name") or "").rsplit("/", 1)[-1])
    for remote in manifest.get("remotes") or []:
        if isinstance(remote, dict) and str(remote.get("url", "")).startswith("https://"):
            return {"name": name, "transport": "sse" if remote.get("type") == "sse" else "http",
                    "url": remote["url"]}
    for package in manifest.get("packages") or []:
        if not isinstance(package, dict) or (package.get("transport") or {}).get("type", "stdio") != "stdio":
            continue
        ident = package.get("identifier")
        version = package.get("version")
        if package.get("registryType") == "npm" and ident:
            return {"name": name, "transport": "stdio", "command": "npx",
                    "args": ["-y", f"{ident}@{version}" if version else ident]}
        if package.get("registryType") == "pypi" and ident:
            return {"name": name, "transport": "stdio", "command": "uvx",
                    "args": [f"{ident}=={version}" if version else ident]}
    return None


_PLUGIN_VARS = ("${CLAUDE_PLUGIN_ROOT}", "$CLAUDE_PLUGIN_ROOT", "${CLAUDE_PLUGIN_DATA}")


def _hook_from_manifest(manifest: dict) -> dict | None:
    """A ``hooks.json`` document → one hook payload when it runs a single self-contained
    command (any number of event/matcher bindings). Hooks that call scripts shipped inside
    their plugin (``${CLAUDE_PLUGIN_ROOT}``) only work through that plugin: ``None``."""
    hooks = manifest.get("hooks") if isinstance(manifest.get("hooks"), dict) else None
    if not hooks:
        return None
    commands, bindings, timeouts = set(), [], set()
    for event, entries in hooks.items():
        if not isinstance(event, str) or not isinstance(entries, list):
            return None
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                return None
            for hook in entry["hooks"]:
                if not isinstance(hook, dict) or hook.get("type", "command") != "command" \
                        or not isinstance(hook.get("command"), str) or set(hook) - {"type", "command", "timeout"}:
                    return None
                commands.add(hook["command"])
                timeouts.add(hook.get("timeout"))
            binding = {"event": event, "matcher": entry.get("matcher")}
            if binding not in bindings:
                bindings.append(binding)
    if len(commands) != 1 or len(timeouts) != 1:
        return None
    command = next(iter(commands))
    if not command.strip() or any(v in command for v in _PLUGIN_VARS):
        return None
    payload: dict = {"command": command, "event_bindings": bindings, **bindings[0]}
    if (timeout := next(iter(timeouts))) is not None:
        payload["timeout"] = timeout
    return payload


def catalog_item(detail: dict) -> dict:
    """Map a catalog ``detail()`` result (or its ``resource``) onto the item shape install uses:
    ``{id, kind, name, description, url, source, install, license, agents}`` where ``source`` is
    ``{type:'github', repo, ref, path}`` (pinned to the indexed commit) and ``install`` carries a
    ready ``mcp`` / ``plugin`` / ``hook`` payload when the resource declares one."""
    res = detail.get("resource") if isinstance(detail.get("resource"), dict) else detail
    kind = {"mcp_server": "mcp"}.get(res.get("type"), res.get("type"))
    meta, manifest, declared = res.get("metadata") or {}, res.get("manifest") or {}, res.get("install") or {}
    found = _GITHUB.search(res.get("url") or "")
    repo = meta.get("repository") or (found.group(1) if found else None)
    path = res.get("repo_path") or ""
    if kind == "skill" and path:
        path = "" if str(PurePosixPath(path).parent) == "." else str(PurePosixPath(path).parent)
    source = ({"type": "github", "repo": repo, "ref": res["commit_sha"], "path": path}
              if repo and res.get("commit_sha") and res.get("repo_path") else None)
    install = None
    if kind == "mcp":
        payload = declared.get("mcp") or _mcp_from_manifest(manifest)
        install = {"mcp": payload} if payload else None
    elif kind == "plugin" and declared.get("name") and declared.get("marketplace"):
        payload = {"plugin": declared["name"], "marketplace": declared["marketplace"]}
        if repo:
            payload["marketplace_source"] = {"source": "github", "repo": repo}
        install = {"plugin": payload}
    elif kind == "hook":
        payload = declared.get("hook") if isinstance(declared.get("hook"), dict) else _hook_from_manifest(manifest)
        install = {"hook": payload} if payload else None
    parents = [p for p in detail.get("parents") or [] if isinstance(p, str)]
    return {"id": res.get("item_id"), "kind": kind, "name": res.get("name") or res.get("item_id"),
            "description": res.get("summary"), "url": res.get("url"), "source": source, "install": install,
            "license": res.get("license"), "agents": res.get("agents") or None,
            "install_via": parents[0] if parents and install is None else None}


def default_catalog_lookup(item_id: str) -> dict | None:
    """``orbit_catalog`` item if that API exists, else the bundled legacy seed catalog."""
    try:
        import orbit_catalog  # noqa: PLC0415 - optional, wired later

        lookup = getattr(orbit_catalog, "item", None)
        if callable(lookup):
            found = lookup(item_id)
            if found:
                return found
    except Exception:  # noqa: BLE001 - optional dependency
        pass
    seeds = []
    try:
        from ..recommend.legacy_catalog import resources  # noqa: PLC0415

        seeds += resources()
    except Exception:  # noqa: BLE001
        pass
    try:  # bottleneck seeds: recommend recalls them while catalog.db is still empty
        from ..analytics.recommendations.catalog import load_catalog  # noqa: PLC0415

        seeds += [e for e in load_catalog() if e.get("url")]
    except Exception:  # noqa: BLE001
        pass
    for entry in seeds:
        if entry.get("id") == item_id:
            return _legacy_item(entry)
    return None


class _Offline:
    """Fetcher used to ask "is this already cached?" without touching the network."""

    def get(self, url, **_):
        raise FetchError("needs_fetch", url, http=409)


def _from_catalog(item: dict, *, cache_dir, fetcher, allow_network: bool) -> tuple[dict, dict]:
    kind = item.get("kind")
    name = item.get("name") or item["id"]
    source = item.get("source")
    lic = _license(item.get("license"))
    base = {"kind": kind, "id": slug(item["id"]), "title": name, "agents": item.get("agents"),
            "source": {"type": "catalog", "id": item["id"], "catalog_item_id": item["id"], "template": None,
                       "license": lic, "sha256": (source or {}).get("sha256")}}
    install = item.get("install") or {}
    link = {"links": [item.get("url")] if item.get("url") else []}
    if kind in ("mcp", "plugin", "hook"):
        payload = install.get(kind) if isinstance(install, dict) else None
        if not isinstance(payload, dict):
            # B16: show the link (and the bundle that installs it) instead of a 422 install CTA
            reason = "needs_plugin" if item.get("install_via") else "no_install_declaration"
            return {**base, "payload": {}, **link, "link_reason": reason,
                    "install_via": item.get("install_via")}, {"status": "link_only"}
        return {**base, "payload": dict(payload)}, {"status": "ready"}
    if kind not in FILE_KINDS:
        return {**base, "payload": {}, **link, "link_reason": "kind_not_installable"}, {"status": "link_only"}
    if not source:
        return {**base, "payload": {}, **link}, {"status": "link_only"}
    if lic is None or lic.get("status") == "link_only":
        return {**base, "payload": {}, **link}, {"status": "link_only"}
    try:
        fetched = fetch_source(source, cache_dir=cache_dir, fetcher=fetcher if allow_network else _Offline())
    except FetchError as error:
        if error.code == "needs_fetch":
            return {**base, "payload": {}}, {"status": "needs_fetch"}
        raise
    if fetched.get("link_only") and not lic:
        return {**base, "payload": {}, **link}, {"status": "link_only"}
    skipped: list[str] = []
    tree = read_tree(cache_dir, fetched["tree_sha256"], skipped)
    base["source"]["sha256"] = "sha256:" + fetched["tree_sha256"]
    if kind == "skill":
        files = [{"rel": rel, "text": text} for rel, text in sorted(tree.items())]
        payload = {"name": targets_mod.safe_name(name) if targets_mod.NAME.fullmatch(name) else slug(name),
                   "files": files}
    else:
        rel = PurePosixPath(source.get("path") or "").name
        text = tree.get(rel) if rel in tree else (next(iter(tree.values())) if len(tree) == 1 else None)
        if text is None:
            raise PlanError("catalog_not_installable", "目录条目来源不是单个文本文件")
        payload = {"text": text, "heading": name} if kind == "rule" else {"name": slug(name), "text": text}
    return {**base, "payload": payload}, {"status": "ready", "fetch": fetched, "skipped": skipped}


# ---- sources --------------------------------------------------------------------------------------

def _row(appdb, sql: str, params, missing_code: str) -> dict | None:
    try:
        with appdb.read() as db:
            row = db.execute(sql, params).fetchone()
    except sqlite3.OperationalError:
        raise PlanError(missing_code, f"{missing_code}", http=404) from None
    return dict(row) if row is not None else None


def _json(value):
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _rec_candidate_row(appdb, sid) -> dict | None:
    """Recommend's persisted candidate: install hints live inside the JSON ``card``."""
    try:
        row = _row(appdb, "SELECT * FROM rec_candidate WHERE candidate_id = ?", (sid,), "recommend_unavailable")
    except PlanError:
        raise PlanError("recommend_unavailable", "推荐候选不可用", http=404) from None
    if row is None:
        return None
    card = _json(row.get("card")) or {}
    for key in ("install_spec", "remedy_rule", "template", "template_params", "catalog_item_id",
                "target_agents", "scope"):
        if key in card and key not in row:
            row[key] = json.dumps(card[key]) if isinstance(card[key], (dict, list)) else card[key]
    # rec-engine-v2 cards name their catalog entry in ``source`` rather than ``catalog_item_id``.
    # A KB card's entry is the rule the official ``orbit-kb`` source publishes as ``kb:<id>``:
    # slate hygiene keeps the evidence-backed KB card and drops its ``catalog:kb:<id>`` twin,
    # so without this the remedy the user is shown could not be installed from its card.
    source = card.get("source") or {}
    if not row.get("catalog_item_id") and source.get("item_id"):
        if source.get("origin") == "catalog":
            row["catalog_item_id"] = source["item_id"]
        elif source.get("origin") == "kb":
            row["catalog_item_id"] = f"kb:{source['item_id']}"
    return row


# ---- KB remedies -----------------------------------------------------------------------------------
# A KB card is a remedy Orbit writes itself (allowlist, rule block, its own hook template, a
# skill or subagent file it authored). Its install payload comes from the rule's own preview
# lines and templates on the card; the catalog's ``kb:<id>`` twin only mirrors the prose and
# carries no install payload, so routing these through the catalog yields link_only / 422.

KB_KINDS = ("permission_rule", "rule", "hook", "skill", "subagent")
HOOK_TIMEOUT_S = 10  # same as ai/generate/render.py
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_ALLOW_LINE = re.compile(r"Bash\((.+?):\*\)|^\s*command\s*=\s*\"(.+)\"\s*$")
_CODEX_NOTE = re.compile(r"^（Codex[:：].*）$")
_FRONT_NAME = re.compile(r"^name:\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*$", re.M)


def _hook_template(rule_id: str):
    """Orbit's own hook script template for a KB hook rule (``retry-breaker``, ``stop-verify``)."""
    try:
        from ..ai.generate import templates  # noqa: PLC0415 - optional, data-only use

        found = templates.load()
    except Exception:  # noqa: BLE001
        return None
    for tid in (rule_id, rule_id.removesuffix("-hook")):
        if tid in found and found[tid].kind == "hook":
            return found[tid]
    return None


def _kb_hook(rule_id: str, text: str) -> dict | None:
    if (tpl := _hook_template(rule_id)) is not None:
        stem = tpl.script_name[:-3]
        base = "{orbit.hooks}/" + tpl.script_name
        matcher = tpl.defaults.get("matcher", "*")
        return {"event_bindings": [{"event": e["event"], "matcher": matcher if e.get("matcher") is None
                                    else e["matcher"]} for e in tpl.events],
                "command": f'python3 "{base}" --config "{base[:-3]}.config.json"', "timeout": HOOK_TIMEOUT_S,
                "script": {"name": tpl.script_name, "text": tpl.body},
                "extra_files": [{"name": f"{stem}.config.json",
                                 "text": json.dumps(tpl.defaults, ensure_ascii=False, indent=2) + "\n"}]}
    try:  # a plain command hook: the preview is the settings.json fragment itself
        doc = json.loads(text)
    except ValueError:
        return None
    return _hook_from_manifest(doc) if isinstance(doc, dict) else None


def _kb_spec(card: dict | None) -> dict | None:
    """InstallSpec for a ``kb``-origin card of an installable kind, else ``None``. Stored cards
    keep the filled preview (``file``), ``kind``, ``target`` and ``problem.vars``, not the rule."""
    source = (card or {}).get("source") or {}
    kind = (card or {}).get("kind")
    if source.get("origin") != "kb" or kind not in KB_KINDS:
        return None
    rid = str(source.get("item_id") or "")
    values = ((card.get("problem") or {}).get("vars")) or {}
    lines = [(t, m) for t, m in card.get("file") or [] if isinstance(t, str)]
    text = "\n".join(t for t, _ in lines if not _CODEX_NOTE.match(t.strip()))
    # Unfilled slots show as "…" (required, no value) or a literal "{name}" on the card.
    missing = list(dict.fromkeys(_PLACEHOLDER.findall(text))) + (["…"] if "…" in text else [])
    # Cards show unfilled slots as a generic phrase; the card records which ones were unfilled.
    missing += [n for n in (card.get("unfilled_slots") or []) if n not in missing]
    if missing:
        raise PlanError("candidate_not_renderable", "推荐还有未填写的内容（卡片中显示为 … 或 {名称}），"
                        "暂不能一键安装", detail={"missing": missing})
    target = card.get("target") or {}
    agents, title = target.get("agents") or None, card.get("title") or rid
    template = None
    if kind == "permission_rule":
        found = (_ALLOW_LINE.search(line) for line, _ in lines)
        heads = values.get("head_list") or [m.group(1) or m.group(2) for m in found if m]
        allow = [h for h in dict.fromkeys(" ".join(str(h).split()) for h in heads) if h in READONLY_VOCAB]
        if heads and not allow:
            raise PlanError("not_readonly", "推荐的命令都不在只读词表内", detail={"rejected": list(heads)})
        spec = render_template(READONLY_ALLOWLIST, {"allow": allow or None, "id": slug(rid), "title": title}, agents)
        return {**spec, "source": {**spec["source"], "type": "kb", "id": rid, "catalog_item_id": f"kb:{rid}"}}
    if kind == "hook":
        payload = _kb_hook(rid, text)
        if payload is None:
            raise PlanError("candidate_not_renderable", "KB hook 没有可安装的模板或命令")
        template = (payload.get("script") or {}).get("name")
    elif not text.strip():
        return None  # e.g. a skill that lives in the catalog (``catalog_ref``)
    elif kind == "rule":
        payload = {"text": text}
    else:
        path = PurePosixPath(str(target.get("path_hint") or ""))
        found = _FRONT_NAME.search(text)
        name = found.group(1) if found else (path.parent.name if kind == "skill" else path.stem) or slug(rid)
        payload = ({"name": name, "files": [{"rel": "SKILL.md", "text": text.rstrip("\n") + "\n"}]}
                   if kind == "skill" else {"name": name, "text": text.rstrip("\n") + "\n"})
    ai_text = sorted({t for t, m in lines if m == "ai" and t.strip()}) if kind != "hook" else []
    return {"kind": kind, "id": slug(rid), "title": title, "agents": agents, "payload": payload,
            "ai_text": ai_text or None,
            "source": {"type": "kb", "id": rid, "catalog_item_id": f"kb:{rid}", "template": template,
                       "license": None, "sha256": None}}


# AI artifacts name their files by symbolic target; the prefix says which agent it is for.
SYMBOLIC_AGENTS = {"claude": "claude_code", "codex": "codex", "agents": "codex"}
_AI_MARKER = re.compile(r"^<!-- /?orbit:rule\b.*-->$")


def _ai_payload(kind: str, payload: dict, files: list[dict]) -> dict:
    """AI generate's payload (see ``ai/generate/render.py``) → this module's InstallSpec payload."""
    by_target = {f.get("target"): f for f in files if isinstance(f, dict)}
    if kind == "rule":
        lines = [ln for ln in str(payload.get("markdown") or "").splitlines() if not _AI_MARKER.match(ln.strip())]
        return {"text": "\n".join(lines).strip("\n")}
    if kind == "skill":
        return {"name": payload.get("name"),
                "files": [{"rel": f.get("path"), "text": f.get("content")} for f in payload.get("files") or []]}
    if kind in ("subagent", "command"):
        return {"name": payload.get("name"), "text": payload.get("markdown")}
    if kind == "hook":
        script = payload.get("script") or {}
        bindings, command = [], None
        for target, f in by_target.items():
            if str(target).startswith("claude.user_settings#/hooks/"):
                for entry in _json(f.get("content")) or []:
                    bindings.append({"event": target.rsplit("/", 1)[1], "matcher": entry.get("matcher")})
                    command = command or ((entry.get("hooks") or [{}])[0]).get("command")
        bindings = bindings or [dict(b) for b in payload.get("event_bindings") or []]
        config = next((f for t, f in by_target.items() if str(t).startswith("orbit.hooks/")
                       and str(t).endswith(".config.json")), None)
        out = {"event_bindings": bindings, "command": command, "timeout": payload.get("timeout_s"),
               "script": {"name": script.get("name"), "text": script.get("content")}}
        if config is not None:
            out["extra_files"] = [{"name": config["target"].split("/", 1)[1], "text": config.get("content")}]
        return out
    return payload


def _from_artifact(row: dict, sid: str) -> dict:
    body = _json(row.get("payload")) or {}
    files = _json(row.get("files")) or []
    kind = body.get("kind") or row.get("kind")
    if isinstance(body.get("payload"), dict):  # already an InstallSpec-shaped body
        inner, agents = body["payload"], body.get("agents")
    else:
        inner = _ai_payload(kind, body, files)
        found = {SYMBOLIC_AGENTS.get(str(f.get("target")).split(".", 1)[0]) for f in files if isinstance(f, dict)}
        agents = sorted(a for a in found if a) or body.get("agents")
    ai_text = [ln["text"] for f in files if isinstance(f, dict) for ln in f.get("lines") or []
               if isinstance(ln, dict) and ln.get("mark") == "ai" and str(ln.get("text") or "").strip()]
    return {"kind": kind, "id": slug(body.get("id") or row.get("name") or sid),
            "title": body.get("title") or row.get("title") or sid, "agents": agents, "payload": inner,
            "ai_ranges": body.get("ai_ranges"), "ai_text": sorted(set(ai_text)) or None,
            "evidence_refs": [e for e in _json(row.get("evidence")) or [] if isinstance(e, str)],
            "source": {"type": "artifact", "id": sid, "template": row.get("template_id"), "license": None,
                       "sha256": None}}


def build_spec(source: dict, *, appdb, catalog_lookup=None, cache_dir, fetcher=None,
               allow_network: bool = False) -> tuple[dict, dict]:
    """Return ``(spec, extra)``; ``extra['status']`` is ready | needs_fetch | link_only."""
    stype = (source or {}).get("type")
    sid = source.get("id")
    if stype == "spec":
        return validate_spec(source.get("spec")), {"status": "ready"}
    if stype == "candidate":
        try:
            row = _row(appdb, "SELECT * FROM candidate WHERE candidate_id = ?", (sid,), "recommend_unavailable")
        except PlanError:
            row = None
        if row is None:
            row = _rec_candidate_row(appdb, sid)
        if row is None:
            raise PlanError("not_found", f"候选不存在：{sid}", http=404)
        agents = _json(row.get("target_agents"))
        spec = _json(row.get("install_spec"))
        template = row.get("remedy_rule") or row.get("template")
        card = _json(row.get("card"))
        card = card if isinstance(card, dict) else {}
        extra = {"status": "ready"}
        if isinstance(spec, dict) and spec:
            spec = {**spec, "id": spec.get("id") or slug(sid)}
        elif template == READONLY_ALLOWLIST:
            spec = render_template(template, _json(row.get("template_params")) or {}, agents)
        elif (kb_spec := _kb_spec(card)) is not None:
            spec = kb_spec
        elif row.get("catalog_item_id"):
            item_id = row["catalog_item_id"]
            # A KB card for a third-party resource (``catalog_ref``) installs that catalog item.
            ref = (card.get("source") or {}).get("catalog_ref") if (card.get("source") or {}).get("origin") == "kb" else None
            if ref and (catalog_lookup or default_catalog_lookup)(ref):
                item_id = ref
            spec, extra = build_spec({"type": "catalog", "id": item_id}, appdb=appdb,
                                     catalog_lookup=catalog_lookup, cache_dir=cache_dir, fetcher=fetcher,
                                     allow_network=allow_network)
        else:
            raise PlanError("candidate_not_renderable", "候选没有可安装的规格或内置模板")
        src = {**(spec.get("source") or {}), "type": "candidate", "id": sid}
        spec = {**spec, "source": src, "title": spec.get("title") or row.get("title") or sid,
                "agents": spec.get("agents") or agents, "scope": spec.get("scope") or row.get("scope") or "user"}
        if extra["status"] != "ready":
            return spec, extra
        return validate_spec(spec), extra
    if stype == "catalog":
        item = (catalog_lookup or default_catalog_lookup)(sid)
        if not item:
            raise PlanError("catalog_unavailable", f"目录条目不可用：{sid}", http=404)
        spec, extra = _from_catalog(item, cache_dir=cache_dir, fetcher=fetcher, allow_network=allow_network)
        return (validate_spec(spec) if extra["status"] == "ready" else spec), extra
    if stype == "artifact":
        row = _row(appdb, "SELECT * FROM ai_artifact WHERE artifact_id = ?", (sid,), "artifact_unavailable")
        if row is None:
            raise PlanError("artifact_unavailable", f"AI 产物不存在：{sid}", http=404)
        return validate_spec(_from_artifact(row, sid)), {"status": "ready"}
    raise PlanError("invalid_source", f"未知来源类型：{stype!r}")


# ---- plan -----------------------------------------------------------------------------------------

def _default_agents(env_info: dict) -> list[str]:
    found = [a["agent"] for a in env_info.get("agents", []) if a["agent"] in FULL_SUPPORT and a.get("installed")]
    return found or ["claude_code"]


def _name(spec: dict) -> str:
    p = spec.get("payload") or {}
    return str(p.get("name") or p.get("plugin") or spec.get("id"))


def make_plan(source: dict, *, agents=None, scope: str = "user", project_path: str | None = None,
              fetch: bool = False, service) -> dict:
    if (source or {}).get("type") == "collect":
        spec, extra, scope = collect.spec(service.home), {"status": "ready"}, "user"
    else:
        spec, extra = build_spec(source, appdb=service.appdb, catalog_lookup=service.catalog_lookup,
                                 cache_dir=service.cache_dir, fetcher=service.fetcher, allow_network=fetch)
    env_info = service.environment()
    spec["agents"] = list(agents or spec.get("agents") or _default_agents(env_info))
    spec["scope"] = scope or spec.get("scope") or "user"
    if spec["scope"] == "project":
        if not project_path or not os.path.isabs(project_path) or not os.path.isdir(project_path):
            raise PlanError("project_path_required", "项目作用域需要已存在的绝对目录 project_path")
        spec["project_path"] = os.path.abspath(project_path)
    else:
        spec["project_path"] = None
    status, warnings, targets = extra["status"], [], []
    if status == "ready":
        try:
            resolve = collect.resolve_targets if spec["kind"] == "collect" else targets_mod.resolve_targets
            targets = resolve(spec, env_info, env=service.env)
        except targets_mod.PlanError as error:
            raise PlanError(error.code, error.message, http=error.http) from None
        if spec.get("ai_text"):
            for t in targets:
                t["ai_text"] = spec["ai_text"]
        if targets and not any(t.get("mappable") for t in targets):
            status = "unmappable"
        inv = INVENTORY_KIND.get(spec["kind"])
        if inv:
            for agent in spec["agents"]:
                if _name(spec) in inventory_names(service.reads, agent, inv):
                    warnings.append(f"already_present:{inv}:{_name(spec)}")
                    break
    warnings += [f"skipped_binary:{rel}" for rel in extra.get("skipped") or []]
    spec_hash = digest({k: v for k, v in spec.items() if k not in ("agents", "scope", "project_path")})
    plan_id = "pl_" + hashlib.sha256(canonical([spec_hash, spec["agents"], spec["scope"],
                                                spec["project_path"]])).hexdigest()[:16]
    src = spec.get("source") or {}
    source_type, source_id = src.get("type") or source.get("type"), src.get("id")
    if source_type == "spec" and source_id is None:
        source_id = spec["id"]
    store.save_plan(service.appdb, {
        "plan_id": plan_id, "source_type": source_type, "source_id": source_id, "spec": spec,
        "spec_hash": spec_hash, "targets": targets, "agents": spec["agents"], "scope": spec["scope"],
        "project_path": spec["project_path"], "status": status, "warnings": warnings})
    active = store.find_active(service.appdb, source_type, source_id)
    return {"plan_id": plan_id, "status": status, "title": spec.get("title"), "kind": spec["kind"],
            "source": {"type": source_type, "id": source_id, "template": src.get("template"),
                       "license": src.get("license")},
            "agents": spec["agents"], "scope": spec["scope"], "project_path": spec["project_path"],
            "warnings": warnings, "links": spec.get("links") or [],
            "link_reason": spec.get("link_reason"), "install_via": spec.get("install_via"),
            "fetch": {k: extra["fetch"][k] for k in ("tree_sha256", "commit", "cached")} if extra.get("fetch") else None,
            "targets": [{k: t.get(k) for k in SUMMARY_KEYS} for t in targets],
            "already_installed": {"install_id": active["install_id"], "state": active["state"],
                                  "tracking_id": active.get("tracking_id")} if active else None}

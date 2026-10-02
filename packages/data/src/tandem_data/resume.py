"""DT-24 resume command templates. Pure data: nothing here executes or spawns a process.

Each template is the documented interactive resume entry of the Agent CLI. ``evidence``
names where the flag was confirmed (vendored upstream source under ``third_party/`` when
available). The caller (App UI) shows or copies the command; running it is the user's act.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from tandem_data.store import readonly_connection

RUNNING_STATUSES = frozenset({"active"})


@dataclass(frozen=True)
class Template:
    argv: tuple[str, ...]  # "{id}" / "{file}" placeholders
    needs_cwd: bool
    evidence: str
    verified: bool = True


TEMPLATES: dict[str, Template] = {
    "claude_code": Template(
        ("claude", "--resume", "{id}"),
        True,
        "Claude Code CLI `--resume <session-id>`; sessions are stored per project directory",
    ),
    "codex": Template(
        ("codex", "resume", "{id}"),
        True,
        "third_party/codex: `codex resume <SESSION_ID>` subcommand",
    ),
    "opencode": Template(
        ("opencode", "--session", "{id}"),
        True,
        "third_party/opencode/packages/opencode/src/cli/cmd/tui.ts option `session`",
    ),
    "pi": Template(
        ("pi", "--session", "{file}"),
        True,
        "third_party/pi/packages/coding-agent/src/cli/args.ts `--session <session.jsonl>`",
    ),
    "hermes": Template(
        ("hermes", "--resume", "{id}"),
        False,
        "third_party/hermes-agent/hermes_cli/sessions_cmd.py relaunch(['--resume', id])",
    ),
    "dsh": Template(
        ("dsh", "tui", "--resume", "{id}"),
        True,
        "third_party/deepseek-harness/apps/cli/README.md `dsh tui --resume <session>`",
    ),
    "kimi": Template(
        ("kimi", "--session", "{id}"),
        True,
        "Kimi CLI `--session <id>`; not vendored, confirm against the installed version",
        verified=False,
    ),
}
AGENTS = tuple(TEMPLATES)


def resume_template(
    agent: str,
    native_id: str | None,
    *,
    status: str = "unknown",
    kind: str = "main",
    cwd: str | None = None,
    session_file: str | None = None,
) -> dict:
    """Return the resume command for one session. Never executes anything."""
    result = {
        "agent": agent,
        "supported": False,
        "disabled": False,
        "reason": None,
        "argv": None,
        "command": None,
        "cwd": cwd,
        "evidence": None,
        "verified": False,
    }
    template = TEMPLATES.get(agent)
    if template is None:
        return {**result, "reason": f"no resume entry is known for agent {agent!r}"}
    result.update(evidence=template.evidence, verified=template.verified)
    if kind != "main":
        return {**result, "reason": f"{kind} sessions are resumed through their root session"}
    values = {"id": native_id, "file": session_file}
    argv = []
    for part in template.argv:
        if part in ("{id}", "{file}"):
            value = values[part[1:-1]]
            if not value:
                missing = "native session id" if part == "{id}" else "session file"
                return {**result, "reason": f"{missing} is unavailable"}
            if value.startswith("-") or any(ord(char) < 32 for char in value):
                return {**result, "reason": "session identifier is not safe to pass as argument"}
            argv.append(value)
        else:
            argv.append(part)
    if template.needs_cwd and not cwd:
        return {**result, "reason": "session working directory is unknown"}
    command = shlex.join(argv)
    if template.needs_cwd:
        command = f"cd {shlex.quote(cwd)} && {command}"
    result.update(supported=True, argv=argv, command=command)
    if status in RUNNING_STATUSES:
        result.update(disabled=True, reason="session is still running")
    return result


def session_resume(home: str | Path, session_uid: str) -> dict:
    """Look up a projected session and return its resume template (read-only)."""
    db_path = Path(home).expanduser() / "tandem.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"No Tandem database at {db_path}")
    with readonly_connection(db_path) as db:
        row = db.execute(
            "SELECT s.session_uid, s.native_id, s.kind, s.status, s.cwd, s.root_uid, src.agent "
            "FROM session s JOIN source src USING(source_id) WHERE s.session_uid=?",
            (session_uid,),
        ).fetchone()
        if row is None:
            raise KeyError(session_uid)
        session_file = None
        if row["agent"] == "pi":
            located = db.execute(
                "SELECT src.root_path, f.relative_path FROM raw_record r "
                "JOIN source_file f USING(file_id) JOIN source src USING(source_id) "
                "WHERE r.session_uid=? AND f.role='transcript' LIMIT 1",
                (session_uid,),
            ).fetchone()
            if located:
                session_file = str(Path(located["root_path"]) / located["relative_path"])
    result = resume_template(
        row["agent"],
        row["native_id"],
        status=row["status"],
        kind=row["kind"],
        cwd=row["cwd"],
        session_file=session_file,
    )
    return {
        "session_uid": session_uid,
        "status": row["status"],
        "root_uid": row["root_uid"],
        **result,
    }

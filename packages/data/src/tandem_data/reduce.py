"""Deterministic L3 derivation. No LLM and no inferred missing tokens.

Cost is either the harness-reported value or, for a resolved model with complete token buckets,
the versioned list price in ``tandem_data.models``; otherwise it stays NULL.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from tandem_data import models as model_catalog
from tandem_data.command_spec import command_spec
from tandem_data.contract import TOKENS, canonical, uid
from tandem_data.shell import command_head
from tandem_data.store import insert, insert_rows


def normalize_remote(remote: str | None) -> str | None:
    if not remote:
        return None
    if remote.startswith("git@") and ":" in remote:
        host, path = remote[4:].split(":", 1)
        result = host.lower() + "/" + path
    elif "://" in remote:
        parsed = urlsplit(remote)
        if not parsed.hostname:
            return None
        result = parsed.hostname.lower() + parsed.path
    else:
        return None
    return result.removesuffix(".git").rstrip("/")


def _git(path: Path, *args) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True, timeout=3
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def project_for(
    store, cwd: str | None, recorded_remote=None, recorded_root=None, *, cache=None
) -> str | None:
    # One projection is a single transaction. Repeated sessions in the same cwd
    # must not launch the same Git probes twice per session. Never cache across runs.
    key = (cwd, recorded_remote, recorded_root)
    if cache is not None and key in cache:
        return cache[key]
    live = {v for v in cache.values() if v} if cache is not None else set()
    result = _project_for(store, cwd, recorded_remote, recorded_root, live)
    if cache is not None:
        cache[key] = result
    return result


# Agent worktree layouts: <repo>/.claude/worktrees/<name>, <repo>/.work/<name>, ... A deleted
# worktree directory belongs to <repo>, not to a project of its own.
_WORKTREE = re.compile(
    r"^(?P<repo>.+?)/(?:\.claude/worktrees|\.work|\.worktrees|\.git/worktrees)/[^/]+(?:/.*)?$"
)
# Directories that hold unrelated projects; a path never folds into them.
_SHARED_ROOTS = frozenset(
    (
        "/",
        "/tmp",
        "/private",
        "/private/tmp",
        "/private/var",
        "/var",
        "/var/folders",
        "/Users",
        "/home",
        "/opt",
        "/usr",
        "/Volumes",
        "/mnt",
        "/workspace",
        "/workspaces",
    )
)


def _shared_root(path: Path) -> bool:
    """True for home, its parents, its direct children (~/Projects) and system roots."""
    home = Path.home()
    return (
        str(path) in _SHARED_ROOTS
        or path == home
        or path in home.parents
        or path.parent == home
        or _system_temp(path)
    )


def _system_temp(path: Path) -> bool:
    """/var/folders/<a>/<b>/T and above hold every process's temporary directories."""
    text = str(path).removeprefix("/private")
    return text.startswith("/var/folders") and len(Path(text).parts) <= 6


def _probe_dir(path: Path) -> Path | None:
    """Where to ask Git about a missing directory: its worktree's repo, else the nearest
    existing ancestor below any shared root (a deleted subdirectory of a checkout)."""
    match = _WORKTREE.match(str(path))
    if match and Path(match["repo"]).is_dir():
        return Path(match["repo"])
    for parent in path.parents:
        if _shared_root(parent):
            return None
        if parent.is_dir():
            return parent
    return None


def _enclosing_project(store, path: Path, live, missing=False) -> str | None:
    """The outermost project in use whose root or recorded path encloses ``path``.

    Only projects of sessions outside this derivation and projects assigned during it
    (``live``) qualify, so stale rows from earlier projections never attract paths. Git
    projects win over plain paths. A deleted directory does not fold into a plain
    directory that still exists: that is a workspace that held a removed project.
    """
    candidates = {}
    for row in store.db.execute(
        "SELECT project_id,key_type,key,paths FROM project WHERE key_type<>'bucket' AND"
        " (project_id IN (SELECT project_id FROM session WHERE project_id IS NOT NULL)"
        " OR project_id IN (SELECT value FROM json_each(?)))"
        " ORDER BY key_type IN ('git_remote','git_root') DESC, project_id",
        (canonical(sorted(live)),),
    ):
        roots = set(json.loads(row["paths"]))
        if row["key_type"] in ("path", "git_root"):
            roots.add(row["key"])
        for root in roots:
            candidates.setdefault(root, (row["project_id"], row["key_type"]))
    for parent in (*reversed(path.parents), path):
        found = candidates.get(str(parent))
        if found is None or _shared_root(parent):
            continue
        if missing and found[1] == "path" and parent.is_dir():
            continue
        return found[0]
    return None


def _project_for(store, cwd, recorded_remote, recorded_root, live=()):
    if not cwd and not recorded_remote and not recorded_root:
        return None
    for override in store.db.execute(
        "SELECT * FROM project_override ORDER BY length(pattern) DESC,pattern"
    ):
        if cwd and fnmatch.fnmatchcase(cwd, override["pattern"]):
            return override["project_id"]
    root = recorded_root
    remote = normalize_remote(recorded_remote)
    path = Path(cwd).expanduser() if cwd else None
    missing = path is not None and not path.is_dir()
    probe = _probe_dir(path) if missing else path
    if remote is None and probe:
        common = _git(probe, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common:
            common_path = Path(common)
            root = str(common_path.parent) if common_path.name == ".git" else common
            remote = remote or normalize_remote(_git(probe, "config", "--get", "remote.origin.url"))
    if missing and not remote and not root:
        # Repository gone too: name the worktree's repository, not the worktree.
        match = _WORKTREE.match(str(path))
        if match:
            path = Path(match["repo"])
    if remote:
        key_type, key = "git_remote", remote
    elif root:
        key_type, key = "git_root", root
    elif path and path.resolve() == Path.home().resolve():
        key_type, key = "bucket", "other"
    elif cwd and ("/Documents/Codex/" in cwd or "local-agent-mode-sessions" in cwd):
        key_type, key = "bucket", "temporary_workspace"
    else:
        key_type, key = "path", str(path) if path else cwd
        enclosing = _enclosing_project(store, Path(key), live, missing) if path else None
        if enclosing is not None:
            # A plain directory inside another project's tree (/repo/src under /repo).
            _add_path(store, enclosing, cwd)
            return enclosing
    project_id = uid("project", key_type, key)
    existing = store.db.execute(
        "SELECT paths FROM project WHERE project_id=?", (project_id,)
    ).fetchone()
    paths = set(json.loads(existing[0])) if existing else set()
    if cwd:
        paths.add(cwd)
    store.db.execute(
        "INSERT INTO project VALUES(?,?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET paths=excluded.paths",
        (project_id, key_type, key, key.rsplit("/", 1)[-1], remote, canonical(sorted(paths))),
    )
    return project_id


def _add_path(store, project_id, cwd):
    if not cwd:
        return
    row = store.db.execute("SELECT paths FROM project WHERE project_id=?", (project_id,)).fetchone()
    paths = set(json.loads(row[0])) if row else set()
    if cwd not in paths:
        paths.add(cwd)
        store.db.execute(
            "UPDATE project SET paths=? WHERE project_id=?", (canonical(sorted(paths)), project_id)
        )


def _model(store, provider, raw):
    if not raw:
        return None, "unknown"
    row = store.db.execute(
        "SELECT model_id FROM model_alias WHERE model_raw=? AND provider IN (?, '') "
        "ORDER BY provider<>'' DESC LIMIT 1",
        (raw, provider or ""),
    ).fetchone()
    if row:
        return row[0], "resolved"
    # Seed the alias table from the built-in normaliser; user rows (same key) always win.
    known = model_catalog.canonical_model(raw)
    if known is None:
        return raw, "unmapped"
    store.db.execute(
        "INSERT OR IGNORE INTO model_alias(provider,model_raw,model_id,family) VALUES(?,?,?,?)",
        (provider or "", raw, known[0], known[1]),
    )
    return known[0], "resolved"


TOOL_KINDS = {
    "shell": {"bash", "exec", "exec_command", "commandexecution", "shell", "pwsh", "terminal"},
    "file.read": {"read", "read_file", "view_image"},
    "file.edit": {"edit", "multiedit", "apply_patch", "filechange", "str_replace_editor"},
    "file.write": {"write", "write_file"},
    "search": {"grep", "glob", "find", "search"},
    "web.search": {"web.search", "websearch", "web_search"},
    "web.fetch": {"web.fetch", "webfetch", "web_fetch"},
    "subagent": {"agent", "task", "spawn_agent", "subagent", "delegate_task"},
    "skill": {"skill"},
    "plan": {"todowrite", "update_plan", "todo_write", "todo/write"},
    "ask_user": {"askuserquestion", "request_user_input", "ask_user_question"},
}


def tool_metadata(name, attrs, *, cwd=None, project_id=None):
    kind = next((key for key, names in TOOL_KINDS.items() if name.lower() in names), "other")
    if attrs.get("category") in TOOL_KINDS:
        kind = attrs["category"]
    server, tool = attrs.get("mcp_server"), attrs.get("mcp_tool")
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3:
            kind, server, tool = "mcp", parts[1], parts[2]
    args = attrs.get("input")
    files = []
    command = None
    skill = None
    if isinstance(args, dict):
        for key in ("path", "file_path", "filename"):
            if isinstance(args.get(key), str):
                files.append(args[key])
        command = args.get("command", args.get("cmd"))
        skill = args.get("skill") if kind == "skill" else attrs.get("skill")
    # Effective program (cd/env/shell wrappers unwrapped); never a path or an assignment.
    head = command_head(command)
    spec = (
        command_spec(
            command, cwd=(args or {}).get("workdir", attrs.get("cwd", cwd)), project_id=project_id
        )
        if kind == "shell" and isinstance(command, str)
        else None
    )
    return {
        "name_raw": name,
        "name": tool if kind == "mcp" else name.lower(),
        "kind": kind,
        "mcp_server": server,
        "mcp_tool": tool,
        "skill": skill,
        "command_head": head,
        "command_spec": canonical(spec) if spec is not None else None,
        "files": canonical(files),
    }


def _duration(call, result, attrs):
    if attrs.get("duration_unmeasured"):
        return None, "unknown", "missing"
    reported = attrs.get("duration_ms")
    if isinstance(reported, int) and not isinstance(reported, bool) and reported >= 0:
        return reported, "reported", "reported"
    if call and result and call["ts"] is not None and result["ts"] is not None:
        delta = result["ts"] - call["ts"]
        if delta >= 0:
            ctime, rtime = call["attrs"]["time"], result["attrs"]["time"]
            if ctime["semantics"] == "started" and rtime["semantics"] == "completed":
                return (
                    delta,
                    "native_bounds",
                    "reported"
                    if ctime["quality"] == rtime["quality"] == "reported"
                    else "estimated",
                )
            return delta, "event_difference", "estimated"
    return None, "unknown", "missing"


def _approve(values, call_uid, approval, evidence):
    """Copy a permission decision onto one tool call and keep both events as its evidence."""
    decision, wait, decision_event, request_event = approval
    evidence.append((call_uid, decision_event, "permission.decision"))
    if request_event:
        evidence.append((call_uid, request_event, "permission.request"))
    values["approval"] = decision
    if wait is not None:
        values["approval_wait_ms"] = wait


def derive(store, *, scoped=False, progress=None, sessions=None):
    """Derive L3 rows. ``sessions`` (SQL) narrows a scoped run to a session closure."""
    project_cache = {}
    progress = progress or (lambda _: None)
    where = ""
    if scoped:
        where = " WHERE i.source_id IN (SELECT source_id FROM rebuild_scope)"
        if sessions is not None:
            where += f" AND i.session_uid IN ({sessions})"
    identities = {
        row["session_uid"]: dict(row)
        for row in store.db.execute(
            "SELECT DISTINCT i.* FROM session_identity i JOIN event e USING(session_uid)" + where
        )
    }
    metas = {}
    recorded_roots = {}
    spawn_ids = {}  # child session -> native id of the parent's spawning tool call
    progress({"stage": "derive_metadata", "completed": 0, "total": len(identities)})
    for index, (session_uid, identity) in enumerate(identities.items()):
        values = {
            "session_uid": session_uid,
            "source_id": identity["source_id"],
            "native_id": identity["native_id"],
            "kind": "main",
            "root_uid": session_uid,
            "status": "unknown",
            "timezone_source": "unknown",
        }
        # Only metadata events and events naming a git root contribute here; the
        # substring test is a superset of both (checked again below), so the other
        # events are neither fetched nor decoded twice (derive_sessions reads them).
        for row in store.db.execute(
            "SELECT kind,attrs,text FROM event WHERE session_uid=? AND (kind IN "
            "('session.meta','setting.change','session.title') OR instr(attrs,'\"git_root\"')>0) "
            "ORDER BY seq",
            (session_uid,),
        ):
            attrs = json.loads(row["attrs"])
            if isinstance(attrs.get("git_root"), str):
                recorded_roots[session_uid] = attrs["git_root"]
            if row["kind"] in ("session.meta", "setting.change"):
                for name in (
                    "kind",
                    "parent_uid",
                    "cwd",
                    "git_branch",
                    "git_sha",
                    "git_remote",
                    "client",
                    "harness_version",
                    "title",
                    "title_source",
                    "timezone",
                    "timezone_source",
                    "depth",
                ):
                    if attrs.get(name) is not None:
                        values[name] = attrs[name]
                if attrs.get("spawn_native_call_id"):
                    spawn_ids[session_uid] = str(attrs["spawn_native_call_id"])
                if attrs.get("forked_from_uid"):
                    values["forked_from"] = attrs["forked_from_uid"]
                if attrs.get("forked_from_native"):
                    values["forked_from"] = store.identity(
                        identity["source_id"], attrs["forked_from_native"]
                    )
                if attrs.get("imported_from"):
                    values["kind"], values["imported_from"] = "import", attrs["imported_from"]
            if row["kind"] == "session.title" and row["text"] is not None:
                previous_priority = {"custom": 3, "native": 2, "ai": 1}.get(
                    values.get("title_source"), 0
                )
                if {"custom": 3, "native": 2, "ai": 1}.get(
                    attrs.get("title_source"), 0
                ) >= previous_priority:
                    values["title"], values["title_source"] = row["text"], attrs.get("title_source")
        if not values.get("timezone"):
            values["timezone"], values["timezone_source"] = None, "unknown"
        # Same fallback as _derive_session, so session and turn projects agree.
        if not values.get("cwd"):
            # First event (by seq) carrying a cwd, read lazily: the filtered scan above
            # skips ordinary events.
            for row in store.db.execute(
                "SELECT attrs FROM event WHERE session_uid=? AND instr(attrs,'\"cwd\"')>0 "
                "ORDER BY seq",
                (session_uid,),
            ):
                event_cwd = json.loads(row["attrs"]).get("cwd")
                if event_cwd:
                    values["cwd"] = event_cwd
                    break
        metas[session_uid] = values
        progress({"stage": "derive_metadata", "completed": index + 1, "total": len(identities)})
    progress({"stage": "derive_projects", "completed": 0, "total": len(metas)})
    # Resolve sessions with a recorded Git identity first, then shallow directories, so
    # /repo exists before /repo/src looks for an enclosing project; the result no longer
    # depends on session order.
    for session_uid, values in sorted(
        metas.items(),
        key=lambda item: (
            not (item[1].get("git_remote") or recorded_roots.get(item[0])),
            len(Path(item[1].get("cwd") or "/").parts),
            item[0],
        ),
    ):
        project_for(
            store,
            values.get("cwd"),
            values.get("git_remote"),
            recorded_roots.get(session_uid),
            cache=project_cache,
        )
    for index, (session_uid, values) in enumerate(metas.items()):
        current, seen = session_uid, {session_uid}
        while metas.get(current, {}).get("parent_uid"):
            parent = metas[current]["parent_uid"]
            if parent not in metas or parent in seen:
                values["lineage_unresolved"] = 1
                store.issue(
                    values["source_id"],
                    "unresolved_session_lineage",
                    stage="l3",
                    detail={"session_uid": session_uid},
                )
                break
            current = parent
            seen.add(current)
        values["root_uid"] = current
        values["project_id"] = project_for(
            store,
            values.get("cwd"),
            values.get("git_remote"),
            recorded_roots.get(session_uid),
            cache=project_cache,
        )
        insert(store.db, "session", values)
        progress({"stage": "derive_projects", "completed": index + 1, "total": len(metas)})

    progress({"stage": "derive_sessions", "completed": 0, "total": len(metas)})
    for index, (session_uid, meta) in enumerate(metas.items()):
        events = []
        # Only the columns _derive_session reads: text and ext can be large.
        for row in store.db.execute(
            "SELECT event_uid,record_uid,seq,kind,ts,call_id,turn_uid,attrs FROM event "
            "WHERE session_uid=? ORDER BY seq",
            (session_uid,),
        ):
            event = dict(row)
            event["attrs"] = json.loads(event["attrs"])
            events.append(event)
        _derive_session(
            store, session_uid, meta, events, recorded_roots.get(session_uid), project_cache
        )
        progress({"stage": "derive_sessions", "completed": index + 1, "total": len(metas)})
    _link_spawns(store, metas, spawn_ids)
    # A partial import can first create a child-path project; later parent metadata
    # folds its sessions into the enclosing project. Keep explicit inventories and
    # overrides, but discard provisional rows with no remaining canonical evidence.
    store.db.execute(
        "DELETE FROM project WHERE project_id NOT IN (SELECT project_id FROM ("
        "SELECT project_id FROM session UNION ALL SELECT project_id FROM event_context "
        "UNION ALL SELECT project_id FROM turn UNION ALL SELECT project_id FROM tool_call "
        "UNION ALL SELECT project_id FROM model_call UNION ALL SELECT project_id FROM project_override "
        "UNION ALL SELECT project_id FROM inventory_scan) WHERE project_id IS NOT NULL)"
    )


def _link_spawns(store, metas, spawn_ids):
    """Parent spawn call <-> child session, from either side's native evidence."""
    for session_uid, native_call in spawn_ids.items():
        parent = metas[session_uid].get("parent_uid")
        row = store.db.execute(
            "SELECT call_uid FROM tool_call WHERE session_uid=? AND native_call_id=? "
            "AND call_event_uid IS NOT NULL ORDER BY started_at LIMIT 1",
            (parent, native_call),
        ).fetchone()
        if parent and row:
            store.db.execute(
                "UPDATE session SET spawn_call_uid=? WHERE session_uid=?", (row[0], session_uid)
            )
            store.db.execute(
                "UPDATE tool_call SET subagent_session_uid=? "
                "WHERE call_uid=? AND subagent_session_uid IS NULL",
                (session_uid, row[0]),
            )
    # Calls whose parent-side evidence named the child (Claude agentId, Codex thread id).
    for session_uid in metas:
        row = store.db.execute(
            "SELECT call_uid FROM tool_call WHERE subagent_session_uid=? "
            "AND call_event_uid IS NOT NULL ORDER BY started_at LIMIT 1",
            (session_uid,),
        ).fetchone()
        if row:
            store.db.execute(
                "UPDATE session SET spawn_call_uid=? "
                "WHERE session_uid=? AND spawn_call_uid IS NULL",
                (row[0], session_uid),
            )


def _insert_grouped(db, table, rows):
    """Insert rows in order, one executemany per run of rows with the same columns."""
    run = []
    for row in rows:
        if run and list(row) != list(run[0]):
            insert_rows(db, table, run)
            run = []
        run.append(row)
    insert_rows(db, table, run)


def _derive_session(store, session_uid, meta, events, recorded_root=None, shared_projects=None):
    current_turn = None
    turns = {}
    context = {"cwd": None, "provider": None, "model_raw": None, "effort_raw": None}
    context["cwd"] = next(
        (e["attrs"].get("cwd") for e in events if e["attrs"].get("cwd")), meta.get("cwd")
    )
    project_cache = {}
    open_tools = defaultdict(list)
    tools = {}
    permissions = {}
    permission_evidence = []
    # Decisions recorded before their tool call (Codex writes exec_approval_* before the
    # completed CommandExecution item): applied when the call with that call_id appears.
    pending_approvals = {}
    features = Counter()
    snapshots = {}
    # Per-event rows are written with one executemany per session (same rows and order).
    contexts, turn_updates = [], []
    for event in events:
        attrs, kind = event["attrs"], event["kind"]
        for field in context:
            if attrs.get(field) is not None:
                context[field] = attrs[field]
        cwd = context["cwd"]
        if cwd not in project_cache:
            project_cache[cwd] = project_for(
                store, cwd, meta.get("git_remote"), recorded_root, cache=shared_projects
            )
        project_id = project_cache[cwd]
        contexts.append({"event_uid": event["event_uid"], "project_id": project_id, **context})
        native_turn = attrs.get("native_turn_id")
        new_trigger = kind == "message.user" and attrs.get("origin") in (
            "human",
            "queued",
            "peer",
            "notification",
            "automation",
        )
        if (
            kind == "turn.start"
            or (new_trigger and (not current_turn or native_turn is None))
            or (
                native_turn is not None
                and kind not in ("session.meta", "setting.change")
                and current_turn
                and turns[current_turn]["native_id"] != str(native_turn)
            )
        ):
            turn_key = str(native_turn) if native_turn is not None else event["event_uid"]
            current_turn = uid("turn", session_uid, turn_key)
            if current_turn not in turns:
                turns[current_turn] = {
                    "turn_uid": current_turn,
                    "session_uid": session_uid,
                    "idx": len(turns),
                    "native_id": str(native_turn) if native_turn is not None else None,
                    "trigger": attrs.get("origin", "unknown"),
                    "boundary_source": "reported" if native_turn is not None else "derived",
                    "project_id": project_id,
                    "status": "unknown",
                    "started_at": event["ts"],
                    "ended_at": None,
                    "trigger_event_uid": event["event_uid"] if new_trigger else None,
                    "first_event_uid": event["event_uid"],
                    "last_event_uid": event["event_uid"],
                }
        if current_turn:
            turn = turns[current_turn]
            event["turn_uid"] = current_turn
            turn["last_event_uid"] = event["event_uid"]
            if new_trigger and turn["trigger_event_uid"] is None:
                turn["trigger_event_uid"], turn["trigger"] = event["event_uid"], attrs["origin"]
            if kind == "turn.end":
                turn["status"], turn["ended_at"] = attrs.get("status", "unknown"), event["ts"]
            turn_updates.append((current_turn, event["event_uid"]))
        if kind == "tool.call":
            call_uid = uid("tool_call", event["event_uid"])
            values = {
                "call_uid": call_uid,
                "session_uid": session_uid,
                "turn_uid": event["turn_uid"],
                "project_id": project_id,
                "native_call_id": event["call_id"],
                "call_event_uid": event["event_uid"],
                "result_event_uid": None,
                **tool_metadata(attrs["name"], attrs, cwd=context["cwd"], project_id=project_id),
                "subagent_session_uid": attrs.get("subagent_session_uid"),
                "status": attrs.get("status") or "unknown",
                "pairing_quality": "missing_result",
                "is_wrapper": int(attrs.get("is_wrapper", False)),
                "argument_digest": attrs.get("argument_digest"),
                "started_at": event["ts"],
                "ended_at": None,
                "duration_ms": None,
                "duration_source": "unknown",
                "duration_quality": "missing",
                "attribution": canonical(attrs.get("attribution", {})),
            }
            tools[call_uid] = (values, event)
            open_tools[event["call_id"]].append(call_uid)
            if event["call_id"] in pending_approvals:
                _approve(
                    values, call_uid, pending_approvals.pop(event["call_id"]), permission_evidence
                )
        elif kind == "tool.result":
            matches = open_tools[event["call_id"]]
            if len(matches) == 1:
                call_uid = matches.pop()
                values, call = tools[call_uid]
                values.update(
                    result_event_uid=event["event_uid"],
                    status=attrs.get("status", "unknown"),
                    pairing_quality="native_id",
                    ended_at=None if attrs.get("duration_unmeasured") else event["ts"],
                    exit_code=attrs.get("exit_code"),
                    error_class=attrs.get("error_class"),
                    status_scope=attrs.get("status_scope", "unknown"),
                )
                duration, source, quality = _duration(call, event, {**call["attrs"], **attrs})
                values.update(
                    duration_ms=duration, duration_source=source, duration_quality=quality
                )
                native_execution = attrs.get("native_execution_ms")
                if (
                    isinstance(native_execution, int)
                    and not isinstance(native_execution, bool)
                    and native_execution >= 0
                    and not attrs.get("duration_unmeasured")
                ):
                    values["native_execution_ms"] = native_execution
                ctime, rtime = call["attrs"]["time"], attrs["time"]
                if (
                    ctime["semantics"] == "started"
                    and rtime["semantics"] == "completed"
                    and ctime["quality"] == rtime["quality"] == "reported"
                    and call["ts"] is not None
                    and event["ts"] is not None
                    and event["ts"] >= call["ts"]
                ):
                    values["wall_elapsed_ms"] = event["ts"] - call["ts"]
            else:
                call_uid = uid("tool_call", event["event_uid"])
                tools[call_uid] = (
                    {
                        "call_uid": call_uid,
                        "session_uid": session_uid,
                        "turn_uid": event["turn_uid"],
                        "project_id": project_id,
                        "native_call_id": event["call_id"],
                        "result_event_uid": event["event_uid"],
                        **tool_metadata(
                            attrs.get("name") or "unknown",
                            attrs,
                            cwd=context["cwd"],
                            project_id=project_id,
                        ),
                        "status": "ambiguous" if matches else "orphan_result",
                        "pairing_quality": "ambiguous" if matches else "missing_call",
                        "ended_at": event["ts"],
                        "duration_source": "unknown",
                        "duration_quality": "missing",
                    },
                    None,
                )
                store.issue(
                    meta["source_id"],
                    "unpaired_tool_result",
                    stage="l3",
                    record_uid=event["record_uid"],
                )
        elif kind == "permission.request":
            if attrs.get("permission_id"):
                permissions[attrs["permission_id"]] = (
                    event["call_id"],
                    event["ts"],
                    event["event_uid"],
                )
        elif kind == "permission.decision":
            call_id, start, request_event = permissions.get(
                attrs.get("permission_id"), (event["call_id"], None, None)
            )
            wait = (
                event["ts"] - start
                if start is not None and event["ts"] is not None and event["ts"] >= start
                else None
            )
            approval = (attrs.get("decision"), wait, event["event_uid"], request_event)
            if open_tools.get(call_id):
                for tool_uid in open_tools[call_id]:
                    _approve(tools[tool_uid][0], tool_uid, approval, permission_evidence)
            elif call_id is not None:
                pending_approvals[call_id] = approval
        elif kind == "model.usage":
            provider, raw = (
                attrs.get("provider", context["provider"]),
                attrs.get("model_raw", context["model_raw"]),
            )
            model_id, resolution = _model(store, provider, raw)
            metrics = {token: attrs.get(token) for token in TOKENS}
            metrics.update(cost_usd=attrs.get("cost_usd"), cost_source=attrs.get("cost_source"))
            if (
                metrics["cost_usd"] is None
                and resolution == "resolved"
                and attrs["usage_scope"] == "call"
            ):
                price = model_catalog.cost_usd(model_id, metrics)
                if price is not None:
                    metrics.update(cost_usd=price, cost_source="price_table")
            if attrs["usage_scope"] == "call":
                insert(
                    store.db,
                    "model_call",
                    {
                        "call_uid": uid("model_call", attrs["request_key"]),
                        "session_uid": session_uid,
                        "turn_uid": event["turn_uid"],
                        "project_id": project_id,
                        "usage_event_uid": event["event_uid"],
                        "request_id": attrs.get("request_id"),
                        "request_identity_quality": "reported"
                        if attrs.get("request_id")
                        else "derived"
                        if attrs.get("request_key")
                        else "unknown",
                        "boundary_quality": "reported"
                        if attrs.get("request_id")
                        else "observed"
                        if attrs.get("boundary_evidence") == "changed_cumulative_usage"
                        else "unknown",
                        "provider": provider,
                        "model_raw": raw,
                        "model_id": model_id,
                        "model_resolution": resolution,
                        "effort_raw": attrs.get("effort_raw"),
                        "effort_rank": attrs.get("effort_rank"),
                        "purpose": attrs.get("purpose"),
                        "coverage": attrs["coverage"],
                        **metrics,
                        "latency_ms": attrs.get("latency_ms"),
                        "ttft_ms": attrs.get("ttft_ms"),
                        "stop_reason": attrs.get("stop_reason"),
                        "ts": event["ts"],
                    },
                )
            else:
                key = (attrs["snapshot_key"], attrs.get("counter_cycle", "unknown"))
                previous = snapshots.get(key)
                if previous and any(
                    metrics[token] is not None
                    and previous.get(token) is not None
                    and metrics[token] < previous[token]
                    for token in TOKENS
                ):
                    store.issue(
                        meta["source_id"],
                        "cumulative_counter_decreased",
                        stage="l3",
                        record_uid=event["record_uid"],
                    )
                snapshots[key] = metrics
                observed_at = store.db.execute(
                    "SELECT v.captured_at FROM raw_record r JOIN source_revision v USING(revision_uid) WHERE record_uid=?",
                    (event["record_uid"],),
                ).fetchone()[0]
                insert(
                    store.db,
                    "usage_snapshot",
                    {
                        "snapshot_uid": uid("usage_snapshot", event["event_uid"]),
                        "session_uid": session_uid,
                        "event_uid": event["event_uid"],
                        "snapshot_key": key[0],
                        "counter_cycle": key[1],
                        "usage_scope": attrs["usage_scope"],
                        "coverage": attrs["coverage"],
                        "provider": provider,
                        "model_raw": raw,
                        "model_id": model_id,
                        "purpose": attrs.get("purpose"),
                        "observation_seq": event["seq"],
                        "ts": event["ts"],
                        "observed_at": observed_at,
                        **metrics,
                    },
                )
        elif kind == "link" and attrs.get("ref"):
            insert(
                store.db,
                "link",
                {
                    "link_uid": uid("link", event["event_uid"]),
                    "session_uid": session_uid,
                    "turn_uid": event["turn_uid"],
                    "event_uid": event["event_uid"],
                    "kind": attrs.get("link_kind", "artifact"),
                    "ref": attrs["ref"],
                    "ts": event["ts"],
                },
            )
    insert_rows(store.db, "event_context", contexts)
    if turn_updates:
        store.db.executemany("UPDATE event SET turn_uid=? WHERE event_uid=?", turn_updates)
    # Same rows in the same order as row-by-row inserts, written per table in batches
    # (foreign keys are deferred, so tool_call rows may precede their turn rows).
    call_events = []
    for values, call in tools.values():
        for role, field in (("call", "call_event_uid"), ("result", "result_event_uid")):
            if values.get(field):
                call_events.append((values["call_uid"], values[field], role))
        if call:
            features[("tool_category", values["kind"])] += 1
            for feature, field in (
                ("mcp_server", "mcp_server"),
                ("skill", "skill"),
                ("command_head", "command_head"),
            ):
                if values.get(field):
                    features[(feature, values[field])] += 1
            for filename in json.loads(values["files"]):
                if Path(filename).suffix:
                    features[("file_extension", Path(filename).suffix)] += 1
    _insert_grouped(store.db, "tool_call", [values for values, _ in tools.values()])
    store.db.executemany("INSERT INTO tool_call_event VALUES(?,?,?)", call_events)
    store.db.executemany("INSERT OR IGNORE INTO tool_call_event VALUES(?,?,?)", permission_evidence)
    insert_rows(store.db, "turn", turns.values())
    store.db.executemany(
        "INSERT INTO session_feature VALUES(?,?,?,?)",
        [(session_uid, feature, value, count) for (feature, value), count in features.items()],
    )
    action_times = [
        e["ts"]
        for e in events
        if e["ts"] is not None
        and e["kind"]
        in (
            "message.user",
            "message.assistant",
            "tool.call",
            "tool.result",
            "turn.start",
            "turn.end",
        )
    ]
    action_times.extend(
        e["ts"]
        for e in events
        if e["ts"] is not None
        and e["kind"] == "session.meta"
        and e["attrs"].get("time", {}).get("semantics") == "created"
    )
    final_boundary = next(
        (e for e in reversed(events) if e["kind"] in ("turn.start", "turn.end")), None
    )
    final_status = (
        final_boundary["attrs"].get("status", "unknown")
        if final_boundary and final_boundary["kind"] == "turn.end"
        else "unknown"
    )
    if not action_times:
        # Sessions without turn/message boundaries (tool-only subagent or review rollouts)
        # still span their timestamped events.
        action_times = [e["ts"] for e in events if e["ts"] is not None]
    store.db.execute(
        "UPDATE session SET started_at=?,ended_at=?,status=? WHERE session_uid=?",
        (
            min(action_times) if action_times else None,
            max(action_times) if action_times else None,
            final_status,
            session_uid,
        ),
    )

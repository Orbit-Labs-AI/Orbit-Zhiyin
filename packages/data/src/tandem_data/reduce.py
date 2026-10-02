"""Deterministic L3 derivation. No LLM, cost estimation, or inferred missing tokens."""

from __future__ import annotations

import fnmatch
import json
import shlex
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from tandem_data.contract import TOKENS, canonical, uid
from tandem_data.store import insert


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


def project_for(store, cwd: str | None, recorded_remote=None, recorded_root=None) -> str | None:
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
    if path and path.is_dir():
        common = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common:
            common_path = Path(common)
            root = str(common_path.parent) if common_path.name == ".git" else common
            remote = remote or normalize_remote(_git(path, "config", "--get", "remote.origin.url"))
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


def _model(store, provider, raw):
    if not raw:
        return None, "unknown"
    row = store.db.execute(
        "SELECT model_id FROM model_alias WHERE model_raw=? AND provider IN (?, '') "
        "ORDER BY provider<>'' DESC LIMIT 1",
        (raw, provider or ""),
    ).fetchone()
    return (row[0], "resolved") if row else (raw, "unmapped")


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


def tool_metadata(name, attrs):
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
    head = None
    if isinstance(command, str):
        try:
            words = shlex.split(command)
            if words:
                head = " ".join(
                    words[:2] if words[0] in ("git", "uv", "pnpm", "npm", "docker") else words[:1]
                )
        except ValueError:
            pass
    return {
        "name_raw": name,
        "name": tool if kind == "mcp" else name.lower(),
        "kind": kind,
        "mcp_server": server,
        "mcp_tool": tool,
        "skill": skill,
        "command_head": head,
        "files": canonical(files),
    }


def _duration(call, result, attrs):
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


def derive(store, *, scoped=False):
    identities = {
        row["session_uid"]: dict(row)
        for row in store.db.execute(
            "SELECT DISTINCT i.* FROM session_identity i JOIN event e USING(session_uid)"
            + (" WHERE i.source_id IN (SELECT source_id FROM rebuild_scope)" if scoped else "")
        )
    }
    metas = {}
    recorded_roots = {}
    for session_uid, identity in identities.items():
        values = {
            "session_uid": session_uid,
            "source_id": identity["source_id"],
            "native_id": identity["native_id"],
            "kind": "main",
            "root_uid": session_uid,
            "status": "unknown",
            "timezone_source": "unknown",
        }
        for row in store.db.execute(
            "SELECT * FROM event WHERE session_uid=? ORDER BY seq", (session_uid,)
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
        metas[session_uid] = values
    for session_uid, values in metas.items():
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
            store, values.get("cwd"), values.get("git_remote"), recorded_roots.get(session_uid)
        )
        insert(store.db, "session", values)

    for session_uid, meta in metas.items():
        events = []
        for row in store.db.execute(
            "SELECT * FROM event WHERE session_uid=? ORDER BY seq", (session_uid,)
        ):
            event = dict(row)
            event["attrs"] = json.loads(event["attrs"])
            events.append(event)
        _derive_session(store, session_uid, meta, events, recorded_roots.get(session_uid))


def _derive_session(store, session_uid, meta, events, recorded_root=None):
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
    features = Counter()
    snapshots = {}
    for event in events:
        attrs, kind = event["attrs"], event["kind"]
        for field in context:
            if attrs.get(field) is not None:
                context[field] = attrs[field]
        cwd = context["cwd"]
        if cwd not in project_cache:
            project_cache[cwd] = project_for(store, cwd, meta.get("git_remote"), recorded_root)
        project_id = project_cache[cwd]
        insert(
            store.db,
            "event_context",
            {"event_uid": event["event_uid"], "project_id": project_id, **context},
        )
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
            store.db.execute(
                "UPDATE event SET turn_uid=? WHERE event_uid=?", (current_turn, event["event_uid"])
            )
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
                **tool_metadata(attrs["name"], attrs),
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
        elif kind == "tool.result":
            matches = open_tools[event["call_id"]]
            if len(matches) == 1:
                call_uid = matches.pop()
                values, call = tools[call_uid]
                values.update(
                    result_event_uid=event["event_uid"],
                    status=attrs.get("status", "unknown"),
                    pairing_quality="native_id",
                    ended_at=event["ts"],
                    exit_code=attrs.get("exit_code"),
                    error_class=attrs.get("error_class"),
                    status_scope=attrs.get("status_scope", "unknown"),
                )
                duration, source, quality = _duration(call, event, {**call["attrs"], **attrs})
                values.update(
                    duration_ms=duration, duration_source=source, duration_quality=quality
                )
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
                        **tool_metadata(attrs.get("name") or "unknown", attrs),
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
                permissions[attrs["permission_id"]] = (event["call_id"], event["ts"])
        elif kind == "permission.decision":
            call_id, start = permissions.get(attrs.get("permission_id"), (event["call_id"], None))
            for tool_uid in open_tools.get(call_id, []):
                values, _ = tools[tool_uid]
                values["approval"] = attrs.get("decision")
                if start is not None and event["ts"] is not None and event["ts"] >= start:
                    values["approval_wait_ms"] = event["ts"] - start
        elif kind == "model.usage":
            provider, raw = (
                attrs.get("provider", context["provider"]),
                attrs.get("model_raw", context["model_raw"]),
            )
            model_id, resolution = _model(store, provider, raw)
            metrics = {token: attrs.get(token) for token in TOKENS}
            metrics.update(cost_usd=attrs.get("cost_usd"), cost_source=attrs.get("cost_source"))
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
    for values, call in tools.values():
        insert(store.db, "tool_call", values)
        for role, field in (("call", "call_event_uid"), ("result", "result_event_uid")):
            if values.get(field):
                store.db.execute(
                    "INSERT INTO tool_call_event VALUES(?,?,?)",
                    (values["call_uid"], values[field], role),
                )
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
    for turn in turns.values():
        insert(store.db, "turn", turn)
    for (feature, value), count in features.items():
        store.db.execute(
            "INSERT INTO session_feature VALUES(?,?,?,?)", (session_uid, feature, value, count)
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
    store.db.execute(
        "UPDATE session SET started_at=?,ended_at=?,status=? WHERE session_uid=?",
        (
            min(action_times) if action_times else None,
            max(action_times) if action_times else None,
            final_status,
            session_uid,
        ),
    )

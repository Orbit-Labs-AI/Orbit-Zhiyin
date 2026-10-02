"""``recommend_inputs`` analysis section (runs in the analysis worker, not the gateway).

Reuses the memoised analysis (signals, assessments, tasks, legacy cards) and adds SQL facts
over the selected sessions: read-only command approvals, failures by software, skill/MCP
usage, model mix and one row per main session. The snapshot cache keeps the result, so the
gateway engine only needs these ≤ 200 KB RecInputs, never the 10-second analysis.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from functools import partial
from pathlib import Path

from ..services.sections import Section, register

VERSION = "rec-inputs-v1"
MAX_BYTES = 200_000
MAX_UIDS = 20
READONLY_HEADS = ("git status", "git diff", "git log", "git show", "ls", "cat", "pwd", "rg",
                  "grep", "find", "head", "tail", "wc", "gh pr view", "gh pr checks",
                  "gh issue view")
FAILURE_CLASSES = ("command_not_found", "missing_dependency", "permission_denied", "timeout",
                   "network")
FAILED = ("failed", "error", "failure")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "apply_patch")
RULE_PROBLEMS = {"correction_density": "wrong_approach",
                 "repeated_requirements": "repeated_instruction",
                 "identical_retries": "tool_env_failure", "tool_failures": "tool_env_failure",
                 "validation_failures": "buggy_output",
                 "acceptance_evidence_gap": "missing_verification",
                 "context_pressure": "context_loss"}
UIDS = "(SELECT value FROM json_each(?))"
APPROVED = ("approved", "approved_for_session", "allow")
# Ordered: the first matching class wins (exit 127 is checked separately).
ERROR_PATTERNS = tuple((error_class, re.compile(pattern, re.IGNORECASE)) for error_class, pattern in (
    ("command_not_found", r"command not found|not recognized"),
    ("permission_denied", r"permission denied|\beacces\b"),
    ("timeout", r"timed out|\btimeout\b"),
    ("network", r"could not resolve host|\benotfound\b|\beconnrefused\b"),
    ("missing_dependency", r"modulenotfounderror|cannot find module|no module named"),
))
WRAPPERS = {("npx",): 1, ("bunx",): 1, ("pnpm", "dlx"): 2, ("yarn", "dlx"): 2, ("npm", "exec"): 2,
            ("uv", "run"): 2, ("uvx",): 1, ("poetry", "run"): 2}
VERIFY = re.compile(r"^(pytest|python -m pytest|python3 -m pytest|npm (run )?test|pnpm (run )?test|"
                    r"yarn test|vitest|jest|cargo test|go test|make( test)?|tsc|latexmk|swift test|"
                    r"xcodebuild test|uv run pytest)\b")
MIN_UNVERIFIED_EDITS, MIN_TEST_FAILURES, MAX_TASK_DIRS = 5, 3, 5


def readonly_head(command_head: str | None) -> str | None:
    if not command_head:
        return None
    head = " ".join(command_head.split())
    for prefix in sorted(READONLY_HEADS, key=len, reverse=True):
        if head == prefix or head.startswith(prefix + " "):
            return prefix
    return None


def compute(store, scope, params, memo) -> dict:
    from ..services.sections import WITH_TEXT

    result = memo.sections(store, scope, ["bottleneck_recommendations", "sessions", "tasks"],
                           WITH_TEXT, params.get("_rev"))
    br = result.get("bottleneck_recommendations") or {}
    signals, assessments = br.get("signals") or [], br.get("assessments") or []
    roots = [r for r in result.get("sessions") or [] if r.get("session_uid")]
    root_of = {}
    for row in roots:
        for uid in row.get("included_session_uids") or [row["session_uid"]]:
            root_of[uid] = row["session_uid"]
        root_of[row["session_uid"]] = row["session_uid"]
    diagnostics: list[dict] = []
    with store.connect() as conn:
        facts, agents = _facts(conn, root_of, roots, signals, diagnostics, result)
        facts.update(_kb_facts(conn, root_of, roots, diagnostics))
        inventory = _inventory(conn, diagnostics, getattr(store, "home", None))
        projects = _projects(conn, {r.get("project_id") for r in roots}, diagnostics)
    starts = [r["started_at"] for r in roots if r.get("started_at") is not None]
    first, last = (min(starts), max(starts)) if starts else (None, None)
    weeks = max(1.0, ((last - first) / (7 * 86_400_000)) if starts else 1.0)
    inputs = {
        "version": VERSION, "scope": None, "scope_hash": None, "data_rev": None,
        "inventory_rev": None, "analysis_digest": result.get("analysis_digest"),
        "agents": agents,
        "sessions": {"main": len(roots), "first_ts": first, "last_ts": last,
                     "weeks": round(weeks, 3)},
        "signals": signals, "assessments": assessments, "tasks": _tasks(result),
        "facts": facts, "inventory": inventory, "projects": projects, "profile": _profile(scope, diagnostics, getattr(store, "home", None)),
        "legacy_cards": (br.get("recommendations") or [])[:20], "diagnostics": diagnostics,
    }
    return cap(inputs)


def _projects(conn, ids: set, diagnostics: list) -> dict[str, dict]:
    """{project_id: {name: basename(root), root}} for the selected sessions' projects, so cards
    name a project directory instead of its opaque id."""
    ids = sorted(i for i in ids if i)
    if not ids:
        return {}
    try:
        rows = conn.execute(f"SELECT project_id, name, paths FROM project WHERE project_id IN {UIDS}",
                            (json.dumps(ids),)).fetchall()
    except Exception as error:  # noqa: BLE001 - optional, never fail the section
        diagnostics.append({"source": "projects", "status": "unavailable", "reason": str(error)})
        return {}
    out = {}
    for project_id, name, paths in rows:
        try:
            parsed = json.loads(paths) if paths else []
        except ValueError:
            parsed = []
        root = next((str(p) for p in parsed if p), None) if isinstance(parsed, list) else None
        base = root.rstrip("/").rsplit("/", 1)[-1] if root else None
        out[project_id] = {"name": base or name, "root": root}
    return out


def _tasks(result: dict) -> list[dict]:
    records = ((result.get("tasks") or {}).get("records")) or []
    seen, out = set(), []
    for task in records:
        compact = {"domain": sorted(_list(task.get("domain"))),
                   "task_type": sorted(_list(task.get("task_type")))}
        key = json.dumps(compact, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(compact)
        if len(out) >= 200:
            break
    return out


def _list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v is not None]
    return [str(value)]


def _facts(conn, root_of: dict, roots: list[dict], signals: list[dict], diagnostics: list,
           result: dict | None = None):
    uids = json.dumps(sorted(root_of))
    per_root = defaultdict(lambda: {"readonly_prompts": 0, "tool_failures": 0, "tokens": 0})
    readonly: dict[str, dict] = {}
    failures: dict[tuple, dict] = {}
    edit_roots: set[str] = set()
    any_approval = False
    for head, error_class, status, approval, name, uid in conn.execute(
            f"SELECT command_head, error_class, status, approval, name, session_uid FROM "
            f"tool_call WHERE session_uid IN {UIDS}", (uids,)):
        root = root_of.get(uid, uid)
        if name in EDIT_TOOLS:
            edit_roots.add(root)
        any_approval = any_approval or approval is not None
        matched = readonly_head(head) if approval is not None else None
        if matched:
            entry = readonly.setdefault(matched, {"command_head": matched, "count": 0,
                                                  "sessions": set()})
            entry["count"] += 1
            entry["sessions"].add(root)
            per_root[root]["readonly_prompts"] += 1
        if status in FAILED:
            per_root[root]["tool_failures"] += 1
            if error_class in FAILURE_CLASSES and head:
                _add_failure(failures, software_of(head), error_class, root)
    if not any_approval:
        _guard("permission_event", diagnostics, _permission_prompts, conn, uids, root_of, readonly,
               per_root)
    _guard("failure_class", diagnostics, _classify_failures, conn, uids, root_of, failures)
    usage = {"skill": {}, "mcp": {}}
    for column, key in (("skill", "skill"), ("mcp_server", "mcp")):
        for name, calls, sessions, last in conn.execute(
                f"SELECT {column}, count(*), count(DISTINCT session_uid), max(started_at) FROM "
                f"tool_call WHERE {column} IS NOT NULL AND session_uid IN {UIDS} "
                f"GROUP BY {column}", (uids,)):
            usage[key][name] = {"calls": calls, "sessions": sessions, "last_ts": last}
    model_mix = _model_mix(conn, uids, root_of, edit_roots, per_root, diagnostics)
    agents: dict[str, int] = defaultdict(int)
    try:
        main = json.dumps([r["session_uid"] for r in roots])
        for agent, count in conn.execute(
                f"SELECT src.agent, count(*) FROM session s JOIN source src ON "
                f"src.source_id = s.source_id WHERE s.session_uid IN {UIDS} "
                f"GROUP BY src.agent", (main,)):
            agents[agent] = count
    except Exception as error:  # noqa: BLE001 - facts are optional, never fail the section
        diagnostics.append({"source": "agents", "status": "unavailable", "reason": str(error)})
    problems_by_root = defaultdict(set)
    for signal in signals:
        problem = RULE_PROBLEMS.get(signal.get("rule_id"))
        root = ((signal.get("scope") or {}).get("root_session_uid"))
        if problem and root:
            problems_by_root[root].add(problem)
    sequences = _guard("call_sequence", diagnostics, _call_sequences, conn, uids, root_of) or {}
    task_kinds = _guard("task_types", diagnostics, _task_kinds, conn, uids, root_of, result) or {}
    session_days = []
    for row in sorted(roots, key=lambda r: r.get("started_at") or 0):
        uid = row["session_uid"]
        stats = per_root[uid]
        problems = set(problems_by_root.get(uid, ()))
        if stats["readonly_prompts"]:
            problems.add("permission_friction")
        day = {"session_uid": uid, "started_at": row.get("started_at"),
               "project_id": row.get("project_id"), "problems": sorted(problems), **stats}
        day.update(task_kinds.get(uid) or {})
        session_days.append(day)
    facts = {
        "readonly_prompts": sorted((_sessions(v) for v in readonly.values()),
                                   key=lambda v: -v["count"]),
        "readonly_prompt_sessions": len({r for v in readonly.values() for r in v["sessions"]}),
        "failures_by_software": sorted((_sessions(v) for v in failures.values()
                                        if len(v["sessions"]) >= 2), key=lambda v: -v["count"]),
        "usage": usage, "model_mix": model_mix, "session_days": session_days,
        **_sequence_facts(sequences),
        "compactions": _guard("compactions", diagnostics, _compactions, conn, uids, root_of)
        or _empty_compactions(),
    }
    return facts, dict(agents)


def _sessions(entry: dict) -> dict:
    uids = sorted(entry["sessions"])
    return {**entry, "sessions": len(uids), "session_uids": uids[:MAX_UIDS]}


def _guard(source: str, diagnostics: list, fn, *args):
    """Run one optional fact; schema drift or odd rows become a diagnostic, never a failure."""
    try:
        return fn(*args)
    except Exception as error:  # noqa: BLE001 - facts are optional, never fail the section
        diagnostics.append({"source": source, "status": "unavailable", "reason": str(error)})
        return None


def software_of(head: str | None) -> str | None:
    """First word of a command head, skipping launchers such as ``npx`` or ``uv run``."""
    tokens = (head or "").split()
    for prefix, skip in sorted(WRAPPERS.items(), key=lambda kv: -len(kv[0])):
        if tuple(tokens[:len(prefix)]) == prefix and len(tokens) > skip:
            tokens = tokens[skip:]
            break
    return tokens[0] if tokens else None


def classify_failure(exit_code, text: str | None) -> str | None:
    """Error class from the exit code and the first 2000 characters of the result text."""
    text = (text or "")[:2000]
    if exit_code == 127:
        return "command_not_found"
    for error_class, pattern in ERROR_PATTERNS:
        if pattern.search(text):
            return error_class
    return None


def _add_failure(failures: dict, software: str | None, error_class: str, root: str) -> None:
    if not software:
        return
    entry = failures.setdefault((software, error_class), {
        "software": software, "error_class": error_class, "count": 0, "sessions": set()})
    entry["count"] += 1
    entry["sessions"].add(root)


def _command_text(value) -> str | None:
    """``ext.command`` is an argv array (first 3 tokens) or a plain string."""
    if value is None:
        return None
    if isinstance(value, str) and value.startswith("["):
        try:
            value = json.loads(value)
        except ValueError:
            return value
    if isinstance(value, list):
        return " ".join(str(token) for token in value[:3])
    return str(value)


def _permission_prompts(conn, uids, root_of, readonly, per_root) -> None:
    """Codex keeps approvals as permission.request/decision events, not tool_call.approval."""
    requests, decisions = [], {}
    for uid, kind, call_id, command, decision in conn.execute(
            f"SELECT session_uid, kind, COALESCE(json_extract(ext,'$.call_id'), call_id), "
            f"json_extract(ext,'$.command'), json_extract(ext,'$.decision') FROM event "
            f"WHERE kind IN ('permission.request','permission.decision') AND session_uid IN {UIDS} "
            f"ORDER BY session_uid, seq", (uids,)):
        if kind == "permission.request":
            requests.append((uid, call_id, _command_text(command)))
        elif call_id is not None:
            decisions[(uid, call_id)] = decision
    for uid, call_id, command in requests:
        decision = decisions.get((uid, call_id))
        matched = readonly_head(command)
        if not matched or (decision is not None and str(decision) not in APPROVED):
            continue
        root = root_of.get(uid, uid)
        entry = readonly.setdefault(matched, {"command_head": matched, "count": 0,
                                              "sessions": set(), "source": "permission_event"})
        entry["count"] += 1
        entry["sessions"].add(root)
        per_root[root]["readonly_prompts"] += 1


def _classify_failures(conn, uids, root_of, failures) -> None:
    """Failed calls without ``error_class``: classify from exit code and result text."""
    status_in = ",".join("?" * len(FAILED))
    for uid, head, exit_code, text in conn.execute(
            f"SELECT t.session_uid, t.command_head, t.exit_code, substr(e.text, 1, 2000) FROM "
            f"tool_call t LEFT JOIN event e ON e.event_uid = t.result_event_uid WHERE "
            f"t.error_class IS NULL AND t.status IN ({status_in}) AND t.session_uid IN {UIDS}",
            (*FAILED, uids)):
        error_class = classify_failure(exit_code, text)
        if error_class and head:
            _add_failure(failures, software_of(head), error_class, root_of.get(uid, uid))


def _call_sequences(conn, uids, root_of) -> dict:
    """Per root: ordered (is_edit, head, failed, digest) tuples for sequence facts."""
    by_root: dict[str, list] = defaultdict(list)
    for uid, name, head, status, digest in conn.execute(
            f"SELECT session_uid, name, command_head, status, argument_digest FROM tool_call "
            f"WHERE session_uid IN {UIDS} ORDER BY started_at, rowid", (uids,)):
        head = " ".join(head.split()) if head else None
        by_root[root_of.get(uid, uid)].append((name in EDIT_TOOLS, head, status in FAILED, digest))
    return by_root


def retry_segments(calls: list) -> list[tuple[int, str | None]]:
    """Runs (length >= 2) of consecutive failures with the same digest (or head when absent)."""
    segments, run_key, run_len, run_head = [], None, 0, None
    for _is_edit, head, failed, digest in [*calls, (False, None, False, None)]:
        key = (digest or head) if failed else None
        if key is not None and key == run_key:
            run_len += 1
            continue
        if run_len >= 2:
            segments.append((run_len, run_head))
        run_key, run_len, run_head = key, 1 if key is not None else 0, head
    return segments


def _sequence_facts(by_root: dict) -> dict:
    """retry_runs, unverified_edits and test_failures from ordered tool calls."""
    retry = {"sessions": set(), "segments": 0, "max_len": 0, "examples": []}
    unverified, edit_counts = set(), []
    tests = {"sessions": set(), "count": 0, "commands": set()}
    for root, calls in by_root.items():
        for length, example in retry_segments(calls):
            retry["sessions"].add(root)
            retry["segments"] += 1
            retry["max_len"] = max(retry["max_len"], length)
            if example and example not in retry["examples"] and len(retry["examples"]) < 5:
                retry["examples"].append(example)
        edits = [i for i, call in enumerate(calls) if call[0]]
        if len(edits) >= MIN_UNVERIFIED_EDITS and not any(
                head and VERIFY.match(head) for _, head, _, _ in calls[edits[-1] + 1:]):
            unverified.add(root)
            edit_counts.append(len(edits))
        failing: dict[str, int] = defaultdict(int)
        for _, head, failed, _ in calls:
            if failed and head and VERIFY.match(head):
                failing[head] += 1
        repeated = {head: n for head, n in failing.items() if n >= MIN_TEST_FAILURES}
        if repeated:
            tests["sessions"].add(root)
            tests["count"] += sum(repeated.values())
            tests["commands"].update(repeated)
    edit_counts.sort()
    median = (edit_counts[len(edit_counts) // 2] if len(edit_counts) % 2
              else (edit_counts[len(edit_counts) // 2 - 1] + edit_counts[len(edit_counts) // 2]) / 2
              ) if edit_counts else 0
    return {
        "retry_runs": {"sessions": len(retry["sessions"]), "segments": retry["segments"],
                       "max_len": retry["max_len"],
                       "session_uids": sorted(retry["sessions"])[:MAX_UIDS],
                       "examples": retry["examples"]},
        "unverified_edits": {"sessions": len(unverified), "session_uids": sorted(unverified)[:MAX_UIDS],
                             "edits_median": median},
        "test_failures": {"sessions": len(tests["sessions"]), "count": tests["count"],
                          "session_uids": sorted(tests["sessions"])[:MAX_UIDS],
                          "commands": sorted(tests["commands"])[:5]},
    }


def _empty_compactions() -> dict:
    return {"sessions": 0, "count": 0, "session_uids": [], "followed_by_user": 0}


def _compactions(conn, uids, root_of) -> dict:
    """Auto-compactions per root, and roots where the user kept talking afterwards."""
    first: dict[str, int] = {}
    last_user: dict[str, int] = {}
    counts: dict[str, int] = defaultdict(int)
    for uid, kind, seq in conn.execute(
            f"SELECT session_uid, kind, seq FROM event WHERE kind IN "
            f"('context.compaction','message.user') AND session_uid IN {UIDS}", (uids,)):
        if kind == "context.compaction":
            counts[uid] += 1
            first[uid] = min(first.get(uid, seq), seq)
        else:
            last_user[uid] = max(last_user.get(uid, seq), seq)
    roots: dict[str, int] = defaultdict(int)
    followed = set()
    for uid, count in counts.items():
        root = root_of.get(uid, uid)
        roots[root] += count
        if last_user.get(uid, -1) > first[uid]:
            followed.add(root)
    return {"sessions": len(roots), "count": sum(roots.values()),
            "session_uids": sorted(roots)[:MAX_UIDS], "followed_by_user": len(followed)}


def _top_dir(path: str, cwd: str | None) -> str | None:
    path = str(path).strip()
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        path = path[len(cwd.rstrip("/")) + 1:]
    parts = [part for part in Path(path).parts if part not in ("/", ".", "")]
    if not parts:
        return None
    return parts[0] if len(parts) > 1 else "."


def _record_roots(record: dict, root_of: dict) -> set[str]:
    uids = {record.get("root_session_uid"), record.get("session_uid")}
    uids.update(rel.get("session_uid") for rel in record.get("session_relations") or ()
                if isinstance(rel, dict))
    return {root_of[uid] for uid in uids if uid in root_of}


def _task_kinds(conn, uids, root_of, result) -> dict:
    """Per root: analysis task types when records carry session uids, plus edited top dirs.

    ``tasks`` is the larger of both counts so the mixed-session template can fire on either."""
    types: dict[str, set] = defaultdict(set)
    for record in (((result or {}).get("tasks") or {}).get("records")) or ():
        if isinstance(record, dict):
            for root in _record_roots(record, root_of):
                types[root].update(_list(record.get("task_type")))
    dirs: dict[str, set] = defaultdict(set)
    try:
        rows = conn.execute(
            f"SELECT t.session_uid, t.files, json_extract(e.attrs, '$.input'), s.cwd FROM tool_call t "
            f"LEFT JOIN event e ON e.event_uid = t.call_event_uid "
            f"LEFT JOIN session s ON s.session_uid = t.session_uid "
            f"WHERE t.name IN ({','.join('?' * len(EDIT_TOOLS))}) AND t.session_uid IN {UIDS}",
            (*EDIT_TOOLS, uids)).fetchall()
    except Exception:  # noqa: BLE001 - older stores lack call_event_uid / cwd
        rows = [(uid, files, None, None) for uid, files in conn.execute(
            f"SELECT session_uid, files FROM tool_call WHERE name IN "
            f"({','.join('?' * len(EDIT_TOOLS))}) AND session_uid IN {UIDS}", (*EDIT_TOOLS, uids))]
    for uid, files, patch_input, cwd in rows:
        paths = _json_list(files)
        if not paths and patch_input:
            try:
                parsed = json.loads(patch_input)
            except ValueError:
                parsed = None
            paths = [key for key in parsed if "/" in key or "." in key] if isinstance(parsed, dict) else []
        root = root_of.get(uid, uid)
        for path in paths:
            if isinstance(path, dict):
                path = path.get("path")
            top = _top_dir(path, cwd) if path else None
            if top and len(dirs[root]) < MAX_TASK_DIRS:
                dirs[root].add(top)
    out = {}
    for root in set(types) | set(dirs):
        entry = {"tasks": max(len(types.get(root, ())), len(dirs.get(root, ())))}
        if types.get(root):
            entry["task_types"] = sorted(types[root])
        out[root] = entry
    return out


def _json_list(value) -> list:
    try:
        parsed = json.loads(value) if value else []
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else []


def _model_mix(conn, uids, root_of, edit_roots, per_root, diagnostics) -> list[dict]:
    try:
        rows = conn.execute(
            f"SELECT m.model_id, m.effort_raw, m.session_uid, COALESCE(m.input_tokens,0) + "
            f"COALESCE(m.output_tokens,0) + COALESCE(m.reasoning_tokens,0), src.agent "
            f"FROM model_call m LEFT JOIN session s ON s.session_uid = m.session_uid "
            f"LEFT JOIN source src ON src.source_id = s.source_id "
            f"WHERE m.session_uid IN {UIDS}", (uids,)).fetchall()
    except Exception as error:  # noqa: BLE001 - schema drift degrades to an empty fact
        diagnostics.append({"source": "model_mix", "status": "unavailable", "reason": str(error)})
        return []
    mix: dict[tuple, dict] = {}
    for model_id, effort, uid, tokens, agent in rows:
        root = root_of.get(uid, uid)
        per_root[root]["tokens"] += tokens
        entry = mix.setdefault((model_id, effort, agent), {"model_id": model_id, "effort": effort,
                                                           "agent": agent, "sessions": set(),
                                                           "tokens": 0})
        entry["sessions"].add(root)
        entry["tokens"] += tokens
    return sorted(({"model_id": e["model_id"], "effort": e["effort"], "agent": e["agent"],
                    "sessions": len(e["sessions"]),
                    "readonly_sessions": len(e["sessions"] - edit_roots), "tokens": e["tokens"]}
                   for e in mix.values()), key=lambda e: (-e["tokens"], str(e["agent"])))


# --- KB coverage facts (review loops, parallel conflicts, read-only reviews, repeated
# workflows, late build failures, polling, deploy platform mix). Kept separate from
# ``_facts`` so the per-call scan can evolve without touching the approval/failure facts.

READ_TOOLS = ("Read", "Grep", "Glob", "LS", "NotebookRead")
READ_HEADS = ("cat", "rg", "grep", "head", "tail", "ls", "find", "sed -n", "wc", "less", "tree")
REVIEW_HEADS = ("gh pr view", "gh pr checks", "gh pr review", "gh pr diff")
BUILD_HEADS = ("latexmk", "tsc", "npm run build", "pnpm build", "pnpm run build", "yarn build",
               "cargo build", "xcodebuild", "swift build", "go build", "make")
POLL_HEADS = ("tail", "ls", "cat", "wc")
STATUS_HEADS = (*POLL_HEADS, "ps", "gh run view", "gh run watch", "gh pr checks", "git status",
                "docker ps", "kubectl get")
DEPLOY_HEADS = {"vercel": "vercel", "wrangler": "wrangler", "netlify": "netlify", "fly": "fly",
                "flyctl": "fly", "firebase deploy": "firebase"}
REVIEW_ROUNDS, READONLY_READS, READONLY_MINUTES = 3, 20, 30
WORKFLOW_LEN, WORKFLOW_SESSIONS, BUILD_EDITS, POLL_CHECKS, LONG_MS = 4, 3, 5, 5, 600_000
KB_FACT_KEYS = ("review_loops", "parallel_conflicts", "readonly_reviews", "repeated_workflows",
                "late_build_failures", "polling", "deploy_platforms")


def _prefix(head: str | None, prefixes) -> str | None:
    if not head:
        return None
    head = " ".join(head.split())
    for prefix in sorted(prefixes, key=len, reverse=True):
        if head == prefix or head.startswith(prefix + " "):
            return prefix
    return None


def _files(raw) -> list[str]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    out = []
    for item in value or ():
        path = item.get("path") if isinstance(item, dict) else item
        if isinstance(path, str) and path:
            out.append(path)
    return out


def _calls_by_root(conn, root_of: dict) -> dict[str, list[dict]]:
    uids = json.dumps(sorted(root_of))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tool_call)")}
    pick = ", ".join(c if c in cols else f"NULL AS {c}" for c in (
        "session_uid", "name", "command_head", "status", "files", "started_at", "ended_at",
        "duration_ms"))
    calls: dict[str, list[dict]] = defaultdict(list)
    for uid, name, head, status, files, start, end, duration in conn.execute(
            f"SELECT {pick} FROM tool_call WHERE session_uid IN {UIDS} "
            f"ORDER BY COALESCE(started_at, 0), rowid", (uids,)):
        calls[root_of.get(uid, uid)].append({
            "name": name, "head": " ".join(head.split()) if head else None, "status": status,
            "files": _files(files), "start": start, "end": end or start, "duration": duration})
    return calls


def _is_edit(call: dict) -> bool:
    return call["name"] in EDIT_TOOLS


def _review_rounds(calls: list[dict]) -> int:
    rounds, reviewed = 0, False
    for call in calls:
        head = call["head"] or ""
        if _prefix(head, REVIEW_HEADS) or (head and "review" in head.split()):
            reviewed = True
        elif reviewed and _is_edit(call):
            rounds, reviewed = rounds + 1, False
    return rounds


def _span(calls: list[dict]) -> tuple[int, int] | None:
    starts = [c["start"] for c in calls if c["start"] is not None]
    ends = [c["end"] for c in calls if c["end"] is not None]
    return (min(starts), max(ends)) if starts and ends else None


def _late_build(calls: list[dict]) -> dict | None:
    builds = [i for i, c in enumerate(calls) if _prefix(c["head"], BUILD_HEADS)]
    if not builds:
        return None
    last = builds[-1]
    if calls[last]["status"] not in FAILED:
        return None
    previous = builds[-2] if len(builds) > 1 else -1
    edits = sum(1 for c in calls[previous + 1:last] if _is_edit(c))
    if edits < BUILD_EDITS:
        return None
    return {"build_command": calls[last]["head"], "edits": edits}


def _polls(calls: list[dict]) -> dict | None:
    targets: dict[str, int] = defaultdict(int)
    for call in calls:
        prefix = _prefix(call["head"], POLL_HEADS)
        if prefix:
            target = (call["files"] or [call["head"][len(prefix):].strip() or prefix])[0]
            targets[target] += 1
    best = max(sorted(targets), key=lambda t: targets[t], default=None)
    if best is not None and targets[best] >= POLL_CHECKS:
        return {"target": best, "checks": targets[best]}
    for i, call in enumerate(calls):
        if (call["duration"] or 0) > LONG_MS:
            follow = [c for c in calls[i + 1:i + 11] if _prefix(c["head"], STATUS_HEADS)]
            if len(follow) >= 3:
                return {"target": call["head"] or call["name"], "checks": len(follow)}
    return None


def _ngrams(calls: list[dict]) -> set[tuple]:
    heads: list[str] = []
    for call in calls:
        head = call["head"]
        if head and (not heads or heads[-1] != head):
            heads.append(head)
    grams = set()
    for i in range(len(heads) - WORKFLOW_LEN + 1):
        gram = tuple(heads[i:i + WORKFLOW_LEN])
        if len(set(gram)) >= 2 and any(not readonly_head(h) for h in gram):
            grams.add(gram)
    return grams


def _chain(grams: dict[tuple, set]) -> list[tuple[list, set]]:
    """Frequent n-grams shared by the same sessions and overlapping by n-1 steps become one
    longer sequence (A B C D + B C D E → A … E), so one workflow yields one problem."""
    chains = [[list(g), m] for g, m in sorted(grams.items(), key=lambda kv: (-len(kv[1]), kv[0]))
              if len(m) >= WORKFLOW_SESSIONS]
    overlap = WORKFLOW_LEN - 1
    merged = True
    while merged:
        merged = False
        for x in chains:
            for y in chains:
                if x is not y and x[1] == y[1] and x[0][-overlap:] == y[0][:overlap]:
                    x[0] += y[0][overlap:]
                    chains.remove(y)
                    merged = True
                    break
            if merged:
                break
    return [(seq, members) for seq, members in chains]


def _kb_facts(conn, root_of: dict, roots: list[dict], diagnostics: list) -> dict:
    """Per-root call scans for the KB coverage problems; schema drift yields empty facts."""
    empty = {key: [] for key in KB_FACT_KEYS}
    try:
        calls = _calls_by_root(conn, root_of)
    except Exception as error:  # noqa: BLE001 - facts are optional, never fail the section
        diagnostics.append({"source": "kb_facts", "status": "unavailable", "reason": str(error)})
        return empty
    project_of = {r["session_uid"]: r.get("project_id") for r in roots}
    names = _project_names(conn, {p for p in project_of.values() if p})
    out = empty
    grams: dict[tuple, set] = defaultdict(set)
    deploys: dict[str, dict] = {}
    spans: dict[str, list] = defaultdict(list)
    for root in sorted(calls):
        seq = calls[root]
        rounds = _review_rounds(seq)
        if rounds >= REVIEW_ROUNDS:
            out["review_loops"].append({"session_uid": root, "rounds": rounds})
        edits = sum(1 for c in seq if _is_edit(c))
        reads = sum(1 for c in seq if c["name"] in READ_TOOLS or _prefix(c["head"], READ_HEADS))
        span = _span(seq)
        minutes = (span[1] - span[0]) / 60_000 if span else 0
        if reads >= READONLY_READS and not edits and minutes >= READONLY_MINUTES:
            out["readonly_reviews"].append({"session_uid": root, "reads": reads,
                                            "minutes": round(minutes)})
        if late := _late_build(seq):
            out["late_build_failures"].append({"session_uid": root, "project_id": project_of.get(root),
                                               **late})
        if poll := _polls(seq):
            out["polling"].append({"session_uid": root, **poll})
        for gram in _ngrams(seq):
            grams[gram].add(root)
        project = project_of.get(root)
        if project:
            for c in seq:
                if platform := DEPLOY_HEADS.get(_prefix(c["head"], DEPLOY_HEADS) or ""):
                    entry = deploys.setdefault(project, {"platforms": set(), "sessions": set()})
                    entry["platforms"].add(platform)
                    entry["sessions"].add(root)
            touched = {f for c in seq if _is_edit(c) for f in c["files"]}
            if span and touched:
                spans[project].append((root, span, touched))
    for sequence, members in _chain(grams)[:3]:
        out["repeated_workflows"].append({"sequence": sequence, "sessions": len(members),
                                          "session_uids": sorted(members)[:MAX_UIDS]})
    for project, entry in sorted(deploys.items()):
        if len(entry["platforms"]) >= 2:
            out["deploy_platforms"].append({
                "project_id": project, "project": names.get(project) or project,
                "platforms": sorted(entry["platforms"]), "sessions": len(entry["sessions"]),
                "session_uids": sorted(entry["sessions"])[:MAX_UIDS]})
    for project, rows in sorted(spans.items()):
        rows.sort(key=lambda r: r[1][0])
        for i, (a, (_a0, a1), fa) in enumerate(rows):
            for b, (b0, _b1), fb in rows[i + 1:]:
                if b0 >= a1:
                    break
                if shared := sorted(fa & fb):
                    out["parallel_conflicts"].append({"project_id": project, "a": a, "b": b,
                                                      "files": shared[:5]})
    out["parallel_conflicts"] = out["parallel_conflicts"][:200]
    return out


def _project_names(conn, ids: set) -> dict:
    if not ids:
        return {}
    try:
        rows = conn.execute(f"SELECT project_id, paths FROM project WHERE project_id IN {UIDS}",
                            (json.dumps(sorted(ids)),)).fetchall()
    except Exception:  # noqa: BLE001 - names are cosmetic
        return {}
    names = {}
    for project_id, paths in rows:
        try:
            first = (json.loads(paths) or [None])[0]
        except (ValueError, TypeError):
            first = None
        if isinstance(first, str) and first:
            names[project_id] = first.rstrip("/").rsplit("/", 1)[-1]
    return names


def _linked_item(item: dict) -> dict:
    """features.linked_inventory row → the RecInputs inventory row (extra fields kept)."""
    return {**item, "content_hash": item.get("content_hash"), "lines": item.get("lines"),
            "resident_tokens": (item.get("resident") or {}).get("tokens_est"),
            "catalog_item_id": (item.get("catalog") or {}).get("item_id")}


def _unbound(home) -> bool:
    """The analysis worker has no FeatureService bound (only the gateway binds one); it
    reads the feature layer directly from ``home``, read-only."""
    from .. import features

    return features.current() is None and home is not None and Path(home, "app.db").is_file()


def _linked_readonly(home) -> dict:
    """features.linked_inventory without a bound service: read-only, nothing persisted."""
    from ..features.linked import catalog_rev, compute_linked, open_connection

    conn = open_connection(Path(home))
    try:
        data = conn.execute("SELECT MAX(run_id) FROM t.projection_run").fetchone()[0]
        inventory = conn.execute("SELECT COALESCE(MAX(scan_id), 0) FROM t.inventory_scan"
                                 ).fetchone()[0]
        revs = {"data": data, "inventory": inventory, "catalog": catalog_rev(conn) or "0"}
        return compute_linked(conn, revs=revs, write=None)
    finally:
        conn.close()


def _inventory(conn, diagnostics: list, home=None) -> list[dict] | None:
    try:
        from ..features import linked_inventory
    except ImportError:
        linked_inventory = None
    if linked_inventory is not None and _unbound(home):
        linked_inventory = partial(_linked_readonly, home)
    if linked_inventory is not None:
        try:
            return [_linked_item(item) for item in linked_inventory().get("items") or ()]
        except Exception as error:  # noqa: BLE001 - fall back to the raw scan
            diagnostics.append({"source": "features.linked_inventory", "status": "failed",
                                "reason": str(error)})
    try:
        rows = conn.execute(
            "SELECT i.inv_id, i.type, i.name, i.config_path, i.enabled, i.content_hash, i.config "
            "FROM inventory_item i JOIN (SELECT max(scan_id) AS scan_id FROM inventory_scan "
            "GROUP BY source_key) latest ON latest.scan_id = i.scan_id ORDER BY i.inv_id"
        ).fetchall()
    except Exception as error:  # noqa: BLE001
        diagnostics.append({"source": "inventory", "status": "unavailable", "reason": str(error)})
        return None
    out = []
    for inv_id, type_, name, path, enabled, content_hash, config in rows:
        try:
            parsed = json.loads(config) if config else {}
        except ValueError:
            parsed = {}
        parsed = parsed if isinstance(parsed, dict) else {}
        lines, tokens = parsed.get("lines"), parsed.get("resident_tokens")
        if type_ in ("skill", "rule") and (lines is None or tokens is None):
            measured = file_size(path)
            if measured:
                lines = measured[0] if lines is None else lines
                tokens = measured[1] if tokens is None else tokens
        out.append({"inv_id": inv_id, "type": type_, "name": name, "config_path": path,
                    "enabled": None if enabled is None else bool(enabled),
                    "content_hash": content_hash, "lines": lines,
                    "resident_tokens": tokens, "catalog_item_id": None})
    return out


def file_size(path: str | None) -> tuple[int, int] | None:
    """(lines, ceil(bytes / 3.5)) of a readable text file; contents are never kept."""
    if not path:
        return None
    try:
        target = Path(path).expanduser()
        if not target.is_file() or target.stat().st_size > 5_000_000:
            return None
        data = target.read_bytes()
    except OSError:
        return None
    lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return lines, math.ceil(len(data) / 3.5)


def _profile_readonly(home, scope) -> dict:
    """features.profile without a bound service: built from the materialized session
    features over a read-only hub; nothing is cached or materialized here."""
    from types import SimpleNamespace

    from ..features.hub import QueryHub
    from ..features.profile import build_profile

    hub = QueryHub(Path(home), Path(home, "app.db"), workers=1)
    try:
        return build_profile(SimpleNamespace(hub=hub), scope)
    finally:
        hub.close()


def _profile(scope, diagnostics: list, home=None) -> dict | None:
    try:
        from ..features import profile
    except ImportError:
        return None
    if _unbound(home):
        profile = partial(_profile_readonly, home)
    try:
        return profile(scope)
    except Exception as error:  # noqa: BLE001
        diagnostics.append({"source": "features.profile", "status": "failed",
                            "reason": str(error)})
        return None


def _size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))


def cap(inputs: dict, limit: int = MAX_BYTES) -> dict:
    """Trim the bulky lists until the payload fits ``limit`` bytes."""
    facts = inputs["facts"]
    facts["session_days"] = facts["session_days"][-2000:]
    if _size(inputs) <= limit:
        return inputs
    for signal in inputs["signals"]:
        signal["evidence"] = (signal.get("evidence") or [])[:10]
    for group in ("readonly_prompts", "failures_by_software", "repeated_workflows",
                  "deploy_platforms"):
        for entry in facts[group]:
            entry["session_uids"] = entry["session_uids"][:5]
    for group in KB_FACT_KEYS:
        facts[group] = (facts.get(group) or [])[:50]
    for card in inputs["legacy_cards"]:
        card["evidence"] = (card.get("evidence") or [])[:10]
    for key, keep in (("tasks", 50), ("assessments", 50), ("legacy_cards", 10)):
        if _size(inputs) > limit:
            inputs[key] = inputs[key][:keep]
    while _size(inputs) > limit and len(facts["session_days"]) > 50:
        facts["session_days"] = facts["session_days"][len(facts["session_days"]) // 4:]
    if _size(inputs) > limit:
        inputs["signals"] = inputs["signals"][:100]
    return inputs


register(Section("recommend_inputs", "recommend_inputs", "heavy", compute, False))

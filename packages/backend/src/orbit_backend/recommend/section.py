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
from functools import lru_cache, partial
from pathlib import Path

from orbit_data.command_spec import command_spec

from ..services.sections import Section, register
from .tool_facts import EDIT_KINDS, EDIT_NAMES, is_edit

VERSION = "rec-inputs-v1"
FACTS_VERSION = 2  # Cache revision; the RecInputs wire shape is unchanged.
MAX_BYTES = 200_000
MAX_UIDS = 20
READONLY_HEADS = ("git status", "git diff", "git log", "git show", "ls", "cat", "pwd", "rg",
                  "grep", "find", "head", "tail", "wc", "gh pr view", "gh pr checks",
                  "gh issue view")
FAILURE_CLASSES = ("command_not_found", "missing_dependency", "permission_denied", "timeout",
                   "network")
FAILED = ("failed", "error", "failure")
DECLINED = ("declined", "denied", "rejected", "cancelled", "aborted")
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
# Command heads that only wrap the real command (``/bin/zsh -lc "cd x && git status"``): the
# call's input is re-read and unwrapped so read-only / software facts see the real command.
WRAPPER_HEADS = ("cd", "bash", "sh", "zsh", "/bin/zsh", "/bin/bash", "/bin/sh", "/usr/bin/env", "env",
                 "export", "source", "set", "pushd", "builtin")
SHELLS = {"bash", "sh", "zsh", "dash", "fish"}
PRELUDE = {"cd", "export", "source", ".", "set", "pushd", "popd", "builtin", "true", "unset", "for", "while",
           "until", "if", "elif", "case", "done", "fi", "esac", "function", "{", "}", "echo", "printf", "sleep"}
# Keywords that introduce the real command of their segment (``do git status``, ``time pytest``).
LEADERS = {"do", "then", "else", "time", "nohup", "exec", "command", "!", "sudo"}
SCOPE_TOP = 200
TEXT_DUMPERS = {"cat", "sed", "awk", "head", "tail", "less", "nl", "jq", "echo", "printf", "rg", "grep"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# A call's own input command, only for wrapper heads (a correlated lookup per wrapped row).
_INPUT = ("CASE WHEN t.command_head IN ({wrappers}) OR (t.command_head IS NULL AND t.kind = 'shell') "
          "THEN (SELECT COALESCE(json_extract(e.attrs, '$.input.command'), json_extract(e.attrs, '$.input.cmd')) "
          "FROM event e WHERE e.event_uid = t.call_event_uid) END")


def is_approved(approval) -> bool:
    """Allowed approvals only (approved, approved_for_session, allowed-once, …); denied and
    aborted prompts are a signal against allow-listing, never a read-only prompt to remove."""
    text = str(approval or "").lower().replace("_", "-")
    return text.startswith("approved") or text.startswith("allow") or text in ("accept", "accepted", "yes")




# Shell-ish tokens: quoted strings, operators, or bare words (with embedded quotes). A regex
# scan that stops at the first real command is ~10x faster than shlex on 50k long commands.
_TOKEN = re.compile(r"""(?P<op>&&|\|\||;;|\|&|[;|&\n])|(?P<paren>[()])|(?P<word>(?:[^\s;|&()"'\\]|\\.|"(?:\\.|[^"\\])*"|'[^']*')+)""")
_QUOTED = re.compile(r"""\\(.)|"((?:\\.|[^"\\])*)"|'([^']*)'""")


def _unquote(word: str) -> str:
    return _QUOTED.sub(lambda m: m.group(1) or (m.group(2) or "").replace('\\"', '"') or m.group(3) or "", word)


def _segments(text: str):
    """Shell words grouped by ``&&`` / ``;`` / ``|`` / newlines, lazily (callers stop early)."""
    current: list[str] = []
    for match in _TOKEN.finditer(text):
        if match.group("op"):
            if current:
                yield current
            current = []
        elif match.group("word"):
            current.append(_unquote(match.group("word")))
    if current:
        yield current


def _shell_script(words: list[str]) -> str | None:
    first = words[0].rsplit("/", 1)[-1] if words else ""
    if first in SHELLS and len(words) >= 3 and words[1].startswith("-") and "c" in words[1]:
        return words[2]
    return None


@lru_cache(maxsize=65536)
def _unwrap_text(text: str, depth: int) -> str | None:
    return unwrap_command(text, depth)


def unwrap_command(command, depth: int = 0) -> str | None:
    """The first real command of a shell invocation: drops ``bash -lc`` / ``zsh -c`` wrappers,
    ``cd x &&`` preludes and ``FOO=1`` assignments. None when nothing real is left."""
    if command is None or depth > 3:
        return None
    if isinstance(command, str) and command.startswith("["):
        try:
            command = json.loads(command)
        except ValueError:
            pass
    if isinstance(command, list):
        argv = [str(token) for token in command]
        script = _shell_script(argv)
        if script is not None:
            return unwrap_command(script, depth + 1)
        segments = [argv]
    else:
        segments = _segments(str(command).strip())
    for words in segments:
        script = _shell_script(words)
        if script is not None:
            if inner := unwrap_command(script, depth + 1):
                return inner
            continue
        while words and (_ASSIGN.match(words[0]) or words[0].rsplit("/", 1)[-1] == "env" or words[0] in LEADERS):
            words = words[1:]
        if not words:
            continue
        first = words[0].rsplit("/", 1)[-1]
        if first in PRELUDE or first in SHELLS:
            continue
        # Up to four words: enough for readonly_head prefixes and software_of launchers
        # (``gh pr view``, ``uv run pytest``, ``npx tsc``).
        return " ".join([first, *words[1:4]])
    return None


SHORT = {"git": 2, "uv": 2, "pnpm": 2, "npm": 2, "docker": 2, "yarn": 2, "cargo": 2, "go": 2, "kubectl": 2,
         "gh": 3}


def short_head(head: str | None) -> str | None:
    """The 1–3 word head used for sequences (``git status``, ``gh pr view``, ``pytest``)."""
    words = (head or "").split()
    return " ".join(words[:SHORT.get(words[0], 1)]) if words else None


def _sequence_head(head: str | None, command) -> str | None:
    """Stored heads as they are; an unwrapped command shortened to its 1–3 word head."""
    real = real_head(head, command)
    if real != head:
        return short_head(real)
    return " ".join(head.split()) if head else None


def real_head(head: str | None, command=None) -> str | None:
    """``command_head`` unless it is a wrapper and the input command unwraps to something real."""
    if command is not None and (head is None or head in WRAPPER_HEADS):
        unwrapped = _unwrap_text(command, 0) if isinstance(command, str) else unwrap_command(command)
        return unwrapped or (None if head in WRAPPER_HEADS else head)
    return None if head in WRAPPER_HEADS else head


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
    denied: dict[str, int] = defaultdict(int)
    failures: dict[tuple, dict] = {}
    software_roots: dict[str, set] = defaultdict(set)
    edit_roots: set[str] = set()
    any_approval = False
    # call_uid -> (failed, approved read-only) for the ledger; plain calls stay out
    flags: dict[str, tuple[bool, bool]] = {}
    waits: list[tuple[str, int]] = []
    for head, _error_class, status, approval, name, uid, command, call_uid, kind in _call_rows(conn, uids):
        root = root_of.get(uid, uid)
        head = real_head(head, command)
        if is_edit(name, kind):
            edit_roots.add(root)
        if head and (software := software_of(head)):
            software_roots[software].add(root)
        any_approval = any_approval or approval is not None
        matched = readonly_head(head) if approval is not None else None
        if matched and (not is_approved(approval) or status in DECLINED):
            denied[matched] += 1
        elif matched:
            entry = readonly.setdefault(matched, {"command_head": matched, "count": 0,
                                                  "sessions": set()})
            entry["count"] += 1
            entry["sessions"].add(root)
            per_root[root]["readonly_prompts"] += 1
        if status in FAILED:
            per_root[root]["tool_failures"] += 1
        failed = status in FAILED
        allowed = bool(matched) and is_approved(approval) and status not in DECLINED
        if call_uid is not None and (failed or allowed):
            flags[call_uid] = (failed, allowed)
    if not any_approval:
        _guard("permission_event", diagnostics, _permission_prompts, conn, uids, root_of, readonly,
               per_root, denied, waits)
    for matched, count in denied.items():
        if matched in readonly:
            readonly[matched]["denied"] = count
    unscoped = _guard("failure_class", diagnostics, _classify_failures, conn, uids, root_of, failures) or set()
    # Command-head exposure misses later shell subcommands. Use the whole scope instead
    # of a denominator that counts only some of their attempts (or just their failures).
    for software in unscoped:
        software_roots.pop(software, None)
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
    scope_sessions = {
        "software": _top({k: len(v) for k, v in software_roots.items()}),
        "projects": _top(_tally(r.get("project_id") for r in roots)),
        "task_types": _top(_tally(t for kinds in task_kinds.values() for t in kinds.get("task_types") or ())),
    }
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
        "readonly_denied": dict(sorted(denied.items())),
        "scope_sessions": scope_sessions,
        "failures_by_software": sorted((_sessions(v) for v in failures.values()
                                        if len(v["sessions"]) >= 2), key=lambda v: -v["count"]),
        "usage": usage, "model_mix": model_mix, "session_days": session_days,
        **_sequence_facts(sequences),
        "compactions": _guard("compactions", diagnostics, _compactions, conn, uids, root_of)
        or _empty_compactions(),
        "trajectory": _guard("trajectory", diagnostics, _ledger, conn, uids, root_of, flags, waits),
    }
    return facts, dict(agents)


def _call_rows(conn, uids: str):
    """tool_call rows plus the input command of wrapper heads; older stores without
    ``call_event_uid`` / ``kind`` keep the plain heads."""
    wrappers = ",".join("?" * len(WRAPPER_HEADS))
    try:
        return conn.execute(
            f"SELECT t.command_head, t.error_class, t.status, t.approval, t.name, t.session_uid, "
            f"{_INPUT.format(wrappers=wrappers)}, t.call_uid, t.kind FROM tool_call t WHERE t.session_uid IN {UIDS}",
            (*WRAPPER_HEADS, uids)).fetchall()
    except Exception:  # noqa: BLE001 - schema drift: no unwrapping
        return [(*row[:6], None, row[6], None) for row in conn.execute(
            f"SELECT command_head, error_class, status, approval, name, session_uid, call_uid FROM "
            f"tool_call WHERE session_uid IN {UIDS}", (uids,))]


# --- Trajectory ledger: what the scope's operations cost in tokens and active time, so a card can
# say which share of the whole trajectory its problem occupies (narrate._save). The totals use the
# App's own definitions: tokens as uiview.sessions.TOKENS_SQL (input + cache read / write + output),
# active time as uiview.metrics.active_ms (event gaps of a session tree, each capped at 5 min).
OP_CLASSES = ("call", "failed", "readonly")
LEDGER_TOKENS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _select(cols: set[str], alias: str, names) -> list[str]:
    """``alias.name`` for the columns a store has, ``NULL`` for the ones an older store lacks."""
    return [f"{alias}.{name}" if name in cols else "NULL" for name in names]


def _ledger(conn, uids: str, root_of: dict, flags: dict, waits: list) -> dict:
    """Scope totals (tokens, active ms, human turns, requests) and the measured cost of each
    operation class (every tool call, failed calls, approved read-only prompts). Each session tree's timeline (tool call start / end, request) is walked once:
    a capped gap goes to the calls running or waiting for the model at its start, and a request's
    tokens to the calls whose results it answered, both split evenly. A failed call therefore
    carries its run, the model's reaction and the request that read its error; whatever no call
    holds (user turns, answers) stays only in the totals. Approved read-only prompts carry just
    their recorded approval wait (``approval_wait_ms`` or a permission request→decision gap; the
    call itself still runs after an allow-list), no tokens; prompts without a recorded wait are
    only counted (``ops.readonly.unmeasured``), never priced with the call's run time."""
    from ..uiview.metrics import IDLE_CAP_MS
    from ..uiview.sessions import HUMAN_WHERE

    active: dict[str, int] = defaultdict(int)
    for root, ms in conn.execute(
            "SELECT root, SUM(MIN(COALESCE(gap, 0), ?)) FROM (SELECT s.root_uid AS root, e.ts - LAG(e.ts) "
            "OVER (PARTITION BY s.root_uid ORDER BY e.ts) AS gap FROM event e JOIN session s ON "
            f"s.session_uid = e.session_uid WHERE e.ts IS NOT NULL AND e.session_uid IN {UIDS}) GROUP BY root",
            (IDLE_CAP_MS, uids)):
        active[root_of.get(root, root)] += int(ms or 0)
    turns = sum(n for (n,) in conn.execute(
        f"SELECT count(*) FROM event e WHERE e.session_uid IN {UIDS} AND {HUMAN_WHERE}", (uids,)))
    model_cols = _columns(conn, "model_call")
    tokens_sql = " + ".join(f"COALESCE({col}, 0)" for col in _select(model_cols, "m", LEDGER_TOKENS))
    requests: dict[str, list] = defaultdict(list)
    by_agent: dict[str, int] = defaultdict(int)
    total = 0
    for uid, ts, tokens, agent in conn.execute(
            f"SELECT m.session_uid, {_select(model_cols, 'm', ('ts',))[0]}, {tokens_sql}, src.agent "
            f"FROM model_call m LEFT JOIN session s ON s.session_uid = m.session_uid "
            f"LEFT JOIN source src ON src.source_id = s.source_id WHERE m.session_uid IN {UIDS}", (uids,)):
        total += int(tokens or 0)
        by_agent[agent or "unknown"] += 1
        requests[root_of.get(uid, uid)].append((ts, int(tokens or 0)))
    call_cols = _columns(conn, "tool_call")
    calls: dict[str, list] = defaultdict(list)
    for call_uid, uid, start, end, wait in conn.execute(
            f"SELECT t.call_uid, t.session_uid, "
            f"{', '.join(_select(call_cols, 't', ('started_at', 'ended_at', 'approval_wait_ms')))} "
            f"FROM tool_call t WHERE t.session_uid IN {UIDS}", (uids,)):
        calls[root_of.get(uid, uid)].append((start, end, wait, flags.get(call_uid, (False, False))))
    ops = {name: [0, 0., 0.] for name in OP_CLASSES}  # n, tokens, ms
    unmeasured: dict[str, int] = {}
    for root in set(calls) | set(requests):
        _attribute(calls.get(root, []), requests.get(root, []), IDLE_CAP_MS, ops, unmeasured)
    for _root, wait in waits:
        ops["readonly"][0] += 1
        ops["readonly"][2] += min(max(0, wait), IDLE_CAP_MS)
    return {"tokens": total, "active_ms": sum(active.values()), "turns": turns,
            "requests": sum(by_agent.values()), "requests_by_agent": dict(sorted(by_agent.items())),
            "ops": {name: {"n": n, "tokens": round(tok), "ms": round(ms),
                           **({"unmeasured": unmeasured[name]} if name in unmeasured else {})}
                    for name, (n, tok, ms) in ops.items()}}


def _attribute(calls: list, requests: list, cap: int, ops: dict, unmeasured: dict | None = None) -> None:
    """Add one session tree's per-call tokens and active milliseconds to ``ops`` (see _ledger)."""
    unmeasured = {} if unmeasured is None else unmeasured
    cost = [[0., 0.] for _ in calls]
    points = []
    for i, (start, end, _wait, _flags) in enumerate(calls):
        if start is not None:
            points += [(start, 0, i), (max(start, end if end is not None else start), 1, i)]
    points += [(ts, 2, tokens) for ts, tokens in requests if ts is not None]
    points.sort(key=lambda p: (p[0], p[1]))
    running, waiting, prev = set(), set(), None
    for t, kind, ref in points:
        holders = running | waiting
        if prev is not None and holders and t > prev:
            share = min(t - prev, cap) / len(holders)
            for i in holders:
                cost[i][1] += share
        prev = t
        if kind == 0:
            running.add(ref)
        elif kind == 1:
            running.discard(ref)
            waiting.add(ref)
        elif waiting:
            share = ref / len(waiting)
            for i in waiting:
                cost[i][0] += share
            waiting.clear()
    for (start, end, wait, (failed, readonly)), (tokens, ms) in zip(calls, cost, strict=True):
        for name in ("call", "failed") if failed else ("call",):
            ops[name][0] += 1
            ops[name][1] += tokens
            ops[name][2] += ms
        if readonly:
            # Only a recorded approval wait is a wait: the call's run time is not (R8). Unmeasured
            # prompts are counted apart so the card can say its cost was not measured.
            if wait is not None:
                ops["readonly"][0] += 1
                ops["readonly"][2] += min(max(0, wait), cap)
            else:
                unmeasured["readonly"] = unmeasured.get("readonly", 0) + 1


def _tally(values) -> dict:
    out: dict = defaultdict(int)
    for value in values:
        if value:
            out[value] += 1
    return out


def _top(counts: dict) -> dict:
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[:SCOPE_TOP])


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


def _permission_prompts(conn, uids, root_of, readonly, per_root, denied=None, waits=None) -> None:
    """Codex keeps approvals as permission.request/decision events, not tool_call.approval.
    ``waits`` collects (root, request → decision ms) of the allowed read-only prompts."""
    requests, decisions = [], {}
    for uid, kind, call_id, command, decision, ts in conn.execute(
            f"SELECT session_uid, kind, COALESCE(json_extract(ext,'$.call_id'), call_id), "
            f"json_extract(ext,'$.command'), json_extract(ext,'$.decision'), ts FROM event "
            f"WHERE kind IN ('permission.request','permission.decision') AND session_uid IN {UIDS} "
            f"ORDER BY session_uid, seq", (uids,)):
        if kind == "permission.request":
            requests.append((uid, call_id, _command_text(command), ts))
        elif call_id is not None:
            decisions[(uid, call_id)] = (decision, ts)
    for uid, call_id, command, asked in requests:
        decision, answered = decisions.get((uid, call_id), (None, None))
        matched = readonly_head(real_head(None, command) or command)
        if not matched:
            continue
        if decision is not None and str(decision) not in APPROVED and not is_approved(decision):
            if denied is not None:
                denied[matched] += 1
            continue
        root = root_of.get(uid, uid)
        entry = readonly.setdefault(matched, {"command_head": matched, "count": 0,
                                              "sessions": set(), "source": "permission_event"})
        entry["count"] += 1
        entry["sessions"].add(root)
        per_root[root]["readonly_prompts"] += 1
        if waits is not None and asked is not None and answered is not None:
            waits.append((root, answered - asked))


_MISSING_PROGRAM = re.compile(
    r"^(?:/\S*/)?(?:bash|sh|zsh|dash)(?::(?: line )?\d+)?: "
    r"(?:(?P<before>[/\w.+-]+): (?:command not found|not found)|"
    r"command not found: (?P<after>[/\w.+-]+))\s*$", re.MULTILINE)


def failure_software(head, command, error_class, text) -> str | None:
    """Prefer a shell's explicit diagnostic; ambiguous compound failures stay unassigned.

    Text emitted by cat/grep/etc. is not a shell diagnostic. A full native script
    matters here: command_head is only a vocabulary key, not the failing program.
    """
    software = software_of(head)
    if error_class == "command_not_found" and text and software not in TEXT_DUMPERS:
        found = {((m.group("before") or m.group("after")).rsplit("/", 1)[-1])
                 for m in _MISSING_PROGRAM.finditer(text)}
        if len(found) == 1:
            return next(iter(found))
        if found:
            return None
    if command is not None:
        if isinstance(command, str) and command.startswith("["):
            try:
                command = json.loads(command)
            except ValueError:
                return None
        if isinstance(command, list):
            import shlex

            command = shlex.join(str(word) for word in command)
        spec = command_spec(command)
        if not spec or not spec["command_complete"]:
            return None
    return software


def _classify_failures(conn, uids, root_of, failures) -> set[str]:
    """Classify failed calls once, including native classes; return incomplete exposures."""
    status_in = ",".join("?" * len(FAILED))
    try:
        rows = conn.execute(
            f"SELECT t.session_uid, t.command_head, t.exit_code, substr(e.text, 1, 2000), "
            f"COALESCE(json_extract(c.attrs, '$.input.command'), json_extract(c.attrs, '$.input.cmd')), "
            f"t.error_class FROM tool_call t LEFT JOIN event e ON e.event_uid = t.result_event_uid "
            f"LEFT JOIN event c ON c.event_uid = t.call_event_uid "
            f"WHERE t.status IN ({status_in}) AND t.session_uid IN {UIDS}", (*FAILED, uids)).fetchall()
    except Exception:  # noqa: BLE001 - old stores retain their native classes but lack result/input links
        rows = [(uid, head, None, None, None, cls) for uid, head, cls in conn.execute(
            f"SELECT session_uid, command_head, error_class FROM tool_call "
            f"WHERE status IN ({status_in}) AND session_uid IN {UIDS}", (*FAILED, uids))]
    unscoped = set()
    for uid, head, exit_code, text, command, native_class in rows:
        head = real_head(head, command)
        # read / print commands echo file contents: their text says nothing about the failure
        dumps = bool(readonly_head(head)) or software_of(head) in TEXT_DUMPERS
        error_class = native_class or classify_failure(exit_code, None if dumps else text)
        if error_class not in FAILURE_CLASSES:
            continue
        software = failure_software(head, command, error_class, None if dumps else text)
        if software:
            _add_failure(failures, software, error_class, root_of.get(uid, uid))
            if software != software_of(head):
                unscoped.add(software)
    return unscoped


def _call_sequences(conn, uids, root_of) -> dict:
    """Per root: ordered (is_edit, head, failed, digest) tuples for sequence facts."""
    by_root: dict[str, list] = defaultdict(list)
    wrappers = ",".join("?" * len(WRAPPER_HEADS))
    try:
        rows = conn.execute(
            f"SELECT t.session_uid, t.name, t.command_head, t.status, t.argument_digest, "
            f"{_INPUT.format(wrappers=wrappers)}, t.kind FROM tool_call t "
            f"WHERE t.session_uid IN {UIDS} ORDER BY t.started_at, t.rowid", (*WRAPPER_HEADS, uids)).fetchall()
    except Exception:  # noqa: BLE001 - older stores: plain heads
        rows = [(*row, None, None) for row in conn.execute(
            f"SELECT session_uid, name, command_head, status, argument_digest FROM tool_call "
            f"WHERE session_uid IN {UIDS} ORDER BY started_at, rowid", (uids,))]
    for uid, name, head, status, digest, command, kind in rows:
        head = _sequence_head(head, command)
        by_root[root_of.get(uid, uid)].append((is_edit(name, kind), head, status in FAILED, digest))
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
            f"WHERE (t.kind IN ({','.join('?' * len(EDIT_KINDS))}) OR "
            f"lower(t.name) IN ({','.join('?' * len(EDIT_NAMES))})) AND t.session_uid IN {UIDS}",
            (*EDIT_KINDS, *EDIT_NAMES, uids)).fetchall()
    except Exception:  # noqa: BLE001 - older stores lack call_event_uid / cwd
        rows = [(uid, files, None, None) for uid, files in conn.execute(
            f"SELECT session_uid, files FROM tool_call WHERE lower(name) IN "
            f"({','.join('?' * len(EDIT_NAMES))}) AND session_uid IN {UIDS}", (*EDIT_NAMES, uids))]
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
                    "readonly_sessions": len(e["sessions"] - edit_roots), "tokens": e["tokens"],
                    "readonly_session_uids": sorted(e["sessions"] - edit_roots)[:MAX_UIDS]}
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
        "duration_ms", "kind"))
    calls: dict[str, list[dict]] = defaultdict(list)
    command = (_INPUT.format(wrappers=",".join("?" * len(WRAPPER_HEADS)))
               if {"call_event_uid", "kind"} <= cols else "NULL")
    params = (*WRAPPER_HEADS, uids) if command != "NULL" else (uids,)
    try:
        rows = conn.execute(f"SELECT {pick}, {command} FROM tool_call t WHERE t.session_uid IN {UIDS} "
                            f"ORDER BY COALESCE(t.started_at, 0), t.rowid", params).fetchall()
    except Exception:  # noqa: BLE001 - no event table: plain heads
        rows = [(*row, None) for row in conn.execute(
            f"SELECT {pick} FROM tool_call WHERE session_uid IN {UIDS} "
            f"ORDER BY COALESCE(started_at, 0), rowid", (uids,))]
    for uid, name, head, status, files, start, end, duration, kind, wrapped in rows:
        head = _sequence_head(head, wrapped)
        calls[root_of.get(uid, uid)].append({
            "name": name, "kind": kind, "head": head, "status": status,
            "files": _files(files), "start": start, "end": end or start, "duration": duration})
    return calls


def _is_edit(call: dict) -> bool:
    return is_edit(call["name"], call.get("kind"))


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
            measured = file_size(path, type_)
            if measured:
                lines = measured[0] if lines is None else lines
                tokens = measured[1] if tokens is None else tokens
        out.append({"inv_id": inv_id, "type": type_, "name": name, "config_path": path,
                    "enabled": None if enabled is None else bool(enabled),
                    "content_hash": content_hash, "lines": lines,
                    "resident_tokens": tokens, "catalog_item_id": None})
    return out


def file_size(path: str | None, kind: str = "rule") -> tuple[int, int] | None:
    """(lines, resident tokens) of a readable text file; contents are never kept. A skill only
    keeps ``name`` + ``description`` resident (features.linked.resident_text)."""
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
    if kind == "skill":
        from ..features.linked import estimate_tokens, resident_text
        return lines, estimate_tokens(resident_text("skill", data.decode("utf-8", "ignore")))
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

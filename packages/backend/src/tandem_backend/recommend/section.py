"""``recommend_inputs`` analysis section (runs in the analysis worker, not the gateway).

Reuses the memoised analysis (signals, assessments, tasks, legacy cards) and adds SQL facts
over the selected sessions: read-only command approvals, failures by software, skill/MCP
usage, model mix and one row per main session. The snapshot cache keeps the result, so the
gateway engine only needs these ≤ 200 KB RecInputs, never the 10-second analysis.
"""

from __future__ import annotations

import json
from collections import defaultdict

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


def readonly_head(command_head: str | None) -> str | None:
    if not command_head:
        return None
    head = " ".join(command_head.split())
    for prefix in sorted(READONLY_HEADS, key=len, reverse=True):
        if head == prefix or head.startswith(prefix + " "):
            return prefix
    return None


def compute(store, scope, params, memo) -> dict:
    result = memo.analysis(store, scope, False, params.get("_rev"))
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
        facts, agents = _facts(conn, root_of, roots, signals, diagnostics)
        inventory = _inventory(conn, diagnostics)
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
        "facts": facts, "inventory": inventory, "profile": _profile(scope, diagnostics),
        "legacy_cards": (br.get("recommendations") or [])[:20], "diagnostics": diagnostics,
    }
    return cap(inputs)


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


def _facts(conn, root_of: dict, roots: list[dict], signals: list[dict], diagnostics: list):
    uids = json.dumps(sorted(root_of))
    per_root = defaultdict(lambda: {"readonly_prompts": 0, "tool_failures": 0, "tokens": 0})
    readonly: dict[str, dict] = {}
    failures: dict[tuple, dict] = {}
    edit_roots: set[str] = set()
    for head, error_class, status, approval, name, uid in conn.execute(
            f"SELECT command_head, error_class, status, approval, name, session_uid FROM "
            f"tool_call WHERE session_uid IN {UIDS}", (uids,)):
        root = root_of.get(uid, uid)
        if name in EDIT_TOOLS:
            edit_roots.add(root)
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
                software = head.split()[0]
                entry = failures.setdefault((software, error_class), {
                    "software": software, "error_class": error_class, "count": 0,
                    "sessions": set()})
                entry["count"] += 1
                entry["sessions"].add(root)
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
    session_days = []
    for row in sorted(roots, key=lambda r: r.get("started_at") or 0):
        uid = row["session_uid"]
        stats = per_root[uid]
        problems = set(problems_by_root.get(uid, ()))
        if stats["readonly_prompts"]:
            problems.add("permission_friction")
        session_days.append({"session_uid": uid, "started_at": row.get("started_at"),
                             "project_id": row.get("project_id"), "problems": sorted(problems),
                             **stats})
    facts = {
        "readonly_prompts": sorted((_sessions(v) for v in readonly.values()),
                                   key=lambda v: -v["count"]),
        "readonly_prompt_sessions": len({r for v in readonly.values() for r in v["sessions"]}),
        "failures_by_software": sorted((_sessions(v) for v in failures.values()
                                        if len(v["sessions"]) >= 2), key=lambda v: -v["count"]),
        "usage": usage, "model_mix": model_mix, "session_days": session_days,
    }
    return facts, dict(agents)


def _sessions(entry: dict) -> dict:
    uids = sorted(entry["sessions"])
    return {**entry, "sessions": len(uids), "session_uids": uids[:MAX_UIDS]}


def _model_mix(conn, uids, root_of, edit_roots, per_root, diagnostics) -> list[dict]:
    try:
        rows = conn.execute(
            f"SELECT model_id, effort_raw, session_uid, COALESCE(input_tokens,0) + "
            f"COALESCE(output_tokens,0) + COALESCE(reasoning_tokens,0) FROM model_call "
            f"WHERE session_uid IN {UIDS}", (uids,)).fetchall()
    except Exception as error:  # noqa: BLE001 - schema drift degrades to an empty fact
        diagnostics.append({"source": "model_mix", "status": "unavailable", "reason": str(error)})
        return []
    mix: dict[tuple, dict] = {}
    for model_id, effort, uid, tokens in rows:
        root = root_of.get(uid, uid)
        per_root[root]["tokens"] += tokens
        entry = mix.setdefault((model_id, effort), {"model_id": model_id, "effort": effort,
                                                    "sessions": set(), "tokens": 0})
        entry["sessions"].add(root)
        entry["tokens"] += tokens
    return sorted(({"model_id": e["model_id"], "effort": e["effort"],
                    "sessions": len(e["sessions"]),
                    "readonly_sessions": len(e["sessions"] - edit_roots), "tokens": e["tokens"]}
                   for e in mix.values()), key=lambda e: -e["tokens"])


def _inventory(conn, diagnostics: list) -> list[dict] | None:
    try:
        from ..features import linked_inventory
    except ImportError:
        linked_inventory = None
    if linked_inventory is not None:
        try:
            return list(linked_inventory())
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
        out.append({"inv_id": inv_id, "type": type_, "name": name, "config_path": path,
                    "enabled": None if enabled is None else bool(enabled),
                    "content_hash": content_hash, "lines": parsed.get("lines"),
                    "resident_tokens": parsed.get("resident_tokens"), "catalog_item_id": None})
    return out


def _profile(scope, diagnostics: list) -> dict | None:
    try:
        from ..features import profile
    except ImportError:
        return None
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
    for group in ("readonly_prompts", "failures_by_software"):
        for entry in facts[group]:
            entry["session_uids"] = entry["session_uids"][:5]
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

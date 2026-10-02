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
        facts.update(_kb_facts(conn, root_of, roots, diagnostics))
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


def _inventory(conn, diagnostics: list) -> list[dict] | None:
    try:
        from ..features import linked_inventory
    except ImportError:
        linked_inventory = None
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

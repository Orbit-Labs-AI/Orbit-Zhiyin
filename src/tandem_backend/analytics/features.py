"""Deterministic measurements. Known subsets and unknown totals stay distinct."""

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from zoneinfo import ZoneInfo

from ..analysis import union_duration
from ..privacy import direct_user_text
from .outcome_subjective import analyze_subjective_outcomes


def ratio(a, b):
    return a / b if a is not None and b else None


def quantile(values, q):
    if not values:
        return None
    v = sorted(values)
    pos = (len(v) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def human(e, main_ids):
    return (e["kind"] == "message.user" and e["session_uid"] in main_ids
            and e.get("attrs", {}).get("origin") == "human"
            and e.get("actor") in ("human", "user"))


CORRECTION = re.compile(r"(?:^|[，。！？；,;!\n]\s*)(?:不对(?:[，。！？；,;!\s]|$)|不是我说的|还是不行|我说的是|你理解错了|请?重新|请?改成|wrong\b|not what I meant\b|try again\b|instead\b)", re.I)
CONSTRAINT = re.compile(r"必须|不要|只能|要求|\b(?:must|do not|don't|only|require)\b", re.I)
FILE = re.compile(r"(?<![\w.])(?:[\w@~-]+/)*[\w.-]+\.(py|ts|tsx|js|jsx|tex|md|json|yaml|yml|rs|go|java|cpp|c|h|sh|html|css|ipynb)\b", re.I)
LANG = {"py": "Python", "ipynb": "Python", "ts": "TypeScript", "tsx": "TypeScript",
        "js": "JavaScript", "jsx": "JavaScript", "tex": "LaTeX", "rs": "Rust", "go": "Go",
        "java": "Java", "cpp": "C++", "c": "C", "h": "C/C++", "sh": "Shell",
        "html": "HTML", "css": "CSS", "md": "Markdown", "json": "JSON", "yaml": "YAML", "yml": "YAML"}


def correction_terms(text):
    # Quotes/examples have already been excluded by the existing prompt fence rules.
    text = direct_user_text(text)
    text = re.sub(r'“[^”]*”|"[^"\n]*"|`[^`]*`', '', text)
    return [m.group(0).strip("，。！？；,;! \n") for m in CORRECTION.finditer(text)]


def structure(e):
    text = e.get("text")
    if text is None:
        return None
    attrs = e.get("attrs", {})
    out = {"prompt_char_count": attrs.get("original_chars", len(text)),
           "prompt_line_count": len(text.splitlines()) if text else 0,
           "paragraph_count": len([p for p in re.split(r"\n\s*\n", text) if p.strip()]),
           "question_mark_count": len(re.findall(r"[?？]", text)),
           "bullet_count": len(re.findall(r"(?m)^\s*[-*+]\s+", text)),
           "numbered_list_count": len(re.findall(r"(?m)^\s*\d+[.)、]\s*", text)),
           "code_block_count": None,  # Legacy normalization removed fenced material.
           "url_count": len(re.findall(r"https?://[^\s<>]+", text)),
           "file_reference_count": len(FILE.findall(text)),
           "explicit_format_request_count": len(re.findall(r"(?:请|用|输出为|写成).{0,8}(?:表格|列表|JSON|Markdown|分点)", text, re.I)),
           "explicit_tool_mention_count": len(re.findall(r"(?:使用|调用|用)\s*`?[\w.]*?(?:MCP|工具|skill|pytest|git|bash)\b", text, re.I)),
           "constraint_marker_count": len(CONSTRAINT.findall(text))}
    if "prompt_structure" in attrs:
        out.update(attrs["prompt_structure"])
    out["constraint_density"] = ratio(out["constraint_marker_count"], len(text))
    out["quality"] = "lower_bound" if e.get("text_truncated") else "normalized_text"
    out["event_uid"] = e["event_uid"]
    return out


def text_lengths(events):
    values, exact, unknown = [], 0, 0
    for e in events:
        text, attrs = e.get("text"), e.get("attrs", {})
        n = attrs.get("original_chars")
        if isinstance(n, int) and n >= 0:
            values.append(n)
            exact += 1
        elif text is not None:
            values.append(len(text))
            exact += not e.get("text_truncated", False)
        else:
            unknown += 1
    return {"avg": mean(values) if values else None, "median": median(values) if values else None,
            "effective_n": len(values), "unknown_n": unknown, "exact_n": exact,
            "quality": "lower_bound" if exact < len(values) else "normalized_text"}


def tool_summary(calls, dataset_status="available"):
    if calls is None:
        return {"status": "unavailable", "totals": None, "by_tool": None,
                "effective_n": 0, "unknown_n": None}
    def aggregate(items):
        statuses = Counter()
        durations, intervals = [], []
        sources, qualities = Counter(), Counter()
        for c in items:
            status = c.get("status")
            # Do not let outer success erase a known failing/unknown inner result.
            if c.get("failed_command_results", 0):
                status = "failed"
            elif c.get("unknown_return_values", 0) and status in ("success", "completed"):
                status = None
            if status == "completed":
                status = "success"
            statuses[status if status in ("success", "failed", "rejected", "interrupted", "running") else "unknown"] += 1
            duration = c.get("duration_ms")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration >= 0:
                durations.append(duration)
                sources[c.get("duration_source") or "unknown"] += 1
                qualities[c.get("duration_quality") or "unknown"] += 1
            a, b = c.get("started_at"), c.get("ended_at")
            reliable = c.get("interval_reliable", c.get("duration_source") == "native_bounds")
            if reliable and a is not None and b is not None and b >= a:
                intervals.append((a, b))
        out = {"call_count": len(items), "paired_result_count": sum(bool(c.get("result_event_uid")) for c in items),
               "unpaired_count": sum(not c.get("result_event_uid") for c in items),
               "known_success_count": statuses["success"], "known_failure_count": statuses["failed"],
               **{k + "_count": statuses[k] for k in ("rejected", "interrupted", "running")},
               "unknown_status_count": statuses["unknown"],
               "eligible_status_count": statuses["success"] + statuses["failed"],
               "success_rate": ratio(statuses["success"], statuses["success"] + statuses["failed"]),
               "failure_rate": ratio(statuses["failed"], statuses["success"] + statuses["failed"]),
               "median_duration_ms": quantile(durations, .5), "p25_duration_ms": quantile(durations, .25),
               "p75_duration_ms": quantile(durations, .75), "p90_duration_ms": quantile(durations, .9),
               "duration_sum_ms": sum(durations) if durations else None,
               "reliable_interval_union_ms": union_duration(intervals) if intervals else None,
               "duration_source": dict(sources), "duration_quality": dict(qualities),
               "duration_effective_n": len(durations), "duration_unknown_n": len(items) - len(durations),
               "reliable_interval_n": len(intervals), "interval_unavailable_n": len(items) - len(intervals)}
        if not items and dataset_status != "available":
            for k in out:
                if k.endswith("_count"):
                    out[k] = None
        return out
    groups = defaultdict(list)
    for c in calls:
        groups[(c.get("name_raw"), c.get("kind"))].append(c)
    return {"status": dataset_status, "totals": aggregate(calls), "effective_n": len(calls),
            "unknown_n": sum(c.get("status") is None for c in calls),
            "by_tool": [{"name_raw": name, "kind": kind, **aggregate(v)}
                        for (name, kind), v in sorted(groups.items(), key=lambda p: (-len(p[1]), str(p[0])))]}


STATES = {"message.assistant": "ASSISTANT_MESSAGE", "tool.call": "TOOL_CALL",
          "tool.result": "TOOL_RESULT", "error": "ERROR", "permission.request": "PERMISSION",
          "branch": "BRANCH", "context.compaction": "COMPACTION", "subagent.spawn": "SUBAGENT_SPAWN",
          "subagent.result": "SUBAGENT_RESULT", "turn.interrupted": "INTERRUPTION"}


def workflow(events, calls, main_ids, supported_kinds=None):
    sequences, transitions = defaultdict(list), Counter()
    for e in sorted(events, key=lambda e: (e["session_uid"], e["seq"], e["event_uid"])):
        state = "HUMAN_MESSAGE" if human(e, main_ids) else STATES.get(e["kind"])
        if state:
            sequences[e["session_uid"]].append((state, e["event_uid"]))
    runs, repeated = 0, 0
    for seq in sequences.values():
        edges = [(a[0], b[0]) for a, b in zip(seq, seq[1:], strict=False)]
        transitions.update(edges)
        seen, prev, run = set(), None, 0
        for edge in edges:
            repeated += edge in seen
            seen.add(edge)
            run = run + 1 if edge == prev else 1
            runs, prev = max(runs, run), edge
    totals = Counter()
    for (a, _), n in transitions.items():
        totals[a] += n
    count = sum(transitions.values())
    counts = {}
    for name, kind in (("error_count", "error"), ("branch_count", "branch"),
                       ("compaction_count", "context.compaction"), ("permission_request_count", "permission.request"),
                       ("subagent_spawn_count", "subagent.spawn"), ("interruption_count", "turn.interrupted")):
        counts[name] = sum(e["kind"] == kind for e in events) if supported_kinds is None or kind in supported_kinds else None
    counts["rollback_rewind_count"] = (sum(e["kind"] == "branch" and e.get("attrs", {}).get("action") in ("rollback", "rewind") for e in events)
                                       if supported_kinds is None or "branch" in supported_kinds else None)
    consecutive, same, max_failures, digest_eligible = 0, 0, 0, 0
    by_session = defaultdict(list)
    for c in calls or []:
        by_session[c["session_uid"]].append(c)
    for group in by_session.values():
        previous, run = None, 0
        for c in sorted(group, key=lambda c: (c.get("seq", 0), c["call_uid"])):
            failed = c.get("status") == "failed" or bool(c.get("failed_command_results"))
            run = run + 1 if failed else 0
            max_failures = max(max_failures, run)
            if run > 1:
                consecutive += 1
                eligible = (bool(c.get("argument_digest")) and bool(previous.get("argument_digest"))
                            and bool(c.get("status_scope")) and c.get("status_scope") != "unknown"
                            and c.get("status_scope") == previous.get("status_scope"))
                digest_eligible += eligible
                same += bool(eligible and c["argument_digest"] == previous["argument_digest"]
                             and (c.get("name_raw"), c.get("kind")) == (previous.get("name_raw"), previous.get("kind")))
            previous = c
    return {**counts, "transition_count": count, "repeated_transition_count": repeated,
            "repeated_transition_rate": ratio(repeated, count), "max_repeated_transition_run": runs,
            "transitions": [{"from": a, "to": b, "count": n, "probability": n / totals[a]}
                            for (a, b), n in sorted(transitions.items())],
            "consecutive_failed_calls": consecutive if calls is not None else None,
            "max_consecutive_failure_run": max_failures if calls is not None else None,
            "confirmed_same_argument_failed_retries": same if digest_eligible else None,
            "retry_eligible_pairs": digest_eligible, "sequences": dict(sequences)}


def activity(sessions, events, calls, model_calls, main_ids, scope):
    zone = ZoneInfo(scope.display_timezone)
    def buckets(records):
        day, hour, weekday, unknown = Counter(), Counter(), Counter(), 0
        for ts in records:
            if ts is None:
                unknown += 1
                continue
            if not scope.contains(ts):
                continue
            try:
                dt = datetime.fromtimestamp(ts / 1000, timezone.utc).astimezone(zone)
            except (ValueError, OverflowError, OSError):
                unknown += 1
                continue
            day[dt.date().isoformat()] += 1
            hour[str(dt.hour)] += 1
            weekday[str(dt.isoweekday())] += 1
        return {"by_day": dict(sorted(day.items())), "by_hour": dict(sorted(hour.items(), key=lambda x: int(x[0]))),
                "weekday_distribution": dict(sorted(weekday.items())), "active_days": len(day),
                "effective_n": sum(day.values()), "time_unknown_n": unknown}
    human_rows = [e for e in events if human(e, main_ids)]
    starts = []
    for s in sessions:
        if s["session_uid"] in main_ids:
            times = [e["ts"] for e in events if e["session_uid"] == s["session_uid"] and e.get("ts") is not None]
            starts.append(s.get("started_at") if s.get("started_at") is not None else min(times, default=None))
    hs = buckets([e.get("ts") for e in human_rows])
    return {"time_basis": "reported log timestamps; not continuous work", "sessions": buckets(starts),
            "human_messages": hs, "tool_calls": None if calls is None else buckets([c.get("started_at") for c in calls]),
            "model_requests": None if model_calls is None else buckets([c.get("ts") for c in model_calls]),
            "active_days": hs["active_days"], "hour_distribution": hs["by_hour"],
            "weekday_distribution": hs["weekday_distribution"]}


TOKEN_BUCKETS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")


def token_total(row):
    values = [row.get(k) for k in TOKEN_BUCKETS]
    if all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in values):
        return sum(values)
    return None


def usage(model_calls, events, sessions, scope, records_complete=True):
    valid = [c for c in model_calls or [] if c.get("usage_scope") == "call"
             and c.get("measurement") == "delta" and c.get("call_uid") and c.get("boundary_reliable") is True]
    # Stable canonical call IDs prevent mirrored records from becoming new requests.
    valid = list({c["call_uid"]: c for c in valid}.values())
    snapshots, legacy, regressed_keys = {}, {}, set()
    for e in sorted(events, key=lambda e: (e["session_uid"], e["seq"], e["event_uid"])):
        if e["kind"] != "model.usage":
            continue
        a = e.get("attrs", {})
        if a.get("measurement") == "cumulative":
            key = a.get("snapshot_key")
            if key and a.get("usage_scope") in ("session_snapshot", "session_model_snapshot"):
                previous_total = token_total(snapshots.get(key, {}))
                current_total = token_total(a)
                if previous_total is not None and current_total is not None and current_total < previous_total:
                    regressed_keys.add(key)
                snapshots[key] = {**a, "session_uid": e["session_uid"], "event_uid": e["event_uid"]}
            elif a.get("reported") is not None:
                legacy[e["session_uid"]] = {"event_uid": e["event_uid"], "reported": a["reported"],
                                            "coverage": "unknown", "usage_scope": "unknown"}
    # Cross-scope accumulation is intentionally conservative. Fully covered self
    # calls win; a root_tree snapshot can supply a root total when no time/scene/
    # model subdivision was requested. Never add the two representations.
    roots = {s["session_uid"]: s.get("root_uid") or s["session_uid"] for s in sessions}
    snapshot_totals = []
    unbounded = scope.from_ts is None and scope.until_ts is None and scope.scene is None and scope.model_ids is None and scope.effort_raw is None
    bounded_or_excluded = bool(scope.excluded_session_uids) or not scope.include_children
    for a in snapshots.values():
        value = token_total(a)
        if a["snapshot_key"] not in regressed_keys and value is not None and a.get("coverage") in ("self", "root_tree"):
            snapshot_totals.append({"snapshot_key": a["snapshot_key"], "session_uid": a["session_uid"],
                                    "coverage": a["coverage"], "total_tokens": value,
                                    "event_uid": a["event_uid"]})
    known_calls = [c for c in valid if c.get("coverage") == "self" and token_total(c) is not None]
    full_calls = bool(valid) and records_complete and len(known_calls) == len(valid) == len(model_calls or [])
    total, basis = (sum(token_total(c) for c in valid), "call_delta") if full_calls else (None, None)
    # One tree snapshot is sufficient only if it exactly covers the selected tree.
    if unbounded and not bounded_or_excluded and len(snapshot_totals) == 1:
        a = snapshot_totals[0]
        selected_roots = set(roots.values())
        covered = (a["coverage"] == "root_tree" and selected_roots == {a["session_uid"]}) or (
            a["coverage"] == "self" and set(roots) == {a["session_uid"]})
        if covered:
            if a["coverage"] == "root_tree" or not full_calls:
                total, basis = a["total_tokens"], "cumulative_snapshot"
    costs = [c["cost_usd"] for c in valid if isinstance(c.get("cost_usd"), (int, float))
             and not isinstance(c["cost_usd"], bool) and math.isfinite(c["cost_usd"]) and c["cost_usd"] >= 0
             and c.get("cost_source") and (c["cost_source"] not in ("price_table", "estimate") or c.get("price_table_version"))]
    latency = [c["latency_ms"] for c in valid if c.get("latency_ms") is not None and c["latency_ms"] >= 0]
    ttft = [c["ttft_ms"] for c in valid if c.get("ttft_ms") is not None and c["ttft_ms"] >= 0]
    return {"status": "available" if full_calls else "partial" if valid or snapshots or legacy else "unavailable",
            "request_count": len(valid) if valid or (model_calls == [] and records_complete) else None,
            "invalid_request_rows": len(model_calls or []) - len(valid),
            "total_tokens": total, "total_basis": basis,
            "known_call_tokens": sum(token_total(c) for c in known_calls) if known_calls else None,
            "token_complete_call_n": len(known_calls), "token_unknown_call_n": len(valid) - len(known_calls),
            "token_buckets": {k: sum(c[k] for c in valid) if valid and all(c.get(k) is not None for c in valid) else None for k in TOKEN_BUCKETS},
            "token_bucket_basis": "call_delta_known_rows",
            "cost_usd": sum(costs) if valid and records_complete and len(costs) == len(valid) == len(model_calls or []) else None,
            "cost_effective_n": len(costs), "cost_unknown_n": len(valid) - len(costs),
            "cost_sources": sorted({c["cost_source"] for c in valid if c.get("cost_source")}),
            "price_table_versions": sorted({c["price_table_version"] for c in valid if c.get("price_table_version")}),
            "median_latency_ms": median(latency) if latency else None, "latency_effective_n": len(latency),
            "median_ttft_ms": median(ttft) if ttft else None, "ttft_effective_n": len(ttft),
            "models": dict(Counter(c.get("model_id") or "unknown" for c in valid)) if model_calls is not None else None,
            "cumulative_snapshots": snapshot_totals or None, "legacy_latest_reports": list(legacy.values()) or None,
            "cumulative_regressed_keys": sorted(regressed_keys),
            "cumulative_note": "快照不按日期分摊、不推算请求、不与逐次值相加；旧报告不提供规范总量"}


def session_features(session, events, calls, main_ids, supported_kinds=None, event_status="available"):
    users = [e for e in events if human(e, main_ids)]
    assistants = [e for e in events if e["kind"] == "message.assistant"]
    unknown_humans = sum(e["kind"] == "message.user" and e.get("attrs", {}).get("origin", "unknown") == "unknown" for e in events)
    times = [e["ts"] for e in events if e.get("ts") is not None]
    lengths_u, lengths_a = text_lengths(users), text_lengths(assistants)
    corrections = [{"event_uid": e["event_uid"], "terms": terms} for e in users
                   if (terms := correction_terms(e.get("text") or ""))]
    structures = [s for e in users if (s := structure(e)) is not None]
    languages = Counter(ext.lower() for e in users for ext in FILE.findall(e.get("text") or ""))
    objective = {"explicit_tool_failures": sum(c.get("status") == "failed" for c in calls) if calls is not None else None,
                 "validation_command_candidates": sum(bool(re.search(r"\b(test|pytest|lint|typecheck|build)\b", c.get("command_head") or "")) for c in calls or []),
                 "task_success": None, "validation_scope": None}
    subjective = analyze_subjective_outcomes(events, main_ids, event_status)
    feedback = None if subjective["feedback"] is None else [
        f for f in subjective["feedback"] if f["delivery_event_uid"] is not None]
    main = session["session_uid"] in main_ids
    features = {"user_message_count": len(users) if main and (users or not unknown_humans) else None,
                "assistant_message_count": len(assistants), "turn_count": len({e["turn_uid"] for e in events if e.get("turn_uid")}) or None,
                "total_event_count": len(events), "first_observed_ts": min(times, default=None),
                "last_observed_ts": max(times, default=None),
                "observed_session_span_ms": max(times) - min(times) if times else None,
                "avg_user_message_chars": lengths_u["avg"], "median_user_message_chars": lengths_u["median"],
                "avg_assistant_message_chars": lengths_a["avg"], "median_assistant_message_chars": lengths_a["median"],
                "tool_call_count": len(calls) if calls is not None else None,
                "correction_signal_count": len(corrections) if users else None,
                "correction_signal_rate": ratio(len(corrections), len(users))}
    return {"features": features, "effective_samples": {"human_messages": len(users), "assistant_messages": len(assistants),
                "tools": len(calls) if calls is not None else None},
            "unknown_counts": {"human_origin": unknown_humans, "event_time": len(events) - len(times),
                               "turn_identity": sum(not e.get("turn_uid") for e in events)},
            "text_measurements": {"user": lengths_u, "assistant": lengths_a},
            "workflow": workflow(events, calls, main_ids, supported_kinds), "correction_signals": corrections,
            "correction_denominator": "confirmed human messages in main sessions",
            "prompt_structure": structures, "language_signals": [{"language": LANG[k], "extension": k, "count": n,
                "basis": "human_text_file_extension"} for k, n in languages.most_common()],
            "objective_outcomes": objective, "subjective_outcome_candidates": feedback,
            "subjective_outcomes": subjective,
            "task_success": None, "tool_sequence": calls,
            "human_evidence_ids": [e["event_uid"] for e in users]}

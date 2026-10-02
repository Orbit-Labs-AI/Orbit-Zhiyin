"""Fixed, evidence-backed projections of the existing feature families.

The current extractor observes both autonomy directions, but only the positive
planning/verification pole and no explicit orchestration choice. Its blind spots
are kept in the contract; missing signals never become personality opposites.
"""

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from ..instruction import resolve_instruction_scope
from ..preference import summarize_preferences
from ..task import summarize_task_distribution

PROFILE_VERSION = "collaboration-profile-v2"
MAX_TREND_MONTHS = 12
# An axis score needs this much explicit evidence; below it the axis is "insufficient"
# (same abstain-until-enough-units rule as uiview persona, which uses Wilson intervals).
MIN_TASKS, MIN_SESSIONS = 5, 2
SINGLE_POLE = {"planning", "verification"}
AXES = {
    "delegation": ("控制", "委托", "C", "D"),
    "planning": ("探索", "规划", "E", "P"),
    "verification": ("加速", "验证", "A", "V"),
    "orchestration": ("专精", "编排", "S", "O"),
}
FEATURE_AXES = {
    "requested_autonomy": "delegation", "execution_order": "planning",
    "verification_requirements": "verification",
}
TEXT_MISSING = {"text_unavailable", "no_direct_text", "text_truncated"}


def _month(ts, zone):
    if not isinstance(ts, int) or isinstance(ts, bool):
        return None
    try:
        value = datetime.fromtimestamp(ts / 1000, zone)
        return f"{value.year:04d}-{value.month:02d}"
    except (ValueError, OverflowError, OSError):
        return None


def _evidence(constraint):
    return {key: constraint.get(key) for key in
            ("event_uid", "session_uid", "constraint_uid", "ts", "feature", "value")}


def _unique_evidence(records):
    unique = {(r.get("session_uid"), r.get("event_uid"), r.get("constraint_uid")): r
              for r in records}
    return [unique[key] for key in sorted(unique, key=str)]


def _task_index(tasks):
    records = {task["task_id"]: task for task in tasks}
    by_event = defaultdict(set)
    for task in records.values():
        for uid in task.get("human_evidence_ids", []):
            by_event[uid].add(task["task_id"])
        for boundary in task.get("task_boundaries", []):
            for end in ("start", "end"):
                evidence = boundary.get(end) or {}
                # An exclusive end is the next task's first event, not this task's.
                if end == "end" and not boundary.get("end_inclusive"):
                    continue
                if evidence.get("event_uid"):
                    by_event[evidence["event_uid"]].add(task["task_id"])
    return records, by_event


def _task_states(tasks, instructions):
    """Resolve within each task/session, then allow at most one vote per task."""
    task_map, by_event = _task_index(tasks)
    grouped = defaultdict(list)
    unmapped, seen = 0, set()
    for row in instructions:
        identity = (row["session_uid"], row["event_uid"])
        if identity in seen:
            continue
        seen.add(identity)
        task_ids = by_event.get(row["event_uid"], set())
        if len(task_ids) != 1:
            unmapped += 1
            continue
        task_id = next(iter(task_ids))
        if row["session_uid"] not in task_map[task_id].get("related_session_ids", []):
            unmapped += 1
            continue
        # Instruction's native/legacy task_id differs from Task's derived ID.
        grouped[(task_id, row["session_uid"])].append({**row, "task_id": task_id})

    states = {tid: {"task_id": tid, "observable": False, "session_ids": set(),
                    "candidate_boundary": any(b.get("status") != "explicit"
                                              for b in task.get("task_boundaries", [])),
                    "values": defaultdict(set), "conflicts": set(),
                    "evidence": defaultdict(list), "conditional_n": 0,
                    "active_checks": [], "active_prohibitions": [],
                    "unresolved": set(), "unresolved_evidence": defaultdict(list)}
              for tid, task in task_map.items()}
    for (task_id, sid), rows in grouped.items():
        state = states[task_id]
        usable = [r for r in rows if not TEXT_MISSING.intersection(r.get("unknown_reasons", []))
                  and r.get("status") != "partial"]
        prior_fields = {c["constraint_uid"]: c["feature"] for r in rows for c in r["constraints"]}
        for row in rows:
            if row in usable or not row.get("supersedes_instruction_ids"):
                continue
            # A partial replacement is evidence that the old state may have
            # changed, but cannot establish the replacement's value. Dropping
            # this row would incorrectly resurrect the prior complete request.
            affected = {FEATURE_AXES[prior_fields[uid]] for uid in row["supersedes_instruction_ids"]
                        if uid in prior_fields and prior_fields[uid] in FEATURE_AXES}
            if any(uid not in prior_fields for uid in row["supersedes_instruction_ids"]):
                affected.update(FEATURE_AXES.values())
            state["unresolved"].update(affected)
            for axis in affected:
                state["unresolved_evidence"][axis].append({
                    "event_uid": row["event_uid"], "session_uid": row["session_uid"], "ts": row.get("ts"),
                    "supersedes_instruction_ids": list(row["supersedes_instruction_ids"]),
                    "reason": "replacement_text_not_observable",
                })
        if not usable:
            continue
        state["observable"] = True
        state["session_ids"].add(sid)
        resolved = resolve_instruction_scope(usable, {"session_uid": sid, "task_id": task_id})
        for item in resolved["history"]:
            if item["state"] == "active":
                if item["feature"] == "prohibited_actions":
                    state["active_prohibitions"].append(item)
                elif item["feature"] == "verification_requirements":
                    state["active_checks"].append(item)
            axis = FEATURE_AXES.get(item["feature"])
            if axis is None:
                continue
            if item["state"] == "conditional":
                state["conditional_n"] += 1
            if item["state"] == "conflict":
                state["conflicts"].add(axis)
            if item["state"] in ("active", "conflict"):
                state["evidence"][axis].append(_evidence(item))
            if item["state"] == "active":
                state["values"][axis].add(item["value"])
        if resolved["invalid_replacements"]:
            # Invalid history pointers cannot establish the final instruction state.
            state["conflicts"].update(FEATURE_AXES[c["feature"]] for r in usable
                                      for c in r["constraints"] if c["feature"] in FEATURE_AXES)

    for state in states.values():
        autonomy = state["values"]["delegation"]
        planning = state["values"]["planning"]
        if {"ask_first", "explicit"} <= autonomy:
            state["conflicts"].add("delegation")
        if "execute_first" in planning and planning.intersection({"plan_first", "discuss_first"}):
            state["conflicts"].add("planning")
        for check in state["active_checks"]:
            for prohibition in state["active_prohibitions"]:
                overlapping = (not check.get("targets") or not prohibition.get("targets")
                               or set(check["targets"]).intersection(prohibition["targets"]))
                if check.get("action") and check["action"] == prohibition.get("action") and overlapping:
                    state["conflicts"].add("verification")
                    state["evidence"]["verification"].append(_evidence(prohibition))
        state["scores"] = {
            "delegation": (0.0 if "ask_first" in autonomy else 1.0 if "explicit" in autonomy
                           else 0.5 if "scoped" in autonomy else None),
            "planning": 1.0 if "plan_first" in planning else None,
            "verification": 1.0 if "requested" in state["values"]["verification"] else None,
            "orchestration": None,
        }
        for axis in state["conflicts"] | state["unresolved"]:
            state["scores"][axis] = None
    return list(states.values()), unmapped


def _wilson(k, n, z=1.959963984540054):
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _axes(states, source_available):
    result = {}
    for key, (low, high, low_code, high_code) in AXES.items():
        known = [s for s in states if s["scores"][key] is not None]
        observed = [s for s in states if s["observable"] and key not in s["conflicts"] | s["unresolved"]]
        sessions = {ref["session_uid"] for state in known for ref in state["evidence"][key]}
        mean = sum(s["scores"][key] for s in known) / len(known) if known else None
        reasons = []
        direction = None
        if not source_available:
            reasons.append("instruction_or_task_source_unavailable")
        if key in ("planning", "verification"):
            reasons.append("single_pole_extractor")
        elif key == "orchestration":
            reasons.append("explicit_orchestration_choice_not_extracted")
        if not known:
            reasons.append("no_usable_explicit_axis_evidence")
        if any(key in s["unresolved"] for s in states):
            reasons.append("replacement_text_not_observable")
        enough = len(known) >= MIN_TASKS and len(sessions) >= MIN_SESSIONS
        if not enough:
            reasons.append("requires_five_tasks_and_two_sessions")
        if any(s["candidate_boundary"] for s in known):
            reasons.append("candidate_task_boundaries")
        if key == "delegation" and not reasons:
            direction = low_code if mean < 0.4 else high_code if mean > 0.6 else None
            if direction is None:
                reasons.append("no_clear_direction")
        result[key] = {
            "label": f"{low} / {high}", "low_label": low, "high_label": high,
            "low_code": low_code, "high_code": high_code,
            # Single-pole extractors only ever vote 1.0, so their mean is not a score;
            # signal_rate (with its interval) is the observable quantity there.
            "score": mean if key == "delegation" and enough else None,
            "observed_score": mean if enough and key not in SINGLE_POLE else None,
            "observed_mean": mean, "direction": direction,
            "direction_status": "provisional" if direction else "undetermined",
            "score_basis": "equal_weight_per_task_with_explicit_axis_evidence",
            "signal_rate": len(known) / len(observed) if observed and key != "orchestration" else None,
            "signal_rate_basis": "explicit_rule_hit_tasks / text_observable_nonconflicting_tasks",
            "signal_rate_ci": _wilson(len(known), len(observed))
            if observed and key != "orchestration" else None,
            "minimum": {"tasks": MIN_TASKS, "sessions": MIN_SESSIONS},
            "effective_task_n": len(known), "observable_task_n": len(observed),
            "unknown_task_n": len(states) - len(known), "session_n": len(sessions),
            "conflicting_task_n": sum(key in s["conflicts"] for s in states),
            "unresolved_task_n": sum(key in s["unresolved"] for s in states),
            "status": "unavailable" if not known else "partial" if enough else "insufficient",
            "missing_reasons": reasons,
            "evidence": _unique_evidence([ref for s in known for ref in s["evidence"][key]]),
            "conflict_evidence": _unique_evidence([ref for s in states if key in s["conflicts"]
                                                    for ref in s["evidence"][key]]),
            "unresolved_evidence": _unique_evidence([ref for s in states for ref in s["unresolved_evidence"][key]]),
        }
    return result


def _task_months(task, zone):
    evidence = [b.get("start") for b in task.get("task_boundaries", [])]
    evidence += [e for values in task.get("label_evidence", {}).values()
                 for refs in values.values() for e in refs]
    return {month for ref in evidence if ref for month in [_month(ref.get("ts"), zone)] if month}


def _month_sequence(months, scope, zone):
    bounds = set(months)
    for key, adjustment in (("from_ts", 0), ("until_ts", -1)):
        ts = scope.get(key)
        if isinstance(ts, int) and not isinstance(ts, bool):
            month = _month(ts + adjustment, zone)
            if month:
                bounds.add(month)
    if not bounds:
        return []
    year, month = map(int, min(bounds).split("-"))
    last = max(bounds)
    end_year, end_month = map(int, last.split("-"))
    first_index = year * 12 + month - 1
    last_index = end_year * 12 + end_month - 1
    first_index = max(first_index, last_index - MAX_TREND_MONTHS + 1)
    year, zero_based_month = divmod(first_index, 12)
    month = zero_based_month + 1
    result = []
    while f"{year:04d}-{month:02d}" <= last:
        result.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def _trend(tasks, instructions, scope, zone, source_available):
    rows = defaultdict(list)
    for row in instructions:
        month = _month(row.get("ts"), zone)
        if month:
            rows[month].append(row)
    task_months = {t["task_id"]: _task_months(t, zone) for t in tasks}
    all_months = set(rows) | {m for months in task_months.values() for m in months}
    result = []
    for month in _month_sequence(all_months, scope, zone):
        eids = {r["event_uid"] for r in rows[month]}
        included = [t for t in tasks if month in task_months[t["task_id"]]
                    or eids.intersection(t.get("human_evidence_ids", []))]
        states, unmapped = _task_states(included, rows[month])
        year, number = map(int, month.split("-"))
        start = int(datetime(year, number, 1, tzinfo=zone).timestamp() * 1000)
        end_year, end_month = (year + 1, 1) if number == 12 else (year, number + 1)
        # No valid input timestamp can extend beyond datetime's year 9999.
        end = (int(datetime(end_year, end_month, 1, tzinfo=zone).timestamp() * 1000)
               if end_year <= 9999 else None)
        clipped = (scope.get("from_ts") is not None and scope["from_ts"] > start
                   or end is not None and scope.get("until_ts") is not None and scope["until_ts"] < end)
        result.append({"month": month, "axes": _axes(states, source_available),
                       "task_n": len(states), "unmapped_instruction_n": unmapped,
                       "basis": "only_instruction_observations_in_this_calendar_month",
                       "scope_clipped": bool(clipped)})
    return {"rows": result, "display_timezone": zone.key,
            "max_months": MAX_TREND_MONTHS,
            "earlier_observed_months_omitted": sum(m < result[0]["month"] for m in all_months) if result else 0,
            "unknown_time_instruction_n": sum(_month(r.get("ts"), zone) is None for r in instructions),
            "method": "independent_monthly_reduction_fixed_mapping_no_smoothing",
            "missing_months": "no_evidence_is_null_not_zero"}


def _scatter(tasks, instructions, sessions):
    groups = defaultdict(list)
    for row in instructions:
        groups[row["session_uid"]].append(row)
    points, missing = [], []
    session_ids = sorted({s["session_uid"] for s in sessions} | set(groups))
    for sid in session_ids:
        included = [t for t in tasks if sid in t.get("related_session_ids", [])]
        states, _ = _task_states(included, groups[sid])
        axes = _axes(states, True)
        # Per-session coordinates are observed request metrics, not gated axis scores.
        x, y = axes["delegation"]["observed_mean"], axes["planning"]["signal_rate"]
        if x is None or y is None:
            missing.append(sid)
            continue
        points.append({"session_uid": sid, "x": x, "y": y,
                       "delegation_task_n": axes["delegation"]["effective_task_n"],
                       "planning_hit_task_n": axes["planning"]["effective_task_n"],
                       "planning_observable_task_n": axes["planning"]["observable_task_n"],
                       "axis_details": axes})
    return {"points": points, "missing_session_ids": missing, "missing_n": len(missing),
            "x_axis": {"id": "delegation", "label": "明确授权方式观察值", "range": [0, 1]},
            "y_axis": {"id": "planning_signal_rate", "label": "明确规划要求命中率", "range": [0, 1]},
            "coordinate_basis": "observable_request_metrics_not_personality_embedding",
            "limitations": ["规划零命中不表示探索偏好", "各会话分母及覆盖不同，坐标不是能力或效率"]}


def _preferences(family, scope):
    rows = family.get("records")
    unique = None if rows is None else list({r["preference_id"]: r for r in rows}.values())
    summary = summarize_preferences(unique, scope)
    records = None if unique is None else [{
        key: deepcopy(record.get(key)) for key in
        ("preference_id", "preference_type", "value", "polarity", "preference_scope",
         "effective_at", "operation", "confirmation", "preference_history", "missing_reasons")
    } | {"evidence": [{k: ref.get(k) for k in ("event_uid", "session_uid", "ts")}
                      for ref in record.get("preference_evidence", [])]} for record in unique]
    return {"summary": summary, "records": records,
            "basis": "explicit_observation_history_not_current_global_policy_or_strength",
            "status": "unavailable" if unique is None else "partial" if unique else "no_observations",
            "candidate_n": len(family.get("candidates") or []),
            "limitations": ["不从重复次数推断偏好强度", "范围、撤销和版本仍保留；当前指令优先于历史偏好",
                            "collaboration.act_directly 不是明确探索或委托授权，未用于四轴"]}


def build_profile(analysis: dict) -> dict:
    """Project one already-scoped feature analysis without re-extracting text.

    All scores summarize observed task requests, not a psychological measurement.
    Fixed mappings make months and session coordinates comparable in meaning;
    changes in evidence coverage must still be inspected before comparing values.
    """
    scope = deepcopy(analysis.get("scope") or {})
    zone = ZoneInfo(scope.get("display_timezone", "UTC"))
    task_rows = analysis.get("tasks", {}).get("records")
    instruction_rows = analysis.get("instruction", {}).get("records")
    tasks = list({r["task_id"]: r for r in task_rows or []}.values())
    instructions = instruction_rows or []
    available = task_rows is not None and instruction_rows is not None
    states, unmapped = _task_states(tasks, instructions)
    axes = _axes(states, available)
    code = "".join(a["direction"] for a in axes.values()) if all(a["direction"] for a in axes.values()) else None
    distribution = summarize_task_distribution(tasks if task_rows is not None else None, scope)
    distribution["semantic_status"] = "lexical_candidates_not_confirmed_interest_or_personality"
    direction = axes["delegation"]["direction"]
    headline = (f"已观察到偏{'委托' if direction == 'D' else '控制'}的授权方式；其余协作方向仍需证据。"
                if direction else "先展示有证据的协作习惯；当前数据不足以确定完整四维类型。")
    return {
        "method_version": PROFILE_VERSION, "scope": scope, "axes": axes, "code": code,
        "headline": headline, "task_distribution": distribution,
        "preferences": _preferences(analysis.get("preferences", {}), scope),
        "monthly_trend": _trend(tasks, instructions, scope, zone, available),
        "scatter": _scatter(tasks, instructions, analysis.get("sessions", [])),
        "coverage": {"task_n": len(tasks) if task_rows is not None else None,
                     "instruction_n": len(instructions) if instruction_rows is not None else None,
                     "unmapped_instruction_n": unmapped,
                     "conditional_constraint_n": sum(s["conditional_n"] for s in states),
                     "source": deepcopy(analysis.get("coverage", {}))},
        "rules": {"aggregation": "one_equal_weight_vote_per_task_per_axis",
                  "minimum_tasks": MIN_TASKS, "minimum_sessions": MIN_SESSIONS,
                  "score_gate": "score/observed_score null and status insufficient below the minimum",
                  "direction_thresholds": [0.4, 0.6],
                  "threshold_status": "product_heuristic_not_calibrated_probability",
                  "time_decay": None, "missing": "abstain_never_impute_zero_or_neutral"},
        "limitations": ["四轴为协作行为展示，不是心理学 MBTI 或能力评价",
                        "Instruction 词面规则尚无真实样本的独立质量校准",
                        "P/V 只提取支持侧，O 未提取；不能据此补齐四字码",
                        "明确偏好按原作用范围保留；不复制为所有任务的投票",
                        "任务边界、来源和时间缺失影响趋势与分母；画像不混入错误率或消耗"],
    }

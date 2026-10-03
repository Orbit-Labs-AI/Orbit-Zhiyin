"""Cross-family cards for outcomes, habits over time and descriptive feedback associations."""

from collections import Counter, defaultdict
from typing import Any
from zoneinfo import ZoneInfo

from ..common import human
from ..context import AnalysisContext
from .feedback import calendar_key

Record = dict[str, Any]


def outcome_card(outcome: Record, subjective: Record) -> Record:
    """Keep protocol validation, explicit criteria and human acceptance as separate facts."""
    runs = outcome.get("validation_runs")
    criteria = outcome.get("acceptance_results", [])
    groups = defaultdict(list)
    for run in runs or []:
        for criterion in run.get("criterion_uids", []):
            groups[(run.get("task_uid"), criterion)].append(run)
    histories = []
    for (task, criterion), values in groups.items():
        clocked = all(isinstance(r.get("available_at"), int) for r in values)
        ordered = sorted(values, key=lambda r: (r.get("available_at") or 0, r["validation_uid"]))
        times_unique = len({r.get("available_at") for r in values}) == len(values)
        same_scope = all(
            r.get("validation_scope") == values[0].get("validation_scope") for r in values
        )
        passed = [i for i, r in enumerate(ordered) if r["validation_result"] == "passed"]
        histories.append(
            {
                "task_uid": task,
                "criterion_uid": criterion,
                "attempts_to_first_pass": passed[0] + 1
                if clocked and times_unique and same_scope and passed
                else None,
                "validation_uids": [r["validation_uid"] for r in ordered],
                "order_quality": "reported_time" if clocked and times_unique else "unknown",
            }
        )
    return {
        "validation_status": outcome["status"],
        "observed_runs": len(runs) if runs is not None else None,
        "validation_results": outcome.get("validation_result_counts"),
        "declared_criteria": len(criteria) if criteria else None,
        "acceptance_results": outcome.get("acceptance_counts"),
        "unmatched_or_stale_criteria": [
            r["criterion_uid"] for r in criteria if r.get("missing_reason")
        ],
        "first_pass": histories,
        "task_results": outcome.get("task_results"),
        "human_feedback": subjective.get("counts"),
        "meaning": "tool success, acceptance-set success and user acceptance are separate measures",
    }


def profile_history(context: AnalysisContext, instructions: list[Record]) -> list[Record]:
    """Show monthly observable evidence, using only events in the requested range."""
    zone = ZoneInfo(context.scope.display_timezone)
    rows = defaultdict(
        lambda: {"events": [], "sessions": set(), "planning": set(), "verification": set()}
    )
    by_event = {r["event_uid"]: r for r in instructions}
    for event in context.events:
        if not human(event, context.main_ids):
            continue
        month = calendar_key(event.get("ts"), zone, "month")
        if month is None:
            continue
        row = rows[month]
        row["events"].append(event["event_uid"])
        row["sessions"].add(event["session_uid"])
        instruction = by_event.get(event["event_uid"])
        if instruction:
            for target, field in (
                ("planning", "execution_order"),
                ("verification", "verification_requirements"),
            ):
                if instruction["features"][field]:
                    row[target].add(event["event_uid"])
    return [
        {
            "month": month,
            "human_messages": len(row["events"]),
            "main_sessions": len(row["sessions"]),
            "planning_message_count": len(row["planning"]),
            "verification_request_count": len(row["verification"]),
            "session_uids": sorted(row["sessions"]),
            "type_code": None,
            "scope_note": "current date filter applies; request unbounded dates for complete monthly history",
        }
        for month, row in sorted(rows.items())
    ]


def feedback_associations(feedback: Record, sessions: list[Record]) -> Record:
    """Compare per-session expression balance across observed failure groups, without causal claims."""
    expressions = defaultdict(list)
    for row in feedback.get("messages") or []:
        if row["emotion"] is not None:
            expressions[row["session_uid"]].append(
                {"positive": 1, "negative": -1, "mixed": 0, "neutral": 0}[row["emotion"]]
            )
    groups = {"with_observed_failure": [], "without_observed_failure": []}
    unknown = 0
    for session in sessions:
        values = expressions[session["session_uid"]]
        calls = session["bottleneck_features"]["respond"]["tool_sequence"]
        if not values or calls is None:
            unknown += 1
            continue
        failed = any(c["tool_result_status"] == "failed" for c in calls)
        if not failed and (
            session["bottleneck_features"]["respond"]["status"] != "available"
            or any(c["tool_result_status"] not in ("success", "failed") for c in calls)
        ):
            unknown += 1
            continue
        groups["with_observed_failure" if failed else "without_observed_failure"].append(
            {"session_uid": session["session_uid"], "balance": sum(values) / len(values)}
        )
    means = {
        key: sum(r["balance"] for r in rows) / len(rows) if rows else None
        for key, rows in groups.items()
    }
    enough = all(len(rows) >= 5 for rows in groups.values())
    return {
        "experimental": True,
        "status": "available" if enough else "insufficient_samples",
        "groups": {
            key: {
                "session_n": len(rows),
                "mean_balance": means[key],
                "session_uids": [r["session_uid"] for r in rows],
            }
            for key, rows in groups.items()
        },
        "difference": means["with_observed_failure"] - means["without_observed_failure"]
        if enough
        else None,
        "unknown_session_n": unknown,
        "meaning": "descriptive association; each session has one vote; minimum five per group is a display guard, not significance",
    }


def observed_languages(calls: list[Record] | None) -> Record:
    """Count extensions on recorded file operations, separately from prompt mentions."""
    from pathlib import PurePosixPath

    from ..features import LANG

    if calls is None:
        return {"status": "unavailable", "rows": None, "unknown_call_n": None}
    counts, evidence, unknown = Counter(), defaultdict(list), 0
    for call in calls:
        files = call.get("files")
        if not isinstance(files, list) or not files:
            unknown += 1
            continue
        values = [
            item if isinstance(item, str) else item.get("path")
            for item in files
            if isinstance(item, (str, dict))
        ]
        paths = {value for value in values if isinstance(value, str)}
        measured = False
        for path in sorted(p for p in paths if isinstance(p, str)):
            language = LANG.get(PurePosixPath(path).suffix.lstrip(".").lower())
            if language:
                measured = True
                counts[language] += 1
                if len(evidence[language]) < 50:
                    evidence[language].append(call["call_uid"])
        if not measured:
            unknown += 1
    return {
        "status": "partial" if unknown else "available",
        "unknown_call_n": unknown,
        "rows": [
            {"language": language, "file_operation_count": count, "call_uids": evidence[language]}
            for language, count in counts.most_common()
        ],
        "meaning": "recorded call/file pairs, not repository language composition",
    }


def compare_sessions(product: Record, first: str, second: str) -> Record:
    """Compare two selected sessions with the same units and explicit independent outcomes."""
    lookup = {s["session_uid"]: s for s in product["sessions"]}
    if first not in lookup or second not in lookup:
        raise ValueError("对比会话不在当前筛选范围内")
    rows = []
    for sid in (first, second):
        session = lookup[sid]
        rows.append(
            {
                "session_uid": sid,
                "features": session["features"],
                "usage": session["usage"],
                "duration": session["duration"],
                "outcomes": session["outcomes"],
                "timeline": session["journey"]["lanes"],
            }
        )
    return {
        "scope": product["scope"],
        "sessions": rows,
        "alignment": "relative to each lane's first observed timestamp; seq is the fallback when time is missing",
    }

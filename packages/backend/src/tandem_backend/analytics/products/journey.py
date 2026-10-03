"""Join tasks, instructions, execution and acceptance without inventing task identity."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from ..common import human, reported_task_identity
from ..context import AnalysisContext
from ..instruction import resolve_instruction_scope
from ..preference import resolve_effective_preferences
from ..respond.rules import result_status

Record = dict[str, Any]
EXPLORE = {
    "read",
    "search",
    "web",
    "file_read",
    "file.read",
    "file.search",
    "web.search",
    "web.fetch",
}


@dataclass
class TaskIndex:
    """Selection-wide lookups built once, so each session journey avoids rescanning every
    task and instruction record (formerly O(sessions x tasks x instructions))."""

    spans: dict[str, list]
    native: dict[tuple, Any]
    by_session: dict[str, list[Record]]
    native_records: dict[tuple, list[Record]]
    instruction_positions: dict[str, list[int]]
    instruction_records: list[Record]


def task_index(tasks: list[Record], instruction_records: list[Record]) -> TaskIndex:
    spans, native, by_session = defaultdict(list), {}, defaultdict(list)
    for task in tasks:
        for sid in task["related_session_ids"]:
            if task.get("native_task_id"):
                native[(sid, task["native_task_id"])] = task["task_id"]
        for span in task["task_boundaries"]:
            spans[span["session_uid"]].append((task["task_id"], span))
        for sid in dict.fromkeys(task["related_session_ids"]):
            by_session[sid].append(task)
    native_records, positions = defaultdict(list), defaultdict(list)
    for position, record in enumerate(instruction_records):
        native_records[(record["session_uid"], record.get("task_id"))].append(record)
        positions[record["event_uid"]].append(position)
    return TaskIndex(spans, native, by_session, native_records, positions, instruction_records)


def task_links(
    events: list[Record], tasks: list[Record], index: TaskIndex | None = None
) -> dict[str, Record]:
    """Associate explicit native identities or local candidate boundaries, keeping their basis."""
    index = index or task_index(tasks, [])
    spans, native = index.spans, index.native
    links = {}
    for event in events:
        sid, attrs = event["session_uid"], event.get("attrs", {})
        if event.get("task_uid"):
            links[event["event_uid"]] = {
                "task_id": event["task_uid"],
                "basis": "explicit" if reported_task_identity(event) else "candidate_boundary",
            }
            continue
        declared = (
            attrs.get("task_id")
            if attrs.get("task_id_source") in ("native", "human_confirmed")
            else None
        )
        declared = declared or attrs.get("task_uid")
        if declared is not None:
            task_id = native.get((sid, declared))
            links[event["event_uid"]] = {
                "task_id": task_id,
                "basis": "explicit" if task_id else "unresolved_native_identity",
            }
            continue
        matches = []
        for task_id, span in spans.get(sid, ()):
            start = span["start"]["seq"]
            end = span.get("end")
            before_end = (
                end is None
                or event["seq"] < end["seq"]
                or (span.get("end_inclusive") and event["seq"] == end["seq"])
            )
            if event["seq"] >= start and before_end:
                matches.append(task_id)
        links[event["event_uid"]] = {
            "task_id": matches[0] if len(matches) == 1 else None,
            "basis": "candidate_boundary" if len(matches) == 1 else "unknown",
        }
    return links


def event_phase(event: Record, call: Record | None) -> str:
    """Assign a display phase from explicit actions; phase labels remain candidates."""
    if event["kind"] == "message.user":
        return "request"
    if call:
        if call.get("kind") in EXPLORE:
            return "explore"
        return "execute"
    if event["kind"] == "message.assistant":
        return (
            "deliver"
            if event.get("attrs", {}).get("phase") in ("final", "final_answer")
            else "respond"
        )
    return "unknown"


def observed_state(events: list[Record]) -> Record:
    """Use explicit lifecycle events; a last tool call alone cannot prove a live session."""
    state, evidence_uid = "unknown", None
    for event in events:
        kind, attrs = event["kind"], event.get("attrs", {})
        if kind in ("turn.start", "turn.started"):
            state = "running"
        elif kind == "permission.request":
            state = "waiting"
        elif kind in ("permission.response", "permission.result"):
            state = "running"
        elif kind in ("turn.end", "turn.completed", "turn.interrupted"):
            state = (
                "interrupted"
                if kind == "turn.interrupted" or attrs.get("status") == "interrupted"
                else "failed"
                if attrs.get("status") == "failed"
                else "ended"
                if attrs.get("status") == "completed" or kind == "turn.completed"
                else "unknown"
            )
        else:
            continue
        evidence_uid = event["event_uid"]
    return {
        "state": state,
        "evidence_event_uid": evidence_uid,
        "last_event_ts": events[-1].get("ts") if events else None,
        "meaning": "last observed state, not proof that the process is still alive",
    }


def session_journey(
    context: AnalysisContext,
    row: Record,
    tasks: list[Record],
    instruction_records: list[Record],
    preferences: list[Record] | None,
    index: TaskIndex | None = None,
) -> Record:
    """Build ordered lanes with shared evidence for Lite nodes and Advance playback.

    Pass ``task_index(tasks, instruction_records)`` when building many journeys.
    """
    events = context.members(set(row["included_session_uids"]), "events")
    families = row["bottleneck_features"]
    if events is None:
        return {
            "status": context.event_status,
            "lanes": None,
            "tasks": None,
            "key_moments": None,
            "state": {"state": "unknown"},
            "outcome": families["outcome"],
            "feedback": row["subjective_outcomes"],
        }
    index = index or task_index(tasks, instruction_records)
    links = task_links(events, tasks, index)
    calls = {c.get("call_event_uid"): c for c in families["respond"]["tool_sequence"] or []}
    validation_calls = {r["call_uid"] for r in families["outcome"]["validation_runs"] or []}
    labels = {item["event_uid"]: item for item in families["interaction"]["message_intents"] or []}
    feedback_ids = {item["event_uid"] for item in row["subjective_outcomes"]["feedback"] or []}
    lanes, moments = [], []
    for sid in row["included_session_uids"]:
        lane = []
        for event in context.event_groups.get(sid, []):
            call = calls.get(event["event_uid"])
            item = {
                "event_uid": event["event_uid"],
                "seq": event["seq"],
                "ts": event.get("ts"),
                "turn_uid": event.get("turn_uid"),
                "kind": event["kind"],
                "phase": event_phase(event, call),
                "phase_basis": "rule_candidate",
                **links[event["event_uid"]],
            }
            if call:
                if call["call_uid"] in validation_calls:
                    item["phase"] = "verify"
                item.update(
                    call_uid=call["call_uid"],
                    tool=call.get("name_raw"),
                    tool_state=result_status(call),
                )
            lane.append(item)
            tags = []
            if call and result_status(call) == "failed":
                tags.append("tool_failure")
            if item["phase"] == "verify":
                tags.append("verification")
            if event["event_uid"] in feedback_ids:
                tags.append("user_feedback")
            if event["kind"] in ("permission.request", "context.compaction", "turn.interrupted"):
                tags.append(event["kind"])
            if (
                event["event_uid"] in labels
                and labels[event["event_uid"]].get("state") == "confirmed"
            ):
                tags.append("confirmed_intervention")
            if tags:
                moments.append(
                    {
                        "session_uid": sid,
                        "event_uid": event["event_uid"],
                        "seq": event["seq"],
                        "ts": event.get("ts"),
                        "types": tags,
                    }
                )
        lanes.append({"session_uid": sid, "events": lane})
    task_rows = []
    # Only instruction records whose event is linked here can be candidates; keep their order.
    linked_records = [
        index.instruction_records[p]
        for p in sorted(p for uid in links for p in index.instruction_positions.get(uid, ()))
    ]
    for task in index.by_session.get(row["session_uid"], ()):
        # Inferred boundary links are display-only; do not feed them back as confirmed acceptance IDs.
        records = (
            list(index.native_records.get((row["session_uid"], task["task_id"]), ()))
            if reported_task_identity(task)
            else []
        )
        effective = resolve_instruction_scope(
            records,
            {
                "session_uid": row["session_uid"],
                "task_id": task["task_id"],
            },
            at=context.scope.until_ts - 1 if context.scope.until_ts is not None else None,
        )
        task_rows.append(
            {
                "task_id": task["task_id"],
                "title": task["task_title"],
                "goal": task["task_goal"],
                "effective_instructions": effective,
                "instruction_candidates": [
                    r
                    for r in (instruction_records if task["task_id"] is None else linked_records)
                    if links.get(r["event_uid"], {}).get("task_id") == task["task_id"]
                ],
                "effective_preferences": resolve_effective_preferences(
                    preferences,
                    task,
                    at=context.scope.until_ts - 1 if context.scope.until_ts is not None else None,
                ),
            }
        )
    own = context.event_groups.get(row["session_uid"], [])
    return {
        "status": context.event_status,
        "lanes": lanes,
        "tasks": task_rows,
        "key_moments": moments,
        "task_link_counts": dict(Counter(link["basis"] for link in links.values())),
        "state": observed_state(own),
        "outcome": families["outcome"],
        "feedback": row["subjective_outcomes"],
        "ordering": "native seq within each lane; lanes are not concatenated into one causal sequence",
    }


def interaction_habits(context: AnalysisContext, instructions: list[Record]) -> Record:
    """Expose observable axis evidence without reproducing the demo's arbitrary personality scores."""
    turns = defaultdict(list)
    for event in context.events:
        if event.get("turn_uid") and event["session_uid"] in context.main_ids:
            turns[(event["session_uid"], event["turn_uid"])].append(event)
    autonomy = []
    for (sid, turn), events in turns.items():
        requests = [e for e in events if human(e, context.main_ids)]
        if not requests:
            continue
        calls = {e.get("call_id") or e["event_uid"] for e in events if e["kind"] == "tool.call"}
        finals = [
            e
            for e in events
            if e["kind"] == "message.assistant"
            and e.get("attrs", {}).get("phase") in ("final", "final_answer")
        ]
        autonomy.append(
            {
                "session_uid": sid,
                "turn_uid": turn,
                "human_messages": len(requests),
                "observed_steps": len(calls) + len(finals),
                "event_uids": [e["event_uid"] for e in events],
            }
        )
    return {
        "status": context.event_status,
        "type_code": None,
        "type_status": "uncalibrated",
        "delegation": {
            "turns": autonomy,
            "meaning": "observed steps in a human-containing turn; not autonomy capability",
        },
        "planning": {
            "evidence_event_uids": [
                r["event_uid"] for r in instructions if r["features"]["execution_order"]
            ]
        },
        "verification": {
            "evidence_event_uids": [
                r["event_uid"] for r in instructions if r["features"]["verification_requirements"]
            ]
        },
        "parallelism": {
            "status": "partial",
            "meaning": "execution overlap is measured separately; it does not prove human multitasking",
        },
    }

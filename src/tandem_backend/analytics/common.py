"""Shared observation boundary; feature families must use the same human filter."""

import re
from collections import defaultdict
from heapq import heappop, heappush

from ..privacy import direct_user_text


def human(e, main_ids):
    return (e["kind"] == "message.user" and e["session_uid"] in main_ids
            and e.get("attrs", {}).get("origin") == "human"
            and e.get("actor") in ("human", "user"))


def semantic_messages(events, sessions):
    """Only direct, non-replayed human statements in confirmed main sessions.

    Retain empty/truncated messages for coverage, never restore removed material.
    Inline quotes are conservatively excluded as well as CommonMark block quotes.
    """
    main_ids = {s["session_uid"] for s in sessions if s.get("kind") == "main"}
    seen, out = set(), []
    for e in sorted(events or [], key=lambda e: (e["session_uid"], e["seq"], e["event_uid"])):
        key = (e["session_uid"], e["event_uid"])
        attrs = e.get("attrs", {})
        if not human(e, main_ids) or key in seen or attrs.get("replayed_from") or attrs.get("duplicate_of"):
            continue
        seen.add(key)
        text = direct_user_text(e.get("text") or "")
        text = re.sub(r'“[^”]*”|「[^」]*」|"[^"\n]*"|`[^`\n]*`', '', text)
        out.append({**e, "semantic_text": text.strip()})
    return out


def evidence(event, statement=None):
    return {"event_uid": event["event_uid"], "session_uid": event["session_uid"],
            "seq": event["seq"], "ts": event.get("ts"), "actor": "human",
            "source": "direct_human_message", "statement": statement,
            "time_quality": "reported" if event.get("ts") is not None else "missing"}


def clauses(text):
    return [part.strip() for part in re.split(r"[。！？!?；;\n]+", text) if part.strip()]


def semantic_coverage(events, messages):
    if events is None:
        return {"status": "unavailable", "human_messages": None, "usable_texts": None,
                "unknown_origin": None, "missing_text": None, "truncated_text": None}
    unknown = sum(e["kind"] == "message.user" and e.get("attrs", {}).get("origin", "unknown") == "unknown"
                  for e in events)
    missing = sum(not e["semantic_text"] for e in messages)
    truncated = sum(bool(e.get("text_truncated")) for e in messages)
    return {"status": "partial" if unknown or missing or truncated else "available",
            "human_messages": len(messages), "usable_texts": len(messages) - missing,
            "unknown_origin": unknown, "missing_text": missing, "truncated_text": truncated}


def chronological_messages(messages):
    """Merge clocked sessions without violating any session's native sequence."""
    groups = defaultdict(list)
    for event in messages:
        groups[event["session_uid"]].append(event)
    queue = []
    for sid, items in groups.items():
        items.sort(key=lambda e: (e["seq"], e["event_uid"]))
        ts = items[0].get("ts")
        heappush(queue, (ts if ts is not None else float("inf"), sid, 0))
    result = []
    while queue:
        _, sid, i = heappop(queue)
        result.append(groups[sid][i])
        if i + 1 < len(groups[sid]):
            ts = groups[sid][i + 1].get("ts")
            heappush(queue, (ts if ts is not None else float("inf"), sid, i + 1))
    return result

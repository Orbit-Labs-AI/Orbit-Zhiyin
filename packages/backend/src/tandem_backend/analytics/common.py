"""Shared observation boundary; feature families must use the same human filter."""

import math
import re
from collections import defaultdict
from heapq import heappop, heappush

from ..privacy import direct_user_text


def human(e, main_ids):
    return (e["kind"] == "message.user" and e["session_uid"] in main_ids
            and e.get("attrs", {}).get("origin") == "human"
            and e.get("actor") in ("human", "user"))


FINAL_PHASES = ("final", "final_answer")


def _human_boundary(e):
    return e["kind"] == "message.user" and e.get("attrs", {}).get("origin") == "human"


def final_assistant_uids(events):
    """``(session_uid, event_uid)`` of assistant messages that end a turn (final deliveries).

    Agent-neutral definition: the last non-empty ``message.assistant`` of a turn
    (``turn_uid``), or — when the agent records no turn ids — the last one between two
    adjacent human messages. Only Codex writes ``attrs.phase``; a session that labels any
    assistant message is treated as labelled and only ``final``/``final_answer`` count there
    (``commentary`` and unlabelled messages do not). Replayed/duplicated copies are never
    deliveries.
    """
    by_session = defaultdict(list)
    for e in events or []:
        by_session[e["session_uid"]].append(e)
    finals = set()
    for sid, items in by_session.items():
        items.sort(key=lambda e: (e["seq"], e["event_uid"]))
        last, segment = {}, 0
        labelled = any(e["kind"] == "message.assistant" and e.get("attrs", {}).get("phase") is not None
                       for e in items)
        for e in items:
            if _human_boundary(e):
                segment += 1
                continue
            attrs = e.get("attrs", {})
            if (e["kind"] != "message.assistant" or not e.get("text")
                    or attrs.get("replayed_from") or attrs.get("duplicate_of")):
                continue
            if labelled:
                if attrs.get("phase") in FINAL_PHASES:
                    finals.add((sid, e["event_uid"]))
                continue
            last[e.get("turn_uid") or ("segment", segment)] = e["event_uid"]
        finals.update((sid, uid) for uid in last.values())
    return finals


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
    """Sentence/clause split for zh and en. An English full stop only ends a sentence when
    followed by whitespace or the end, so ``parser.py``, ``v1.2`` and ``3.14`` stay intact."""
    return [part.strip() for part in re.split(r"[。！？!?；;\n]+|\.+(?=\s|$)", text) if part.strip()]


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


def ratio(a, b):
    return a / b if a is not None and b else None


# Tool rates are only reported when explicit outcomes cover at least this share
# of calls whose outcome could have been success or failure. Below it the known
# subset is biased (e.g. only errors carry a status) and a rate would mislead.
MIN_STATUS_COVERAGE = .5


def status_coverage(known, unknown):
    """Share of outcome-eligible calls with an explicit success/failure status."""
    if known is None or unknown is None or known + unknown == 0:
        return None
    return known / (known + unknown)


def covered_ratio(numerator, known, unknown):
    """``numerator / known`` unless the known subset covers too few calls."""
    coverage = status_coverage(known, unknown)
    if coverage is None or coverage < MIN_STATUS_COVERAGE:
        return None
    return ratio(numerator, known)


def quantile(values, q):
    if not values:
        return None
    v = sorted(values)
    pos = (len(v) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def nonnegative_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def timestamp(value):
    """The input contract uses integer UTC milliseconds, never bool or NaN."""
    return isinstance(value, int) and not isinstance(value, bool)


def task_uid(event):
    attrs = event.get("attrs", {})
    return event.get("task_uid") or attrs.get("task_uid") or attrs.get("task_id")


def canonical_task_reference(event):
    """A supplied canonical UID is an explicit reference; projected candidates are not."""
    attrs = event.get("attrs", {})
    uid = event.get("task_uid") or attrs.get("task_uid")
    quality = event.get("task_identity_quality", attrs.get("task_identity_quality"))
    source = event.get("task_relation_source", attrs.get("task_relation_source"))
    return uid if (isinstance(uid, str) and uid and source in (None, "canonical_task_uid")
                   and quality in (None, "explicit", "native", "human_confirmed", "explicit_boundary")) else None


def reported_task_identity(row):
    """Provided canonical identities remain compatible; projected candidates abstain."""
    return row.get("task_identity_quality", "explicit") in (
        "native", "human_confirmed", "explicit_boundary", "explicit")


def annotation_visible(annotation, until_ts=None):
    """Later annotations cannot rewrite an earlier snapshot; unclocked ones abstain."""
    return until_ts is None or (timestamp(annotation.get("available_at"))
                                and annotation["available_at"] < until_ts)

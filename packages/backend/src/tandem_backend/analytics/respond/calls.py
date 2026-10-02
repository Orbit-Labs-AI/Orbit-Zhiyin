"""Pair native call/result events and normalize logical tool calls."""

from collections import Counter, defaultdict
from copy import deepcopy

from ..common import task_uid
from .rules import RESULT_FIELDS


def _detach(value):
    """Copy mutable containers one level; scalars and strings are immutable already.

    Rows are only updated at the top level downstream, so a recursive copy per call
    was pure overhead. Lists/dicts still get their own container so no caller can
    append into the input bundle through a normalized row.
    """
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value


def native_sequence(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def sequence_sort_key(row, identity):
    """Unknown positions sort last for stable output, never establish adjacency."""
    seq = row.get("seq")
    return (row["session_uid"], not native_sequence(seq), seq if native_sequence(seq) else 0,
            row[identity])


def ordered_call_group(group):
    """Abstain for the whole session: dropping a call could bridge unknown neighbors."""
    seqs = [c.get("seq") for c in group]
    if any(not native_sequence(seq) for seq in seqs) or len(set(seqs)) != len(seqs):
        return None
    return sorted(group, key=lambda c: c["seq"])


def project_call_sequence(calls, events):
    """Join canonical calls to selected native call events without expanding scope."""
    by_id, positions = defaultdict(list), Counter()
    for event in events or []:
        attrs = event.get("attrs", {})
        if attrs.get("replayed_from") or attrs.get("duplicate_of"):
            continue
        by_id[(event["session_uid"], event["event_uid"])].append(event)
        if native_sequence(event.get("seq")):
            positions[(event["session_uid"], event["seq"])] += 1
    projected = []
    for original in calls or []:
        call = deepcopy(original)
        matches = by_id.get((call["session_uid"], call.get("call_event_uid")), [])
        reason = "call_event_not_selected"
        seq = None
        if len(matches) > 1:
            reason = "duplicate_event_identity"
        elif matches:
            event = matches[0]
            if event.get("kind") != "tool.call":
                reason = "not_a_call_event"
            elif (call.get("source_id") is not None and event.get("source_id") is not None
                  and call["source_id"] != event["source_id"]):
                reason = "source_identity_conflict"
            elif not native_sequence(event.get("seq")):
                reason = "native_sequence_missing"
            elif positions[(event["session_uid"], event["seq"])] != 1:
                reason = "duplicate_native_sequence"
            elif call.get("pairing_status") == "conflict":
                reason = "call_identity_conflict"
            else:
                seq, reason = event["seq"], None
        call.update(seq=seq, sequence_basis="selected_call_event_native_seq" if seq is not None else None,
                    sequence_unknown_reason=reason)
        projected.append(call)
    # Two logical call identities referencing the same event cannot be ordered.
    call_positions = Counter((c["session_uid"], c["seq"]) for c in projected if c["seq"] is not None)
    for call in projected:
        if call["seq"] is not None and call_positions[(call["session_uid"], call["seq"])] > 1:
            call.update(seq=None, sequence_basis=None, sequence_unknown_reason="duplicate_call_position")
    return sorted(projected, key=lambda c: sequence_sort_key(c, "call_uid"))


def pair_tool_calls(events):
    """Pair L2 records by source/session/native call ID, never by proximity.

    Multiple distinct calls or returns for an ID remain conflicts; exact mirrored
    event IDs are deduplicated. A return preceding its call cannot close it.
    """
    grouped, seen, duplicates = defaultdict(lambda: {"calls": [], "results": []}), {}, []
    event_conflicts = set()
    for e in sorted(events, key=lambda e: sequence_sort_key(e, "event_uid")):
        if e["kind"] not in ("tool.call", "tool.result"):
            continue
        if e.get("attrs", {}).get("replayed_from") or e.get("attrs", {}).get("duplicate_of"):
            continue
        identity = (e.get("source_id"), e["session_uid"], e["event_uid"])
        if identity in seen:
            if e != seen[identity]:
                event_conflicts.add(identity)
            duplicates.append(e["event_uid"])
            continue
        seen[identity] = e
        native = e.get("call_id") or e.get("attrs", {}).get("call_id")
        key = (e.get("source_id"), e["session_uid"], native or ("missing", e["event_uid"]))
        grouped[key]["calls" if e["kind"] == "tool.call" else "results"].append(e)
    calls, orphans, conflicts = [], [], []
    for key, group in grouped.items():
        starts, ends = group["calls"], group["results"]
        conflict = (len(starts) > 1 or len(ends) > 1
                    or any((e.get("source_id"), e["session_uid"], e["event_uid"]) in event_conflicts
                           for e in starts + ends))
        if conflict:
            conflicts.append({"session_uid": key[1], "source_id": key[0],
                              "event_uids": [e["event_uid"] for e in starts + ends]})
        paired = bool(len(starts) == len(ends) == 1 and not conflict
                      and native_sequence(starts[0].get("seq")) and native_sequence(ends[0].get("seq"))
                      and ends[0]["seq"] > starts[0]["seq"])
        if not paired:
            orphans.extend(e["event_uid"] for e in ends)
        for e in starts:
            a = e.get("attrs", {})
            name = a.get("name_raw") or a.get("name")
            row = {"call_uid": e["event_uid"], "session_uid": e["session_uid"], "source_id": key[0],
                   "turn_uid": e.get("turn_uid"), "task_uid": task_uid(e), "seq": e.get("seq"),
                   "call_event_uid": e["event_uid"], "result_event_uid": None,
                   "name_raw": name, "kind": a.get("category", "unknown"),
                   "is_wrapper": a.get("is_wrapper", (name or "").rsplit(".", 1)[-1] in ("exec", "wait")),
                   "status": None, "status_scope": None, "started_at": e.get("ts"), "ended_at": None,
                   "interval_reliable": False, "pairing_status": "conflict" if conflict else "unpaired",
                   **{k: _detach(a[k]) for k in ("argument_digest", "argument_digest_kind", "command_head",
                       "command_complete", "validation", "validation_scope", "retry_of_call_uid", "project_id") if k in a}}
            if paired:
                r = ends[0]
                ra = r.get("attrs", {})
                row.update({k: _detach(ra.get(k)) for k in RESULT_FIELDS})
                row.update(result_event_uid=r["event_uid"], result_available_at=r.get("ts"),
                           result_seq=r["seq"], pairing_status="paired")
                if row["status"] is None and isinstance(ra.get("exit_code"), int) and not isinstance(ra["exit_code"], bool):
                    row["status"] = "success" if ra["exit_code"] == 0 else "failed"
                # Native bounds must be explicit; log timestamps are not execution endpoints.
                if a.get("interval_reliable") is True and ra.get("interval_reliable") is True:
                    row.update(started_at=a.get("started_at"), ended_at=ra.get("ended_at"),
                               interval_reliable=True, duration_source="native_bounds", duration_quality="reported")
            calls.append(row)
    return {"calls": sorted(calls, key=lambda c: sequence_sort_key(c, "call_uid")),
            "orphan_result_event_uids": orphans, "duplicate_event_uids": duplicates, "pairing_conflicts": conflicts}


def normalize_tool_calls(calls):
    """One logical L3 call per identity; conflicting mirrors cannot claim success."""
    rows, duplicates, conflicts = {}, 0, []
    for original in calls or []:
        key = (original["session_uid"], original["call_uid"])
        c = dict(original)
        for k, v in c.items():
            if isinstance(v, (list, dict)):
                c[k] = v.copy()  # same one-level detachment as _detach, without a call per field
        c.setdefault("is_wrapper", (c.get("name_raw") or "").rsplit(".", 1)[-1] in ("exec", "wait"))
        if key in rows:
            duplicates += 1
            if c != rows[key]:
                conflicts.append({"session_uid": key[0], "call_uid": key[1], "reason": "conflicting_call_rows"})
                rows[key].update({k: None for k in RESULT_FIELDS})
                rows[key].update(pairing_status="conflict", result_event_uid=None, interval_reliable=False)
        else:
            rows[key] = c
    return {"calls": sorted(rows.values(), key=lambda c: sequence_sort_key(c, "call_uid")),
            "duplicate_call_rows": duplicates, "call_conflicts": conflicts}

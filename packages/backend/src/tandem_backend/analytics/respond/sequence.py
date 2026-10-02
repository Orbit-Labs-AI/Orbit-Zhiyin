"""Recorded execution transitions, failure evidence and scoped retry links."""

from collections import Counter, defaultdict

from ..common import human, ratio
from .calls import native_sequence, ordered_call_group, sequence_sort_key
from .rules import STATES, result_status


def workflow(events, calls, main_ids, supported_kinds=None):
    sequences, transitions = defaultdict(list), Counter()
    valid_events = [e for e in events if native_sequence(e.get("seq"))]
    ambiguous_sessions = {e["session_uid"] for e in events if not native_sequence(e.get("seq"))}
    positions = Counter((e["session_uid"], e["seq"]) for e in valid_events)
    ambiguous_sessions.update(sid for (sid, _), n in positions.items() if n > 1)
    for e in sorted(valid_events, key=lambda e: sequence_sort_key(e, "event_uid")):
        if e["session_uid"] in ambiguous_sessions:
            continue
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
    unknown_call_sessions = []
    for sid, group in by_session.items():
        ordered = ordered_call_group(group)
        if ordered is None:
            unknown_call_sessions.append(sid)
            continue
        previous, run = None, 0
        for c in ordered:
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
            "consecutive_failed_calls": consecutive if calls is not None and not unknown_call_sessions else None,
            "max_consecutive_failure_run": max_failures if calls is not None and not unknown_call_sessions else None,
            "sequence_unknown_session_uids": sorted(unknown_call_sessions),
            "confirmed_same_argument_failed_retries": same if digest_eligible else None,
            "retry_eligible_pairs": digest_eligible, "sequences": dict(sequences)}


def analyze_execution_sequence(calls):
    """Stricter retry links alongside the compatible v1 workflow counters."""
    groups, retries, failures, unknown_sessions = defaultdict(list), [], [], []
    for c in calls or []:
        groups[c["session_uid"]].append(c)
        status = result_status(c)
        if status in ("failed", "rejected", "interrupted"):
            code = c.get("error_class") or c.get("failure_reason")
            if not code and status in ("rejected", "interrupted"):
                code = status
            failures.append({"call_uid": c["call_uid"], "session_uid": c["session_uid"],
                             "failure_reason": code, "exit_code": c.get("exit_code"),
                             "status_scope": c.get("status_scope"), "source": "explicit_protocol",
                             "evidence_event_uid": c.get("result_event_uid")})
    for sid, group in groups.items():
        ordered = ordered_call_group(group)
        if ordered is None:
            unknown_sessions.append(sid)
            continue
        prior, previous = {}, None
        for c in ordered:
            explicit = c.get("retry_of_call_uid")
            p = prior.get(explicit) if explicit else previous
            if p and result_status(p) == "failed" and (c.get("name_raw"), c.get("kind")) == (p.get("name_raw"), p.get("kind")):
                task_same = bool(c.get("task_uid") and c.get("task_uid") == p.get("task_uid"))
                task_conflict = c.get("task_uid") and p.get("task_uid") and not task_same
                scope_same = bool(c.get("status_scope") not in (None, "unknown")
                                  and c.get("status_scope") == p.get("status_scope"))
                digest_known = bool(c.get("argument_digest") and p.get("argument_digest")
                                    and c.get("argument_digest_kind") not in (None, "unknown")
                                    and c.get("argument_digest_kind") == p.get("argument_digest_kind"))
                same_args = c.get("argument_digest") == p.get("argument_digest") if digest_known else None
                if not task_conflict and (explicit or same_args is not False):
                    confirmed = task_same and scope_same and (bool(explicit) or same_args is True)
                    retries.append({"session_uid": c["session_uid"], "from_call_uid": p["call_uid"],
                                    "to_call_uid": c["call_uid"], "state": "confirmed" if confirmed else "candidate",
                                    "basis": "explicit_link" if explicit else "failed_same_tool_repeat",
                                    "same_arguments": same_args, "status_scope": c.get("status_scope"),
                                    "task_uid": c.get("task_uid"),
                                    "missing": ([] if task_same else ["task_identity"])
                                        + ([] if scope_same else ["status_scope"])
                                        + ([] if explicit or digest_known else ["argument_digest_identity"])})
            prior[c["call_uid"]], previous = c, c
    return {"retry_links": retries if calls is not None else None,
            "retry_sequence_unknown_session_uids": sorted(unknown_sessions),
            "failure_reasons": failures if calls is not None else None,
            "failure_reason_unknown_n": sum(r["failure_reason"] is None for r in failures) if calls is not None else None}

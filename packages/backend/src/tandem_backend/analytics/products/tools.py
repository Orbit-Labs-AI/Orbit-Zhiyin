"""Tool shares, conditional transitions and recovery from the same normalized calls."""

from collections import Counter, defaultdict
from typing import Any

from ..common import covered_ratio
from ..respond.order import ordered_calls as ordered_calls
from ..respond.rules import result_status
from .contracts import metric

Record = dict[str, Any]
EVIDENCE_LIMIT = 50


def _capped_sessions(sessions: set[str]) -> Record:
    """Bounded session evidence; ``session_count`` keeps the exact support."""
    ordered = sorted(sessions)
    return {"session_uids": ordered[:EVIDENCE_LIMIT], "session_count": len(ordered)}


def transition_matrix(runs: list[list[Record]], field: str) -> Record:
    """Estimate P(next tool | current tool) over observed, nonterminal adjacencies."""
    edges, terminals, evidence = Counter(), Counter(), defaultdict(list)
    for run in runs:
        terminals[run[-1].get(field) or "unknown"] += 1
        for current, following in zip(run, run[1:], strict=False):
            key = (current.get(field) or "unknown", following.get(field) or "unknown")
            edges[key] += 1
            ref = {
                "session_uid": current["session_uid"],
                "call_uid": current["call_uid"],
                "next_call_uid": following["call_uid"],
            }
            if len(evidence[key]) < EVIDENCE_LIMIT:
                evidence[key].append(ref)
    outgoing = Counter()
    for (source, _), count in edges.items():
        outgoing[source] += count
    rows = [
        {
            "from": source,
            "to": target,
            "count": count,
            "denominator": outgoing[source],
            "probability": count / outgoing[source],
            "evidence": evidence[(source, target)],
            "evidence_truncated": count > EVIDENCE_LIMIT,
        }
        for (source, target), count in sorted(edges.items())
    ]
    # Per-pair next_calls grew with every adjacency (93 MB on a large home); the capped
    # per-edge evidence above already locates examples, so the default payload omits them.
    return {
        "by": field,
        "rows": rows,
        "pair_count": sum(edges.values()),
        "terminal_counts": dict(sorted(terminals.items())),
        "meaning": "conditional on an observed next call; no edge across sessions or ambiguous order",
    }


def tool_shares(calls: list[Record], field: str, status: str) -> list[Record]:
    """Count each logical call once, retaining unknown labels and outcome states."""
    groups = defaultdict(list)
    for call in calls:
        groups[call.get(field) or "unknown"].append(call)
    result = []
    for name, rows in sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        states = Counter(result_status(c) for c in rows)
        known = states["success"] + states["failed"]
        result.append(
            {
                "name": name,
                "count": len(rows),
                "share": metric(len(rows) / len(calls), "ratio", len(calls), status=status),
                "states": dict(states),
                "success_rate": metric(
                    covered_ratio(states["success"], known, states["unknown"]),
                    "ratio",
                    known,
                    len(rows) - known,
                    status=status,
                ),
                **_capped_sessions({c["session_uid"] for c in rows}),
                "call_uids": [c["call_uid"] for c in rows[:EVIDENCE_LIMIT]],
                "evidence_truncated": len(rows) > EVIDENCE_LIMIT,
            }
        )
    return result


def recovery_chains(respond: Record) -> list[Record]:
    """Join confirmed retry edges; candidates and branched recovery remain explicit."""
    calls = {(c["session_uid"], c["call_uid"]): c for c in respond["tool_sequence"] or []}
    children, parents = defaultdict(list), {}
    for link in respond.get("retry_links") or []:
        if link.get("state") != "confirmed":
            continue
        source = (link["session_uid"], link["from_call_uid"])
        target = (link["session_uid"], link["to_call_uid"])
        children[source].append(target)
        parents[target] = source
    durations = {
        (r["session_uid"], r["call_uid"]): r["duration_ms"]
        for r in respond.get("execution_intervals") or []
    }
    result = []
    for root in sorted(set(children) - set(parents)):
        pending, members, seen = [root], [], set()
        while pending:
            item = pending.pop()
            if item in seen:
                continue
            seen.add(item)
            members.append(item)
            pending.extend(children[item])
        leaves = [item for item in members if not children[item]]
        states = {result_status(calls[item]) for item in leaves if item in calls}
        retry_durations = [durations[item] for item in members[1:] if item in durations]
        result.append(
            {
                "session_uid": root[0],
                "call_uids": [key[1] for key in members],
                "retry_count": len(members) - 1,
                "state": "recovered"
                if states == {"success"}
                else "failed"
                if states == {"failed"}
                else "unknown",
                "retry_execution_ms": metric(
                    sum(retry_durations) if retry_durations else None,
                    "ms",
                    len(retry_durations),
                    len(members) - 1 - len(retry_durations),
                ),
                "terminal_call_uids": [key[1] for key in leaves],
            }
        )
    return result


def workflow_patterns(runs: list[list[Record]]) -> list[Record]:
    """Rank observed three-call patterns by distinct sessions, not repetitions."""
    groups = defaultdict(set)
    for run in runs:
        for index in range(len(run) - 2):
            chain = tuple(c.get("kind") or "unknown" for c in run[index : index + 3])
            groups[chain].add(run[index]["session_uid"])
    eligible = {run[0]["session_uid"] for run in runs if len(run) >= 3}
    return [
        {
            "steps": list(chain),
            "support_sessions": len(sessions),
            "eligible_sessions": len(eligible),
            "support_rate": len(sessions) / len(eligible),
            **_capped_sessions(sessions),
            "denominator": "sessions with at least three unambiguously ordered calls",
        }
        for chain, sessions in sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0]))[
            :20
        ]
    ]


def analyze_tools(respond: Record) -> Record:
    """Compose tool-table and matrix data from the Respond family's canonical sequence."""
    calls, status = respond["tool_sequence"], respond["status"]
    if calls is None:
        return {
            "status": status,
            "call_count": None,
            "by_name": None,
            "by_kind": None,
            "transitions": None,
            "patterns": None,
            "recovery": None,
            "order_unknown_n": None,
        }
    runs, unknown = ordered_calls(calls)
    return {
        "status": status,
        "call_count": len(calls),
        "by_name": tool_shares(calls, "name_raw", status),
        "by_kind": tool_shares(calls, "kind", status),
        "order_unknown_n": unknown,
        "transitions": {
            "name": transition_matrix(runs, "name_raw"),
            "kind": transition_matrix(runs, "kind"),
        },
        "patterns": workflow_patterns(runs),
        "recovery": recovery_chains(respond),
        "failures": respond.get("failure_reasons"),
    }

"""Relational analysis/recommendation checks; each identity retains its own grain."""

import json
import sqlite3
from collections import Counter
from pathlib import Path

from orbit_backend.analytics.common import human
from orbit_backend.analytics.context import AnalysisContext


def validate_result(bundle, scope, analysis, recommendations, *, home=None, fixture_event_uids=()):
    context = AnalysisContext.select(bundle, scope)
    violations = []

    def check(condition, code, **details):
        if not condition:
            violations.append({"code": code, **details})

    events = {(e["session_uid"], e["event_uid"]): e for e in context.events}
    allowed_ids = {e["event_uid"] for e in context.events}
    linked = {
        uid
        for c in context.calls or []
        for uid in (c.get("call_event_uid"), c.get("result_event_uid"))
        if uid
    }
    linked &= {
        e["event_uid"]
        for e in bundle.events or []
        if e["session_uid"] in context.session_map
        and (scope.until_ts is None or e.get("ts") is None or e["ts"] < scope.until_ts)
    }
    allowed_ids |= linked
    selected_sessions = set(context.session_map)
    for event in context.events:
        check(scope.contains(event.get("ts")), "event_outside_window", event_uid=event["event_uid"])
    fixture_ids = set(fixture_event_uids)
    if home is not None:
        db_path = (Path(home) / "orbit.db").resolve()
        with sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True) as db:
            ids = sorted(allowed_ids - fixture_ids)
            native = set(
                row[0]
                for row in db.execute(
                    "SELECT e.event_uid FROM event e WHERE e.event_uid IN (SELECT value FROM json_each(?)) "
                    "AND EXISTS (SELECT 1 FROM record_event re WHERE re.event_uid=e.event_uid)",
                    (json.dumps(ids),),
                )
            )
        check(
            native == set(ids),
            "canonical_event_provenance_gap",
            missing_event_uids=sorted(set(ids) - native)[:20],
        )

    features = analysis.get("bottleneck_features") or {}
    interaction = features.get("interaction") or {}
    rows = interaction.get("message_intents")
    if rows is not None:
        check(
            len({(r["session_uid"], r["event_uid"]) for r in rows}) == len(rows),
            "duplicate_intent_identity",
        )
        for row in rows:
            event = events.get((row["session_uid"], row["event_uid"]))
            check(
                event is not None and human(event, context.main_ids),
                "intent_is_not_selected_main_human",
                event_uid=row["event_uid"],
            )
        observed = sum(human(e, context.main_ids) for e in context.events)
        check(
            (interaction.get("effective_samples") or {}).get("human_messages") == observed,
            "human_denominator_mismatch",
            expected=observed,
        )

    calls = {(c["session_uid"], c["call_uid"]): c for c in context.calls or []}
    models = {(c["session_uid"], c["call_uid"]): c for c in context.model_calls or []}
    validations = {
        (v["session_uid"], v["validation_uid"]): v
        for v in (features.get("outcome") or {}).get("validation_runs") or []
    }
    criteria = {
        (r["session_uid"], r["criterion_uid"])
        for r in (features.get("outcome") or {}).get("acceptance_results") or []
    }
    graph = analysis.get("work_graph") or {}
    nodes = {n["node_uid"]: n for n in graph.get("nodes", [])}
    check(len(nodes) == len(graph.get("nodes", [])), "duplicate_graph_node")
    for row in [*nodes.values(), *graph.get("edges", [])]:
        if row.get("available_at") is not None and scope.until_ts is not None:
            check(
                row["available_at"] < scope.until_ts,
                "future_graph_availability",
                uid=row.get("node_uid", row.get("edge_uid")),
            )
        if row.get("coverage", {}).get("status") == "available":
            check(
                set(row.get("evidence_uids", [])) <= allowed_ids,
                "graph_evidence_outside_selection",
                uid=row.get("node_uid", row.get("edge_uid")),
            )
    for edge in graph.get("edges", []):
        check(
            edge["from_node_uid"] in nodes and edge["to_node_uid"] in nodes,
            "dangling_graph_edge",
            edge_uid=edge["edge_uid"],
        )
    memberships = {
        (edge["from_node_uid"], edge["to_node_uid"])
        for edge in graph.get("edges", [])
        if edge["kind"] == "BELONGS_TO_TASK"
    }
    for trajectory in graph.get("task_trajectories", []):
        check(trajectory["task_node_uid"] in nodes, "trajectory_task_absent")
        for kind, member_ids in trajectory["members"].items():
            for uid in member_ids:
                check(
                    uid in nodes
                    and nodes[uid]["kind"] == kind
                    and (uid, trajectory["task_node_uid"]) in memberships
                    and (
                        nodes[uid].get("task_uid") is None
                        or kind in ("Turn", "Artifact", "ArtifactVersion")
                        or nodes[uid]["task_uid"] == trajectory["task_uid"]
                    ),
                    "trajectory_member_misattributed",
                    node_uid=uid,
                )

    def reference(ref):
        key = (ref.get("session_uid"), ref.get("id"))
        check(key[0] in selected_sessions, "recommendation_session_outside_scope", reference=ref)
        kind = ref.get("kind")
        if kind == "event":
            check(key in events, "recommendation_event_unselected", reference=ref)
        elif kind in ("call", "tool_call"):
            check(key in calls, "recommendation_call_unselected", reference=ref)
        elif kind == "model_call":
            check(key in models, "recommendation_model_unselected", reference=ref)
        elif kind == "validation":
            check(key in validations, "recommendation_validation_unselected", reference=ref)
        elif kind == "criterion":
            check(key in criteria, "recommendation_criterion_unselected", reference=ref)
        else:
            check(False, "unknown_recommendation_evidence_kind", reference=ref)

    signals = {s["signal_id"]: s for s in recommendations.get("signals", [])}
    for signal in signals.values():
        check(bool(signal["evidence"]), "signal_without_evidence", signal_id=signal["signal_id"])
        included = set(signal["scope"]["included_session_uids"])
        check(included <= selected_sessions, "signal_scope_outside_selection")
        for ref in signal["evidence"]:
            reference(ref)
            check(ref["session_uid"] in included, "signal_evidence_outside_root")
    cards = recommendations.get("recommendations", [])
    if recommendations.get("status") in (
        "no_threshold_met",
        "insufficient_evidence",
        "no_matching_resources",
    ):
        check(not cards, "non_ready_status_has_recommendations")
    for card in cards:
        used = card["candidate_features"]["grounded_signal_ids"]
        check(
            bool(used) and set(used) <= signals.keys() and card["signal_id"] in used,
            "card_signal_orphan",
        )
        refs = {
            (r["kind"], r["session_uid"], r["id"])
            for sid in used
            if sid in signals
            for r in signals[sid]["evidence"]
        }
        for ref in card["evidence"]:
            reference(ref)
            check(
                (ref["kind"], ref["session_uid"], ref["id"]) in refs, "card_evidence_not_in_signal"
            )
        for uid in used:
            if uid in signals:
                check(
                    signals[uid]["scope"]["root_session_uid"] == card["scope"]["root_session_uid"],
                    "card_signal_wrong_root",
                )
        if card["pending_requirements"]:
            check(
                card["recommendation_status"] == "needs_context"
                and card["compatibility"] == "unknown",
                "unknown_context_promoted",
            )
        check(
            card["effect_status"] == "unmeasured"
            and card["evaluation_plan"]["observed_effect"] is None,
            "historical_log_claims_measured_utility",
        )

    token_usage = (features.get("cost_time") or {}).get("usage") or {}
    buckets = token_usage.get("token_buckets") or {}
    counts = [
        buckets.get(k)
        for k in ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")
    ]
    if all(value is not None for value in counts):
        check(token_usage.get("total_tokens") == sum(counts), "token_bucket_conservation")
    return {
        "schema_version": "analysis-relational-invariants-v1",
        "status": "failed" if violations else "passed",
        "violations": violations,
        "violation_counts": dict(Counter(v["code"] for v in violations)),
        "selected": {
            "sessions": len(selected_sessions),
            "events": len(context.events),
            "tool_calls": len(calls),
            "model_calls": len(models),
            "fixture_event_uids": len(fixture_ids),
        },
        "counting": "identities and provenance checked per grain; no selected/imported/analyzed scalar funnel",
    }

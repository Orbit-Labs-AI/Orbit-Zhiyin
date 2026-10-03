"""Synthetic orphan sessions must not manufacture a pooled recommendation."""

import pytest

from orbit_backend.analytics.inputs import AnalysisInputBundle
from orbit_backend.analytics.recommendations import recommend_bottlenecks
from orbit_backend.analytics.service import analyze_bundle

RULE_IDS = {
    "correction_density", "repeated_requirements", "identical_retries", "tool_failures",
    "validation_failures", "acceptance_evidence_gap", "context_pressure",
}


def analyze_orphans(kind="subagent", count=2):
    sessions, events, calls = [], [], []
    for index in range(count):
        sid = f"synthetic-child-{index}"
        root = f"absent-root-{index}"
        sessions.append({"session_uid": sid, "root_uid": root, "parent_uid": root,
                         "kind": kind, "project_id": "synthetic-project"})
        # Each root has only five known calls: too few for the ten-call rule.
        # Pooling both roots would produce ten calls and four failures.
        for seq in range(5):
            uid = f"{sid}-call-{seq}"
            call = {"session_uid": sid, "call_uid": uid,
                    "call_event_uid": f"call-{uid}", "result_event_uid": f"result-{uid}",
                    "seq": seq * 2, "result_seq": seq * 2 + 1,
                    "name_raw": "synthetic_shell", "kind": "shell",
                    "status": "failed" if seq < 2 else "success", "status_scope": "command",
                    "started_at": seq * 10, "ended_at": seq * 10 + 1}
            calls.append(call)
            for event_kind, id_key, seq_key, ts_key in (
                ("tool.call", "call_event_uid", "seq", "started_at"),
                ("tool.result", "result_event_uid", "result_seq", "ended_at"),
            ):
                events.append({"event_uid": call[id_key], "session_uid": sid,
                               "kind": event_kind, "seq": call[seq_key], "ts": call[ts_key],
                               "actor": "tool", "attrs": {"call_id": uid}})
    bundle = AnalysisInputBundle(
        sessions=sessions, events=events, tool_calls=calls, model_calls=[],
        coverage={name: {"status": "available"} for name in
                  ("sessions", "events", "tool_calls", "model_calls")},
    )
    return analyze_bundle(bundle, with_text=False)


def assert_no_root_recommendations(analysis):
    assert analysis["sessions"] == []
    # Use the real catalogue so the test also checks that no actionable cards
    # escape; an empty catalogue would conceal that regression.
    result = recommend_bottlenecks(analysis, target_agent="codex")
    assert result["status"] == "insufficient_evidence"
    assert result["signals"] == []
    assert result["recommendations"] == []
    assert {item["rule_id"] for item in result["assessments"]} == RULE_IDS
    assert all(item["status"] == "insufficient_evidence" for item in result["assessments"])
    assert all(item["scope"]["root_session_uid"] is None for item in result["assessments"])


@pytest.mark.parametrize("kind", ["subagent", "workflow_agent"])
def test_orphan_children_from_different_roots_are_not_pooled(kind):
    analysis = analyze_orphans(kind)
    aggregate_calls = analysis["bottleneck_features"]["respond"]["tool_sequence"]
    assert len(aggregate_calls) == 10
    assert sum(call["status"] == "failed" for call in aggregate_calls) == 4
    assert len({call["session_uid"] for call in aggregate_calls}) == 2
    assert_no_root_recommendations(analysis)


def test_empty_production_analysis_has_no_signals_or_cards():
    analysis = analyze_orphans(count=0)
    assert analysis["bottleneck_features"]["respond"]["tool_sequence"] == []
    assert_no_root_recommendations(analysis)

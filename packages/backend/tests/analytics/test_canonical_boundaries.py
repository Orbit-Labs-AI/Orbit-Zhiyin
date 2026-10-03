"""Reused canonical inputs cannot widen snapshots or multiply measured facts."""

import copy
import json
from dataclasses import asdict

import pytest

from orbit_backend.analytics.inputs import Scope, select
from orbit_backend.analytics.service import analyze_bundle


def canonical(fixtures):
    session, event, bundle = fixtures
    rows = [
        event("请修复 Python 代码", "u", 0, ts=100),
        event("", "call", 1, ts=120),
        event("", "result", 2, ts=150),
        event("", "usage", 3, ts=160),
    ]
    rows[1].update(kind="tool.call", actor="assistant")
    rows[2].update(kind="tool.result", actor="tool")
    rows[3].update(kind="model.usage", actor="system")
    data = bundle(
        rows,
        [session(agent="codex"), session("other", root_uid="other", project_id="p2", agent="pi")],
    )
    data.tool_calls = [
        {
            "call_uid": "c",
            "session_uid": "s",
            "turn_uid": "t-call",
            "call_event_uid": "call",
            "result_event_uid": "result",
            "name_raw": "shell",
            "kind": "shell",
            "started_at": 120,
            "ended_at": 150,
            "status": "failed",
            "status_scope": "direct_command",
            "wall_elapsed_ms": 30,
            "native_execution_ms": 20,
        }
    ]
    data.model_calls = [
        {
            "call_uid": "m",
            "session_uid": "s",
            "turn_uid": "t-usage",
            "usage_event_uid": "usage",
            "ts": 160,
            "model_id": "m",
            "request_identity_quality": "reported",
            "boundary_quality": "reported",
            "input_tokens": 10,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 5,
            "coverage": "self",
        }
    ]
    data.statistical_members = {"event_uids": [r["event_uid"] for r in rows]}
    return data


def test_identical_duplicates_are_counted_once_and_conflicts_are_explicit(fixtures):
    data = canonical(fixtures)
    base = analyze_bundle(data, with_text=False)
    for name in ("sessions", "events", "tool_calls", "model_calls"):
        getattr(data, name).extend(copy.deepcopy(getattr(data, name)))
    duplicate = analyze_bundle(data, with_text=False)
    assert duplicate["overview"]["counts"] == base["overview"]["counts"]
    assert duplicate["tools"]["totals"] == base["tools"]["totals"]
    assert duplicate["bottleneck_features"]["cost_time"] == base["bottleneck_features"]["cost_time"]
    assert duplicate["work_graph"] == base["work_graph"]
    assert duplicate["selection"]["canonical_duplicate_rows"] == {
        "sessions": 2,
        "events": 4,
        "tool_calls": 1,
        "model_calls": 1,
    }
    data.events[-4]["text"] = "conflicting source content"
    with pytest.raises(ValueError, match="Conflicting canonical events identity"):
        analyze_bundle(data, with_text=False)


def test_record_order_is_not_an_evidence_or_ranking_input(fixtures):
    data = canonical(fixtures)
    base = analyze_bundle(data, with_text=False)
    for name in ("sessions", "events", "tool_calls", "model_calls"):
        getattr(data, name).reverse()
    assert json.dumps(analyze_bundle(data, with_text=False), sort_keys=True) == json.dumps(
        base, sort_keys=True
    )


@pytest.mark.parametrize(
    "scope",
    [
        Scope(project_ids=[]),
        Scope(root_session_uids=[]),
        Scope(source_ids=[]),
        Scope(excluded_session_uids=["s"]),
        Scope(project_ids=["p2"]),
    ],
)
def test_canonical_members_do_not_override_a_narrower_session_scope(fixtures, scope):
    assert select(canonical(fixtures), scope)[:4] == ([], [], [], [])


def test_manual_canonical_cutoff_keeps_start_and_hides_future_result(fixtures):
    sessions, events, calls, models, _ = select(
        canonical(fixtures), Scope(from_ts=100, until_ts=150)
    )
    assert len(sessions) == 1
    assert [e["event_uid"] for e in events] == ["u", "call"]
    assert models == []
    assert calls[0]["status"] is calls[0]["ended_at"] is calls[0]["result_event_uid"] is None
    assert calls[0]["native_execution_ms"] is calls[0]["wall_elapsed_ms"] is None


@pytest.mark.parametrize(
    "scope",
    [Scope(until_ts=150), Scope(from_ts=100), Scope(model_ids=[]), Scope(effort_raw=["high"])],
)
def test_changed_producer_scope_requires_new_snapshot_not_stale_l3_metadata(fixtures, scope):
    data = canonical(fixtures)
    data.selection_scope = asdict(Scope())
    with pytest.raises(ValueError, match="read a new scoped bundle"):
        select(data, scope)


def test_model_context_filter_does_not_require_token_usage_per_turn(fixtures):
    data = canonical(fixtures)
    data.model_calls = []
    scope = Scope(model_ids=["m"])
    data.selection_scope = asdict(scope)
    assert len(select(data, scope)[1]) == 4


def test_future_model_change_does_not_erase_past_generic_turn(fixtures):
    _, event, bundle = fixtures
    data = bundle([event("请修复代码", "u", 0, ts=100)])
    data.statistical_members = None
    data.events[0]["turn_uid"] = "turn"
    data.model_calls = [
        {"call_uid": "past", "session_uid": "s", "turn_uid": "turn", "ts": 110, "model_id": "a"}
    ]
    scope = Scope(model_ids=["a"], until_ts=200)
    before = select(data, scope)
    data.model_calls.append(
        {"call_uid": "future", "session_uid": "s", "turn_uid": "turn", "ts": 500, "model_id": "b"}
    )
    assert select(data, scope) == before

import copy
import json

import pytest

from orbit_backend.analytics.canonical import canonical_bundle, input_scope
from orbit_backend.analytics.inputs import select
from orbit_backend.analytics.service import analyze_bundle
from orbit_backend.cli import main


def reader_data():
    events = [
        {"event_uid": "context", "session_uid": "s", "seq": 0, "ts": 5, "turn_uid": "t",
         "kind": "message.user", "actor": "human", "text": "以前的要求", "attrs": {"origin": "human"}},
        {"event_uid": "u", "session_uid": "s", "seq": 1, "ts": 10, "turn_uid": "t",
         "kind": "message.user", "actor": "human", "text": "请实现接口", "attrs": {"origin": "human"}},
        {"event_uid": "usage", "session_uid": "s", "seq": 2, "ts": 12, "turn_uid": "t",
         "kind": "model.usage", "actor": "assistant", "text": None,
         "attrs": {"usage_scope": "call", "measurement": "delta", "request_key": ["s", "r"],
                   "request_id": "r", "coverage": "self"}},
        {"event_uid": "end", "session_uid": "s", "seq": 3, "ts": 13, "turn_uid": "t",
         "kind": "turn.end", "actor": "harness", "text": None, "attrs": {"status": "interrupted"}},
    ]
    return {"input_contract": "analysis-input-v1", "projection_run_id": 1,
            "parser_version": "main-test", "scope": {"display_timezone": "Asia/Shanghai", "from_ts": 10, "until_ts": 20},
            "coverage": {"events": {"status": "available"}, "tool_call": {"status": "available"},
                         "model_call": {"status": "available"}},
            "sessions": [{"session_uid": "s", "kind": "main", "root_uid": "s", "started_at": 5}],
            "projects": [], "turns": [], "events": events, "tool_calls": [],
            "model_calls": [{"call_uid": "mc", "session_uid": "s", "turn_uid": "t", "ts": 12,
                             "usage_event_uid": "usage", "request_id": "r", "coverage": "self",
                             "input_tokens": 10, "cache_read_tokens": 20, "cache_write_tokens": 0,
                             "output_tokens": 3}],
            "statistical_members": {"event_uids": ["u", "usage", "end"]}}


def test_native_request_evidence_counts_without_including_earlier_context():
    data = reader_data()
    original = copy.deepcopy(data)
    result = analyze_bundle(canonical_bundle(data), input_scope(data, {}), with_text=False)
    assert result["overview"]["counts"]["human_messages"] == 1
    assert result["overview"]["usage"]["request_count"] == 1
    assert result["overview"]["usage"]["total_tokens"] == 33
    assert result["workflow"]["interruption_count"] == 1
    assert result["versions"]["parser_version"] == "main-test"
    assert data == original


@pytest.mark.parametrize("change", ["missing_usage", "snapshot", "wrong_session", "wrong_request"])
def test_incomplete_request_evidence_is_not_promoted(change):
    data = reader_data()
    if change == "missing_usage":
        data["model_calls"][0]["usage_event_uid"] = "absent"
    elif change == "snapshot":
        data["events"][2]["attrs"]["usage_scope"] = "session_snapshot"
        data["events"][2]["attrs"]["measurement"] = "cumulative"
    elif change == "wrong_session":
        data["events"][2]["session_uid"] = "different"
    else:
        data["model_calls"][0]["request_id"] = "different"
    assert canonical_bundle(data).model_calls[0]["boundary_reliable"] is False


def test_declared_members_exclude_in_window_context_from_counts():
    data = reader_data()
    data["events"][0]["ts"] = 11
    _, events, *_ = select(canonical_bundle(data), input_scope(data, {}))
    assert "context" not in {event["event_uid"] for event in events}


def test_saved_window_cannot_be_widened_or_reference_unknown_members():
    data = reader_data()
    with pytest.raises(ValueError, match="只能缩小"):
        input_scope(data, {"from_ts": 0})
    data["statistical_members"]["event_uids"].append("absent")
    with pytest.raises(ValueError, match="不存在"):
        canonical_bundle(data)


def test_cli_standard_input_uses_its_scope_without_creating_legacy_database(tmp_path):
    source, output, legacy = [tmp_path / name for name in ("input.json", "result.json", "old.sqlite")]
    source.write_text(json.dumps(reader_data()))
    main(["--db", str(legacy), "analytics", "--analysis-input", str(source), "--no-text", "--output", str(output),
          "--feature-output", str(tmp_path / "features")])
    result = json.loads(output.read_text())
    assert result["scope"]["display_timezone"] == "Asia/Shanghai"
    assert result["scope"]["from_ts"] == 10
    assert not legacy.exists()
    assert json.loads((tmp_path / "features/index.json").read_text())["feature_count"] == len(result["feature_dictionary"])


def test_typed_request_quality_is_not_replaced_by_legacy_event_fields():
    data = reader_data()
    call = data["model_calls"][0]
    call.update(request_identity_quality="reported", boundary_quality="observed")
    data["events"][2]["attrs"] = {}
    assert canonical_bundle(data).model_calls[0] == call


def test_saved_source_and_agent_selection_cannot_be_widened():
    data = reader_data()
    data["scope"].update(source_ids=["a"], agent_ids=["codex"])
    for override in ({"source_ids": ["a", "b"]}, {"agent_ids": ["codex", "claude_code"]}):
        with pytest.raises(ValueError, match="只能缩小"):
            input_scope(data, override)

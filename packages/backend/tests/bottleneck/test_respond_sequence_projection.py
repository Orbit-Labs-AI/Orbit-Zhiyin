"""Selected native event positions are the only canonical tool-order evidence."""

from copy import deepcopy

import pytest

from tandem_backend.analytics.respond import analyze_respond


def test_canonical_calls_join_selected_events_and_ignore_list_or_clock_order(make_call, make_event):
    calls = [make_call("z"), make_call("a")]
    for call in calls:
        call.pop("seq")
    events = [make_event("a", 9, "tool.call", ts=1), make_event("z", 2, "tool.call", ts=900)]
    before = deepcopy((calls, events))
    result = analyze_respond(events, calls, [], {"s"})
    assert [(c["call_uid"], c["seq"]) for c in result["tool_sequence"]] == [("z", 2), ("a", 9)]
    assert all(c["sequence_basis"] == "selected_call_event_native_seq" for c in result["tool_sequence"])
    assert result["sequence_unknown_call_n"] == 0
    assert (calls, events) == before


@pytest.mark.parametrize("seq", [None, True, "4", -1])
def test_invalid_native_positions_are_unknown(make_call, make_event, seq):
    event = make_event("c", seq, "tool.call")
    result = analyze_respond([event], [make_call()], [], {"s"})
    call = result["tool_sequence"][0]
    assert call["seq"] is None
    assert call["sequence_unknown_reason"] == "native_sequence_missing"
    assert result["sequence_unknown_call_n"] == 1


@pytest.mark.parametrize("variant", ["missing", "other_session", "result", "replayed", "source_conflict"])
def test_unselected_or_wrong_identity_does_not_restore_stale_call_seq(make_call, make_event, variant):
    event = make_event("c", 3, "tool.call")
    call = make_call(seq=99, source_id="one")
    if variant == "other_session":
        event["session_uid"] = "another"
    elif variant == "result":
        event["kind"] = "tool.result"
    elif variant == "replayed":
        event["attrs"]["replayed_from"] = "original"
    elif variant == "source_conflict":
        event["source_id"] = "two"
    result = analyze_respond([] if variant == "missing" else [event], [call], [], {"s"})
    assert result["tool_sequence"][0]["seq"] is None
    assert result["tool_sequence"][0]["sequence_basis"] is None


@pytest.mark.parametrize("variant", ["event_identity", "native_sequence", "call_position"])
def test_duplicate_positions_abstain(make_call, make_event, variant):
    events = [make_event("c", 3, "tool.call")]
    calls = [make_call()]
    if variant == "event_identity":
        events.append(deepcopy(events[0]))
    elif variant == "native_sequence":
        events.append(make_event("other", 3, "message.assistant"))
    else:
        calls.append(make_call("other", call_event_uid="c"))
    result = analyze_respond(events, calls, [], {"s"})
    assert all(c["seq"] is None for c in result["tool_sequence"])
    assert result["sequence_unknown_call_n"] == len(calls)


def test_missing_middle_position_does_not_bridge_failed_retry_neighbors(make_call, make_event):
    calls = [make_call(uid, status="failed", argument_digest="x", argument_digest_kind="literal")
             for uid in ("a", "b", "c")]
    events = [make_event("a", 1, "tool.call"), make_event("c", 3, "tool.call")]
    result = analyze_respond(events, calls, [], {"s"})
    assert result["retry_links"] == []
    assert result["retry_sequence_unknown_session_uids"] == ["s"]
    assert result["workflow"]["consecutive_failed_calls"] is None
    assert len(result["failure_reasons"]) == 3


def test_duplicate_sequence_across_different_sessions_is_valid(make_call, make_event):
    calls = [make_call("a"), make_call("b", session_uid="other")]
    events = [make_event("a", 2, "tool.call"), make_event("b", 2, "tool.call", sid="other")]
    result = analyze_respond(events, calls, [], {"s", "other"})
    assert result["sequence_unknown_call_n"] == 0


def test_excluded_sources_cannot_lend_sequence_or_rebuild_calls(make_call, make_event):
    event = make_event("c", 3, "tool.call")
    excluded = analyze_respond([event], [make_call()], [], {"s"}, dataset_status="excluded")
    assert excluded["tool_sequence"] is None
    assert excluded["sequence_unknown_call_n"] is None
    no_events = analyze_respond([event], [make_call()], [], {"s"}, event_status="excluded")
    assert no_events["tool_sequence"][0]["seq"] is None
    no_fallback = analyze_respond([event], None, [], {"s"}, event_status="excluded")
    assert no_fallback["tool_sequence"] is None
    assert no_fallback["workflow"] is None


def test_native_zero_and_l2_pairing_remain_supported(make_event):
    events = [make_event("c", 0, "tool.call", call_id="x"),
              make_event("r", 1, "tool.result", call_id="x", status="success")]
    result = analyze_respond(events, None, [], {"s"})
    assert result["call_source"] == "paired_L2"
    assert result["tool_sequence"][0]["seq"] == 0
    assert result["tool_sequence"][0]["result_event_uid"] == "r"

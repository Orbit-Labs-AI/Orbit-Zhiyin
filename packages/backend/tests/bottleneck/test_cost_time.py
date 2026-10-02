import copy
import json

import pytest

from tandem_backend.analytics.cost_time import activity, summarize_durations, usage
from tandem_backend.analytics.inputs import Scope


def request(**values):
    return {"session_uid": "s", "call_uid": "m", "usage_scope": "call", "measurement": "delta",
            "boundary_reliable": True, "coverage": "self", "ts": 100,
            "input_tokens": 120, "cache_read_tokens": 50, "cache_write_tokens": 10,
            "output_tokens": 30, "reasoning_tokens": 20, **values}


def test_inclusive_cache_input_normalized_without_reasoning_double_count(make_session):
    calls = [request(input_tokens_semantics="includes_cache")]
    before = copy.deepcopy(calls)
    r = usage(calls, [], [make_session()], Scope())
    assert r["token_buckets"] == {"input_tokens": 60, "cache_read_tokens": 50, "cache_write_tokens": 10, "output_tokens": 30}
    assert r["total_tokens"] == 150
    assert calls == before


@pytest.mark.parametrize("bad", [-1, True, "12", float("nan"), float("inf"), None])
def test_invalid_bucket_remains_unknown_and_json_safe(make_session, bad):
    r = usage([request(input_tokens=bad)], [], [make_session()], Scope())
    assert r["total_tokens"] is None
    assert r["token_buckets"]["input_tokens"] is None
    assert r["token_unknown_call_n"] == 1
    json.dumps(r, allow_nan=False)


def test_cache_larger_than_inclusive_input_or_unknown_semantics_abstains(make_session):
    for c in [request(input_tokens=20, input_tokens_semantics="includes_cache"),
              request(input_tokens_semantics="unknown")]:
        assert usage([c], [], [make_session()], Scope())["total_tokens"] is None


def test_identical_requests_count_once_conflicts_never_pick_last(make_session):
    c = request()
    r = usage([c, copy.deepcopy(c)], [], [make_session()], Scope())
    assert r["total_tokens"] == 210
    assert r["request_count"] == 1
    assert r["duplicate_request_rows"] == 1
    conflict = usage([c, request(output_tokens=90)], [], [make_session()], Scope())
    assert conflict["total_tokens"] is None
    assert conflict["conflicting_request_ids"] == [{"session_uid": "s", "call_uid": "m"}]


def test_snapshot_latest_not_sum_and_same_key_in_other_session_not_overwritten(make_event, make_session):
    attrs = {"measurement": "cumulative", "usage_scope": "session_snapshot", "snapshot_key": "cycle",
             "coverage": "self", "cache_read_tokens": 0, "cache_write_tokens": 0, "output_tokens": 0}
    es = [make_event("a", 1, "model.usage", input_tokens=100, **attrs),
          make_event("b", 2, "model.usage", input_tokens=150, **attrs)]
    assert usage(None, es, [make_session()], Scope())["total_tokens"] == 150
    es.append(make_event("child", 1, "model.usage", sid="child", input_tokens=10, **attrs))
    result = usage(None, es, [make_session(), make_session("child")], Scope())
    assert len(result["cumulative_snapshots"]) == 2
    assert result["total_tokens"] is None


def test_partial_requests_keep_known_subtotal_but_not_complete_total(make_session):
    r = usage([request()], [], [make_session()], Scope(), records_complete=False)
    assert r["known_call_tokens"] == 210 and r["total_tokens"] is None


def test_reliable_duration_sum_union_and_log_estimates_stay_separate(make_call, make_event):
    calls = [make_call("a", started_at=0, ended_at=10000, interval_reliable=True),
             make_call("b", started_at=5000, ended_at=15000, interval_reliable=True),
             make_call("estimate", duration_ms=40000, duration_source="event_difference"),
             make_call("unknown")]
    r = summarize_durations(calls, [make_event(ts=500)])
    assert r["wall_elapsed_sum_ms"] == 20000
    assert r["execution_duration_sum_ms"] is None
    assert r["reliable_interval_union_ms"] == 15000
    assert r["estimated_log_gap_sum_ms"] == 40000
    assert r["wall_effective_n"] == 2
    assert r["effective_n"] == 0 and r["unknown_n"] == 4
    assert r["session_spans"][0]["observed_session_span_ms"] == 0


def test_reported_duration_does_not_invent_interval_or_end_timestamp(make_call, make_event):
    r = summarize_durations([make_call(ended_at=None, duration_ms=900, duration_source="reported")],
                            [make_event(ts=None)])
    assert r["execution_duration_sum_ms"] == 900
    assert r["reliable_interval_union_ms"] is None
    assert r["execution_durations"][0]["ended_at"] is None
    assert r["session_spans"][0]["observed_session_span_ms"] is None
    assert r["session_spans"][0]["unknown_n"] == 1


def test_calendar_uses_timezone_deduplicated_requests_and_real_session_starts(make_event, make_session):
    es = [make_event(ts=0), make_event("unclocked", 2, ts=None)]
    models = [request(ts=0), request(ts=0), request(call_uid="snapshot", measurement="cumulative")]
    r = activity([make_session(started_at=None)], es, [], models, {"s"}, Scope(display_timezone="Asia/Shanghai"))
    assert r["human_messages"]["by_hour"] == {"8": 1}
    assert r["human_messages"]["time_unknown_n"] == 1
    assert r["model_requests"]["effective_n"] == 1
    assert r["sessions"]["effective_n"] == 0 and r["sessions"]["time_unknown_n"] == 1


def test_invalid_latency_not_counted_or_serialized_as_nan(make_session):
    r = usage([request(latency_ms=float("nan"), ttft_ms=True)], [], [make_session()], Scope())
    assert r["median_latency_ms"] is None and r["median_ttft_ms"] is None
    json.dumps(r, allow_nan=False)


def test_known_empty_request_dataset_is_zero_but_unavailable_or_partial_is_not(make_session):
    known = usage([], [], [make_session()], Scope())
    assert known["status"] == "available" and known["total_tokens"] == 0
    assert set(known["token_buckets"].values()) == {0}
    assert usage(None, [], [make_session()], Scope())["total_tokens"] is None
    assert usage([], [], [make_session()], Scope(), records_complete=False)["total_tokens"] is None

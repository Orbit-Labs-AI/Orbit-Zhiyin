from datetime import datetime

import pytest

from orbit_backend.analytics.presentation.statistics import (
    build_statistics,
    project_identity_resolver,
    project_statistics,
)


def ms(value):
    return round(datetime.fromisoformat(value).timestamp() * 1000)


def row(sid, first=None, last=None, *, project=None, legacy=None, dates=None, **extra):
    return {"session_uid": sid, "kind": "main", "project_id": project,
            "legacy_project_id": legacy, "included_session_uids": [sid],
            "features": {"first_observed_ts": first, "last_observed_ts": last,
                         "observed_event_dates": dates,
                         "user_message_count": 2, "assistant_message_count": 3,
                         "total_event_count": 5, "turn_count": 2, "tool_call_count": 4},
            "unknown_counts": {}, **extra}


def analysis(rows, *, timezone="UTC", counts=None):
    return {"sessions": rows, "scope": {"display_timezone": timezone},
            "coverage": {name: {"status": "available"} for name in
                         ("sessions", "events", "tool_calls")},
            "overview": {"counts": counts or {"sessions": len(rows), "main_sessions": len(rows),
                                               "session_kind_unknown": 0}}}


def value(result, group, key):
    return result[group][key]["value"]


def test_project_inventory_coalesces_canonical_alias_and_excludes_null_group():
    rows = [row("a", project="p1", legacy="old"), row("b", legacy="old"),
            row("c", project="p1", legacy="another"), row("d", legacy="other"), row("e")]
    result = build_statistics(analysis(rows))
    assert value(result, "counts", "projects") == 2
    assert value(result, "counts", "unassigned_project_sessions") == 1
    assert result["counts"]["projects"]["unknown_n"] == 1
    assert result["project_identity"] == {"canonical_n": 1, "legacy_only_n": 1,
                                          "unassigned_group_is_project": False}


def test_ambiguous_legacy_alias_never_merges_different_canonical_projects():
    rows = [row("a", project="p1", legacy="old"), row("b", project="p2", legacy="old"),
            row("c", legacy="old")]
    source = analysis(rows)
    result = build_statistics(source)
    assert value(result, "counts", "projects") == 2
    assert value(result, "counts", "ambiguous_project_sessions") == 1
    assert result["counts"]["projects"]["status"] == "partial"
    resolve = project_identity_resolver(source)
    assert resolve(rows[0]) == ("canonical", "p1")
    assert resolve(rows[2]) is None


def test_epoch_zero_and_singlepoint_are_valid_but_creation_time_is_not_used():
    rows = [row("a", 0, 0, dates=["1970-01-01"]),
            row("b", started_at=100, ended_at=500)]
    result = build_statistics(analysis(rows))
    assert value(result, "time", "first_observed_ts") == 0
    assert value(result, "time", "last_observed_ts") == 0
    assert value(result, "time", "observed_session_span_sum_ms") == 0
    assert value(result, "time", "unknown_span_sessions") == 1
    assert result["activity"]["daily_session_starts"]["rows"] == [{"date": "1970-01-01", "count": 1}]
    assert sum(r["minutes"] for r in result["activity"]["observed_span_by_hour"]["rows"]) == 0


def test_cross_midnight_and_parallel_sessions_have_distinct_sum_union_and_local_bins():
    rows = [row("a", ms("2026-10-01T15:30:00+00:00"), ms("2026-10-01T17:00:00+00:00"),
                dates=["2026-10-01", "2026-10-02"]),
            row("b", ms("2026-10-01T16:00:00+00:00"), ms("2026-10-01T17:00:00+00:00"),
                dates=["2026-10-02"])]
    result = build_statistics(analysis(rows, timezone="Asia/Shanghai"))
    assert value(result, "time", "observed_session_span_sum_ms") == 150 * 60_000
    assert value(result, "time", "observed_session_span_union_ms") == 90 * 60_000
    assert value(result, "time", "observed_session_span_mean_ms") == 75 * 60_000
    assert value(result, "time", "observed_session_span_median_ms") == 75 * 60_000
    assert value(result, "activity", "active_dates") == 2
    hours = result["activity"]["observed_span_by_hour"]["rows"]
    assert hours[23]["minutes"] == 30
    assert hours[0]["minutes"] == 120
    assert result["activity"]["daily_session_starts"]["rows"] == [
        {"date": "2026-10-01", "count": 1}, {"date": "2026-10-02", "count": 1}]


@pytest.mark.parametrize("start,end,zone,expected", [
    ("2026-11-01T00:30:00-04:00", "2026-11-01T02:30:00-05:00", "America/New_York", {0: 30, 1: 120, 2: 30}),
    ("2026-03-08T01:30:00-05:00", "2026-03-08T03:30:00-04:00", "America/New_York", {1: 30, 3: 30}),
    ("2026-10-04T01:30:00+10:30", "2026-10-04T03:30:00+11:00", "Australia/Lord_Howe", {1: 30, 2: 30, 3: 30}),
])
def test_hour_allocation_uses_real_elapsed_time_across_dst(start, end, zone, expected):
    result = build_statistics(analysis([row("a", ms(start), ms(end))], timezone=zone))
    hours = result["activity"]["observed_span_by_hour"]["rows"]
    assert {r["hour"]: r["minutes"] for r in hours if r["minutes"]} == expected
    assert sum(r["minutes"] for r in hours) * 60_000 == ms(end) - ms(start)


def test_child_count_is_known_but_parent_bounds_cannot_fill_child_time():
    parent = row("a", 0, 60_000, included_session_uids=["a", "child"], project="p1")
    source = analysis([parent], counts={"sessions": 3, "main_sessions": 1, "session_kind_unknown": 1})
    global_result = build_statistics(source)
    assert value(global_result, "counts", "subagent_sessions") == 1
    assert value(global_result, "counts", "unknown_kind_sessions") == 1
    assert value(global_result, "time", "unknown_span_sessions") == 2
    assert value(global_result, "time", "observed_session_span_sum_ms") == 60_000
    project = project_statistics(source, [parent])
    assert value(project, "counts", "sessions") == 2
    assert value(project, "counts", "subagent_sessions") == 1
    assert value(project, "time", "unknown_span_sessions") == 1
    assert value(project, "counts", "tool_calls") == 4


def test_project_scope_cannot_borrow_other_project_time_or_weekday_heatmap():
    a, b = row("a", 100, 200, project="a"), row("b", 1000, 2000, project="b")
    source = analysis([a, b])
    source["overview"]["activity_rhythm"] = {"human_messages": {"by_weekday_hour": {"1:0": 5}}}
    result = project_statistics(source, [a, a])
    assert value(result, "counts", "sessions") == 1
    assert value(result, "time", "last_observed_ts") == 200
    assert result["activity"]["message_weekday_hour"]["rows"] is None


def test_empty_selection_and_unavailable_events_are_not_a_fabricated_duration():
    result = build_statistics(analysis([]))
    assert value(result, "counts", "projects") == 0
    assert value(result, "time", "observed_session_span_sum_ms") is None
    assert result["activity"]["observed_span_by_hour"]["rows"] is None
    source = analysis([row("a", included_session_uids=["a", "child"])],
                      counts={"sessions": 2, "main_sessions": 1, "session_kind_unknown": 0})
    source["coverage"]["events"]["status"] = "unavailable"
    result = build_statistics(source)
    assert value(result, "counts", "human_messages") is None
    assert result["activity"]["daily_session_starts"]["rows"] is None


def test_bad_timestamp_and_reversed_bounds_do_not_enter_duration_aggregates():
    rows = [row("a", 100, 0), row("b", float("inf"), 1000), row("c", True, 2000),
            row("d", -(10**20), 10**20)]
    result = build_statistics(analysis(rows))
    assert value(result, "time", "known_span_sessions") == 0
    assert value(result, "time", "unknown_span_sessions") == 4
    assert value(result, "time", "observed_session_span_sum_ms") is None


def test_unclocked_events_lower_boundary_and_active_date_coverage():
    one = row("a", 0, 60_000, dates=["1970-01-01"])
    one["features"]["time_unknown_event_count"] = 2
    result = build_statistics(analysis([one]))
    assert result["time"]["observed_session_span_sum_ms"]["status"] == "partial"
    assert result["time"]["observed_session_span_sum_ms"]["unknown_n"] == 1
    assert value(result, "time", "unclocked_events") == 2
    assert result["activity"]["active_dates"]["status"] == "partial"


def test_long_spans_keep_totals_without_expanding_unbounded_calendar():
    end = ms("2026-10-01T00:00:00+00:00")
    result = build_statistics(analysis([row("a", 0, end)]))
    assert value(result, "time", "observed_session_span_sum_ms") == end
    hours = result["activity"]["observed_span_by_hour"]
    # 1970-01-01 .. 2026-10-01 UTC is a whole number of days: every hour gets end/24.
    assert hours["status"] == "available"
    assert {r["minutes"] for r in hours["rows"]} == {end / 24 / 60_000}
    assert len(result["activity"]["daily_session_starts"]["rows"]) == 1


def test_thousands_of_multi_day_sessions_allocate_exactly_and_fast():
    import time

    start = ms("2026-03-01T00:30:00+00:00")
    span = 72 * 3_600_000 + 15 * 60_000  # 72h15m crosses 3 full days plus a partial hour
    rows = [row(f"s{i}", start + i * 3_600_000, start + i * 3_600_000 + span)
            for i in range(5000)]
    began = time.perf_counter()
    result = build_statistics(analysis(rows, timezone="America/New_York"))  # crosses DST start
    elapsed = time.perf_counter() - began
    hours = result["activity"]["observed_span_by_hour"]
    assert hours["status"] == "available" and elapsed < 1.0, elapsed
    assert sum(r["minutes"] for r in hours["rows"]) * 60_000 == 5000 * span


def test_message_heatmap_uses_joint_observations_not_marginal_product():
    source = analysis([])
    source["overview"]["activity_rhythm"] = {"human_messages": {
        "by_hour": {"1": 2}, "weekday_distribution": {"1": 2}}}
    assert build_statistics(source)["activity"]["message_weekday_hour"]["rows"] is None
    source["overview"]["activity_rhythm"]["human_messages"]["by_weekday_hour"] = {"1:1": 2, "2:2": 3}
    heatmap = build_statistics(source)["activity"]["message_weekday_hour"]["rows"]
    assert len(heatmap) == 7 * 24
    assert sum(cell["count"] for cell in heatmap) == 5
    assert next(cell for cell in heatmap if cell["weekday"] == 1 and cell["hour"] == 2)["count"] == 0


def test_partial_all_unknown_messages_cannot_generate_zeros_in_heatmap():
    source = analysis([])
    source["overview"]["counts"]["human_origin_unknown"] = 2
    source["overview"]["activity_rhythm"] = {"human_messages": {"by_weekday_hour": {}}}
    heatmap = build_statistics(source)["activity"]["message_weekday_hour"]
    assert heatmap["status"] == "partial"
    assert all(cell["count"] is None for cell in heatmap["rows"])


def test_daily_average_uses_actual_main_event_dates_not_span_days_or_child_count():
    a = row("a", 0, 10 * 86_400_000, dates=["1970-01-01", "1970-01-11"],
            included_session_uids=["a", "child"])
    b = row("b", 0, 0, dates=["1970-01-01"])
    b["features"]["user_message_count"] = 6
    source = analysis([a, b], counts={"sessions": 3, "main_sessions": 2,
                                      "session_kind_unknown": 0})
    averages = build_statistics(source)["averages"]
    assert averages["human_messages_per_main_session"]["value"] == 4
    assert averages["human_messages_per_main_session"]["denominator"] == 2
    assert averages["sessions_per_active_date"]["value"] == 1
    assert averages["sessions_per_active_date"]["denominator"] == 2
    assert averages["sessions_per_active_date"]["status"] == "available"


def test_daily_average_null_when_only_boundaries_exist_and_ignores_unknown_kind_dates():
    main = row("a", 0, 86_400_000)
    unknown = row("b", 0, 0, kind="unknown", dates=["1970-01-01"])
    source = analysis([main, unknown], counts={"sessions": 2, "main_sessions": 1,
                                               "session_kind_unknown": 1})
    averages = build_statistics(source)["averages"]
    assert averages["sessions_per_active_date"]["value"] is None
    assert averages["sessions_per_active_date"]["denominator"] is None
    assert averages["human_messages_per_main_session"]["value"] == 2
    assert averages["human_messages_per_main_session"]["status"] == "partial"


def test_averages_preserve_partial_denominators_and_missing_message_evidence():
    known, unknown = row("a", dates=["1970-01-01"]), row("b", dates=None)
    unknown["features"]["user_message_count"] = None
    unknown["unknown_counts"]["human_origin"] = 3
    result = project_statistics(analysis([known, unknown]), [known, unknown])
    assert result["counts"]["human_messages"]["unknown_n"] == 1
    assert result["counts"]["human_messages"]["unknown_evidence_n"] == 3
    assert result["averages"]["human_messages_per_main_session"]["value"] == 1
    assert result["averages"]["human_messages_per_main_session"]["unknown_n"] == 1
    daily = result["averages"]["sessions_per_active_date"]
    assert daily["value"] == 1
    assert daily["status"] == "partial"
    assert daily["unknown_n"] == 1
    unavailable_source = analysis([unknown])
    assert build_statistics(unavailable_source)["averages"]["human_messages_per_main_session"]["value"] is None


def test_empty_and_unavailable_selections_do_not_fabricate_averages():
    assert all(item["value"] is None for item in build_statistics(analysis([]))["averages"].values())
    source = analysis([row("a", dates=["1970-01-01"])])
    source["coverage"]["sessions"]["status"] = "excluded"
    assert all(item["value"] is None for item in build_statistics(source)["averages"].values())


def test_explicit_project_joint_heatmap_is_accepted_without_global_unknown_leakage():
    a, b = row("a", project="p1"), row("b", project="p2")
    rhythm = {"human_messages": {"by_weekday_hour": {"1:0": 2}, "time_unknown_n": 0}}
    source = analysis([a, b])
    source["overview"]["counts"]["human_origin_unknown"] = 99
    source["projects"] = [{"project_id": "p1", "activity_rhythm": rhythm}]
    source["overview"]["activity_rhythm"] = rhythm
    result = project_statistics(source, [a])["activity"]["message_weekday_hour"]
    assert sum(cell["count"] for cell in result["rows"]) == 2
    assert result["status"] == "available"
    assert result["unknown_n"] == 0


def test_project_joint_heatmap_rejects_global_and_partial_project_scope():
    a, b, c = row("a", project="p1"), row("b", project="p1"), row("c", project="p2")
    project_rhythm = {"human_messages": {"by_weekday_hour": {"1:0": 2}}}
    global_rhythm = {"human_messages": {"by_weekday_hour": {"1:0": 2, "1:1": 10}}}
    source = analysis([a, b, c])
    source["projects"] = [{"project_id": "p1", "activity_rhythm": project_rhythm}]
    source["overview"]["activity_rhythm"] = global_rhythm
    assert project_statistics(source, [a, b])["activity"]["message_weekday_hour"]["rows"] is None
    source["overview"]["activity_rhythm"] = project_rhythm
    assert project_statistics(source, [a])["activity"]["message_weekday_hour"]["rows"] is None

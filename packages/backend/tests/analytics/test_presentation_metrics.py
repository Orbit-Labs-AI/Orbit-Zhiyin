from datetime import datetime

import pytest

from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.presentation.metrics import activity_view, ranked_counts, window_scope


def test_window_is_fixed_duration_and_respects_historical_cutoff():
    end = 1790899200000
    scope = window_scope(Scope(until_ts=end, display_timezone="Asia/Shanghai"), "7d")
    assert scope.until_ts == end
    assert scope.from_ts == end - 7 * 86400000
    assert scope.contains(scope.from_ts)
    assert not scope.contains(end)
    assert window_scope(Scope(), "30d", now_ts=end).from_ts == end - 30 * 86400000
    assert window_scope(Scope(), "all").until_ts is None


def test_now_anchored_window_is_aligned_to_local_day():
    shanghai = Scope(display_timezone="Asia/Shanghai")
    # 2026-10-03 09:00 and 23:59 Shanghai (UTC+8): same local day.
    morning = int(datetime.fromisoformat("2026-10-03T09:00:00+08:00").timestamp() * 1000)
    night = int(datetime.fromisoformat("2026-10-03T23:59:59+08:00").timestamp() * 1000)
    tomorrow = int(datetime.fromisoformat("2026-10-04T00:00:01+08:00").timestamp() * 1000)
    first, second = (window_scope(shanghai, "7d", now_ts=t) for t in (morning, night))
    assert (first.from_ts, first.until_ts) == (second.from_ts, second.until_ts)
    # Covers 2026-09-27 .. 2026-10-03 local: [09-27 00:00, 10-04 00:00) Shanghai.
    assert first.until_ts == int(datetime.fromisoformat("2026-10-04T00:00:00+08:00").timestamp() * 1000)
    assert first.from_ts == int(datetime.fromisoformat("2026-09-27T00:00:00+08:00").timestamp() * 1000)
    assert first.contains(morning) and first.contains(night)
    moved = window_scope(shanghai, "7d", now_ts=tomorrow)
    assert moved.from_ts == first.from_ts + 86400000 and moved.until_ts == first.until_ts + 86400000
    # Re-anchoring on the computed end (what the worker does) is idempotent.
    again = window_scope(shanghai, "7d", now_ts=first.until_ts)
    assert (again.from_ts, again.until_ts) == (first.from_ts, first.until_ts)


def test_now_anchored_window_keeps_local_midnights_across_dst():
    berlin = Scope(display_timezone="Europe/Berlin")
    # DST ends 2026-10-25 03:00 -> 02:00 in Berlin; the 7 local days hold 7*24h + 1h.
    now = int(datetime.fromisoformat("2026-10-27T12:00:00+01:00").timestamp() * 1000)
    scope = window_scope(berlin, "7d", now_ts=now)
    assert scope.from_ts == int(datetime.fromisoformat("2026-10-21T00:00:00+02:00").timestamp() * 1000)
    assert scope.until_ts == int(datetime.fromisoformat("2026-10-28T00:00:00+01:00").timestamp() * 1000)
    assert scope.until_ts - scope.from_ts == 7 * 86400000 + 3600000


@pytest.mark.parametrize("scope,window", [(Scope(from_ts=1), "7d"),
                                         (Scope(until_ts=1), "all"), (Scope(), "bad")])
def test_conflicting_window_arguments_are_rejected(scope, window):
    with pytest.raises(ValueError):
        window_scope(scope, window)


def test_activity_handles_timezone_midnight_zero_days_and_separate_units():
    start = int(datetime.fromisoformat("2026-10-01T16:00:00+00:00").timestamp() * 1000)
    rhythm = {"human_messages": {"by_day": {"2026-10-02": 3}, "by_hour": {"0": 3},
                                 "time_unknown_n": 1}, "tool_calls": None, "model_requests": None}
    view = activity_view(rhythm, {"display_timezone": "Asia/Shanghai", "from_ts": start,
                                 "until_ts": start + 2 * 86400000})
    series = view["series"]["human_messages"]
    assert series["status"] == "partial"
    assert series["by_day"] == [
        {"date": "2026-10-02", "count": 3, "share": 1, "intensity": 1},
        {"date": "2026-10-03", "count": 0, "share": 0, "intensity": 0},
    ]
    assert len(series["by_hour"]) == 24
    assert view["series"]["tool_calls"]["by_day"] is None
    assert activity_view(None, {})["series"] is None


def test_huge_date_range_stays_sparse():
    source = {"by_day": {"2026-10-02": 1}, "by_hour": {"12": 1}, "time_unknown_n": 0}
    result = activity_view({"human_messages": source}, {"from_ts": 0, "until_ts": 10**15})
    assert result["calendar"] == "observed_days_only"
    assert len(result["series"]["human_messages"]["by_day"]) == 1


def test_ranks_keep_zero_unknown_and_deterministic_ties_separate():
    assert ranked_counts(None, basis="x")["rows"] is None
    assert ranked_counts({}, basis="x")["rows"] == []
    ranked = ranked_counts({"b": 1, "a": 1, "c": 2}, basis="observations", unknown_n=2)
    assert ranked["status"] == "partial"
    assert [r["name"] for r in ranked["rows"]] == ["c", "a", "b"]
    assert sum(r["share"] for r in ranked["rows"]) == 1

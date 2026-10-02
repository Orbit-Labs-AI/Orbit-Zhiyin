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

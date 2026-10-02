from tandem_backend import quota
from tandem_backend.quota.windows import parse_windows

from .conftest import DAY, HOUR, NOW


def codex_limits(used5=40, used_week=70, reset5=NOW + 2 * HOUR, reset_week=NOW + 3 * DAY):
    return {"primary": {"used_percent": used5, "window_minutes": 300,
                        "resets_at": reset5 // 1000},
            "secondary": {"used_percent": used_week, "window_minutes": 10080,
                          "resets_at": reset_week // 1000}}


def test_parse_windows_relative_and_absolute():
    ws = parse_windows({"snapshot": {"primary": {"used_percent": 5, "window_minutes": 300,
                                                 "resets_in_seconds": 60},
                                     "secondary": {"window_minutes": "x"}}}, 1000)
    assert ws == [{"window_minutes": 300, "window_kind": "five_hour", "used_percent": 5.0,
                   "resets_at": 61_000}]


def test_usage_groups_and_unknown_buckets(tandem):
    tandem.session("s1", agent="claude_code")
    tandem.session("s2", agent="codex", project="p2")
    tandem.model_call("s1", ts=NOW - HOUR, inp=100, out=50, cache_read=300, cost=0.01)
    tandem.model_call("s1", ts=NOW - 2 * DAY, model="claude-opus-4-5", inp=10, out=5)
    tandem.model_call("s2", ts=NOW - HOUR, model="gpt-5", inp=None, out=20, cost=0.02)
    tandem.model_call("s2", ts=NOW - 40 * DAY, model="gpt-5")  # Outside 30 days.
    with tandem.connect() as db:
        by_agent = quota.usage(db, group_by="agent", now_ms=NOW)
        by_model = quota.usage(db, group_by="model", now_ms=NOW)
        by_day = quota.usage(db, group_by="day", now_ms=NOW, excluded=["s2"])
    claude, codex = by_agent["rows"]
    assert claude["agent"] == "claude_code" and claude["requests"] == 2
    assert claude["tokens_total"] == 465 and claude["cost_usd"] is None
    assert claude["known_cost_usd"] == 0.01 and claude["cost_coverage"] == 0.5
    assert claude["cache_hit_rate"] == round(300 / 410, 4)
    assert codex["tokens_input"] is None and codex["tokens_total"] is None
    assert codex["known_tokens_total"] == 20 and codex["cost_usd"] == 0.02
    assert by_agent["totals"]["requests"] == 3
    assert [r["model"] for r in by_model["rows"]][0] == "claude-sonnet-4-5"
    assert next(r for r in by_model["rows"] if r["model"] == "gpt-5")["agents"] == ["codex"]
    assert [r["requests"] for r in by_day["rows"]] == [1, 1]
    assert by_day["rows"][0]["day"] < by_day["rows"][1]["day"]


def test_usage_empty_is_insufficient(tandem):
    with tandem.connect() as db:
        out = quota.usage(db, group_by="day", now_ms=NOW)
    assert out["rows"] == [] and out["basis"] == "insufficient"
    assert out["totals"]["tokens_total"] == 0 and out["totals"]["cost_usd"] is None


def test_codex_windows_latest_reset_and_stale(tandem):
    tandem.session("c1", agent="codex")
    tandem.limits("c1", ts=NOW - 3 * HOUR, windows=codex_limits(used5=10))
    tandem.limits("c1", ts=NOW - HOUR, windows=codex_limits(used5=40))
    with tandem.connect() as db:
        snap = quota.snapshot(db, NOW)
    five = next(w for w in snap["quota_window"] if w["window_kind"] == "five_hour")
    week = next(w for w in snap["quota_window"] if w["window_kind"] == "weekly")
    assert five["used_percent"] == 40 and five["headroom"] == 0.6 and week["used_percent"] == 70
    assert five["basis"] == "observed" and len(five["history"]) == 2
    assert five["pace"] == round(0.4 / 0.6, 3)  # 3h of 5h elapsed.
    codex = next(a for a in snap["agents"] if a["agent"] == "codex")
    assert codex["binding_window"] == "weekly" and codex["headroom"] == 0.3
    gemini = next(a for a in snap["agents"] if a["agent"] == "gemini")
    assert gemini["status"] == "insufficient"

    with tandem.connect() as db:  # After both resets: observed_reset with full headroom.
        later = quota.snapshot(db, NOW + 4 * DAY)
    assert {w["basis"] for w in later["quota_window"] if w["agent"] == "codex"} == {
        "observed_reset"}


def test_codex_stale_without_reset_time_is_insufficient(tandem):
    tandem.session("c1", agent="codex")
    tandem.limits("c1", ts=NOW - 6 * HOUR,
                  windows={"primary": {"used_percent": 50, "window_minutes": 300}})
    with tandem.connect() as db:
        snap = quota.snapshot(db, NOW)
    (w,) = [w for w in snap["quota_window"] if w["agent"] == "codex"]
    assert w["basis"] == "insufficient" and w["headroom"] is None


def test_claude_estimate_needs_history_then_uses_peak(tandem):
    tandem.session("s1", agent="claude_code")
    tandem.model_call("s1", ts=NOW - HOUR, inp=100, out=100)
    with tandem.connect() as db:
        short = quota.snapshot(db, NOW)
    five = next(w for w in short["quota_window"] if w["agent"] == "claude_code")
    assert five["basis"] == "insufficient" and five["active_tokens"] == 200

    tandem.model_call("s1", ts=NOW - 20 * DAY, inp=500, out=300, cache_read=10_000)
    with tandem.connect() as db:
        snap = quota.snapshot(db, NOW)
    five, week = [w for w in snap["quota_window"] if w["agent"] == "claude_code"]
    assert five["basis"] == "estimated_peak" and five["peak_tokens"] == 800  # cache_read excluded.
    assert five["used_percent"] == 25.0 and five["headroom"] == 0.75
    assert week["basis"] == "estimated_peak" and week["headroom"] == 0.75


def test_advice_prefers_most_headroom_and_hints_model(tandem):
    tandem.session("c1", agent="codex")
    tandem.session("s1", agent="claude_code")
    tandem.limits("c1", ts=NOW - HOUR, windows=codex_limits(used5=95, used_week=50))
    tandem.model_call("c1", ts=NOW - HOUR, model="gpt-5-codex")
    tandem.model_call("c1", ts=NOW - 2 * HOUR, model="gpt-5-codex")
    tandem.model_call("c1", ts=NOW - 3 * HOUR, model="gpt-5-codex")
    tandem.model_call("c1", ts=NOW - 4 * HOUR, model="gpt-5-mini")
    tandem.model_call("s1", ts=NOW - HOUR, inp=100, out=100)
    tandem.model_call("s1", ts=NOW - 20 * DAY, inp=500, out=300)
    with tandem.connect() as db:
        out = quota.advise(quota.snapshot(db, NOW), quota.model_mix(db, NOW))
    items = {i["agent"]: i for i in out["items"]}
    assert items["codex"]["verdict"] == "avoid"
    assert items["codex"]["model_hint"]["to"] == "gpt-5-mini"
    assert items["claude_code"]["verdict"] == "available"
    assert items["gemini"]["verdict"] == "insufficient"
    assert out["status"] == "partial"
    rec = out["recommendation"]
    assert rec["agent"] == "claude_code" and rec["kind"] == "workflow"
    assert rec["confidence"] == "low"


def test_advice_insufficient_without_data(tandem):
    with tandem.connect() as db:
        out = quota.advise(quota.snapshot(db, NOW), quota.model_mix(db, NOW))
    assert out["status"] == "insufficient" and out["recommendation"] is None
    assert all(i["verdict"] == "insufficient" for i in out["items"])

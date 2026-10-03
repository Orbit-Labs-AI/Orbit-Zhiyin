"""Real-data calibration (recs-B12 / B10 / B11): problem bars per scope, inventory confidence,
benefit-0 cards and tool-dict groups. All synthetic."""

import pytest
from test_engine import INPUTS, MEMORY, fake_recall, raw
from test_recommend_problems import inputs, signal

from tandem_backend.recommend import engine, problems
from tandem_backend.recommend.ranking import gates


def _failures(k, software="docker"):
    uids = [f"s{i}" for i in range(k)]
    return {"failures_by_software": [{"software": software, "error_class": "network", "count": 28 * 6,
                                      "sessions": k, "session_uids": uids}]}


def _big(facts, main=390):
    return inputs(facts=facts, sessions={"main": main, "weeks": 6})


def test_large_heterogeneous_user_is_not_held_to_five_percent_of_all_sessions():
    # 16 of 390 sessions: Wilson lower bound ≈ 0.025 < 0.05, but the bar shrinks with n.
    out = {p["key"]: p for p in problems.build(_big(_failures(16)))}
    docker = out["tool_env_failure:docker"]
    assert docker["status"] == "active" and docker["wilson_lo"] < .05
    assert docker["threshold"] < docker["wilson_lo"] and docker["denominator_all"] == 390
    assert problems.min_wilson_lo(10) == problems.MIN_WILSON_LO
    # three scattered sessions still are noise
    assert {p["key"]: p for p in problems.build(_big(_failures(3)))}["tool_env_failure:docker"]["status"] \
        == "below_threshold"


def test_problem_is_measured_against_its_software_and_project_population():
    facts = {**_failures(8), "scope_sessions": {"software": {"docker": 40}}}
    docker = {p["key"]: p for p in problems.build(_big(facts))}["tool_env_failure:docker"]
    assert docker["scope"] == {"basis": "software", "n": 40} and docker["denominator"] == 40
    assert docker["status"] == "active" and docker["vars"]["n"] == 40

    days = [{"session_uid": f"r{i}", "project_id": "small" if i < 12 else "big", "task_types": []}
            for i in range(390)]
    sigs = [signal("context_pressure", f"r{i}") for i in range(5)]
    loss = problems.build(inputs(signals=sigs, facts={"session_days": days},
                                 sessions={"main": 390, "weeks": 6}))[0]
    assert loss["scope"] == {"basis": "project", "n": 12} and loss["status"] == "active"


def test_tool_dict_groups_fold_generic_tools_and_name_real_software():
    sigs = [signal("tool_failures", f"r{i}", group={"tool": "exec_command", "kind": "shell"}) for i in range(3)]
    sigs += [signal("tool_failures", f"q{i}", group={"tool": "WebFetch", "kind": "web.fetch"}) for i in range(3)]
    keys = {p["key"]: p for p in problems.build(inputs(signals=sigs))}
    assert "tool_env_failure" in keys and "tool_env_failure:WebFetch" in keys
    assert not any("{" in key for key in keys)
    assert keys["tool_env_failure:WebFetch"]["vars"]["software"] == "WebFetch"


def test_evidence_gate_uses_the_problem_bar():
    docker = {p["key"]: p for p in problems.build(_big(_failures(16)))}["tool_env_failure:docker"]
    ok, reason = gates._evidence_ok({"problem": docker, "kind": "rule", "kb": {}}, {}, {})
    assert ok is True and reason == ""


def test_benefit_zero_cards_do_not_pass():
    inv = problems.build(inputs(
        inventory=[{"inv_id": "m1", "type": "mcp", "name": "figma", "enabled": True}],
        facts={"usage": {"skill": {}, "mcp": {}}},
        sessions={"main": 40, "weeks": 6, "first_ts": "2026-05-01T00:00:00Z", "last_ts": "2026-09-01T00:00:00Z"}))
    unused = next(p for p in inv if p["type"] == "installed_unused")
    assert unused["wilson_lo"] <= .9 and unused["vars"]["tokens_basis"] == "estimate"
    zero = raw("removal:x", kind="removal", dim="mcp", unit_minutes=0., prob={**unused, "weekly_count": 0})
    slate = engine.build_slate(INPUTS, MEMORY, recall=fake_recall([zero], [unused]))
    card = slate["candidates"][0]
    assert card["gates"]["passed"] is False and engine.NO_BENEFIT in card["gates"]["reasons"]


def test_signal_units_read_in_chinese_and_unknown_usage_is_not_unused():
    sig = signal("tool_failures", "r1", group={"tool": "WebFetch", "kind": "web.fetch"})
    sig["metrics"][0]["unit"] = "count"
    assert problems.build(inputs(signals=[sig]))[0]["unit"] == "次"
    window = {"main": 40, "weeks": 6, "first_ts": "2026-05-01T00:00:00Z", "last_ts": "2026-09-01T00:00:00Z"}
    inv = [{"inv_id": "c", "type": "skill", "name": "codex-skill", "status": "unknown_usage", "resident_tokens": 50},
           {"inv_id": "u", "type": "skill", "name": "idle", "status": "unused", "resident_tokens": 50}]
    keys = {p["key"] for p in problems.build(inputs(inventory=inv, facts={"usage": {"skill": {}, "mcp": {}}},
                                                    sessions=window))}
    assert "installed_unused:u" in keys and "installed_unused:c" not in keys


def test_merge_keeps_the_primary_problem_type():
    from tandem_backend.recommend.recall import multi

    def payload(ptype, lo):
        prob = {"type": ptype, "status": "active", "wilson_lo": lo, "weekly_count": 1, "key": ptype}
        return {"evidence": {"session_uids": ["a"], "signal_ids": [], "counts": {"sessions": 1}}, "problem": prob}

    merged = multi._merge("k", {"catalog": {"k": payload("tool_env_failure", .04)},
                                "hashed_lexical": {"k": payload("installed_unused", .58)}})
    assert merged["problem"]["type"] == "tool_env_failure"


def _independent_wilson_lo(k, n, z=1.96):
    # Wilson (1927) score interval lower bound, written out here independently of problems.wilson_lo
    p = k / n
    return (p + z * z / (2 * n) - z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** .5)) / (1 + z * z / n)


@pytest.mark.parametrize(("n", "bar", "min_k"), [(60, .05, 7), (200, .0273861, 11), (400, .0193649, 14)])
def test_relaxed_wilson_bar_minimum_k_table(n, bar, min_k):
    from tandem_backend.recommend.problems import min_wilson_lo

    # bar = .05 · √(60/n) above n = 60 (floor .01): √.3 = .547723, √.15 = .387298
    assert min_wilson_lo(n) == pytest.approx(bar, abs=1e-6)
    assert _independent_wilson_lo(min_k, n) >= bar > _independent_wilson_lo(min_k - 1, n)
    assert problems.wilson_lo(min_k, n) == pytest.approx(_independent_wilson_lo(min_k, n), abs=1e-9)
    assert min_wilson_lo(10 ** 6) == .01  # floor


def test_signal_without_metric_counts_evidence_not_one():
    sig = {"signal_id": "s1", "rule_id": "identical_retries", "reason": "r", "metrics": [],
           "scope": {"root_session_uid": "r1"},
           "evidence": [{"kind": "event", "session_uid": "r1", "id": "e1"},
                        {"kind": "event", "session_uid": "r1", "id": "e2"}]}
    bare = {**sig, "signal_id": "s2", "evidence": [], "scope": {"root_session_uid": "r2"}}
    out = problems.build(inputs(signals=[sig, bare], sessions={"main": 10, "weeks": 2}))[0]
    assert out["weekly_count"] == 1.0  # (2 evidence events + 0) / 2 weeks — no +1 per bare signal
    assert out["vars"]["count_basis"] == "evidence"


def test_short_window_uses_actual_days():
    from tandem_backend.recommend.problems import observed_weeks

    assert observed_weeks({"weeks": .5}) == .5
    assert observed_weeks({"first_ts": "2026-09-01T00:00:00Z", "last_ts": "2026-09-04T12:00:00Z"}) == .5
    assert observed_weeks({"weeks": .01}) == pytest.approx(1 / 7)  # never below one day
    assert observed_weeks({}) == 1.
    sig = [{"signal_id": f"s{i}", "rule_id": "identical_retries", "reason": "r",
            "metrics": [{"value": 1}], "scope": {"root_session_uid": f"r{i}"},
            "evidence": [{"session_uid": f"r{i}", "id": f"e{i}"}]} for i in range(3)]
    out = problems.build(inputs(signals=sig, sessions={"main": 10, "weeks": .5}))[0]
    assert out["weekly_count"] == 6.0  # 3 events in half a week, not 3 (old max(1, weeks))


@pytest.mark.parametrize(("current", "last", "changed"), [
    (8, None, False), (10, 10, False), (11, 10, False), (12, 10, True), (8, 10, True), (9, 10, False),
    (1, 0, True), (0, 0, False)])
def test_evidence_changed_twenty_percent(current, last, changed):
    from tandem_backend.recommend.ranking.gates import evidence_changed

    # |current − last| / max(last, 1) ≥ .2 ; session counts are integers: 12 vs 10 → .2, 11 vs 10 → .1
    assert evidence_changed(current, last) is changed


def _days(k, n):
    return [{"session_uid": f"d{i}", "task_types": ["a", "b", "c"] if i < k else ["a"]} for i in range(n)]


@pytest.mark.parametrize(("k", "n", "recurs"), [
    (2, 5, False),     # k < MIN_SESSIONS even though share .4
    (3, 10, True),     # share .30 ≥ MIXED_SHARE
    (3, 20, True),     # share .15, Wilson lo .05237 ≥ .05
    (3, 21, False),    # share .143, Wilson lo .04981 < .05
    (3, 100, False)])  # share .03, Wilson lo .01025
def test_mixed_recurs_boundaries(k, n, recurs):
    from tandem_backend.recommend.recall import templates

    data = {"sessions": {"main": n, "weeks": 4}, "facts": {"session_days": _days(k, n)}}
    assert templates._mixed_recurs(data) is recurs


def test_fact_sessions_above_main_are_truncated_and_not_active():
    # 12 failing sessions reported against 8 main sessions: k/n would read 12/12 = 100 %.
    out = {p["key"]: p for p in problems.build(_big(_failures(12), main=8))}["tool_env_failure:docker"]
    assert out["status"] == "insufficient"
    assert out["sessions"] == 8 and out["denominator_all"] == 8
    assert out["vars"]["count_mismatch"] == {"k_reported": 12, "main": 8}
    # without any session total the share is unknown as well
    none = {p["key"]: p for p in problems.build(_big(_failures(6), main=0))}["tool_env_failure:docker"]
    assert none["status"] == "insufficient" and none["vars"]["count_mismatch"]["main"] == 0
    # consistent counts carry no diagnostic: 6 of 8 → Wilson lo = 0.409 (hand: p=.75, z=1.96)
    ok = {p["key"]: p for p in problems.build(_big(_failures(6), main=8))}["tool_env_failure:docker"]
    assert ok["status"] == "active" and "count_mismatch" not in ok["vars"]
    assert ok["wilson_lo"] == pytest.approx(.4093, abs=1e-4)


@pytest.mark.parametrize(("first", "expected"), [
    ("2026-06-10T00:00:00Z", None),   # 83 days: features.linked says insufficient_history
    ("2026-06-03T00:00:00Z", .5),     # exactly 90 days: unused, confidence starts at .5
    ("2026-04-19T00:00:00Z", .7),     # 135 days: .5 + .4 × 45/90
    ("2026-01-01T00:00:00Z", .9),     # ≥ 180 days: capped at .9
])
def test_installed_unused_follows_the_linked_90_day_window(first, expected):
    inv = [{"inv_id": "m", "type": "mcp", "name": "figma", "enabled": True, "resident_tokens": 2100}]
    sessions = {"main": 40, "weeks": 6, "first_ts": first, "last_ts": "2026-09-01T00:00:00Z"}
    out = {p["key"]: p for p in problems.build(inputs(inventory=inv, facts={"usage": {"mcp": {}, "skill": {}}},
                                                      sessions=sessions))}
    unused = out.get("installed_unused:m")
    if expected is None:
        assert unused is None
    else:
        assert unused["status"] == "active" and unused["wilson_lo"] == pytest.approx(expected)


def test_linked_insufficient_history_is_not_unused():
    inv = [{"inv_id": "m", "type": "mcp", "name": "figma", "enabled": True, "resident_tokens": 2100,
            "status": "insufficient_history"}]
    sessions = {"main": 40, "weeks": 30, "first_ts": "2026-01-01T00:00:00Z", "last_ts": "2026-09-01T00:00:00Z"}
    keys = {p["key"] for p in problems.build(inputs(inventory=inv, facts={"usage": {"mcp": {}, "skill": {}}},
                                                    sessions=sessions))}
    assert "installed_unused:m" not in keys

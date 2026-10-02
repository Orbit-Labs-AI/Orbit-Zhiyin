"""Real-data calibration (recs-B12 / B10 / B11): problem bars per scope, inventory confidence,
benefit-0 cards and tool-dict groups. All synthetic."""

from test_engine import INPUTS, MEMORY, fake_recall, raw
from test_problems import inputs, signal

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
        sessions={"main": 40, "weeks": 6, "first_ts": "2026-07-01T00:00:00Z", "last_ts": "2026-09-01T00:00:00Z"}))
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
    window = {"main": 40, "weeks": 6, "first_ts": "2026-07-01T00:00:00Z", "last_ts": "2026-09-01T00:00:00Z"}
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
                                "dense": {"k": payload("installed_unused", .58)}})
    assert merged["problem"]["type"] == "tool_env_failure"

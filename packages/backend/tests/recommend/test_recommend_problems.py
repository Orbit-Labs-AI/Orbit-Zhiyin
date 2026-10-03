import pytest

from orbit_backend.recommend import problems
from orbit_backend.recommend.problems import wilson_lo


def signal(rule_id, root, *, group=None, value=2, project="p1"):
    scope = {"root_session_uid": root, "project_id": project}
    if group:
        scope["group"] = group
    return {"signal_id": f"{rule_id}-{root}", "rule_id": rule_id, "reason": f"{rule_id} in {root}",
            "metrics": [{"path": "x", "value": value, "unit": "次"}], "scope": scope,
            "evidence": [{"kind": "event", "session_uid": root, "id": f"ev-{root}"}]}


def inputs(**over):
    base = {"scope": "all", "scope_hash": "h", "agents": {"claude_code": 10}, "sessions": {"main": 10, "weeks": 2},
            "signals": [], "assessments": [], "tasks": [], "facts": {}, "inventory": None, "profile": None,
            "legacy_cards": []}
    return {**base, **over}


@pytest.mark.parametrize(("k", "n", "expected"), [(3, 10, .1078), (0, 10, 0.), (10, 10, .7225), (5, 5, .5655)])
def test_wilson_lower_bound_matches_known_values(k, n, expected):
    assert wilson_lo(k, n) == pytest.approx(expected, abs=5e-4)
    assert wilson_lo(1, 0) == 0


def test_rule_mapping_grouping_and_thresholds():
    sigs = [signal("identical_retries", f"r{i}") for i in range(3)] + [signal("tool_failures", "r9")]
    sigs += [signal("correction_density", "r1", group="deploy")]
    out = {p["key"]: p for p in problems.build(inputs(signals=sigs))}
    retry = out["tool_env_failure"]
    assert (retry["sessions"], retry["denominator"], retry["status"]) == (4, 10, "active")
    assert retry["weekly_count"] == 4.0 and retry["project_ids"] == ["p1"]
    assert retry["evidence"]["event_ids"] and retry["problem_id"] == problems.build(inputs(signals=sigs))[0]["problem_id"]
    assert out["wrong_approach:deploy"]["status"] == "below_threshold"
    few = problems.build(inputs(signals=sigs[:3], sessions={"main": 3, "weeks": 1}))
    assert few[0]["status"] == "insufficient" and few[0]["denominator"] == 3


def test_facts_become_permission_friction_and_software_failures():
    facts = {"readonly_prompts": [{"command_head": "git status", "count": 40, "sessions": 6, "session_uids": ["a", "b"]},
                                  {"command_head": "ls", "count": 20, "sessions": 4, "session_uids": ["c"]}],
             "readonly_prompt_sessions": 7,
             "failures_by_software": [{"software": "wrangler", "error_class": "auth", "count": 9, "sessions": 4,
                                       "session_uids": ["s1", "s2", "s3", "s4"]},
                                      {"software": "once", "error_class": "x", "count": 1, "sessions": 1}]}
    out = {p["key"]: p for p in problems.build(inputs(facts=facts))}
    perm = out["would_prompt:readonly_shell"]
    assert perm["type"] == "permission_friction" and perm["sessions"] == 7 and perm["status"] == "active"
    assert perm["weekly_count"] == 30 and perm["vars"]["heads"] == "git status、ls" and perm["vars"]["n_heads"] == 2
    assert out["tool_env_failure:wrangler"]["vars"]["software"] == "wrangler"
    assert "tool_env_failure:once" not in out


def test_inventory_resident_cost_and_installed_unused():
    inv = [{"inv_id": "i1", "type": "rule", "name": "AGENTS.md", "lines": 312, "resident_tokens": 3000},
           {"inv_id": "i2", "type": "mcp", "name": "figma", "enabled": True, "resident_tokens": 2100},
           {"inv_id": "i3", "type": "skill", "name": "used", "resident_tokens": 100}]
    facts = {"usage": {"skill": {"used": {"calls": 4}}, "mcp": {}}}
    sessions = {"main": 20, "weeks": 4, "first_ts": "2026-08-01T00:00:00Z", "last_ts": "2026-09-01T00:00:00Z"}
    out = {p["key"]: p for p in problems.build(inputs(inventory=inv, facts=facts, sessions=sessions))}
    assert out["resident_cost:rules_file:AGENTS.md"]["vars"]["lines"] == 312
    unused = out["installed_unused:i2"]
    # An inventory fact is a measurement: fixed confidence, not a Wilson bound with k == n (≈ 0.99).
    assert unused["sessions"] == unused["denominator"] == 20 and unused["wilson_lo"] < round(wilson_lo(20, 20), 4)
    assert unused["scope"]["basis"] == "inventory" and .5 <= unused["wilson_lo"] <= .9
    assert "resident_cost:i2" in out and not any(k.endswith(":i3") for k in out)
    short = {**sessions, "last_ts": "2026-08-05T00:00:00Z"}
    assert "installed_unused:i2" not in {p["key"] for p in problems.build(inputs(inventory=inv, facts=facts, sessions=short))}


def test_legacy_cards_and_muted_types():
    cards = [{"rule_id": "long_response", "root_session_uid": f"r{i}"} for i in range(4)]
    out = problems.build(inputs(legacy_cards=cards, signals=[signal("context_pressure", "r1")]))
    assert {p["type"] for p in out} == {"communication_gap", "context_loss"}
    muted = problems.build(inputs(legacy_cards=cards), {"muted_problem_types": ["communication_gap"]})
    assert muted == []


def test_installed_unused_skips_items_without_usage_attribution():
    inv = [{"inv_id": "cx", "type": "skill", "name": "codex-skill", "agent": "codex",
            "usage": {"attributable": False, "basis": "usage_unavailable"}},
           {"inv_id": "cc", "type": "skill", "name": "claude-skill", "agent": "claude_code",
            "usage": {"attributable": True, "basis": "tool_call.skill"}}]
    facts = {"usage": {"skill": {"other": {"calls": 3}}, "mcp": {}}}
    sessions = {"main": 20, "weeks": 4, "first_ts": "2026-08-01T00:00:00Z", "last_ts": "2026-09-01T00:00:00Z"}
    keys = {p["key"] for p in problems.build(inputs(inventory=inv, facts=facts, sessions=sessions))}
    assert "installed_unused:cc" in keys and "installed_unused:cx" not in keys

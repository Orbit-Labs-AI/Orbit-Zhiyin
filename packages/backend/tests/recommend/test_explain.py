"""explain.explain_candidate on hand-built rows (service stack): status, evidence, score and tier
rules checked against values derived by hand, not against another run of the pipeline."""

from types import SimpleNamespace

import pytest
from test_ranking import resource, state

from orbit_backend.recommend.explain import explain_candidate


def sig(sid, tier="reported", evidence=None, caps=("debugging",), metrics=("repeat_rate",)):
    return {"signal_id": sid, "rule_id": "identical_retries", "severity": .8, "confidence": .9,
            "capabilities": list(caps), "evidence_tier": tier, "reason": f"{sid} reason",
            "metrics": [{"path": "x", "value": 3}], "scope": {"root_session_uid": "synthetic-session"},
            "hypothesis": "重复失败可能来自环境差异", "evaluation_metrics": list(metrics),
            "evidence": evidence if evidence is not None else
            [{"kind": "tool_call", "session_uid": "synthetic-session", "id": f"{sid}-call"}]}


def row(*, signals=None, grounded=None, pending=(), compat="manual", score=.4567, family_pending=(), item=None,
        scenarios=None):
    signals = signals or [sig("s1")]
    current = state(signals=signals,
                    context_state={"agent": "codex", **({"benefit_scenarios": scenarios} if scenarios else {})})
    return {"item": item or resource(), "signal": signals[0],
            "features": {"grounded_signal_ids": grounded if grounded is not None else [s["signal_id"] for s in signals],
                         "preference_matches": []},
            "filter": SimpleNamespace(pending_requirements=list(pending), compatibility=compat),
            "state": current, "score": score, "score_breakdown": {"x": 1.},
            "candidate": SimpleNamespace(route_scores={"rules": 1.}, route_ranks={"rules": 1}, fusion_score=1 / 61),
            "family_pending": list(family_pending)}


def test_status_follows_pending_then_adaptation_then_trial():
    pending = explain_candidate(row(pending=["tools:pytest"], family_pending=["agent:codex", "tools:pytest"]))
    assert pending["recommendation_status"] == "needs_context" and pending["compatibility"] == "unknown"
    assert pending["declared_compatibility"] == "manual"
    assert pending["pending_requirements"] == ["agent:codex", "tools:pytest"]  # merged, de-duplicated, sorted
    assert pending["setup_steps"][0] == "先确认以下条件：agent:codex、tools:pytest"
    adapt = explain_candidate(row(compat="adaptation_required"))
    assert adapt["recommendation_status"] == "adaptation_required" and adapt["compatibility"] == "adaptation_required"
    assert "agent_adaptation" in adapt["benefit_estimate"]["conditions"]
    trial = explain_candidate(row())
    assert trial["recommendation_status"] == "trial" and trial["setup_steps"] == resource().action.setup_steps


def test_priority_is_the_score_on_a_percent_scale_with_its_meaning():
    out = explain_candidate(row(score=.4567))
    assert out["priority_score"] == 45.67
    assert "不是效果百分比" in out["score_meaning"] and out["calibrated_utility_probability"] is None
    assert out["effect_status"] == "unmeasured" and out["explanation"]["expected_effect"]["targets"]


def test_evidence_only_from_grounded_signals_deduplicated_and_sorted():
    shared = {"kind": "tool_call", "session_uid": "a", "id": "c-2"}
    s1 = sig("s1", evidence=[shared, {"kind": "event", "session_uid": "a", "id": "e-9"}])
    s2 = sig("s2", evidence=[shared])
    s3 = sig("s3", evidence=[{"kind": "event", "session_uid": "z", "id": "ungrounded"}])
    out = explain_candidate(row(signals=[s1, s2, s3], grounded=["s1", "s2"]))
    # sorted by (kind, session_uid, id): event < tool_call
    assert [e["id"] for e in out["evidence"]] == ["e-9", "c-2"]
    assert out["explanation"]["bottleneck_ids"] == ["s1", "s2"]
    assert out["matched_capabilities"] == ["debugging"]


@pytest.mark.parametrize(("tiers", "expected"), [
    (["reported", "reported"], "reported"),
    (["model_inferred", "model_inferred"], "model_inferred"),
    (["model_inferred", "reported"], "mixed"),
])
def test_evidence_tier(tiers, expected):
    signals = [sig(f"s{i}", tier=t) for i, t in enumerate(tiers)]
    assert explain_candidate(row(signals=signals))["evidence_tier"] == expected


def test_no_grounded_signal_is_reported_tier_with_no_evidence():
    out = explain_candidate(row(grounded=[]))
    assert out["evidence"] == [] and out["evidence_tier"] == "reported" and out["matched_capabilities"] == []


def test_github_source_links_the_pinned_file():
    out = explain_candidate(row())
    assert out["source"]["source_url"] == ("https://github.com/example/repo/blob/" + "a" * 40
                                           + "/skills/debug/SKILL.md")


def test_benefit_without_scenarios_is_not_estimated():
    out = explain_candidate(row())
    assert out["benefit_estimate"]["status"] == "insufficient_inputs"


def test_ids_are_stable_and_agent_specific():
    a, b = explain_candidate(row()), explain_candidate(row())
    assert a["id"] == b["id"] and a["target_agent"] == "codex"
    assert a["evaluation_plan"]["target_metrics"] == ["repeat_rate"]

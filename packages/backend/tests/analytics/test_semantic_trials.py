"""Constructed shared model observations can nominate trials without human labels."""

import hashlib

import pytest

from orbit_backend.analytics.inputs import Scope
from orbit_backend.analytics.semantic_cascade import Budget, attach_cache, run_cascade
from orbit_backend.analytics.service import analyze_bundle
from orbit_backend.recommend.service import recommend


def observed_bundle(fixtures, *, known=8, corrected=3, unknown=0, unresolved=False):
    _, event, bundle = fixtures
    events = []
    for i in range(known + unknown):
        delivery = event("已交付", f"d-{i}", i * 2, ts=100 + i * 20, task_uid="task")
        delivery.update(kind="message.assistant", actor="assistant")
        delivery["attrs"]["phase"] = "final"
        events.append(delivery)
        events.append(
            event(
                "这里不对，请修改" if i < corrected else "请继续执行",
                f"u-{i}",
                i * 2 + 1,
                ts=110 + i * 20,
                task_uid="task",
            )
        )

    def provider(batch, _budget):
        observations = []
        for candidate in batch:
            i = int(candidate["event_uid"].split("-")[1])
            correction = i < corrected
            observations.append(
                {
                    "session_uid": candidate["session_uid"],
                    "event_uid": candidate["event_uid"],
                    "intents": ["correction" if correction else "request"] if i < known else [],
                    "intent_quote": candidate["text"] if i < known else None,
                    "target_event_uid": f"d-{i}" if correction and not unresolved else None,
                    "friction_types": ["scope"] if correction and not unresolved else [],
                    "controls": [],
                    "feedback": None,
                    "abstention_reason": "ambiguous" if i >= known else None,
                }
            )
        return {"observations": observations}, {"constructed_provider": True}

    cache = run_cascade(events, {"s"}, provider, Budget())
    assert cache["diagnostics"]["parsed_messages"] == known + unknown
    return bundle(attach_cache(events, {"s"}, cache))


def skill():
    preview = "Synthetic scope intervention."
    return {
        "identity": {"id": "scope-skill", "name": "scope-skill"},
        "family": "skills",
        "target_task": {"text": "scope alignment"},
        "trigger": {"rule_ids": ["correction_density"]},
        "capability": {"text": preview, "tags": ["scope_alignment"]},
        "expected_effect": {"targets": {"correction_density": 1.0}},
        "compatibility": {"agents": {"codex": "native"}},
        "friction": {"setup_cost": 0.0},
        "evidence_quality": {
            "status": "reviewed",
            "score": 1.0,
            "reviewed_by": "constructed-reviewer",
        },
        "source": {
            "origin": "local",
            "status": "verified",
            "content_sha256": hashlib.sha256(preview.encode()).hexdigest(),
        },
        "action": {
            "preview": preview,
            "setup_steps": ["Try on the constructed task."],
            "trial": "Use the same task checkpoint in treatment and control.",
        },
    }


def test_shared_inferred_corrections_nominate_bounded_trial_but_never_confirm_outcome(fixtures):
    data = analyze_bundle(observed_bundle(fixtures), with_text=False)
    interaction = data["bottleneck_features"]["interaction"]
    assert interaction["effective_samples"]["intent_messages"] == 0
    assert interaction["confirmed_correction_count"] is None
    assert interaction["semantic_observations"]["correction_count"] == 3
    result = recommend(data, catalog=[skill()], context={"agent": "codex"})
    card = result["recommendations"][0]
    assert card["evidence_tier"] == "model_inferred"
    assert card["effect_status"] == "unmeasured"
    assert card["calibrated_utility_probability"] is None
    assert card["recommendation_status"] == "trial"
    assert all(m["path"].startswith("interaction.semantic_observations") for m in card["metrics"])
    assert card["evaluation_plan"]["observed_effect"] is None
    assert data["bottleneck_features"]["outcome"]["task_success"] is None
    assert all(
        s["calibrated_probability"] is None
        for s in result["signals"]
        if s.get("evidence_tier") == "model_inferred"
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"known": 7},
        {"corrected": 2},
        {"known": 13, "corrected": 3},
        {"unknown": 6},
        {"unresolved": True},
    ],
)
def test_unresolved_targets_and_insufficient_cohorts_cannot_trigger_trial(fixtures, arguments):
    data = analyze_bundle(observed_bundle(fixtures, **arguments), with_text=False)
    result = recommend(data, catalog=[skill()], context={"agent": "codex"})
    assert result["recommendations"] == []
    assert not any(s.get("evidence_tier") == "model_inferred" for s in result["signals"])


def test_future_context_or_cache_observation_cannot_support_earlier_trial(fixtures):
    data = analyze_bundle(observed_bundle(fixtures), Scope(until_ts=140), with_text=False)
    result = recommend(data, catalog=[skill()], context={"agent": "codex"})
    assert result["recommendations"] == []

"""P0 integration acceptance using fictional conversations and temporary catalogues."""

import hashlib
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.recommendations.diagnosis import diagnose_bottlenecks
from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.api import create_app
from tandem_backend.recommend.service import recommend


def correction_bundle(roots=None, *, friction="scope"):
    """Each tuple is (root ID, observed human messages, confirmed corrections)."""
    sessions, events = [], []
    for sid, count, corrected in roots or [("fictional-a", 8, 3)]:
        sessions.append({"session_uid": sid, "root_uid": sid, "kind": "main",
                         "project_id": "fictional-project", "started_at": 0})
        target = sid + "-delivery"
        events.append({"event_uid": target, "session_uid": sid, "turn_uid": sid + "-turn", "seq": 0,
                       "kind": "message.assistant", "actor": "assistant", "ts": 100,
                       "attrs": {"task_uid": sid + "-task"}})
        for index in range(count):
            label = {"state": "confirmed", "source": "synthetic-reviewer", "available_at": 100,
                     "intents": ["correction" if index < corrected else "request"], "requirements": []}
            if index < corrected:
                label.update(target_event_uid=target, evidence_event_uids=[target], friction_types=[friction])
            events.append({"event_uid": f"{sid}-human-{index}", "session_uid": sid,
                           "turn_uid": sid + "-turn", "seq": index + 1, "ts": 110 + 10 * index,
                           "kind": "message.user", "actor": "human", "text": "fictional request",
                           "attrs": {"origin": "human", "task_uid": sid + "-task", "interaction": label}})
    return AnalysisInputBundle(
        sessions=sessions, events=events, tool_calls=[], model_calls=[],
        coverage={key: {"status": "available"} for key in
                  ("sessions", "events", "tool_calls", "model_calls", "turns", "projects", "lineage")},
        versions={"content_digest": "synthetic-pipeline-acceptance"},
    )


def ready_item(uid="synthetic-skill", family="skills", **updates):
    preview = "Synthetic intervention for testing the recommendation boundary."
    value = {
        "identity": {"id": uid, "name": uid}, "family": family,
        "target_task": {"text": "pytest Python scope alignment"},
        "trigger": {"rule_ids": ["correction_density"]},
        "capability": {"text": "Explicit scope and acceptance checks", "tags": ["scope_alignment"]},
        "expected_effect": {"targets": {"correction_density": 1.0}},
        "compatibility": {"agents": {"codex": "native", "generic": "manual"}},
        "friction": {"setup_cost": 0.0},
        "evidence_quality": {"status": "reviewed", "score": 1.0, "reviewed_by": "synthetic-reviewer"},
        "source": {"origin": "local", "status": "verified",
                   "content_sha256": hashlib.sha256(preview.encode()).hexdigest()},
        "action": {"preview": preview, "setup_steps": ["Try only on this fictional task."],
                   "trial": "Compare the same synthetic task before and after the intervention."},
    }
    value.update(updates)
    return value


def write_family(directory, family, items):
    (directory / (family + ".json")).write_text(json.dumps({
        "schema_version": "recommendation-catalog-v1", "family": family, "items": items,
    }), encoding="utf-8")


@pytest.fixture
def analyzed():
    return analyze_bundle(correction_bundle(), with_text=False)


def test_explicit_empty_catalogue_never_falls_back_to_bundled_resources(tmp_path, analyzed):
    # First establish that the very same synthetic signals would find seed items.
    assert recommend(analyzed, context={"agent": "codex"})["recommendations"]
    empty_directory = recommend(analyzed, catalog_directory=tmp_path, context={"agent": "codex"})
    empty_list = recommend(analyzed, catalog=[], context={"agent": "codex"})
    for result in (empty_directory, empty_list):
        assert result["signals"]
        assert result["status"] == "no_matching_resources"
        assert result["recommendations"] == []
    assert len([d for d in empty_directory["diagnostics"] if d.get("reason") == "missing"]) == 7


def test_partial_catalogue_ranks_reviewed_items_and_excludes_drafts(tmp_path, analyzed):
    strong = ready_item("reviewed-strong")
    weaker = ready_item("reviewed-weaker", evidence_quality={
        "status": "reviewed", "score": .2, "reviewed_by": "synthetic-reviewer",
    }, friction={"setup_cost": 1.0})
    draft = ready_item("draft-not-ready", source={"status": "draft"}, evidence_quality={"status": "draft"})
    write_family(tmp_path, "skills", [weaker, draft, strong, {"identity": {"id": "malformed"}}])
    result = recommend(analyzed, catalog_directory=tmp_path, context={"agent": "codex"})
    assert result["status"] == "ready"
    cards = result["recommendations"]
    assert [card["resource_id"] for card in cards] == ["reviewed-strong", "reviewed-weaker"]
    assert cards[0]["priority_score"] > cards[1]["priority_score"]
    assert all(card["effect_status"] == "unmeasured" and card["evidence"] for card in cards)
    assert any(row["resource_id"] == "draft-not-ready" for row in result["excluded_resources"])
    assert any(row.get("resource_id") == "malformed" and row["reason"] == "invalid_item"
               for row in result["diagnostics"])


def test_matching_keywords_and_context_cannot_replace_bottleneck_evidence():
    analysis = analyze_bundle(correction_bundle([("fictional-a", 8, 0)]), with_text=False)
    result = recommend(analysis, catalog=[ready_item()], context={
        "agent": "codex", "languages": ["Python"], "tools": ["pytest"],
    })
    assert "pytest" in result["states"][0]["task_text"]
    assert result["signals"] == []
    assert result["recommendations"] == []


def test_two_small_roots_cannot_pool_samples_into_one_recommendation():
    analysis = analyze_bundle(correction_bundle([("fictional-a", 4, 2), ("fictional-b", 4, 2)]), with_text=False)
    result = recommend(analysis, catalog=[ready_item()])
    assert len(result["states"]) == 2
    assert result["signals"] == []
    assert result["recommendations"] == []


def test_recommendation_and_its_evidence_remain_with_the_triggering_root():
    analysis = analyze_bundle(correction_bundle([("fictional-a", 8, 3), ("fictional-b", 8, 0)]), with_text=False)
    result = recommend(analysis, catalog=[ready_item()])
    assert result["recommendations"]
    assert all(card["scope"]["root_session_uid"] == "fictional-a" for card in result["recommendations"])
    assert all(ref["session_uid"] == "fictional-a" for card in result["recommendations"] for ref in card["evidence"])
    second = next(row for row in result["states"] if row["root_session_uid"] == "fictional-b")
    assert second["signals"] == [] and second["bottleneck_vector"] == {}


def test_reusing_diagnosis_from_a_different_feature_snapshot_is_rejected(analyzed):
    diagnosis = diagnose_bottlenecks(analyzed)
    changed = deepcopy(analyzed)
    changed["sessions"][0]["bottleneck_features"]["interaction"]["confirmed_correction_count"] = 100
    # Even an unchanged outer analysis_digest cannot conceal changed features.
    assert changed["analysis_digest"] == analyzed["analysis_digest"]
    with pytest.raises(ValueError, match="snapshot"):
        recommend(changed, bottlenecks=diagnosis, catalog=[ready_item()])


def test_supplied_diagnosis_cannot_cross_root_evidence_boundaries():
    analysis = analyze_bundle(correction_bundle([("fictional-a", 8, 3), ("fictional-b", 8, 0)]), with_text=False)
    diagnosis = diagnose_bottlenecks(analysis)
    diagnosis["signals"][0]["evidence"][0]["session_uid"] = "fictional-b"
    with pytest.raises(ValueError, match="crosses root"):
        recommend(analysis, bottlenecks=diagnosis, catalog=[ready_item()])


def test_missing_hook_metadata_is_context_needed_not_native_readiness(analyzed):
    result = recommend(analyzed, catalog=[ready_item("unfinished-hook", "hooks")], context={"agent": "codex"})
    card = result["recommendations"][0]
    assert card["declared_compatibility"] == "native"
    assert card["compatibility"] == "unknown"
    assert card["recommendation_status"] == "needs_context"
    assert set(card["pending_requirements"]) >= {
        "family_features.event", "family_features.condition", "family_features.action",
    }


def test_explicit_permission_denial_excludes_an_otherwise_matching_intervention(analyzed):
    denied = ready_item("denied-skill", risk_permission={"required_permissions": ["filesystem_write"]})
    allowed = ready_item("allowed-skill")
    result = recommend(analyzed, catalog=[denied, allowed], context={
        "agent": "codex", "denied_permissions": ["filesystem_write"],
    })
    assert [card["resource_id"] for card in result["recommendations"]] == ["allowed-skill"]
    exclusion = next(row for row in result["excluded_resources"] if row["resource_id"] == "denied-skill")
    assert "permission_denied:filesystem_write" in exclusion["details"]


@pytest.mark.parametrize(("friction", "capability"), [("execution", "debugging"), ("verification", "verification")])
def test_legacy_correction_resources_follow_friction_not_the_broad_rule_id(friction, capability):
    analysis = analyze_bundle(correction_bundle(friction=friction), with_text=False)
    result = recommend(analysis, context={"agent": "codex"}, limit=20)
    assert result["recommendations"]
    assert {signal["rule_id"] for signal in result["signals"]} == {"correction_density"}
    assert "tandem-scope-brief" not in {card["resource_id"] for card in result["recommendations"]}
    assert all(capability in card["matched_capabilities"] for card in result["recommendations"])


def test_pipeline_does_not_mutate_caller_analysis_context_or_catalogue(analyzed):
    catalogue = [ready_item()]
    context = {"agent": "codex", "tools": ["pytest"]}
    before = deepcopy((analyzed, catalogue, context))
    first = recommend(analyzed, catalog=catalogue, context=context)
    second = recommend(analyzed, catalog=catalogue, context=context)
    assert (analyzed, catalogue, context) == before
    assert first == second
    json.dumps(first, allow_nan=False)


def test_api_configured_empty_directory_does_not_fall_back_to_seeds(tmp_path, monkeypatch):
    catalog_directory = tmp_path / "catalogue"
    catalog_directory.mkdir()
    bundle = correction_bundle()
    monkeypatch.setattr("tandem_backend.analytics.service.analyze_store",
                        lambda store, scope, with_text: analyze_bundle(bundle, scope, with_text))
    with TestClient(create_app(db=tmp_path / "synthetic.sqlite", recommendation_catalog=catalog_directory)) as client:
        for response in (client.get("/v1/analytics/recommendations?target_agent=codex"),
                         client.post("/v1/analytics/recommendations", json={"context": {"agent": "codex"}})):
            assert response.status_code == 200
            result = response.json()["bottleneck_recommendations"]
            assert result["signals"]
            assert result["recommendations"] == []
            assert result["status"] == "no_matching_resources"


def test_api_family_filter_context_and_selected_root_reach_pipeline(tmp_path, monkeypatch):
    catalog_directory = tmp_path / "catalogue"
    catalog_directory.mkdir()
    write_family(catalog_directory, "skills", [ready_item("skill")])
    write_family(catalog_directory, "hooks", [ready_item(
        "hook", "hooks", requirements={"tools": ["pytest"]},
        risk_permission={"required_permissions": ["filesystem_write"]},
        family_features={"event": "PostToolUse", "condition": "synthetic condition", "action": "synthetic action"},
    )])
    bundle = correction_bundle([("fictional-a", 8, 3), ("fictional-b", 8, 3)])
    calls = []

    def scoped_analysis(store, scope, with_text):
        calls.append((scope, with_text))
        return analyze_bundle(bundle, scope, with_text)

    monkeypatch.setattr("tandem_backend.analytics.service.analyze_store", scoped_analysis)
    with TestClient(create_app(db=tmp_path / "synthetic.sqlite", recommendation_catalog=catalog_directory)) as client:
        route = "/v1/analytics/recommendations?root_session_uids=fictional-b"
        fetched = client.get(route + "&family=hooks&target_agent=codex")
        assert fetched.status_code == 200
        card = fetched.json()["bottleneck_recommendations"]["recommendations"][0]
        assert card["resource_id"] == "hook" and card["family"] == "hooks"
        assert card["scope"]["root_session_uid"] == "fictional-b"
        assert card["recommendation_status"] == "needs_context"
        payload = {"family": "hooks", "context": {"agent": "codex", "tools": ["pytest"],
                                                      "permissions": ["filesystem_write"]}}
        supplied = client.post(route, json=payload)
        assert supplied.status_code == 200
        card = supplied.json()["bottleneck_recommendations"]["recommendations"][0]
        assert card["recommendation_status"] == "trial" and card["compatibility"] == "native"
        assert card["scope"]["root_session_uid"] == "fictional-b"
        assert all(ref["session_uid"] == "fictional-b" for ref in card["evidence"])
        payload["context"]["denied_permissions"] = ["filesystem_write"]
        denied = client.post(route, json=payload)
        assert denied.status_code == 200
        assert denied.json()["bottleneck_recommendations"]["recommendations"] == []
    assert len(calls) == 3
    assert all(scope.root_session_uids == ["fictional-b"] and with_text is False for scope, with_text in calls)


def test_analysis_time_scope_is_preserved_in_supplied_diagnosis():
    analysis = analyze_bundle(correction_bundle(), Scope(until_ts=130), with_text=False)
    result = recommend(analysis, catalog=[ready_item()])
    assert result["scope"]["until_ts"] == 130
    assert result["recommendations"] == []
    assert result["signals"] == []

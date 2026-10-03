import json

import pytest

from orbit_catalog.contracts import Page, Record, Resource
from orbit_catalog.service import CatalogService


@pytest.fixture
def skill_smoke(monkeypatch):
    from evals.recommendation.skills import run

    return run


def seed(home):
    service = CatalogService(home / "catalog.db")
    try:
        for source in ("anthropic-skills", "awesome-copilot"):
            job = service.store.begin_run(source)
            records = [Record(native_id=kind, resource=Resource(
                item_id=source + ":" + kind, type=kind, name="pytest testing", summary="Debug tests",
                url="https://github.com/example/skills/blob/" + "a" * 40 + "/skills/testing/SKILL.md",
                repo_path="skills/testing/SKILL.md", commit_sha="a" * 40,
                body="Run pytest to investigate failing tests.", body_policy="licensed", license="MIT",
            )) for kind in ("skill", "plugin")]
            service.store.stage(job["run_id"], Page(records=records, complete=True, revision="a" * 40))
            service.store.publish(job["run_id"])
    finally:
        service.close()


def test_offline_export_uses_selected_skills_without_promoting_source_claims(tmp_path, monkeypatch, skill_smoke):
    seed(tmp_path)

    def no_network(*args, **kwargs):
        raise AssertionError("Offline smoke must not fetch")

    monkeypatch.setattr("orbit_catalog.network.HttpClient.get", no_network)
    result = skill_smoke(tmp_path, ["anthropic-skills"], query="pytest")
    assert result["skill_count"] == result["accepted_drafts"] == result["search_hits"] == 1
    assert result["recommendation_count"] == 0
    assert result["synthetic_baseline_count"] > 0
    raw = json.loads((tmp_path / "skills.raw.json").read_text())["items"]
    assert [row["resource"]["item_id"] for row in raw] == ["anthropic-skills:skill"]
    item = json.loads((tmp_path / "recommend/skills.json").read_text())["items"][0]
    assert item["evidence_quality"]["status"] == item["source"]["status"] == "draft"
    assert item["source"]["verified_sha"] == "a" * 40
    assert item["trigger"]["rule_ids"] == []


@pytest.mark.parametrize("status", ["failed", "paused"])
def test_incomplete_fetch_cannot_be_reported_as_success(tmp_path, monkeypatch, status, skill_smoke):
    seed(tmp_path)
    monkeypatch.setattr("orbit_catalog.sync.CatalogSync.sync", lambda *a, **kw: [
        {"source_id": "anthropic-skills", "status": status},
    ])
    with pytest.raises(ValueError, match="failed or paused"):
        skill_smoke(tmp_path, ["anthropic-skills"], fetch=True)
    assert not (tmp_path / "skills.raw.json").exists()
    assert json.loads((tmp_path / "sync.json").read_text())[0]["status"] == status


def test_empty_catalog_needs_explicit_fetch(tmp_path, skill_smoke):
    with pytest.raises(ValueError, match="--fetch first"):
        skill_smoke(tmp_path, ["anthropic-skills"])


def test_failed_refresh_in_backoff_cannot_pass_using_old_snapshot(tmp_path, skill_smoke):
    seed(tmp_path)
    service = CatalogService(tmp_path / "catalog.db")
    try:
        job = service.store.begin_run("anthropic-skills")
        service.store.finish_interrupted(job["run_id"], "http_429", retry_after=300)
    finally:
        service.close()
    with pytest.raises(ValueError, match="failed refresh"):
        skill_smoke(tmp_path, ["anthropic-skills"], fetch=True)
    assert json.loads((tmp_path / "sync.json").read_text())[0]["status"] == "not_due"

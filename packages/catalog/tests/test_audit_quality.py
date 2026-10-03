"""Regression cases from source/retrieval audit; all documents and vectors are synthetic."""

import gzip
import json

import pytest

from orbit_catalog.contracts import MatchRequest, Resource, SourceSpec
from orbit_catalog.features import extract
from orbit_catalog.quality import assess
from orbit_catalog.service import CatalogService
from orbit_catalog.snapshot import FORMAT
from orbit_catalog.sources.github import file_kind
from orbit_catalog.vectors import index_embeddings

from .test_retrieval import ToyEncoder
from .test_storage import publish, record


def test_quality_is_observable_metadata_not_effectiveness():
    sparse = assess({"official": True, "license": "NOASSERTION", "version_id": "local-hash"})
    assert sparse["score"] == 0 and sparse["official"]
    assert sparse["effect_status"] == "unmeasured" and sparse["security_status"] == "not_audited"
    documented = assess({"verification": "repository_and_source_read", "license": "MIT", "body_policy": "licensed",
                         "body_len": 50, "agents": '["codex"]', "url": 'https://github.com/acme/repo/blob/' + 'a' * 40 + '/SKILL.md'})
    assert documented["level"] == "documented" and documented["score"] == 1


def test_hook_classifier_excludes_website_data_and_hook_dependency_files():
    assert file_kind("docs-site/src/data/hooks.json") is None
    assert file_kind("hooks/package.json") is None
    assert file_kind("plugins/x/hooks/claude-hooks.json") == "hook"
    assert file_kind("hooks/continual-learning/hooks.json") == "hook"
    assert file_kind("hooks.json") == "hook"


def test_extra_dimensions_remain_extracted_not_curated():
    resource = Resource(item_id="x", type="skill", name="Test-driven review", url="https://example.org",
                        summary="Create an implementation plan and architecture diagram with regression tests")
    found = {(f.feature, f.value): f for f in extract(resource)}
    assert {("task_phase", "plan"), ("task_phase", "verify"), ("artifact", "diagram"), ("practice", "test_driven")} <= found.keys()
    assert all(found[k].origin == "extracted" for k in found if k[0] in {"task_phase", "artifact", "practice"})


@pytest.mark.parametrize("batch", [False, True])
def test_encoder_failure_keeps_independent_retrieval(tmp_path, batch):
    encoder = ToyEncoder()
    service = CatalogService(tmp_path / "catalog.db", encoder=encoder)
    try:
        service.store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
        publish(service.store, [record("retry")])
        index_embeddings(service.store, encoder)
        def broken(*a, **kw):
            raise RuntimeError("invalid local weights")
        encoder.encode = broken
        requests = [MatchRequest(text="debugging regression"), MatchRequest(text="重复失败 now")]
        results = service.match_many(requests) if batch else [service.match(r) for r in requests]
        assert all(r["items"] and r["vector"]["status"] == "unavailable" for r in results)
        assert all(r["routes"]["lexical"] > 0 for r in results)
    finally:
        service.close()


def test_search_preserves_review_language_and_explicit_support(tmp_path):
    service = CatalogService(tmp_path / "catalog.db")
    try:
        service.store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
        publish(service.store, [record("reviewed", language="en", metadata={"verification": "repository_and_source_read",
                                               "agent_support": {"codex": "native"}})])
        item = service.match(MatchRequest(text="debug"))["items"][0]
        assert item["verification"] == "repository_and_source_read" and item["language"] == "en"
        assert item["support"] == {"codex": "native"} and item["quality"]["dimensions"]["source_read"]
        assert service.library(q="debug")["items"][0]["quality"] == item["quality"]
    finally:
        service.close()


def test_bundled_update_adds_new_sources_without_republishing_unchanged_seed(tmp_path):
    service = CatalogService(tmp_path / "catalog.db")
    def seed(sources):
        return gzip.compress(json.dumps({"format": FORMAT, "sources": sources, "stats": {}}).encode())
    def source(key):
        return {"revision": key, "items": [Resource(item_id=key, type="skill", name=key, url="").model_dump()]}
    try:
        first = seed({"one": source("one")})
        assert service.bootstrap(first, offline_ids=())["seed"]["items"] == 1
        assert service.bootstrap(first, offline_ids=())["seed"] is None
        update = seed({"one": source("one"), "two": source("two")})
        result = service.bootstrap(update, offline_ids=())["seed"]
        assert result["items"] == 1 and result["unchanged"] == ["one"]
        assert service.store.stats()["items"] == 2
    finally:
        service.close()


def test_feature_contract_upgrade_rebuilds_existing_projection_once(tmp_path):
    service = CatalogService(tmp_path / "catalog.db")
    try:
        service.store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
        publish(service.store, [record("review", summary="implementation plan")])
        with service.store.connect() as conn:
            conn.execute("DELETE FROM item_feature WHERE feature='task_phase'")
            conn.execute("UPDATE catalog_meta SET value='features-old:chunks-old' WHERE key='projection_version'")
        assert service.store.ensure_projections()
        assert not service.store.ensure_projections()
        with service.store.connect(True) as conn:
            assert conn.execute("SELECT 1 FROM item_feature WHERE feature='task_phase' AND value='plan'").fetchone()
    finally:
        service.close()

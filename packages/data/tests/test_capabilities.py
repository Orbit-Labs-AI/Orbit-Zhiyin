import json
import socket

import pytest

from orbit_data.capabilities import CACHE_FILE, CACHE_TTL_MS, FEATURES, MATRIX, capabilities
from orbit_data.resume import AGENTS
from orbit_data.service import ImportRequest, ImportService
from orbit_data.store import Store
from orbit_data.validation.fixtures import create_sources

NOW = 1_800_000_000_000


@pytest.fixture
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("capability detection must stay offline")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def home(tmp_path):
    roots = create_sources(tmp_path / "fixtures")
    home = tmp_path / "home"
    with Store(home) as store:
        service = ImportService(store)
        for agent, root in roots.items():
            service.import_source(ImportRequest(agent, root))
    return home


def test_matrix_covers_every_agent_and_feature():
    assert set(MATRIX) == set(AGENTS)
    for values in MATRIX.values():
        assert values["evidence"]
        for feature in FEATURES:
            assert values[feature] in ("supported", "partial", "unsupported", "unknown")


def test_report_lists_sources_with_latest_harness_version(home, offline):
    report = capabilities(home, now_ms=NOW)
    assert report["cache"] == "miss"
    agents = {source["agent"]: source for source in report["sources"]}
    assert set(agents) == {"claude_code", "opencode", "dsh", "pi", "hermes", "kimi"}
    versions = {agent: source["harness_version"] for agent, source in agents.items()}
    assert {v for v in versions.values() if v} >= {"1.5", "3", "4"}
    for source in agents.values():
        assert source["sessions"] >= 1
        assert set(source["observed"]) == {"hooks", "skills", "mcp", "subagents"}
        assert set(FEATURES) <= set(source["matrix"])


def test_second_call_within_24h_hits_cache_without_rewriting(home, offline):
    first = capabilities(home, now_ms=NOW)
    path = home / CACHE_FILE
    stat = path.stat()
    assert stat.st_mode & 0o777 == 0o600
    second = capabilities(home, now_ms=NOW + CACHE_TTL_MS - 1)
    assert second["cache"] == "hit"
    assert path.stat().st_mtime_ns == stat.st_mtime_ns
    assert second["sources"] == first["sources"]
    expired = capabilities(home, now_ms=NOW + CACHE_TTL_MS)
    assert expired["cache"] == "miss" and expired["generated_at"] == NOW + CACHE_TTL_MS
    assert capabilities(home, now_ms=NOW + CACHE_TTL_MS + 1, refresh=True)["cache"] == "miss"


def test_new_projection_invalidates_cache(home, tmp_path, offline):
    capabilities(home, now_ms=NOW)
    extra = create_sources(tmp_path / "more")
    with Store(home) as store:
        ImportService(store).import_source(ImportRequest("pi", extra["pi"]))
    assert capabilities(home, now_ms=NOW + 1)["cache"] == "miss"


def test_corrupt_cache_and_missing_database(tmp_path, offline):
    home = tmp_path / "home"
    home.mkdir()
    (home / "cache").mkdir()
    (home / CACHE_FILE).write_text("{not json")
    report = capabilities(home, now_ms=NOW)
    assert report["sources"] == [] and report["cache"] == "miss"
    assert json.loads((home / CACHE_FILE).read_text())["fingerprint"] == "empty"
    absent = tmp_path / "absent"
    assert capabilities(absent, now_ms=NOW)["sources"] == []
    assert not absent.exists()

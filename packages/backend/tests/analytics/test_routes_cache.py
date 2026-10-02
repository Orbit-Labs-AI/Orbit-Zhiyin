"""API reads cached sections: warm requests are fast, rows page without full analysis."""

import time
import zlib

import pytest
from cache_fixtures import build_home
from fastapi.testclient import TestClient

from tandem_backend.analytics import warmup
from tandem_backend.analytics.cache import clear_memory_cache
from tandem_backend.analytics.history import history_for
from tandem_backend.analytics.service import ROW_STATS
from tandem_backend.api import create_app
from tandem_backend.data_access.store import CanonicalStore


@pytest.fixture(autouse=True)
def isolated_memory_cache():
    clear_memory_cache()
    yield
    clear_memory_cache()


def timed(client, url):
    start = time.perf_counter()
    response = client.get(url)
    return response, time.perf_counter() - start


@pytest.mark.serial  # latency budget: measured outside the parallel pass
def test_thousand_sessions_warm_requests_meet_latency_budgets(tmp_path, monkeypatch):
    home, _ = build_home(tmp_path, 1000)
    store = CanonicalStore(home)
    with TestClient(create_app(home=home)) as client:
        assert client.get("/v1/analytics/status").json()["warmup"] == {"status": "idle"}
        assert client.post("/v1/analytics/warmup").status_code == 200
        state = warmup.wait(store, timeout=300)
        assert state["status"] == "completed", state
        assert state["done"] == list(warmup.FIRST_SCREEN)
        status = client.get("/v1/analytics/status").json()
        assert status["freshness"]["cached"] is True and status["runs"]

        first, _ = timed(client, "/v1/analytics/overview")
        assert first.status_code == 200 and first.json()["freshness"]["cache_hit"] is True
        second, seconds = timed(client, "/v1/analytics/overview")
        assert second.json()["overview"] == first.json()["overview"]
        assert seconds <= 0.2, seconds

        runs = history_for(store).list_runs()["total"]
        computed = ROW_STATS["computed"]
        page, seconds = timed(client, "/v1/analytics/sessions?limit=50")
        assert page.status_code == 200 and seconds <= 0.1, seconds
        body = page.json()
        assert body["total"] == 1000 and len(body["sessions"]) == 50
        assert set(body["sessions"][0]) >= {"session_uid", "features", "usage"}
        assert "bottleneck_features" not in body["sessions"][0]

        # A single session is read by key: no analysis run, no row computation.
        # The analysis entry points are disabled to prove it.
        def fail(*args, **kwargs):
            raise AssertionError("full analysis must not run for a cached session row")

        monkeypatch.setattr("tandem_backend.analytics.service.AnalysisSections.full", fail)
        monkeypatch.setattr("tandem_backend.analytics.cache.AnalysisCache._compute", fail)
        sid = body["sessions"][7]["session_uid"]
        detail, seconds = timed(client, f"/v1/analytics/sessions/{sid}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["session"]["session_uid"] == sid
        assert "bottleneck_features" in detail.json()["session"]
        assert client.get("/v1/analytics/sessions/missing").status_code == 404
        assert history_for(store).list_runs()["total"] == runs
        assert ROW_STATS["computed"] == computed


def test_cold_session_detail_computes_only_the_sessions_section(tmp_path, monkeypatch):
    home, _ = build_home(tmp_path, 6)

    def fail(*args, **kwargs):
        raise AssertionError("session detail must not compute lexical/statistics/recommendations")

    for name in ("_statistics",):
        monkeypatch.setattr(f"tandem_backend.analytics.service.AnalysisSections.{name}", fail)
    monkeypatch.setattr("tandem_backend.analytics.products.lexical.lexical_analysis", fail)
    monkeypatch.setattr("tandem_backend.analytics.service.recommend_resources", fail)
    with TestClient(create_app(home=home)) as client:
        sid = client.get("/v1/analytics/sessions?limit=1").json()["sessions"][0]["session_uid"]
        detail = client.get(f"/v1/analytics/sessions/{sid}").json()
        assert detail["session"]["session_uid"] == sid
        assert detail["freshness"]["cache_hit"] is True
        overview = client.get("/v1/analytics/overview").json()
        assert overview["effective_samples"]["main_sessions"] == 6


def test_exclusion_endpoints_persist_and_shrink_all_analyses(tmp_path):
    home, _ = build_home(tmp_path, 5)
    with TestClient(create_app(home=home)) as client:
        before = client.get("/v1/analytics/overview").json()
        products = client.get("/v1/analytics/products").json()
        sid = client.get("/v1/analytics/sessions").json()["sessions"][0]["session_uid"]
        assert client.post("/v1/sessions/missing/exclude").status_code == 404
        response = client.post(f"/v1/sessions/{sid}/exclude", json={"reason": "测试噪声"})
        assert response.status_code == 200 and response.json()["reason"] == "测试噪声"
        after = client.get("/v1/analytics/overview").json()
        assert after["effective_samples"]["main_sessions"] == before["effective_samples"]["main_sessions"] - 1
        assert sid in after["scope"]["excluded_session_uids"]
        assert client.get("/v1/analytics/sessions").json()["total"] == 4
        assert client.get(f"/v1/analytics/sessions/{sid}").status_code == 404
        statistics = client.get("/v1/analytics/statistics").json()
        assert statistics["effective_samples"]["main_sessions"] == 4
        excluded_products = client.get("/v1/analytics/products").json()
        assert sid in excluded_products["scope"]["excluded_session_uids"]
        assert excluded_products["analysis_digest"] != products["analysis_digest"]
        assert client.get("/v1/analytics/status").json()["exclusions"] == 1
        assert client.delete(f"/v1/sessions/{sid}/exclude").status_code == 200
        assert client.delete(f"/v1/sessions/{sid}/exclude").status_code == 404
        restored = client.get("/v1/analytics/overview").json()
        assert restored["effective_samples"] == before["effective_samples"]
        assert restored["freshness"]["cache_hit"] is True


def test_damaged_cached_section_is_a_conflict(tmp_path):
    home, _ = build_home(tmp_path, 3)
    store = CanonicalStore(home)
    with TestClient(create_app(home=home)) as client:
        assert client.get("/v1/analytics/tools").status_code == 200
        clear_memory_cache()
        with history_for(store).connect() as db:
            db.execute(
                "UPDATE analysis_section SET payload=? WHERE section='tools'",
                (zlib.compress(b"{}"),),
            )
        response = client.get("/v1/analytics/tools")
        assert response.status_code == 409 and "checksum" in response.json()["detail"]


def test_each_section_endpoint_returns_only_its_section(tmp_path):
    home, _ = build_home(tmp_path, 4)
    with TestClient(create_app(home=home)) as client:
        for path, key in (
            ("overview", "overview"),
            ("tools", "tools"),
            ("projects", "projects"),
            ("instruction", "instruction"),
            ("tasks", "tasks"),
            ("bottleneck", "bottleneck_features"),
            ("lexical", "lexical"),
            ("statistics", "statistics"),
        ):
            body = client.get(f"/v1/analytics/{path}").json()
            assert key in body and "sessions" not in body and "freshness" in body, path
        assert client.get("/v1/analytics/recommendations").status_code == 200
        assert client.get("/v1/analytics/preferences").json()["preferences"]["effective"] is not None


def test_insights_routes_are_mounted_and_read_cached_sections(tmp_path, monkeypatch):
    home, _ = build_home(tmp_path, 6)
    with TestClient(create_app(home=home)) as client:
        signals = client.get("/v1/analytics/signals")
        assert signals.status_code == 200 and "signals" in signals.json()
        # Signals filled the sessions/bottleneck sections; later insight reads must not run
        # the engine again, only input selection.
        import tandem_backend.analytics.service as service

        def fail(*args, **kwargs):
            raise AssertionError("insight route recomputed analysis sections")

        monkeypatch.setattr(service, "AnalysisSections", fail)
        monkeypatch.setattr(service, "analyze_context", fail)
        metrics = client.get("/v1/analytics/metrics")
        assert metrics.status_code == 200, metrics.text
        problems = client.get("/v1/analytics/problems")
        assert problems.status_code == 200, problems.text
        assert client.get("/v1/analytics/metrics?metric=nope").status_code == 422

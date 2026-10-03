"""API reads cached sections: warm requests are fast, rows page without full analysis."""

import time
import zlib
from contextlib import contextmanager

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


TOKEN = "synthetic-test-token-0123456789abcdef"


@contextmanager
def imported_gateway(tmp_path):
    """A real gateway (worker processes) over 4 synthetic Codex sessions, import finished."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parents[1] / "services"))
    from synthetic import write_codex_tree

    from tandem_backend.services.gateway import Gateway
    from tandem_backend.services.supervisor import SupervisorConfig

    root = tmp_path / "agents" / "codex"
    write_codex_tree(root, 4)
    config = SupervisorConfig(heartbeat_s=0.3, stale_s=3.0, term_grace_s=1.0,
                              backoff_s=(0.1, 0.2, 0.4, 0.8), tick_s=0.05,
                              light_timeout_s=60.0, heavy_timeout_s=120.0)
    gateway = Gateway(tmp_path / "home", config=config, discovery=lambda: [],
                      prewarm_debounce_s=3600.0)
    with TestClient(gateway.app(token=TOKEN, port=8765), base_url="http://127.0.0.1:8765",
                    headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        source = client.post("/v1/app/sources", json={"agent": "codex", "root": str(root)})
        job = client.post("/v1/app/jobs", json={"kind": "import", "source_ids": [source.json()["id"]]})
        poll(client, f"/v1/app/jobs/{job.json()['id']}",
             lambda r: r.json()["status"] not in ("queued", "running"))
        yield client, gateway


def poll(client, url, ok, headers=None):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = client.get(url, headers=headers or {})
        if ok(response):
            return response
        time.sleep(0.1)
    raise AssertionError(f"{url}: {response.status_code} {response.text[:300]}")


def fresh(response):
    return response.status_code == 200 and response.json()["meta"]["freshness"] == "fresh"


@pytest.mark.serial  # gateway with worker processes and wall-clock waits
def test_presentation_window_is_stable_within_a_day_and_moves_across_days(tmp_path, monkeypatch):
    """Gateway route: window=7d anchors on the local day, so the snapshot key is reused all day."""
    from datetime import datetime

    from tandem_backend.services import routes_analytics

    day = int(datetime.fromisoformat("2026-10-03T09:00:00+00:00").timestamp() * 1000)
    clock = {"now": day}
    monkeypatch.setattr(routes_analytics, "now_ms", lambda: clock["now"])

    def read(client):
        return poll(client, "/v1/analytics/presentation?window=7d&wait_ms=3000", fresh).json()

    with imported_gateway(tmp_path) as (client, _):
        first = read(client)
        clock["now"] = day + 10 * 3600 * 1000  # 19:00 UTC, same day
        second = read(client)
        assert second["meta"]["scope_hash"] == first["meta"]["scope_hash"]
        assert second["meta"]["computed_at"] == first["meta"]["computed_at"]  # snapshot reused
        window = first["meta"]["window"]
        end = int(datetime.fromisoformat("2026-10-04T00:00:00+00:00").timestamp() * 1000)
        assert (window["from_ts"], window["until_ts"]) == (end - 7 * 86400000, end)
        assert window["requested_at"] == day
        # The worker computed with exactly the bounds the gateway reports.
        assert (first["scope"]["from_ts"], first["scope"]["until_ts"]) == (window["from_ts"], end)
        clock["now"] = day + 24 * 3600 * 1000  # next day
        third = read(client)
        assert third["meta"]["scope_hash"] != first["meta"]["scope_hash"]
        assert third["meta"]["window"]["until_ts"] == third["scope"]["until_ts"] == end + 86400000


@pytest.mark.serial  # gateway with worker processes and wall-clock waits
def test_catalog_match_etag_changes_when_the_catalog_changes(tmp_path):
    from tandem_catalog import get_service

    url = "/v1/catalog/match-analysis?wait_ms=3000"
    with imported_gateway(tmp_path) as (client, gateway):
        first = poll(client, url, fresh)
        tag = first.headers["ETag"]
        assert client.get(url, headers={"If-None-Match": tag}).status_code == 304
        store = get_service(gateway.home / "catalog.db").store
        with store.connect() as conn:  # what a catalog refresh does to the generation
            conn.execute("UPDATE catalog_meta SET value=CAST(value AS INTEGER)+1 "
                         "WHERE key='generation'")
        again = client.get(url, headers={"If-None-Match": tag})
        assert again.status_code == 200 and again.headers["ETag"] != tag


class _Analysis:
    def __init__(self):
        self.submitted = []

    def clear_failures(self, *_):
        pass

    def submit(self, name, scope, params, h, *_):
        self.submitted.append((name, params, h))
        return type("Task", (), {"id": f"job-{len(self.submitted)}"})()


class _Gateway:
    def __init__(self, data_rev):
        self.data_rev = data_rev
        self.supervisor = type("Supervisor", (), {"analysis": _Analysis()})()
        outer = self

        class revisions:  # noqa: N801 - mirrors the Gateway attribute
            @staticmethod
            def snapshot():
                return {"data_rev": outer.data_rev, "inventory_rev": 0}

        self.revisions = revisions


def _client(gateway):
    from fastapi import FastAPI

    from tandem_backend.services.gateway import install_error_handlers
    from tandem_backend.services.routes_analytics import router

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router(gateway))
    return TestClient(app)


@pytest.mark.parametrize("section,get_url,params", [
    ("presentation", "/v1/analytics/presentation", {}),
    ("presentation", "/v1/analytics/presentation?window=7d&target_agent=hermes",
     {"window": "7d", "target_agent": "hermes"}),
    ("recommendations", "/v1/analytics/recommendations?kind=skill", {"kind": "skill"}),
    ("products", "/v1/analytics/products?bucket=week", {"bucket": "week"}),
    ("work_graph", "/v1/analytics/work-graph", {}),
])
def test_recompute_hashes_like_the_get_route(monkeypatch, section, get_url, params):
    from tandem_backend.services import routes_analytics

    monkeypatch.setattr(routes_analytics, "now_ms", lambda: 1_790_985_600_000)
    get_hash = _client(_Gateway(None)).get(get_url).json()["meta"]["scope_hash"]
    gateway = _Gateway(1)
    queued = _client(gateway).post("/v1/analytics/recompute",
                                   json={"sections": [section], "params": params})
    assert queued.status_code == 202, queued.text
    assert queued.json()["jobs"][0]["scope_hash"] == get_hash


@pytest.mark.parametrize("section,params", [
    ("products", {"bucket": "year"}),
    ("presentation", {"window": "2d"}),
    ("presentation", {"target_agent": "cursor"}),
    ("recommendations", {"limit": 99}),
    ("overview", {"limit": 5}),
])
def test_recompute_rejects_invalid_params_before_queueing(section, params):
    gateway = _Gateway(1)
    response = _client(gateway).post("/v1/analytics/recompute",
                                     json={"sections": [section], "params": params})
    assert response.status_code == 422, response.text
    assert gateway.supervisor.analysis.submitted == []


def test_coverage_status_table_holds_only_statuses():
    from tandem_backend.analytics.coverage import STATUS_LABELS, build_coverage_report

    assert set(STATUS_LABELS) == {"available", "partial", "unavailable", "excluded"}
    assert set(build_coverage_report({})["status_meanings"]) == set(STATUS_LABELS)


def test_every_session_feature_is_in_the_shared_dictionary():
    from tandem_backend.analytics.dictionary import FEATURES
    from tandem_backend.analytics.features import session_features

    events = [{"event_uid": "u1", "session_uid": "s", "kind": "message.user", "seq": 1,
               "actor": "human", "ts": 1_790_000_000_000, "text": "fix a.py",
               "attrs": {"origin": "human"}},
              {"event_uid": "a1", "session_uid": "s", "kind": "message.assistant", "seq": 2,
               "ts": None, "text": "done", "attrs": {}}]
    features = session_features({"session_uid": "s"}, events, [], {"s"})["features"]
    assert {"observed_event_dates", "observed_timestamp_n", "time_unknown_event_count"} <= set(features)
    assert sorted(set(features) - set(FEATURES)) == []

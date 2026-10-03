"""Heavy analytics routes never run analyze_store / build_report inside the gateway.

Regression: statistics, lexical, bottleneck, presentation, recommendations, products and
/v1/analysis used to fall through to create_app(), which ran the full engine on the gateway
threadpool (no timeout, multi-GB RSS, GIL starvation of every other route). They must go
through the supervised analysis worker (202 → analysis.ready → 200 fresh).
"""

from __future__ import annotations

import pytest
from conftest import add_codex, bus_events, fast_config, run_job, wait_for, wait_job

from orbit_backend.services.worker_protocol import DEBUG_DELAY_ENV

# Real worker processes use fast_config's 3 s heartbeat watchdog; this module also
# asserts a 0.3 s wall-clock timeout. As with test_analytics_flow, keep it outside
# the xdist pass so competing workers cannot turn CPU starvation into interruption.
pytestmark = pytest.mark.serial

ROUTES = [
    ("statistics", "get", "/v1/analytics/statistics", {}, "statistics"),
    ("lexical", "get", "/v1/analytics/lexical", {}, "lexical"),
    ("bottleneck", "get", "/v1/analytics/bottleneck", {}, "bottleneck_features"),
    ("presentation", "get", "/v1/analytics/presentation", {}, None),
    ("recommendations", "get", "/v1/analytics/recommendations", {},
     "bottleneck_recommendations"),
    ("recommendations", "post", "/v1/analytics/recommendations", {"json": {}},
     "bottleneck_recommendations"),
    ("products", "get", "/v1/analytics/products", {}, None),
    ("analysis", "get", "/v1/analysis", {}, None),
    ("products", "get", "/v1/analytics/products/sessions", {"params": {"query": "x"}}, "items"),
    ("comparison", "post", "/v1/analytics/compare", {"json": {"first": {}, "second": {}}},
     "distributions"),
    ("catalog_requests", "get", "/v1/catalog/match-analysis", {}, "batches"),
]


def _forbid_in_process(monkeypatch):
    def boom(*_, **__):
        raise AssertionError("heavy analysis ran inside the gateway process")

    import orbit_backend.analytics.products as products
    import orbit_backend.analytics.products.service as product_service
    import orbit_backend.analytics.service as service
    import orbit_backend.api.routes as legacy_routes
    import orbit_backend.application.reports as reports

    monkeypatch.setattr(service, "analyze_store", boom)
    monkeypatch.setattr(products, "analyze_product_store", boom)
    monkeypatch.setattr(reports, "build_report", boom)
    monkeypatch.setattr(reports, "analyze", boom)
    monkeypatch.setattr(legacy_routes, "build_report", boom)
    monkeypatch.setattr(legacy_routes, "analyze", boom)
    monkeypatch.setattr(product_service, "compare_scopes", boom)
    monkeypatch.setattr(product_service, "analyze_product_store", boom)


@pytest.fixture
def imported(client_factory, codex_root, monkeypatch):
    client, gateway = client_factory()
    source = add_codex(client, codex_root)
    imported_job = wait_job(client, run_job(client, "import", [source], phase="head")["id"])
    assert imported_job["status"] == "completed", imported_job
    _forbid_in_process(monkeypatch)  # The worker is a separate process and is unaffected.
    return client, gateway


@pytest.mark.parametrize(("section", "method", "path", "kwargs", "key"), ROUTES,
                         ids=[f"{m} {p}" for _, m, p, _, _ in ROUTES])
def test_heavy_route_runs_in_supervised_worker(imported, section, method, path, kwargs, key):
    client, gateway = imported
    first = getattr(client, method)(path, **kwargs)
    assert first.status_code == 202, first.text
    assert first.json()["meta"]["freshness"] == "computing"
    wait_for(lambda: any(f.data["section"] == section
                         for f in bus_events(gateway, "analysis.ready")), 120, 0.05,
             f"analysis.ready {section}")
    fresh = getattr(client, method)(path, **kwargs)
    assert fresh.status_code == 200, fresh.text
    body = fresh.json()
    assert body["meta"]["freshness"] == "fresh"
    if key is not None:
        assert key in body
    for boundary in (body.get("sample_boundary"), *(body.get(k, {}).get("sample_boundary")
                                                    for k in ("first", "second")
                                                    if isinstance(body.get(k), dict))):
        if boundary:  # The file list is opt-in via /v1/analytics/sample_files.
            assert "files" not in boundary and "file_count" in boundary


def test_invalid_presentation_window_is_rejected_without_analysis(imported):
    client, _ = imported
    response = client.get("/v1/analytics/presentation", params={"window": "bogus"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_timed_out_on_demand_route_reports_failure_instead_of_rerunning(client_factory,
                                                                         codex_root):
    config = fast_config(worker_env={DEBUG_DELAY_ENV: "600"})
    client, gateway = client_factory(config=config)
    source = add_codex(client, codex_root)
    imported_job = wait_job(client, run_job(client, "import", [source], phase="head")["id"])
    assert imported_job["status"] == "completed", imported_job
    config.light_timeout_s = 0.3  # Shorter than the worker's fixed 0.6 s start-up delay.
    analysis = gateway.supervisor.analysis

    first = client.get("/v1/analytics/statistics")
    assert first.status_code == 202
    job_id = first.json()["meta"]["job_id"]
    assert client.get(f"/v1/analytics/jobs/{job_id}").json()["status"] in ("queued", "running")
    wait_for(lambda: any(f.data["code"] == "timeout"
                         for f in bus_events(gateway, "analysis.failed")), 30, message="timeout")
    wait_for(lambda: analysis.running is None and not analysis.pending, 10)
    job = client.get(f"/v1/analytics/jobs/{job_id}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "timeout"
    assert job["section"] == "statistics"

    dispatched = sum(analysis.dispatched.values())
    for _ in range(3):  # Polling never restarts the expensive computation.
        again = client.get("/v1/analytics/statistics")
        assert again.status_code == 503
        assert again.json()["error"]["code"] == "analysis_unavailable"
        assert "timeout" in again.json()["error"]["message"]
    assert sum(analysis.dispatched.values()) == dispatched
    assert client.get("/v1/analytics/jobs/nope").status_code == 404


def test_product_session_compare_projects_the_cached_products_snapshot(imported):
    client, gateway = imported
    assert client.get("/v1/analytics/products").status_code == 202
    wait_for(lambda: any(f.data["section"] == "products"
                         for f in bus_events(gateway, "analysis.ready")), 120, 0.05, "products")
    page = client.get("/v1/analytics/products/sessions", params={"limit": 2}).json()
    assert page["meta"]["freshness"] == "fresh" and page["total"] >= 2
    first, second = (row["session_uid"] for row in page["items"][:2])
    compared = client.get("/v1/analytics/products/compare",
                          params={"first": first, "second": second})
    assert compared.status_code == 200, compared.text
    assert compared.json()["meta"]["freshness"] == "fresh"
    missing = client.get("/v1/analytics/products/compare", params={"first": first,
                                                                    "second": "nope"})
    assert missing.status_code == 422
    assert sum(1 for f in bus_events(gateway, "analysis.ready")
               if f.data["section"] == "products") == 1  # One worker run serves all three.

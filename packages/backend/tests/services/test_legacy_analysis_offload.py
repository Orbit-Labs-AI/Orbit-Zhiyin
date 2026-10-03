"""Legacy products/statistics/presentation run in the analysis worker, never in the gateway."""

from __future__ import annotations

from conftest import add_codex, bus_events, run_job, wait_for, wait_job

from tandem_backend.services.sections import HEAVY, LIGHT


def _ready(gateway, section):
    wait_for(lambda: any(f.data["section"] == section
                         for f in bus_events(gateway, "analysis.ready")),
             120, 0.05, f"analysis.ready {section}")


def test_legacy_analyses_are_queued_paged_and_bounded(client_factory, codex_root, monkeypatch):
    def in_gateway(*args, **kwargs):
        raise AssertionError("the gateway process must not compute products itself")

    monkeypatch.setattr("tandem_backend.analytics.products.analyze_product_store", in_gateway)
    client, gateway = client_factory()
    source = add_codex(client, codex_root)
    job = run_job(client, "import", [source], phase="head")
    assert wait_job(client, job["id"])["status"] == "completed"

    for path, section in (("/v1/analytics/products", "products"),
                          ("/v1/analytics/statistics", "statistics"),
                          ("/v1/analytics/presentation", "presentation")):
        queued = client.get(path, params={"limit": 1} if section == "products" else None)
        assert queued.status_code == 202, (path, queued.text)
        assert queued.json()["meta"]["freshness"] == "computing"
        _ready(gateway, section)

    product = client.get("/v1/analytics/products", params={"limit": 1}).json()
    assert product["meta"]["freshness"] == "fresh"
    assert len(product["sessions"]) == 1 and product["total"] >= 1
    assert all("next_calls" not in m for m in product["tools"]["transitions"].values())
    statistics = client.get("/v1/analytics/statistics").json()
    assert statistics["meta"]["freshness"] == "fresh" and statistics["statistics"]["metrics"]
    assert client.get("/v1/analytics/presentation").status_code == 200
    bad = client.get("/v1/analytics/presentation", params={"window": "1y"})
    assert bad.status_code == 422
    # On demand only: a publish must not prewarm minutes of products work.
    assert not {"products", "presentation", "statistics", "lexical"} & set(LIGHT + HEAVY)


def test_work_graph_and_trajectories_are_worker_snapshots(client_factory, codex_root, monkeypatch):
    def in_gateway(*args, **kwargs):
        raise AssertionError("the gateway process must not build the work graph itself")

    monkeypatch.setattr("tandem_backend.analytics.work_graph.graph.build_work_graph", in_gateway)
    client, gateway = client_factory()
    source = add_codex(client, codex_root)
    job = run_job(client, "import", [source], phase="head")
    assert wait_job(client, job["id"])["status"] == "completed"

    queued = client.get("/v1/analytics/work-graph")
    assert queued.status_code == 202, queued.text
    _ready(gateway, "work_graph")
    graph = client.get("/v1/analytics/work-graph")
    assert graph.status_code == 200 and graph.json()["meta"]["freshness"] == "fresh"
    tag = graph.headers["etag"]
    assert client.get("/v1/analytics/work-graph", headers={"If-None-Match": tag}).status_code == 304
    assert client.get("/v1/analytics/tasks/absent/trajectory").status_code == 404
    assert client.get("/v1/analytics/work-graph", params={"bogus": 1}).status_code == 422
    assert "work_graph" not in set(LIGHT + HEAVY)

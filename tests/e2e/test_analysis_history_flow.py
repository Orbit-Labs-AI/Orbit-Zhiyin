"""Public CLI/API analyses persist all runs and expose the full immutable result."""

import json

from fastapi.testclient import TestClient

from tandem_backend.analytics.history import history_for
from tandem_backend.analytics.products import analyze_product_store
from tandem_backend.api import create_app
from tandem_backend.cli import demo_home, main
from tandem_backend.data_access.ingest import ingest
from tandem_backend.data_access.store import CanonicalStore


def test_api_stores_successes_failures_and_complete_vocabulary(tmp_path):
    home = tmp_path / "data"
    ingest(home, "codex", demo_home(tmp_path / "source"))
    with TestClient(create_app(home=home)) as client:
        product = client.get("/v1/analytics/products").json()
        runs = client.get("/v1/analytics/runs?engine=products&status=completed").json()
        assert runs["total"] == 1
        run_id = runs["items"][0]["run_id"]
        assert client.get(f"/v1/analytics/runs/{run_id}/result").json() == product
        terms = client.get(
            f"/v1/analytics/runs/{run_id}/records", params={"pointer": "/lexical/terms", "limit": 2}
        ).json()
        assert terms["total"] == len(product["lexical"]["terms"]) > 2
        assert terms["items"] == product["lexical"]["terms"][:2]
        assert client.get("/v1/analytics/products?compare_previous=true").status_code == 422
        assert client.get("/v1/analytics/runs?status=failed").json()["total"] == 1
        assert client.get("/v1/analytics/runs/missing").status_code == 404
        statistics = client.get("/v1/analytics/statistics").json()["statistics"]
        assert statistics["metrics"]["human_messages_per_session"]["n"] == 3
        assert client.get("/v1/analytics/runs?engine=features").json()["total"] == 1


def test_repeat_compare_and_cli_history_preserve_earlier_results(tmp_path):
    home = tmp_path / "data"
    ingest(home, "codex", demo_home(tmp_path / "source"))
    store = CanonicalStore(home)
    product = analyze_product_store(store)
    assert analyze_product_store(store) == product
    history = history_for(store)
    runs = history.list_runs(engine="products")
    assert runs["total"] == 2
    assert len({r["snapshot_id"] for r in runs["items"]}) == 1
    output = tmp_path / "history.json"
    main(
        [
            "--home",
            str(home),
            "analysis-history",
            "--run-id",
            runs["items"][0]["run_id"],
            "--output",
            str(output),
        ]
    )
    assert json.loads(output.read_text()) == product
    with TestClient(create_app(home=home)) as client:
        response = client.post("/v1/analytics/compare", json={"first": {}, "second": {}})
        assert response.status_code == 200
        data = response.json()
        assert data["vocabulary"]["rows"]
        assert all(r["difference_per_1000_tokens"] == 0 for r in data["vocabulary"]["rows"])
        assert history.list_runs(engine="comparison")["total"] == 1
    assert history.result(runs["items"][0]["run_id"]) == product


def test_previous_window_report_and_history_include_complete_baseline(tmp_path):
    from tandem_backend.analytics.inputs import Scope
    from tandem_backend.analytics.products.render import html_report, terminal_report

    home = tmp_path / "data"
    ingest(home, "codex", demo_home(tmp_path / "source"))
    store = CanonicalStore(home)
    product = analyze_product_store(
        store, Scope(from_ts=1767225600000, until_ts=1767312000000), compare_previous=True
    )
    assert "与上期比较" in terminal_report(product)
    assert "均值差 95% 区间" in html_report(product)
    assert product["comparison"]["baseline"]["lexical"]["token_count"] == 0
    run = history_for(store).list_runs(engine="products")["items"][0]
    assert (
        history_for(store).result(run["run_id"])["comparison"]["baseline"]
        == product["comparison"]["baseline"]
    )


def test_bounded_report_snapshot_retains_persistent_history(tmp_path):
    from tandem_backend.profiling.analysis import analyze

    home = tmp_path / "data"
    ingest(home, "codex", demo_home(tmp_path / "source"))
    store = CanonicalStore(home)
    snapshot = store.report_snapshot(from_ts=1767225600000, until_ts=1767312000000)
    assert snapshot.bundle["scope"]["from_ts"] == 1767225600000
    assert snapshot.bundle["scope"]["until_ts"] == 1767312000000
    result = analyze(snapshot)
    history = history_for(store)
    run = history.list_runs(engine="profile")["items"][0]
    assert run["status"] == "completed" and history.result(run["run_id"]) == result

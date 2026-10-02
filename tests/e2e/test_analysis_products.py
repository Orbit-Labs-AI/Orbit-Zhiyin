"""Native-import and service-flow acceptance for UI analysis products."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.products import analyze_product_store, session_page
from tandem_backend.api import create_app
from tandem_backend.cli import demo_home
from tandem_backend.data_access.ingest import ingest
from tandem_backend.data_access.store import CanonicalStore


def test_native_import_api_scope_and_previous_window_are_consistent(tmp_path):
    home = tmp_path / "data"
    ingest(home, "codex", demo_home(tmp_path / "first"))
    ingest(home, "codex", demo_home(tmp_path / "second"))
    store = CanonicalStore(home)
    source = store.sources()[0]["source_id"]
    product = analyze_product_store(store, Scope(source_ids=[source]))
    assert product["overview"]["counts"]["main_sessions"] == 3
    assert product["tools"]["order_unknown_n"] == 0
    assert product["tools"]["transitions"]["kind"]["pair_count"] == 2
    assert session_page(product, query="no such session")["total"] == 0
    with TestClient(create_app(home=home)) as client:
        response = client.get("/v1/analytics/products", params={"source_ids": source})
        assert response.status_code == 200 and response.json() == product
        assert (
            client.get("/v1/analytics/products?source_ids=").json()["overview"]["counts"][
                "main_sessions"
            ]
            == 0
        )
        assert client.get("/v1/analytics/products?compare_previous=true").status_code == 422
        comparison = client.get(
            "/v1/analytics/products",
            params={
                "from_ts": 1767225600000,
                "until_ts": 1767312000000,
                "compare_previous": "true",
            },
        ).json()["comparison"]
        assert comparison["rows"][0]["previous"] == 0
        assert comparison["rows"][0]["relative_change"] is None


def test_cli_report_is_identical_to_product_api_and_does_not_run_recommendations(
    tmp_path, monkeypatch
):
    from tandem_backend.cli import main

    home = tmp_path / "data"
    ingest(home, "codex", demo_home(tmp_path / "source"))

    def forbidden(*args, **kwargs):
        raise AssertionError("analysis report must not run recommendations")

    monkeypatch.setattr("tandem_backend.analytics.service.recommend_resources", forbidden)
    output = tmp_path / "reports"
    main(["--home", str(home), "analysis-report", "--output", str(output)])
    actual = json.loads((output / "analysis.json").read_text())
    with TestClient(create_app(home=home)) as client:
        assert client.get("/v1/analytics/products").json() == actual


def test_native_acceptance_script_is_rerunnable_without_mixing_runs(tmp_path):
    import runpy

    runner = runpy.run_path(str(Path(__file__).parents[2] / "evals/analytics/products.py"))
    output = tmp_path / "acceptance"
    homes = []
    for _ in range(2):
        assert runner["main"](["--synthetic", "--output", str(output)]) == 0
        result = json.loads((output / "validation.json").read_text())
        assert result["status"] == "passed" and result["data_verification"]["unparsed"] == 0
        homes.append(result["data_home"])
    assert len(set(homes)) == 2


def test_failed_native_run_cannot_leave_a_stale_success_manifest(tmp_path):
    import runpy

    runner = runpy.run_path(str(Path(__file__).parents[2] / "evals/analytics/products.py"))
    output, source = tmp_path / "output", tmp_path / "empty-source"
    output.mkdir()
    source.mkdir()
    (output / "validation.json").write_text('{"status":"passed"}')
    with pytest.raises(SystemExit) as failure:
        runner["main"](["--source", f"codex={source}", "--output", str(output)])
    assert failure.value.code == 2
    assert json.loads((output / "validation.json").read_text())["status"] == "failed"

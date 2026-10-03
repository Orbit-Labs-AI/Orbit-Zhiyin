"""Service acceptance from installed CLI commands to the API; no native UI claim."""

import json
import os
import subprocess
import sys

from fastapi.testclient import TestClient

from orbit_backend.api import create_app
from orbit_backend.cli import demo_home


def test_import_report_and_evidence_from_outside_checkout(tmp_path):
    source = demo_home(tmp_path / "synthetic-source")
    home = tmp_path / "app-data"
    output = tmp_path / "report"
    catalog = tmp_path / "catalog.json"
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}

    def cli(*args):
        return subprocess.run(
            [sys.executable, "-m", "orbit_backend", "--home", str(home), "--catalog-cache", str(catalog), *args],
            cwd=tmp_path, env=environment, text=True, capture_output=True, check=True,
        )

    cli("ingest", "--agent", "codex", "--root", str(source))
    cli("report", "--output", str(output))
    report = json.loads((output / "analysis.json").read_text())
    with TestClient(create_app(home=home, catalog_cache=catalog)) as client:
        sessions = client.get("/v1/sessions")
        assert sessions.status_code == 200
        assert len(sessions.json()) == 3
        response = client.get("/v1/analysis")
        assert response.status_code == 200
        assert response.json() == report
        sid = sessions.json()[0]["id"]
        events = client.get(f"/v1/sessions/{sid}/events?limit=1")
        assert events.status_code == 200
        event = events.json()["items"][0]
        evidence = client.get(f"/v1/evidence/{event['id']}")
        assert evidence.status_code == 200
        assert evidence.json()["id"] == event["id"]
    before = (output / "analysis.json").read_bytes()
    cli("evaluate", "--output", str(tmp_path / "evaluation.json"))
    cli("report", "--output", str(output))
    assert (output / "analysis.json").read_bytes() == before

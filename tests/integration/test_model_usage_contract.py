"""Native usage must survive the L2 → L3 → analytics boundary without invented quality."""

import json
import sqlite3
from importlib.resources import files

from tandem_data import SCHEMA_VERSION
from tandem_data.analysis_input import AnalysisScope, model_call_row, read_analysis
from tandem_data.contract import canonical
from tandem_data.store import Store

from tandem_backend.analytics.cost_time import usage
from tandem_backend.analytics.inputs import Scope


def test_native_and_observed_boundaries_are_used_but_unknown_is_diagnosed(tmp_path):
    records = [
        {"type": "session_meta", "payload": {"id": "sample", "cwd": "/synthetic"}},
        {"type": "token_usage_record", "timestamp": "2026-10-02T00:00:00Z",
         "payload": {"response_id": "response-1", "usage": {
             "input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 20}}},
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("codex", tmp_path / "source")
        store.capture_stream(source, "sessions/sample.jsonl",
                             [(canonical(r) + "\n").encode() for r in records])
        store.rebuild()
        bundle = read_analysis(store.home, AnalysisScope("UTC"))
        request = bundle["model_calls"][0]
        assert request["request_identity_quality"] == "reported"
        assert request["boundary_quality"] == "reported"
        assert request["boundary_reliable"] is True
        result = usage(bundle["model_calls"], bundle["events"], bundle["sessions"], Scope())
        assert result["request_count"] == 1
        assert result["invalid_request_rows"] == 0
        assert result["token_buckets"]["input_tokens"] == 60
        assert result["token_buckets"]["output_tokens"] == 20
        observed = {**request, "call_uid": "observed", "request_identity_quality": "derived",
                    "boundary_quality": "observed"}
        unknown = {**request, "call_uid": "unknown", "boundary_quality": "unknown"}
        assert model_call_row(unknown)["boundary_reliable"] is False
        result = usage([request, observed, unknown], [], bundle["sessions"], Scope())
        assert result["request_count"] == 2
        assert result["invalid_request_reasons"] == {"unreliable_request_boundary": 1}
        assert result["request_boundary_qualities"] == {"reported": 1, "observed": 1}


def test_v6_upgrade_backfills_quality_from_evidence_and_preserves_identity(tmp_path):
    home = tmp_path / "old"
    home.mkdir()
    with sqlite3.connect(home / "tandem.db") as db:
        for version in range(1, 7):
            db.executescript(files("tandem_data").joinpath(f"migrations/{version:03}.sql").read_text())
        db.execute("PRAGMA foreign_keys=OFF")
        for index, (request_id, boundary, _quality) in enumerate([
                ("native", None, "reported"), (None, "changed_cumulative_usage", "observed"),
                (None, None, "unknown")]):
            attrs = json.dumps({"request_key": ["s", index], "boundary_evidence": boundary, "time": {"quality": "missing"}})
            db.execute("INSERT INTO event(event_uid,session_uid,record_uid,native_key,event_path,kind,actor,seq,attrs,contract_version,mapper_version) VALUES(?, 's','r','[]','usage','unknown','harness',?, ?,1,'old')", (f"e{index}", index, attrs))
            db.execute("INSERT INTO model_call(call_uid,session_uid,usage_event_uid,request_id,model_resolution,coverage) VALUES(?, 's', ?, ?, 'unresolved','self')", (f"m{index}", f"e{index}", request_id))
    with Store(home) as store:
        models = [dict(row) for row in store.db.execute("SELECT * FROM model_call ORDER BY call_uid")]
        assert [r["call_uid"] for r in models] == ["m0", "m1", "m2"]
        assert [r["boundary_quality"] for r in models] == ["reported", "observed", "unknown"]
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

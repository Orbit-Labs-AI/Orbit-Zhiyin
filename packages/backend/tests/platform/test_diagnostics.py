from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

from orbit_backend.platform import diagnostics, logs
from orbit_backend.platform.diagnostics import redact_obj

SECRET = "sk-" + "A" * 24


def test_redact_obj():
    out = redact_obj({"api_key": "x", "Authorization": "Bearer abc", "nested": [
        {"note": f"Bearer abcdef0123 and {SECRET} at /Users/alice/proj mail a@b.co"}]})
    assert out["api_key"] == "<redacted>" and out["Authorization"] == "<redacted>"
    note = out["nested"][0]["note"]
    assert "abcdef0123" not in note and SECRET not in note and "alice" not in note
    assert "a@b.co" not in note and "~/proj" in note


def test_export_bundle(started):
    started.gw.state.items = [{"kind": "import", "status": "failed", "phase": "full",
                               "origin": "user", "created_at": 1, "started_at": 10,
                               "finished_at": 25, "error": {"code": "boom", "message": "x"},
                               "source_ids": ["/Users/alice/.codex"],
                               "prompt": "write my secret plan"}]
    logs.log_event("probe", header="Bearer abcdef0123456789", key=SECRET,
                   path="/Users/alice/work/secret-project/x.py", home=str(started.home))
    started.log_handler.flush()
    result = diagnostics.export(started)
    path = Path(result["path"])
    assert path.parent == started.home / "exports"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with zipfile.ZipFile(path) as bundle:
        names = bundle.namelist()
        text = "\n".join(bundle.read(n).decode() for n in names)
        body = json.loads(bundle.read("diagnostics.json"))
    assert set(names) == {"README.txt", "diagnostics.json", "health.json", "metrics.csv",
                          "logs/orbit.log"} == set(result["files"])
    for leaked in ("abcdef0123456789", SECRET, "alice", "secret-project", "secret plan",
                   str(started.home)):
        assert leaked not in text, leaked
    job = body["jobs"][0]
    assert job["duration_ms"] == 15 and job["error_code"] == "boom" and len(job["sources"][0]) == 8
    assert "prompt" not in job
    assert body["app"]["version"] and body["health"]["status"]


def test_exports_are_capped(started):
    exports = started.home / "exports"
    exports.mkdir()
    for i in range(7):
        (exports / f"diagnostics-2020010{i}T000000.zip").write_bytes(b"x")
    assert diagnostics.prune_exports(started.home) == 2
    assert len(list(exports.iterdir())) == 5


def test_export_hides_project_names_in_relative_import_paths(started):
    """Import logs name each file relative to its source root; Claude Code keeps sessions under
    ``projects/<cwd with / turned into ->/``, so that relative path spells the user name and
    the project folders."""
    for path in ("projects/-Users-alice-work-secret-project/0b9f.jsonl",
                 "projects/-Users-alice-work-secret-project/0b9f/subagents/agent-1.jsonl"):
        logs.log_event("import_file", stage="capture", path=path, status="captured")
    started.log_handler.flush()
    body = diagnostics.collect(started)
    with zipfile.ZipFile(diagnostics.export(started)["path"]) as bundle:
        text = "\n".join(bundle.read(n).decode() for n in bundle.namelist())
    assert "import_file" in text and '"path": "<path#' in text
    for leaked in ("alice", "secret-project"):
        assert leaked not in text and leaked not in json.dumps(body), leaked

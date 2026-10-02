"""Run the installed CLI and App query boundary against real native storage formats."""

import hashlib
import json
import os
import subprocess
import sys

import pytest

from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store
from tandem_data.validation.fixtures import create_sources


def invoke(*args):
    return subprocess.run(
        [sys.executable, "-m", "tandem_data.cli", *map(str, args)], text=True, capture_output=True
    )


def test_cli_discover_import_query_export_rebuild_and_readonly_sources(tmp_path):
    roots = create_sources(tmp_path / "fixtures")
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for root in roots.values()
        for path in root.rglob("*")
        if path.is_file()
    }
    home = tmp_path / "data"
    for agent, root in roots.items():
        result = invoke("--home", home, "scan", "--agent", agent, "--root", root)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["changed"] == 1
    result = invoke("--home", home, "verify")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["unparsed"] == 0
    export = tmp_path / "events.jsonl"
    result = invoke("--home", home, "export", "--table", "v_analysis_event", "--output", export)
    assert result.returncode == 0, result.stderr
    assert len(export.read_text().splitlines()) > 10
    if os.name == "posix":
        assert export.stat().st_mode & 0o777 == 0o600
    # Export refuses overwrite and cannot write through an Agent root.
    assert (
        invoke("--home", home, "export", "--table", "session", "--output", export).returncode != 0
    )
    assert (
        invoke(
            "--home", home, "export", "--table", "session", "--output", roots["pi"] / "out.jsonl"
        ).returncode
        != 0
    )
    assert invoke("--home", home, "rebuild").returncode == 0
    assert all(
        hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in before.items()
    )


def test_offline_validation_command_generates_inspectable_six_agent_report(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "tandem_data.validation", "--output", str(tmp_path / "validation")],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    report = next((tmp_path / "validation").glob("*/report.html"))
    summary = json.loads(report.with_name("results.json").read_text())
    assert len(summary["results"]) == 6
    assert all(r["status"] == "passed" for r in summary["results"])
    assert summary["benchmark"]["warm_changed"] == 0
    assert "textContent" in report.read_text()
    assert "<script src=" not in report.read_text()


def test_corrupt_row_isolated_and_unknown_type_has_evidence(tmp_path):
    from tandem_data.contract import canonical

    root = tmp_path / "pi"
    file = root / "sessions/s.jsonl"
    file.parent.mkdir(parents=True)
    file.write_text(
        "\n".join(
            [
                canonical({"type": "session", "id": "s"}),
                "{bad",
                canonical({"type": "message", "id": "broken", "message": None}),
                canonical({"type": "new.type", "id": "new", "future": {"nested": True}}),
                canonical(
                    {
                        "type": "message",
                        "id": "ok",
                        "message": {"role": "user", "content": "survives"},
                    }
                ),
            ]
        )
        + "\n"
    )
    with Store(tmp_path / "data") as store:
        result = ImportService(store).import_source(ImportRequest("pi", root))
        assert result["current_unparsed"] == 2
        assert store.verify()["unparsed"] == 2
        assert store.db.execute("SELECT text FROM v_human_message").fetchone()[0] == "survives"
        assert (
            store.db.execute("SELECT COUNT(*) FROM event WHERE kind='unknown'").fetchone()[0] == 1
        )


def test_second_writer_does_not_start_import(tmp_path):
    import fcntl

    roots = create_sources(tmp_path / "fixtures")
    with Store(tmp_path / "data") as store:
        with (store.home / "import.lock").open("w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(RuntimeError, match="worker"):
                ImportService(store).import_source(ImportRequest("pi", roots["pi"]))

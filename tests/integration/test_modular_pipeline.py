"""Application acceptance: native inputs -> L0/L1 -> canonical facts -> CLI/API/analysis."""

import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from orbit_data import SCHEMA_VERSION
from orbit_data.analysis_input import AnalysisScope, read_analysis
from orbit_data.service import ImportRequest, ImportService
from orbit_data.store import Store
from orbit_data.validation.fixtures import create_sources

from orbit_backend.analytics.inputs import Scope
from orbit_backend.analytics.service import analyze_store
from orbit_backend.api import create_app
from orbit_backend.cli import demo_home, main
from orbit_backend.data_access.ingest import ingest, ingest_staging, maintain
from orbit_backend.data_access.store import CanonicalStore, ReportSnapshot


@pytest.fixture
def data(tmp_path):
    home, root = tmp_path / "data", demo_home(tmp_path / "codex")
    ingest(home, "codex", root)
    return home, root


def test_default_import_publishes_layers_without_using_mvp_parser(tmp_path, monkeypatch, capsys):
    root, home = demo_home(tmp_path / "codex"), tmp_path / "data"
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*.jsonl")}

    def forbidden(*args, **kwargs):
        raise AssertionError("native parsing must belong to orbit_data")

    monkeypatch.setattr("orbit_backend.legacy.store.parse_rollout", forbidden)
    main(["--home", str(home), "import", "--codex-home", str(root)])
    result = json.loads(capsys.readouterr().out)
    assert result["import"]["changed"] == 3
    assert result["stored"]["tables"]["source_revision"] == 3
    assert not (home / "orbit.sqlite").exists()
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in hashes.items())
    assert ingest(home, "codex", root)["import"]["changed"] == 0
    assert maintain(home, "verify")["unparsed"] == 0
    result = analyze_store(CanonicalStore(home), with_text=False)
    assert result["versions"]["storage"] == "orbit-session-v1"
    assert result["overview"]["counts"]["main_sessions"] == 3
    assert result["overview"]["counts"]["human_messages"] == 5
    for entity in ("sessions", "projects", "turns"):
        assert result["coverage"][entity]["status"] == "available"
        assert result["coverage"][entity]["rows"] > 0


# Hand-derived from orbit_data.validation.fixtures.create_sources (one session, one tool call
# per native agent) and demo_home (three Codex rollouts, one tool call each, no usage rows).
# usage: per-request token total (input + cache read + cache write + output) when the native
# row identifies its request, "unknown" when the row has no request id (excluded with a
# reason), "snapshot" for Hermes' per-session cumulative usage table, None without usage.
AGENT_EXPECTATIONS = {
    "codex": {"sessions": 3, "tool_calls": 3, "usage": None},
    "claude_code": {"sessions": 1, "tool_calls": 1, "usage": 35},
    "pi": {"sessions": 1, "tool_calls": 1, "usage": "unknown"},
    "dsh": {"sessions": 1, "tool_calls": 1, "usage": 35},
    "kimi": {"sessions": 1, "tool_calls": 1, "usage": 35},
    "opencode": {"sessions": 1, "tool_calls": 1, "usage": 35},
    "hermes": {"sessions": 1, "tool_calls": 1, "usage": "snapshot"},
}


def test_all_supported_agents_feed_the_same_analysis_contract(tmp_path):
    roots = create_sources(tmp_path / "sources")
    roots["codex"] = demo_home(tmp_path / "codex")
    home = tmp_path / "data"
    assert set(roots) == set(AGENT_EXPECTATIONS)
    for agent, root in roots.items():
        assert ingest(home, agent, root)["import"]["capture_errors"] == 0
    store = CanonicalStore(home)
    assert len(store.sources()) == 7
    bundle = store.read_bundle()
    assert {s["agent"] for s in bundle["sample_boundary"]["sources"]} == set(roots)
    agent_of = {s["session_uid"]: s["agent"] for s in bundle["sessions"]}
    observed = {agent: {"sessions": 0, "tool_calls": 0, "calls": []} for agent in roots}
    for session in bundle["sessions"]:
        observed[session["agent"]]["sessions"] += 1
    for call in bundle["tool_calls"]:
        observed[agent_of[call["session_uid"]]]["tool_calls"] += 1
    for call in bundle["model_calls"]:
        observed[agent_of[call["session_uid"]]]["calls"].append(call)
    snapshot_agents = {agent_of[e["session_uid"]] for e in bundle["events"]
                       if e["kind"] == "model.usage" and e["attrs"].get("measurement") == "cumulative"}
    for agent, expected in AGENT_EXPECTATIONS.items():
        got = observed[agent]
        assert (got["sessions"], got["tool_calls"]) == (expected["sessions"], expected["tool_calls"]), agent
        calls = got["calls"]
        if expected["usage"] is None or expected["usage"] == "snapshot":
            assert calls == [], agent
            assert (agent in snapshot_agents) == (expected["usage"] == "snapshot"), agent
        elif expected["usage"] == "unknown":
            assert [c["boundary_quality"] for c in calls] == ["unknown"], agent
            assert calls[0]["request_id"] is None, agent
        else:
            assert [c["boundary_quality"] for c in calls] == ["reported"], agent
            total = sum(calls[0][k] for k in ("input_tokens", "cache_read_tokens",
                                              "cache_write_tokens", "output_tokens"))
            assert total == expected["usage"], agent
    result = analyze_store(store, with_text=False)
    assert result["overview"]["counts"]["main_sessions"] == sum(
        e["sessions"] for e in AGENT_EXPECTATIONS.values())
    usage = result["overview"]["usage"]
    unknown = [a for a, e in AGENT_EXPECTATIONS.items() if e["usage"] == "unknown"]
    bounded = [e["usage"] for e in AGENT_EXPECTATIONS.values() if isinstance(e["usage"], int)]
    assert usage["request_count"] == len(bounded)
    assert usage["invalid_request_reasons"] == {"unreliable_request_boundary": len(unknown)}
    assert usage["known_call_tokens"] == sum(bounded)
    # An unbounded request row keeps the total a marked lower bound (audit B13), never complete.
    assert (usage["total_tokens"], usage["total_basis"], usage["total_complete"]) == (
        sum(bounded), "call_delta_known_rows", False)
    assert usage["status"] == "partial"
    assert maintain(home, "verify")["unparsed"] == 0


def test_same_native_session_ids_from_two_roots_do_not_collide(tmp_path):
    home = tmp_path / "data"
    ingest(home, "codex", demo_home(tmp_path / "first"))
    ingest(home, "codex", demo_home(tmp_path / "second"))
    bundle = CanonicalStore(home).read_bundle()
    assert len(bundle["sessions"]) == 6
    assert len({s["session_uid"] for s in bundle["sessions"]}) == 6


def test_analysis_keeps_context_out_of_members_and_historical_status(data):
    home, _ = data
    store = CanonicalStore(home)
    scope = Scope(from_ts=1767225603000, until_ts=1767225604000)
    bundle = store.read_bundle(scope)
    assert len(bundle["events"]) > len(bundle["statistical_members"]["event_uids"])
    result = analyze_store(store, scope, with_text=False)
    assert result["overview"]["counts"]["events"] == len(bundle["statistical_members"]["event_uids"])
    assert result["overview"]["counts"]["human_messages"] == 0
    assert all(c["result_event_uid"] is None for c in bundle["tool_calls"])
    assert analyze_store(store, Scope(project_ids=[]), with_text=False)["overview"]["counts"]["events"] == 0


def test_narrative_does_not_treat_child_agent_prompts_as_human_preferences(data):
    bundle = CanonicalStore(data[0]).read_bundle()
    sid = bundle["sessions"][0]["session_uid"]
    expected = sum(e["kind"] == "message.user" and e["attrs"].get("origin") == "human"
                   and e["session_uid"] != sid for e in bundle["events"])
    bundle["sessions"][0]["kind"] = "subagent"
    snapshot = ReportSnapshot(bundle)
    assert sum(e.kind == "user_message" for e in snapshot.events()) == expected


def test_sql_scope_applies_before_analysis_memory_budget(tmp_path):
    home = tmp_path / "data"
    root = create_sources(tmp_path / "sources")["pi"]
    ingest(home, "pi", root)
    # A zero selection must not decode the entire dataset then trip the limit.
    bundle = read_analysis(home, AnalysisScope("UTC", project_ids=()), max_events=0)
    assert bundle["events"] == []
    with pytest.raises(ValueError, match="limit exceeded"):
        read_analysis(home, AnalysisScope("UTC"), max_events=1)


def test_api_pages_are_readonly_and_do_not_materialize_analysis(data, monkeypatch):
    home, _ = data
    store = CanonicalStore(home)
    with store.connect() as connection, pytest.raises(sqlite3.OperationalError, match="readonly"):
        connection.execute("DELETE FROM event")
    session = store.session_page(limit=1)["items"][0]["id"]

    def forbidden(*args, **kwargs):
        raise AssertionError("a list endpoint must not load the analysis bundle")

    monkeypatch.setattr(CanonicalStore, "read_bundle", forbidden)
    client = TestClient(create_app(home=home))
    assert len(client.get("/v1/sessions?limit=1").json()) == 1
    first = client.get(f"/v1/sessions/{session}/events?limit=2").json()
    second = client.get(f"/v1/sessions/{session}/events", params={"limit": 2, "after_seq": first["next_after_seq"]}).json()
    assert len(first["items"]) == 2
    assert {e["id"] for e in first["items"]}.isdisjoint(e["id"] for e in second["items"])
    assert client.get("/v1/evidence/" + first["items"][0]["id"]).status_code == 200
    assert client.get("/v1/sessions/missing/events").status_code == 404


def test_no_implicit_legacy_database_or_raw_acquisition_on_read(tmp_path):
    with pytest.raises(ValueError, match="数据库不存在"):
        create_app(home=tmp_path / "absent")
    assert not (tmp_path / "absent").exists()


def test_reader_serves_the_published_projection_until_rebuilt(data):
    """A capture that is not published yet never mixes into analysis: readers keep reading
    the published run (strict readers refuse), and the rebuild publishes the new facts."""
    from orbit_data.query import current_projection
    from orbit_data.store import readonly_connection

    home, root = data
    before = analyze_store(CanonicalStore(home), with_text=False)["analysis_digest"]
    with Store(home) as store:
        path = next(root.rglob("*.jsonl"))
        with path.open("a") as handle:
            handle.write(json.dumps({"type": "event_msg", "timestamp": "2026-01-02T00:00:00Z",
                                    "payload": {"type": "user_message", "message": "new prompt"}}) + "\n")
        ImportService(store).import_source(ImportRequest("codex", root, rebuild=False))
    assert analyze_store(CanonicalStore(home), with_text=False)["analysis_digest"] == before
    with readonly_connection(home / "orbit.db") as db, pytest.raises(ValueError, match="pending"):
        current_projection(db)
    ingest(home, "codex", root)
    assert analyze_store(CanonicalStore(home), with_text=False)["analysis_digest"] != before


def test_empty_authorized_source_can_be_opened_by_app(tmp_path):
    root, home = tmp_path / "source", tmp_path / "data"
    root.mkdir()
    assert ingest(home, "codex", root)["import"]["files"] == 0
    assert TestClient(create_app(home=home)).get("/health").json()["counts"]["events"] == 0


def test_cli_reports_partial_import_with_nonzero_status(tmp_path, capsys):
    root, home = tmp_path / "source", tmp_path / "data"
    (root / "sessions").mkdir(parents=True)
    (root / "sessions/bad.jsonl").write_text("{bad\n")
    with pytest.raises(SystemExit) as error:
        main(["--home", str(home), "ingest", "--agent", "codex", "--root", str(root)])
    assert error.value.code == 2
    assert json.loads(capsys.readouterr().out)["import"]["current_unparsed"] == 1
    assert (home / "raw").exists()


def test_report_rerun_cleans_only_its_old_canonical_evidence(data, tmp_path, capsys):
    home, _ = data
    output = tmp_path / "report"
    main(["--home", str(home), "report", "--output", str(output)])
    capsys.readouterr()
    evidence = output / "evidence"
    previous = {p.name for p in evidence.iterdir()}
    assert previous and all(name.startswith("event_") for name in previous)
    unrelated = evidence / "my-note.txt"
    unrelated.write_text("keep")
    main(["--home", str(home), "report", "--project-id", "absent", "--output", str(output)])
    assert {p.name for p in evidence.iterdir()} == {"my-note.txt"}


def test_new_import_does_not_silently_ignore_legacy_sample_policy_flags(tmp_path):
    home = tmp_path / "data"
    with pytest.raises(SystemExit) as error:
        main(["--home", str(home), "import", "--codex-home", str(tmp_path), "--before", "2026-01-01T00:00:00Z"])
    assert error.value.code == 2 and not home.exists()


def test_staging_bridge_is_usable_after_native_source_is_gone(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    cli = repo / "packages/connectors/dist/cli.js"
    if not cli.exists() or not shutil.which("node"):
        pytest.fail("Missing staging producer: run pnpm --dir packages/connectors build before integration tests")
    root = demo_home(tmp_path / "codex")
    for path in root.rglob("*.jsonl"):
        path.rename(path.with_name("rollout-" + path.name))
    staging, home = tmp_path / "staging", tmp_path / "data"
    result = subprocess.run(["node", str(cli), "ingest", "--codex-home", str(root), "--data-dir", str(staging)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    shutil.rmtree(root)
    ingest_staging(home, staging)
    assert CanonicalStore(home).counts()["sessions"] == 3
    assert maintain(home, "verify")["unparsed"] == 0
    assert ingest_staging(home, staging)["import"]["imported_revisions"] == 0


def test_cli_progress_uses_stderr_and_preserves_json(tmp_path, capsys):
    root, home = demo_home(tmp_path / "codex"), tmp_path / "data"
    main(["--home", str(home), "ingest", "--agent", "codex", "--root", str(root)])
    captured = capsys.readouterr()
    assert json.loads(captured.out)["import"]["current_unparsed"] == 0
    for stage in ("capture", "reset_projection", "prepare", "map", "derive", "published"):
        assert stage in captured.err
    main(["--home", str(home), "--no-progress", "rebuild"])
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["tables"]["session"] == 3


def test_interrupted_projection_keeps_published_facts_and_can_retry(data):
    home, _ = data
    before = CanonicalStore(home).read_bundle()

    def cancel(update):
        if update["stage"] == "derive":
            raise KeyboardInterrupt

    with Store(home) as store:
        with pytest.raises(KeyboardInterrupt):
            store.rebuild(progress=cancel)
    after = CanonicalStore(home).read_bundle()
    assert after["projection_run_id"] == before["projection_run_id"]
    assert after["events"] == before["events"]
    maintain(home, "rebuild")
    assert CanonicalStore(home).counts()["events"] == len(before["events"])


def test_cli_interrupt_has_actionable_message_not_traceback(monkeypatch, capsys):
    def cancel(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("orbit_backend.data_access.ingest.maintain", cancel)
    with pytest.raises(SystemExit) as error:
        main(["rebuild"])
    assert error.value.code == 130
    captured = capsys.readouterr()
    assert "已中断" in captured.err and "Traceback" not in captured.err


@pytest.mark.parametrize("command", ["analytics", "report"])
def test_cli_event_budget_is_explicit_and_no_partial_report(data, tmp_path, capsys, command):
    home, _ = data
    output = tmp_path / ("result.json" if command == "analytics" else "report")
    args = ["--home", str(home), "--no-progress", "--max-events", "1", command, "--output", str(output)]
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    message = capsys.readouterr().err
    assert "--max-events" in message and "--from-ts" in message and "Traceback" not in message
    assert not output.exists()
    args[4] = "1000"
    main(args)
    assert output.exists()


def test_report_time_scope_uses_same_canonical_selector_as_analytics(data):
    store = CanonicalStore(data[0])
    scope = Scope(from_ts=1767225603000, until_ts=1767225604000)
    snapshot = store.report_snapshot(from_ts=scope.from_ts, until_ts=scope.until_ts)
    bundle = store.read_bundle(scope)
    assert {e.id for e in snapshot.events()} == set(bundle["statistical_members"]["event_uids"])


def test_over_budget_read_rejects_before_decoding_event_payloads(data, monkeypatch):
    import orbit_data.analysis_input as reader

    original = reader.decoded

    def guard(row):
        assert "event_uid" not in row.keys(), "over-budget payload must not be materialized"
        return original(row)

    monkeypatch.setattr(reader, "decoded", guard)
    with pytest.raises(ValueError, match="event limit exceeded"):
        reader.read_analysis(data[0], AnalysisScope("UTC"), max_events=1)


def test_projection_probes_each_project_once_but_refreshes_next_run(tmp_path, monkeypatch):
    root, home, project = demo_home(tmp_path / "codex"), tmp_path / "data", tmp_path / "project"
    project.mkdir()
    for path in root.rglob("*.jsonl"):
        path.write_text(path.read_text().replace("/fictional/sample-project", str(project)))
    probes = []

    def git_probe(path, *args):
        probes.append((path, args))
        return None

    monkeypatch.setattr("orbit_data.reduce._git", git_probe)
    ingest(home, "codex", root)
    assert len(probes) == 1
    maintain(home, "rebuild")
    assert len(probes) == 2
    assert CanonicalStore(home).counts()["sessions"] == 3


def test_recorded_git_remote_needs_no_local_git_probe(tmp_path, monkeypatch):
    from orbit_data.reduce import project_for

    def forbidden(*args):
        raise AssertionError("known remote identity needs no Git subprocess")

    monkeypatch.setattr("orbit_data.reduce._git", forbidden)
    with Store(tmp_path / "data") as store:
        pid = project_for(store, str(tmp_path), "https://example.com/team/repo.git")
        row = store.db.execute("SELECT * FROM project WHERE project_id=?", (pid,)).fetchone()
        assert row["key_type"] == "git_remote" and row["key"] == "example.com/team/repo"


def test_analysis_omits_native_copies_but_keeps_facts_and_evidence(data):
    store = CanonicalStore(data[0])
    full = store.read_bundle()
    compact = store.read_bundle(include_native=False)
    assert any(e["ext"] for e in full["events"])
    assert all(e["ext"] == {} for e in compact["events"])
    assert [{k: v for k, v in e.items() if k not in ("ext", "native_key")} for e in full["events"]] == [
        {k: v for k, v in e.items() if k not in ("ext", "native_key")} for e in compact["events"]]
    assert compact["coverage"]["native_event_payload"]["status"] == "excluded"
    assert all(e["ext"] == {} for e in store.analysis_bundle().events)
    assert store.evidence(full["events"][0]["event_uid"]) is not None


@pytest.mark.parametrize("schema_version", [4, 5, 6])
def test_existing_store_adds_indexes_for_deferred_parent_inserts(data, schema_version):
    home, _ = data
    with Store(home) as store:
        # A historical fixture must have its historical columns, not just an old
        # version number attached to the current DDL.
        for table, columns in (("model_call", ("request_identity_quality", "boundary_quality")),
                               ("tool_call", ("command_spec", "wall_elapsed_ms", "native_execution_ms"))):
            for column in columns:
                store.db.execute(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')
        if schema_version == 4:
            store.db.execute("DROP TABLE inventory_item")
            store.db.execute("DROP TABLE inventory_scan")
        store.db.execute(f"PRAGMA user_version={schema_version}")
        store.db.execute("UPDATE schema_manifest SET schema_version=?", (schema_version,))
        names = [r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'fk_%'")]
        # v4 had no inventory_scan; 010 drops two fk_ prefixes of v8 list indexes.
        assert len(names) == (27 if schema_version == 4 else 28)
        for name in names:
            store.db.execute(f'DROP INDEX "{name}"')
    with Store(home) as store:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert store.db.execute("SELECT count(*) FROM inventory_scan").fetchone()[0] == 0
        assert store.db.execute("SELECT count(*) FROM inventory_item").fetchone()[0] == 0
        store.db.execute("BEGIN")
        store.db.execute("PRAGMA defer_foreign_keys=ON")
        roots = {r["rootpage"]: r["name"] for r in store.db.execute("SELECT name,rootpage FROM sqlite_master")}
        for table in ("session", "turn", "tool_call"):
            row = store.db.execute(f"SELECT * FROM {table} LIMIT 1").fetchone()
            columns = ",".join(row.keys())
            placeholders = ",".join("?" for _ in row)
            plan = store.db.execute(f"EXPLAIN INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(row)).fetchall()
            cursors = {op[2]: roots.get(op[3]) for op in plan if op[1] == "OpenRead"}
            scans = {cursors.get(op[2]) for op in plan if op[1] == "Rewind"}
            assert not scans & {"session", "tool_call", "model_call", "link"}
        store.db.execute("ROLLBACK")

"""The local diagnostic must preserve source data and explain an empty result honestly."""

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from tandem_backend.analytics.inputs import Scope

_SPEC = importlib.util.spec_from_file_location(
    "preference_local", Path(__file__).resolve().parents[4] / "evals/analytics/preference_local.py")
local = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(local)


@pytest.fixture
def snapshot(tmp_path):
    database = tmp_path / "snapshot.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE schema_manifest(contract_id TEXT);
            INSERT INTO schema_manifest VALUES ('tandem-session-v1');
            CREATE TABLE session(session_uid TEXT, root_uid TEXT, kind TEXT,
                                 project_id TEXT, started_at INTEGER);
            INSERT INTO session VALUES ('s','s','main','p',0), ('other','other','main','q',0),
                                       ('child','s','subagent','p',0);
            CREATE TABLE event(event_uid TEXT, session_uid TEXT, root_uid TEXT, project_id TEXT,
                               kind TEXT, actor TEXT, seq INTEGER, ts INTEGER, turn_uid TEXT,
                               text TEXT, text_truncated INTEGER, attrs TEXT);
            CREATE VIEW v_analysis_event AS SELECT * FROM event;
        """)
        for uid, sid, ts, text, attrs in (
            ("start", "s", 10, "请修复代码", {"origin": "human"}),
            ("verify", "s", 20, "请运行测试", {"origin": "human"}),
            ("unknown", "s", 21, "直接执行", {"origin": "unknown"}),
            ("replay", "s", 22, "直接执行", {"origin": "human", "replayed_from": "older"}),
            ("child", "child", 25, "直接执行", {"origin": "human"}),
            ("explicit", "s", 30, "以后所有项目用中文", {"origin": "human"}),
            ("other", "other", 20, "无需确认", {"origin": "human"}),
        ):
            connection.execute("INSERT INTO event VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                uid, sid, "s" if sid == "child" else sid, "q" if sid == "other" else "p",
                "message.user", "human", ts, ts, uid, text, 0, json.dumps(attrs)))
    return database


def test_snapshot_uses_time_project_and_source_boundaries_without_writing(snapshot):
    before = hashlib.sha256(snapshot.read_bytes()).digest()
    scope = Scope(from_ts=10, until_ts=30, project_ids=["p"])
    report, preferences, _ = local.diagnose(snapshot, scope)
    assert hashlib.sha256(snapshot.read_bytes()).digest() == before
    assert report["selected_user_messages"] == 4 and report["human_messages"] == 2
    assert report["explicit_records"] == 0 and report["evidence_count"] == 1
    assert preferences["evidence"][0]["evidence_event_uids"] == ["verify"]
    assert report["historical_support"][0]["values"][0]["support_tasks"] == 1
    assert local.diagnose(snapshot, scope)[0]["sample_digest"] == report["sample_digest"]


def test_empty_or_excluded_input_is_no_evidence(snapshot):
    for scope in (Scope(until_ts=10), Scope(excluded_session_uids=["s", "other"])):
        report, preferences, instructions = local.diagnose(snapshot, scope)
        assert report["status"] == "no_evidence" and report["human_messages"] == 0
        assert preferences["evidence"] == instructions == []


def test_message_budget_and_invalid_source_fail_without_truncation(snapshot, tmp_path):
    with pytest.raises(ValueError, match="Message limit exceeded"):
        local.read_snapshot(snapshot, Scope(), max_messages=1)
    with pytest.raises(ValueError, match="must be positive"):
        local.read_snapshot(snapshot, Scope(), max_messages=0)
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(ValueError, match="existing canonical"):
        local.read_snapshot(missing, Scope())
    assert not missing.exists()


def test_cli_saves_details_only_in_private_directory(snapshot, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(local, "ROOT", tmp_path)
    assert local.main(["--db", str(snapshot), "--project-id", "p"]) == 0
    stdout = capsys.readouterr().out
    report = json.loads(stdout)
    assert report["explicit_records"] == 1
    assert "以后所有项目用中文" not in stdout
    output = tmp_path / ".local" / "preference-check"
    folders = list(output.iterdir())
    assert len(folders) == 1
    assert {p.name for p in folders[0].iterdir()} == {"summary.json", "preferences.json", "instruction.json"}
    details = json.loads((folders[0] / "preferences.json").read_text())
    assert {e["source_type"] for e in details["evidence"]} == {"explicit_preference", "task_instruction"}
    with pytest.raises(ValueError, match=".local"):
        local.output_directory(tmp_path / "public")
    with pytest.raises(FileExistsError):
        local.output_directory(folders[0])
    with pytest.raises(SystemExit) as error:
        local.main(["--db", str(snapshot), "--from-ts", "30", "--until-ts", "10"])
    assert error.value.code == 2

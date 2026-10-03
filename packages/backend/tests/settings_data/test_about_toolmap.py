"""SET-11 / SET-13 / HLP-02: about summary and the tool-name map."""

from __future__ import annotations

import json
import sqlite3

from orbit_data.store import Store


def test_about(client):
    body = client.get("/v1/app/about").json()
    assert body["app"]["name"] == "Orbit" and body["app"]["contract"] == "orbit-app-v1"
    components = body["components"]
    for key in ("rules_version", "redaction_version", "prompt_version", "db_schema_version",
                "catalog_schema_version", "feature_vocab", "mappers"):
        assert components[key], key
    assert "codex" in components["mappers"] and "claude_code" in components["mappers"]
    assert body["update"] == {"channel": None, "available": None, "checked_at": None}
    assert {"python", "platform", "arch"} <= body["runtime"].keys()


def test_tool_map_static_without_database(client):
    body = client.get("/v1/app/tool_map").json()
    kinds = {k["kind"]: k for k in body["kinds"]}
    assert "shell" in kinds and "mcp" in kinds and body["observed"] == 0
    assert any(n["name"] == "bash" for n in kinds["shell"]["names"])
    assert body["mcp"]["pattern"] == "mcp__<server>__<tool>"


def test_tool_map_observed_names(client, home):
    Store(home).db.close()
    db = sqlite3.connect(home / "orbit.db", isolation_level=None)
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute("INSERT INTO source VALUES ('src-codex', 'codex', '/x', NULL, 1, 0)")
    db.execute("INSERT INTO session(session_uid, source_id, native_id, kind, root_uid, started_at,"
               " status) VALUES ('s1', 'src-codex', 'n1', 'main', 's1', 1, 'completed')")
    for i, (name, kind) in enumerate([("exec_command", "shell")] * 3 + [
            ("mcp__github__search", "mcp")]):
        db.execute("INSERT INTO tool_call(call_uid, session_uid, name_raw, name, kind, files, "
                   "status, pairing_quality, started_at, duration_source, duration_quality) "
                   "VALUES (?, 's1', ?, ?, ?, ?, 'success', 'paired', 1, 'unknown', 'missing')",
                   (f"c{i}", name, name, kind, json.dumps([])))
    db.close()
    body = client.get("/v1/app/tool_map").json()
    kinds = {k["kind"]: k for k in body["kinds"]}
    shell = {n["name"]: n for n in kinds["shell"]["names"]}
    assert shell["exec_command"] == {"agent": "codex", "name": "exec_command", "calls": 3}
    assert kinds["mcp"]["names"] == [{"agent": "codex", "name": "mcp__github__search",
                                      "calls": 1}]
    assert body["observed"] == 2

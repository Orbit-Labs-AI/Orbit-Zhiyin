"""recommend_inputs section: facts SQL on a tiny synthetic store, shape and size cap."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import pytest

from tandem_backend import features
from tandem_backend.recommend import section
from tandem_backend.services.sections import SECTIONS


@pytest.fixture(autouse=True)
def _unbound_features(monkeypatch):
    """Other suites bind a FeatureService globally; these cases test the raw-scan fallback."""
    monkeypatch.setattr(features, "_service", None)


def test_linked_inventory_rows_are_mapped(monkeypatch):
    linked = {"items": [{"inv_id": "skill:x", "type": "skill", "name": "x", "status": "unused",
                         "resident": {"tokens_est": 120}, "catalog": {"item_id": "cat-x"}}]}
    monkeypatch.setattr(features, "linked_inventory", lambda *a, **kw: linked)
    rows = section._inventory(None, [])
    assert rows[0]["resident_tokens"] == 120 and rows[0]["catalog_item_id"] == "cat-x"
    assert rows[0]["status"] == "unused"

DAY = 86_400_000
T0 = 1_780_000_000_000

SCHEMA = """
CREATE TABLE source (source_id TEXT PRIMARY KEY, agent TEXT);
CREATE TABLE session (session_uid TEXT PRIMARY KEY, source_id TEXT, title TEXT);
CREATE TABLE tool_call (call_uid TEXT PRIMARY KEY, session_uid TEXT, name TEXT,
  command_head TEXT, status TEXT, error_class TEXT, approval TEXT, skill TEXT,
  mcp_server TEXT, files TEXT DEFAULT '[]', started_at INTEGER);
CREATE TABLE model_call (call_uid TEXT PRIMARY KEY, session_uid TEXT, model_id TEXT,
  effort_raw TEXT, input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER);
CREATE TABLE inventory_scan (scan_id INTEGER PRIMARY KEY, source_key TEXT);
CREATE TABLE inventory_item (scan_id INTEGER, inv_id TEXT, type TEXT, name TEXT,
  config_path TEXT, enabled INTEGER, content_hash TEXT, config TEXT);
"""


class FakeStore:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
        finally:
            conn.close()


class FakeMemo:
    def __init__(self, result):
        self.result = result

    def analysis(self, store, scope, with_text, revision):
        return self.result

    def sections(self, store, scope, keys, with_text, revision):
        return self.analysis(store, scope, with_text, revision)


def build(tmp_path, sessions=6):
    path = tmp_path / "tandem.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO source VALUES ('src1','claude_code'), ('src2','codex')")
    calls = []
    for i in range(sessions):
        uid = f"s{i}"
        conn.execute("INSERT INTO session VALUES (?,?,?)", (uid, "src1" if i % 3 else "src2", uid))
        calls += [(f"{uid}-a", uid, "Bash", "git status", "success", None, "approved", None, None),
                  (f"{uid}-b", uid, "Bash", "npm install", "failed", "network", None, None, None),
                  (f"{uid}-c", uid, "Skill", None, "success", None, None, "pdf", None)]
        if i % 2:
            calls.append((f"{uid}-d", uid, "Edit", None, "success", None, None, None, None))
        conn.execute("INSERT INTO model_call VALUES (?,?,?,?,?,?,?)",
                     (f"{uid}-m", uid, "claude-x", "high", 100, 20, 5))
    # A child session folds into its root.
    conn.execute("INSERT INTO session VALUES ('s0-child','src2','child')")
    calls.append(("c-a", "s0-child", "Bash", "ls -la", "success", None, "approved", None, "fs"))
    conn.executemany("INSERT INTO tool_call (call_uid, session_uid, name, command_head, status, "
                     "error_class, approval, skill, mcp_server, started_at) VALUES "
                     "(?,?,?,?,?,?,?,?,?, 1)", calls)
    conn.execute("INSERT INTO inventory_scan VALUES (1,'a'), (2,'a')")
    conn.execute("INSERT INTO inventory_item VALUES (1,'old','skill','old','p',1,'h','{}'),"
                 "(2,'mcp:fs','mcp','fs','~/.claude.json',1,'h2','{\"resident_tokens\": 900}')")
    conn.commit()
    conn.close()
    roots = [{"session_uid": f"s{i}", "project_id": "p1", "started_at": T0 + i * DAY,
              "included_session_uids": [f"s{i}"] + (["s0-child"] if i == 0 else [])}
             for i in range(sessions)]
    signal = {"signal_id": "sig1", "rule_id": "tool_failures", "capabilities": ["env"],
              "evidence": [{"kind": "tool_call", "session_uid": "s1", "id": "x",
                            "task_uid": None}] * 30,
              "scope": {"root_session_uid": "s1"}}
    result = {"analysis_digest": "ad1", "sessions": roots,
              "tasks": {"records": [{"domain": ["web"], "task_type": "debug"},
                                    {"domain": ["web"], "task_type": ["debug"]}]},
              "bottleneck_recommendations": {"signals": [signal], "assessments": [],
                                             "recommendations": [{"resource_id": "r"}] * 25}}
    return FakeStore(path), FakeMemo(result)


def test_registration():
    assert "recommend_inputs" in SECTIONS
    assert SECTIONS["recommend_inputs"].cost == "heavy"


def test_compute_shape(tmp_path):
    store, memo = build(tmp_path)
    inputs = section.compute(store, None, {"_rev": [1, 1]}, memo)
    assert inputs["version"] == "rec-inputs-v1"
    assert inputs["agents"] == {"claude_code": 4, "codex": 2}
    assert inputs["sessions"]["main"] == 6 and inputs["sessions"]["weeks"] == 1.0
    assert inputs["tasks"] == [{"domain": ["web"], "task_type": ["debug"]}]
    assert len(inputs["legacy_cards"]) == 20
    facts = inputs["facts"]
    heads = {f["command_head"]: f for f in facts["readonly_prompts"]}
    assert heads["git status"]["count"] == 6 and heads["ls"]["sessions"] == 1
    assert heads["ls"]["session_uids"] == ["s0"]  # child folded into root
    assert facts["readonly_prompt_sessions"] == 6
    assert facts["failures_by_software"] == [{"software": "npm", "error_class": "network",
                                              "count": 6, "sessions": 6,
                                              "session_uids": [f"s{i}" for i in range(6)]}]
    assert facts["usage"]["skill"]["pdf"]["calls"] == 6
    assert facts["usage"]["mcp"]["fs"]["sessions"] == 1
    assert facts["model_mix"] == [
        {"model_id": "claude-x", "effort": "high", "agent": "claude_code", "sessions": 4,
         "readonly_sessions": 2, "tokens": 500, "readonly_session_uids": ["s2", "s4"]},
        {"model_id": "claude-x", "effort": "high", "agent": "codex", "sessions": 2,
         "readonly_sessions": 1, "tokens": 250, "readonly_session_uids": ["s0"]}]
    day1 = facts["session_days"][1]
    assert day1["session_uid"] == "s1"
    assert day1["problems"] == ["permission_friction", "tool_env_failure"]
    assert day1["readonly_prompts"] == 1 and day1["tool_failures"] == 1 and day1["tokens"] == 125
    assert [i["inv_id"] for i in inputs["inventory"]] == ["mcp:fs"]
    assert inputs["inventory"][0]["resident_tokens"] == 900
    json.dumps(inputs)


def test_size_cap(tmp_path):
    store, memo = build(tmp_path, sessions=3)
    memo.result["bottleneck_recommendations"]["signals"] *= 2000
    inputs = section.compute(store, None, {}, memo)
    assert len(json.dumps(inputs, ensure_ascii=False, separators=(",", ":"))) <= section.MAX_BYTES


def test_readonly_head_prefix():
    assert section.readonly_head("git  status --short") == "git status"
    assert section.readonly_head("gh pr view 12") == "gh pr view"
    assert section.readonly_head("lsof") is None
    assert section.readonly_head(None) is None

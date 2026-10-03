"""Trajectory ledger (section._ledger): scope totals and per-operation costs that narrate turns
into the cards' token / time shares. One hand-timed session tree, plus an older store without
the timing columns."""

from __future__ import annotations

import json
import sqlite3

from fact_db import SCHEMA

from orbit_backend.recommend import section

FULL = """
CREATE TABLE source (source_id TEXT PRIMARY KEY, agent TEXT);
CREATE TABLE session (session_uid TEXT PRIMARY KEY, source_id TEXT, root_uid TEXT);
CREATE TABLE event (event_uid TEXT PRIMARY KEY, session_uid TEXT, kind TEXT, actor TEXT, ts INTEGER,
  attrs TEXT DEFAULT '{}');
CREATE TABLE tool_call (call_uid TEXT PRIMARY KEY, session_uid TEXT, started_at INTEGER, ended_at INTEGER,
  approval_wait_ms INTEGER);
CREATE TABLE model_call (call_uid TEXT PRIMARY KEY, session_uid TEXT, ts INTEGER, input_tokens INTEGER,
  cache_read_tokens INTEGER, cache_write_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER);
"""
HUMAN = json.dumps({"origin": "human"})


def _store():
    conn = sqlite3.connect(":memory:")
    conn.executescript(FULL)
    conn.execute("INSERT INTO source VALUES ('src', 'claude_code')")
    conn.executemany("INSERT INTO session VALUES (?, 'src', 'root')", [("root",), ("sub",)])
    # user 0 → request 1 000 → call a 1 000–4 000 → request 6 000 (reads a) → failed call b 6 000–10 000
    # → request 16 000 (reads b) → user 20 000 → request 22 000 (an answer: no call holds it)
    events = [("u1", "root", "message.user", "human", 0, HUMAN), ("m1", "root", "usage", "agent", 1000, "{}"),
              ("a1", "root", "tool.call", "agent", 1000, "{}"), ("a2", "root", "tool.result", "tool", 4000, "{}"),
              ("m2", "root", "usage", "agent", 6000, "{}"), ("b1", "sub", "tool.call", "agent", 6000, "{}"),
              ("b2", "sub", "tool.result", "tool", 10000, "{}"), ("m3", "sub", "usage", "agent", 16000, "{}"),
              ("u2", "root", "message.user", "human", 20000, HUMAN), ("m4", "root", "usage", "agent", 22000, "{}"),
              ("x", "root", "message.user", "system", 21000, "{}")]  # not a human turn
    conn.executemany("INSERT INTO event VALUES (?,?,?,?,?,?)", events)
    conn.executemany("INSERT INTO tool_call VALUES (?,?,?,?,?)",
                     [("a", "root", 1000, 4000, None), ("b", "sub", 6000, 10000, None),
                      ("c", "root", None, None, 2500)])  # an allowed read-only prompt with a reported wait
    conn.executemany("INSERT INTO model_call VALUES (?,?,?,?,?,?,?,?)",
                     [("r1", "root", 1000, 40, 50, 0, 10, 99), ("r2", "root", 6000, 100, 80, 10, 10, 0),
                      ("r3", "sub", 16000, 100, 150, 0, 50, 0), ("r4", "root", 22000, 200, 150, 0, 50, 0)])
    return conn


def test_ledger_splits_gaps_and_request_tokens_over_calls():
    conn = _store()
    uids = json.dumps(["root", "sub"])
    flags = {"b": (True, False), "c": (False, True)}   # a: a plain call, not in the flags
    ledger = section._ledger(conn, uids, {"root": "root", "sub": "root"}, flags, [("root", 4000)])
    # tokens = input + cache read / write + output (reasoning excluded, as the App counts them): 100+200+300+400
    assert ledger["tokens"] == 1000 and ledger["requests"] == 4 and ledger["requests_by_agent"] == {"claude_code": 4}
    # capped event gaps 1000+0+3000+2000+0+4000+6000+4000+1000+1000 ; two human turns
    assert ledger["active_ms"] == 22000 and ledger["turns"] == 2
    ops = ledger["ops"]
    # a: run 3 000 + wait for the model 2 000, and request 2 that read it ; b: 4 000 + 6 000 and request 3
    assert ops["call"] == {"n": 3, "tokens": 500, "ms": 15000}
    assert ops["failed"] == {"n": 1, "tokens": 300, "ms": 10000}
    # approval waits: c's reported 2 500 ms plus a Codex request → decision of 4 000 ms; never tokens
    assert ops["readonly"] == {"n": 2, "tokens": 0, "ms": 6500}


def test_parallel_calls_share_their_gaps_and_request():
    conn = sqlite3.connect(":memory:")
    conn.executescript(FULL)
    conn.execute("INSERT INTO session VALUES ('s', NULL, 's')")
    conn.executemany("INSERT INTO tool_call VALUES (?,?,?,?,NULL)", [("p", "s", 0, 2000), ("q", "s", 0, 4000)])
    conn.execute("INSERT INTO model_call VALUES ('m', 's', 5000, 0, 0, 0, 100, 0)")
    ops = section._ledger(conn, json.dumps(["s"]), {}, {}, [])["ops"]
    # 0–2 000 both running, 2 000–4 000 one waits and one runs, 4 000–5 000 both wait: 5 000 ms and 100 tokens split
    assert ops["call"] == {"n": 2, "tokens": 100, "ms": 5000}


def test_older_store_without_timing_columns_still_counts_tokens():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO session (session_uid, kind, root_uid) VALUES ('s', 'main', 's')")
    conn.execute("INSERT INTO model_call (call_uid, session_uid, input_tokens, output_tokens) VALUES ('m', 's', 30, 12)")
    conn.execute("INSERT INTO tool_call (call_uid, session_uid, started_at) VALUES ('t', 's', 1000)")
    ledger = section._ledger(conn, json.dumps(["s"]), {}, {}, [])
    assert ledger["tokens"] == 42 and ledger["active_ms"] == 0 and ledger["ops"]["call"]["n"] == 1


def test_readonly_prompt_without_a_recorded_wait_is_counted_not_priced_by_run_time():
    """R8: a flagged read-only call with no approval_wait_ms ran 1 000–4 000; that run time is not
    an approval wait, so it adds nothing to the readonly ms and is counted as unmeasured."""
    conn = _store()
    flags = {"a": (False, True), "c": (False, True)}
    ops = section._ledger(conn, json.dumps(["root", "sub"]), {"root": "root", "sub": "root"}, flags, [])["ops"]
    assert ops["readonly"] == {"n": 1, "tokens": 0, "ms": 2500, "unmeasured": 1}


def test_each_human_turn_carries_its_own_measured_cost():
    """R10: u1 (0) holds requests 1–3 and every gap up to u2, including the wait before u2;
    u2 (20 000) holds request 4 and the last two gaps."""
    conn = _store()
    ledger = section._ledger(conn, json.dumps(["root", "sub"]), {"root": "root", "sub": "root"}, {}, [])
    assert ledger["turn_cost"] == {"by_session": {"root": [2, 1000, 22000]},
                                   "by_event": {"u1": [600, 20000], "u2": [400, 2000]}}

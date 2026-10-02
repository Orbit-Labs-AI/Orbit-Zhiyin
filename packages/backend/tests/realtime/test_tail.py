from __future__ import annotations

import time

from conftest import ATTRS, NOW, Reads

from tandem_backend.realtime.tail import ACTIVE_SQL, load_tails


def _bulk(tandem, sessions=20_000, active=30):
    """Old sessions in bulk (executemany, FTS trigger dropped), then 30 live ones."""
    db = tandem.db
    db.execute("DROP TRIGGER event_ai")  # FTS upkeep is irrelevant to the plan under test.
    old = NOW - 30 * 86_400_000
    db.execute("BEGIN")
    db.executemany(
        "INSERT INTO session(session_uid, source_id, native_id, kind, root_uid, started_at, "
        "status) VALUES (?, 'src-codex', ?, 'main', ?, ?, 'completed')",
        ((f"o{i}", f"o{i}", f"o{i}", old + i) for i in range(sessions)))
    db.executemany(
        "INSERT INTO event(event_uid, session_uid, record_uid, native_key, event_path, kind, "
        "actor, seq, ts, attrs, contract_version, mapper_version) "
        "VALUES (?, ?, ?, '[]', '$', ?, 'assistant', ?, ?, ?, 1, 't')",
        ((f"oe{i}-{j}", f"o{i}", f"or{i}-{j}", ("message", "tool.call", "tool.result")[j],
          j, old + i * 10 + j, ATTRS) for i in range(sessions) for j in range(3)))
    for i in range(active):
        uid = f"s{i}"
        tandem.session(uid, started=NOW - 600_000)
        base = NOW - 300_000 - i * 1000
        for j in range(3):
            tandem.event(uid, base + j * 100, actor="human" if j == 0 else "assistant")
        tandem.call(uid, base + 50)
        tandem.usage(uid, base + 90, 1000)
    db.execute("COMMIT")
    db.execute("ANALYZE")


def test_active_query_uses_index_and_is_fast(tandem):
    _bulk(tandem)
    plan = [row[3] for row in tandem.db.execute(
        "EXPLAIN QUERY PLAN " + ACTIVE_SQL, (NOW - 86_400_000, 200))]
    assert not any(step.startswith("SCAN event") for step in plan), plan
    assert any("event_by_kind_time" in step for step in plan), plan
    reads = Reads(tandem.path)
    started = time.perf_counter()
    tails = load_tails(reads, NOW)
    elapsed = time.perf_counter() - started
    assert len(tails) == 30
    assert elapsed < 0.2, elapsed
    tail = tails[0]
    assert tail.agent == "claude_code" and tail.project == "demo"
    assert [e.actor for e in tail.events] == ["human", "assistant", "assistant"]
    assert tail.usage == {"used_tokens": 1000, "model": "claude-sonnet-4-5"}
    assert tail.calls[0].command_head == "ls"


def test_pending_permission_only_when_newest(tandem):
    tandem.session("a")
    tandem.event("a", NOW - 5000, "permission.request", "hook",
                 attrs={"command": "rm -rf build"})
    tandem.session("b")
    tandem.event("b", NOW - 9000, "permission.request", "hook", text="git push")
    tandem.event("b", NOW - 4000, "permission.decision", "hook")
    tails = {t.session_uid: t for t in load_tails(Reads(tandem.path), NOW)}
    assert tails["a"].pending_permission == {"ts": NOW - 5000, "command": "rm -rf build"}
    assert tails["b"].pending_permission is None

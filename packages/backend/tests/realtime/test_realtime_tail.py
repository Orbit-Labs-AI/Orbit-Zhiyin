from __future__ import annotations

import time

import pytest
from realtime_fixtures import ATTRS, NOW, Reads

from orbit_backend.realtime import classify
from orbit_backend.realtime.tail import ACTIVE_SQL, load_tails


def _bulk(orbit, sessions=20_000, active=30):
    """Old sessions in bulk (executemany, FTS trigger dropped), then 30 live ones."""
    db = orbit.db
    # FTS upkeep is irrelevant to the plan under test (event_search_ai since schema v8).
    db.execute("DROP TRIGGER IF EXISTS event_ai")
    db.execute("DROP TRIGGER IF EXISTS event_search_ai")
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
        orbit.session(uid, started=NOW - 600_000)
        base = NOW - 300_000 - i * 1000
        for j in range(3):
            orbit.event(uid, base + j * 100, actor="human" if j == 0 else "assistant")
        orbit.call(uid, base + 50)
        orbit.usage(uid, base + 90, 1000)
    db.execute("COMMIT")
    db.execute("ANALYZE")


@pytest.mark.serial
def test_active_query_uses_index_and_is_fast(orbit):
    _bulk(orbit)
    plan = [row[3] for row in orbit.db.execute(
        "EXPLAIN QUERY PLAN " + ACTIVE_SQL, (NOW - 86_400_000, 200))]
    assert not any(step.startswith("SCAN event") for step in plan), plan
    assert any("event_by_kind_time" in step for step in plan), plan
    reads = Reads(orbit.path)
    started = time.perf_counter()
    tails = load_tails(reads, NOW)
    elapsed = time.perf_counter() - started
    assert len(tails) == 30
    assert elapsed < 0.2, elapsed
    tail = tails[0]
    assert tail.agent == "claude_code" and tail.project == "demo"
    assert [e.actor for e in tail.events] == ["human", "assistant", "assistant"]
    assert tail.usage == {"used_tokens": 1000, "model": "claude-sonnet-4-5", "window_tokens": None}
    assert tail.calls[0].command_head == "ls"


def test_pending_permission_only_when_newest(orbit):
    orbit.session("a")
    orbit.event("a", NOW - 5000, "permission.request", "hook",
                 attrs={"command": "rm -rf build"})
    orbit.session("b")
    orbit.event("b", NOW - 9000, "permission.request", "hook", text="git push")
    orbit.event("b", NOW - 4000, "permission.decision", "hook")
    tails = {t.session_uid: t for t in load_tails(Reads(orbit.path), NOW)}
    assert tails["a"].pending_permission == {"ts": NOW - 5000, "command": "rm -rf build"}
    assert tails["b"].pending_permission is None


@pytest.mark.parametrize(("fresh", "read", "write", "used", "ratio", "pressure"), [
    # Claude after a compact: the whole new prompt is written to the cache in one call.
    # 2_000 + 0 + 182_000 = 184_000 of the 200k Claude window = 0.92 >= 0.9.
    (2_000, 0, 182_000, 184_000, 0.92, True),
    # Same prompt read back from cache on the next call: 2_000 + 182_000 + 0.
    (2_000, 182_000, None, 184_000, 0.92, True),
    # Without the cache write the prompt would read as 2_000 / 200_000 = 0.01.
    (2_000, 0, 0, 2_000, 0.01, False),
    # Codex-style row: input already fresh (total 120 - cached 40 - written 10 = 70).
    (70, 40, 10, 120, 0.0006, False),
    # Unknown fresh input stays unknown even when caches are known.
    (None, 5_000, 5_000, None, None, False),
])
def test_context_counts_cache_write(orbit, fresh, read, write, used, ratio, pressure):
    orbit.session("s1", started=NOW - 60_000)
    orbit.event("s1", NOW - 3_000, actor="human")
    orbit.event("s1", NOW - 1_000, actor="assistant")
    orbit.usage("s1", NOW - 1_000, fresh, cache_read=read, cache_write=write)
    (tail,) = load_tails(Reads(orbit.path), NOW)
    assert tail.usage["used_tokens"] == used
    state = classify.classify(tail, NOW)
    assert state.state != "idle"
    assert state.context["ratio"] == ratio
    assert ("context_pressure" in state.flags) is pressure

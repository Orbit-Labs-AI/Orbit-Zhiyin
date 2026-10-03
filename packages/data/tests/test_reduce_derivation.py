"""Direct checks of reduce derivations: tool durations, turn splitting and call pairing."""

import pytest

from tandem_data.contract import canonical
from tandem_data.reduce import _duration
from tandem_data.store import Store


def timed(ts, semantics, quality="reported"):
    return {"ts": ts, "attrs": {"time": {"semantics": semantics, "quality": quality}}}


@pytest.mark.parametrize(
    ("call", "result", "attrs", "expected"),
    [
        # A harness-reported duration wins over timestamps.
        (
            timed(1000, "started"),
            timed(9000, "completed"),
            {"duration_ms": 250},
            (250, "reported", "reported"),
        ),
        # Started -> completed, both reported: native bounds, reported quality.
        (timed(1000, "started"), timed(4500, "completed"), {}, (3500, "native_bounds", "reported")),
        # Same bounds but one timestamp estimated: still native bounds, estimated quality.
        (
            timed(1000, "started"),
            timed(4500, "completed", "estimated"),
            {},
            (3500, "native_bounds", "estimated"),
        ),
        # Record write times (not start/complete): only an event difference estimate.
        (
            timed(1000, "created"),
            timed(1600, "created"),
            {},
            (600, "event_difference", "estimated"),
        ),
        # Negative differences are never a duration.
        (timed(5000, "started"), timed(4000, "completed"), {}, (None, "unknown", "missing")),
        # Explicitly unmeasured beats everything, including a reported value.
        (
            timed(1000, "started"),
            timed(2000, "completed"),
            {"duration_unmeasured": True, "duration_ms": 5},
            (None, "unknown", "missing"),
        ),
        # Invalid reported values fall through to the timestamps.
        (
            timed(0, "started"),
            timed(10, "completed"),
            {"duration_ms": -1},
            (10, "native_bounds", "reported"),
        ),
        (
            timed(0, "started"),
            timed(10, "completed"),
            {"duration_ms": True},
            (10, "native_bounds", "reported"),
        ),
        # Missing side or missing timestamp: unknown.
        (None, timed(10, "completed"), {}, (None, "unknown", "missing")),
        (timed(None, "started"), timed(10, "completed"), {}, (None, "unknown", "missing")),
    ],
)
def test_duration_sources(call, result, attrs, expected):
    assert _duration(call, result, attrs) == expected


def user(id_, text, ts):
    return {
        "type": "message",
        "id": id_,
        "timestamp": ts,
        "message": {"role": "user", "content": text},
    }


def assistant(id_, ts, calls=(), text=None):
    content = [
        {"type": "toolCall", "id": c, "name": "bash", "arguments": {"command": "ls"}} for c in calls
    ]
    if text:
        content.append({"type": "text", "text": text})
    return {
        "type": "message",
        "id": id_,
        "timestamp": ts,
        "message": {"role": "assistant", "model": "test", "content": content},
    }


def result(id_, call_id, ts):
    return {
        "type": "message",
        "id": id_,
        "timestamp": ts,
        "message": {
            "role": "toolResult",
            "toolCallId": call_id,
            "toolName": "bash",
            "content": "ok",
            "isError": False,
        },
    }


def derive(tmp_path, rows):
    store = Store(tmp_path / "data")
    source = store.add_source("pi", tmp_path / "source")
    store.capture_stream(
        source, "s.jsonl", [(canonical(r) + "\n").encode() for r in rows], format_name="jsonl"
    )
    store.rebuild()
    return store


def test_derived_turns_split_on_each_human_message(tmp_path):
    rows = [
        {"type": "session", "id": "s", "cwd": "/r"},
        user("u1", "first", "2026-10-02T00:00:00Z"),
        assistant("a1", "2026-10-02T00:00:05Z", text="one"),
        user("u2", "second", "2026-10-02T00:01:00Z"),
        assistant("a2", "2026-10-02T00:01:07Z", text="two"),
    ]
    with derive(tmp_path, rows) as store:
        turns = store.db.execute(
            "SELECT idx,trigger,boundary_source,native_id,started_at,status FROM turn ORDER BY idx"
        ).fetchall()
        assert [tuple(t) for t in turns] == [
            (0, "human", "derived", None, 1790899200000, "unknown"),
            (1, "human", "derived", None, 1790899260000, "unknown"),
        ]
        # Every assistant event belongs to the turn its user message opened.
        rows = store.db.execute(
            "SELECT e.kind,t.idx FROM event e JOIN turn t USING(turn_uid) "
            "WHERE e.kind IN ('message.user','message.assistant') ORDER BY e.seq"
        ).fetchall()
        assert [tuple(r) for r in rows] == [
            ("message.user", 0),
            ("message.assistant", 0),
            ("message.user", 1),
            ("message.assistant", 1),
        ]
        session = store.db.execute("SELECT started_at,ended_at,status FROM session").fetchone()
        # Span = first/last action event; no turn.end on pi, so status stays unknown.
        assert tuple(session) == (1790899200000, 1790899267000, "unknown")


def test_pairing_native_ambiguous_and_orphan(tmp_path):
    rows = [
        {"type": "session", "id": "s", "cwd": "/r"},
        user("u1", "go", "2026-10-02T00:00:00Z"),
        # c1: one call, one result -> paired. dup: two calls share an id -> ambiguous.
        assistant("a1", "2026-10-02T00:00:01Z", calls=("c1",)),
        result("t1", "c1", "2026-10-02T00:00:03Z"),
        assistant("a2", "2026-10-02T00:00:04Z", calls=("dup",)),
        assistant("a3", "2026-10-02T00:00:05Z", calls=("dup",)),
        result("t2", "dup", "2026-10-02T00:00:06Z"),
        # ghost: a result with no call at all -> orphan.
        result("t3", "ghost", "2026-10-02T00:00:07Z"),
    ]
    with derive(tmp_path, rows) as store:
        calls = store.db.execute(
            "SELECT native_call_id,status,pairing_quality,call_event_uid IS NOT NULL AS has_call,"
            "result_event_uid IS NOT NULL AS has_result FROM tool_call ORDER BY started_at,native_call_id"
        ).fetchall()
        summary = sorted(tuple(c) for c in calls)
        assert summary == [
            ("c1", "completed", "native_id", 1, 1),
            ("dup", "ambiguous", "ambiguous", 0, 1),
            ("dup", "unknown", "missing_result", 1, 0),
            ("dup", "unknown", "missing_result", 1, 0),
            ("ghost", "orphan_result", "missing_call", 0, 1),
        ]
        issues = store.db.execute(
            "SELECT COUNT(*) FROM ingest_issue WHERE code='unpaired_tool_result'"
        ).fetchone()[0]
        assert issues == 2
        # Only calls (not orphan/ambiguous result rows) count as tool usage features.
        n = store.db.execute(
            "SELECT n FROM session_feature WHERE feature='tool_category' AND value='shell'"
        ).fetchone()[0]
        assert n == 3

"""A scoped analysis read costs what the scope holds, not what the corpus holds."""

import sqlite3
from contextlib import contextmanager

import tandem_data.analysis_input as analysis_input
from tandem_data.analysis_input import AnalysisScope, read_analysis
from tandem_data.contract import canonical
from tandem_data.store import Store


def transcript(name: str, cwd: str, commands: int) -> list[dict]:
    rows = [
        {"type": "session_meta", "payload": {"id": name, "source": "cli", "cwd": cwd}},
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn"}},
        {"type": "event_msg", "payload": {"type": "item_completed", "turn_id": "turn", "item": {
            "id": "user", "type": "UserMessage",
            "content": [{"type": "text", "text": "synthetic request " + "x" * 400}]}}},
    ]
    for i in range(commands):
        rows.append({"type": "event_msg", "payload": {"type": "item_completed", "turn_id": "turn",
                     "item": {"id": f"command-{i}", "type": "CommandExecution",
                              "command": ["pytest", f"case-{i}"], "status": "completed",
                              "exit_code": 0, "duration_ms": 10,
                              "aggregated_output": "synthetic output " + "y" * 400}}})
    for i, row in enumerate(rows):
        row["timestamp"] = f"2026-10-02T02:{i // 60:02d}:{i % 60:02d}Z"
    return rows


def build(path, other_sessions: int) -> Store:
    store = Store(path)
    source = store.add_source("codex", path / "source")
    sessions = [("small", "/fictional/small", 3)]
    sessions += [(f"big-{n}", "/fictional/big", 40) for n in range(other_sessions)]
    for name, cwd, commands in sessions:
        rows = transcript(name, cwd, commands)
        store.capture_stream(source, f"{name}.jsonl",
                             [(canonical(row) + "\n").encode() for row in rows])
    store.rebuild()
    return store


def measured(store, monkeypatch) -> tuple[dict, int]:
    """Reads the small project's bundle and counts SQLite VM steps spent on it."""
    steps = [0]
    original = analysis_input.readonly_connection

    @contextmanager
    def counting(path):
        with original(path) as connection:
            def tick():
                steps[0] += 1
                return 0

            connection.set_progress_handler(tick, 100)
            yield connection

    monkeypatch.setattr(analysis_input, "readonly_connection", counting)
    db = sqlite3.connect(store.home / "tandem.db")
    project = db.execute(
        "SELECT project_id FROM session WHERE cwd='/fictional/small'").fetchone()[0]
    db.close()
    bundle = read_analysis(store.home, AnalysisScope("UTC", project_ids=(project,)),
                           include_native=False)
    return bundle, steps[0]


def test_scoped_read_does_not_scan_unrelated_events_and_tool_calls(tmp_path, monkeypatch):
    with build(tmp_path / "few", 1) as few, build(tmp_path / "many", 30) as many:
        small_bundle, small_cost = measured(few, monkeypatch)
        large_bundle, large_cost = measured(many, monkeypatch)
        added = sum(
            store.db.execute("SELECT COUNT(*) FROM event").fetchone()[0] * sign
            for store, sign in ((many, 1), (few, -1)))
        assert many.db.execute("SELECT COUNT(*) FROM tool_call").fetchone()[0] > 1000
    # Same selection either way …
    for bundle in (small_bundle, large_bundle):
        assert len(bundle["sessions"]) == 1 and len(bundle["tool_calls"]) == 3
        assert {e["project_id"] for e in bundle["events"]} == {
            bundle["sessions"][0]["project_id"]}
    assert len(small_bundle["events"]) == len(large_bundle["events"])
    # … and unrelated rows cost at most a narrow key probe each (~20 VM steps for the
    # event_context project lookup), never correlated subqueries over every event plus a
    # whole-table tool_call decode (~300 steps per unrelated event before the fix).
    per_unrelated_event = (large_cost - small_cost) * 100 / added
    assert per_unrelated_event < 100, (small_cost, large_cost, added)

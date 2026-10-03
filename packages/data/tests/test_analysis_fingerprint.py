"""Tree fingerprints change exactly when a root session tree's stored rows change."""

import sqlite3

from orbit_data.analysis_fingerprint import fingerprints, known_sessions
from orbit_data.contract import canonical
from orbit_data.store import Store


def codex_rows(sid, text="请运行测试", minute=0):
    stamp = f"2026-03-01T00:{minute:02d}:0"
    return [
        {
            "type": "session_meta",
            "timestamp": stamp + "0Z",
            "payload": {"id": sid, "cwd": "/fictional/fp", "source": "cli", "cli_version": "t"},
        },
        {
            "type": "event_msg",
            "timestamp": stamp + "1Z",
            "payload": {"type": "task_started", "turn_id": f"turn-{sid}"},
        },
        {
            "type": "turn_context",
            "timestamp": stamp + "1Z",
            "payload": {"turn_id": f"turn-{sid}", "model": "fixture-model"},
        },
        {
            "type": "response_item",
            "timestamp": stamp + "2Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        },
        {
            "type": "response_item",
            "timestamp": stamp + "3Z",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "call_id": f"call-{sid}",
                "arguments": '{"cmd":"pytest"}',
            },
        },
        {
            "type": "response_item",
            "timestamp": stamp + "4Z",
            "payload": {
                "type": "function_call_output",
                "call_id": f"call-{sid}",
                "output": '{"exit_code":0}',
            },
        },
    ]


def write(store, source, sid, rows):
    raw = "".join(canonical(row) + "\n" for row in rows).encode()
    store.capture_stream(source, f"sessions/{sid}.jsonl", [raw])


def test_tree_fingerprints_track_appends_and_leave_other_trees_unchanged(tmp_path):
    home = tmp_path / "data"
    with Store(home) as store:
        source = store.add_source("codex", tmp_path / "source")
        for index in range(3):
            write(store, source, f"fp-{index}", codex_rows(f"fp-{index}", minute=index))
        store.rebuild()
    first = fingerprints(home)
    assert len(first.trees) == 3 and first.projection_run_id is not None
    roots = first.root_of()
    assert len(roots) == 3 and set(roots.values()) == set(first.trees)
    tree = next(iter(first.trees.values()))
    assert tree.events > 0 and tree.min_ts is not None and tree.max_ts >= tree.min_ts
    # Fingerprinting is deterministic for an unchanged database.
    assert fingerprints(home).input_fp() == first.input_fp()

    # Appending a new session leaves every existing tree fingerprint untouched.
    with Store(home) as store:
        source = store.add_source("codex", tmp_path / "source")
        write(store, source, "fp-3", codex_rows("fp-3", minute=3))
        store.rebuild()
    second = fingerprints(home)
    assert set(second.trees) > set(first.trees) and len(second.trees) == 4
    assert all(second.trees[root].fp == first.trees[root].fp for root in first.trees)
    assert second.input_fp() != first.input_fp()
    assert second.input_fp(first.trees) != first.input_fp(first.trees)  # new projection run

    # Appending to an existing session changes that tree and only that tree.
    with Store(home) as store:
        source = store.add_source("codex", tmp_path / "source")
        rows = codex_rows("fp-1", minute=1)
        rows.append(
            {
                "type": "response_item",
                "timestamp": "2026-03-01T00:01:09Z",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "再补一个用例"}],
                },
            }
        )
        write(store, source, "fp-1", rows)
        store.rebuild()
    third = fingerprints(home)
    grown = [r for r in second.trees if third.trees[r].events > second.trees[r].events]
    assert len(grown) == 1 and third.trees[grown[0]].fp != second.trees[grown[0]].fp
    # Re-projection shifts later trees' rowids as a block; that alone is not a change.
    changed = [r for r in second.trees if third.trees[r].fp != second.trees[r].fp]
    assert changed == grown
    assert known_sessions(home, [*roots, "missing"]) == set(roots)


def test_rowid_or_count_changes_alone_invalidate_the_tree(tmp_path):
    home = tmp_path / "data"
    with Store(home) as store:
        source = store.add_source("codex", tmp_path / "source")
        for index in range(2):
            write(store, source, f"rw-{index}", codex_rows(f"rw-{index}", minute=index))
        store.rebuild()
    before = fingerprints(home)
    connection = sqlite3.connect(home / "orbit.db")
    connection.execute("PRAGMA foreign_keys=OFF")
    session, max_rowid = connection.execute(
        "SELECT session_uid, max(rowid) FROM event GROUP BY session_uid ORDER BY session_uid"
    ).fetchone()
    # Re-inserting the same event under a new rowid keeps count and seq but moves max(rowid).
    connection.execute(
        "UPDATE event SET rowid=(SELECT max(rowid)+1 FROM event) WHERE rowid=?", (max_rowid,)
    )
    connection.commit()
    connection.close()
    after = fingerprints(home)
    root = before.root_of()[session]
    assert after.trees[root].fp != before.trees[root].fp
    others = set(before.trees) - {root}
    assert all(after.trees[r].fp == before.trees[r].fp for r in others)

    # In-place session metadata updates are part of the tree identity as well.
    other = next(iter(others))
    connection = sqlite3.connect(home / "orbit.db")
    connection.execute("UPDATE session SET title='renamed' WHERE root_uid=?", (other,))
    connection.commit()
    connection.close()
    renamed = fingerprints(home)
    assert renamed.trees[other].fp != after.trees[other].fp
    assert renamed.trees[root].fp == after.trees[root].fp


def test_fingerprints_are_reused_until_the_database_changes(tmp_path):
    home = tmp_path / "data"
    with Store(home) as store:
        source = store.add_source("codex", tmp_path / "source")
        write(store, source, "memo-0", codex_rows("memo-0"))
        store.rebuild()
    first = fingerprints(home)
    assert fingerprints(home) is first  # no commit since: the memo serves it
    db = sqlite3.connect(home / "orbit.db")
    db.execute("UPDATE event SET ts = ts + 1 WHERE rowid = (SELECT min(rowid) FROM event)")
    db.commit()
    db.close()
    second = fingerprints(home)
    assert second is not first and second.input_fp() != first.input_fp()

"""Codex rollouts mapped by workers must equal the writer's serial mapping, table by table.

Only constructed records: plain rollouts, a native history fork with an exact mirror of the
superseded branch, a mirrored archive copy, a spawned subagent with an inherited prefix,
``session_index.jsonl``, a ``state_5.sqlite`` threads table and damaged lines.
"""

import json
import random
import sqlite3

import pytest
from _integrity import assert_integrity, differing_tables, logical_digest

from orbit_data import parallel
from orbit_data.contract import canonical
from orbit_data.service import ImportRequest, ImportService
from orbit_data.store import Store

OLD = "11111111-1111-1111-1111-111111111111"
NEW = "22222222-2222-2222-2222-222222222222"
PARENT = "33333333-3333-3333-3333-333333333333"
CHILD = "44444444-4444-4444-4444-444444444444"


def _write(path, records, tail=b""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(canonical(r) + "\n" for r in records).encode() + tail)


def _turn(rng, session, turn, ts):
    turn_id = f"{session}-t{turn}"
    rows = [
        {
            "type": "event_msg",
            "timestamp": ts,
            "payload": {"type": "task_started", "turn_id": turn_id},
        },
        {"type": "turn_context", "timestamp": ts, "payload": {"turn_id": turn_id, "model": "m"}},
        {
            "type": "event_msg",
            "timestamp": ts,
            "payload": {"type": "user_message", "message": f"ask {rng.randrange(9)}"},
        },
        {
            "type": "response_item",
            "timestamp": ts,
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": f"ask {turn}"}],
            },
        },
    ]
    for call in range(rng.randint(0, 3)):
        call_id = f"{turn_id}-c{call}"
        rows += [
            {
                "type": "response_item",
                "timestamp": ts,
                "payload": {
                    "type": "function_call",
                    "id": f"fc-{call_id}",
                    "call_id": call_id,
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": f"ls {call}"}),
                },
            },
            {
                "type": "response_item",
                "timestamp": ts,
                "payload": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": f"Process exited with code {rng.choice((0, 0, 1))}\nok",
                },
            },
        ]
    rows += [
        {
            "type": "event_msg",
            "timestamp": ts,
            "payload": {"type": "agent_message", "message": f"done {turn}"},
        },
        {
            "type": "token_usage_record",
            "timestamp": ts,
            "payload": {
                "response_id": f"r-{turn_id}",
                "model": "m",
                "input_tokens": rng.randrange(100),
                "output_tokens": rng.randrange(50),
                "cached_input_tokens": rng.randrange(10),
            },
        },
        {
            "type": "event_msg",
            "timestamp": ts,
            "payload": {"type": "task_complete", "turn_id": turn_id},
        },
    ]
    return rows


def _session(rng, native, turns, **meta):
    rows = [{"type": "session_meta", "payload": {"id": native, "cwd": "/fixture", **meta}}]
    for turn in range(turns):
        rows += _turn(rng, native, turn, f"2026-01-01T00:{turn:02d}:00Z")
    return rows


def build_codex(root, seed):
    rng = random.Random(seed)
    paths = []
    for index in range(rng.randint(26, 34)):
        native = f"5{index:07d}-0000-0000-0000-{seed:012d}"
        path = root / f"sessions/2026/01/01/rollout-{native}.jsonl"
        tail = b'{"type":"event_msg"' if index == 3 else b""  # pending tail
        rows = _session(rng, native, rng.randint(1, 5))
        if index == 5:
            rows.insert(2, {"type": "future_record", "payload": {"fixture_only": True}})
        _write(path, rows, tail)
        if index == 7:
            with path.open("ab") as out:
                out.write(b"not json\n")
        paths.append((native, path))
    # Exact archived mirror of one plain rollout.
    mirrored = paths[1][1]
    (root / "archived_sessions").mkdir(parents=True, exist_ok=True)
    (root / "archived_sessions" / mirrored.name).write_bytes(mirrored.read_bytes())
    # Native history fork: the new branch keeps the old one's first two records.
    old = [
        {"ordinal": 0, "type": "session_meta", "payload": {"id": "logical"}},
        {"ordinal": 1, "type": "event_msg", "payload": {"type": "user_message", "message": "kept"}},
        {
            "ordinal": 2,
            "type": "event_msg",
            "payload": {"type": "agent_message", "message": "gone"},
        },
    ]
    _write(root / f"sessions/rollout-{OLD}.jsonl", old)
    _write(root / "sessions/rollout-0000-copy.jsonl", old)
    _write(
        root / f"sessions/rollout-{NEW}.jsonl",
        [
            {
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "id": "logical",
                    "history_base": {"thread_id": OLD, "end_ordinal_exclusive": 2},
                },
            },
            {
                "ordinal": 2,
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "now"},
            },
        ],
    )
    # Spawned subagent whose first records replay its parent's.
    parent = _session(rng, PARENT, 2)
    _write(root / f"sessions/rollout-{PARENT}.jsonl", parent)
    child_meta = {
        "type": "session_meta",
        "payload": {
            "id": CHILD,
            "parent_thread_id": PARENT,
            "source": {"subagent": {"thread_spawn": {"parent_thread_id": PARENT}}},
            "subagent_history_start_ordinal": 4,
        },
    }
    _write(
        root / f"sessions/rollout-{CHILD}.jsonl",
        [child_meta, *parent[1:4], *_turn(rng, CHILD, 9, "2026-01-02T00:00:00Z")],
    )
    _write(
        root / "session_index.jsonl",
        [{"id": native, "thread_name": f"title {native[:8]}"} for native, _ in paths[:10]],
    )
    with sqlite3.connect(root / "state_5.sqlite") as db:
        db.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT, cwd TEXT)"
        )
        db.executemany(
            "INSERT INTO threads VALUES(?,?,?,?)",
            [(native, str(path), f"thread {native[:8]}", "/fixture") for native, path in paths]
            + [("logical", str(root / f"sessions/rollout-{NEW}.jsonl"), "fork", "/fixture")],
        )
    db.close()
    return paths


def _import(home, root, workers, threshold=None):
    with Store(home) as store:
        service = ImportService(store, workers=workers)
        if threshold is not None:
            service.pool.threshold = threshold
        try:
            result = service.import_source(ImportRequest("codex", root))
            assert result["capture_errors"] == 0
        finally:
            service.close()
        assert_integrity(store)
    return logical_digest(home)


def _grow(root, paths, seed):
    rng = random.Random(seed + 1000)
    native, path = paths[rng.randrange(len(paths))]
    with path.open("ab") as out:
        for row in _turn(rng, native, 40, "2026-01-03T00:00:00Z"):
            out.write((canonical(row) + "\n").encode())
    _write(root / "session_index.jsonl", [{"id": native, "thread_name": "renamed"}])


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_parallel_codex_mapping_matches_serial(tmp_path, monkeypatch, seed):
    root = tmp_path / "codex"
    paths = build_codex(root, seed)
    outcomes = []
    map_file = parallel.map_file

    def counted(task, spill_dir=None):
        outcome = map_file(task, spill_dir)
        if task["info"]["agent"] == "codex":
            outcomes.append("serial" if outcome.get("serial") else "worker")
        return outcome

    after = parallel.MapPlan.after_history
    remapped = []

    def counted_after(self, mappers):
        before = {k for k, m in mappers.items() if isinstance(m, parallel.ReplayMapper)}
        after(self, mappers)
        remapped.extend(k for k in before if not isinstance(mappers[k], parallel.ReplayMapper))

    homes = {"serial": (1, None), "inline": (8, 10_000), "pooled": (8, 0)}

    def run_all():
        digests = {}
        for name, args in homes.items():
            if name == "pooled":  # Spawned workers import the real, unpatched module.
                digests[name] = _import(tmp_path / name, root, *args)
                continue
            with monkeypatch.context() as patch:
                patch.setattr(parallel, "SPILL_CHUNK_RECORDS", 3)  # many chunks per file
                patch.setattr(parallel, "map_file", counted)
                patch.setattr(parallel.MapPlan, "after_history", counted_after)
                digests[name] = _import(tmp_path / name, root, *args)
        for name in ("inline", "pooled"):
            assert differing_tables(tmp_path / "serial", tmp_path / name) == []
        assert len(set(digests.values())) == 1

    run_all()
    assert "worker" in outcomes and "serial" in outcomes  # the forked child stays on the writer
    assert remapped  # the superseded history branch was re-mapped by the writer

    # A live rollout grows and its title changes: the incremental rebuild agrees as well.
    _grow(root, paths, seed)
    run_all()
    with Store(tmp_path / "pooled") as store:
        assert store.db.execute(
            "SELECT COUNT(*) FROM event WHERE text='renamed' AND kind='session.title'"
        ).fetchone()[0]


def test_worker_spill_chunks_are_removed_after_replay(tmp_path, monkeypatch):
    root = tmp_path / "codex"
    build_codex(root, 4)
    monkeypatch.setattr(parallel, "SPILL_CHUNK_RECORDS", 2)
    with Store(tmp_path / "home") as store:
        service = ImportService(store, workers=8)
        service.pool.threshold = 10_000  # in-process, same code as a worker
        try:
            service.import_source(ImportRequest("codex", root))
            spill = service.pool._spill
            assert spill is not None
            assert list((tmp_path / "home").glob("import-*/*.map")) == []
        finally:
            service.close()
        assert not (tmp_path / "home" / spill).exists() if spill else True

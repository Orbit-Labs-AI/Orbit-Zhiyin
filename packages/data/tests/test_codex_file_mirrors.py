"""Native file-copy regressions, using only constructed Codex records."""

import pytest
import zstandard

from tandem_data.contract import canonical
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store


def write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(r) + "\n" for r in records))


def native_records():
    return [
        {"type": "session_meta", "payload": {"id": "original", "cwd": "/fixture"}},
        {"type": "turn_context", "payload": {"turn_id": "turn", "model": "fixture"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "try again"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "try again"}},
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "call_id": "call",
                "name": "exec_command",
                "arguments": '{"cmd":"pytest"}',
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call",
                "output": '{"exit_code":0}',
            },
        },
        {
            "type": "token_usage_record",
            "payload": {
                "response_id": "request",
                "model": "fixture",
                "input_tokens": 11,
                "output_tokens": 3,
                "cached_input_tokens": 7,
            },
        },
        {"type": "future_record", "payload": {"fixture_only": True}},
    ]


def facts(store):
    return {
        "events": [tuple(r) for r in store.db.execute("SELECT event_uid,seq,kind FROM event")],
        "humans": [
            tuple(r) for r in store.db.execute("SELECT event_uid,text FROM v_human_message")
        ],
        "tools": [tuple(r) for r in store.db.execute("SELECT call_uid,status FROM tool_call")],
        "models": [tuple(r) for r in store.db.execute("SELECT * FROM model_call")],
    }


@pytest.mark.parametrize("compressed", [False, True])
def test_exact_file_copy_does_not_duplicate_events_and_keeps_all_raw_evidence(tmp_path, compressed):
    root = tmp_path / "codex"
    original = root / "sessions/z-original.jsonl"
    write(original, native_records())
    with Store(tmp_path / "data") as store:
        service = ImportService(store)
        service.import_source(ImportRequest("codex", root))
        before = facts(store)
        assert len(before["humans"]) == 2  # Identical native messages are separate inputs.
        assert len(before["models"]) == len(before["tools"]) == 1
        copy = root / ("sessions/a-copy.jsonl.zst" if compressed else "sessions/a-copy.jsonl")
        data = original.read_bytes()
        copy.write_bytes(zstandard.ZstdCompressor().compress(data) if compressed else data)
        result = service.import_source(ImportRequest("codex", root))
        assert result["current_unparsed"] == 0
        assert facts(store) == before
        assert store.db.execute("SELECT count(*) FROM raw_record").fetchone()[0] == 16
        assert (
            store.db.execute(
                "SELECT count(*) FROM raw_record WHERE disposition='duplicate'"
            ).fetchone()[0]
            == 8
        )
        assert (
            store.db.execute(
                "SELECT count(*) FROM record_event WHERE relation='duplicate'"
            ).fetchone()[0]
            == 8
        )
        assert (
            store.db.execute("SELECT count(*) FROM event WHERE kind='unknown'").fetchone()[0] == 1
        )
        assert not store.db.execute("PRAGMA foreign_key_check").fetchall()
        assert store.verify()["integrity"] == "ok"
        store.rebuild()
        assert (
            facts(store) == before
        )  # Earlier-sorting copy cannot replace the published representative.
        assert service.import_source(ImportRequest("codex", root))["changed"] == 0
        assert facts(store) == before
        assert original.read_bytes() == data


def test_native_filename_keeps_mirror_representative_equal_in_full_and_incremental_import(tmp_path):
    root = tmp_path / "codex"
    original = root / "sessions/rollout-original.jsonl"
    copy = root / "sessions/000-copy.jsonl"
    write(original, native_records())
    copy.write_bytes(original.read_bytes())
    with Store(tmp_path / "full") as store:
        ImportService(store).import_source(ImportRequest("codex", root))
        full = facts(store)
    with Store(tmp_path / "incremental") as store:
        service = ImportService(store)
        service.import_source(ImportRequest("codex", root, files=(copy.relative_to(root),)))
        service.import_source(ImportRequest("codex", root))
        assert facts(store) == full
        assert store.verify()["integrity"] == "ok"


def test_diverging_file_is_not_silently_treated_as_an_exact_mirror(tmp_path):
    root = tmp_path / "codex"
    records = native_records()
    write(root / "sessions/original.jsonl", records)
    copy = root / "sessions/copy.jsonl"
    write(copy, records)
    with Store(tmp_path / "data") as store:
        service = ImportService(store)
        service.import_source(ImportRequest("codex", root))
        assert len(facts(store)["humans"]) == 2
        records[2] = {
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "distinct new input"},
        }
        write(copy, records)
        service.import_source(ImportRequest("codex", root))
        assert "distinct new input" in [r[1] for r in facts(store)["humans"]]
        assert not store.db.execute(
            "SELECT 1 FROM source_file WHERE json_extract(watermark,'$.mirror_file_id') IS NOT NULL"
        ).fetchall()
        assert store.verify()["integrity"] == "ok"


def test_damaged_and_pending_rows_in_mirrors_keep_their_original_disposition(tmp_path):
    root = tmp_path / "codex"
    original = root / "sessions/original.jsonl"
    write(original, native_records())
    data = original.read_bytes() + b'{broken\n{"type":"event_msg"'
    original.write_bytes(data)
    (root / "sessions/copy.jsonl").write_bytes(data)
    with Store(tmp_path / "data") as store:
        result = ImportService(store).import_source(ImportRequest("codex", root))
        assert result["current_unparsed"] == 2
        assert len(facts(store)["humans"]) == 2
        assert (
            store.db.execute(
                "SELECT count(*) FROM raw_record WHERE native_type='pending_tail' AND disposition='ignored' AND json_extract(note,'$.reason')='incomplete_tail_retained_in_L0'"
            ).fetchone()[0]
            == 2
        )
        assert store.verify()["integrity"] == "ok"


def test_parent_lookup_uses_canonical_file_before_mirror_relations_are_restored(tmp_path):
    root = tmp_path / "codex"
    parent = native_records()[:3]
    write(root / "sessions/parent.jsonl", parent)
    write(root / "sessions/z-parent-copy.jsonl", parent)
    inherited = [
        {
            "type": "session_meta",
            "payload": {
                "id": "child",
                "parent_thread_id": "original",
                "subagent_history_start_ordinal": 3,
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": "original"}}},
            },
        },
        *parent[1:3],
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "child response"}},
    ]
    write(root / "sessions/child.jsonl", inherited)
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("codex", root))
        assert len(facts(store)["humans"]) == 1
        assert (
            store.db.execute(
                "SELECT count(*) FROM raw_record WHERE disposition='replayed'"
            ).fetchone()[0]
            == 2
        )
        assert not store.db.execute(
            "SELECT 1 FROM ingest_issue WHERE code='inherited_parent_evidence_unavailable'"
        ).fetchall()
        assert store.verify()["integrity"] == "ok"


def test_history_base_alias_survives_when_its_file_has_an_earlier_sorting_mirror(tmp_path):
    root = tmp_path / "codex"
    old = "11111111-1111-1111-1111-111111111111"
    new = "22222222-2222-2222-2222-222222222222"
    records = [
        {"ordinal": 0, "type": "session_meta", "payload": {"id": "logical"}},
        {"ordinal": 1, "type": "event_msg", "payload": {"type": "user_message", "message": "kept"}},
        {
            "ordinal": 2,
            "type": "event_msg",
            "payload": {"type": "agent_message", "message": "reverted"},
        },
    ]
    write(root / f"sessions/rollout-{old}.jsonl", records)
    write(root / "sessions/rollout-0000-copy.jsonl", records)
    write(
        root / f"sessions/rollout-{new}.jsonl",
        [
            {
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "id": "logical",
                    "history_base": {"thread_id": old, "end_ordinal_exclusive": 2},
                },
            },
            {
                "ordinal": 2,
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "current"},
            },
        ],
    )
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("codex", root))
        assert [
            r[0] for r in store.db.execute("SELECT text FROM event WHERE kind='message.assistant'")
        ] == ["current"]
        assert len(facts(store)["humans"]) == 1
        assert not store.db.execute(
            "SELECT 1 FROM ingest_issue WHERE code='ambiguous_active_history'"
        ).fetchall()
        assert store.verify()["integrity"] == "ok"

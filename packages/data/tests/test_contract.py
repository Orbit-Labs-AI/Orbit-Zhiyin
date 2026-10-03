import json
import sqlite3

import pytest
from jsonschema import ValidationError

from orbit_data.contract import EventDraft, normalize_usage, time_fields, uid, validate_event
from orbit_data.store import Store


def test_structured_ids_and_time_quality():
    assert uid("event", ["a:b", "c"]) != uid("event", ["a", "b:c"])
    assert uid("event", ["a", "b"]) != uid("record", ["a", "b"])
    assert time_fields(1.234, "ts", "seconds")[0] == 1234
    assert time_fields(1234, "ts", "milliseconds")[0] == 1234
    for value in (None, "bad", "2026-10-02T10:00:00"):
        assert time_fields(value, "ts")[0] is None
    assert (
        time_fields("2026-10-02T10:00:00+08:00", "ts")[0]
        == time_fields("2026-10-02T02:00:00Z", "ts")[0]
    )


def test_null_is_not_zero_and_usage_buckets():
    assert normalize_usage({}, "codex")["input_tokens"] is None
    usage = normalize_usage(
        {
            "input_tokens": 100,
            "cached_input_tokens": 40,
            "output_tokens": 20,
            "reasoning_output_tokens": 5,
        },
        "codex",
    )
    assert usage["input_tokens"] == 60 and usage["output_tokens"] == 20
    assert normalize_usage({"output": 20, "reasoning": 5}, "opencode")["output_tokens"] == 25
    with pytest.raises(ValueError):
        normalize_usage({"input_tokens": 1, "cached_input_tokens": 2}, "codex")


def test_schema_rejects_fake_time_and_snapshot_call():
    draft = EventDraft(
        "session",
        ["key"],
        "usage",
        "model.usage",
        attrs={
            "time": {
                "source_field": None,
                "semantics": "unknown",
                "quality": "missing",
                "reported": {},
            },
            "usage_scope": "call",
            "measurement": "cumulative",
            "coverage": "self",
            "reported": {},
            "request_key": ["r"],
        },
    )
    with pytest.raises(ValidationError):
        validate_event(draft.envelope("record", 0, "1"))
    draft.kind, draft.attrs = "message.assistant", {"time": draft.attrs["time"]}
    draft.ts = 0
    with pytest.raises(ValidationError):
        validate_event(draft.envelope("record", 0, "1"))


def test_sqlite_constraints_and_lossless_source(tmp_path):
    with Store(tmp_path / "data") as store:
        assert store.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            store.db.execute(
                "INSERT INTO source_file(file_id,source_id,relative_path,role,format) VALUES('f','missing','a','transcript','jsonl')"
            )
        source = store.add_source("pi", tmp_path / "source")
        raw = b'{"type":"session","id":"s","cwd":"/missing/demo"}\n' + b"not-json\n"
        store.capture_stream(source, "s.jsonl", [raw])
        records = store.db.execute("SELECT record_uid FROM raw_record ORDER BY ordinal").fetchall()
        assert store.read_raw(records[0][0]) + store.read_raw(records[1][0]) == raw
        result = store.rebuild()
        assert result["records"] == 2
        assert store.verify()["unparsed"] == 1
        assert (
            store.db.execute("SELECT disposition FROM raw_record ORDER BY ordinal").fetchall()[0][0]
            == "mapped"
        )


def test_snapshot_schema_is_valid_json():
    from importlib.resources import files

    assert json.loads(files("orbit_data").joinpath("schemas/event-v1.schema.json").read_text())[
        "title"
    ]

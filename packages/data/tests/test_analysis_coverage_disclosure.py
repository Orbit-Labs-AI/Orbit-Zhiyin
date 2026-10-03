"""read_analysis discloses what the default analysis views leave out (audit T-08)."""

import json
from importlib.resources import files

import jsonschema

from orbit_data.analysis_input import AnalysisScope, read_analysis
from orbit_data.contract import canonical
from orbit_data.store import Store

ISO = "2026-01-01T00:00:00.000Z"


def pi_session(sid, model, usage):
    return [
        {"type": "session", "id": sid, "timestamp": ISO, "cwd": "/fixture"},
        {
            "type": "message",
            "id": sid + "u",
            "timestamp": ISO,
            "message": {"role": "user", "content": "hi"},
        },
        {
            "type": "message",
            "id": sid + "a",
            "timestamp": ISO,
            "message": {
                "role": "assistant",
                "model": model,
                "provider": "anthropic",
                "content": [{"type": "text", "text": "ok"}],
                "usage": usage,
            },
        },
    ]


def build(tmp_path):
    # main1: known model; main2 and rev: a model name absent from the model table.
    store = Store(tmp_path / "data")
    source = store.add_source("pi", tmp_path / "pi")
    for sid, model, usage in (
        ("main1", "claude-sonnet-4-5", {"input": 100, "output": 20}),
        ("main2", "made-up-model-x", {"input": 7, "output": 3}),
        ("rev", "made-up-model-x", {"input": 40, "output": 5}),
    ):
        store.capture_stream(
            source,
            f"sessions/{sid}.jsonl",
            [(canonical(row) + "\n").encode() for row in pi_session(sid, model, usage)],
        )
    store.rebuild()
    return store


def uid(store, native):
    return store.db.execute(
        "SELECT session_uid FROM session WHERE native_id=?", (native,)
    ).fetchone()[0]


def test_coverage_reports_excluded_trees_status_share_and_unmapped_models(tmp_path):
    with build(tmp_path) as store:
        # rev stands for a Codex review / `claude -p` automation tree: the views drop it.
        store.db.execute(
            "UPDATE session SET kind='review' WHERE session_uid=?", (uid(store, "rev"),)
        )
        store.db.execute(
            "UPDATE session SET status='completed' WHERE session_uid=?", (uid(store, "main1"),)
        )
    coverage = read_analysis(tmp_path / "data", AnalysisScope("UTC"))["coverage"]
    excluded = coverage["excluded_sessions"]
    assert excluded["status"] == "excluded" and excluded["rows"] == 1
    assert excluded["reason_counts"] == {"excluded_kind_review": 1}
    assert excluded["model_calls"] == 1
    assert excluded["tokens"]["input_tokens"] == 40
    assert excluded["tokens"]["output_tokens"] == 5
    # No excluded call reported reasoning tokens or cost: unknown, not zero.
    assert excluded["tokens"]["reasoning_tokens"] is None
    assert excluded["cost_usd"] is None
    # Two analysed sessions, one with a known final status.
    assert coverage["sessions"]["rows"] == 2
    assert coverage["sessions"]["status_known_rows"] == 1
    assert coverage["sessions"]["status_known_share"] == 0.5
    # Two analysed calls (main1, main2); main2's model is unmapped.
    assert coverage["model_call"]["unmapped_model_rows"] == 1
    assert coverage["model_call"]["unmapped_model_share"] == 0.5
    schema = json.loads(
        files("orbit_data").joinpath("schemas/coverage-v1.schema.json").read_text()
    )
    jsonschema.validate(excluded, schema)


def test_excluded_disclosure_follows_scope_and_orphans(tmp_path):
    with build(tmp_path) as store:
        store.db.execute(
            "UPDATE session SET lineage_unresolved=1 WHERE session_uid=?", (uid(store, "main2"),)
        )
        orphan = uid(store, "main2")
    coverage = read_analysis(tmp_path / "data", AnalysisScope("UTC"))["coverage"]
    assert coverage["excluded_sessions"]["reason_counts"] == {"excluded_lineage_unresolved": 1}
    assert coverage["excluded_sessions"]["tokens"]["input_tokens"] == 7
    # A session the caller excluded on purpose is not reported as a hidden gap.
    scoped = read_analysis(
        tmp_path / "data", AnalysisScope("UTC", excluded_session_uids=(orphan,))
    )["coverage"]
    assert scoped["excluded_sessions"]["rows"] == 0
    # A time window before every event leaves nothing in scope.
    empty = read_analysis(tmp_path / "data", AnalysisScope("UTC", until_ts=1))["coverage"]
    assert empty["excluded_sessions"] == {
        "status": "available",
        "rows": 0,
        "reasons": [],
        "reason_counts": {},
        "model_calls": 0,
        "tokens": dict.fromkeys(
            (
                "input_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "output_tokens",
                "reasoning_tokens",
            )
        ),
        "cost_usd": None,
    }
    assert empty["sessions"]["status_known_share"] is None

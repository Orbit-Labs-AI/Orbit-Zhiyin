"""Synthetic regressions for L3 quality: tool status, command heads, models/cost, session span."""

import json

import pytest

from tandem_data.analysis_input import AnalysisScope, read_analysis
from tandem_data.connectors.codex import output_status
from tandem_data.contract import canonical
from tandem_data.models import PRICE_TABLE_VERSION, canonical_model, cost_usd
from tandem_data.shell import command_head
from tandem_data.store import Store


def capture(store, agent, root, rows, filename="fixture.jsonl"):
    source = store.add_source(agent, root / "source")
    raw = "".join(canonical(row) + "\n" for row in rows).encode()
    store.capture_stream(source, filename, [raw], format_name="jsonl")
    return source


@pytest.mark.parametrize(
    ("command", "head"),
    [
        ("cd /repo && git status", "git status"),
        ('/bin/zsh -lc "git -C /x status --short"', "git status"),
        ("S=/tmp/x/y; ls $S", "ls"),
        ("for f in *; do wc -l $f; done", "wc"),
        (["bash", "-lc", "cd /a && pytest -q"], "pytest"),
        ("FOO=1 BAR=2 /usr/local/bin/python3 x.py", "python3"),
        ("env -u X PYTHONPATH=. pytest", "pytest"),
        ("source .venv/bin/activate && pytest", "pytest"),
        ("timeout 30 npm test", "npm test"),
        ("/Users/someone/proj/scripts/run.sh --x", "run.sh"),
        ("(cd sub && make -C build all)", "make all"),
        ("if [ -f a ]; then rm a; fi", "rm"),
        ("$HOME/bin/tool", None),
        ('echo "unbalanced', "echo"),
        ("cd /only/a/dir", None),
        ("", None),
        (None, None),
    ],
)
def test_command_head_is_the_effective_program(command, head):
    assert command_head(command) == head
    if head:
        assert "/" not in head and "=" not in head


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("claude-sonnet-4-5-20250929", ("claude-sonnet-4-5", "sonnet")),
        ("us.anthropic.claude-haiku-4-5-20251001-v1:0", ("claude-haiku-4-5", "haiku")),
        ("anthropic/claude-opus-4.6", ("claude-opus-4-6", "opus")),
        ("claude-opus-4-6[1m]", ("claude-opus-4-6", "opus")),
        ("gpt-5.3-codex", ("gpt-5.3-codex", "gpt")),
        ("<synthetic>", None),
        ("test-model", None),
    ],
)
def test_canonical_model(raw, expected):
    assert canonical_model(raw) == expected


def test_cost_needs_a_price_and_complete_buckets():
    full = {
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    assert cost_usd("claude-sonnet-4-5", full) == 3.0
    assert cost_usd("claude-sonnet-4-5", {**full, "cache_write_tokens": None}) is None
    assert cost_usd("gpt-5.3-codex", full) is None


def test_codex_output_status_reads_only_the_harness_header():
    assert output_status(
        "Chunk ID: ab12\nWall time: 0.1 seconds\nProcess exited with code 2\n"
    ) == {"status": "failed", "exit_code": 2, "status_scope": "direct_command"}
    assert output_status("Exit code: 0\nWall time: 1 seconds\nOutput:\n")["status"] == "completed"
    assert output_status("Script completed\nWall time 1 seconds")["status_scope"] == "outer_wrapper"
    assert output_status("Script running with cell ID 3")["status"] == "unknown"
    # A body line that merely looks like a header does not count.
    assert output_status("hello\nProcess exited with code 0\n")["status"] == "unknown"


def claude_rows():
    common = {"sessionId": "s", "cwd": "/missing/demo", "version": "synthetic-v1"}
    usage = {
        "input_tokens": 1000,
        "output_tokens": 100,
        "cache_read_input_tokens": 2000,
        "cache_creation_input_tokens": 0,
    }
    calls = [
        ("e1", "Edit", {"file_path": "a.py"}),
        ("e2", "Edit", {"file_path": "b.py"}),
        ("e3", "Edit", {"file_path": "c.py"}),
        ("b1", "Bash", {"command": "cd /missing/demo && FOO=1 uv run pytest -q"}),
    ]
    rows = [
        {
            **common,
            "type": "user",
            "uuid": "u",
            "timestamp": "2026-10-02T02:00:00Z",
            "message": {"role": "user", "content": "task"},
        }
    ]
    for index, (call_id, name, args) in enumerate(calls):
        rows.append(
            {
                **common,
                "type": "assistant",
                "uuid": "a" + call_id,
                "timestamp": f"2026-10-02T02:0{index + 1}:00Z",
                "message": {
                    "id": "r" + call_id,
                    "model": "claude-sonnet-4-5-20250929",
                    "content": [{"type": "tool_use", "id": call_id, "name": name, "input": args}],
                    "usage": usage,
                },
            }
        )
        block = {"type": "tool_result", "tool_use_id": call_id, "content": "ok"}
        if call_id == "e3":
            block["is_error"] = True
        rows.append(
            {
                **common,
                "type": "user",
                "uuid": "r" + call_id,
                "timestamp": f"2026-10-02T02:0{index + 1}:30Z",
                "message": {"role": "user", "content": [block]},
            }
        )
    return rows


def test_claude_status_command_head_model_and_cost(tmp_path):
    home = tmp_path / "data"
    with Store(home) as store:
        capture(store, "claude_code", tmp_path, claude_rows())
        store.rebuild()
        tools = {r["native_call_id"]: r for r in store.db.execute("SELECT * FROM tool_call")}
        assert [tools[k]["status"] for k in ("e1", "e2", "e3")] == [
            "completed",
            "completed",
            "failed",
        ]
        assert tools["b1"]["command_head"] == "uv run"
        heads = store.db.execute(
            "SELECT value FROM session_feature WHERE feature='command_head'"
        ).fetchall()
        assert [r[0] for r in heads] == ["uv run"]
        calls = store.db.execute("SELECT * FROM model_call").fetchall()
        assert len(calls) == 4
        for call in calls:
            assert call["model_id"] == "claude-sonnet-4-5"
            assert call["model_resolution"] == "resolved"
            assert call["cost_source"] == "price_table"
            assert call["cost_usd"] == pytest.approx((1000 * 3 + 100 * 15 + 2000 * 0.3) / 1e6)
        alias = store.db.execute("SELECT * FROM model_alias").fetchone()
        assert (alias["model_raw"], alias["model_id"], alias["family"]) == (
            "claude-sonnet-4-5-20250929",
            "claude-sonnet-4-5",
            "sonnet",
        )
    bundle = read_analysis(home, AnalysisScope("UTC"))
    for row in bundle["model_calls"]:
        assert row["usage_scope"] == "call" and row["measurement"] == "delta"
        assert row["boundary_reliable"] is True
        assert row["price_table_version"] == PRICE_TABLE_VERSION
    assert read_analysis(home, AnalysisScope("UTC", model_ids=("claude-sonnet-4-5",)))[
        "model_calls"
    ]


def test_user_alias_wins_and_unknown_models_stay_unpriced(tmp_path):
    rows = claude_rows()
    for row in rows:
        if row["type"] == "assistant":
            row["message"]["model"] = "house-model"
    with Store(tmp_path / "data") as store:
        capture(store, "claude_code", tmp_path, rows)
        store.rebuild()
        call = store.db.execute("SELECT * FROM model_call").fetchone()
        assert call["model_resolution"] == "unmapped"
        assert call["cost_usd"] is None and call["cost_source"] is None
        assert not store.db.execute("SELECT 1 FROM model_alias").fetchone()
    with Store(tmp_path / "data2") as store:
        capture(store, "claude_code", tmp_path, claude_rows())
        store.db.execute(
            "INSERT INTO model_alias VALUES('','claude-sonnet-4-5-20250929','mine',NULL)"
        )
        store.db.commit()
        store.rebuild()
        ids = {r[0] for r in store.db.execute("SELECT model_id FROM model_call")}
        assert ids == {"mine"}


def test_codex_exit_codes_shell_heads_and_tool_only_session_span(tmp_path):
    def item(ts, payload):
        return {"timestamp": ts, "type": "response_item", "payload": payload}

    rows = [
        {"timestamp": "2026-10-02T03:00:00Z", "type": "session_meta", "payload": {"id": "s"}},
        item(
            "2026-10-02T03:00:01Z",
            {
                "type": "function_call",
                "name": "exec_command",
                "call_id": "c1",
                "arguments": json.dumps({"cmd": "/bin/zsh -lc 'cd /missing && pytest -q'"}),
            },
        ),
        item(
            "2026-10-02T03:00:05Z",
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": "Chunk ID: ab\nWall time: 4 seconds\nProcess exited with code 1\nOutput:\nF",
            },
        ),
        item(
            "2026-10-02T03:00:06Z",
            {
                "type": "web_search_call",
                "id": "w1",
                "status": "completed",
                "action": {"type": "search", "query": "q"},
            },
        ),
    ]
    with Store(tmp_path / "data") as store:
        capture(store, "codex", tmp_path, rows)
        store.rebuild()
        tools = {r["native_call_id"]: r for r in store.db.execute("SELECT * FROM tool_call")}
        assert tools["c1"]["status"] == "failed" and tools["c1"]["exit_code"] == 1
        assert tools["c1"]["command_head"] == "pytest"
        assert tools["w1"]["status"] == "completed"
        session = store.db.execute("SELECT * FROM session").fetchone()
        assert session["started_at"] is not None and session["ended_at"] >= session["started_at"]


def test_session_without_action_events_spans_its_timestamped_events(tmp_path):
    rows = [
        {"timestamp": "2026-10-02T03:00:00Z", "type": "session_meta", "payload": {"id": "s"}},
        {
            "timestamp": "2026-10-02T03:00:02Z",
            "type": "response_item",
            "payload": {"type": "reasoning", "summary": [{"type": "summary_text", "text": "x"}]},
        },
        {
            "timestamp": "2026-10-02T03:00:09Z",
            "type": "response_item",
            "payload": {"type": "reasoning", "summary": [{"type": "summary_text", "text": "y"}]},
        },
    ]
    with Store(tmp_path / "data") as store:
        capture(store, "codex", tmp_path, rows)
        store.rebuild()
        session = store.db.execute("SELECT * FROM session").fetchone()
        assert session["started_at"] is not None
        assert session["ended_at"] - session["started_at"] >= 7000

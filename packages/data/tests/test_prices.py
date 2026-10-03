"""prices.json consistency, TTL-bucket cost arithmetic and the v14 cost/failure/file columns.

Every expected cost below is hand-computed from the provider's list price
(USD per MTok) times the token counts, not read back from the implementation.
"""

import json

import pytest
from test_reduce_quality import capture, claude_rows

from orbit_data.models import PRICE_SOURCES, PRICE_TABLE_VERSION, PRICES, cost_usd
from orbit_data.reduce import _failure_kind
from orbit_data.store import Store


def test_every_price_row_is_sourced_and_ordered():
    assert PRICE_TABLE_VERSION.startswith("list-")
    for source in PRICE_SOURCES.values():
        assert source["url"].startswith("https://") and len(source["retrieved"]) == 10
    families = {row["source"] for row in PRICES.values()}
    assert {"anthropic", "openai", "google", "moonshot", "zai"} <= families
    for model, row in PRICES.items():
        assert row["source"] in PRICE_SOURCES, model
        assert 0 < row["cache_read"] < row["input"] <= row["output"], model
        if row.get("cache_write_billed", True):
            # Anthropic prompt caching: 5m write = 1.25x input, 1h write = 2x input.
            assert row["cache_write_5m"] == pytest.approx(row["input"] * 1.25), model
            assert row["cache_write_1h"] == pytest.approx(row["input"] * 2), model
        else:
            assert row["cache_write_5m"] is None and row["cache_write_1h"] is None, model


OPUS_55 = {"input_tokens": 1000, "output_tokens": 500, "cache_read_tokens": 10_000}


@pytest.mark.parametrize(
    ("model", "tokens", "one_hour", "expected"),
    [
        # 1000*4 + 500*20 + 10000*0.20 + 2000*5.0 (5m) + 1000*8.0 (1h) = 34000 -> $0.034
        ("claude-opus-5-5", {**OPUS_55, "cache_write_tokens": 3000}, 1000, 0.034),
        # Same call, every write on the 5m TTL: 16000 + 3000*5.0 = 31000
        ("claude-opus-5-5", {**OPUS_55, "cache_write_tokens": 3000}, 0, 0.031),
        # No writes: the split is irrelevant. 4000 + 10000 + 2000 = 16000
        ("claude-opus-5-5", {**OPUS_55, "cache_write_tokens": 0}, None, 0.016),
        # Writes without a reported TTL split: unknown, never the cheaper 5m guess.
        ("claude-opus-5-5", {**OPUS_55, "cache_write_tokens": 3000}, None, None),
        # 1h part larger than the total is inconsistent evidence.
        ("claude-opus-5-5", {**OPUS_55, "cache_write_tokens": 3000}, 4000, None),
        # OpenAI bills no cache writes: 100000*1.75 + 50000*0.175 + 2000*14 = 211750
        (
            "gpt-5.3-codex",
            {
                "input_tokens": 100_000,
                "output_tokens": 2000,
                "cache_read_tokens": 50_000,
                "cache_write_tokens": None,
            },
            None,
            0.21175,
        ),
        # Above the 272K short-context limit the table has no price.
        (
            "gpt-5.4",
            {
                "input_tokens": 300_000,
                "output_tokens": 1,
                "cache_read_tokens": 0,
                "cache_write_tokens": None,
            },
            None,
            None,
        ),
        # Gemini 2.5 Flash: 1e6*0.30 + 1e6*2.50 + 1e6*0.03 = 2.83
        (
            "gemini-2.5-flash",
            {
                "input_tokens": 1_000_000,
                "output_tokens": 1_000_000,
                "cache_read_tokens": 1_000_000,
                "cache_write_tokens": 0,
            },
            None,
            2.83,
        ),
        # Kimi k2.6: 1e6*0.95 + 1e6*4.00 + 1e6*0.16 = 5.11
        (
            "kimi-k2.6",
            {
                "input_tokens": 1_000_000,
                "output_tokens": 1_000_000,
                "cache_read_tokens": 1_000_000,
                "cache_write_tokens": None,
            },
            None,
            5.11,
        ),
        # A missing input bucket is never zero.
        (
            "glm-5.1",
            {
                "input_tokens": None,
                "output_tokens": 1,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            },
            None,
            None,
        ),
        # Unverified provider (no row): NULL.
        ("deepseek-chat", {**OPUS_55, "cache_write_tokens": 0}, None, None),
    ],
)
def test_cost_by_bucket(model, tokens, one_hour, expected):
    value = cost_usd(model, tokens, cache_write_1h=one_hour)
    if expected is None:
        assert value is None
    else:
        assert value == pytest.approx(expected)


def test_reduce_reads_ttl_split_and_service_tier(tmp_path):
    rows = claude_rows()
    for row in rows:
        if row["type"] == "assistant":
            row["message"]["model"] = "claude-opus-5-5"
            row["message"]["usage"] = {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_input_tokens": 10_000,
                "cache_creation_input_tokens": 3000,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 2000,
                    "ephemeral_1h_input_tokens": 1000,
                },
                "service_tier": "standard",
            }
    # Last call reports only the 5m part: the 1h part is the remainder (3000 - 2500).
    rows[-2]["message"]["usage"]["cache_creation"] = {"ephemeral_5m_input_tokens": 2500}
    with Store(tmp_path / "data") as store:
        capture(store, "claude_code", tmp_path, rows)
        store.rebuild()
        calls = store.db.execute(
            "SELECT cache_write_1h_tokens,service_tier,cost_usd,cost_source FROM model_call "
            "ORDER BY ts"
        ).fetchall()
        assert [c["cache_write_1h_tokens"] for c in calls] == [1000, 1000, 1000, 500]
        assert {c["service_tier"] for c in calls} == {"standard"}
        assert [c["cost_usd"] for c in calls[:3]] == [pytest.approx(0.034)] * 3
        # 16000 + 2500*5.0 + 500*8.0 = 32500
        assert calls[3]["cost_usd"] == pytest.approx(0.0325)
        assert {c["cost_source"] for c in calls} == {"price_table"}
        tools = {
            r["native_call_id"]: r
            for r in store.db.execute("SELECT native_call_id,status,failure_kind FROM tool_call")
        }
        # e3 failed with is_error only: no evidence of why, so no kind.
        assert tools["e3"]["status"] == "failed" and tools["e3"]["failure_kind"] is None
        assert tools["e1"]["failure_kind"] is None
        files = store.db.execute(
            "SELECT path,op,quality FROM tool_call_file ORDER BY path"
        ).fetchall()
        assert [tuple(r) for r in files] == [
            ("a.py", "unknown", "missing"),
            ("b.py", "unknown", "missing"),
            ("c.py", "unknown", "missing"),
        ]
        assert json.loads(
            store.db.execute("SELECT files FROM tool_call WHERE native_call_id='e1'").fetchone()[0]
        ) == ["a.py"]


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"status": "completed", "exit_code": 0}, None),
        ({"status": "failed", "approval": "denied"}, "permission_denied"),
        ({"status": "failed", "approval": "abort"}, "permission_denied"),
        ({"status": "interrupted"}, "interrupted"),
        ({"status": "failed", "exit_code": 2}, "nonzero_exit"),
        # A nonzero exit is a failure even when the harness status says completed.
        ({"status": "completed", "exit_code": 1}, "nonzero_exit"),
        ({"status": "failed", "error_class": "rate_limit"}, "harness_error"),
        ({"status": "failed"}, None),
        ({"status": "unknown", "exit_code": True}, None),
    ],
)
def test_failure_kind_needs_evidence(values, expected):
    assert _failure_kind(values) == expected

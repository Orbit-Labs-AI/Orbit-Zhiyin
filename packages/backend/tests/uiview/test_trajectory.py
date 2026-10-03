import json
import time
from datetime import UTC

import pytest

from orbit_backend.uiview import trajectory

from .l1_builder import *  # noqa: F403 - pytest fixtures
from .l1_builder import MIN, T0, codex_unknown, handwritten_cc

TOOL_LANES = {"read", "edit", "bash", "web"}


def detail(l1, uid="cc-fix", **kw):
    return trajectory.build_detail(l1.db, uid, tz=UTC, **kw)


def count(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def test_lane_counts_match_l1(l1):
    uid = handwritten_cc(l1)
    body = detail(l1)
    events = body["trajectory"]["events"]
    tools = [e for e in events if e["lane"] in TOOL_LANES]
    assert len(tools) == count(l1.db, "SELECT COUNT(*) FROM tool_call WHERE session_uid=?", uid)
    assert sum(e["err"] for e in tools) == count(
        l1.db, "SELECT COUNT(*) FROM tool_call WHERE session_uid=? AND status='failed'", uid)
    users = [e for e in events if e["lane"] == "user"]
    assert len(users) == body["stats7"]["msgs"] == 3
    assert sum(e["corr"] for e in users) == body["stats7"]["corr"] == 2
    assert [e["lane"] for e in events if e["lane"] == "agent"] == ["agent", "agent"]
    assert body["trajectory"]["lanes"] == ["user", "agent", "sub", "read", "edit", "bash", "web"]
    assert {e["lane"] for e in tools} == {"read", "edit", "bash"}
    failed = [e for e in tools if e["err"]]
    assert {e["cmd"] for e in failed} == {"wrangler deploy"}
    assert failed[0]["res"] == "exit 1 · auth_error"
    assert body["trajectory"]["steps_axis"] == [e["seq"] for e in events]
    assert all(e["event_uid"] for e in events)


def test_phases_cover_zero_to_T_without_overlap(l1):
    handwritten_cc(l1)
    tr = detail(l1)["trajectory"]
    phases = tr["phases"]
    assert phases[0]["t"] == 0 and phases[-1]["t2"] == tr["T"] == 12.0
    for a, b in zip(phases, phases[1:], strict=False):
        assert a["t2"] == b["t"] and a["t"] < a["t2"]
    assert all(p["inferred"] is True for p in phases)
    assert phases[-1]["phase"] == "verify"


def test_header_stats_and_resume(l1):
    handwritten_cc(l1)
    body = detail(l1)
    head, stats = body["header"], body["stats7"]
    assert head["agent_name"] == "Claude Code" and head["model"] == "claude-opus-4-5"
    assert head["effort"] == "high" and head["cwd"] == "/w/p1" and head["started_at"] == T0
    # 2 of 3 human messages are corrections: same "part" as the list row (uiview.outcome).
    assert head["out"] == "part" and head["out_basis"] == "estimate"
    assert head["resume"]["shell"] == "cd /w/p1 && claude --resume native-cc-fix"
    # The data-layer template documents `claude --resume <id>` (orbit_data.resume).
    assert head["resume"]["verified"] is True
    assert stats["tools"] == 8 and stats["errors"] == 3 and stats["steps"] == 10
    assert stats["tok"] == 50_000 + 10_000 + 800 + 150_000 + 900
    assert body["trajectory"]["start_min"] == 8 * 60 + 53


def test_ctx_estimate_and_null_without_window(l1):
    handwritten_cc(l1)
    tr = detail(l1)["trajectory"]
    assert tr["ctx"] == [[0.6, 30.0], [10.5, 75.0]]  # (input + cache) / 200k window
    assert detail(l1)["stats7"]["ctx_peak"] == 75.0
    assert detail(l1)["stats7"]["ctx_basis"] == "estimate"
    assert [m["kind"] for m in tr["marks"]] == ["compaction"] and tr["marks"][0]["t"] == 8.0
    # Unknown model: no window table hit -> ctx null, never 0.
    l1.session("mystery", started=T0 + 3600_000)
    l1.user("mystery", T0 + 3600_000, "hello")
    l1.model("mystery", T0 + 3600_000 + MIN, model="mystery-model-1")
    body = detail(l1, "mystery")
    assert body["trajectory"]["ctx"] is None
    assert body["stats7"]["ctx_peak"] is None and body["stats7"]["ctx_basis"] is None


def test_unknown_values_are_null_not_zero(l1):
    codex_unknown(l1)
    body = detail(l1, "cx-1")
    stats = body["stats7"]
    assert stats["errors"] is None and stats["tok"] is None and stats["ctx_peak"] is None
    assert body["trajectory"]["ctx"] is None
    assert body["header"]["out"] is None
    assert body["header"]["title_source"] == "first_message"


def test_privacy_no_home_path_in_text(l1):
    handwritten_cc(l1)
    body = detail(l1)
    text = json.dumps(body, ensure_ascii=False)
    assert "/Users/" not in text and "alice" not in text
    users = [e for e in body["trajectory"]["events"] if e["lane"] == "user"]
    assert users[-1]["txt"].endswith("~/secret-proj/x.txt")
    assert all(len(u["txt"]) <= 120 for u in users)
    assert all(e["txt"] is None for e in body["trajectory"]["events"] if e["lane"] != "user")


def test_subagent_span_lane(l1):
    handwritten_cc(l1)
    l1.session("cc-fix-sub", kind="subagent", root="cc-fix", parent="cc-fix",
               started=T0 + 2 * MIN, title="探索仓库")
    l1.reply("cc-fix-sub", T0 + 2 * MIN)
    l1.call("cc-fix-sub", T0 + 3 * MIN, name="Read", kind="file.read")
    l1.reply("cc-fix-sub", T0 + 4 * MIN, final=True)
    body = detail(l1)
    subs = [e for e in body["trajectory"]["events"] if e["lane"] == "sub"]
    assert len(subs) == 1 and subs[0]["t"] == 2.0 and subs[0]["w"] == 2.0
    assert subs[0]["child_tools"] == 1
    assert body["stats7"]["tools"] == 9  # whole session tree, like the list row


def test_lite_nodes_and_insight(client, l1):
    handwritten_cc(l1)
    body = client.get("/v1/uiview/sessions/cc-fix").json()
    nodes = body["lite_nodes"]
    assert 1 <= len(nodes) <= 4
    assert [n["rule"] for n in nodes] == ["goal", "lexical_correction", "failure_streak",
                                          "validation_command"]
    assert "_facts" not in body
    assert body["insight"]["actions"][0]["rec_id"] == "retry-breaker"
    assert body["insight"]["actions"][0]["problem_type"] == "tool_env_failure"
    assert body["insight"]["basis"] == "l0_template"
    assert client.get("/v1/uiview/sessions/nope").status_code == 404


@pytest.mark.serial
def test_detail_5000_events_under_200ms(l1):
    uid = "big"
    l1.session(uid, started=T0)
    for i in range(1250):
        at = T0 + i * 2000
        l1.user(uid, at, f"第 {i} 步 不对，请重新来" if i % 50 == 0 else f"第 {i} 步")
        l1.reply(uid, at + 500)
        l1.call(uid, at + 900, head="pytest -q", status="failed" if i % 7 == 0 else "success")
    assert count(l1.db, "SELECT COUNT(*) FROM event WHERE session_uid=?", uid) == 3750
    l1.db.execute("ANALYZE")
    for i in range(1250):  # pad to 5000 events with harness noise
        l1.event(uid, T0 + i * 2000 + 1500, "turn.started", "harness")
    detail(l1, uid)  # warm caches
    started = time.perf_counter()
    body = detail(l1, uid)
    elapsed = time.perf_counter() - started
    assert len(body["trajectory"]["moments"]) <= 6
    assert elapsed < 0.2, f"detail took {elapsed:.3f}s"


def test_stats_corr_matches_header_corr(l1):
    """UT-06: one corr per page; facts (A1) win in both the header and stats7."""
    handwritten_cc(l1)
    plain = detail(l1)
    assert plain["stats7"]["corr"] == plain["header"]["corr"] == 2  # 2 lexical corrections
    with_facts = trajectory.build_detail(l1.db, "cc-fix", facts={"corr": 4})
    assert with_facts["header"]["corr"] == with_facts["stats7"]["corr"] == 4


def test_active_time_is_one_implementation():
    from orbit_backend.uiview import metrics, sessions

    assert trajectory._active_ms([0, 60_000, 60_000 + 10 * 60_000]) == 60_000 + 5 * 60_000
    assert metrics.active_ms([]) is None and metrics.active_ms([5]) == 0
    assert sessions.ACTIVE_GAP_MS == metrics.IDLE_CAP_MS


def test_repeated_tool_labels_are_redacted_once_per_request(l1, monkeypatch):
    from collections import Counter

    l1.session("repeated", started=T0)
    l1.user("repeated", T0, "检查结果")
    for i in range(20):
        l1.call("repeated", T0 + i * 1000, head="pytest -q", status="success")
    expected = detail(l1, "repeated", now_ms=T0 + MIN)
    original = trajectory.scrub
    calls = Counter()

    def counted(text, limit=120):
        calls[text, limit] += 1
        return original(text, limit)

    monkeypatch.setattr(trajectory, "scrub", counted)
    assert detail(l1, "repeated", now_ms=T0 + MIN) == expected
    assert calls["pytest -q", 80] == 1
    assert detail(l1, "repeated", now_ms=T0 + MIN) == expected
    assert calls["pytest -q", 80] == 2  # no process-wide caching of redacted labels

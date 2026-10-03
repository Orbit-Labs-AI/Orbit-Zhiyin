"""Default packs stay within their task budget (B11 replay_calls, B12 facet.session without uids)."""

from __future__ import annotations

import pytest
from ai_analysis_fakectx import DAY, NOW

from orbit_backend.ai import pack as P
from orbit_backend.ai.redact import est_tokens

SCOPE = {"start_ms": NOW - 30 * DAY, "end_ms": NOW}


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(P, "now_ms", lambda: NOW)


def _calls(n, fail_at=()):
    return [{"tool_name": "Bash", "kind": "shell", "command_head": f"cmd{i % 7}",
             "status": "failed" if i in fail_at else "success", "error_class": "exit" if i in fail_at else None}
            for i in range(n)]


def test_clip_replay_keeps_failures_and_fits_budget():
    sessions = [{"session_uid": f"s{k}", "title": "t", "evidence": k < 3, "calls": _calls(200, (100, 101))}
                for k in range(8)]
    out = P.clip_replay(sessions)
    assert est_tokens(out) <= P.REPLAY_TOKENS
    for s in out:
        assert s["omitted_calls"] == 200 - len(s["calls"])
        assert [c for c in s["calls"] if c["status"] == "failed"]  # the failure run survives
    small = [{"session_uid": "s", "evidence": True, "calls": _calls(5)}]
    assert P.clip_replay(small) == small


def test_hook_pack_replay_calls_within_budget(tdb, appdb, orbit_home):
    fail = [("Bash", "shell", "pytest", "failed", "exit_nonzero")] * 2
    for k in range(8):
        tdb.session(f"s{k}", start=NOW - (k + 1) * DAY, humans=["跑测试", "不对，又失败了"],
                    tools=[("Bash", "shell", f"make step{i}") for i in range(198)] + fail)
    tdb.commit()
    task = {"task_id": "generate.hook", "prompt_version": "t@1",
            "pack_items": [("goal", True), ("replay_calls", True)]}
    pack = P.build(task, reads=tdb.reads, appdb=appdb, home=orbit_home, scope=SCOPE, goal="失败两次就停",
                   params={"session_uids": ["s0", "s1", "s2"]})
    replay = pack["content"]["replay_calls"]
    assert replay and est_tokens(replay) <= P.REPLAY_TOKENS
    assert all(s.get("omitted_calls") for s in replay)


def test_facet_without_uids_respects_input_budget(tdb, appdb, orbit_home):
    for k in range(30):
        tdb.session(f"f{k}", start=NOW - (k + 1) * DAY, minutes=30,
                    humans=[f"任务{k} " + "详细说明需求和背景，" * 40, "不对，重来", "继续推进"],
                    replies=["好的，我来处理。" * 30] * 3)
    tdb.commit()
    task = {"task_id": "facet.session", "prompt_version": "facet@t", "input_budget": 9000,
            "pack_items": [("items", True)]}
    pack = P.build(task, reads=tdb.reads, appdb=appdb, home=orbit_home, scope=SCOPE)
    item = pack["items"][0]
    assert 0 < len(pack["content"]["items"]) < 30
    assert pack["total_tokens"] <= 9000
    assert item["queued"] == 30 - len(pack["content"]["items"]) and "排队" in item["desc"]
    explicit = P.build(task, reads=tdb.reads, appdb=appdb, home=orbit_home, scope=SCOPE,
                       params={"session_uids": ["f1"]})
    assert list(explicit["content"]["items"]) == ["f1"] and "queued" not in explicit["items"][0]

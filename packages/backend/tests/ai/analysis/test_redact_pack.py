"""AI-08 context pack + EV-14 second redaction pass."""

from __future__ import annotations

import json
import time

import pytest
from ai_analysis_fakectx import DAY, NOW

from tandem_backend.ai import pack as P
from tandem_backend.ai.redact import est_tokens, redact2
from tandem_backend.ai.tasks_analysis import TASKS

SECRETS = ["sk-abcdefghijklmnop1234", "eyJhbGciOiJIUzI1NiJ9.payload", "alex.smith@example.com",
           "/Users/alex/work", "192.168.1.20", "build.internal"]
SCOPE = {"start_ms": NOW - 30 * DAY, "end_ms": NOW}
NARRATE = TASKS["narrate.overview"]


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(P, "now_ms", lambda: NOW)


def task(**over):
    return {"task_id": "test.task", "prompt_version": "t@1", **over}


def test_redact2_hides_identity_and_counts(user_home):
    text, hits = redact2("key sk-abcdefghijklmnop1234 mail alex.smith@example.com at /Users/alex/x on "
                         "192.168.1.20 and db.internal by alex; Authorization: Bearer abcdefghijklmnopqrstu")
    for raw in ("sk-abcdefghijklmnop1234", "alex.smith@example.com", "/Users/alex", "192.168.1.20",
                "db.internal", "abcdefghijklmnopqrstu"):
        assert raw not in text
    assert "alex" not in text
    assert "[email]" in text and "~/x" in text and "[host]" in text and "[user]" in text
    assert hits >= 7
    assert redact2(text) == (text, 0)


def test_est_tokens_counts_cjk_per_char():
    assert est_tokens("纠偏率") == 3
    assert est_tokens("abcdefgh") == 2
    assert est_tokens("中abcd") == 2


def test_privacy_fixture_never_leaks(tdb, appdb, tandem_home):
    """EV-14: injected secrets/identity appear nowhere in the pack JSON."""
    message = ("不对，用 sk-abcdefghijklmnop1234 和 Bearer eyJhbGciOiJIUzI1NiJ9.payload 调用，"
               "联系 alex.smith@example.com，路径 /Users/alex/work，主机 192.168.1.20 / build.internal，我是 alex")
    tdb.session("s1", title="fix /Users/alex/work build", humans=[message, "再试 again 不对"],
                tools=[("Bash", "shell", "pytest", "failed", "exit_nonzero"),
                       ("Bash", "shell", "pytest", "failed", "exit_nonzero")])
    tdb.commit()
    t = task(pack_items=[("goal", True), ("sessions", True), ("evidence", True), ("friction", True),
                         ("tool_evidence", True), ("items", True)])
    pack = P.build(t, reads=tdb.reads, appdb=appdb, home=tandem_home, scope=SCOPE, goal="调用 不对",
                   goal_source="candidate",
                   params={"candidate": {"evidence_session_uids": ["s1"], "top_signal_event_uids": ["s1-h0"]}})
    blob = json.dumps(pack, ensure_ascii=False)
    for raw in SECRETS + ["alex"]:
        assert raw not in blob, raw
    assert pack["redaction_hits"] >= 7
    assert pack["content"]["evidence"][0]["event_uid"] == "s1-h0"


def test_digest_stable_and_sensitive(tdb, appdb, tandem_home):
    tdb.session("s1", humans=["hello world", "不对 again"])
    tdb.commit()
    kw = dict(reads=tdb.reads, appdb=appdb, home=tandem_home, scope=SCOPE)
    a = P.build(NARRATE, goal="g", **kw)
    b = P.build(NARRATE, goal="g", **kw)
    assert a["preview_digest"] == b["preview_digest"] and a["preview_digest"].startswith("sha256:")
    assert P.build(NARRATE, goal="h", **kw)["preview_digest"] != a["preview_digest"]
    c = P.build(NARRATE, goal="g", selection={"items": {"sessions": True}}, **kw)
    assert c["preview_digest"] != a["preview_digest"]
    assert "sessions" in c["content"] and "sessions" not in a["content"]


def test_tokens_sum_and_raw_never_enabled(tdb, appdb, tandem_home):
    tdb.session("s1", humans=["one", "two"], tools=[("Read", "read"), ("Edit", "edit"), ("Read", "read")])
    tdb.commit()
    t = task(pack_items=[("metrics", True), ("transitions", True), ("sessions", False), ("raw", True)])
    pack = P.build(t, reads=tdb.reads, appdb=appdb, home=tandem_home, scope=SCOPE,
                   selection={"items": {"raw": True}})
    assert sum(i["tokens"] for i in pack["items"] if i["enabled"]) == pack["total_tokens"]
    raw = next(i for i in pack["items"] if i["key"] == "raw")
    assert raw["enabled"] is False and "raw" not in pack["content"]
    sessions = next(i for i in pack["items"] if i["key"] == "sessions")
    assert sessions["tokens"] > 0 and not sessions["enabled"]
    assert all(len(i["preview"]) <= 8 for i in pack["items"])
    assert pack["content"]["transitions"][0]["probability"] <= 1
    assert "tool_calls" in pack["refs"]["metric"]
    assert 3.0 in pack["numbers"]


def test_manual_fts_returns_human_messages_only(tdb, appdb, tandem_home):
    for i in range(8):
        tdb.session(f"s{i}", humans=[f"部署 失败 第{i}次", "ok"], replies=["部署 失败 已修复"])
    tdb.commit()
    pack = P.build(task(pack_items=[("evidence", True)]), reads=tdb.reads, appdb=appdb, home=tandem_home,
                   scope=SCOPE, goal="部署失败")
    ev = pack["content"]["evidence"]
    assert 0 < len(ev) <= 5
    assert all(e["kind"] == "human" and "-h" in e["event_uid"] for e in ev)
    none = P.build(task(pack_items=[("evidence", True)]), reads=tdb.reads, appdb=appdb, home=tandem_home,
                   scope=SCOPE, goal="完全无关的词语")
    assert none["content"]["evidence"] == []


def test_excludes_tandem_sessions(tdb, appdb, tandem_home):
    tdb.session("real", humans=["a", "b"])
    tdb.session("bycwd", humans=["a", "b"], cwd=str(tandem_home / "agent-cwd"))
    tdb.session("bymarker", humans=["[tandem-analysis v1 task=x] prompt", "b"])
    tdb.commit()
    pack = P.build(task(pack_items=[("sessions", True), ("metrics", True)]), reads=tdb.reads, appdb=appdb,
                   home=tandem_home, scope=SCOPE)
    assert [s["session_uid"] for s in pack["content"]["sessions"]] == ["real"]
    assert pack["content"]["metrics"]["sessions"] == 1


def test_existing_rules_only_reads_user_home(tdb, appdb, tandem_home, user_home, tmp_path):
    (user_home / ".claude").mkdir()
    (user_home / ".claude" / "CLAUDE.md").write_text("# 部署\n\n部署前先跑 pytest 再推送。\n\n# 其他\n\n写中文提交信息。\n")
    outside = tmp_path / "outside.md"
    outside.write_text("部署 秘密 规则 pytest\n")
    proj = user_home / "proj"
    proj.mkdir()
    (proj / "AGENTS.md").write_text("部署 时 不要 强推。\n")
    tdb.inventory([("rule", "outside", str(outside)), ("rule", "proj", str(proj / "AGENTS.md"))])
    tdb.commit()
    pack = P.build(task(pack_items=[("existing_rules", True)]), reads=tdb.reads, appdb=appdb, home=tandem_home,
                   scope=SCOPE, goal="部署 pytest")
    rules = pack["content"]["existing_rules"]
    assert rules and all(r["path_label"].startswith("~/") for r in rules)
    assert not any("秘密" in r["text"] for r in rules)
    assert {r["path_label"] for r in rules} <= {"~/.claude/CLAUDE.md", "~/proj/AGENTS.md"}
    assert all(len(r["anchor_hash"]) == 16 for r in rules)


def test_missing_db_degrades(appdb, tandem_home, tmp_path, user_home):
    def reads():
        raise RuntimeError("no projection")
    pack = P.build(NARRATE, reads=reads, appdb=appdb, home=tandem_home, goal="x")
    metrics = next(i for i in pack["items"] if i["key"] == "metrics")
    assert "不可用" in metrics["desc"] and pack["content"]["metrics"] == {}


def test_slots_are_redacted_and_counted(tdb, appdb, tandem_home):
    tdb.commit()
    slots = {"candidates": [{"candidate_id": "c1", "title": "联系 alex.smith@example.com", "kind": "rule",
                             "priority": 3, "reason": "r", "evidence_counts": {}}]}
    pack = P.build(NARRATE, reads=tdb.reads, appdb=appdb, home=tandem_home, slots=slots, scope=SCOPE)
    assert "[email]" in pack["content"]["candidates"][0]["title"]
    assert pack["refs"]["candidate"] == ["c1"]


def test_facet_items_batches_and_skip(tdb, appdb, tandem_home):
    for i in range(10):
        tdb.session(f"s{i:02d}", minutes=5, humans=["做一个功能", "不对，换个方式" if i % 2 else "好的继续"],
                    replies=["好"], tools=[("Bash", "shell", "ls")] * 3)
    tdb.session("short", minutes=0, humans=["a", "b"])
    tdb.session("active", status="active", humans=["a", "b"])
    tdb.session("one", humans=["only one"])
    tdb.commit()
    facet = TASKS["facet.session"]
    pack = P.build(facet, reads=tdb.reads, appdb=appdb, home=tandem_home, scope=SCOPE)
    items = pack["content"]["items"]
    assert set(items) == {f"s{i:02d}" for i in range(10)}
    assert set(list(items)[:5]) == {"s09", "s07", "s05", "s03", "s01"}  # L0 candidates first
    assert [len(b) for b in pack["batches"]] == [8, 2]
    assert items["s01"]["tool_sequence"] == ["Bash×3"]
    assert items["s01"]["candidates"][0]["signal_id"] == "sig:s01-h1"
    appdb.put_facet("s01", facet["prompt_version"], P.content_hash(items["s01"]))
    again = P.build(facet, reads=tdb.reads, appdb=appdb, home=tandem_home, scope=SCOPE)
    assert "s01" not in again["content"]["items"] and len(again["content"]["items"]) == 9


def test_facet_payload_chunking():
    payload = {"row": {}, "tool_sequence": [], "candidates": [],
               "human_messages": [{"event_uid": f"h{i}", "text": "字" * 600} for i in range(12)],
               "assistant_replies": [{"event_uid": f"a{i}", "text": "答" * 400} for i in range(12)]}
    out = P.clip_facet(payload)
    assert out["chunked"] and out["assistant_replies"] == []
    assert est_tokens(out) <= P.FACET_SESSION_TOKENS
    assert out["human_messages"][-1]["event_uid"] == "h11"


def test_build_under_250ms_on_2k_sessions(tdb, appdb, tandem_home):
    for i in range(2000):
        tdb.session(f"s{i:04d}", project="p1" if i % 2 else "p2", start=NOW - (i % 60) * DAY // 2,
                    humans=[f"任务 {i} 部署", "不对" if i % 5 == 0 else "继续"],
                    tools=[("Read", "read"), ("Bash", "shell", "pytest", "failed" if i % 7 == 0 else "success",
                                              "exit_nonzero" if i % 7 == 0 else None), ("Edit", "edit")])
    tdb.commit()
    t = task(pack_items=[("goal", True), ("metrics", True), ("friction", True), ("sessions", True),
                         ("transitions", True), ("evidence", True), ("tool_evidence", True), ("candidates", True)])
    kw = dict(reads=tdb.reads, appdb=appdb, home=tandem_home, scope=SCOPE, goal="部署 失败")
    P.build(t, **kw)  # warm jieba / page cache
    best = min(_timed(lambda: P.build(t, **kw)) for _ in range(3))
    assert best < 0.25, best


def _timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start

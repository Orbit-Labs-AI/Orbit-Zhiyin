"""A6 情绪与语义 adapter: detectors, buckets, friction sources, topics, phrases, drivers."""

from __future__ import annotations

import json
from zoneinfo import ZoneInfo

import pytest
from a4a6_ps_fixture import DAY, MIN, T0, Tandem, ro

from tandem_backend.analytics.interaction.rules import correction_terms
from tandem_backend.appdb import AppDB
from tandem_backend.uiview import a4a6_sentiment as S

UTC = ZoneInfo("UTC")
CORRECTIONS = ["别用子代理", "不要改别的文件", "用 Cloudflare 不是 Vercel", "你改错了",
               "stop, that's wrong", "不对，重新来", "回滚刚才的改动", "撤销这个提交",
               "don't touch the tests", "use pnpm instead of npm"]
NOT_CORRECTIONS = ["比如用户说“不对”时怎么处理", "把「不对」翻译成英文", "帮我写一个 fastapi 接口",
                   "好的，继续", "例如：别用子代理这种说法要怎么识别"]


def test_corrections_union_with_detectors():
    for text in CORRECTIONS:
        hits = S.corrections(text)
        assert hits, text
        assert all(h["detector"] and h["term"] for h in hits)
    for text in NOT_CORRECTIONS:
        assert S.corrections(text) == [], text
    for text in CORRECTIONS + NOT_CORRECTIONS:
        if correction_terms(text):  # legacy hits are a subset
            assert any(h["detector"] == "interaction.correction_terms" for h in S.corrections(text))


@pytest.mark.parametrize("text,expected", [
    ("中中中中中中中abc", "zh"),      # 7/10 = 0.7
    ("中中中中中中abcd", "mixed"),    # 0.6
    ("中abcdefghi", "en"),           # 0.1
    ("中中abcdefghi", "mixed"),
    ("hello world", "en"),
    ("!!! ??? ...", "unknown"),
    ("ab", "unknown"),
    ("123456", "unknown"),
])
def test_language_thresholds(text, expected):
    assert S.language_of(text) == expected


def _m(uid, sess, ts, text):
    return {"event_uid": uid, "session_uid": sess, "seq": 0, "ts": ts, "raw": text,
            "text": S.semantic_text(text)}


def test_series_quantiles_breaks_and_hot():
    sessions = {s: {"started_at": T0} for s in ("a", "b", "c", "d")}
    humans = [
        _m("1", "a", T0, "我很开心"), _m("2", "b", T0, "我很失望"),
        _m("3", "a", T0, "不对，重新来"), _m("4", "b", T0, "你改错了"), _m("5", "a", T0, "回滚"),
        _m("6", "c", T0 + DAY, "我很开心"),
        _m("7", "d", T0 + 2 * DAY, "继续"),
        _m("8", "d", T0 + 3 * DAY, "撤销这个提交"),
    ]
    series = {b["bucket"]: b for b in S.build_series(humans, sessions, "day", UTC)}
    d0, d1, d2, d3 = (series[k] for k in sorted(series))
    assert (d0["n_sessions"], d0["explicit_n"], d0["p50"]) == (2, 2, 0.0)
    assert d0["p25"] == -0.5 and d0["p75"] == 0.5
    assert d1["n_sessions"] == 1 and d1["p50"] == 1.0 and d1["p25"] is None and d1["p75"] is None
    assert d2["p50"] is None and d2["explicit_n"] == 0  # no expression: break, no interpolation
    assert d0["corr"] == 3 and d0["corr_hot"] is True
    assert d3["corr"] == 1 and d3["corr_hot"] is False  # below the floor of 2


def test_bucket_mode_matches_frontend():
    assert S.bucket_mode(0, 31 * DAY) == "day"
    assert S.bucket_mode(0, 31 * DAY + 1) == "week"
    assert S.bucket_mode(0, 90 * DAY, "day") == "day"


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def world(home):
    t = Tandem(home)
    t.project("p1")
    # Current window [T0, T0+10d): f1 (facet), r1 (2 failures), r2 (read-only ask), q1/q2 phrases.
    t.session("f1", start=T0 + DAY)
    t.human("f1", "部署 docker 到服务器，确保测试通过", ts=T0 + DAY)
    t.human("f1", "我很失望", ts=T0 + DAY + MIN)
    t.session("r1", start=T0 + 2 * DAY)
    t.human("r1", "帮我修后端接口", ts=T0 + 2 * DAY)
    t.call("r1", head="pytest", status="failed", ts=T0 + 2 * DAY + MIN)
    t.call("r1", head="pytest", status="error", ts=T0 + 2 * DAY + 2 * MIN)
    t.session("r2", start=T0 + 3 * DAY)
    t.human("r2", "跑一下测试", ts=T0 + 3 * DAY)
    t.human("r2", "token sk-abcdefghijklmnop1234 记一下", ts=T0 + 3 * DAY + MIN)
    t.call("r2", head="git status", approval="approved", ts=T0 + 3 * DAY + 2 * MIN)
    t.session("q1", start=T0 + 4 * DAY)
    t.human("q1", "跑一下测试！", ts=T0 + 4 * DAY)
    t.human("q1", "跑一下测试", ts=T0 + 4 * DAY + MIN)
    t.human("q1", "token sk-abcdefghijklmnop1234 记一下", ts=T0 + 4 * DAY + 2 * MIN)
    t.human("q1", "只说一次的话", ts=T0 + 4 * DAY + 3 * MIN)
    t.session("q2", start=T0 + 5 * DAY)
    t.human("q2", "跑一下测试", ts=T0 + 5 * DAY)
    # Previous window [T0-10d, T0): one tool failure session.
    t.session("old", start=T0 - 5 * DAY)
    t.human("old", "修一下", ts=T0 - 5 * DAY)
    t.call("old", head="make", status="failed", ts=T0 - 5 * DAY + MIN)
    t.call("old", head="make", status="failed", ts=T0 - 5 * DAY + 2 * MIN)
    t.event("old", "context.compaction", ts=T0 - 5 * DAY + 3 * MIN, actor="system")
    yield t
    t.close()


@pytest.fixture
def appdb(home):
    db = AppDB(home / "app.db")
    yield db
    db.close()


PARAMS = {"since": T0, "until": T0 + 10 * DAY, "tz": "UTC"}


def run(world, appdb, params=PARAMS):
    conn = ro(world.path)
    try:
        return S.build_sentiment(conn, appdb, {}, params, now_ms=T0 + 10 * DAY)
    finally:
        conn.close()


def test_friction_rules_only_without_facets(world, appdb):
    body = run(world, appdb)
    rows = {r["type"]: r for r in body["friction"]}
    assert set(rows) == {"tool_env_failure", "permission_friction"}
    tef = rows["tool_env_failure"]
    assert (tef["sessions"], tef["prev"], tef["delta"]) == (1, 1, 0)
    assert tef["type_source"] == "rule" and tef["session_uids"] == ["r1"]
    assert tef["label"] == "工具 / 环境失败" and tef["typical"]
    perm = rows["permission_friction"]
    assert (perm["sessions"], perm["prev"], perm["delta"]) == (1, 0, 1)


def test_friction_prefers_facets(world, appdb):
    with appdb.write() as w:
        w.execute("INSERT INTO ai_facet VALUES ('f1','facet@1.1','1','h','m','ok',?,NULL,1)",
                  (json.dumps({"friction_types": ["wrong_approach", "excessive_changes"]}),))
        w.execute("INSERT INTO ai_facet VALUES ('r1','facet@1.1','1','h','m','ok',?,NULL,1)",
                  (json.dumps({"friction_types": ["misunderstood_request"]}),))
    rows = {r["type"]: r for r in run(world, appdb)["friction"]}
    assert rows["wrong_approach"]["type_source"] == "facet"
    assert rows["wrong_approach"]["label"] == "方向错误"
    assert rows["wrong_approach"]["avg_balance"] == -1.0
    assert rows["misunderstood_request"]["session_uids"] == ["r1"]
    # r1's rule-derived tool failure is superseded by its facet; prev window still counts one.
    assert rows["tool_env_failure"]["sessions"] == 0 and rows["tool_env_failure"]["delta"] == -1
    assert rows["permission_friction"]["type_source"] == "rule"


def test_topics_taxonomy_and_ai_override(world, appdb):
    topics = {t["id"]: t for t in run(world, appdb)["topics"]}
    assert topics["software.devops"]["label"] == "部署与运维"
    assert topics["software.devops"]["label_source"] == "taxonomy"
    assert topics["software.devops"]["avg_balance"] == -1.0
    assert topics["software.backend_api"]["session_uids"] == ["r1"]
    assert "other" in topics and topics["other"]["label"] == "其他"
    with appdb.write() as w:
        w.execute("INSERT INTO ai_job(job_id,task_id,engine,slot,request,status,result,created_at,"
                  "finished_at) VALUES ('j1','name.topics','fake','cheap','{}','ok',?,1,2)",
                  (json.dumps({"topics": [{"id": "software.devops", "label": "部署收尾"}]}),))
    body = run(world, appdb)
    topics = {t["id"]: t for t in body["topics"]}
    assert topics["software.devops"]["label"] == "部署收尾"
    assert topics["software.devops"]["label_source"] == "ai"
    assert topics["software.backend_api"]["label_source"] == "taxonomy"
    assert body["meta"]["last_job_at"] == 2


def test_phrases_sessions_redaction_and_sources(world, appdb):
    body = run(world, appdb)
    phrases = {p["text"]: p for p in body["phrases"]}
    test = phrases["跑一下测试"]
    assert test["sessions"] == 3 and test["n"] == 4 and test["category"] == "验证"
    assert 1 <= len(test["event_uids"]) <= 3
    assert all(p["sessions"] >= 2 for p in body["phrases"])
    assert not any("只说一次" in p["text"] for p in body["phrases"])
    text = json.dumps(body, ensure_ascii=False)
    assert "sk-abcdefghijklmnop1234" not in text
    assert any("[密钥已隐藏]" in p["text"] for p in body["phrases"])


def test_language_mix_and_meta(world, appdb):
    body = run(world, appdb)
    mix = body["language_mix"]
    assert mix["n"] == 10 and mix["zh"] + mix["en"] + mix["mixed"] + mix["unknown"] == 10
    meta = body["meta"]
    assert meta["mode"] == "stats" and meta["engine"] is None and meta["remote"] is True
    assert meta["experimental"] is True and meta["definition_version"] == S.DEFINITION_VERSION
    assert meta["bucket"] == "day"


def test_drivers_insufficient_and_ok(world, appdb):
    drivers = run(world, appdb)["drivers"]
    assert [d["key"] for d in drivers] == [k for k, _ in S.DRIVERS]
    assert all(d["status"] == "insufficient" and d["diff"] is None for d in drivers)
    sessions = {f"s{i}": {"started_at": 0, "end": (120 if i < 10 else 10) * MIN}
                for i in range(20)}
    balances = {f"s{i}": (-1.0 if i < 10 else 1.0) for i in range(20)}
    rows = {d["key"]: d for d in S.build_drivers(sessions, {}, [], balances, set())}
    assert rows["long_session"]["status"] == "ok" and rows["long_session"]["diff"] == -2.0
    assert rows["compaction"]["status"] == "insufficient"  # n_a = 0

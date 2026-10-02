"""Event hits on storage v8+ (contentless trigram ``event_search``) and on legacy ``event_fts``.

The v8 store is the synthetic fixture store with the event-index section of the real
``008.sql`` applied, so the table, tokenizer and triggers are the ones real stores get.
"""

import sys
from pathlib import Path

import pytest
import tandem_data
from conftest import DAY, NOW

from tandem_backend.features.search import PER_SOURCE, search
from tandem_backend.features.search_index import SearchIndex

MIGRATION = Path(tandem_data.__file__).parent / "migrations" / "008.sql"


def to_v8(world):
    sql = MIGRATION.read_text()
    world.t.executescript(sql[sql.index("DROP TRIGGER IF EXISTS event_ai;"):
                              sql.index("UPDATE schema_manifest")])
    names = {r[0] for r in world.t.execute("SELECT name FROM sqlite_master")}
    assert "event_search" in names and "event_fts" not in names


@pytest.fixture
def v8(world):
    to_v8(world)
    world.project("p1", "Tandem 前端")
    world.project("p2", "billing-api")
    world.session("s1", project="p1", title="修复登录页面的样式问题", started=NOW - DAY)
    world.session("s2", source="s-codex", project="p2", title="Refactor login flow",
                  started=NOW - 40 * DAY)
    world.message("s1", "请帮我修复登录页面的样式问题", ts=NOW - DAY)
    world.message("s1", "登录页面已经修好了，样式也对齐了", ts=NOW - DAY,
                  kind="message.assistant", actor="assistant")
    world.message("s2", "login page throws on Submit", ts=NOW - 40 * DAY)
    world.message("s2", "submit handler patched", ts=NOW - 40 * DAY, kind="tool.result",
                  actor="tool")  # not indexed by event_search
    return world


def run(world, q, **kw):
    kw.setdefault("timeout_s", 5.0)
    kw.setdefault("kinds", ["event"])
    return search(world.home, q, index=SearchIndex(world.home), data_rev=1, now_ms=NOW, **kw)


def marked(hit):
    return [hit["snippet"][s:e] for s, e in hit["marks"]]


def test_english_match_uses_trigram_substring(v8):
    out = run(v8, "submit")
    assert out["counts"] == {"event": 1} and out["complete"] and out["partial_reasons"] == {}
    hit = out["results"][0]
    assert hit["ref"] == {"page": "session", "id": "s2", "event_uid": "e3"}
    assert hit["title"] == "Refactor login flow" and hit["agent"] == "codex"
    assert marked(hit) == ["Submit"]
    assert run(v8, "ubmi")["counts"] == {"event": 1}  # substring, not word prefix


def test_chinese_three_characters_match(v8):
    out = run(v8, "登录页")
    assert out["counts"] == {"event": 2} and out["complete"]
    assert {r["id"] for r in out["results"]} == {"e1", "e2"}
    assert all(marked(r) == ["登录页"] for r in out["results"])


def test_chinese_two_characters_scan_recent_events(v8):
    out = run(v8, "样式")
    assert out["counts"] == {"event": 2} and out["complete"] and out["partial"] == []
    assert all(marked(r) == ["样式"] for r in out["results"])
    mixed = run(v8, "样式 修好")  # only short terms: every one must appear
    assert [r["id"] for r in mixed["results"]] == ["e2"]
    filtered = run(v8, "页面 请帮我修复")  # long term matches, short term filters
    assert [r["id"] for r in filtered["results"]] == ["e1"] and filtered["complete"]


def test_short_query_window_is_reported_partial(v8, monkeypatch):
    search_mod = sys.modules[search.__module__]
    v8.message("s1", "样式最新", ts=NOW)  # newest row: the only one inside a 1-row window
    monkeypatch.setattr(search_mod, "EVENT_LIKE_ROWS", 1)
    out = run(v8, "样式", kinds=["event", "project"])
    assert [r["id"] for r in out["results"] if r["kind"] == "event"] == ["e5"]
    assert out["partial"] == ["event"] and not out["complete"]
    assert out["partial_reasons"] == {"event": "short_query_window"}
    assert run(v8, "样式最新")["complete"]  # 3+ chars go through the index, not the window


def test_full_page_from_window_is_exact_and_counted(v8, monkeypatch):
    search_mod = sys.modules[search.__module__]
    for i in range(PER_SOURCE + 1):
        v8.message("s1", f"样式 {i}", ts=NOW)
    monkeypatch.setattr(search_mod, "EVENT_LIKE_ROWS", PER_SOURCE + 1)
    out = run(v8, "样式", limit=50)
    assert out["counts"] == {"event": PER_SOURCE} and out["counts_at_least"] == ["event"]
    assert out["complete"]


def test_snippet_is_cut_around_the_hit(v8):
    v8.message("s1", "开头" + "甲" * 400 + "目标词出现在这里" + "乙" * 400, ts=NOW)
    hit = run(v8, "目标词")["results"][0]
    assert hit["snippet"].startswith("…") and hit["snippet"].endswith("…")
    assert len(hit["snippet"]) <= 98 and marked(hit) == ["目标词"]
    assert "开头" not in hit["snippet"]


def test_scope_applies_to_events(v8):
    assert run(v8, "page", scope={"agent_ids": ["claude_code"]})["counts"] == {"event": 0}
    assert run(v8, "page", scope={"agent_ids": ["codex"]})["counts"] == {"event": 1}
    assert run(v8, "登录", scope={"project_ids": ["p2"]})["counts"] == {"event": 0}
    assert run(v8, "登录页", scope={"from_ts": NOW - 2 * DAY})["counts"] == {"event": 2}
    assert run(v8, "page", scope={"from_ts": NOW - 2 * DAY})["counts"] == {"event": 0}


def test_empty_query_is_rejected(v8):
    for q in ("", "   "):
        with pytest.raises(ValueError):
            run(v8, q)


def test_route_returns_event_hits_on_v8_store(v8):
    from test_search_routes import client

    http, gateway = client(v8)
    try:
        body = http.get("/v1/search", params={"q": "登录页面", "kinds": "event"}).json()
        assert body["counts"] == {"event": 2} and body["complete"]
        short = http.get("/v1/search", params={"q": "登录", "kinds": "event"}).json()
        assert short["counts"] == {"event": 2}
        assert http.get("/v1/search", params={"q": " ", "kinds": "event"}).status_code == 400
    finally:
        gateway.close()


def test_legacy_event_fts_still_answers(world):
    """A pre-v8 store without event_search keeps the unicode61 prefix path."""
    world.session("s1", title="Legacy session", started=NOW - DAY)
    world.message("s1", "login page throws on submit")
    world.message("s1", "登录页面报错")
    out = run(world, "subm")
    assert out["counts"] == {"event": 1} and out["complete"]
    assert marked(out["results"][0]) == ["subm"]
    assert out["results"][0]["title"] == "Legacy session"
    # unicode61 cannot match inside a CJK run; those terms fall back to the LIKE scan.
    assert [r["id"] for r in run(world, "登录")["results"]] == ["e2"]
    assert [r["id"] for r in run(world, "submit 抛出")["results"]] == []
    assert [r["id"] for r in run(world, "页面报错")["results"]] == ["e2"]

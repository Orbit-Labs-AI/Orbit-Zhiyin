import time

import pytest
from conftest import DAY, NOW

from tandem_backend.features.search import parse, search, snippet, strip_marks
from tandem_backend.features.search_index import SearchIndex


@pytest.fixture
def seeded(world):
    world.project("p1", "Tandem 前端")
    world.project("p2", "billing-api")
    world.session("s1", project="p1", title="修复登录页面的样式问题", started=NOW - DAY)
    world.session("s2", source="s-codex", project="p2", title="Refactor login flow",
                  started=NOW - 40 * DAY)
    world.message("s1", "请帮我修复登录页面的样式问题", ts=NOW - DAY)
    world.message("s1", "登录页面还有一个 bug", ts=NOW - DAY)
    world.message("s1", "登录页面第三条", ts=NOW - DAY)
    world.message("s2", "login page throws on submit", ts=NOW - 40 * DAY)
    world.call("s1", command="git status", files=["/repo/src/app/login.tsx"])
    world.call("s2", command="pytest -q", files=["/repo/api/billing.py"])
    world.item("cat-1", "skill", "login-helper", summary="自动化登录流程")
    world.inventory("claude_code", [{"inv_id": "i1", "type": "skill", "name": "login-helper"}])
    index = SearchIndex(world.home)
    index.sync(world.tandem, data_rev=1)
    return world, index


def run(world, index, q, **kw):
    kw.setdefault("timeout_s", 5.0)  # deadline behaviour is tested explicitly below
    return search(world.home, q, index=index, data_rev=1, now_ms=NOW, **kw)


def test_parse_rules():
    assert parse("  abc 中文 x ")["match"] == '"abc"'
    assert parse("abc 中文 x")["like"] == ["中文", "x"]
    assert parse('a"bc')["match"] == '"a""bc"'
    with pytest.raises(ValueError):
        parse("   ")


def test_chinese_substring_and_marks(seeded):
    world, index = seeded
    out = run(world, index, "登录页面", kinds=["session", "message"])
    assert out["counts"] == {"session": 1, "message": 3}
    assert [r["kind"] for r in out["results"]].count("message") == 2  # per-session cap
    top = out["results"][0]
    assert top["kind"] == "session" and top["ref"] == {"page": "session", "id": "s1"}
    s, e = top["marks"][0]
    assert top["snippet"][s:e] == "登录页面"
    assert out["index"]["state"] == "ready" and out["partial"] == []


def test_short_terms_fall_back_to_like(seeded):
    world, index = seeded
    out = run(world, index, "登录", kinds=["session", "message"])
    assert out["counts"]["session"] == 1 and out["counts"]["message"] == 3
    out = run(world, index, "bug 登录页面", kinds=["message"])
    assert out["counts"] == {"message": 1}


def test_latin_prefix_command_file_and_scope(seeded):
    world, index = seeded
    out = run(world, index, "logi")
    kinds = {r["kind"] for r in out["results"]}
    assert {"session", "message", "file", "catalog", "inventory"} <= kinds
    file_hit = next(r for r in out["results"] if r["kind"] == "file")
    assert file_hit["title"] == "app/login.tsx" and file_hit["ref"]["id"] == "s1"
    scoped = run(world, index, "logi", kinds=["session", "message"],
                 scope={"project_ids": ["p2"]})
    assert {r["session_uid"] for r in scoped["results"]} == {"s2"}
    agent = run(world, index, "logi", kinds=["session"], scope={"agent_ids": ["codex"]})
    assert [r["id"] for r in agent["results"]] == ["s2"]
    recent = run(world, index, "logi", kinds=["message"], scope={"from_ts": NOW - 10 * DAY})
    assert recent["counts"]["message"] == 0
    git = run(world, index, "git", kinds=["command"])
    assert git["results"][0]["title"] == "git status"


def test_project_catalog_inventory_and_event(seeded):
    world, index = seeded
    out = run(world, index, "billing", kinds=["project", "file"])
    assert out["counts"] == {"project": 1, "file": 1}
    assert out["results"][0]["ref"] == {"page": "project", "id": "p2"}
    cat = run(world, index, "自动化", kinds=["catalog"])
    assert cat["results"][0]["ref"] == {"page": "library", "id": "cat-1"}
    linked = run(world, index, "helper", kinds=["inventory"],
                 linked=lambda: {"items": [{"inv_id": "x", "name": "Login-Helper", "type": "skill",
                                            "agent": "codex"}]})
    assert linked["results"][0]["ref"] == {"page": "local_library", "id": "x"}
    event = run(world, index, "subm", kinds=["event"])
    assert event["counts"] == {"event": 1}
    assert event["results"][0]["ref"]["event_uid"]


def test_missing_catalog_and_candidate_tables(seeded):
    world, index = seeded
    world.catalog.unlink()
    out = run(world, index, "login", kinds=["catalog", "recommendation", "session"])
    assert out["counts"]["catalog"] == 0 and out["counts"]["recommendation"] == 0
    assert out["partial"] == []
    world.a.execute("CREATE TABLE candidate (candidate_id TEXT, title TEXT)")
    world.a.execute("INSERT INTO candidate VALUES ('r1', '登录流程技能')")
    rec = run(world, index, "登录流程", kinds=["recommendation"])
    assert rec["results"][0]["ref"] == {"page": "recs", "id": "r1"}


def test_slow_source_lands_in_partial(seeded):
    world, index = seeded

    def slow():
        time.sleep(0.5)
        return []

    out = run(world, index, "login", kinds=["inventory", "session"], linked=slow,
              timeout_s=0.05)
    assert out["partial"] == ["inventory"]
    assert out["counts"].get("session") == 1


def test_failing_source_lands_in_partial(seeded):
    world, index = seeded

    def broken():
        raise RuntimeError("boom")

    out = run(world, index, "login", kinds=["inventory", "project"], linked=broken)
    assert out["partial"] == ["inventory"]


def test_rrf_order_is_stable(seeded):
    world, index = seeded
    first = run(world, index, "login")
    for _ in range(3):
        again = run(world, index, "login")
        assert [(r["kind"], r["id"]) for r in again["results"]] == \
            [(r["kind"], r["id"]) for r in first["results"]]
    scores = [r["score"] for r in first["results"]]
    assert scores == sorted(scores, reverse=True)


def test_empty_index_builds_inline(world):
    world.session("s1", title="第一次搜索")
    out = search(world.home, "第一次", index=SearchIndex(world.home), now_ms=NOW,
                 kinds=["session"])
    assert out["index"]["state"] == "ready" and out["counts"] == {"session": 1}


def test_snippet_helpers():
    text, marks = snippet("x" * 200 + "needle" + "y" * 200, ["needle"])
    assert text.startswith("…") and text[marks[0][0]:marks[0][1]] == "needle"
    assert strip_marks("a\x01bc\x02d") == ("abcd", [[1, 3]])

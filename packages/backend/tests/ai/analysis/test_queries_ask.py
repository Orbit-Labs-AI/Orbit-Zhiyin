"""AI-09 whitelist queries and L0 ask presets/answers (ASK-02, POP-11)."""

from __future__ import annotations

import pytest
from ai_analysis_fakectx import DAY, NOW

from orbit_backend.ai import ask, queries
from orbit_backend.ai import pack as P


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(P, "now_ms", lambda: NOW)


@pytest.fixture
def data(tdb, orbit_home):
    for i in range(6):
        tdb.session(f"cur{i}", project="p1" if i % 2 else "p2", title=f"任务{i}", start=NOW - (i + 1) * DAY,
                    humans=["做个功能", "不对，不是这样" if i < 4 else "好", "继续"],
                    tools=[("Bash", "shell", "pytest", "failed", "exit_nonzero"), ("Read", "read"),
                           ("mcp:github", "mcp")])
    for i in range(6):
        tdb.session(f"old{i}", start=NOW - (35 + i) * DAY, humans=["做个功能", "继续", "好"],
                    tools=[("Read", "read")])
    tdb.inventory([("mcp", "github", "/x"), ("mcp", "figma", "/y"), ("skill", "pr-wrap", "/z")])
    tdb.commit()
    return tdb


def test_params_out_of_range_raise():
    with pytest.raises(ValueError):
        queries.check("metrics", {"scope": {"days": 400}})
    with pytest.raises(ValueError):
        queries.check("search", {"q": "x" * 81})
    with pytest.raises(ValueError):
        queries.check("sessions", {"limit": 50})
    with pytest.raises(ValueError):
        queries.check("tools", {"sql": "DROP TABLE x"})
    with pytest.raises(ValueError):
        queries.check("text", {})
    with pytest.raises(ValueError):
        queries.check("search", {})
    assert queries.check("metrics", {"metric": "correction_rate", "scope": {"days": 7}})


def test_run_shapes(data, orbit_home):
    kw = dict(reads=data.reads, home=orbit_home)
    m = queries.run("metrics", {"scope": {"days": 30}}, **kw)
    rows = {r["metric"]: r for r in m["rows"]}
    assert rows["sessions"]["value"] == 6 and rows["sessions"]["prev"] == 6
    assert rows["corrections"]["value"] == 4 and rows["corrections"]["prev"] == 0
    assert {"kind": "metric", "id": "correction_rate"} in m["refs"] and 6.0 in m["numbers"]
    s = queries.run("sessions", {"limit": 3}, **kw)
    assert len(s["rows"]) == 3 and s["rows"][0]["session_uid"] == "cur0"
    assert {"kind": "session", "id": "cur0"} in s["refs"]
    t = queries.run("tools", {}, **kw)
    assert t["rows"][0]["tool"] == "Bash" and t["rows"][0]["failures"] == 6
    inv = {r["name"]: r for r in queries.run("inventory", {}, **kw)["rows"]}
    assert inv["github"]["calls_30d"] == 6 and inv["figma"]["calls_30d"] == 0
    ev = queries.run("evidence", {"session_uid": "cur1"}, **kw)
    assert [r["event_uid"] for r in ev["rows"]] == ["cur1-h0", "cur1-h1", "cur1-h2"]
    assert queries.run("catalog", {"q": "x"}, **kw)["rows"] == []
    proj = queries.run("projects", {}, **kw)["rows"]
    assert {p["name"] for p in proj} == {"alpha", "beta"}
    for api in queries.APIS:
        assert len(queries.run(api, {"q": "功能"} if api in ("search", "catalog") else {}, **kw)["rows"]) <= 20


def test_presets_deterministic_and_gated(data, orbit_home):
    kw = dict(reads=data.reads, appdb=None, home=orbit_home)
    over = ask.presets("overview", **kw)
    assert over == ask.presets("overview", **kw)
    assert [p["question"] for p in over][:3] == ask.ASKQ["overview"]
    assert over[-1] == {"index": 3, "question": "为什么本周纠偏率上升？"}  # 0 → 4 corrections
    assert len(ask.presets("tools", **kw)) == 4  # failures 0% → 50%
    for ctx in ask.ASKQ:
        assert len(ask.presets(ctx, **kw)) >= 3
    calm = dict(kw, scope={"days": 30})
    # earlier window has no rise → no conditional question
    data.db.execute("DELETE FROM session WHERE session_uid LIKE 'cur%'")
    data.commit()
    assert len(ask.presets("overview", **calm)) == 3


def test_preset_answers_use_query_numbers(data, orbit_home):
    kw = dict(reads=data.reads, appdb=None, home=orbit_home)
    a = ask.preset_answer("overview", 2, **kw)
    assert a["source"] == "template" and "4 ÷ 18" in a["answer"]
    assert {"kind": "metric", "id": "corrections"} in a["refs"]
    assert "6 → 6" in ask.preset_answer("overview", 0, **kw)["answer"]
    assert "Bash 失败最多：6 次" in ask.preset_answer("tools", 0, **kw)["answer"]
    assert "figma" in ask.preset_answer("tools", 2, **kw)["answer"]
    assert ask.preset_answer("session", 0, **kw)["answer"] == "先在左侧选一个会话。"
    s = ask.preset_answer("session", 0, session_uid="cur1", **kw)
    assert "1 次错误" in s["answer"] and {"kind": "session", "id": "cur1"} in s["refs"]
    for ctx, qs in ask.ASKQ.items():
        for i in range(len(qs)):
            r = ask.preset_answer(ctx, i, **kw)
            assert r["answer"] and r["next"] in ("studio", "recs", "sessions", "tools", "none")


def test_answers_degrade_without_db(orbit_home):
    def reads():
        raise RuntimeError("no db")
    r = ask.preset_answer("overview", 2, reads=reads, home=orbit_home)
    assert r["answer"] and r["refs"] == []
    assert ask.presets("overview", reads=reads)[:3] == [{"index": i, "question": q}
                                                       for i, q in enumerate(ask.ASKQ["overview"])]
    assert ask.opening_suggestion(reads) is None


def test_opening_suggestion(data, orbit_home):
    s = ask.opening_suggestion(data.reads, home=orbit_home, scope={"days": 7})
    assert s["text"] and s["next"] in ("studio", "sessions")


def test_out_of_scope_routes_pages():
    r = ask.out_of_scope("哪个 MCP 最慢")
    assert r["answer"] == ask.OUT_OF_SCOPE and r["pages"][0]["page"] == "A4"
    assert ask.out_of_scope("今天天气")["pages"] == [{"page": "A1", "label": "概览"}]


# ---------------------------------------------------------------- real orbit.db (synthetic Codex import)

@pytest.fixture(scope="module")
def real_db(tmp_path_factory):
    import sqlite3
    import sys
    from contextlib import contextmanager
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parents[2] / "services"))
    from orbit_data.service import ImportRequest, ImportService
    from orbit_data.store import Store
    from synthetic import write_codex_tree

    root = tmp_path_factory.mktemp("real")
    write_codex_tree(root / "codex", 24)
    store = Store(root / "orbit")
    ImportService(store).import_source(ImportRequest("codex", root / "codex"))

    @contextmanager
    def reads():
        conn = sqlite3.connect((root / "orbit" / "orbit.db").as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    return reads, root


def test_real_db_pack_queries_and_presets(real_db, monkeypatch, user_home):
    import time

    from orbit_backend.ai.tasks_analysis import TASKS
    monkeypatch.setattr(P, "now_ms", lambda: int(time.time() * 1000))
    reads, root = real_db
    home = root / "home"
    pack = P.build(TASKS["narrate.overview"], reads=reads, appdb=None, home=home,
                   selection={"items": {"sessions": True}})
    assert pack["content"]["metrics"]["sessions"] > 0
    assert pack["content"]["metrics"]["human_messages"] >= pack["content"]["metrics"]["sessions"]
    assert pack["content"]["sessions"] and pack["refs"]["session"]
    uids = [s["session_uid"] for s in pack["content"]["sessions"][:3]]
    facet = P.build(TASKS["facet.session"], reads=reads, appdb=None, home=home, params={"session_uids": uids})
    assert set(facet["content"]["items"]) == set(uids)
    assert all(p["human_messages"] for p in facet["content"]["items"].values())
    manual = P.build({"task_id": "t", "pack_items": [("evidence", True)]}, reads=reads, appdb=None, home=home,
                     goal="synthetic task")
    assert 0 < len(manual["content"]["evidence"]) <= 5
    for api in queries.APIS:
        queries.run(api, {"q": "synthetic"} if api in ("search", "catalog") else {}, reads=reads, home=home)
    for ctx, qs in ask.ASKQ.items():
        assert len(ask.presets(ctx, reads=reads, home=home)) >= 3
        for i in range(len(qs)):
            assert ask.preset_answer(ctx, i, reads=reads, home=home)["answer"]


def test_tool_rates_use_known_results_only(tdb, orbit_home):
    # Synthetic: 99 unknown + 1 failed Edit, 3 completed + 1 failed + 1 declined Read.
    tools = [("Edit", "edit", None, "unknown")] * 99 + [("Edit", "edit", None, "failed")]
    tools += [("Read", "read", None, "completed")] * 3 + [("Read", "read", None, "failed"),
                                                         ("Read", "read", None, "declined")]
    tdb.session("s", start=NOW - DAY, tools=tools)
    tdb.commit()
    kw = dict(reads=tdb.reads, home=orbit_home)
    rows = {r["tool"]: r for r in queries.run("tools", {}, **kw)["rows"]}
    assert rows["Edit"]["failure_rate"] == 1.0  # 1 of 1 known; unknown_share exposes the gap
    assert rows["Edit"]["known"] == 1 and rows["Edit"]["unknown_share"] == 0.99
    assert rows["Read"]["failure_rate"] == 0.25 and rows["Read"]["rejected"] == 1
    m = {r["metric"]: r["value"] for r in queries.run("metrics", {"scope": {"days": 30}}, **kw)["rows"]}
    assert m["tool_failures"] == 2 and m["tool_failure_rate"] == round(2 / 5, 3)


def _subagent_lineage(tdb, child, root):
    tdb.db.execute("ALTER TABLE session ADD COLUMN root_uid TEXT")
    tdb.db.execute("ALTER TABLE session ADD COLUMN lineage_unresolved INTEGER DEFAULT 0")
    tdb.db.execute("UPDATE session SET root_uid=? WHERE session_uid=?", (root, child))


def test_inventory_counts_beyond_twenty_and_subagent_calls(tdb, orbit_home, monkeypatch):
    monkeypatch.setattr(P, "now_ms", lambda: NOW)
    tdb.session("main1", start=NOW - DAY, tools=[("mcp:m00", "mcp")])
    # m07 is only ever called from a subagent of main1
    tdb.session("sub1", kind="subagent", start=NOW - DAY, tools=[("mcp:m07", "mcp"), ("mcp:m07", "mcp")])
    items = [("mcp", f"m{i:02d}", f"/m{i}") for i in range(25)] + [("skill", f"s{i}", f"/s{i}") for i in range(3)]
    tdb.inventory(items)
    _subagent_lineage(tdb, "sub1", "main1")
    tdb.commit()
    r = queries.run("inventory", {"limit": 5}, reads=tdb.reads, home=orbit_home)
    # 25 MCPs and 3 skills installed; only m00 (1 call) and m07 (2 subagent calls) were used.
    assert r["totals"] == {"mcp": {"count": 25, "unused": 23}, "skill": {"count": 3, "unused": 3}}
    assert [(x["name"], x["calls_30d"]) for x in r["rows"][:2]] == [("m07", 2), ("m00", 1)]
    assert len(r["rows"]) == 5
    unused = {x["name"] for x in r["unused"]}
    assert "m07" not in unused and "m00" not in unused and "m24" in unused and len(unused) == 26
    q = ask._Q(tdb.reads, None, {}, orbit_home)
    assert ask._li_all(q, None)[0] == "已装组件：mcp 25 个，skill 3 个。"
    text, _ = ask._to_mcp(q, None)
    assert "m07" not in text and "等 23 个" in text
    text, _ = ask._li_unused(q, None)
    assert text.startswith("近 30 天没有调用的有 26 个：")


def test_inventory_respects_exclusion(tdb, orbit_home, monkeypatch):
    monkeypatch.setattr(P, "now_ms", lambda: NOW)
    tdb.session("keep", start=NOW - DAY, tools=[("mcp:a", "mcp")])
    tdb.session("drop", start=NOW - DAY, tools=[("mcp:b", "mcp")])
    tdb.inventory([("mcp", "a", "/a"), ("mcp", "b", "/b")])
    tdb.commit()
    monkeypatch.setattr(queries, "_excluded", lambda appdb: ["drop"])
    r = queries.run("inventory", {}, reads=tdb.reads, home=orbit_home)
    assert {x["name"]: x["calls_30d"] for x in r["rows"]} == {"a": 1, "b": 0}


def test_session_answers_state_counts_without_ranking_units(tdb, orbit_home, monkeypatch):
    monkeypatch.setattr(P, "now_ms", lambda: NOW)
    # e1: 3 tool errors, 0 corrections; c1: 0 errors, 1 correction; both: 1 error + 2 corrections
    fail = ("Bash", "shell", "pytest", "failed", "exit_nonzero")
    tdb.session("e1", start=NOW - DAY, humans=["跑测试"], tools=[fail] * 3)
    tdb.session("c1", start=NOW - DAY, humans=["改一下", "不对，不是这个文件"], tools=[("Read", "read")])
    tdb.session("b1", start=NOW - DAY, humans=["改", "不对", "我说的是另一个"], tools=[fail])
    tdb.commit()
    kw = dict(reads=tdb.reads, appdb=None, home=orbit_home)
    tool_rule, approach_rule = ask.FRIC_RULE["tool_env_failure"], ask.FRIC_RULE["wrong_approach"]
    e = ask.preset_answer("session", 0, session_uid="e1", **kw)["answer"]
    assert "3 次错误，0 次纠偏" in e and tool_rule in e and approach_rule not in e
    c = ask.preset_answer("session", 0, session_uid="c1", **kw)["answer"]
    assert "0 次错误，1 次纠偏" in c and approach_rule in c and tool_rule not in c
    b = ask.preset_answer("session", 0, session_uid="b1", **kw)["answer"]
    # errors (1) < corrections (2) used to hide the tool rule; both are now listed
    assert "1 次错误，2 次纠偏" in b and tool_rule in b and approach_rule in b
    assert "主要卡在" not in e + c + b
    rule = ask.preset_answer("session", 2, session_uid="b1", **kw)["answer"]
    assert f"- {tool_rule}" in rule and f"- {approach_rule}" in rule


def test_recs_pair_makes_no_compatibility_claim(data, orbit_home, monkeypatch):
    cands = [{"candidate_id": "a", "title": "熔断", "kind": "hook", "priority": 3},
             {"candidate_id": "b", "title": "提交规范", "kind": "rule", "priority": 2}]
    monkeypatch.setattr(P, "candidates", lambda scope, limit, appdb: cands)
    a = ask.preset_answer("recs", 1, reads=data.reads, home=orbit_home)["answer"]
    assert "「熔断」（hook）" in a and "「提交规范」（rule）" in a and "互不影响" not in a


def test_persona_tradeoff_reads_profile(data, orbit_home, monkeypatch):
    kw = dict(reads=data.reads, home=orbit_home)
    monkeypatch.setattr(ask, "features_profile", lambda scope: {})
    assert "画像还没生成" in ask.preset_answer("persona", 1, **kw)["answer"]
    monkeypatch.setattr(ask, "features_profile", lambda scope: {
        "code": "P", "label": "规划型", "weights": {"planning": 0.72, "verification": 0.4}})
    a1 = ask.preset_answer("persona", 1, **kw)["answer"]
    monkeypatch.setattr(ask, "features_profile", lambda scope: {
        "code": "B", "label": "速攻型", "weights": {"brevity": 0.9}})
    a2 = ask.preset_answer("persona", 1, **kw)["answer"]
    assert "planning 72%" in a1 and "verification 40%" in a1 and "brevity 90%" in a2 and a1 != a2


def test_tool_worst_recommends_breaker_only_when_missing(data, orbit_home):
    kw = dict(reads=data.reads, home=orbit_home)
    assert "装「重复失败熔断」" in ask.preset_answer("tools", 0, **kw)["answer"]
    data.inventory([("hook", "orbit-retry-breaker", "/h")], root="/hooks")
    data.commit()
    a = ask.preset_answer("tools", 0, **kw)["answer"]
    assert "已安装" in a and "装「重复失败熔断」" not in a


class _BrokenAppDB:
    """app.db whose reads fail (closed / corrupt)."""

    def read(self):
        raise RuntimeError("app.db closed")


def test_inventory_reads_persisted_exclusion_from_appdb(tdb, orbit_home, appdb, monkeypatch):
    import sqlite3

    monkeypatch.setattr(P, "now_ms", lambda: NOW)
    tdb.session("keep", start=NOW - DAY, tools=[("mcp:a", "mcp")])
    tdb.session("drop", start=NOW - DAY, tools=[("mcp:b", "mcp")])
    tdb.inventory([("mcp", "a", "/a"), ("mcp", "b", "/b")])
    tdb.commit()
    with sqlite3.connect(appdb.path) as db:
        db.execute("INSERT INTO session_exclusion(session_uid, excluded_at) VALUES ('drop', 1)")
    r = queries.run("inventory", {}, reads=tdb.reads, appdb=appdb, home=orbit_home)
    # "drop" is the only session that called b, so excluding it leaves b at 0 calls.
    assert {x["name"]: x["calls_30d"] for x in r["rows"]} == {"a": 1, "b": 0}


def test_exclusion_read_failure_is_fail_closed(tdb, orbit_home, monkeypatch):
    from orbit_backend.sessionops.exclusion import ExclusionsUnavailable

    monkeypatch.setattr(P, "now_ms", lambda: NOW)
    tdb.session("drop", start=NOW - DAY, tools=[("mcp:b", "mcp")])
    tdb.inventory([("mcp", "b", "/b")])
    tdb.commit()
    with pytest.raises(ExclusionsUnavailable) as err:
        queries.run("inventory", {}, reads=tdb.reads, appdb=_BrokenAppDB(), home=orbit_home)
    assert err.value.status == 503
    # ask must not swallow it into an empty ("0 个") answer either.
    q = ask._Q(tdb.reads, _BrokenAppDB(), {}, orbit_home)
    with pytest.raises(ExclusionsUnavailable):
        q.inventory()
    with pytest.raises(ExclusionsUnavailable):
        q("metrics")

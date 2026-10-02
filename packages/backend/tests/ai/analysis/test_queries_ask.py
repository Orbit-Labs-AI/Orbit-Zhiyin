"""AI-09 whitelist queries and L0 ask presets/answers (ASK-02, POP-11)."""

from __future__ import annotations

import pytest
from ai_analysis_fakectx import DAY, NOW

from tandem_backend.ai import ask, queries
from tandem_backend.ai import pack as P


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(P, "now_ms", lambda: NOW)


@pytest.fixture
def data(tdb, tandem_home):
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


def test_run_shapes(data, tandem_home):
    kw = dict(reads=data.reads, home=tandem_home)
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


def test_presets_deterministic_and_gated(data, tandem_home):
    kw = dict(reads=data.reads, appdb=None, home=tandem_home)
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


def test_preset_answers_use_query_numbers(data, tandem_home):
    kw = dict(reads=data.reads, appdb=None, home=tandem_home)
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


def test_answers_degrade_without_db(tandem_home):
    def reads():
        raise RuntimeError("no db")
    r = ask.preset_answer("overview", 2, reads=reads, home=tandem_home)
    assert r["answer"] and r["refs"] == []
    assert ask.presets("overview", reads=reads)[:3] == [{"index": i, "question": q}
                                                       for i, q in enumerate(ask.ASKQ["overview"])]
    assert ask.opening_suggestion(reads) is None


def test_opening_suggestion(data, tandem_home):
    s = ask.opening_suggestion(data.reads, home=tandem_home, scope={"days": 7})
    assert s["text"] and s["next"] in ("studio", "sessions")


def test_out_of_scope_routes_pages():
    r = ask.out_of_scope("哪个 MCP 最慢")
    assert r["answer"] == ask.OUT_OF_SCOPE and r["pages"][0]["page"] == "A4"
    assert ask.out_of_scope("今天天气")["pages"] == [{"page": "A1", "label": "概览"}]


# ---------------------------------------------------------------- real tandem.db (synthetic Codex import)

@pytest.fixture(scope="module")
def real_db(tmp_path_factory):
    import sqlite3
    import sys
    from contextlib import contextmanager
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parents[2] / "services"))
    from synthetic import write_codex_tree
    from tandem_data.service import ImportRequest, ImportService
    from tandem_data.store import Store

    root = tmp_path_factory.mktemp("real")
    write_codex_tree(root / "codex", 24)
    store = Store(root / "tandem")
    ImportService(store).import_source(ImportRequest("codex", root / "codex"))

    @contextmanager
    def reads():
        conn = sqlite3.connect((root / "tandem" / "tandem.db").as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    return reads, root


def test_real_db_pack_queries_and_presets(real_db, monkeypatch, user_home):
    import time

    from tandem_backend.ai.tasks_analysis import TASKS
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

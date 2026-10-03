"""A5 项目 adapter over a synthetic three-project orbit.db (tmp_path only)."""

from __future__ import annotations

import json
import math
import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from orbit_backend.appdb import AppDB
from orbit_backend.features.service import FeatureService
from orbit_backend.services.gateway import install_error_handlers
from orbit_backend.uiview import a4a6_projects as P
from orbit_backend.uiview import a4a6_sentiment as S

from .a4a6_ps_fixture import DAY, MIN, T0, Orbit, ro

FLOW = ["git status", "pytest -q", "git commit"]


def seed(t: Orbit) -> None:
    t.project("p1", name="confluo", git="github.com/org/confluo")
    t.project("p2", name="web")
    t.project("p3", name="tiny")
    # p1: s1/s2 overlap (union 40 min), s3-s5 60 min, s6 open with last event at +20 min.
    t.session("s1", project="p1", start=T0, minutes=30, cwd="/w/p1/apps/web")
    t.session("s2", project="p1", start=T0 + 10 * MIN, minutes=30, cwd="/w/p1/apps/web")
    for i, uid in enumerate(("s3", "s4", "s5"), start=1):
        t.session(uid, project="p1", start=T0 + i * DAY, minutes=60,
                  agent="codex" if uid == "s5" else "claude_code")
    t.session("s6", project="p1", start=T0 + 4 * DAY, ended=False, agent="codex")
    t.human("s1", "帮我修一下 fastapi 后端接口", ts=T0)
    # Corrections count only after the agent responded (rules.countable_messages).
    t.event("s1", "message.assistant", ts=T0 + MIN // 2, actor="assistant", text="好的")
    t.human("s1", "不对，重新来", ts=T0 + MIN)
    t.event("s2", "message.assistant", ts=T0 + 11 * MIN, actor="assistant", text="好的")
    t.human("s2", "别用子代理", ts=T0 + 11 * MIN)
    t.call("s1", head="git status", files=["/w/p1/a.py"], ts=T0 + 2 * MIN)
    t.call("s1", head="pytest -q", status="failed", files=["/w/p1/b.py"], ts=T0 + 3 * MIN)
    for i, uid in enumerate(("s3", "s4", "s5"), start=1):
        start = T0 + i * DAY
        t.human(uid, "继续完善后端接口", ts=start)
        t.human(uid, "可以了", ts=start + MIN)
        for j, head in enumerate(FLOW):
            t.call(uid, head=head, files=["/w/p1/x.ts"] if j == 0 else ["/w/p1/y.py"],
                   ts=start + (2 + j) * MIN)
        t.call(uid, head=FLOW[-1], ts=start + 9 * MIN)  # repeated step collapses
    t.human("s6", "看一下日志", ts=T0 + 4 * DAY)
    t.event("s6", "message.assistant", ts=T0 + 4 * DAY + 20 * MIN, actor="assistant", text="ok")
    # p2: 5 sessions; a 3-step chain seen in only 2 sessions.
    for i in range(5):
        uid = f"w{i}"
        t.session(uid, project="p2", start=T0 + i * DAY + 5 * 3_600_000, minutes=20)
        t.human(uid, "改一下页面样式", ts=T0 + i * DAY + 5 * 3_600_000)
        if i < 2:
            for j, head in enumerate(["ls", "make", "npm run build"]):
                t.call(uid, head=head, ts=T0 + i * DAY + 5 * 3_600_000 + j * MIN)
    # p3: 2 sessions only.
    for i in range(2):
        t.session(f"t{i}", project="p3", start=T0 + i * DAY + 8 * 3_600_000, minutes=10)
        t.human(f"t{i}", "hello", ts=T0 + i * DAY + 8 * 3_600_000)


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def db(home):
    t = Orbit(home)
    seed(t)
    yield t
    t.close()


@pytest.fixture
def conn(db):
    c = ro(db.path)
    yield c
    c.close()


def by_id(body):
    return {p["project_id"]: p for p in body["projects"]}


def test_hours_union_scatter_and_no_regression(conn):
    body = P.build_projects(conn, {}, {})
    rows = by_id(body)
    p1 = rows["p1"]
    assert p1["sessions"] == 6
    # Active time (5-min capped gaps between events, uiview.metrics): s1 events at 0/1/2/3 min
    # = 3; s2 one event = 0; s3-s5 at 0/1/2/3/4/9 = 4 + 5 = 9 each; s6 at 0/20 = 5 (capped).
    # Span union (idle included) is still reported separately: s1∪s2 40 + 3×60 + 20.
    assert p1["hours"] == {"value": round((3 + 0 + 3 * 9 + 5) / 60, 2),
                           "basis": "active_estimate",
                           "span": round((40 + 3 * 60 + 20) / 60, 2),
                           "span_basis": "observed_span_union_incl_idle"}
    assert p1["friction"]["corr"] == 2 and p1["friction"]["msgs"] == 10
    assert p1["friction"]["basis"] == "lexical_candidate"
    assert p1["friction"]["lo"] < p1["friction"]["value"] < p1["friction"]["hi"]
    assert p1["tools_per_human_message"] == round(14 / 10, 2)
    assert p1["tags"][0] == "Python" and "TypeScript" in p1["tags"]
    assert p1["identity_quality"] == "path" and p1["git"] == "github.com/org/confluo"
    agents = {a["agent"]: a for a in p1["agents"]}
    assert agents["claude_code"]["sessions"] == 4 and agents["codex"]["sessions"] == 2
    assert agents["claude_code"]["accepted"] == 2 and agents["codex"]["accepted"] == 1
    assert agents["claude_code"]["reworked"] == 1  # s1: 不对，重新来
    assert p1["persona"]["code"] is None and p1["persona"]["status"] == "persona_pending"
    ids = {p["id"] for p in body["scatter"]["points"]}
    assert ids == {"p1", "p2"}  # p3 has < 5 sessions
    assert body["scatter"]["note"] == "相关不等于因果"
    text = json.dumps(body)
    for banned in ("fit", "regression", "residual", "slope"):
        assert f'"{banned}' not in text


def test_group_folder_sums_to_project_sessions(conn):
    body = P.build_projects(conn, {}, {"group": "folder"})
    sums = {}
    for f in body["folders"]:
        sums[f["belongs_to"]] = sums.get(f["belongs_to"], 0) + f["sessions"]
    assert sums == {p["project_id"]: p["sessions"] for p in body["projects"]}
    web = next(f for f in body["folders"] if f["cwd"] == "/w/p1/apps/web")
    # Active time of s1 (3 min) + s2 (single event, 0 min); the 40-min span is idle-inclusive.
    assert web["sessions"] == 2 and web["hours"] == round(3 / 60, 2)


def test_persona_lookup_is_optional(conn):
    body = P.build_projects(conn, {}, {}, persona_lookup=lambda pid: {"code": "CEAS",
                                                                       "n_tasks": 9}
                            if pid == "p1" else None)
    rows = by_id(body)
    assert rows["p1"]["persona"]["code"] == "CEAS" and rows["p2"]["persona"]["code"] is None

    def boom(pid):
        raise RuntimeError(pid)

    assert by_id(P.build_projects(conn, {}, {}, persona_lookup=boom))["p1"]["persona"]["code"] is None


def _wilson(k, n, z=1.959963984540054):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def test_compare_newcombe_and_small_n(conn):
    detail = P.build_project(conn, {}, "p1", {"compare": "overall"})
    metrics = {m["key"]: m for m in detail["vs"]["metrics"]}
    assert len(metrics) == 6
    verify = metrics["verify_rate"]
    # p1: 4/6 ran a verify command (s1, s3-s5); overall adds `make` in w0/w1: 6/13.
    p1, p2 = 4 / 6, 6 / 13
    l1, u1 = _wilson(4, 6)
    l2, u2 = _wilson(6, 13)
    assert verify["a"] == round(p1, 3) and verify["b"] == round(p2, 3)
    assert verify["delta"] == round(p1 - p2, 3)
    assert verify["lo"] == round(p1 - p2 - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), 3)
    assert verify["hi"] == round(p1 - p2 + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2), 3)
    assert isinstance(verify["flat"], bool)
    small = P.build_project(conn, {}, "p1", {"compare": "p3"})
    for m in small["vs"]["metrics"]:
        assert m["flat"] is None and m["delta"] is None and m["note"] == "无可比"


def test_workflows_need_three_sessions(conn):
    flows = P.build_project(conn, {}, "p1", {})["workflows"]
    assert flows, "the 3-step chain in s3/s4/s5 must surface"
    top = flows[0]
    assert [s["head"] for s in top["steps"]] == FLOW
    assert top["support_sessions"] == 3 and top["session_uids"] == ["s3", "s4", "s5"]
    assert top["eligible_sessions"] == 3 and top["support_rate"] == 1.0
    assert P.build_project(conn, {}, "p2", {})["workflows"] == []  # only 2 sessions


def test_coverage_and_rule_files(conn, db, home, tmp_path):
    proj = tmp_path / "w" / "p1"
    proj.mkdir(parents=True)
    agents_md = proj / "AGENTS.md"
    agents_md.write_text("# rules\nline two\nline three\n")
    outside = tmp_path / "elsewhere" / "CLAUDE.md"
    outside.parent.mkdir()
    outside.write_text("secret\n")
    db.db.execute("UPDATE project SET paths=? WHERE project_id='p1'", (json.dumps([str(proj)]),))
    db.inventory([("rule", "AGENTS.md", str(agents_md), {"project_path": str(proj)}),
                  ("hook", "PreToolUse", str(proj / ".claude/settings.json"),
                   {"project_path": str(proj)}),
                  ("skill", "pdf", str(proj / ".claude/skills/pdf/SKILL.md"),
                   {"project_path": str(proj)}),
                  ("agent", "reviewer", str(proj / ".claude/agents/reviewer.md"),
                   {"project_path": str(proj)})], project="p1")
    db.inventory([("mcp", "playwright", str(home / "mcp.json"), {}),
                  ("rule", "CLAUDE.md", str(outside), {})], scope="global")
    appdb = AppDB(home / "app.db")
    svc = FeatureService(home, appdb, lambda: {"data_rev": 1, "inventory_rev": 1})
    try:
        items = svc.linked_inventory({"project_ids": ["p1"]})["items"]
    finally:
        svc.close()
        appdb.close()
    c = ro(db.path)
    try:
        detail = P.build_project(c, {}, "p1", {}, inventory_items=items,
                                 allowed_roots=[proj])
    finally:
        c.close()
    cov = {x["type"]: x for x in detail["coverage"]}
    assert all(cov[k]["configured"] is True for k in ("rule", "hook", "skill", "mcp"))
    # Subagent definitions are inventory type "agent" (schema 15); no command was scanned here.
    assert cov["subagent"]["configured"] is True and cov["subagent"]["project"] == 1
    assert cov["subagent"]["inventory_type"] == "agent"
    assert cov["command"]["configured"] is False and cov["command"]["detail"] == "项目 0 · 全局 0"
    assert "claude_code" in cov["subagent"]["agents_read"]
    assert "codex" not in cov["subagent"]["agents_read"] and "codex" in cov["mcp"]["agents_read"]
    files = detail["header"]["rule_files"]
    assert len(files) == 1 and detail["header"]["rule_files_rejected"] == 1
    st = os.stat(agents_md)
    assert files[0] == {"path": os.path.realpath(agents_md), "bytes": st.st_size, "lines": 3,
                        "mtime": int(st.st_mtime * 1000), "agent": "claude_code"}
    no_inv = P.build_project(conn, {}, "p1", {}, inventory_items=None)
    assert all(x["configured"] is None for x in no_inv["coverage"])


def test_evidence_and_top_recommendation(conn, home):
    appdb = AppDB(home / "app.db")
    try:
        with appdb.write() as w:
            w.execute("INSERT INTO rec_run(run_id,scope_hash,scope,inputs_digest,engine_version,"
                      "status,created_at) VALUES ('r1','h','{\"project_ids\":[\"p1\"]}','d','v','ok',1)")
            for cid, rank in (("c2", 2), ("c1", 1)):
                w.execute("INSERT INTO rec_candidate(candidate_id,run_id,rec_key,kind,dim,title,rank,"
                          "passed,card,created_at) VALUES (?,?,?,?,?,?,?,1,'{}',1)",
                          (cid, "r1", cid, "rule", "d", f"title {cid}", rank))
        detail = P.build_project(conn, {}, "p1", {}, appdb=appdb)
        other = P.build_project(conn, {}, "p2", {}, appdb=appdb)
    finally:
        appdb.close()
    assert detail["top_recommendation"] == {"candidate_id": "c1", "title": "title c1"}
    assert other["top_recommendation"] is None
    ev = detail["evidence_preview"]
    assert 1 <= len(ev) <= 5
    assert {e["kind"] for e in ev} == {"human", "error"}
    assert P.build_project(conn, {}, "nope", {}) is None


# ------------------------------------------------------------------ routes

class _Reads:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def read(self, check=True, empty=False):
        c = ro(self.path)
        try:
            yield c
        finally:
            c.close()

    def is_empty(self, connection):
        return False


def make_client(home, path, **extra):
    appdb = AppDB(home / "app.db")
    gw = SimpleNamespace(home=home, appdb=appdb, reads=_Reads(path), **extra)
    api = APIRouter()
    P.register(api, gw)
    S.register(api, gw)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(api)
    return TestClient(app), appdb


def test_routes(db, home):
    client, appdb = make_client(home, db.path)
    try:
        r = client.get("/v1/uiview/projects")
        assert r.status_code == 200
        assert r.json()["projects"][0]["persona"]["code"] is None
        assert client.get("/v1/uiview/projects", params={"group": "folder"}).json()["folders"]
        assert client.get("/v1/uiview/projects", params={"group": "x"}).status_code == 400
        d = client.get("/v1/uiview/projects/p1", params={"compare": "p2"})
        assert d.status_code == 200 and d.json()["vs"]["against"] == "p2"
        assert client.get("/v1/uiview/projects/missing").status_code == 404
        s = client.get("/v1/uiview/sentiment", params={"since": T0 - DAY, "until": T0 + 10 * DAY,
                                                       "tz": "UTC"})
        assert s.status_code == 200 and s.json()["meta"]["experimental"] is True
        assert client.get("/v1/uiview/sentiment", params={"bucket": "month"}).status_code == 400
    finally:
        appdb.close()


def _count(client, path, **params):
    body = client.get(path, params=params).json()
    if path == "/v1/uiview/projects/p1":
        return body["header"]["sessions"], body
    return body["meta"]["n_sessions"], body


def test_routes_respect_exclusion_and_source_range(db, home, monkeypatch):
    """A5/A6 see the same session set as analytics_scope (UT-01)."""
    from orbit_backend.appdata import sources_scope
    from orbit_backend.sessionops import exclusion

    # x1/x2 (p2) share a phrase (phrases need >= 2 sessions) and fail twice (rule friction,
    # so x1's opening message is the friction ``typical`` quote).
    marker = "这个迁移脚本又跑挂了"
    for i, uid in enumerate(("x1", "x2")):
        start = T0 + (6 + i) * DAY
        db.session(uid, project="p2", start=start, minutes=15)
        db.human(uid, marker, ts=start)
        for j in range(2):
            db.call(uid, head="pytest -q", status="failed", ts=start + (1 + j) * MIN)
    window = {"since": T0 - DAY, "until": T0 + 10 * DAY, "tz": "UTC"}
    client, appdb = make_client(home, db.path)
    try:
        base = {path: _count(client, path, **(window if "sentiment" in path else {}))
                for path in ("/v1/uiview/projects", "/v1/uiview/projects/p1",
                             "/v1/uiview/sentiment")}
        senti = base["/v1/uiview/sentiment"][1]
        assert any(p["text"] == marker for p in senti["phrases"])
        assert any(marker in t for f in senti["friction"] for t in f["typical"])
        monkeypatch.setattr(exclusion, "_provider", lambda: ["s1", "x1"])
        got, _ = _count(client, "/v1/uiview/projects")
        assert got == base["/v1/uiview/projects"][0] - 2
        got, _ = _count(client, "/v1/uiview/projects/p1")
        assert got == base["/v1/uiview/projects/p1"][0] - 1
        got, senti = _count(client, "/v1/uiview/sentiment", **window)
        assert got == base["/v1/uiview/sentiment"][0] - 2
        # x2 alone no longer forms a phrase; the typical quote now comes from x2, never x1/s1.
        assert all(p["text"] != marker for p in senti["phrases"])
        assert all("x1" not in f["session_uids"] and "s1" not in f["session_uids"]
                   for f in senti["friction"])
        monkeypatch.setattr(exclusion, "_provider", lambda: [])
        # Disabling the codex source drops s5 and s6 (the only codex sessions; s6 is in p1).
        monkeypatch.setattr(sources_scope, "_provider", lambda: [
            {"id": "src-claude_code", "enabled": True}, {"id": "src-codex", "enabled": False}])
        n, _ = _count(client, "/v1/uiview/projects/p1")
        assert n == base["/v1/uiview/projects/p1"][0] - 2
        n, _ = _count(client, "/v1/uiview/sentiment", **window)
        assert n == base["/v1/uiview/sentiment"][0] - 2
    finally:
        appdb.close()


def test_coverage_agents_read_and_unscanned_follow_inventory():
    cov = {x["type"]: x for x in P.coverage([], "p1", ["claude_code", "opencode", "pi"])}
    # OpenCode reads agent/*.md subagents and the inventory scans them.
    assert "opencode" in cov["subagent"]["agents_read"]
    assert "opencode" not in cov["subagent"]["agents_unscanned"]
    # Pi reads prompts as commands, but the inventory does not scan them yet: 未扫描, not 未配置.
    assert "pi" in cov["command"]["agents_read"] and cov["command"]["agents_unscanned"] == ["pi"]
    assert cov["skill"]["agents_unscanned"] == []

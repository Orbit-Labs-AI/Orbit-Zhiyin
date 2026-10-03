"""`/v1/recommendations`, labels and outcomes routes on a FastAPI app with a fake gateway."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orbit_backend.appdb import AppDB
from orbit_backend.recommend import inputs as rec_inputs
from orbit_backend.recommend import runs, store
from orbit_backend.services import routes_recommend
from orbit_backend.services.gateway import install_error_handlers
from orbit_backend.services.snapshots import Snapshot, SnapshotKey


def legacy_card(i, kind="skill"):
    return {"resource_id": f"res{i}", "kind": kind, "name": f"Resource {i}",
            "reason": f"why {i}", "summary": "s", "priority_score": 90 - i,
            "compatibility": "compatible", "setup_steps": ["step"],
            "evidence": [{"kind": "tool_call", "session_uid": f"s{i}", "id": "e",
                          "task_uid": None}]}


INPUTS = {"version": "rec-inputs-v1", "signals": [{"signal_id": "x"}],
          "sessions": {"main": 10, "first_ts": 0, "last_ts": 1, "weeks": 1},
          "facts": {"session_days": []},
          "legacy_cards": [legacy_card(0, "hook"), legacy_card(1), legacy_card(2, "mcp"),
                           legacy_card(3, "prompt")]}


class FakeReads:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def read(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
        finally:
            conn.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    orbit = tmp_path / "orbit.db"
    conn = sqlite3.connect(orbit)
    conn.executescript("""
        CREATE TABLE session (session_uid TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE tool_call (session_uid TEXT, name TEXT, command_head TEXT, files TEXT,
                                started_at INTEGER);
        INSERT INTO session VALUES ('s1', '修复登录');
        INSERT INTO tool_call VALUES ('s1','Bash','pytest -q','[]',1),
                                     ('s1','Edit',NULL,'["a.py"]',2),
                                     ('s1','Write',NULL,'[{"path":"b.py"}]',3);""")
    conn.commit()
    conn.close()
    gw = SimpleNamespace(appdb=AppDB(tmp_path / "app.db"), reads=FakeReads(orbit))
    state = {"inputs": dict(INPUTS), "freshness": "fresh"}

    def fetch(gw_, scope_dict, *, wait_ms=0):
        if state["inputs"] is None:
            return None, state["freshness"], "job1" if state["freshness"] == "computing" else None
        from orbit_backend.services.snapshots import scope_hash
        return ({**state["inputs"], "scope": scope_dict,
                 "scope_hash": scope_hash(scope_dict, {}), "data_rev": 1, "inventory_rev": 1},
                state["freshness"], None)

    monkeypatch.setattr(rec_inputs, "fetch", fetch)
    monkeypatch.setattr(runs, "_engine", lambda: (runs.legacy_slate, runs.LEGACY_ENGINE))
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(routes_recommend.router(gw))
    client = TestClient(app)
    yield client, gw, state
    gw.appdb.close()


def test_legacy_list_reuse_and_dims(env):
    client, gw, _ = env
    first = client.get("/v1/recommendations")
    assert first.status_code == 200
    body = first.json()
    assert body["run"]["engine_version"] == "legacy-v1"
    assert body["run"]["freshness"] == "fresh"
    assert [i["rec_key"] for i in body["items"]] == [f"legacy:res{i}" for i in range(4)]
    item = body["items"][0]
    assert item["ui"]["icon"] == "bolt" and item["ui"]["ev"] == "1 个会话"
    assert item["candidate_id"] and item["dim"] == "hook"
    dims = {d["id"]: d["count"] for d in body["dims"]}
    assert dims == {"all": 4, "rule": 1, "skill": 1, "hook": 1, "mcp": 1, "agent": 0,
                    "model": 0, "flow": 0}
    again = client.get("/v1/recommendations")
    assert again.json()["run"]["run_id"] == body["run"]["run_id"]  # same digest reused
    recompute = client.post("/v1/recommendations/recompute", json={"scope": {}})
    assert recompute.json()["reused"] is True
    forced = client.post("/v1/recommendations/recompute", json={"scope": {}, "force": True})
    assert forced.json()["reused"] is False
    assert client.get("/v1/recommendations?dim=skill").json()["items"][0]["dim"] == "skill"
    runs_body = client.get("/v1/recommendations/runs").json()["runs"]
    assert len(runs_body) == 1 and runs_body[0]["n_passed"] == 4  # forced run replaced
    assert runs_body[0]["top"] == ["Resource 0", "Resource 1", "Resource 2"]


def test_label_changes_memory_and_hides(env):
    client, _, _ = env
    items = client.get("/v1/recommendations").json()["items"]
    run_id = items[0]["run_id"]
    target = items[0]["candidate_id"]
    bad = client.post("/v1/labels", json={"target_kind": "candidate", "target_id": target,
                                          "label": "not_applicable"})
    assert bad.status_code == 422
    label = client.post("/v1/labels", json={"target_kind": "candidate", "target_id": target,
                                            "label": "not_applicable",
                                            "reason": "has_equivalent"}).json()
    assert label["effect"]["status"] == "not_applicable"
    body = client.get("/v1/recommendations").json()
    assert body["run"]["run_id"] != run_id  # memory_rev changed -> new run
    assert "legacy:res0" not in [i["rec_key"] for i in body["items"]]
    assert client.delete(f"/v1/labels/{label['label_id']}").json() == {"ok": True}
    assert client.delete("/v1/labels/nope").status_code == 404
    keys = [i["rec_key"] for i in client.get("/v1/recommendations").json()["items"]]
    assert "legacy:res0" in keys
    snooze = client.post("/v1/labels", json={"target_kind": "candidate", "target_id": target,
                                             "label": "snooze"}).json()
    assert snooze["effect"]["hidden_until"] is not None
    missing = client.post("/v1/labels", json={"target_kind": "candidate", "target_id": "x",
                                              "label": "useful"})
    assert missing.status_code == 404


def test_surfaces_use_top_snapshot(env):
    client, gw, _ = env
    menubar = client.get("/v1/recommendations?surface=menubar").json()["items"]
    assert len(menubar) == 1
    a1 = client.get("/v1/recommendations?surface=A1").json()["items"]
    assert [i["rec_key"] for i in a1] == [f"legacy:res{i}" for i in range(3)]
    with gw.appdb.read() as conn:
        top = conn.execute("SELECT run_id FROM rec_top WHERE surface='A1'").fetchone()[0]
    # A new run (exposure changes memory) keeps serving the same A1 snapshot.
    client.post(f"/v1/recommendations/{a1[0]['candidate_id']}/exposure",
                json={"surface": "A1", "position": 0, "action": "view"})
    again = client.get("/v1/recommendations?surface=A1").json()["items"]
    assert [i["candidate_id"] for i in again] == [i["candidate_id"] for i in a1]
    assert again[0]["run_id"] == top


def test_exposures_detail_tracking_outcome(env):
    client, _, _ = env
    items = client.get("/v1/recommendations").json()["items"]
    cid = items[1]["candidate_id"]
    one = client.post(f"/v1/recommendations/{cid}/exposure",
                      json={"surface": "A7", "position": 1, "action": "view"}).json()
    assert one["state"]["shown_count"] == 1
    batch = client.post("/v1/recommendations/exposures", json={"surface": "A7", "items": [
        {"candidate_id": cid, "position": 1, "action": "preview"},
        {"candidate_id": "missing", "position": 2}]}).json()
    assert batch["missing"] == ["missing"]
    assert client.post("/v1/recommendations/missing/exposure",
                       json={"surface": "A7"}).status_code == 404
    assert client.post(f"/v1/recommendations/{cid}/exposure",
                       json={"surface": "nope"}).status_code == 422
    tracking = client.post(f"/v1/recommendations/{cid}/tracking",
                           json={"install_id": "inst-1"}).json()
    assert tracking["tracking_id"]
    detail = client.get(f"/v1/recommendations/{cid}").json()
    assert detail["item"]["rec_key"] == "legacy:res1"
    assert detail["state"]["status"] == "installed"
    assert detail["exposures"]["count"] == 2
    assert detail["outcome"]["effect_status"] == "tracking"
    assert client.get("/v1/recommendations/unknown").status_code == 404
    outcome = client.get("/v1/outcomes/inst-1").json()
    assert outcome["effect_status"] == "tracking" and outcome["windows"] == []
    assert client.get("/v1/outcomes/none").status_code == 404
    metrics = client.get("/v1/recommendations/metrics").json()["rows"]
    assert metrics[0]["group"] == "legacy" and metrics[0]["shown"] == 1
    # Installed items are hidden from the list.
    keys = [i["rec_key"] for i in client.get("/v1/recommendations").json()["items"]]
    assert "legacy:res1" not in keys


def test_detail_mixed_alternatives(env):
    """Alternatives mix kb rec_key strings and slate-folded summaries; detail must not 500 on dicts."""
    client, gw, _ = env
    items = client.get("/v1/recommendations").json()["items"]
    cid, other = items[0]["candidate_id"], items[1]["rec_key"]
    folded = {"rec_key": "kb:folded", "title": "Folded", "kind": "skill", "priority": 2}
    with gw.appdb.write() as conn:
        card = json.loads(conn.execute("SELECT card FROM rec_candidate WHERE candidate_id=?", (cid,)).fetchone()[0])
        card["alternatives"] = [other, folded, {"rec_key": other}, "kb:missing"]
        conn.execute("UPDATE rec_candidate SET card=? WHERE candidate_id=?", (json.dumps(card), cid))
    resp = client.get(f"/v1/recommendations/{cid}")
    assert resp.status_code == 200
    alts = resp.json()["alternatives"]
    assert [a["rec_key"] for a in alts] == [other, "kb:folded", other]
    assert alts[0]["candidate_id"] == items[1]["candidate_id"] and alts[1] == folded


def test_relations_fallback_and_handoff(env):
    client, _, _ = env
    items = client.get("/v1/recommendations").json()["items"]
    ids = "&".join(f"candidate_id={i['candidate_id']}" for i in items[:2])
    pairs = client.get(f"/v1/recommendations/relations?{ids}")
    assert pairs.status_code == 200 and "pairs" in pairs.json()
    assert client.get(f"/v1/recommendations/relations?candidate_id={items[0]['candidate_id']}"
                      ).status_code == 422
    handoff = client.get("/v1/recommendations/handoff/s1").json()
    assert handoff["parts"] == {"task": "修复登录", "recent_files": ["b.py", "a.py"],
                                "verify_pending": True, "last_test_command": "pytest -q"}
    assert handoff["text"].startswith("继续上一个任务：修复登录")
    assert client.get("/v1/recommendations/handoff/zzz").status_code == 404


def test_computing_none_and_stale(env):
    client, _, state = env
    state["inputs"], state["freshness"] = None, "none"
    none = client.get("/v1/recommendations")
    assert none.status_code == 200 and none.json()["meta"]["freshness"] == "none"
    assert client.post("/v1/recommendations/recompute", json={}).status_code == 409
    state["freshness"] = "computing"
    computing = client.get("/v1/recommendations")
    assert computing.status_code == 202
    assert computing.json()["meta"] == {"scope_hash": computing.json()["meta"]["scope_hash"],
                                        "freshness": "computing", "job_id": "job1"}
    assert client.post("/v1/recommendations/recompute", json={}).status_code == 202
    state["inputs"], state["freshness"] = dict(INPUTS), "fresh"
    client.get("/v1/recommendations")
    state["inputs"], state["freshness"] = None, "computing"
    stale = client.get("/v1/recommendations").json()
    assert stale["meta"]["freshness"] == "stale" and stale["items"]
    assert client.post("/v1/recommendations/recompute",
                       json={"scope": {"bogus": 1}}).status_code == 422


def test_engine_slate_stores_gated_and_failure_falls_back(env, monkeypatch):
    client, gw, _ = env

    def build_slate(inputs, memory, *, catalog=None):
        cand = runs.legacy_slate(inputs)["candidates"][0]
        gated = {**cand, "rec_key": "kb:gated", "rank": None,
                 "gates": {"passed": False, "checks": {"installed": False},
                           "reasons": ["已安装等价项"]}}
        return {"engine_version": "rec-engine-v2", "kb_version": "kb1", "catalog_generation": 3,
                "status": "ready", "problems": [{"problem_id": "p"}], "candidates": [cand, gated],
                "routes": {"kb": 1}, "diagnostics": []}

    monkeypatch.setattr(runs, "_engine", lambda: (build_slate, "rec-engine-v2"))
    body = client.get("/v1/recommendations?include_gated=true").json()
    assert body["run"]["kb_version"] == "kb1" and body["problems"] == [{"problem_id": "p"}]
    assert [g["rec_key"] for g in body["gated"]] == ["kb:gated"]
    assert "ui" not in body["gated"][0]
    run_id = body["run"]["run_id"]
    assert client.get("/v1/recommendations").json()["run"]["run_id"] == run_id  # stable digest

    def broken(inputs, memory, *, catalog=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(runs, "_engine", lambda: (broken, "rec-engine-v3"))
    body = client.get("/v1/recommendations").json()
    assert body["run"]["engine_version"] == "legacy-v1" and len(body["items"]) == 4


def test_widget_counts_and_problem_filter(env, monkeypatch):
    client, _, _ = env

    def build_slate(inputs, memory, *, catalog=None):
        cards = runs.legacy_slate(inputs)["candidates"]
        for i, card in enumerate(cards):
            card["problem"] = {"problem_id": "p1" if i < 2 else "p2"}
            card["basis"] = "problem"
        cards[0]["basis"], cards[0]["problem"] = "catalog_only", None  # 资料库推荐 sinks
        return {"engine_version": "rec-engine-v2", "kb_version": "kb1", "catalog_generation": 1,
                "status": "ready", "problems": [], "candidates": cards, "routes": {},
                "diagnostics": []}

    monkeypatch.setattr(runs, "_engine", lambda: (build_slate, "rec-engine-v2"))
    body = client.get("/v1/recommendations").json()
    assert body["items"][-1]["basis"] == "catalog_only"
    assert body["counts"]["dim"] == {"hook": 1, "skill": 1, "mcp": 1, "rule": 1}
    assert body["counts"]["library"] == 1 and sum(body["counts"]["kind"].values()) == 4
    assert body["counts"]["state"] == {"pending": 4, "installed": 0, "not_applicable": 0,
                                       "snoozed": 0}
    widget = client.get("/v1/recommendations?surface=widget").json()["items"]
    assert len(widget) == 1 and widget[0]["basis"] != "catalog_only"
    only = client.get("/v1/recommendations?problem_id=p2").json()["items"]
    assert len(only) == 2 and {i["problem"]["problem_id"] for i in only} == {"p2"}
    assert len(client.get("/v1/recommendations?problem_id=p1&problem_id=p2").json()["items"]) == 3
    label = client.post("/v1/labels", json={"target_kind": "candidate", "target_id": only[0][
        "candidate_id"], "label": "not_applicable", "reason": "other"})
    assert label.status_code == 200
    assert client.get("/v1/recommendations").json()["counts"]["state"]["not_applicable"] == 1


def test_detail_with_folded_alternatives(env, monkeypatch):
    """R1: slate folding stores alternatives as dict stubs; detail must not 500 on them."""
    client, _, _ = env

    def build_slate(inputs, memory, *, catalog=None):
        cards = runs.legacy_slate(inputs)["candidates"]
        cards[0]["alternatives"] = [
            {"rec_key": cards[3]["rec_key"], "title": "Resource 3", "kind": "prompt",
             "priority": 1}, "kb:not-in-run", cards[1]["rec_key"]]
        cards[3]["excluded"] = f"folded:{cards[0]['rec_key']}"
        return {"engine_version": "rec-engine-v2", "kb_version": "kb1", "catalog_generation": 1,
                "status": "ready", "problems": [], "candidates": cards, "routes": {},
                "diagnostics": []}

    monkeypatch.setattr(runs, "_engine", lambda: (build_slate, "rec-engine-v2"))
    first = client.get("/v1/recommendations").json()["items"][0]
    resp = client.get(f"/v1/recommendations/{first['candidate_id']}")
    assert resp.status_code == 200, resp.text
    alts = resp.json()["alternatives"]
    assert [a["rec_key"] for a in alts] == ["legacy:res3", "legacy:res1"]
    assert all(a["candidate_id"] for a in alts)


def test_concurrent_runs_coalesce(env):
    client, gw, _ = env
    results = []

    def call():
        results.append(client.get("/v1/recommendations").json()["run"]["run_id"])

    threads = [threading.Thread(target=call) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(results)) == 1


class FakeTask:
    def __init__(self, status="queued"):
        self.id, self.status = "job9", status
        self.done = threading.Event()


def test_inputs_fetch_states():
    from orbit_backend.services.sections import rules_digest
    from orbit_backend.services.snapshots import scope_hash

    h = scope_hash({}, {})
    key = SnapshotKey("recommend_inputs", h, 2, 1, rules_digest())
    snapshots = {}
    old = Snapshot(SnapshotKey("recommend_inputs", h, 1, 1, rules_digest()), {"v": "old"}, 0, 0)
    revision = {"data_rev": 2, "inventory_rev": 1}
    gw = SimpleNamespace(
        revisions=SimpleNamespace(snapshot=lambda: revision),
        snapshots=SimpleNamespace(get=lambda k: snapshots.get(k),
                                  latest=lambda *a: snapshots.get("latest")),
        supervisor=SimpleNamespace(analysis=SimpleNamespace(submit=lambda *a: FakeTask())))
    assert rec_inputs.fetch(gw, {}) == (None, "computing", "job9")
    snapshots["latest"] = old
    data, freshness, job = rec_inputs.fetch(gw, {})
    assert (data["v"], freshness, job, data["data_rev"]) == ("old", "stale", "job9", 1)
    snapshots[key] = Snapshot(key, {"v": "new"}, 0, 0)
    data, freshness, _ = rec_inputs.fetch(gw, {})
    assert (data["v"], data["scope_hash"], freshness) == ("new", h, "fresh")
    revision["data_rev"] = None
    assert rec_inputs.fetch(gw, {}) == (None, "none", None)


def test_real_gateway_wiring(tmp_path):
    from orbit_backend.services.gateway import Gateway

    token = "synthetic-test-token-0123456789abcdef"
    gateway = Gateway(tmp_path / "home", discovery=lambda: [], prewarm_debounce_s=3600.0)
    app = gateway.app(token=token, port=8765)
    with TestClient(app, base_url="http://127.0.0.1:8765",
                    headers={"Authorization": f"Bearer {token}"}) as client:
        body = client.get("/v1/recommendations").json()
        assert body["meta"]["freshness"] == "none" and body["items"] == []
        assert client.post("/v1/recommendations/recompute", json={}).status_code == 409
        assert client.get("/v1/recommendations/metrics").json() == {"rows": []}


def _engine_slate(inputs, memory, *, catalog=None, **kw):
    slate = runs.legacy_slate(inputs)
    slate["engine_version"], slate["diagnostics"] = "rec-engine-v2", []
    slate["candidates"].append({**slate["candidates"][0], "rec_key": "generate:rule:x", "rank": None,
                                "generate": {"task_id": "generate.rule", "template_id": "blank@1"}})
    slate["seen"] = {"settings": memory["settings"], "catalog": catalog, **kw}
    return slate


def test_settings_from_platform_and_ai_rerank(env, monkeypatch):
    from orbit_backend import ai
    from orbit_backend.platform.settings import PlatformSettings

    client, gw, _ = env
    gw.platform = SimpleNamespace(settings=PlatformSettings(gw.appdb))
    seen = {}

    def build(inputs, memory, **kw):
        slate = _engine_slate(inputs, memory, **kw)
        seen.update(slate.pop("seen"))
        return slate

    monkeypatch.setattr(runs, "_engine", lambda: (build, "rec-engine-v2"))
    calls = []

    class FakeAI:
        def __init__(self, mode):
            self.mode = mode

        def run(self, task_id, slots=None, scope=None, timeout=60):
            calls.append((task_id, [c["candidate_id"] for c in slots["candidates"]]))
            ids = [c["candidate_id"] for c in slots["candidates"]]
            return {"status": "ok", "job_id": "j1", "result": {
                "order": ids[::-1], "items": [{"candidate_id": ids[-1], "fit": "fits",
                                               "explain": "e", "reasons": []}]}}

    fake = FakeAI("stats")
    monkeypatch.setattr(ai, "service", lambda gw_: fake)
    monkeypatch.setattr(runs, "ai_enabled", lambda gw_: fake.mode != "stats")
    assert client.get("/v1/recommendations/settings").json() == {
        "ai_generate": False, "level": None, "ai_available": False}
    assert client.put("/v1/recommendations/settings",
                      json={"ai_generate": True}).json()["ai_generate"] is True
    client.get("/v1/recommendations")
    assert seen["settings"] == {"ai_generate": False} and not calls  # consent mode=stats
    fake.mode = "agent"
    body = client.get("/v1/recommendations").json()  # AI flip keys a new run
    assert seen["settings"] == {"ai_generate": True}
    assert calls == [("rerank.fit", [f"legacy:res{i}" for i in range(4)])]
    assert [i["rec_key"] for i in body["items"]] == [*(f"legacy:res{i}" for i in (3, 2, 1, 0)),
                                                     "generate:rule:x"]  # unranked last
    assert body["items"][0]["ai_fit"]["fit"] == "fits" and body["items"][0]["rank"] == 4
    gen = next(i for i in client.get("/v1/recommendations?limit=50").json()["items"]
               if i["rec_key"] == "generate:rule:x")
    assert gen["generate"]["available"] is True

    def unavailable(*a, **kw):
        raise ai.AIUnavailable("consent_required")

    fake.run = unavailable
    body = client.post("/v1/recommendations/recompute", json={"scope": {}, "force": True}).json()
    with gw.appdb.read() as conn:
        diags = store.get_run(conn, body["run_id"])["diagnostics"]
    assert {"source": "rerank.fit", "status": "unavailable", "reason": "consent_required"} in diags


def test_views_do_not_rerun_engine(env):
    client, _, _ = env
    items = client.get("/v1/recommendations").json()["items"]
    run_id = items[0]["run_id"]
    for item in items:
        client.post(f"/v1/recommendations/{item['candidate_id']}/exposure",
                    json={"surface": "A7", "action": "view"})
    assert client.get("/v1/recommendations").json()["run"]["run_id"] == run_id


def test_catalog_service_and_features_passed(env, monkeypatch, tmp_path):
    from orbit_backend import features

    client, gw, _ = env
    gw.home = tmp_path / "home"
    gw.home.mkdir()
    assert runs.catalog_service(gw) is None  # no catalog.db yet
    seen = {}

    def build(inputs, memory, **kw):
        slate = _engine_slate(inputs, memory, **kw)
        seen.update(slate.pop("seen"))
        return slate

    monkeypatch.setattr(runs, "_engine", lambda: (build, "rec-engine-v2"))
    monkeypatch.setattr(features, "_service", object())
    client.get("/v1/recommendations")
    assert seen["features"] is features and seen["catalog"] is None


def test_catalog_service_from_home_and_generation(env, tmp_path):
    from orbit_catalog.service import CatalogService

    _, gw, _ = env
    gw.home = tmp_path / "home2"
    gw.home.mkdir()
    CatalogService(gw.home / "catalog.db")  # empty catalog on disk
    svc = runs.catalog_service(gw)
    assert svc is not None and runs.catalog_service(gw) is svc  # cached on gw
    generation, items = runs._catalog_state(svc)
    assert isinstance(generation, int) and items == 0  # empty → run uses the seed fallback


class _FakeCatalogStore:
    """catalog.db with a non-zero generation and active items (synthetic)."""

    def __init__(self, path, generation):
        self.path = path
        conn = sqlite3.connect(path)
        conn.executescript("CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT);"
                           "CREATE TABLE catalog_item (item_id TEXT, status TEXT);"
                           "INSERT INTO catalog_item VALUES ('syn-a','active'),('syn-b','active');")
        conn.execute("INSERT INTO catalog_meta VALUES ('generation', ?)", (str(generation),))
        conn.commit()
        conn.close()

    @contextmanager
    def connect(self, readonly=False):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
        finally:
            conn.close()


@pytest.mark.parametrize("reported", [None, 6, "7"])
def test_repeat_get_reuses_run_with_live_catalog(env, monkeypatch, tmp_path, reported):
    """The slate's catalog generation (absent when no catalog.match answered, or a lagging
    index snapshot) must not key the run: the lookup uses catalog_meta, so must the store."""
    client, gw, _ = env
    gw.catalog = SimpleNamespace(store=_FakeCatalogStore(tmp_path / "cat.db", 7))

    def build(inputs, memory, *, catalog=None, **kw):
        assert catalog is gw.catalog
        slate = runs.legacy_slate(inputs)
        slate.update(engine_version="rec-engine-v2", kb_version="kb-syn@1",
                     catalog_generation=reported, diagnostics=[])
        return slate

    monkeypatch.setattr(runs, "_engine", lambda: (build, "rec-engine-v2"))
    first = runs.run(gw, {})
    second = runs.run(gw, {})
    assert first["reused"] is False and second["reused"] is True
    assert second["run_id"] == first["run_id"]
    with gw.appdb.read() as conn:
        assert store.get_run(conn, first["run_id"])["catalog_generation"] == 7
    ids = [i["candidate_id"] for i in client.get("/v1/recommendations").json()["items"]]
    client.get("/v1/recommendations/runs")
    client.get("/v1/recommendations?surface=A1")
    assert [i["candidate_id"] for i in client.get("/v1/recommendations").json()["items"]] == ids
    assert len(client.get("/v1/recommendations/runs").json()["runs"]) == 1


@pytest.mark.parametrize(("surface", "expected"), [("A7", 12), ("A1", 3), ("lite", 3), ("menubar", 1),
                                                   ("widget", 1), ("palette", 10), ("ask", 5), ("hud", 1)])
def test_surface_default_limits(env, surface, expected):
    client, _, state = env
    state["inputs"] = {**INPUTS, "legacy_cards": [legacy_card(i) for i in range(12)]}
    items = client.get(f"/v1/recommendations?surface={surface}").json()["items"]
    assert len(items) == expected
    assert routes_recommend.SURFACE_LIMIT is runs.SURFACE_LIMIT


def test_top_surfaces_apply_dim_filter(env):
    client, _, _ = env
    assert client.get("/v1/recommendations?surface=menubar").json()["items"][0]["dim"] == "hook"
    only = client.get("/v1/recommendations?surface=menubar&dim=mcp").json()["items"]
    assert len(only) == 1 and only[0]["dim"] == "mcp"
    # the cached unfiltered top is unaffected by the filtered request
    assert client.get("/v1/recommendations?surface=menubar").json()["items"][0]["dim"] == "hook"


def test_scope_whitelist_matches_analytics_scope():
    import inspect

    from orbit_backend.services.routes_analytics import analytics_scope

    assert routes_recommend.SCOPE_KEYS == set(inspect.signature(analytics_scope).parameters)


def test_recommendation_level_change_invalidates_cached_run(env, monkeypatch):
    client, gw, _ = env
    monkeypatch.setattr(runs, "_engine", lambda: (_engine_slate, "rec-level-cache-test"))
    gw.rec_settings = {"level": 1}
    first = runs.run(gw, {})
    assert runs.run(gw, {})["reused"]
    gw.rec_settings = {"level": 3}
    changed = runs.run(gw, {})
    assert not changed["reused"] and changed["run_id"] != first["run_id"]


def test_funnel_survives_card_retention_and_reports_legacy_unknown(env, monkeypatch):
    from orbit_backend.recommend.funnel import Funnel

    client, gw, _ = env
    old = runs.run(gw, {})
    legacy = client.get(f"/v1/recommendations/runs/{old['run_id']}/funnel").json()
    assert legacy["status"] == "not_recorded" and legacy["funnel"] is None

    def build(inputs, memory, **kw):
        slate = _engine_slate(inputs, memory, **kw)
        audit = Funnel(inputs, [], {})
        for cand in slate["candidates"]:
            cand["evidence"] = {"session_uids": ["evidence-session"]}
        audit.record("raw_candidates", ((c, True, []) for c in slate["candidates"]))
        slate["funnel"] = audit.export()
        return slate

    monkeypatch.setattr(runs, "_engine", lambda: (build, "funnel-test"))
    monkeypatch.setattr(runs, "KEEP_PASSED", 1)
    new = runs.run(gw, {}, force=True)
    response = client.get(f"/v1/recommendations/runs/{new['run_id']}/funnel")
    assert response.status_code == 200
    audit = response.json()["funnel"]
    assert len(audit["candidates"]) == 5
    assert audit["candidates"]["legacy:res1"]["evidence"]["session_uids"] == ["evidence-session"]
    serial = audit["stages"][-1]
    assert serial["stage"] == "serialization" and serial["kept_count"] == 1
    assert serial["rejected_count"] == 4
    assert all(d["reasons"] == ["persistence_cap"] for d in serial["decisions"] if not d["kept"])
    assert client.get("/v1/recommendations/runs/missing/funnel").status_code == 404

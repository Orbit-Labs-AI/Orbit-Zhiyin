"""`/v1/uiview/*` handlers over a stub gateway: fresh / stale / computing, ETag, 422."""

import json
import threading
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tandem_backend.services import routes_uiview
from tandem_backend.services.gateway import install_error_handlers
from tandem_backend.services.sections import rules_digest
from tandem_backend.services.snapshots import SnapshotKey, SnapshotStore, scope_hash
from tandem_backend.uiview import facts, fetch

from .synth import TODAY, analysed


class Analysis:
    def __init__(self):
        self.calls = []

    def submit(self, section, scope, params, h, priority, revs, rules):
        self.calls.append((section, h, priority, revs))
        done = threading.Event()
        done.set()
        return SimpleNamespace(id=f"job-{len(self.calls)}", status="queued", done=done)


class Revisions:
    def __init__(self):
        self.data_rev = 3

    def snapshot(self):
        return {"data_rev": self.data_rev, "inventory_rev": 1}


@pytest.fixture()
def gw():
    gateway = SimpleNamespace(revisions=Revisions(), snapshots=SnapshotStore(None),
                              supervisor=SimpleNamespace(analysis=Analysis()), realtime=None)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(routes_uiview.router(gateway))
    gateway.client = TestClient(app)
    gateway.h = scope_hash(asdict(routes_uiview.facts_scope()), {})
    return gateway


def put(gw, data_rev=3):
    key = SnapshotKey(fetch.SECTION, gw.h, data_rev, 1, rules_digest())
    gw.snapshots.put(key, json.loads(json.dumps(analysed()[4])))


def test_computing_then_fresh_with_etag(gw):
    r = gw.client.get("/v1/uiview/facts")
    assert r.status_code == 202 and r.json()["meta"]["freshness"] == "computing"
    assert gw.supervisor.analysis.calls[0][0] == "uiview_facts"
    put(gw)
    r = gw.client.get("/v1/uiview/facts", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["freshness"] == "fresh" and body["meta"]["data_rev"] == 3
    assert len(facts.expand(body)) == 150
    tag = r.headers["etag"]
    assert gw.client.get("/v1/uiview/facts", headers={"If-None-Match": tag}).status_code == 304


def test_stale_after_new_revision(gw):
    put(gw)
    gw.revisions.data_rev = 4
    r = gw.client.get("/v1/uiview/overview", params={"range": 30, "today": TODAY.isoformat()})
    assert r.status_code == 200
    assert r.json()["meta"]["freshness"] == "stale" and r.json()["meta"]["job_id"]
    facts_r = gw.client.get("/v1/uiview/facts")
    assert facts_r.json()["meta"]["freshness"] == "stale" and "etag" not in facts_r.headers


def test_gzip_when_accepted(gw):
    put(gw)
    r = gw.client.get("/v1/uiview/facts", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert len(r.json()["rows"]) == 150  # the client decodes transparently


def test_overview_and_persona_payloads(gw):
    put(gw)
    common = {"today": TODAY.isoformat()}
    ov = gw.client.get("/v1/uiview/overview", params={**common, "range": 0,
                                                       "agents": "codex", "compare": 1,
                                                       "edition": "lite", "metric": "h"}).json()
    assert ov["header"]["n"] == 90 and ov["strip"] and ov["trend"]["metric"] == "h"
    p = gw.client.get("/v1/uiview/persona", params={**common, "period": "all"}).json()
    assert p["ok"] and p["n"] == 150 and p["meta"]["freshness"] == "fresh"
    rv = gw.client.get("/v1/uiview/persona/reveal", params={**common, "period": "sep"}).json()
    assert rv["code"] == gw.client.get("/v1/uiview/persona",
                                       params={**common, "period": "sep"}).json()["code"]


@pytest.mark.parametrize("path,params", [
    ("/v1/uiview/overview", {"range": 5}),
    ("/v1/uiview/overview", {"metric": "cost"}),
    ("/v1/uiview/overview", {"hour": 24}),
    ("/v1/uiview/overview", {"from_ts": 10, "until_ts": 5}),
    ("/v1/uiview/persona", {"period": "fortnight"}),
    ("/v1/uiview/persona", {"period": "90", "today": "not-a-day"}),
])
def test_invalid_parameters_are_422(gw, path, params):
    put(gw)
    assert gw.client.get(path, params=params).status_code == 422

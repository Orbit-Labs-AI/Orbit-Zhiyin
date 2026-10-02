"""EV-04.1 (zero-annotation part): facet.session output quality over a scripted FakeEngine.

Ten synthetic sessions in a tiny tandem.db go through the real AIService and facet.session task.
Good outputs must all validate and store; broken outputs (missing field, wrong enum, evidence id
not in the pack) must never be stored as written; a second run with unchanged input must not call
the engine again.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

from ..contract import Check, EvalContext, SuiteResult

ID = "facet_quality"
TITLE = "Facet quality without annotations"
EV = ("EV-04.1",)

GOOD = [f"good-{i:02d}" for i in range(10)]
BROKEN = {"bad-missing": "missing_field", "bad-enum": "wrong_enum", "bad-evidence": "foreign_evidence"}
FOREIGN = "event-not-in-pack"
SCHEMA = """
CREATE TABLE project(project_id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE session(session_uid TEXT PRIMARY KEY, kind TEXT, project_id TEXT, cwd TEXT, title TEXT,
  client TEXT, started_at INTEGER, ended_at INTEGER, status TEXT, native_id TEXT);
CREATE TABLE event(event_uid TEXT PRIMARY KEY, session_uid TEXT, kind TEXT, actor TEXT, seq INTEGER,
  ts INTEGER, text TEXT, origin TEXT);
CREATE VIEW v_human_message AS SELECT * FROM event WHERE kind='message.user' AND origin='human';
CREATE TABLE tool_call(call_uid TEXT PRIMARY KEY, session_uid TEXT, name TEXT, status TEXT,
  error_class TEXT, started_at INTEGER);
"""


def _tandem_db(path) -> None:
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.execute("INSERT INTO project VALUES ('p1', 'alpha')")
    start = 1_700_000_000_000
    for n, uid in enumerate(GOOD + list(BROKEN)):
        t0 = start + n * 3_600_000
        db.execute("INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (uid, "main", "p1", "/w", f"task {n}", "codex", t0, t0 + 600_000, "completed",
                    f"native-{n}"))
        texts = ["add a retry to the upload job", "不对，应该用 uv 运行测试", "thanks, ship it"]
        for i, text in enumerate(texts):
            db.execute("INSERT INTO event VALUES (?,?,?,?,?,?,?,?)",
                       (f"{uid}-h{i}", uid, "message.user", "human", 2 * i, t0 + i * 1000, text,
                        "human"))
            db.execute("INSERT INTO event VALUES (?,?,?,?,?,?,?,?)",
                       (f"{uid}-a{i}", uid, "message.assistant", "assistant", 2 * i + 1,
                        t0 + i * 1000 + 500, "done", None))
        db.execute("INSERT INTO tool_call VALUES (?,?,?,?,?,?)",
                   (f"{uid}-c0", uid, "shell", "failed" if n % 3 == 0 else "success",
                    "exit_nonzero" if n % 3 == 0 else None, t0 + 100))
    db.commit()
    db.close()


def _facet(uid: str, item: dict) -> dict:
    cands = [{"signal_id": c["signal_id"], "event_uid": c["event_uid"], "is_correction": True,
              "feedback_kind": "correct", "friction_type": "wrong_approach", "confidence": "high"}
             for c in item.get("candidates") or []]
    out = {"session_uid": uid, "goal": "add retry", "task_type": "bugfix",
           "outcome": "mostly_achieved",
           "friction_types": ["wrong_approach"] if cands else [], "candidates": cands,
           "repeated_instructions": [], "summary": "retry added", "chunked": False}
    kind = BROKEN.get(uid)
    if kind == "missing_field":
        del out["outcome"]
    elif kind == "wrong_enum":
        out["task_type"] = "debugging"
    elif kind == "foreign_evidence":
        out["candidates"].append({**cands[0], "signal_id": "sig:" + FOREIGN, "event_uid": FOREIGN,
                                  "friction_type": "none"})
    return out


def _script(request) -> dict:
    body = request.prompt.split("<sessions>\n", 1)[1].split("\n</sessions>", 1)[0]
    items = [json.loads(line) for line in body.splitlines()]
    return {"items": [_facet(i["ref_id"], i) for i in items]}


def run(ctx: EvalContext) -> SuiteResult:
    try:
        from ...ai.engines import FakeEngine  # noqa: PLC0415
        from ...ai.service import AIService  # noqa: PLC0415
        from ...appdb import AppDB  # noqa: PLC0415
        from ...services.events import EventBus  # noqa: PLC0415
    except ImportError as error:
        return SuiteResult(ID, skipped=f"ai service unavailable: {error}")
    root = ctx.tmp / "facet_quality"
    root.mkdir(parents=True, exist_ok=True)
    tandem_db = root / "tandem.db"
    _tandem_db(tandem_db)

    @contextmanager
    def read():
        conn = sqlite3.connect(tandem_db.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    gw = SimpleNamespace(home=root / "tandem", appdb=AppDB(root / "tandem" / "app.db"),
                         bus=EventBus(), reads=SimpleNamespace(read=read))
    svc = AIService(gw)
    try:
        svc._engines.clear()  # never probe the real claude / codex binaries
        engine = FakeEngine({"facet.session": _script})
        svc.register_engine("fake", engine)
        svc.set_consent({"mode": "agent", "default_engine": "fake",
                         "grants": {"fake": {"summary": True, "snippets": True}}})
        return _measure(svc, engine, read)
    finally:
        svc.close()
        gw.appdb.close()


def _job(svc, uids: list[str]) -> dict:
    sub = svc.submit("facet.session", {"engine": "fake", "params": {"session_uids": uids}},
                     waiter=True, skip_preview=True)
    done = svc.runner.done.get(sub["job_id"])
    if done is not None:
        done.wait(10)
    return svc.job(sub["job_id"])


def _facets(svc, uids) -> dict[str, dict]:
    with svc.appdb.read() as db:
        rows = db.execute(f"SELECT session_uid, status, json FROM ai_facet WHERE session_uid IN "
                          f"({','.join('?' * len(uids))})", list(uids)).fetchall()
    return {r["session_uid"]: {"status": r["status"], "json": r["json"] and json.loads(r["json"])}
            for r in rows}


def _measure(svc, engine, read) -> SuiteResult:
    checks: list[Check] = []
    job = _job(svc, GOOD)
    stored = _facets(svc, GOOD)
    ok = [u for u in GOOD if stored.get(u, {}).get("status") == "ok"]
    validity = len(ok) / len(GOOD)
    failed_rate = 1 - validity
    checks.append(Check("facet.schema_validity", validity == 1.0, value=validity, threshold=1.0,
                        detail=f"job {job['status']}"))
    checks.append(Check("facet.failed_rate", failed_rate <= 0.1, value=failed_rate, threshold=0.1))

    with read() as db:
        events = {r[0] for r in db.execute("SELECT event_uid FROM event")}
    refs = [c for f in stored.values() if f["json"] for c in f["json"]["candidates"]]
    bad = [c["event_uid"] for c in refs
           if c["event_uid"] not in events or c["signal_id"] != "sig:" + c["event_uid"]]
    rate = len(bad) / len(refs) if refs else 0.0
    checks.append(Check("facet.hallucination_rate", bool(refs) and not bad, value=rate,
                        threshold=0.0, detail=", ".join(bad)))

    calls = len(engine.requests)
    again = _job(svc, GOOD)
    extra = len(engine.requests) - calls
    checks.append(Check("facet.repeat_cached", extra == 0 and again["status"] == "ok",
                        value=extra, threshold=0))

    for uid in BROKEN:  # one job each: a schema-invalid item fails its whole batch call
        _job(svc, [uid])
    broken = _facets(svc, list(BROKEN))
    for uid, kind in BROKEN.items():
        row = broken.get(uid) or {}
        if kind == "foreign_evidence":  # dropped from the facet, or the facet failed
            cands = (row.get("json") or {}).get("candidates") or []
            passed = all(c["event_uid"] != FOREIGN for c in cands)
        else:
            passed = row.get("status") == "failed" and row.get("json") is None
        checks.append(Check(f"facet.broken.{kind}", passed, detail=json.dumps(row)[:200]))
    return SuiteResult(ID, checks, metrics={"sessions": len(GOOD), "validity": validity,
                                            "failed_rate": failed_rate, "hallucination_rate": rate,
                                            "engine_calls": len(engine.requests)})

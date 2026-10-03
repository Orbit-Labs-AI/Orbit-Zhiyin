"""Eval run history in app.db (``appdb/schema/eval.sql``).

Functions take an AppDB-like object (anything with ``write()`` / ``read()`` context
managers), so the gateway passes ``gw.appdb`` and the CLI a standalone ``AppDB``.
"""

from __future__ import annotations

import json

from . import registry

KEEP_RUNS = 200


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def queue(db, run_id: str, suites: list[str], fail_under: float | None, params: dict,
          now: int, status: str = "queued") -> None:
    """Insert (or restart) a run row; also prunes history beyond the newest 200 runs."""
    with db.write() as conn:
        conn.execute("INSERT INTO eval_run (run_id, started_at, status, suites, fail_under, params) "
                     "VALUES (?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
                     "started_at=excluded.started_at, status=excluded.status",
                     (run_id, now, status, _dumps(suites), fail_under, _dumps(params or {})))
        prune(conn)


def finish(db, report: dict) -> None:
    summary = {"suites": [{k: s.get(k) for k in ("suite", "kind", "skipped", "score", "metrics")}
                          for s in report["suites"]]}
    with db.write() as conn:
        conn.execute("UPDATE eval_run SET finished_at=?, status=?, score=?, passed=?, summary=? "
                     "WHERE run_id=?",
                     (report["finished_at"], report["status"], report["score"],
                      int(report["passed"]), _dumps(summary), report["run_id"]))
        conn.execute("DELETE FROM eval_check WHERE run_id=?", (report["run_id"],))
        conn.executemany(
            "INSERT OR REPLACE INTO eval_check VALUES (?,?,?,?,?,?,?)",
            [(report["run_id"], s["suite"], c["id"], int(c["passed"]), c["value"], c["threshold"],
              c["detail"] or "") for s in report["suites"] for c in s["checks"]])


def fail(db, run_id: str, error: str, now: int) -> None:
    with db.write() as conn:
        conn.execute("UPDATE eval_run SET finished_at=?, status='failed', passed=0, summary=? "
                     "WHERE run_id=?", (now, _dumps({"error": error, "suites": []}), run_id))


def prune(conn, keep: int | None = None) -> int:
    keep = keep or KEEP_RUNS
    gone = conn.execute("DELETE FROM eval_run WHERE run_id NOT IN (SELECT run_id FROM eval_run "
                        "ORDER BY started_at DESC, rowid DESC LIMIT ?)", (keep,)).rowcount
    if gone:
        conn.execute("DELETE FROM eval_check WHERE run_id NOT IN (SELECT run_id FROM eval_run)")
    return gone


def _brief(row) -> dict:
    return {"run_id": row["run_id"], "started_at": row["started_at"],
            "finished_at": row["finished_at"], "status": row["status"],
            "passed": None if row["passed"] is None else bool(row["passed"]),
            "score": row["score"], "fail_under": row["fail_under"],
            "suites": json.loads(row["suites"])}


def list_runs(db, limit: int = 20) -> list[dict]:
    with db.read() as conn:
        rows = conn.execute("SELECT * FROM eval_run ORDER BY started_at DESC, rowid DESC LIMIT ?",
                            (limit,)).fetchall()
    return [_brief(r) for r in rows]


def get_run(db, run_id: str) -> dict | None:
    """The RunReport shape; suites carry their checks once the run has finished."""
    with db.read() as conn:
        row = conn.execute("SELECT * FROM eval_run WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        checks = conn.execute("SELECT suite, check_id, passed, value, threshold, detail FROM "
                              "eval_check WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
    report = _brief(row)
    summary = json.loads(row["summary"]) if row["summary"] else {}
    by_suite: dict[str, list[dict]] = {}
    for c in checks:
        by_suite.setdefault(c["suite"], []).append(
            {"id": c["check_id"], "passed": bool(c["passed"]), "value": c["value"],
             "threshold": c["threshold"], "detail": c["detail"]})
    # Runs stored before suites carried a kind get it from the registry table.
    report["suites"] = [{**s, "kind": s.get("kind") or registry.kind(s["suite"]),
                         "checks": by_suite.get(s["suite"], [])}
                        for s in summary.get("suites") or []] or \
                       [{"suite": s, "kind": registry.kind(s), "skipped": None, "score": None,
                         "checks": [], "metrics": {}}
                        for s in report["suites"]]
    if summary.get("error"):
        report["error"] = summary["error"]
    report["params"] = json.loads(row["params"])
    return report

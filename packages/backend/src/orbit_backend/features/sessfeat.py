"""Materialize per-session vocabulary features into app.db ``sess_feat``.

Inputs are ``t.session_feature`` (mapped through the vocabulary) plus features
``orbit.db`` does not keep: error classes, project path markers and friction counts
derived from ``t.tool_call``. Only sessions whose signature
``ended_at|tool_calls|vocab`` changed are recomputed.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict

from .vocab import (
    PATH_MARKERS,
    VOCAB_VERSION,
    command_info,
    from_session_feature,
    norm,
    path_markers,
)

DATA_REV_KEY = "__data_rev__"
FAILED = "(tc.status IN ('error','failed') OR COALESCE(tc.exit_code, 0) <> 0)"
MARKER_LIKE = " OR ".join(["j.value LIKE ?"] * len(PATH_MARKERS))
MARKER_PARAMS = ["%" + p.replace("*", "%") + ("%" if p.startswith("*") else "")
                 for p in PATH_MARKERS]


def _signatures(db) -> dict[str, str]:
    rows = db.execute(
        "SELECT s.session_uid, s.ended_at, COALESCE(c.n, 0) FROM t.session s "
        "LEFT JOIN (SELECT session_uid, COUNT(*) n FROM t.tool_call GROUP BY session_uid) c "
        "USING(session_uid)").fetchall()
    return {uid: f"{ended}|{n}|{VOCAB_VERSION}" for uid, ended, n in rows}


def _batch_queries(uids: list[str]) -> dict:
    marks = ",".join("?" * len(uids))
    where = f"tc.session_uid IN ({marks})"

    def rows(sql: str, extra: list | None = None):
        return lambda db: db.execute(sql, [*uids, *(extra or [])]).fetchall()

    return {
        "base": rows(f"SELECT session_uid, feature, value, n FROM t.session_feature "
                     f"WHERE session_uid IN ({marks})"),
        "heads": rows(f"SELECT tc.session_uid, tc.command_head, COUNT(*), "
                      f"SUM(COALESCE(tc.approval_wait_ms, 0) > 0) FROM t.tool_call tc "
                      f"WHERE {where} AND tc.command_head IS NOT NULL GROUP BY 1, 2"),
        "friction": rows(f"SELECT tc.session_uid, SUM({FAILED}), "
                         f"SUM(COALESCE(tc.approval_wait_ms, 0) > 0), "
                         f"SUM(COALESCE(tc.duration_ms, 0) > 60000) FROM t.tool_call tc "
                         f"WHERE {where} GROUP BY 1"),
        "errors": rows(f"SELECT tc.session_uid, tc.error_class, COUNT(*) FROM t.tool_call tc "
                       f"WHERE {where} AND tc.error_class IS NOT NULL GROUP BY 1, 2"),
        "retry": rows(f"SELECT session_uid, SUM(failed AND prev) FROM (SELECT tc.session_uid, "
                      f"{FAILED} failed, LAG({FAILED}) OVER (PARTITION BY tc.session_uid, "
                      f"tc.name_raw, tc.command_head ORDER BY tc.started_at) prev "
                      f"FROM t.tool_call tc WHERE {where}) GROUP BY 1"),
        "markers": rows(f"SELECT tc.session_uid, j.value FROM t.tool_call tc, "
                        f"json_each(tc.files) j WHERE {where} AND tc.files <> '[]' "
                        f"AND ({MARKER_LIKE})", MARKER_PARAMS),
    }


def compute(hub, uids: list[str]) -> dict[str, Counter]:
    """``{session_uid: Counter(fid name -> n)}`` for the given sessions (parallel reads)."""
    out: dict[str, Counter] = defaultdict(Counter)
    results = hub.gather(**_batch_queries(uids))
    for value in results.values():
        if isinstance(value, Exception):
            raise value
    for uid, feature, value, n in results["base"]:
        for fid in from_session_feature(feature, value):
            out[uid][fid] += n
    for uid, head, n, waited in results["heads"]:
        cls = command_info(head)["cls"]
        if cls == "destructive":
            out[uid]["friction:destructive_cmd"] += n
        if cls == "readonly" and waited:
            out[uid]["friction:readonly_prompted"] += waited
    for uid, failed, waited, long_wait in results["friction"]:
        for fid, n in (("friction:tool_error", failed), ("friction:approval_wait", waited),
                       ("friction:long_tool_wait", long_wait)):
            if n:
                out[uid][fid] += n
    for uid, error_class, n in results["errors"]:
        out[uid][f"err:{norm(error_class)}"] += n
    for uid, n in results["retry"]:
        if n:
            out[uid]["friction:retry_same_call"] += n
    for uid, path in results["markers"]:
        for fid in path_markers(path):
            out[uid][fid] += 1
    return out


def _fids(db, names: set[str], cache: dict[str, int]) -> dict[str, int]:
    missing = [name for name in names if name not in cache]
    found = dict(cache)
    if missing:
        db.executemany("INSERT OR IGNORE INTO feat_vocab(name) VALUES (?)",
                       [(name,) for name in missing])
        for i in range(0, len(missing), 500):
            part = missing[i:i + 500]
            found.update(db.execute(
                f"SELECT name, fid FROM feat_vocab WHERE name IN ({','.join('?' * len(part))})",
                part).fetchall())
    return found


def data_rev_seen(svc) -> int | None:
    with svc.hub.read() as db:
        row = db.execute("SELECT sig FROM sess_feat_state WHERE session_uid = ?",
                         (DATA_REV_KEY,)).fetchone()
    return int(row[0]) if row else None


def stale(svc) -> bool:
    return data_rev_seen(svc) != svc.data_rev()


def materialize(svc, batch: int = 500) -> dict:
    if not svc.materialize_lock.acquire(blocking=False):
        return {"skipped": True}
    try:
        return _materialize(svc, batch)
    finally:
        svc.materialize_lock.release()


def _materialize(svc, batch: int) -> dict:
    started = time.perf_counter()
    data_rev = svc.data_rev()
    hub = svc.hub
    if "t" not in hub.attached():
        return {"changed": 0, "removed": 0, "ms": 0, "status": "no_data"}
    with hub.read() as db:
        current = _signatures(db)
        known = dict(db.execute("SELECT session_uid, sig FROM sess_feat_state "
                                "WHERE session_uid <> ?", (DATA_REV_KEY,)).fetchall())
    changed = sorted(uid for uid, sig in current.items() if known.get(uid) != sig)
    removed = sorted(set(known) - set(current))
    now = int(time.time() * 1000)
    for i in range(0, len(changed), batch):
        uids = changed[i:i + batch]
        counts = compute(hub, uids)
        names = {name for counter in counts.values() for name in counter}
        with svc.appdb.write() as db:
            fids = _fids(db, names, svc.fid_cache)
            marks = ",".join("?" * len(uids))
            db.execute(f"DELETE FROM sess_feat WHERE session_uid IN ({marks})", uids)
            db.executemany("INSERT INTO sess_feat VALUES (?, ?, ?)",
                           [(uid, fids[name], n) for uid, counter in counts.items()
                            for name, n in counter.items()])
            db.executemany("INSERT OR REPLACE INTO sess_feat_state VALUES (?, ?, ?)",
                           [(uid, current[uid], now) for uid in uids])
        svc.fid_cache = fids
    with svc.appdb.write() as db:
        for i in range(0, len(removed), batch):
            part = removed[i:i + batch]
            marks = ",".join("?" * len(part))
            db.execute(f"DELETE FROM sess_feat WHERE session_uid IN ({marks})", part)
            db.execute(f"DELETE FROM sess_feat_state WHERE session_uid IN ({marks})", part)
        db.execute("INSERT OR REPLACE INTO sess_feat_state VALUES (?, ?, ?)",
                   (DATA_REV_KEY, str(data_rev), now))
    return {"changed": len(changed), "removed": len(removed),
            "ms": round((time.perf_counter() - started) * 1000, 1)}

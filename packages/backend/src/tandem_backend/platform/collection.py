"""Collection pause / resume (DT-02.1, MB-04, POP-11, HUD-01).

A pause stops automatic collection only: the gateway's continuous sync loop reads
``collection.paused`` and skips its ``origin="sync"`` imports, so nothing new is written to
L1-L3 while paused. Imports the user starts explicitly (import, re-index) are not blocked.
The open pause interval lives in ``app.db``, so a pause survives restarts. On resume one
full incremental import catches up; the importers keep head/tail checkpoints and
generations per file, so anything still present in the agent logs is picked up without
extra watermarks. If a job is already running, ``catch_up_pending`` stays set until the
sync loop submits the catch-up and calls ``consume_catch_up()``.
"""

from __future__ import annotations

import threading
import time

DAY_MS = 86_400_000


def prune_pauses(db, now: int) -> int:
    """Keep closed intervals for one year and at most 200 of them."""
    aged = db.execute("DELETE FROM collection_pause WHERE ended_at IS NOT NULL AND "
                      "ended_at < ?", (now - 365 * DAY_MS,)).rowcount
    over = db.execute("DELETE FROM collection_pause WHERE ended_at IS NOT NULL AND id NOT IN "
                      "(SELECT id FROM collection_pause WHERE ended_at IS NOT NULL "
                      "ORDER BY id DESC LIMIT 200)").rowcount
    return aged + over


def _local_midnight_ms(now_ms: int) -> int:
    local = time.localtime(now_ms / 1000)
    return int(time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1))
               * 1000)


class Collection:
    def __init__(self, gw, clock=time.time):
        self.gw = gw
        self.clock = clock
        self.lock = threading.Lock()
        self.catch_up_pending = False
        with gw.appdb.read() as db:
            row = db.execute("SELECT id, started_at, reason FROM collection_pause WHERE "
                             "ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        self.open_id, self.since, self.reason = (row[0], row[1], row[2]) if row else (
            None, None, None)

    @property
    def paused(self) -> bool:
        return self.open_id is not None

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    def pause(self, reason: str = "user") -> dict:
        reason = (reason or "user")[:64]
        with self.lock:
            if self.open_id is None:
                now = self.now_ms()
                with self.gw.appdb.write() as db:
                    self.open_id = db.execute(
                        "INSERT INTO collection_pause (started_at, reason) VALUES (?, ?)",
                        (now, reason)).lastrowid
                self.since, self.reason = now, reason
                self.catch_up_pending = False
                self._publish("paused")
        return self.status()

    def resume(self) -> dict:
        with self.lock:
            if self.open_id is None:
                return {"paused": False, "resumed_at": None, "paused_ms": 0,
                        "catch_up_job_id": None, "catch_up_pending": self.catch_up_pending}
            now = self.now_ms()
            with self.gw.appdb.write() as db:
                db.execute("UPDATE collection_pause SET ended_at = ? WHERE ended_at IS NULL",
                           (now,))
            paused_ms = now - (self.since or now)
            self.open_id = self.since = self.reason = None
            self._publish("resumed")
            job_id = self._catch_up()
            self._publish("running")
            return {"paused": False, "resumed_at": now, "paused_ms": paused_ms,
                    "catch_up_job_id": job_id, "catch_up_pending": self.catch_up_pending}

    def _catch_up(self) -> str | None:
        from tandem_backend.services.jobs import JobConflict

        sources = self.gw.state.snapshot().get("sources") or {}
        enabled = [key for key, source in sources.items() if source.get("enabled")]
        if not enabled:
            return None
        try:
            job = self.gw.jobs.submit("import", enabled, phase="full", origin="sync")
        except (JobConflict, ValueError):
            self.catch_up_pending = True
            return None
        self.catch_up_pending = False
        return job.get("id") if isinstance(job, dict) else None

    def consume_catch_up(self) -> bool:
        """True once after a resume whose catch-up import could not start yet."""
        with self.lock:
            pending, self.catch_up_pending = self.catch_up_pending, False
            return pending

    def status(self) -> dict:
        now = self.now_ms()
        midnight = _local_midnight_ms(now)
        with self.gw.appdb.read() as db:
            row = db.execute(
                "SELECT COALESCE(SUM(MIN(COALESCE(ended_at, ?), ?) - MAX(started_at, ?)), 0) "
                "FROM collection_pause WHERE COALESCE(ended_at, ?) > ?",
                (now, now, midnight, now, midnight)).fetchone()
        return {"paused": self.paused, "since": self.since, "reason": self.reason,
                "paused_ms_today": max(0, row[0]), "catch_up_pending": self.catch_up_pending}

    def intervals(self, limit: int = 50) -> list[dict]:
        with self.gw.appdb.read() as db:
            rows = db.execute("SELECT id, started_at, ended_at, reason FROM collection_pause "
                              "ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [dict(row) for row in rows]

    def prune(self) -> int:
        with self.gw.appdb.write() as db:
            return prune_pauses(db, self.now_ms())

    def _publish(self, state: str) -> None:
        self.gw.bus.publish("service", "service", {"name": "collection", "state": state})

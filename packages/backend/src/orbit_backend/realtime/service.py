"""Live session snapshot, lazy refresh thread and notifier hooks (AN-13, AN-13.1 producer).

Reads orbit.db only. The refresh thread runs every ``TICK_S`` while an SSE client is
connected or a snapshot was asked for within ``KEEPALIVE_S``, and exits otherwise; the next
request starts it again. Transitions between ticks become ``notify``/``resolve`` calls.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path

from ..platform import logs, timed
from ..services.auth import ApiError
from . import hooks
from .classify import classify, finish_ts
from .context_windows import load_overrides
from .model import SessionState, SessionTail
from .tail import load_tails

TICK_S = 2.0
KEEPALIVE_S = 30.0
PREWARM_JOIN_S = 15.0  # a cold tail query took up to ~8 s on real data
ORDER = {"awaiting_approval": 0, "failing": 1, "running": 2, "just_finished": 3, "idle": 4}
ACTIVE = {"awaiting_approval", "failing", "running"}
NOTIFY_TYPES = ("awaiting_approval", "failing", "context_pressure", "just_finished")
DISMISSABLE = ("failing", "context_pressure")
SEVERITY = {"awaiting_approval": "urgent", "failing": "urgent", "just_finished": "info",
            "context_pressure": "attention"}
TITLES = {"awaiting_approval": "会话等待你的批准", "failing": "会话反复失败",
          "context_pressure": "会话上下文接近上限", "just_finished": "会话已完成"}
FAILURE_KEYS = ("n", "command_head", "error_class_share", "cause_hint")
VOLATILE = ("running_s",)
MIN_RUN_S = {"just_finished": 600}  # Default of notify policy ``min_run_s``.  # Changes every tick; clients derive it from ``since``.


def _notifier_module():
    try:
        return import_module("orbit_backend.platform.notify")
    except ModuleNotFoundError:
        return None


def _bins(stamps, now: int, minutes: int) -> list[int]:
    counts = [0] * minutes
    for ts in stamps:
        age = (now - ts) // 60_000
        if 0 <= age < minutes:
            counts[minutes - 1 - age] += 1
    return counts


def _body(kind: str, item: dict) -> str:
    name = item["title"] or item["project"] or item["session_uid"]
    if kind == "awaiting_approval":
        return f"{name}：{(item['approval'] or {}).get('command') or '有操作待批准'}"
    if kind == "failing":
        failure = item["failure"] or {}
        hint = f"（{failure['cause_hint']}）" if failure.get("cause_hint") else ""
        return f"{name}：{failure.get('command_head')} 连续失败 {failure.get('n')} 次{hint}"
    if kind == "context_pressure":
        ratio = (item["context"] or {}).get("ratio") or 0
        return f"{name}：上下文已用 {round(ratio * 100)}%"
    return f"{name} 已结束本轮工作"


def _run_s(tail: SessionTail, state: SessionState) -> int | None:
    """Run length of a finished session (start → finish), None when either end is unknown."""
    end = state.finished_at or finish_ts(tail)
    if tail.started_at is None or end is None:
        return None
    return max(0, (end - tail.started_at) // 1000)


def content_hash(snapshot: dict) -> str:
    body = {k: v for k, v in snapshot.items() if k != "generated_at"}
    body["sessions"] = [{k: v for k, v in s.items() if k not in VOLATILE}
                        for s in snapshot.get("sessions", [])]
    return hashlib.sha1(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class Realtime:
    def __init__(self, gw, clock=time.time, notify=None, resolve=None):
        self.gw = gw
        self.clock = clock
        self._notify, self._resolve = notify, resolve
        self.lock = threading.RLock()
        self.active: dict[str, set[str]] = {}  # session -> notification types currently open
        self.dismissed: dict[str, int] = {}  # session -> until ms
        self.known: set[str] = set()
        self.last: dict | None = None
        self.last_at = 0.0
        self.requested_at = 0.0
        self.clients = 0
        self.thread: threading.Thread | None = None
        self.prewarm_thread: threading.Thread | None = None
        self.stop = threading.Event()
        self.last_error: str | None = None  # last logged tick failure (dedupes the log)
        home = getattr(gw, "home", None)
        self.hooks = hooks.HookFeed(Path(home) / "hooks") if home else None

    # -- lifecycle -----------------------------------------------------------------------
    def start(self) -> None:
        with self.lock:
            if self.stop.is_set() or (self.thread and self.thread.is_alive()):
                return
            self.thread = threading.Thread(target=self._run, name="realtime", daemon=True)
            self.thread.start()

    def start_prewarm(self) -> None:
        """Warm the tail query on a background thread that ``close`` waits for."""
        with self.lock:
            if self.stop.is_set() or (self.prewarm_thread and self.prewarm_thread.is_alive()):
                return
            self.prewarm_thread = threading.Thread(target=self.prewarm, name="realtime-prewarm",
                                                   daemon=True)
            self.prewarm_thread.start()

    def close(self) -> bool:
        """Stop the tick loop and wait for it and the prewarm: both read orbit.db through
        the gateway's read pool, which the gateway closes right after (a read still running
        on a closed SQLite connection could crash the process). A tick runs the same cold
        tail reads as the prewarm, so both get ``PREWARM_JOIN_S``. Returns False when a
        thread is still alive after that, so the caller can say so."""
        self.stop.set()
        stopped = True
        for thread in (self.thread, self.prewarm_thread):
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(PREWARM_JOIN_S)
                stopped = stopped and not thread.is_alive()
        return stopped

    def attach(self) -> None:
        with self.lock:
            self.clients += 1
        self.start()

    def detach(self) -> None:
        with self.lock:
            self.clients = max(0, self.clients - 1)

    def _wanted(self) -> bool:
        return self.clients > 0 or self.clock() - self.requested_at < KEEPALIVE_S

    def stopping(self) -> bool:
        stopping = getattr(self.gw, "stopping", None)
        return self.stop.is_set() or bool(stopping and stopping.is_set())

    def _run(self) -> None:
        while not self.stop.wait(TICK_S):
            with self.lock:
                if self.stopping() or not self._wanted():
                    self.thread = None
                    return
            try:
                self.refresh()
                self.last_error = None
            except Exception as error:  # noqa: BLE001 - the loop must survive a bad tick.
                # Log once per distinct failure, not every 2 s tick, so a stuck HUD is diagnosable.
                message = f"{type(error).__name__}: {error}"[:300]
                if message != self.last_error:
                    self.last_error = message
                    logs.log_event("realtime_tick_failed", logging.WARNING, error=message)

    # -- reads ---------------------------------------------------------------------------
    def snapshot(self, now: float | None = None, lanes: bool = False) -> dict:
        """Current snapshot; ``now`` (seconds) forces a refresh at that virtual time."""
        if now is not None:
            snap = self.refresh(now)
        else:
            self.requested_at = self.clock()
            self.start()
            snap = self.last if self.last and self.clock() - self.last_at < TICK_S else None
            snap = snap or self.refresh()
        return snap if lanes else self.strip(snap)

    def latest(self) -> dict | None:
        return self.last

    @staticmethod
    def strip(snapshot: dict) -> dict:
        return {**snapshot, "sessions": [{k: v for k, v in s.items() if k != "lanes"}
                                         for s in snapshot["sessions"]]}

    def _paused(self) -> bool:
        collection = getattr(getattr(self.gw, "platform", None), "collection", None)
        return bool(getattr(collection, "paused", False))

    def _tails(self, now_ms: int) -> list[SessionTail]:
        try:
            return load_tails(self.gw.reads, now_ms)
        except (ApiError, sqlite3.Error):  # No orbit.db yet, or busy: show nothing.
            return []

    def _classify(self, tail: SessionTail, now_ms: int, overrides) -> tuple[SessionTail, SessionState]:
        info = self.hooks.session(tail.agent, tail.native_id) if self.hooks else None
        hooks.overlay(tail, info)
        state = classify(tail, now_ms, overrides)
        hooks.refine(state, info)
        return tail, state

    def approvals(self, since_ms: int = 0, limit: int = 100) -> dict:
        """Hook-observed approval waits (HUD-03 / POP-*): closed waits and open ones."""
        if self.hooks is None:
            return {"items": [], "pending": [], "summary": hooks.summary([])}
        self.hooks.poll()
        items = self.hooks.waits(since_ms, limit)
        return {"items": items, "pending": self.hooks.pending(), "summary": hooks.summary(items)}

    def refresh(self, now: float | None = None) -> dict:
        now_s = self.clock() if now is None else now
        now_ms = int(now_s * 1000)
        with self.lock, timed("realtime.refresh"):
            paused = self._paused()
            # Paused collection means orbit.db is not being updated: any state would be stale.
            tails = [] if paused else self._tails(now_ms)
            if self.hooks is not None:
                try:
                    self.hooks.poll()
                except OSError:  # unreadable events file: run on orbit.db alone
                    pass
            overrides = load_overrides(getattr(self.gw, "appdb", None))
            pairs = [self._classify(t, now_ms, overrides) for t in tails]
            self.dismissed = {k: v for k, v in self.dismissed.items() if v > now_ms}
            items = [self._item(t, s, now_ms) for t, s in pairs]
            items.sort(key=lambda i: (ORDER[i["state"]], -(i["since"] or 0)))
            self.known = {t.session_uid for t in tails}
            if not paused:
                self._transitions(items, {t.session_uid: _run_s(t, s) for t, s in pairs})
            snap = self._compose(items, pairs, now_ms, paused)
            self.last, self.last_at = snap, self.clock()
            return snap

    def _compose(self, items, pairs, now_ms: int, paused: bool) -> dict:
        midnight = int(datetime.fromtimestamp(now_ms / 1000).replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        counts = {k: 0 for k in ("running", "awaiting_approval", "failing", "just_finished",
                                 "context_pressure")}
        for item in items:
            if item["state"] in counts:
                counts[item["state"]] += 1
            if "context_pressure" in item["flags"]:
                counts["context_pressure"] += 1
        # Today's counts use the overview / menu-bar session set (``shell.main_where``: main
        # sessions, not excluded, not started by Orbit itself), never subagent sessions.
        counted = self._counted([t for t, _ in pairs])
        finished = 0
        for tail, _ in pairs:
            if tail.session_uid not in counted:
                continue
            done = finish_ts(tail)
            finished += done is not None and midnight <= done <= now_ms
        if paused:
            status = "paused"
        else:
            status = "active" if any(i["state"] in ACTIVE for i in items) else "idle"
        idle = sum(1 for i in items if i["state"] == "idle")
        return {"generated_at": now_ms, "status": status, "counts": {**counts, "idle": idle},
                "today": None if paused else {
                    "sessions_started": sum(1 for t, _ in pairs if t.session_uid in counted
                                            and (t.started_at or 0) >= midnight),
                    "sessions_finished": finished},
                "reason": "collection_paused" if paused else None,
                # Only live and recently finished sessions; idle ones are counted, not listed.
                "sessions": [i for i in items if i["state"] != "idle"]}

    def _counted(self, tails: list[SessionTail]) -> set[str]:
        """Tails that are analysed main sessions (``shell.main_where``); without the gateway
        pieces (tests, no app.db) the session kind alone decides."""
        mains = [t.session_uid for t in tails if t.kind == "main"]
        if not mains:
            return set()
        try:
            from ..shell import main_where

            where, args = main_where(self.gw)
            marks = ",".join("?" * len(mains))
            with self.gw.reads.read(check=False) as db:
                rows = db.execute(f"SELECT s.session_uid FROM session s WHERE {where} "
                                  f"AND s.session_uid IN ({marks})", [*args, *mains])
                return {r[0] for r in rows}
        except Exception:  # noqa: BLE001 - no app.db / home: kind only
            return set(mains)

    def prewarm(self) -> None:
        """Warm the tail query (page cache, statement cache) without notifying anyone."""
        try:
            if not self.stopping() and not self._paused():
                self._tails(int(self.clock() * 1000))
        except Exception:  # noqa: BLE001 - best effort only
            pass

    def _item(self, tail: SessionTail, state: SessionState, now_ms: int) -> dict:
        flags = set(state.flags)
        until = self.dismissed.get(tail.session_uid)
        if until:
            flags -= set(DISMISSABLE)
        lane_from = now_ms - 20 * 60_000
        return {
            "session_uid": tail.session_uid, "agent": tail.agent, "project_id": tail.project_id,
            "project": tail.project, "title": tail.title, "state": state.state,
            "flags": sorted(flags), "since": state.since,
            "running_s": max(0, (now_ms - state.since) // 1000) if state.state in ACTIVE else 0,
            "current_tool": state.current_tool,
            "density": _bins([e.ts for e in tail.events if e.ts is not None], now_ms, 10),
            "context": state.context,
            "failure": state.failure and {k: state.failure[k] for k in FAILURE_KEYS},
            "approval": state.approval, "outcome": None, "dismissed_until": until,
            "lanes": {
                "human": [e.ts for e in tail.events
                          if e.actor == "human" and e.ts and e.ts >= lane_from],
                "tool": [c.started_at for c in tail.calls
                         if c.started_at and c.started_at >= lane_from],
                "error": [c.started_at for c in tail.calls if c.status in ("failed", "error")
                          and c.started_at and c.started_at >= lane_from]},
        }

    # -- notifier ------------------------------------------------------------------------
    def _call(self, name: str, arg) -> None:
        handler = getattr(self, f"_{name}")
        if handler is None:
            handler = getattr(_notifier_module(), name, None)
        if handler is None:
            return
        try:
            handler(arg)
        except Exception:  # noqa: BLE001 - a notifier error never breaks the loop.
            pass

    def _min_run_s(self, kind: str) -> int:
        notifier = getattr(getattr(self.gw, "platform", None), "notifier", None)
        policy = getattr(notifier, "policy_body", None) or {}
        value = (policy.get("min_run_s") or {}).get(kind)
        return MIN_RUN_S.get(kind, 0) if value is None else int(value)

    def _transitions(self, items: list[dict], run_s: dict[str, int | None] | None = None,
                     ) -> None:
        current = {}
        threshold = self._min_run_s("just_finished")
        for item in items:
            kinds = {f for f in item["flags"] if f in NOTIFY_TYPES}
            if item["state"] == "just_finished":
                ran = (run_s or {}).get(item["session_uid"])
                # SIM-01: only runs of at least ``min_run_s`` notify; unknown length notifies.
                if ran is None or ran >= threshold:
                    kinds.add("just_finished")
            current[item["session_uid"]] = (kinds, item)
        for uid in list(self.active):
            if uid not in current:
                for kind in self.active.pop(uid):
                    self._call("resolve", f"{kind}:{uid}")
        for uid, (kinds, item) in current.items():
            before = self.active.get(uid, set())
            for kind in sorted(before - kinds):
                self._call("resolve", f"{kind}:{uid}")
            for kind in sorted(kinds - before):
                payload = {k: v for k, v in item.items() if k not in ("lanes", "density")}
                self._call("notify", {"type": kind, "key": f"{kind}:{uid}", "session_uid": uid,
                                      "severity": SEVERITY[kind], "title": TITLES[kind],
                                      "body": _body(kind, item), "payload": payload})
            if kinds:
                self.active[uid] = kinds
            else:
                self.active.pop(uid, None)

    # -- actions -------------------------------------------------------------------------
    def dismiss(self, session_uid: str, seconds: int = 3600) -> dict:
        if session_uid not in self.known:
            self.refresh()
        if session_uid not in self.known:
            raise ApiError(404, "not_found", f"Unknown or inactive session {session_uid}")
        until = int((self.clock() + seconds) * 1000)
        with self.lock:
            self.dismissed[session_uid] = until
            self.last = None  # Next snapshot reflects the dismissal.
        notifier = getattr(getattr(self.gw, "platform", None), "notifier", None)
        snooze = getattr(notifier, "snooze", None)
        if callable(snooze):
            for kind in DISMISSABLE:
                try:
                    snooze(seconds, f"session:{session_uid}:{kind}")
                except Exception:  # noqa: BLE001
                    pass
        return {"session_uid": session_uid, "until": until}

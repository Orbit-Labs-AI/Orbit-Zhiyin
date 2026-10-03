"""Notification policy engine and attention queue (FE-18.1, AN-13.1).

Producers (AN-13 detectors, AI jobs, the gateway itself) call ``notify(event)``. Each event
passes a fixed decision chain — disabled → muted type → snooze → cooldown dedupe → quiet
hours → rate limit → channel matrix — and is stored in ``app.db`` even when suppressed, so
the settings page can explain what was held back. Muted/snoozed/quiet/limited events lose
banner and HUD but keep the menu-bar badge, matching the UI copy. Delivery itself is the
host's job: it consumes ``notify`` SSE frames and shows each channel listed in the frame.
This module never reads session content; producers supply the copy.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any

from orbit_data.privacy import sanitize

TYPES = ("awaiting_approval", "failing", "context_pressure", "just_finished", "ai_job_done",
         "weekly", "new_source", "system")
PRIORITY = {name: rank for rank, name in enumerate(TYPES)}
CHANNELS = ("banner", "hud", "badge")
ALIASES = {"waiting": "awaiting_approval", "done": "just_finished", "stuck": "failing",
           "ctx": "context_pressure"}
SEVERITY = {"awaiting_approval": "urgent", "failing": "attention",
            "context_pressure": "attention", "system": "attention"}
SEVERITIES = ("info", "attention", "urgent")
PAYLOAD_MAX = 2048
DAY_MS = 86_400_000

DEFAULT_POLICY: dict[str, Any] = {
    "matrix": {"awaiting_approval": ["banner", "hud", "badge"],
               "failing": ["banner", "hud", "badge"], "context_pressure": ["hud"],
               "just_finished": ["hud", "badge"], "ai_job_done": ["banner", "badge"],
               "weekly": ["badge"], "new_source": ["badge"], "system": ["banner", "badge"]},
    "quiet_hours": {"enabled": False, "start": "22:00", "end": "08:00",
                    "allow": ["awaiting_approval"]},
    "cooldown_s": {"awaiting_approval": 120, "failing": 300, "context_pressure": 600,
                   "just_finished": 60, "ai_job_done": 0, "weekly": 0, "new_source": 3600,
                   "system": 3600},
    "rate_limit": {"per_minute": 6, "per_hour": 40},
    "muted_types": [],
    "snooze_default_s": 3600,
    # Minimum run length before a type is worth a notification (SIM-01: "会话完成(超过
    # 10 分钟)"); the realtime badge state is unaffected.
    "min_run_s": {"just_finished": 600},
}
MIN_RUN_TYPES = ("just_finished",)

PRESETS = {
    "quiet": {"awaiting_approval": ["banner", "hud", "badge"], "failing": ["hud", "badge"],
              "just_finished": ["badge"]},
    "all": {name: list(CHANNELS) for name in TYPES},
}

ROW_FIELDS = ("id", "type", "severity", "session_uid", "title", "body", "payload", "channels",
              "state", "suppressed_reason", "count", "ts", "last_ts", "acked_at")

_active: Notifier | None = None


def notify(event: dict) -> int | None:
    """Module-level entry for producers; a no-op until the gateway starts a Notifier."""
    notifier = _active
    return notifier.emit(event) if notifier is not None else None


def resolve(key: str) -> int | None:
    notifier = _active
    return notifier.resolve(key) if notifier is not None else None


def normalize_type(name: str) -> str:
    name = ALIASES.get(name, name)
    if name not in TYPES:
        raise ValueError(f"unknown notification type {name!r}")
    return name


def _local_minute(ts_s: float) -> int:
    """Minutes since local midnight (patched in tests)."""
    local = time.localtime(ts_s)
    return local.tm_hour * 60 + local.tm_min


def _hhmm(value: str) -> int:
    try:
        hour, minute = value.split(":")
        hour_i, minute_i = int(hour), int(minute)
    except (AttributeError, ValueError):
        raise ValueError(f"time must be HH:MM, got {value!r}") from None
    if len(hour) != 2 or len(minute) != 2 or not (0 <= hour_i < 24 and 0 <= minute_i < 60):
        raise ValueError(f"time must be HH:MM, got {value!r}")
    return hour_i * 60 + minute_i


def _merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value  # Lists (matrix channels, muted types) replace wholesale.
    return out


def validate_policy(policy: dict) -> dict:
    """Normalize aliases and check every field; raises ValueError on bad input."""
    unknown = set(policy) - set(DEFAULT_POLICY)
    if unknown:
        raise ValueError(f"unknown policy keys {sorted(unknown)}")
    matrix: dict[str, list[str]] = {}
    for name, channels in dict(policy["matrix"]).items():
        if not isinstance(channels, list) or not set(channels) <= set(CHANNELS):
            raise ValueError(f"matrix.{name} must be a subset of {list(CHANNELS)}")
        matrix[normalize_type(name)] = [c for c in CHANNELS if c in channels]
    quiet = dict(policy["quiet_hours"])
    if set(quiet) - {"enabled", "start", "end", "allow"}:
        raise ValueError("quiet_hours accepts enabled, start, end, allow")
    _hhmm(quiet["start"]), _hhmm(quiet["end"])
    quiet["enabled"] = bool(quiet["enabled"])
    quiet["allow"] = sorted({normalize_type(t) for t in quiet["allow"]}, key=PRIORITY.get)
    cooldown: dict[str, int] = {}
    for name, seconds in dict(policy["cooldown_s"]).items():
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 0 <= seconds <= 86400:
            raise ValueError(f"cooldown_s.{name} must be an integer in 0..86400")
        cooldown[normalize_type(name)] = seconds
    rate = dict(policy["rate_limit"])
    if set(rate) != {"per_minute", "per_hour"} or any(
            isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in rate.values()):
        raise ValueError("rate_limit needs positive integers per_minute and per_hour")
    snooze = policy["snooze_default_s"]
    if isinstance(snooze, bool) or not isinstance(snooze, int) or not 60 <= snooze <= 86400:
        raise ValueError("snooze_default_s must be an integer in 60..86400")
    muted = sorted({normalize_type(t) for t in policy["muted_types"]}, key=PRIORITY.get)
    min_run: dict[str, int] = {}
    for name, seconds in dict(policy.get("min_run_s") or {}).items():
        name = normalize_type(name)
        if name not in MIN_RUN_TYPES:
            raise ValueError(f"min_run_s applies to {list(MIN_RUN_TYPES)}")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 0 <= seconds <= 86400:
            raise ValueError(f"min_run_s.{name} must be an integer in 0..86400")
        min_run[name] = seconds
    return {"matrix": {**{t: [] for t in TYPES}, **matrix}, "quiet_hours": quiet,
            "cooldown_s": {**{t: 0 for t in TYPES}, **cooldown}, "rate_limit": rate,
            "muted_types": muted, "snooze_default_s": snooze,
            "min_run_s": {**DEFAULT_POLICY["min_run_s"], **min_run}}


def _in_window(minute: int, start: int, end: int) -> bool:
    if start == end:
        return False
    return start <= minute < end if start < end else minute >= start or minute < end


class Notifier:
    def __init__(self, gw, clock=time.time):
        self.gw = gw
        self.clock = clock
        self.lock = threading.Lock()
        self.policy_body: dict = validate_policy(DEFAULT_POLICY)
        self.policy_rev = 0
        self.last_delivered: dict[str, tuple[int, int]] = {}  # dedupe_key -> (id, ts)
        self.banners: deque[int] = deque()
        self.snooze_until: dict[str, int] = {}

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    # -- lifecycle -----------------------------------------------------------------------
    def start(self) -> Notifier:
        global _active
        now = self.now_ms()
        with self.gw.appdb.write() as db:
            row = db.execute("SELECT body, updated_at FROM notification_policy").fetchone()
            if row is None:
                db.execute("INSERT INTO notification_policy VALUES (1, ?, ?)",
                           (json.dumps(self.policy_body), now))
                self.policy_rev = now
            else:
                self.policy_body = validate_policy(_merge(DEFAULT_POLICY, json.loads(row[0])))
                self.policy_rev = row[1]
            for key, id_, ts in db.execute(
                    "SELECT dedupe_key, id, ts FROM notification WHERE state = 'delivered' "
                    "AND ts >= ? ORDER BY ts", (now - DAY_MS,)):
                self.last_delivered[key] = (id_, ts)
            self.banners.extend(ts for (ts,) in db.execute(
                "SELECT ts FROM notification WHERE ts >= ? AND channels LIKE '%banner%' "
                "AND state = 'delivered' ORDER BY ts", (now - 3_600_000,)))
            self.snooze_until = dict(db.execute(
                "SELECT scope, until FROM notification_snooze WHERE until > ?", (now,)))
        _active = self
        return self

    def close(self) -> None:
        global _active
        if _active is self:
            _active = None

    # -- decision chain ------------------------------------------------------------------
    def _enabled(self) -> bool:
        settings = getattr(getattr(self.gw, "platform", None), "settings", None)
        if settings is None:
            return True
        if callable(getattr(settings, "flag", None)):
            return settings.flag("notifications")
        if isinstance(settings, dict):
            return bool(settings.get("notifications", True))
        return bool(getattr(settings, "notifications", True))

    def _snoozed(self, kind: str, session_uid: str | None, now: int) -> bool:
        scopes = ["global", f"type:{kind}"]
        if session_uid:
            scopes.append(f"session:{session_uid}:{kind}")
        return any(self.snooze_until.get(scope, 0) > now for scope in scopes)

    def decide(self, ev: dict, now: int) -> tuple[list[str], str | None, int | None]:
        """Returns ``(channels, reason, dedupe_into_id)``; caller holds ``self.lock``."""
        policy = self.policy_body
        kind = ev["type"]
        matrix = set(policy["matrix"].get(kind, ()))
        if not self._enabled():
            return [], "disabled", None
        if ev["force"]:
            return [c for c in CHANNELS if c in (matrix or set(CHANNELS))], None, None
        channels, reason = set(CHANNELS), None

        def reduce(keep: set[str], why: str):
            nonlocal channels, reason
            channels &= keep
            reason = reason or why

        if kind in policy["muted_types"]:
            reduce({"badge"}, "muted_type")
        if self._snoozed(kind, ev["session_uid"], now):
            reduce({"badge"}, "snoozed")
        cooldown = policy["cooldown_s"].get(kind, 0) * 1000
        last = self.last_delivered.get(ev["key"])
        if cooldown and last and now - last[1] < cooldown:
            return [], "deduped", last[0]
        quiet = policy["quiet_hours"]
        if quiet["enabled"] and kind not in quiet["allow"] and _in_window(
                _local_minute(now / 1000), _hhmm(quiet["start"]), _hhmm(quiet["end"])):
            reduce({"badge"}, "quiet_hours")
        if "banner" in channels & matrix and ev["severity"] != "urgent":
            while self.banners and self.banners[0] <= now - 3_600_000:
                self.banners.popleft()
            recent = sum(1 for ts in self.banners if ts > now - 60_000)
            limit = policy["rate_limit"]
            if recent >= limit["per_minute"] or len(self.banners) >= limit["per_hour"]:
                reduce({"hud", "badge"}, "rate_limited")
        final = [c for c in CHANNELS if c in channels & matrix]
        return final, reason, None

    # -- producers -----------------------------------------------------------------------
    def _normalize(self, event: dict) -> dict:
        event = sanitize(event)
        kind = normalize_type(str(event.get("type") or ""))
        title = str(event.get("title") or "").strip()
        if not title:
            raise ValueError("notification title is required")
        severity = event.get("severity") or SEVERITY.get(kind, "info")
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        session_uid = event.get("session_uid") or None
        payload = json.dumps(event.get("payload") or {}, ensure_ascii=False,
                             separators=(",", ":"), default=str)
        if len(payload.encode()) > PAYLOAD_MAX:
            payload = "{}"
        return {"type": kind, "session_uid": session_uid, "title": title[:200],
                "key": str(event.get("key") or f"{kind}:{session_uid or '-'}"),
                "body": str(event.get("body") or "")[:1000], "severity": severity,
                "payload": payload, "force": bool(event.get("force")), "ts": event.get("ts")}

    def emit(self, event: dict) -> int | None:
        ev = self._normalize(event)
        now = int(ev["ts"]) if ev["ts"] is not None else self.now_ms()
        with self.lock:
            channels, reason, into = self.decide(ev, now)
            with self.gw.appdb.write() as db:
                if into is not None:
                    row = db.execute(
                        "UPDATE notification SET count = count + 1, last_ts = ?, payload = ? "
                        "WHERE id = ? AND state = 'delivered' RETURNING id", (
                            now, ev["payload"], into)).fetchone()
                    if row is not None:
                        summary = self._summary(db)
                        new_id, state = into, "deduped"
                    else:  # Row was acked/resolved behind our back; deliver afresh.
                        self.last_delivered.pop(ev["key"], None)
                        channels, reason, into = self.decide(ev, now)
                if into is None:
                    state = "delivered" if channels else "suppressed"
                    if state == "delivered":  # A fresh delivery supersedes older rows.
                        db.execute("UPDATE notification SET state = 'resolved' WHERE "
                                   "dedupe_key = ? AND state = 'delivered'", (ev["key"],))
                    new_id = db.execute(
                        "INSERT INTO notification (ts, last_ts, type, dedupe_key, session_uid, "
                        "severity, title, body, payload, channels, state, suppressed_reason) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                            now, now, ev["type"], ev["key"], ev["session_uid"], ev["severity"],
                            ev["title"], ev["body"], ev["payload"], json.dumps(channels), state,
                            reason)).lastrowid
                    summary = self._summary(db)
                    if state == "delivered":
                        self.last_delivered[ev["key"]] = (new_id, now)
                        if "banner" in channels:
                            self.banners.append(now)
                if state == "deduped":
                    count = db.execute("SELECT count FROM notification WHERE id = ?",
                                       (new_id,)).fetchone()[0]
        bus = self.gw.bus
        if state == "delivered":
            bus.publish("notify", "notification", {
                "id": new_id, "type": ev["type"], "severity": ev["severity"],
                "session_uid": ev["session_uid"], "title": ev["title"], "body": ev["body"],
                "channels": channels, "count": 1, "ts": now,
                "payload": json.loads(ev["payload"])})
        elif state == "deduped":
            summary = {**summary, "deduped": {"id": new_id, "count": count}}
        bus.publish("notify", "attention", summary)
        _record(ev["type"], state)
        return new_id

    def resolve(self, key: str) -> int:
        with self.lock, self.gw.appdb.write() as db:
            changed = db.execute("UPDATE notification SET state = 'resolved' WHERE "
                                 "dedupe_key = ? AND state = 'delivered'", (key,)).rowcount
            self.last_delivered.pop(key, None)
            summary = self._summary(db)
        if changed:
            self.gw.bus.publish("notify", "attention", summary)
        return changed

    # -- user actions --------------------------------------------------------------------
    def ack(self, id: int, snooze_s: int | None = None, mute_type: bool = False) -> dict:
        now = self.now_ms()
        with self.lock, self.gw.appdb.write() as db:
            row = db.execute("SELECT type, session_uid, dedupe_key FROM notification "
                             "WHERE id = ?", (id,)).fetchone()
            if row is None:
                raise KeyError(id)
            kind, session_uid, key = row
            db.execute("UPDATE notification SET state = 'acked', acked_at = ? WHERE id = ?",
                       (now, id))
            if self.last_delivered.get(key, (None,))[0] == id:
                del self.last_delivered[key]
            out: dict[str, Any] = {"id": id, "state": "acked"}
            if snooze_s:
                scope = f"session:{session_uid}:{kind}" if session_uid else f"type:{kind}"
                out["snoozed_until"] = self._snooze(db, scope, now + int(snooze_s) * 1000)
                out["scope"] = scope
            if mute_type:
                body = dict(self.policy_body)
                body["muted_types"] = sorted({*body["muted_types"], kind}, key=PRIORITY.get)
                self._save_policy(db, body, now)
                out["muted_type"] = kind
            summary = self._summary(db)
        self.gw.bus.publish("notify", "attention", summary)
        return out

    def ack_all(self) -> int:
        now = self.now_ms()
        with self.lock, self.gw.appdb.write() as db:
            acked = db.execute("UPDATE notification SET state = 'acked', acked_at = ? "
                               "WHERE state = 'delivered'", (now,)).rowcount
            self.last_delivered.clear()
            summary = self._summary(db)
        self.gw.bus.publish("notify", "attention", summary)
        return acked

    def snooze(self, seconds: int, scope: str = "global") -> dict:
        if scope != "global":
            prefix, _, rest = scope.partition(":")
            if prefix == "type":
                scope = f"type:{normalize_type(rest)}"
            elif prefix == "session" and ":" in rest:
                uid, _, kind = rest.rpartition(":")
                scope = f"session:{uid}:{normalize_type(kind)}"
            else:
                raise ValueError("scope must be global, type:<t> or session:<uid>:<t>")
        now = self.now_ms()
        with self.lock, self.gw.appdb.write() as db:
            until = self._snooze(db, scope, now + int(seconds) * 1000)
        return {"scope": scope, "until": until}

    def unsnooze(self, scope: str = "global") -> dict:
        with self.lock, self.gw.appdb.write() as db:
            db.execute("DELETE FROM notification_snooze WHERE scope = ?", (scope,))
            self.snooze_until.pop(scope, None)
        return {"scope": scope}

    def snoozes(self) -> list[dict]:
        now = self.now_ms()
        with self.lock:
            return [{"scope": s, "until": u} for s, u in sorted(self.snooze_until.items())
                    if u > now]

    def _snooze(self, db, scope: str, until: int) -> int:
        db.execute("INSERT INTO notification_snooze VALUES (?, ?) ON CONFLICT(scope) DO UPDATE "
                   "SET until = excluded.until", (scope, until))
        self.snooze_until[scope] = until
        return until

    # -- policy --------------------------------------------------------------------------
    def policy(self) -> dict:
        with self.lock:
            return {**json.loads(json.dumps(self.policy_body)), "updated_at": self.policy_rev,
                    "policy_rev": self.policy_rev}

    def set_policy(self, patch: dict | None = None, preset: str | None = None) -> dict:
        patch = dict(patch or {})
        patch.pop("updated_at", None), patch.pop("policy_rev", None)
        if preset is not None:
            if preset not in PRESETS:
                raise ValueError(f"preset must be one of {sorted(PRESETS)}")
            patch["matrix"] = {**{t: [] for t in TYPES}, **PRESETS[preset],
                               **(patch.get("matrix") or {})}
        with self.lock:
            body = validate_policy(_merge(self.policy_body, patch))
            with self.gw.appdb.write() as db:
                self._save_policy(db, body, max(self.now_ms(), self.policy_rev + 1))
        return self.policy()

    def _save_policy(self, db, body: dict, now: int) -> None:
        db.execute("INSERT INTO notification_policy VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE "
                   "SET body = excluded.body, updated_at = excluded.updated_at",
                   (json.dumps(body), now))
        self.policy_body, self.policy_rev = body, now

    # -- queries -------------------------------------------------------------------------
    @staticmethod
    def _summary(db) -> dict:
        by_type: dict[str, int] = {}
        active = urgent = 0
        for kind, severity, count in db.execute(
                "SELECT type, severity, COUNT(*) FROM notification WHERE state = 'delivered' "
                "GROUP BY type, severity"):
            by_type[kind] = by_type.get(kind, 0) + count
            active += count
            urgent += count if severity == "urgent" else 0
        return {"active": active, "urgent": urgent, "by_type": by_type}

    def summary(self) -> dict:
        with self.gw.appdb.read() as db:
            return self._summary(db)

    def attention(self) -> list[dict]:
        with self.gw.appdb.read() as db:
            rows = db.execute(
                "SELECT id, type, severity, session_uid, title, body, count, ts, last_ts, "
                "payload FROM notification WHERE state = 'delivered' AND severity IN "
                "('attention', 'urgent') ORDER BY last_ts DESC LIMIT 500").fetchall()
        items = [{"id": r["id"], "type": r["type"], "severity": r["severity"],
                  "session_uid": r["session_uid"], "title": r["title"], "body": r["body"],
                  "count": r["count"], "since": r["ts"], "last_ts": r["last_ts"],
                  "payload": json.loads(r["payload"])} for r in rows]
        items.sort(key=lambda item: (PRIORITY[item["type"]], -item["last_ts"]))
        return sanitize(items[:50])

    def listing(self, state: str | None = None, type: str | None = None, limit: int = 50,
                before_id: int | None = None) -> list[dict]:
        where, args = [], []
        if state is not None:
            where.append("state = ?"), args.append(state)
        if type is not None:
            where.append("type = ?"), args.append(normalize_type(type))
        if before_id is not None:
            where.append("id < ?"), args.append(before_id)
        sql = (f"SELECT {', '.join(ROW_FIELDS)} FROM notification "
               f"{'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY id DESC LIMIT ?")
        with self.gw.appdb.read() as db:
            rows = db.execute(sql, (*args, max(1, min(limit, 200)))).fetchall()
        return sanitize([{**dict(r), "payload": json.loads(r["payload"]),
                          "channels": json.loads(r["channels"])} for r in rows])

    # -- feeds ---------------------------------------------------------------------------
    def observe(self, topic: str, event: str, data: dict) -> None:
        """Turn gateway frames into system notifications; never raises."""
        try:
            if topic == "job" and data.get("status") == "failed":
                kind = data.get("kind") or "job"
                error = data.get("error") or {}
                self.emit({"type": "system", "key": f"job_failed:{kind}",
                           "title": "导入失败" if kind == "import" else "后台任务失败",
                           "body": str(error.get("message") or "")[:300],
                           "payload": {"job_id": data.get("id"), "kind": kind,
                                       "code": error.get("code")}})
            elif topic == "service" and data.get("state") == "degraded":
                name = data.get("name") or "service"
                self.emit({"type": "system", "key": f"service:{name}",
                           "title": "后台服务降级", "body": f"{name} 暂不可用，正在自动恢复。",
                           "payload": {"name": name}})
        except Exception:  # noqa: BLE001 — a notification must never break the event feed.
            pass

    def prune(self) -> dict:
        """Retention: 30 days and 500 rows for handled notifications; open ones are kept."""
        from .collection import prune_pauses

        now = self.now_ms()
        with self.lock, self.gw.appdb.write() as db:
            aged = db.execute("DELETE FROM notification WHERE state != 'delivered' AND ts < ?",
                              (now - 30 * DAY_MS,)).rowcount
            over = db.execute(
                "DELETE FROM notification WHERE state != 'delivered' AND id NOT IN "
                "(SELECT id FROM notification ORDER BY id DESC LIMIT 500)").rowcount
            snoozes = db.execute("DELETE FROM notification_snooze WHERE until <= ?",
                                 (now,)).rowcount
            self.snooze_until = {s: u for s, u in self.snooze_until.items() if u > now}
            pauses = prune_pauses(db, now)
        return {"notifications": aged + over, "snoozes": snoozes, "pauses": pauses}


_telemetry: Any = None  # None = not looked up yet, False = unavailable.


def _record(kind: str, state: str) -> None:
    global _telemetry
    if _telemetry is None:
        try:
            from orbit_backend.platform import telemetry  # type: ignore[attr-defined]

            _telemetry = telemetry
        except Exception:  # noqa: BLE001 — telemetry is optional (platform-core may be absent).
            _telemetry = False
    if _telemetry:
        try:
            _telemetry.record("notify", 1, type=kind, state=state)
        except Exception:  # noqa: BLE001
            pass

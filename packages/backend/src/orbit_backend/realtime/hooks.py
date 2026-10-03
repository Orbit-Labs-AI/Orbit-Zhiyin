"""Incremental reader of ``$ORBIT_HOME/hooks/events.jsonl`` (IN-07 collection, HUD-03, POP-*).

The collection hook appends one JSON line per agent event. This reader resumes from a byte
offset kept in ``events.offset.json`` together with the little state it derives, so a
restart neither replays old lines nor forgets an approval that is still waiting:

* approval wait: ``PermissionRequest`` (or a ``permission_prompt`` notification) opens it;
  the next other event of that session (tool result, prompt, stop) closes it and records
  the wait duration.
* context: the latest status line ``context_window`` sample, ignored once a later
  ``PreCompact`` made it stale.

Only complete lines are consumed. A shrunk or replaced file restarts from offset 0.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from pathlib import Path

from .classify import CONTEXT_PRESSURE

MAX_WAITS = 500
SESSION_TTL_MS = 86_400_000
READ_LIMIT = 4 * 1024 * 1024  # per poll; the rest is read on the next tick
OPENS = ("PermissionRequest",)
PASSIVE = ("StatusLine", "Notification", "PreCompact")  # never close a wait


def _key(agent: str | None, session_id: str | None) -> str:
    return f"{agent or '?'}:{session_id}"


class HookFeed:
    def __init__(self, hooks_dir: Path | str):
        self.dir = Path(hooks_dir)
        self.path = self.dir / "events.jsonl"
        self.checkpoint = self.dir / "events.offset.json"
        self.lock = threading.Lock()
        self.state = self._load()

    # -- checkpoint -----------------------------------------------------------------------
    @staticmethod
    def _empty() -> dict:
        return {"offset": 0, "ino": None, "sessions": {}, "waits": []}

    def _load(self) -> dict:
        try:
            state = json.loads(self.checkpoint.read_text("utf-8"))
        except (OSError, ValueError):
            return self._empty()
        return {**self._empty(), **state} if isinstance(state, dict) else self._empty()

    def _save(self) -> None:
        newest = max((s.get("last_ts") or 0 for s in self.state["sessions"].values()), default=0)
        self.state["sessions"] = {k: s for k, s in self.state["sessions"].items()
                                  if s.get("pending") or (s.get("last_ts") or 0) >= newest - SESSION_TTL_MS}
        self.state["waits"] = self.state["waits"][-MAX_WAITS:]
        tmp = self.checkpoint.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, separators=(",", ":")), "utf-8")
        os.replace(tmp, self.checkpoint)

    # -- reading --------------------------------------------------------------------------
    def poll(self) -> int:
        """Consume new complete lines; returns how many events were applied."""
        with self.lock:
            try:
                stat = self.path.stat()
            except OSError:
                return 0
            if stat.st_ino != self.state["ino"] or stat.st_size < self.state["offset"]:
                self.state.update(offset=0, ino=stat.st_ino)  # rotated or truncated
            if stat.st_size == self.state["offset"]:
                return 0
            with self.path.open("rb") as f:
                f.seek(self.state["offset"])
                chunk = f.read(READ_LIMIT)
            end = chunk.rfind(b"\n") + 1
            if not end:
                return 0  # a hook is mid-write; wait for the newline
            applied = 0
            for line in chunk[:end].splitlines():
                with contextlib.suppress(ValueError):
                    record = json.loads(line)
                    if isinstance(record, dict) and record.get("session_id"):
                        self._apply(record)
                        applied += 1
            self.state["offset"] += end
            with contextlib.suppress(OSError):
                self._save()
            return applied

    def _apply(self, rec: dict) -> None:
        ts, event = int(rec.get("ts") or 0), rec.get("event")
        session = self.state["sessions"].setdefault(_key(rec.get("agent"), rec["session_id"]), {})
        session["last_ts"] = max(ts, session.get("last_ts") or 0)
        pending = session.get("pending")
        if event in OPENS or (event == "Notification" and rec.get("notification_type") == "permission_prompt"):
            if pending is None:
                session["pending"] = {"ts": ts, "tool": rec.get("tool"), "command": rec.get("command")}
            else:  # the notification and the request describe the same wait
                pending["command"] = pending.get("command") or rec.get("command")
                pending["tool"] = pending.get("tool") or rec.get("tool")
        elif event == "StatusLine":
            if rec.get("context"):
                session["context"] = {**rec["context"], "model": rec.get("model"), "ts": ts}
        elif event == "PreCompact":
            session["compact_ts"] = ts
        elif event not in PASSIVE and pending is not None:
            session["pending"] = None
            self.state["waits"].append({
                "agent": rec.get("agent"), "session_id": rec["session_id"], "started_at": pending["ts"],
                "ended_at": ts, "wait_s": max(0, ts - pending["ts"]) / 1000, "tool": pending.get("tool"),
                "closed_by": event})

    # -- views ----------------------------------------------------------------------------
    def session(self, agent: str | None, session_id: str | None) -> dict | None:
        return self.state["sessions"].get(_key(agent, session_id)) if session_id else None

    def waits(self, since_ms: int = 0, limit: int = 100) -> list[dict]:
        return [w for w in self.state["waits"] if w["ended_at"] >= since_ms][-limit:]

    def pending(self) -> list[dict]:
        out = []
        for key, s in self.state["sessions"].items():
            if s.get("pending"):
                agent, _, sid = key.partition(":")
                out.append({"agent": agent, "session_id": sid, **s["pending"]})
        return sorted(out, key=lambda p: p["ts"])


def context(sample: dict | None, compact_ts: int | None) -> dict | None:
    """Status line ``context_window`` → the realtime ``context`` shape, or None if stale."""
    if not sample or (compact_ts and compact_ts >= sample.get("ts", 0)):
        return None
    window = sample.get("context_window_size")
    used = sample.get("used_tokens")
    if isinstance(sample.get("used_percentage"), (int, float)):
        ratio = sample["used_percentage"] / 100
    elif used is not None and window:
        ratio = used / window
    else:
        return None
    return {"used_tokens": used, "window_tokens": window, "ratio": round(ratio, 4), "basis": "statusline"}


def overlay(tail, info: dict | None) -> None:
    """Before classify: a hook-observed approval wait counts as the pending permission."""
    pending = (info or {}).get("pending")
    if pending and tail.pending_permission is None:
        tail.pending_permission = {"ts": pending["ts"], "command": pending.get("command") or pending.get("tool")}


def refine(state, info: dict | None) -> None:
    """After classify: prefer the status line's own context numbers (exact window size)."""
    if not info:
        return
    ctx = context(info.get("context"), info.get("compact_ts"))
    if ctx is None:
        return
    ctx["auto_compact_ratio"] = (state.context or {}).get("auto_compact_ratio")
    state.context = ctx
    state.flags.discard("context_pressure")
    if ctx["ratio"] >= CONTEXT_PRESSURE and state.state != "idle":
        state.flags.add("context_pressure")


def summary(waits: list[dict]) -> dict:
    values = sorted(w["wait_s"] for w in waits)
    if not values:
        return {"n": 0, "median_s": None, "p90_s": None, "total_s": 0}
    return {"n": len(values), "median_s": values[len(values) // 2],
            "p90_s": values[min(len(values) - 1, int(len(values) * 0.9))], "total_s": round(sum(values), 3)}

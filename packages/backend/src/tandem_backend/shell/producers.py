"""Event-driven notification producers (NT-04): "首次分析完成" and "协作画像已生成".

``AnalysisWatcher.observe`` is a platform bus tap (worker reader threads), so it only
flags work; the check runs on one short-lived thread at a time. Each notification fires
once per home: the notification table itself remembers that it was sent.
"""

from __future__ import annotations

import threading

from . import cached_section, default_scope

READY_SECTIONS = frozenset({"overview", "tasks", "instruction", "preferences"})
DONE = ("completed", "partial")


def already_sent(gw, key: str) -> bool:
    try:
        with gw.appdb.read() as db:
            return db.execute("SELECT 1 FROM notification WHERE dedupe_key = ? LIMIT 1",
                              (key,)).fetchone() is not None
    except Exception:  # noqa: BLE001 - no table yet: treat as unsent.
        return False


def emit(gw, event: dict) -> int | None:
    notifier = getattr(getattr(gw, "platform", None), "notifier", None)
    if notifier is None:
        return None
    try:
        return notifier.emit(event)
    except Exception:  # noqa: BLE001 - producers never fail because of notifications.
        return None


class AnalysisWatcher:
    def __init__(self, gw):
        self.gw = gw
        self.lock = threading.Lock()
        self.running = False
        self.dirty = False

    # -- bus tap -------------------------------------------------------------------------
    def observe(self, topic: str, event: str, data: dict) -> None:
        relevant = (topic == "analysis" and event == "analysis.ready"
                    and data.get("section") in READY_SECTIONS) or (
            topic == "job" and data.get("kind") == "import" and data.get("status") in DONE)
        if relevant:
            self.kick()

    def kick(self) -> None:
        with self.lock:
            if self.running:
                self.dirty = True
                return
            self.running = True
        threading.Thread(target=self._drain, name="shell-watch", daemon=True).start()

    def _drain(self) -> None:
        while True:
            with self.lock:
                self.dirty = False
            try:
                self.check()
            except Exception:  # noqa: BLE001
                pass
            with self.lock:
                if not self.dirty:
                    self.running = False
                    return

    # -- checks (synchronous; tests call this directly) ---------------------------------
    def check(self) -> list[str]:
        gw = self.gw
        sent = []
        stopping = getattr(gw, "stopping", None)
        if stopping is not None and stopping.is_set():
            return sent
        if gw.revisions.snapshot()["data_rev"] is None:
            return sent
        settings = gw.state.snapshot()["settings"]
        scope = default_scope(gw, settings.get("default_range_days") or 30)
        if not already_sent(gw, "analysis_ready"):
            body, freshness, _ = cached_section(gw, "overview", scope)
            if body is not None:
                sessions = ((body.get("overview") or {}).get("counts") or {}).get(
                    "main_sessions")
                emit(gw, {"type": "system", "key": "analysis_ready", "title": "首次分析完成",
                          "body": f"已分析 {sessions} 个会话，可以查看概览了。"
                          if sessions is not None else "可以查看概览了。",
                          "payload": {"data_rev": gw.revisions.snapshot()["data_rev"],
                                      "sessions": sessions}})
                sent.append("analysis_ready")
        if not already_sent(gw, "persona_ready"):
            from .reveal import persona_summary

            persona = persona_summary(gw, scope)
            if persona["ok"]:
                emit(gw, {"type": "system", "key": "persona_ready", "title": "协作画像已生成",
                          "body": f"你的协作类型：{persona['code']}"
                          + (f" {persona['name_zh']}" if persona.get("name_zh") else ""),
                          "payload": {"code": persona["code"]}})
                sent.append("persona_ready")
        return sent

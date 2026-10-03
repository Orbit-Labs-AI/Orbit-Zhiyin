"""AI settings and per (engine × data class) consent.

Default ``mode=stats`` keeps every model call off. Grants are explicit, revocable and
logged in ``ai_consent_log``; ``raw`` (original text) is never sendable to any engine.
"""

from __future__ import annotations

import json
import re
import time

from .errors import AIError

REAL_ENGINES = ("claude_code", "codex", "api_key")
DATA_CLASSES = [
    {"id": "summary", "label": "结构化统计", "desc": "指标、计数、会话行与工具序列，不含原文",
     "allowed_engines": [*REAL_ENGINES, "fake"]},
    {"id": "snippets", "label": "脱敏片段", "desc": "二次脱敏后的少量消息与证据片段",
     "allowed_engines": [*REAL_ENGINES, "fake"]},
    {"id": "rules", "label": "规则文件段落", "desc": "CLAUDE.md / AGENTS.md 等规则文件的相关段落",
     "allowed_engines": [*REAL_ENGINES, "fake"]},
    {"id": "raw", "label": "原文", "desc": "未脱敏的会话原文；永远不发送给任何引擎",
     "allowed_engines": []},
]
CLASS_IDS = tuple(item["id"] for item in DATA_CLASSES)
ALLOWED = {item["id"]: set(item["allowed_engines"]) for item in DATA_CLASSES}
MODES = ("stats", "agent", "api")
# Engines a setting may name (registry.ENGINES; "fake" is the test engine).
KNOWN_ENGINES = (*REAL_ENGINES, "fake")
SLOT_NAMES = ("cheap", "main")
# Model ids are passed to CLIs as `--model <id>` / `-m <id>`: allow only id characters
# (claude-sonnet-5-5, gpt-5.1-codex, claude-opus-5-5[1m], vendor:model) and never a leading
# "-", which the CLI would parse as another option.
MODEL_ID = re.compile(r"^(?!-)[A-Za-z0-9._:\-\[\]]+$")


def _check_slots(slots) -> None:
    if not isinstance(slots, dict):
        raise AIError(422, "invalid_settings", "slots 必须是 {engine: {cheap|main: model}}")
    for engine, by_slot in slots.items():
        if engine not in KNOWN_ENGINES:
            raise AIError(422, "invalid_settings", f"slots 中有未知引擎：{engine}")
        if not isinstance(by_slot, dict):
            raise AIError(422, "invalid_settings", f"slots.{engine} 必须是对象")
        for slot, model in by_slot.items():
            if slot not in SLOT_NAMES:
                raise AIError(422, "invalid_settings", f"slots.{engine} 只能有 cheap / main")
            if model is not None and not (isinstance(model, str) and len(model) <= 128
                                          and MODEL_ID.match(model)):
                raise AIError(422, "invalid_settings", f"slots.{engine}.{slot} 不是合法的模型 id")
DEFAULTS = {"mode": "stats", "default_engine": None, "slots": {}, "daily_usd_cap": 2.0,
            "auto_facet_new": False, "auto_overview": False}
AUTO_KEYS = ("auto_facet_new", "auto_overview")


def now_ms() -> int:
    return int(time.time() * 1000)


class Consent:
    def __init__(self, appdb):
        self.appdb = appdb

    def settings(self) -> dict:
        with self.appdb.read() as db:
            rows = {row["key"]: json.loads(row["value"])
                    for row in db.execute("SELECT key, value FROM ai_setting")}
        return {key: rows.get(key, default) for key, default in DEFAULTS.items()}

    def grants(self, engines=()) -> dict[str, dict[str, bool]]:
        result = {engine: dict.fromkeys(CLASS_IDS, False) for engine in engines}
        with self.appdb.read() as db:
            for row in db.execute("SELECT engine, data_class, granted FROM ai_consent"):
                result.setdefault(row["engine"], dict.fromkeys(CLASS_IDS, False))
                result[row["engine"]][row["data_class"]] = bool(row["granted"])
        return result

    def granted(self, engine: str, data_class: str) -> bool:
        if engine not in ALLOWED.get(data_class, ()):
            return False
        return self.grants().get(engine, {}).get(data_class, False)

    def missing(self, engine: str, pack: dict) -> list[str]:
        """Data classes of enabled pack items that ``engine`` may not receive."""
        grants = self.grants().get(engine, {})
        needed = {item.get("data_class", "summary") for item in pack.get("items", [])
                  if item.get("enabled")}
        return sorted(c for c in needed
                      if engine not in ALLOWED.get(c, ()) or not grants.get(c, False))

    def state(self, engines=()) -> dict:
        settings = self.settings()
        return {"mode": settings["mode"], "default_engine": settings["default_engine"],
                "grants": self.grants(engines), "data_classes": DATA_CLASSES,
                "settings": {key: settings[key]
                             for key in ("daily_usd_cap", "auto_facet_new", "auto_overview", "slots")}}

    def update(self, patch: dict) -> list[tuple[str, str]]:
        """Apply a partial update; returns the (engine, class) pairs that were revoked."""
        settings = dict(patch.get("settings") or {})
        for key in ("mode", "default_engine"):
            if key in patch:
                settings[key] = patch[key]
        unknown = set(settings) - set(DEFAULTS)
        if unknown:
            raise AIError(400, "invalid_request", f"未知设置：{', '.join(sorted(unknown))}")
        if "mode" in settings and settings["mode"] not in MODES:
            raise AIError(400, "invalid_request", "mode 只能是 stats / agent / api")
        if "slots" in settings:
            _check_slots(settings["slots"])
        if settings.get("default_engine") is not None and settings["default_engine"] not in KNOWN_ENGINES:
            raise AIError(422, "invalid_settings", f"未知引擎：{settings['default_engine']}")
        for key in AUTO_KEYS:
            if key in settings and not isinstance(settings[key], bool):
                raise AIError(400, "invalid_request", f"{key} 必须是 true / false")
        if "daily_usd_cap" in settings and not (
                isinstance(settings["daily_usd_cap"], int | float)
                and settings["daily_usd_cap"] >= 0):
            raise AIError(400, "invalid_request", "daily_usd_cap 必须是非负数")
        grants = patch.get("grants") or {}
        for engine, classes in grants.items():
            for data_class, value in (classes or {}).items():
                if data_class not in CLASS_IDS:
                    raise AIError(400, "invalid_request", f"未知数据类：{data_class}")
                if value and engine not in ALLOWED[data_class]:
                    raise AIError(400, "consent_forbidden",
                                  f"{data_class} 不允许发送给 {engine}")
        current = self.grants()
        revoked = []
        at = now_ms()
        with self.appdb.write() as db:
            for key, value in settings.items():
                db.execute("INSERT INTO ai_setting VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE "
                           "SET value = excluded.value, updated_at = excluded.updated_at",
                           (key, json.dumps(value, ensure_ascii=False), at))
            for engine, classes in grants.items():
                for data_class, value in (classes or {}).items():
                    value = bool(value)
                    if current.get(engine, {}).get(data_class, False) == value:
                        continue
                    db.execute("INSERT INTO ai_consent VALUES (?, ?, ?, ?) ON CONFLICT(engine, "
                               "data_class) DO UPDATE SET granted = excluded.granted, "
                               "changed_at = excluded.changed_at",
                               (engine, data_class, int(value), at))
                    db.execute("INSERT INTO ai_consent_log (engine, data_class, granted, at) "
                               "VALUES (?, ?, ?, ?)", (engine, data_class, int(value), at))
                    if not value:
                        revoked.append((engine, data_class))
        return revoked

"""Platform settings in ``app.db`` ``platform_kv`` (JSON values, cached, written through)."""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from pathlib import Path

DEFAULTS = {
    "telemetry": {"enabled": False, "retention_days": 14, "slow_ms": 500, "export_dir": None},
    "flags": {"notifications": True, "slow_log": True, "maintenance": True, "json_logs": True},
    # Recommend memory settings: AI-generated candidates; audience level 0..4 (None = any).
    "recommend": {"ai_generate": False, "level": None},
}


class SettingsError(ValueError):
    pass


class PlatformSettings:
    def __init__(self, appdb):
        self.appdb = appdb
        self.lock = threading.Lock()
        self.cache: dict[str, object] = {}
        with appdb.read() as db:
            for key, value in db.execute("SELECT key, value FROM platform_kv"):
                try:
                    self.cache[key] = json.loads(value)
                except ValueError:
                    continue
        # Merge stored dicts over defaults so new keys appear after upgrades.
        for key, default in DEFAULTS.items():
            stored = self.cache.get(key)
            self.cache[key] = {**default, **stored} if isinstance(stored, dict) else copy.deepcopy(
                default)

    def get(self, key: str, default=None):
        with self.lock:
            value = self.cache.get(key, default)
        return copy.deepcopy(value)

    def put(self, key: str, value) -> None:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self.appdb.write() as db:
            db.execute("INSERT INTO platform_kv VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET "
                       "value=excluded.value, updated_at=excluded.updated_at",
                       (key, text, int(time.time() * 1000)))
        with self.lock:
            self.cache[key] = copy.deepcopy(value)

    def put_telemetry(self, patch: dict) -> dict:
        cfg = self.get("telemetry")
        for key, value in patch.items():
            if key not in cfg:
                raise SettingsError(f"unknown telemetry setting: {key}")
            if key == "enabled":
                if not isinstance(value, bool):
                    raise SettingsError("enabled must be a boolean")
            elif key == "retention_days":
                if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 30:
                    raise SettingsError("retention_days must be 1..30")
            elif key == "slow_ms":
                if not isinstance(value, int) or isinstance(value, bool) or not (
                        50 <= value <= 60_000):
                    raise SettingsError("slow_ms must be 50..60000")
            elif key == "export_dir" and value not in (None, ""):
                path = Path(str(value)).expanduser()
                if not path.is_absolute() or not path.is_dir() or not os.access(path, os.W_OK):
                    raise SettingsError("export_dir must be an existing writable absolute folder")
                value = str(path)
            cfg[key] = value or None if key == "export_dir" else value
        self.put("telemetry", cfg)
        return cfg

    def put_flags(self, patch: dict) -> dict:
        flags = self.get("flags")
        for key, value in patch.items():
            if key not in flags:
                raise SettingsError(f"unknown flag: {key}")
            if not isinstance(value, bool):
                raise SettingsError(f"{key} must be a boolean")
            flags[key] = value
        self.put("flags", flags)
        return flags

    def put_recommend(self, patch: dict) -> dict:
        cfg = self.get("recommend")
        for key, value in patch.items():
            if key == "ai_generate":
                if not isinstance(value, bool):
                    raise SettingsError("ai_generate must be a boolean")
            elif key == "level":
                if value is not None and (not isinstance(value, int) or isinstance(value, bool)
                                          or not 0 <= value <= 4):
                    raise SettingsError("level must be null or 0..4")
            else:
                raise SettingsError(f"unknown recommend setting: {key}")
            cfg[key] = value
        self.put("recommend", cfg)
        return cfg

    def flag(self, name: str) -> bool:
        with self.lock:
            return bool(self.cache["flags"].get(name, False))  # type: ignore[union-attr]

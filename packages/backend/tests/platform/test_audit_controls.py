import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from orbit_backend.platform.settings import PlatformSettings


def test_notifications_obey_real_platform_flags(started):
    settings, notifier = started.settings, started.notifier
    settings.put_flags({"notifications": False})
    id_ = notifier.emit({"type": "waiting", "title": "Synthetic approval", "session_uid": "s1"})
    item = next(row for row in notifier.listing() if row["id"] == id_)
    assert item["state"] == "suppressed"
    assert item["channels"] == [] and item["suppressed_reason"] == "disabled"
    settings.put_flags({"notifications": True})
    id_ = notifier.emit({"type": "waiting", "title": "Synthetic approval", "session_uid": "s2"})
    assert next(row for row in notifier.listing() if row["id"] == id_)["state"] == "delivered"


def test_concurrent_patches_preserve_both_fields(platform_env, monkeypatch):
    settings = platform_env.settings
    first_read, release, second_started = threading.Event(), threading.Event(), threading.Event()
    original = settings.get

    def paused_get(key, default=None):
        value = original(key, default)
        if key == "flags" and not first_read.is_set():
            first_read.set()
            assert release.wait(5)
        return value

    monkeypatch.setattr(settings, "get", paused_get)

    def second():
        second_started.set()
        return settings.put_flags({"slow_log": False})

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(settings.put_flags, {"notifications": False})
        assert first_read.wait(5)
        other = pool.submit(second)
        assert second_started.wait(5)
        try:
            with pytest.raises(TimeoutError):
                other.result(timeout=0.05)
        finally:
            release.set()
        first.result(5)
        other.result(5)
    for cfg in (settings, PlatformSettings(platform_env.appdb)):
        assert cfg.flag("notifications") is False
        assert cfg.flag("slow_log") is False

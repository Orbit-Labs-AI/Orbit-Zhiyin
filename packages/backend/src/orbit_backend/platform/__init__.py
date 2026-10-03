"""Platform: local observability and maintenance (telemetry, logs, health, diagnostics).

Module-level helpers need no gateway and are no-ops until a ``Platform`` starts, so any
area can call them (and its tests can) unconditionally:

    from orbit_backend import platform
    platform.record("recommend.run", ms, scope="all")
    with platform.timed("install.apply"): ...
"""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module

from .telemetry import gauge, record, timed

_platform = None


def get_platform():
    """The running gateway's ``Platform`` (or None)."""
    return _platform


def _set_platform(platform) -> None:
    global _platform
    _platform = platform


def resolve(key: str):
    notifier = getattr(_platform, "notifier", None)
    handler = getattr(notifier, "resolve", None)
    if not callable(handler):
        return None
    try:
        return handler(key)
    except Exception:  # noqa: BLE001
        return None


def register_etag(prefix: str, fn: Callable[[], object], exact: bool = False) -> bool:
    """Let GETs under ``prefix`` answer 304 while ``fn()`` is unchanged (None disables)."""
    if _platform is None:
        return False
    _platform.etag_rules.add(prefix, fn, exact)
    return True


def bump_rev(name: str) -> int:
    """Increment an in-memory revision (use in an ``register_etag`` function via ``token``)."""
    if _platform is None:
        return 0
    return _platform.revisions.bump(name)


def rev_token(*names: str) -> str:
    return _platform.revisions.token(*names) if _platform is not None else ""


# The optional ``.notify`` submodule (platform-notify) would rebind the package attribute
# ``notify`` when first imported; import it first so the function below wins.
try:
    import_module(f"{__name__}.notify")
except ModuleNotFoundError as _error:
    if _error.name != f"{__name__}.notify":
        raise


def notify(event: dict):
    """Route an event to the notification engine if installed (platform-notify)."""
    notifier = getattr(_platform, "notifier", None)
    handler = getattr(notifier, "emit", None)  # Notifier's producer entry is ``emit``.
    if not callable(handler):
        return None
    try:
        return handler(event)
    except Exception:  # noqa: BLE001 - producers never fail because of notifications.
        return None


__all__ = ["bump_rev", "gauge", "get_platform", "notify", "record", "register_etag",
           "resolve", "rev_token", "timed"]

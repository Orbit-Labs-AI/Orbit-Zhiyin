"""Disabled sources hide their sessions by default (SET-07).

Analytics scopes are built by a module-level dependency, so the gateway installs a provider
returning the configured sources (``[{id, enabled}]``). ``default_source_ids`` is ``None``
while every configured source is enabled (scope and scope hash unchanged) and the enabled
ids otherwise; an explicit ``source_ids`` from the caller always wins.
"""

from __future__ import annotations

from collections.abc import Callable

_provider: Callable[[], list[dict]] | None = None


def set_provider(fn: Callable[[], list[dict]] | None) -> None:
    global _provider
    _provider = fn


def configured() -> list[dict]:
    try:
        return list(_provider()) if _provider is not None else []
    except Exception:  # noqa: BLE001 - a missing app state must not break analytics.
        return []


def enabled_source_ids() -> list[str]:
    return sorted(s["id"] for s in configured() if s.get("enabled") and s.get("id"))


def default_source_ids(explicit: list[str] | None = None) -> list[str] | None:
    """``explicit`` when given; otherwise the enabled ids if any source is disabled."""
    if explicit is not None:
        return explicit
    sources = configured()
    if not any(not s.get("enabled") for s in sources):
        return None
    return enabled_source_ids()

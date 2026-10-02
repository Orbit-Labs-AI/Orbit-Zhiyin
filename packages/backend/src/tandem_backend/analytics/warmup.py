"""Warm the App's first screen after an import: default Scope, ``with_text=False``.

``warm`` runs synchronously (CLI/tests); ``start`` runs it once per store in a daemon
thread and ``status`` reports progress. Callers that finish an import (service gateway,
CLI) call ``start(store)``; nothing here runs implicitly.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from .inputs import Scope

FIRST_SCREEN = ("overview", "sessions", "tools", "projects")

_lock = threading.Lock()
_states: dict[str, dict[str, Any]] = {}
_threads: dict[str, threading.Thread] = {}


def _key(store) -> str:
    return str(Path(store.home).resolve())


def _now() -> int:
    return int(time.time() * 1000)


def status(store) -> dict[str, Any]:
    """Progress of the latest warm-up for this store (``idle`` when none ran)."""
    home = getattr(store, "home", None)
    if home is None:
        return {"status": "unsupported"}
    with _lock:
        return dict(_states.get(_key(store), {"status": "idle"}))


def warm(store, sections: tuple[str, ...] = FIRST_SCREEN) -> dict[str, Any]:
    """Compute (or confirm cached) first-screen sections; returns the final state."""
    from .cache import AnalysisCache

    key = _key(store)
    state = {
        "status": "running",
        "sections": list(sections),
        "done": [],
        "started_at": _now(),
        "finished_at": None,
        "error": None,
        "freshness": None,
    }
    with _lock:
        _states[key] = state
    cache = AnalysisCache(store)
    try:
        # One pass shares the bundle, rows and metadata across all first-screen sections.
        result = cache.sections(Scope(), list(sections), with_text=False)
        with _lock:
            state["done"] = list(sections)
            state["freshness"] = result["freshness"]
        with _lock:
            state.update(status="completed", finished_at=_now())
    except Exception as error:  # reported through status(); the App falls back to on demand
        with _lock:
            state.update(
                status="failed", finished_at=_now(), error=f"{type(error).__name__}: {error}"
            )
    with _lock:
        return dict(state)


def start(store, sections: tuple[str, ...] = FIRST_SCREEN) -> dict[str, Any]:
    """Run ``warm`` in the background unless a warm-up for this store is already running."""
    key = _key(store)
    with _lock:
        running = _threads.get(key)
        if running is not None and running.is_alive():
            return dict(_states.get(key, {"status": "running"}))
        _states[key] = {"status": "queued", "sections": list(sections), "done": []}
        thread = threading.Thread(target=warm, args=(store, sections), daemon=True)
        _threads[key] = thread
        thread.start()
        return dict(_states[key])


def wait(store, timeout: float | None = None) -> dict[str, Any]:
    """Block until the background warm-up finishes (tests, CLI)."""
    with _lock:
        thread = _threads.get(_key(store))
    if thread is not None:
        thread.join(timeout)
    return status(store)

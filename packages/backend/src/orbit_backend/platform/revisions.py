"""In-memory revision counters and ETag rules for conditional GETs.

ETags carry the process ``boot`` nonce, so counters restarting at 0 after a relaunch can
never produce a false 304.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable

RevFn = Callable[[], object]


class RevisionRegistry:
    def __init__(self):
        self.boot = secrets.token_hex(3)
        self.lock = threading.Lock()
        self.counters: dict[str, int] = {}

    def bump(self, name: str) -> int:
        with self.lock:
            self.counters[name] = self.counters.get(name, 0) + 1
            return self.counters[name]

    def token(self, *names: str) -> str:
        with self.lock:
            return "|".join(f"{n}.{self.counters.get(n, 0)}" for n in names)

    def snapshot(self) -> dict:
        with self.lock:
            return {"boot": self.boot, **self.counters}


class EtagRules:
    """Path prefix → revision function; longest prefix wins, ``exact`` matches only itself."""

    def __init__(self):
        self.rules: list[tuple[str, RevFn, bool]] = []

    def add(self, prefix: str, fn: RevFn, exact: bool = False) -> None:
        self.rules = [r for r in self.rules if r[0] != prefix] + [(prefix, fn, exact)]
        self.rules.sort(key=lambda r: len(r[0]), reverse=True)

    def match(self, path: str) -> RevFn | None:
        for prefix, fn, exact in self.rules:
            if path == prefix or (not exact and path.startswith(prefix.rstrip("/") + "/")):
                return fn
        return None

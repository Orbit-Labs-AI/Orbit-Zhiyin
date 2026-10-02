"""Feature layer: shared vocabulary (DT-13), cross-database reads, session features and
the user profile, plus linked inventory and search when those modules are present.

Other modules call the module-level helpers after ``routes_features.router(gw)`` bound a
``FeatureService``; they raise ``RuntimeError`` when nothing is bound.
"""

from __future__ import annotations

from typing import Any

_service: Any = None


def bind(svc) -> None:
    global _service
    _service = svc


def get():
    if _service is None:
        raise RuntimeError("FeatureService 未绑定")
    return _service


def profile(scope=None, **kw) -> dict:
    return get().profile(scope, **kw)


def linked_inventory(scope=None, **filters) -> dict:
    return get().linked_inventory(scope, **filters)


def search(q: str, kinds=None, scope=None, limit: int = 20) -> dict:
    return get().search(q, kinds=kinds, scope=scope, limit=limit)


def match_items(profile_body: dict, **kw) -> list[dict]:
    return get().match(profile_body, **kw)


def vocab() -> dict:
    from .vocab import vocab_table

    return vocab_table()

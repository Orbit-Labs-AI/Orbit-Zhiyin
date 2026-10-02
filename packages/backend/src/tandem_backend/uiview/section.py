"""``uiview_facts`` analysis section (runs in the analysis worker, never in the gateway).

Reuses the memoised analysis (``memo.analysis``) and adds read-only L1 SQL through
``store.connect()``. The snapshot cache keeps the body, so A1 / A2 / Lite payloads are
re-derived in the gateway in milliseconds for any filter, window or brush.

Wiring (one line each, owned by the integrator): ``services/sections.py`` imports this
module; ``services/gateway.py`` adds ``routes_uiview`` to its router tuple.
"""

from __future__ import annotations

from ..services.sections import Section, register
from .facts import build_facts

SECTION = "uiview_facts"


def compute(store, scope, params, memo) -> dict:
    result = memo.analysis(store, scope, False, params.get("_rev"))
    with store.connect() as conn:
        return build_facts(conn, result, scope)


register(Section(SECTION, SECTION, "heavy", compute, False))

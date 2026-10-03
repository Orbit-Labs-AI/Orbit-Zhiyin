"""``uiview_facts`` analysis section (runs in the analysis worker, never in the gateway).

Reads the analysis sections it needs through ``memo.sections`` (the read-through cache,
shared with the analytics sections of the same scope) and adds read-only L1 SQL through
``store.connect()``. The snapshot cache keeps the body, so A1 / A2 / Lite payloads are
re-derived in the gateway in milliseconds for any filter, window or brush.

Wiring (one line each, owned by the integrator): ``services/sections.py`` imports this
module; ``services/gateway.py`` adds ``routes_uiview`` to its router tuple.
"""

from __future__ import annotations

from ..services.sections import WITH_TEXT, Section, register
from .facts import build_facts

SECTION = "uiview_facts"
# What build_facts reads; bottleneck_recommendations computes the rest of the analysis,
# which the cache stores for the analytics sections of the same scope.
INPUTS = ["sessions", "overview", "instruction", "tasks", "bottleneck_recommendations"]


def compute(store, scope, params, memo) -> dict:
    result = memo.sections(store, scope, INPUTS, WITH_TEXT, params.get("_rev"))
    with store.connect() as conn:
        return build_facts(conn, result, scope)


register(Section(SECTION, SECTION, "heavy", compute, False))

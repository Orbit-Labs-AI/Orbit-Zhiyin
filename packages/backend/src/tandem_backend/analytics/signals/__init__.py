"""Cross-family signal layer: eight-family facts → signal → problem / key moment / outcome.

Not a ninth family: it only reads ``AnalysisContext`` and (optionally) an
``analyze_context`` result, and never mutates either. See
``docs/modules/analytics/signals.md`` for the closed vocabulary and versions.
"""

from dataclasses import dataclass, field
from typing import Any

from ..context import AnalysisContext
from .detectors import SessionView, build_views, detect_all
from .facts import session_facts
from .moments import key_moments
from .outcome import synthesize_outcome
from .problems import upgrade_problems

Record = dict[str, Any]


@dataclass
class SignalLayer:
    views: list[SessionView]
    detected: dict[str, dict[str, list[Record] | None]]
    signals: list[Record]
    outcomes: dict[str, Record]
    facts: dict[str, Record]
    moments: dict[str, Record]
    calls: list[Record] | None = field(default=None)

    def problems(self, labels: list[Record] | None = None, **kw) -> Record:
        return upgrade_problems(self.signals, list(self.facts.values()), labels=labels, **kw)


def build_signal_layer(context: AnalysisContext, result: Record | None = None, *,
                       facets: dict[str, str] | None = None) -> SignalLayer:
    """Run every detector once per root session tree and derive the downstream rows."""
    views = build_views(context, result)
    detected, signals, outcomes, facts, moments = {}, [], {}, {}, {}
    calls: list[Record] | None = [] if views else None
    for view in views:
        sid = view.session_uid
        detected[sid] = detect_all(view)
        signals.extend(s for rows in detected[sid].values() for s in rows or [])
        outcomes[sid] = synthesize_outcome(view, detected[sid], (facets or {}).get(sid))
        facts[sid] = session_facts(view, detected[sid], outcomes[sid])
        moments[sid] = key_moments(view, detected[sid], outcomes[sid])
        if view.calls is None:
            calls = None
        elif calls is not None:
            calls.extend(view.calls)
    return SignalLayer(views, detected, signals, outcomes, facts, moments, calls)


__all__ = ["SignalLayer", "build_signal_layer"]

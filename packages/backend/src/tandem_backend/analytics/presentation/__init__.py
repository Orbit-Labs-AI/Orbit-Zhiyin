"""Versioned, deterministic feature-to-display rules; no new extraction or model calls."""

PRESENTATION_VERSION = "presentation-v2"


# Per-call evidence in the presentation: one ref per adjacent call pair (transitions), per
# success/failed call (success_rate and error_rate, globally and per tool) and per finding,
# repeated in the overview, every project and every session. Measured ≈ 1 KB per call
# across the three layers, so the snapshot grows without bound; aggregates are computed
# before the cap and stay exact, ``<key>_total`` keeps the true length.
PRESENTATION_CAPPED_KEYS = frozenset({"evidence_refs", "retry_links", "subagent_relations"})


def build_presentation(analysis):
    from .service import build_presentation as build

    return build(analysis)


def bounded_presentation(analysis):
    """``build_presentation`` with evidence arrays capped like the products payload."""
    from ..products.payload import CAPPED_KEYS, compact

    return compact(build_presentation(analysis), keys=CAPPED_KEYS | PRESENTATION_CAPPED_KEYS)


__all__ = ["PRESENTATION_VERSION", "bounded_presentation", "build_presentation"]

"""Versioned, deterministic feature-to-display rules; no new extraction or model calls."""

PRESENTATION_VERSION = "presentation-v2"


def build_presentation(analysis):
    from .service import build_presentation as build

    return build(analysis)


__all__ = ["PRESENTATION_VERSION", "build_presentation"]

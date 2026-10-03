"""Opt-in, bounded semantic parsing; ordinary analysis never calls a model."""

from .candidates import Budget, cache_identity, select_candidates
from .pipeline import attach_cache, observation_for, run_cascade
from .schema import EFFORT, MODEL, PROMPT_VERSION, SCHEMA_VERSION, BatchResult

__all__ = [
    "Budget",
    "BatchResult",
    "EFFORT",
    "MODEL",
    "PROMPT_VERSION",
    "SCHEMA_VERSION",
    "attach_cache",
    "cache_identity",
    "observation_for",
    "run_cascade",
    "select_candidates",
]

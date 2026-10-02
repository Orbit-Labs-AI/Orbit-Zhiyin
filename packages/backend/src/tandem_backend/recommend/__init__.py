"""Recommendation pipeline; the historic profile API remains compatible."""

from .legacy import recommend, trial_method

__all__ = ["recommend", "trial_method"]

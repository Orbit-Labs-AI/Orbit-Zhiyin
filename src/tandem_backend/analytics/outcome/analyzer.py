"""Objective outcome composition entry point with compatible public imports."""

from collections import Counter

from .acceptance import (
    collect_acceptance_criteria,
    match_acceptance_criteria,
    summarize_objective_outcomes,
)
from .validation import extract_validation_runs, legacy_objective_candidates


def analyze_outcome(calls, events, main_ids, until_ts=None, dataset_status="available"):
    extracted = extract_validation_runs(calls, until_ts)
    criteria = collect_acceptance_criteria(events, main_ids, until_ts)
    accepted = match_acceptance_criteria(criteria["criteria"], extracted["validation_runs"])
    return {"status": dataset_status if calls is not None else "unavailable", "grain": "validation/criterion",
            **extracted, "acceptance_results": accepted,
            "unusable_criteria_events": criteria["unusable_criteria_events"],
            "validation_result_counts": dict(Counter(r["validation_result"] for r in extracted["validation_runs"] or [])) if calls is not None else None,
            **summarize_objective_outcomes(accepted)}


__all__ = ['analyze_outcome', 'collect_acceptance_criteria', 'extract_validation_runs', 'legacy_objective_candidates', 'match_acceptance_criteria', 'summarize_objective_outcomes']

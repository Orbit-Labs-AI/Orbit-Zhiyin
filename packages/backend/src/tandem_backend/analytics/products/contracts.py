"""Small shared contracts for UI products, with explicit measurement limits."""

from typing import Literal, TypedDict

from tandem_data.coverage import COVERAGE_CONTRACT

PRODUCT_VERSION = "analysis-products-v1"
RULE_VERSIONS = {
    "coverage": COVERAGE_CONTRACT,
    "products": PRODUCT_VERSION,
    "tools": "tool-sequence-v1",
    "emotion": "explicit-emotion-v1",
    "journey": "journey-v1",
    "habits": "observed-habits-v1",
    "trends": "calendar-trends-v1",
    "instruction": "instruction-v1",
    "task": "task-v1",
    "preference": "preference-v1",
    "interaction": "bottleneck-features-v1",
    "respond": "bottleneck-features-v1",
    "cost_time": "bottleneck-features-v1",
    "outcome": "bottleneck-features-v1",
    "outcome_subjective": "subjective-outcome-v1",
    "lexical": "lexical-v1",
    "statistics": "descriptive-statistics-v1",
}


def rule_versions() -> dict[str, str]:
    """Every rule version that shapes a cached analysis section or served snapshot.

    ``RULE_VERSIONS`` holds the feature/product families declared here; the work graph,
    presentation projection, presentation diagnostics and the recommendation pipeline own
    their version constants in their own modules. They are read at call time (lazy imports,
    no import cycle), so bumping any of them changes ``algo_version()``, ``rules_digest()``,
    ``analysis_digest`` and ``meta.analysis_methods``.
    """
    from ...recommend import contracts as recommend_contracts
    from .. import presentation
    from ..presentation import diagnostics as presentation_diagnostics
    from ..recommendations import policy
    from ..work_graph import index as work_graph_index

    return {
        **RULE_VERSIONS,
        "work_graph": work_graph_index.WORK_GRAPH_VERSION,
        "presentation": presentation.PRESENTATION_VERSION,
        "presentation_diagnostics": presentation_diagnostics.RULE_VERSION,
        "bottleneck_recommendations": policy.ALGORITHM_VERSION,
        "recommendation_pipeline": recommend_contracts.RESULT_VERSION,
    }


class Metric(TypedDict):
    value: int | float | None
    unit: str
    effective_n: int
    unknown_n: int | None
    status: Literal["available", "partial", "unavailable", "excluded"]
    basis: str


def metric(
    value: int | float | None,
    unit: str,
    effective_n: int,
    unknown_n: int | None = 0,
    *,
    basis: str = "observed",
    status: str = "available",
) -> Metric:
    """Keep a known subset visible without presenting it as the full population."""
    state: Literal["available", "partial", "unavailable", "excluded"]
    if status == "excluded":
        state = "excluded"
    elif status == "unavailable" or value is None:
        state = "unavailable"
    elif status == "partial" or unknown_n:
        state = "partial"
    else:
        state = "available"
    return {
        "value": value,
        "unit": unit,
        "effective_n": effective_n,
        "unknown_n": unknown_n,
        "status": state,
        "basis": basis,
    }

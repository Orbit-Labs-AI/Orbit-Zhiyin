"""Explicit extension boundary for three separate semantic recall spaces.

No model is downloaded or called by this module. The P0 service uses the
disabled status until an embedding backend and a reviewed catalogue index are
provided deliberately. A backend is responsible for retrieval inside each
named field and must not mix vectors produced by different model revisions.
"""

from typing import Literal, Protocol

from ..contracts import RecommendationItem, RecommendationState

DenseField = Literal["task", "trigger", "capability"]
FIELDS: tuple[DenseField, ...] = ("task", "trigger", "capability")


class DenseBackend(Protocol):
    """Future injection contract; model revision and dimension identify a space.

    Implementations must validate finite nonzero vectors, consistent dimensions
    and the same space_id for query and catalogue vectors before scoring.
    The backend's lifecycle and consent for network use belong to its caller.
    """

    space_id: str
    dimensions: int

    def recall(self, *, field: DenseField, query: str,
               items: list[RecommendationItem], limit: int) -> list[tuple[str, float]]:
        """Return a finite, nonnegative, descending relevance list for one field."""
        ...


def status() -> dict[str, object]:
    return {"enabled": False, "status": "disabled", "fields": list(FIELDS),
            "reason": "No embedding backend is configured; offline recall remains available."}


def queries(state: RecommendationState) -> dict[DenseField, str]:
    """Keep task, observed trigger, and desired intervention in separate routes."""
    return {"task": state.task_text, "trigger": state.problem_text,
            "capability": state.desired_effect_text}

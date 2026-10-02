"""Context relevance is candidate discovery, never bottleneck evidence."""

from ..contracts import RecommendationItem, RecommendationState
from ._common import names, ranked


def recall(state: RecommendationState, items: list[RecommendationItem],
           limit: int = 50) -> list[tuple[str, float]]:
    """Recall from explicitly known compatible environment dimensions.

    A missing dimension adds no match. Unavailable requirements or explicitly
    incompatible agents are removed later by hard filters, not by this route.
    Generic support alone provides no discriminative context match.
    """
    context = state.context_state
    scores: dict[str, float] = {}
    for item in items:
        compared: list[float] = []
        if context.agent != "generic" and item.compatibility.agents:
            support = item.compatibility.agents.get(context.agent)
            compared.append({"native": 1., "manual": .8, "adaptation_required": .4}.get(support, 0.))
        if context.os and item.compatibility.os:
            compared.append(float(context.os.strip().casefold() in names(item.compatibility.os)))
        for actual, supported in ((context.languages, item.compatibility.languages),
                                  (context.frameworks, item.compatibility.frameworks),
                                  (context.tools, item.requirements.tools),
                                  (context.software, item.requirements.software)):
            desired = names(supported)
            if actual is not None and desired:
                compared.append(len(names(actual) & desired) / len(desired))
        # Family-specific identifiers remain exact metadata matches; they are
        # deliberately not interpreted as semantic descriptions of a problem.
        for actual, expected in ((context.model, item.family_features.get("model")),
                                 (context.repository, item.family_features.get("repository"))):
            if actual and isinstance(expected, str) and expected.strip():
                compared.append(float(actual.strip().casefold() == expected.strip().casefold()))
        score = sum(compared) / len(compared) if compared else 0.
        scores[item.identity.id] = max(scores.get(item.identity.id, 0.), score)
    return ranked(scores, limit)

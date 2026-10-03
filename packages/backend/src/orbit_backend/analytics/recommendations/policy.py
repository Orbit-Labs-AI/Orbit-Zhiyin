"""Versioned, inspectable heuristics; thresholds are not learned effect estimates."""

from dataclasses import dataclass, fields

ALGORITHM_VERSION = "bottleneck-recommendations-v2"  # v2: retry coverage, repeat evidence


@dataclass(frozen=True)
class RecommendationPolicy:
    correction_min_count: int = 3
    intent_min_samples: int = 8
    correction_min_rate: float = .25
    annotation_min_coverage: float = .6
    repeated_min_count: int = 2
    requirement_min_samples: int = 4
    retry_min_count: int = 2
    tool_failure_min_count: int = 3
    tool_min_samples: int = 10
    tool_failure_min_rate: float = .2
    tool_min_coverage: float = .7
    validation_failure_min_count: int = 2
    acceptance_gap_min_count: int = 2
    token_min_requests: int = 5
    uncached_input_min_tokens: int = 20000
    input_min_share: float = .8

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if f.type is int:
                valid = isinstance(value, int) and not isinstance(value, bool) and value > 0
            else:
                valid = isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= 1
            if not valid:
                raise ValueError(f"Invalid recommendation threshold: {f.name}")

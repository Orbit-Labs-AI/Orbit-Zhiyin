"""Translate existing bottleneck results; no dependency on an analysis implementation."""

from .contracts import Feature, MatchRequest


def requests_from_analysis(analysis: dict, *, agent: str = "codex", limit: int = 10) -> list[MatchRequest]:
    return [MatchRequest(
        text=bottleneck["reason"], purpose="recommendation", problem_id=bottleneck["id"],
        problem_type=bottleneck["type"], scene=bottleneck["scene"], language=bottleneck.get("language"),
        agents=[agent], evidence_ids=bottleneck["evidence_ids"],
        profile_evidence_ids=bottleneck["profile_evidence_ids"],
        features=[Feature(feature="dimension", value=d) for d in bottleneck["dimensions"]], limit=limit,
    ) for bottleneck in analysis["bottlenecks"]]

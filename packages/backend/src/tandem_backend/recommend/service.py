"""One deterministic entry point from scoped analytics to actionable trials."""

from copy import deepcopy
from dataclasses import asdict

from pydantic import ValidationError

from ..analytics.recommendations.policy import RecommendationPolicy
from .catalog import load_catalog
from .contracts import FAMILIES, RankingPolicy, RecommendationContext, RecommendationResult
from .explain import KINDS, explain_candidate
from .families import prepare_item
from .features import candidate_features
from .ranking.diversity import select_diverse
from .ranking.filters import filter_item
from .ranking.score import score_candidate
from .recall import context as context_recall
from .recall import dense, effect, rules, sparse
from .recall.fusion import fuse
from .state import build_states


def recommend(analytics_result, bottlenecks=None, context=None, limit=6, *, catalog=None, catalog_directory=None,
              family=None, kind=None, policy=None, ranking_policy=None, include_legacy=True):
    """Receive reviewed items or a partial catalogue directory, never fetch/install.

    Explicit ``catalog=[]`` or an empty ``catalog_directory`` stays empty.
    Environment inventories use None=unknown and []=known empty. A supplied
    diagnosis must be made from the same scoped feature snapshot.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError("Recommendation limit must be between 1 and 20")
    if family is not None and family not in FAMILIES:
        raise ValueError("Unknown recommendation family")
    if kind is not None and kind not in set(KINDS.values()) | {"agent"}:
        raise ValueError("Unknown resource kind")
    policy = policy or RecommendationPolicy()
    ranking_policy = RankingPolicy.model_validate(ranking_policy or {}) if not isinstance(ranking_policy, RankingPolicy) else ranking_policy
    context = RecommendationContext.model_validate(context or {}) if not isinstance(context, RecommendationContext) else context
    state_build = build_states(analytics_result, bottlenecks, context, policy)
    loaded = load_catalog(directory=catalog_directory, items=catalog, include_legacy=include_legacy)
    diagnostics, excluded, prepared, decisions, pending = deepcopy(loaded.diagnostics), [], {}, {}, {}
    for item in loaded.items:
        if family is not None and item.family != family or kind is not None and (item.legacy_kind or KINDS[item.family]) != kind:
            continue
        try:
            item, family_pending = prepare_item(item)
        except (ValidationError, ValueError, TypeError):
            excluded.append({"resource_id": item.identity.id, "reason": "invalid_family_features"})
            continue
        decision = filter_item(item, context)
        if not decision.eligible:
            excluded.append({"resource_id": item.identity.id, "reason": "hard_filter", "details": decision.reasons})
            continue
        prepared[item.identity.id], decisions[item.identity.id], pending[item.identity.id] = item, decision, family_pending
    # Remove known unusable items BEFORE capped recall, so they cannot crowd out
    # compatible items. Unknown prerequisites stay explicit for explanation.
    items, ranked = list(prepared.values()), []
    for state in state_build.states:
        if not state.signals:
            continue
        routes = {"rules": rules.recall(state, items, ranking_policy.per_route),
                  "sparse": sparse.recall(state, items, ranking_policy.per_route),
                  "effect": effect.recall(state, items, ranking_policy.per_route),
                  "context": context_recall.recall(state, items, ranking_policy.per_route)}
        for candidate in fuse(routes, k=ranking_policy.rrf_k):
            item = prepared[candidate.item_id]
            candidate_state = state
            if item.legacy_kind:
                # Legacy effect maps are broad. Keep the original reviewed
                # capability condition, especially for different friction types.
                own = [s for s in state.signals if set(s["capabilities"]) & set(item.capability.tags)]
                candidate_state = state.model_copy(deep=True)
                candidate_state.signals = own
                candidate_state.bottleneck_vector = {rule: value for rule, value in state.bottleneck_vector.items()
                                                     if any(s["rule_id"] == rule for s in own)}
            features = candidate_features(candidate_state, item, candidate, decisions[item.identity.id],
                                          fusion_upper_bound=len(routes) / (ranking_policy.rrf_k + 1))
            score, breakdown = score_candidate(features, ranking_policy)
            if score <= 0:
                continue
            signal = next(s for s in candidate_state.signals if s["signal_id"] == features["primary_signal_id"])
            ranked.append({"item": item, "candidate": candidate, "features": features, "score": score,
                           "score_breakdown": breakdown, "filter": decisions[item.identity.id], "signal": signal,
                           "state": candidate_state, "family_pending": pending[item.identity.id]})
    cards = [explain_candidate(row) for row in select_diverse(ranked, limit, ranking_policy)]
    status = ("ready" if cards else "no_matching_resources" if state_build.signals else "insufficient_evidence"
              if not state_build.assessments or all(a["status"] == "insufficient_evidence" for a in state_build.assessments) else "no_threshold_met")
    diagnostics.append({"source": "dense", **dense.status()})
    return RecommendationResult(
        status=status, recommendations=cards, signals=state_build.signals, assessments=state_build.assessments,
        states=[state.model_dump(mode="json") for state in state_build.states], diagnostics=diagnostics,
        policy=asdict(policy), ranking_policy=ranking_policy.model_dump(), target_agent=context.agent, kind=kind, family=family,
        catalog_digest=loaded.digest, analysis_digest=analytics_result.get("analysis_digest"), scope=analytics_result.get("scope"),
        excluded_resources=excluded + [{"resource_id": d.get("resource_id"), "reason": d["reason"]} for d in loaded.diagnostics
                                      if d.get("resource_id") and d["reason"] != "draft"],
        limitations=["阈值和权重为初始启发式，需在获授权的评测集上校准。", "效果权重代表改善方向的相关先验，不是已测量收益。",
                     "向量召回、自动抓取及 LLM 重排未启用；运行时不下载、安装或执行资源。",
                     "来源核验是目录声明的版本快照；实际环境条件仍需确认。"],
    ).model_dump(mode="json")

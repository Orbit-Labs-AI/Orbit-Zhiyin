"""Public recommendation entry point for the already scoped feature result."""

from copy import deepcopy
from dataclasses import asdict

from .catalog import KINDS, TARGETS, digest, load_catalog, vetted_catalog
from .policy import ALGORITHM_VERSION, RecommendationPolicy
from .ranking import rank_resources
from .rules import RULE_IDS, evaluate_features


def recommend_bottlenecks(analysis, target_agent="generic", catalog=None, policy=None, limit=6, kind=None):
    """Return opportunities, abstentions and actionable trials without IO or mutation.

    ``analysis`` is the result of analytics.service.analyze_bundle/analyze_store.
    Pass vetted resource metadata via ``catalog`` to override the bundled catalogue.
    No network, raw-history reads, LLM calls, installs or estimated savings occur.
    """
    if target_agent not in TARGETS or kind is not None and kind not in KINDS:
        raise ValueError("Unknown target_agent or resource kind")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise ValueError("Recommendation limit must be between 1 and 20")
    policy = policy or RecommendationPolicy()
    if not isinstance(policy, RecommendationPolicy):
        raise ValueError("policy must be a RecommendationPolicy")
    resources, excluded = vetted_catalog(load_catalog() if catalog is None else catalog)
    signals, assessments = [], []
    # Recompute decisions within each root tree. Aggregates can hide cross-task
    # coincidence and must not be used to manufacture sufficient sample sizes.
    roots = analysis.get("sessions")
    top = analysis.get("bottleneck_features")
    if top is not None and top.get("schema_version") != "bottleneck-features-v1":
        raise ValueError("Unsupported bottleneck feature schema")
    scopes = [(r.get("bottleneck_features"), {"root_session_uid": r["session_uid"],
                "project_id": r.get("project_id"), "included_session_uids": r.get("included_session_uids", [r["session_uid"]])})
              for r in roots or []]
    if not scopes:
        # An empty root list may still have orphan child calls in the aggregate.
        # Those calls cannot be pooled to manufacture a qualified root sample.
        assessments = [{"rule_id": rule, "status": "insufficient_evidence", "reason": "没有可独立分析的根会话，不能用跨根聚合补足样本。",
                        "scope": {"root_session_uid": None, "included_session_uids": []}} for rule in RULE_IDS]
    for features, context in scopes:
        if features is None:
            continue
        if features.get("schema_version") != "bottleneck-features-v1":
            raise ValueError("Unsupported bottleneck feature schema")
        found, checks = evaluate_features(features, policy, context)
        signals.extend(found)
        assessments.extend(checks)
    signals.sort(key=lambda s: (s["rule_id"], s["signal_id"]))
    assessments.sort(key=lambda a: (a["rule_id"], a["scope"]["root_session_uid"] or ""))
    recommendations = rank_resources(signals, resources, target_agent, limit, kind)
    status = ("ready" if recommendations else "no_matching_resources" if signals else "insufficient_evidence"
              if not assessments or all(a["status"] == "insufficient_evidence" for a in assessments) else "no_threshold_met")
    return deepcopy({"schema_version": ALGORITHM_VERSION, "status": status, "target_agent": target_agent,
        "kind": kind, "policy": asdict(policy), "catalog_digest": digest(sorted(resources, key=lambda r: r["id"])),
        "analysis_digest": analysis.get("analysis_digest"), "scope": analysis.get("scope"),
        "signals": signals, "assessments": assessments, "recommendations": recommendations,
        "excluded_resources": excluded,
        "limitations": ["阈值和权重为初始启发式，需在获授权的评测集上校准。",
                        "推荐表示值得试验，不表示已证明因果或效率收益。",
                        "资源记录核验时的版本，运行时不联网；升级前应重新审核固定版本与兼容性。"]})

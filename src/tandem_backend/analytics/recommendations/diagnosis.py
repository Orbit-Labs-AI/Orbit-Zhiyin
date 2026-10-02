"""Reuse the existing evidence rules independently of resource recommendation."""

from copy import deepcopy

from .catalog import digest
from .policy import RecommendationPolicy
from .rules import RULE_IDS, evaluate_features


def feature_digest(analysis):
    return digest({"scope": analysis.get("scope"), "roots": [
        {"session_uid": r["session_uid"], "bottleneck_features": r.get("bottleneck_features")}
        for r in analysis.get("sessions") or []]})


def diagnose_bottlenecks(analysis, policy=None):
    policy = policy or RecommendationPolicy()
    if not isinstance(policy, RecommendationPolicy):
        raise ValueError("policy must be a RecommendationPolicy")
    top = analysis.get("bottleneck_features")
    if top is not None and top.get("schema_version") != "bottleneck-features-v1":
        raise ValueError("Unsupported bottleneck feature schema")
    signals, assessments = [], []
    for row in analysis.get("sessions") or []:
        features = row.get("bottleneck_features")
        context = {"root_session_uid": row["session_uid"], "project_id": row.get("project_id"),
                   "included_session_uids": row.get("included_session_uids", [row["session_uid"]])}
        if features is None:
            assessments.extend({"rule_id": rule, "status": "insufficient_evidence", "reason": "缺少本根会话的瓶颈特征。",
                                "scope": context} for rule in RULE_IDS)
            continue
        if features.get("schema_version") != "bottleneck-features-v1":
            raise ValueError("Unsupported bottleneck feature schema")
        found, checks = evaluate_features(features, policy, context)
        signals.extend(found)
        assessments.extend(checks)
    if not analysis.get("sessions"):
        assessments = [{"rule_id": rule, "status": "insufficient_evidence", "reason": "没有可独立分析的根会话，不能用跨根聚合补足样本。",
                        "scope": {"root_session_uid": None, "included_session_uids": []}} for rule in RULE_IDS]
    return deepcopy({"signals": sorted(signals, key=lambda s: (s["rule_id"], s["signal_id"])),
                     "assessments": sorted(assessments, key=lambda a: (a["rule_id"], a["scope"]["root_session_uid"] or "")),
                     "scope": analysis.get("scope"), "analysis_digest": analysis.get("analysis_digest"),
                     "feature_digest": feature_digest(analysis)})

"""Transparent trial priority, never a predicted percentage improvement."""

from collections import Counter
from copy import deepcopy

from .catalog import digest

COMPATIBILITY = {"native": 1., "manual": 1., "adaptation_required": .55}
EASE = {"low": 1., "medium": .6, "high": .3}


def rank_resources(signals, resources, target_agent, limit, kind):
    candidates = []
    for signal in signals:
        for resource in resources:
            if kind and resource["kind"] != kind:
                continue
            compatibility = resource["compatibility"].get(target_agent, "unsupported")
            if compatibility not in COMPATIBILITY:
                continue
            matched = sorted(set(signal["capabilities"]) & set(resource["capabilities"]))
            if not matched:
                continue
            # Capabilities represent alternative interventions, not an AND checklist.
            fit = 1.
            components = {"capability_fit": fit, "evidence_confidence": signal["confidence"],
                          "compatibility_factor": COMPATIBILITY[compatibility], "severity": signal["severity"],
                          "recurrence": signal["recurrence"], "setup_ease": EASE[resource["effort"]]}
            score = 100 * fit * signal["confidence"] * COMPATIBILITY[compatibility] * (
                .60 * signal["severity"] + .25 * signal["recurrence"] + .15 * EASE[resource["effort"]])
            source = {k: resource[k] for k in ("origin", "url", "source_path", "verified_sha", "blob_sha",
                                              "content_sha256", "verification", "verified_at", "license") if k in resource}
            if resource["origin"] == "github":
                source["source_url"] = f'{resource["url"]}/blob/{resource["verified_sha"]}/{resource["source_path"]}'
            candidates.append({
                "id": digest([signal["signal_id"], resource["id"], target_agent]),
                "resource_id": resource["id"], "name": resource["name"], "kind": resource["kind"],
                "target_agent": target_agent, "compatibility": compatibility,
                "recommendation_status": "adaptation_required" if compatibility == "adaptation_required" else "trial",
                "priority_score": round(score, 2), "score_breakdown": components,
                "score_meaning": "启发式试用优先级，非效果百分比或成功概率",
                "signal_id": signal["signal_id"], "rule_id": signal["rule_id"], "reason": signal["reason"],
                "metrics": signal["metrics"], "evidence": signal["evidence"], "scope": signal["scope"],
                "matched_capabilities": matched, "hypothesis": signal["hypothesis"], "effect_status": "unmeasured",
                "evaluation_plan": {"target_metrics": signal["evaluation_metrics"],
                    "baseline": "固定任务、输入、验收范围与模型配置；对照启用前后，分别记录重复试验。",
                    "guardrails": ["验收通过率和验证覆盖不得下降。", "新增配置、验证、Token 和耗时均计入成本。"],
                    "observed_effect": None},
                "source": source, "summary": resource["summary"], "setup_steps": resource["setup_steps"],
                "preview": resource["preview"], "limitations": resource["limitations"], "trial": resource["trial"],
            })
    candidates.sort(key=lambda c: (-c["priority_score"], c["rule_id"], c["resource_id"], c["signal_id"]))
    selected, seen, counts = [], set(), Counter()
    for card in candidates:
        # Avoid flooding the UI with resources for one problem or repeating a resource.
        if card["resource_id"] in seen or counts[card["rule_id"]] >= 2:
            continue
        selected.append(card)
        seen.add(card["resource_id"])
        counts[card["rule_id"]] += 1
        if len(selected) >= limit:
            break
    return deepcopy(selected)

"""Build explanations from observed signals, never from invented causal claims."""

from urllib.parse import quote

from ..analytics.recommendations.catalog import digest

KINDS = {"rules_prompts": "prompt", "skills": "skill", "plugins": "plugin", "mcp": "mcp",
         "hooks": "hook", "model_configs": "model_config", "workflows": "workflow"}


def explain_candidate(row):
    item, signal, features = row["item"], row["signal"], row["features"]
    decision, state = row["filter"], row["state"]
    pending = sorted(set(decision.pending_requirements + row.get("family_pending", [])))
    source = item.source.model_dump(exclude_none=True)
    if item.source.origin == "github":
        source["source_url"] = f"{item.source.url.rstrip('/')}/blob/{item.source.verified_sha}/{quote(item.source.source_path, safe='/')}"
    status = ("needs_context" if pending else "adaptation_required"
              if decision.compatibility == "adaptation_required" else "trial")
    matched = [s for s in state.signals if s["signal_id"] in features["grounded_signal_ids"]]
    references = {(r["kind"], r["session_uid"], r["id"]): r for s in matched for r in s["evidence"]}
    return {
        "id": digest([state.root_session_uid, signal["signal_id"], item.identity.id, state.context_state.agent]),
        "resource_id": item.identity.id, "name": item.identity.name, "family": item.family,
        "kind": item.legacy_kind or KINDS[item.family], "target_agent": state.context_state.agent,
        "compatibility": "unknown" if pending else decision.compatibility,
        "declared_compatibility": decision.compatibility, "recommendation_status": status,
        "pending_requirements": pending, "priority_score": round(row["score"] * 100, 2),
        "score_meaning": "启发式试用优先级，不是效果百分比或成功概率",
        "score_breakdown": row["score_breakdown"], "candidate_features": features,
        "recall": {"scores": row["candidate"].route_scores, "ranks": row["candidate"].route_ranks,
                   "rrf_score": row["candidate"].fusion_score},
        "diversity": {"mmr_score": row.get("mmr_score"), "penalty": row.get("diversity_penalty")},
        "rule_id": signal["rule_id"], "signal_id": signal["signal_id"], "reason": signal["reason"],
        "metrics": signal["metrics"], "scope": signal["scope"],
        "evidence": [references[key] for key in sorted(references)],
        "matched_capabilities": sorted(set(item.capability.tags) & {c for s in matched for c in s["capabilities"]}),
        "explanation": {"observed": [{"rule_id": s["rule_id"], "metrics": s["metrics"], "evidence": s["evidence"]} for s in matched],
                        "trigger": item.trigger.model_dump(), "bottleneck_ids": [s["signal_id"] for s in matched],
                        "intervention": item.capability.model_dump(), "expected_effect": item.expected_effect.model_dump(),
                        "pending_requirements": pending},
        "hypothesis": signal["hypothesis"], "effect_status": "unmeasured", "source": source,
        "summary": item.capability.text, "setup_steps": (["先确认以下条件：" + "、".join(pending)] if pending else []) + item.action.setup_steps,
        "preview": item.action.preview, "limitations": item.action.limitations, "trial": item.action.trial,
        "evaluation_plan": {"target_metrics": sorted({m for s in matched for m in s["evaluation_metrics"]}),
                            "baseline": "固定任务、输入、验收范围与模型配置，记录启用前后的重复试验。",
                            "guardrails": ["验收通过率和验证覆盖不得下降。", "新增配置、验证、Token 和耗时均计入成本。"],
                            "observed_effect": None},
    }

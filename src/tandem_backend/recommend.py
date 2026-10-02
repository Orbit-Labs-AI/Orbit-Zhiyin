"""Join profile evidence AND bottleneck evidence to a resource's capabilities.

Popularity is deliberately absent. A match supports a trial, not an effectiveness claim.
"""

from .catalog import skills
from .feedback import SCENE_LABELS


def trial_method(resource: dict, bottleneck: dict) -> str:
    """Make the reader check concrete using the existing task, without promising benefit."""
    if resource["id"] != "doc-coauthoring":
        return resource["trial"]
    checks = {
        "math_explanation": "先复述证明思路，指出条件在哪一步用到",
        "developer_report": "复述已完成的工作、当前限制和下一步",
        "document": "复述核心结论和它的依据",
    }
    question = checks.get(bottleneck["scene"])
    if not question:
        return resource["trial"]
    readers = "、".join(r["label"] for r in bottleneck.get("readers", [])) or "目标读者"
    return f"保持原任务的交付语言和必要事实，让没看过这段对话的{readers}读一版，{question}。记录他卡在哪里，再改写并用同一问题复测。"


def recommend(analysis: dict, scene: str = "auto", language: str = "auto", catalog: list[dict] | None = None) -> list[dict]:
    dimensions = {p["dimension"]: p for p in analysis["preferences"]}
    contexts = {c["scene"]: c for c in analysis.get("contexts", [])}
    recommendations = []
    for bottleneck in analysis["bottlenecks"]:
        actual_scene = bottleneck["scene"]
        if scene != "auto" and scene != actual_scene:
            continue  # A requested filter cannot relabel the evidence's original task.
        scene_preferences = contexts.get(actual_scene, {}).get("preferences")
        if scene_preferences is None:
            scene_preferences = [p for p in analysis["preferences"] if actual_scene in p.get("scenes", {})]
        scoped_dimensions = {p["dimension"]: p for p in scene_preferences}
        matched_profile = [d for d in bottleneck["dimensions"] if d in dimensions and d in scoped_dimensions]
        if not matched_profile or not bottleneck["profile_evidence_ids"]:
            continue
        for resource in skills() if catalog is None else catalog:
            matched = [d for d in resource["dimensions"] if d in matched_profile]
            if not matched or bottleneck["type"] not in resource.get("problem_types", []):
                continue
            if actual_scene not in resource["scenes"]:
                continue
            actual_language = bottleneck.get("language", "zh")
            allowed_languages = actual_language.split('_or_')
            if language != "auto" and language not in allowed_languages:
                continue  # A filter cannot change the requested deliverable's language.
            if resource["language"] not in (*allowed_languages, "any"):
                continue
            if not resource["verified_sha"] or resource["verification"] != "repository_and_skill_read":
                continue
            preference = scoped_dimensions[matched[0]]
            context_ids = list(dict.fromkeys([i for i in [bottleneck.get("language_evidence_id")] +
                                              [r["evidence_id"] for r in bottleneck.get("readers", [])] if i]))
            recommendations.append({
                "id": resource["id"] + ":" + bottleneck["id"],
                "resource_id": resource["id"], "kind": resource["kind"], "name": resource["name"],
                "url": resource["url"],
                "source_url": f"{resource['url']}/blob/{resource['verified_sha']}/{resource['source_path']}",
                "reason": f"在{SCENE_LABELS.get(actual_scene, actual_scene)}中，你提出过“{preference['label']}”的要求。{bottleneck['reason']}",
                "profile_evidence_ids": bottleneck["profile_evidence_ids"],
                "bottleneck_id": bottleneck["id"], "bottleneck_evidence_ids": bottleneck["evidence_ids"],
                "context_evidence_ids": context_ids,
                "evidence_ids": list(dict.fromkeys(bottleneck["profile_evidence_ids"] + bottleneck["evidence_ids"] + context_ids)),
                "matched_dimensions": matched, "status": "trial", "effect_status": "unmeasured",
                "scene": actual_scene, "trial": trial_method(resource, bottleneck), "limitation": resource["limitations"],
                "language": actual_language, "language_basis": bottleneck.get("language_basis", "message_language"),
                "language_evidence_id": bottleneck.get("language_evidence_id"),
                "readers": bottleneck.get("readers", []), "capability": resource["summary"],
                "verified_sha": resource["verified_sha"], "match_basis": "profile_and_bottleneck",
                "source_status": resource.get("source_status", "bundled_snapshot"),
            })
    # Present one concrete opportunity per resource; retain the originating incident.
    seen, output = set(), []
    for item in recommendations:
        if item["resource_id"] not in seen:
            seen.add(item["resource_id"])
            output.append(item)
    return output

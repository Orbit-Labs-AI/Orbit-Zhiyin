"""Join profile evidence AND bottleneck evidence to a resource's capabilities.

Popularity is deliberately absent. A match supports a trial, not an effectiveness claim.
"""

from .catalog import skills


def recommend(analysis: dict, scene: str = "auto", language: str = "auto") -> list[dict]:
    dimensions = {p["dimension"]: p for p in analysis["preferences"]}
    recommendations = []
    for bottleneck in analysis["bottlenecks"]:
        matched_profile = [d for d in bottleneck["dimensions"] if d in dimensions]
        if not matched_profile or not bottleneck["profile_evidence_ids"]:
            continue
        for resource in skills():
            matched = [d for d in resource["dimensions"] if d in matched_profile]
            if not matched or bottleneck["type"] not in resource.get("problem_types", []):
                continue
            actual_scene = bottleneck["scene"] if scene == "auto" else scene
            if actual_scene not in resource["scenes"]:
                continue
            actual_language = bottleneck.get("language", "zh") if language == "auto" else language
            if resource["language"] not in (actual_language, "any"):
                continue
            if not resource["verified_sha"] or resource["verification"] != "repository_and_skill_read":
                continue
            preference = dimensions[matched[0]]
            recommendations.append({
                "id": resource["id"] + ":" + bottleneck["id"],
                "resource_id": resource["id"], "kind": resource["kind"], "name": resource["name"],
                "url": resource["url"],
                "source_url": f"{resource['url']}/blob/{resource['verified_sha']}/{resource['source_path']}",
                "reason": f"你在这类任务中提出过“{preference['label']}”的要求。{bottleneck['reason']}这个资源提供了对应的处理步骤，可以做一次对照。",
                "profile_evidence_ids": bottleneck["profile_evidence_ids"],
                "bottleneck_id": bottleneck["id"], "bottleneck_evidence_ids": bottleneck["evidence_ids"],
                "evidence_ids": list(dict.fromkeys(bottleneck["profile_evidence_ids"] + bottleneck["evidence_ids"])),
                "matched_dimensions": matched, "status": "trial", "effect_status": "unmeasured",
                "scene": actual_scene, "trial": resource["trial"], "limitation": resource["limitations"],
                "verified_sha": resource["verified_sha"], "match_basis": "profile_and_bottleneck",
            })
    # Present one concrete opportunity per resource; retain the originating incident.
    seen, output = set(), []
    for item in recommendations:
        if item["resource_id"] not in seen:
            seen.add(item["resource_id"])
            output.append(item)
    return output

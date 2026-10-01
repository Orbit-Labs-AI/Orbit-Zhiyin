"""Recommend a trial only when both user evidence and resource scope match."""

from .catalog import skills


def recommend(analysis: dict, scene: str = "developer_report", language: str = "zh") -> list[dict]:
    dimensions = {p["dimension"]: p for p in analysis["preferences"]}
    recommendations = []
    for skill in skills():
        matched = [d for d in skill["dimensions"] if d in dimensions]
        if not matched or scene not in skill["scenes"] or skill["language"] != language:
            continue
        if not skill["verified_sha"] or skill["verification"] != "repository_and_skill_read":
            continue
        evidence = [e["event_id"] for d in matched for e in dimensions[d]["evidence"]]
        recommendations.append({
            "id": skill["id"], "name": skill["name"], "url": skill["url"],
            "source_url": f"{skill['url']}/blob/{skill['verified_sha']}/{skill['source_path']}",
            "reason": "你的记录里出现过希望表达清楚或控制篇幅的要求。这个 skill 提供对应的编辑规则，可以先试用。",
            "evidence_ids": list(dict.fromkeys(evidence))[:5], "matched_dimensions": matched,
            "status": "trial", "effect_status": "unmeasured", "scene": scene,
            "trial": "用同一段输入分别生成原版和使用 skill 的版本，隐藏版本名称后判断哪份更易读；同时核对事实有没有丢失。",
            "limitation": skill["limitations"], "verified_sha": skill["verified_sha"],
        })
    return recommendations

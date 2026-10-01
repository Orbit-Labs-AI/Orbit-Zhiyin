"""User-facing wording. Facts are supplied by analysis; templates add no claims."""

def explain(analysis: dict, recommendations: list[dict] | None = None, audience: str = "user") -> dict:
    if audience not in ("user", "developer"):
        raise ValueError("audience 只能是 user 或 developer")
    counts = analysis["counts"]
    preferences = analysis["preferences"]
    if counts["user_messages"] == 0:
        return {"summary": "还没有可用于分析的用户消息。先导入一段包含真实用户输入的 Codex 会话。",
                "findings": [], "next_step": "导入后再查看结果。", "audience": audience,
                "details": analysis}
    opening = f"已整理 {counts['sessions']} 个会话，覆盖 {counts['projects']} 个项目。"
    clarity = next((p for p in preferences if p["dimension"] == "clarity"), None)
    if clarity:
        opening += f"其中 {clarity['sessions']} 个会话里，你明确要求回答容易理解。"
    elif preferences:
        p = preferences[0]
        opening += f"记录中较常出现的要求是“{p['label']}”，见于 {p['sessions']} 个会话。"
    else:
        opening += "目前没找到足够明确的协作要求，暂时不下画像结论。"
    findings = []
    for p in preferences[:3]:
        evidence = p["evidence"]
        if not evidence:
            continue
        findings.append({"title": p["label"],
                         "text": f"在 {p['sessions']} 个会话中出现过这类要求。先把它用于同类任务；跨场景是否适用还要验证。",
                         "evidence_ids": [e["event_id"] for e in evidence],
                         "example": evidence[0]["quote"]})
    if analysis["bottlenecks"]:
        next_step = "先回看被纠正的那一轮回答，确认是表达问题还是目标改变，再试对应的写作规则。"
    elif clarity:
        next_step = "下一次同类写作任务先试一个候选 skill，再对比结果是否更容易理解；当前还没有它有效的证据。"
    else:
        next_step = "选一段你认可或不认可的回答作反馈，系统才有依据调整建议。"
    if audience == "developer":
        next_step = "先核对证据引用和反馈分类，再做同场景对照；自动检查通过后仍需读者判断。"
    return {"summary": opening, "findings": findings, "next_step": next_step,
            "recommendations": recommendations or [], "audience": audience, "details": analysis}


def markdown(result: dict) -> str:
    """Short first layer; full machine-readable details stay in the JSON artifact."""
    lines = ["# 这批会话里看到了什么", "", result["summary"], ""]
    for finding in result["findings"]:
        lines.extend([f"**{finding['title']}**：{finding['text']}", "",
                      f"> {finding['example']}", "",
                      f"证据：`{finding['evidence_ids'][0]}`。", ""])
    for rec in result.get("recommendations", [])[:2]:
        lines.extend([f"可以试 [{rec['name']}]({rec['url']})：{rec['reason']}", "",
                      f"验证方式：{rec['trial']}", ""])
    lines.extend([result["next_step"], "", "这些结论来自记录中的明确表达；未收到反馈的回答不算已获认可。", ""])
    return "\n".join(lines)

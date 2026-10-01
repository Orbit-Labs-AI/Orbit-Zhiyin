"""User-facing wording. Facts are supplied by analysis; templates add no claims."""

from .feedback import SCENE_LABELS


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
    recommended_scenes = {r["scene"] for r in recommendations or []}
    contexts = sorted(analysis.get("contexts", []), key=lambda c: (c["scene"] not in recommended_scenes, -c["user_sessions"]))
    contextual = [(c, p) for c in contexts for p in sorted(c["preferences"], key=lambda p: (
        p["dimension"] != "clarity", p.get("target") != "communication", -p["sessions"]))]
    if not contextual:
        contextual = [({"label": "这批任务", "readers": [], "scene": "conversation"}, p) for p in preferences]
    for c, p in contextual[:2]:
        evidence = p["evidence"]
        if not evidence:
            continue
        reader_labels = "、".join(r["label"] for r in p.get("readers", []))
        reader_note = f"其中有任务明确指定读者为{reader_labels}。" if reader_labels else ""
        findings.append({"title": c["label"] + "：" + p["label"],
                         "text": f"这类任务有 {p['sessions']} 个会话提出过这项要求。{reader_note}",
                         "scene": c["scene"],
                         "evidence_ids": [e["event_id"] for e in evidence],
                         "example": evidence[0]["quote"]})
    if analysis["bottlenecks"]:
        next_step = "先回看建议所引用的那组要求与结果，确认问题，再按同一验收条件试用资源。"
    elif analysis.get("data_gaps"):
        next_step = "日志只记录了文件交付；需要拿到对应文档正文，才能判断是否写得易懂。"
    elif clarity:
        next_step = "要求容易理解本身还不足以确定该换什么工具。先选一次具体任务，核对要求与交付结果。"
    else:
        next_step = "选一段你认可或不认可的回答作反馈，系统才有依据调整建议。"
    if audience == "developer":
        next_step = "先核对证据引用和反馈分类，再做同场景对照；自动检查通过后仍需读者判断。"
    bottlenecks = [{"id": b["id"], "type": b["type"], "text": b["reason"], "status": b["status"],
                    "scene": b["scene"], "scene_label": SCENE_LABELS.get(b["scene"], b["scene"]),
                    "evidence_ids": b["evidence_ids"]} for b in analysis["bottlenecks"][:2]]
    if analysis.get("data_gaps"):
        opening += "部分记录只留下文件交付说明，正文质量还无法核对。"
    return {"summary": opening, "findings": findings, "bottlenecks": bottlenecks, "next_step": next_step,
            "recommendations": recommendations or [], "audience": audience, "details": analysis}


def markdown(result: dict) -> str:
    """Short first layer; full machine-readable details stay in the JSON artifact."""
    lines = ["# 这批会话里看到了什么", "", result["summary"], ""]
    for index, finding in enumerate(result["findings"]):
        lines.extend([f"**{finding['title']}**：{finding['text']}", "",
                      f"[查看原始要求](http://127.0.0.1:8765/v1/evidence/{finding['evidence_ids'][0]})", ""])
        if index == 0:
            lines.extend([f"> {finding['example']}", ""])
    shown_bottlenecks = set()
    for bottleneck in result.get("bottlenecks", [])[:1]:
        lines.extend([f"**待核对的卡点（{bottleneck['scene_label']}）**：{bottleneck['text']}", ""])
        shown_bottlenecks.add(bottleneck["id"])
    for rec in result.get("recommendations", [])[:2]:
        reason = rec["reason"] if rec["bottleneck_id"] not in shown_bottlenecks else f"对应上面的卡点，适用于{SCENE_LABELS.get(rec['scene'], rec['scene'])}。"
        lines.extend([f"可以试 [{rec['name']}]({rec['source_url']})：{reason}", "",
                      f"它提供的办法：{rec['capability']}", "",
                      f"验证方式：{rec['trial']}", ""])
    if not result.get("recommendations"):
        lines.extend(["目前的证据还不足以选定具体资源。", ""])
        lines.extend([result["next_step"], ""])
    lines.extend(["这些是这批任务中的明确要求；未收到反馈不代表满意，资源的效果也尚未测定。", ""])
    return "\n".join(lines)

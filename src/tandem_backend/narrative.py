"""Explain the next concrete check before exposing the full analysis.

Every factual claim comes from the analysis. Selection is a reading order, not a
severity score or a claim that one candidate caused the user's dissatisfaction.
"""

from .feedback import SCENE_LABELS


def _primary_bottleneck(analysis: dict, recommendations: list[dict]) -> dict | None:
    linked = {r["bottleneck_id"] for r in recommendations}
    candidates = analysis.get("bottlenecks", [])
    return next((b for b in candidates if b["id"] in linked), candidates[0] if candidates else None)


def _main_point(bottleneck: dict | None, preferences: list[dict]) -> str:
    if bottleneck:
        scene = SCENE_LABELS.get(bottleneck["scene"], bottleneck["scene"])
        if bottleneck["type"] == "explanation_revision":
            return f"先回看{scene}的这次修改：交付后，你又要求调整说明。是否已经讲清楚，还需要核对正文。"
        return f"先核对{scene}中的这处卡点：{bottleneck['reason']}"
    if preferences:
        first = next((p for p in preferences if p["dimension"] == "clarity"), preferences[0])
        return f"这批任务中有明确的“{first['label']}”要求，但还没有足够证据确定具体卡点。"
    return "这批消息还没有明确的协作要求，暂时无法形成画像或推荐。"


def explain(analysis: dict, recommendations: list[dict] | None = None, audience: str = "user") -> dict:
    if audience not in ("user", "developer"):
        raise ValueError("audience 只能是 user 或 developer")
    counts = analysis["counts"]
    preferences = analysis["preferences"]
    recommendations = recommendations or []
    sample = f"样本共 {counts['sessions']} 个会话、{counts['projects']} 个项目。"
    primary = _primary_bottleneck(analysis, recommendations)
    if counts["user_messages"] == 0:
        main = "还没有可用于分析的用户消息。先导入一段包含真实用户输入的 Codex 会话。"
    else:
        main = _main_point(primary, preferences)
    contexts = sorted(analysis.get("contexts", []), key=lambda c: (
        not primary or c["scene"] != primary["scene"], -c["user_sessions"]))
    contextual = [(c, p) for c in contexts for p in sorted(c["preferences"], key=lambda p: (
        bool(primary) and p["dimension"] not in primary["dimensions"],
        p["dimension"] != "clarity", p.get("target") != "communication", -p["sessions"]))]
    if not contextual:
        contextual = [({"label": "这批任务", "scene": "conversation"}, p) for p in preferences]
    findings = []
    for c, p in contextual[:2]:
        evidence = p["evidence"]
        if not evidence:
            continue
        reader_labels = "、".join(r["label"] for r in p.get("readers", []))
        reader_note = f"有任务明确指定读者为{reader_labels}。" if reader_labels else ""
        text = f"{c['label']}中，{p['sessions']} 个会话提出过“{p['label']}”的要求。{reader_note}"
        if audience == "developer":
            text += f"分母是这类任务的 {p['denominator']} 个会话；同一会话重复提出只计一次。"
        findings.append({"title": c["label"] + "：" + p["label"], "text": text,
                         "scene": c["scene"], "evidence_ids": [e["event_id"] for e in evidence],
                         "example": evidence[0]["quote"]})
    if counts["user_messages"] == 0:
        next_step = "导入后再查看结果。"
    elif primary and recommendations:
        next_step = "先核对下面这组要求与交付，再按同一任务试一次资源的方法。"
    elif primary:
        next_step = "先回看这次要求与交付。当前目录没有同时匹配画像、卡点和场景的资源。"
    elif analysis.get("data_gaps"):
        next_step = ("需要对应文档正文，才能判断它是否容易理解。" if any(
            g["code"] == "artifact_body_missing" for g in analysis["data_gaps"]) else
            "这段回复的篇幅记录不完整，先补齐记录再核对要求。")
    else:
        next_step = "先选一次具体任务，核对要求与结果，再决定是否换工具。"
    if audience == "developer" and counts["user_messages"]:
        next_step = "先检查这组证据的角色、场景和交付语言，再用同一任务做对照。读者验收仍待完成。"
    selected = ([primary] if primary else []) + [b for b in analysis["bottlenecks"] if b is not primary]
    bottlenecks = [{"id": b["id"], "type": b["type"], "text": b["reason"], "status": b["status"],
                    "scene": b["scene"], "scene_label": SCENE_LABELS.get(b["scene"], b["scene"]),
                    "evidence_ids": b["evidence_ids"], "request_preview": b.get("request_preview", ""),
                    "response_content": b.get("response_content", "message")} for b in selected[:2]]
    clarity = next((p for p in preferences if p["dimension"] == "clarity"), None)
    if clarity:
        sample += f"其中 {clarity['sessions']} 个会话明确要求说明容易理解。"
    return {"summary": main, "sample_summary": sample, "findings": findings, "bottlenecks": bottlenecks,
            "next_step": next_step, "recommendations": recommendations, "audience": audience,
            "main_evidence_ids": primary["evidence_ids"] if primary else [], "details": analysis}


def markdown(result: dict) -> str:
    """Keep a short first layer; evidence and full details can be opened separately."""
    title = "先看哪件事" if result["audience"] == "user" else "这次分析得到了什么"
    lines = ["# " + title, "", result["summary"], ""]
    for finding in result["findings"]:
        lines.extend([finding["text"], ""])
    primary = next(iter(result.get("bottlenecks", [])), None)
    if primary:
        preview = primary["request_preview"]
        if preview:
            lines.extend(["> " + preview.replace("\n", "\n> "), ""])
        # A revision is an observation. Its linked delivery may contain only a
        # file link; do not turn that into a claim about the unseen document.
        if primary["type"] == "explanation_revision":
            lines.extend(["你随后要求调整说明，不能单凭它断定上一版失败。", ""])
        if primary["response_content"] == "artifact_delivery":
            lines.extend(["这次交付在日志里只有文件说明，文档正文还需要另看。", ""])
        ids = primary["evidence_ids"]
        links = [f"[要求](http://127.0.0.1:8765/v1/evidence/{ids[0]})"]
        links.extend(f"[相关记录 {i}](http://127.0.0.1:8765/v1/evidence/{eid})" for i, eid in enumerate(ids[1:], 1))
        lines.extend(["回看证据：" + " · ".join(links), ""])
    elif result["findings"]:
        first = result["findings"][0]
        lines.extend(["> " + first["example"].replace("\n", "\n> "), "",
                      f"[回看要求](http://127.0.0.1:8765/v1/evidence/{first['evidence_ids'][0]})", ""])
    for index, rec in enumerate(result.get("recommendations", [])[:2]):
        if primary and rec["bottleneck_id"] == primary["id"]:
            reason = f"对应这次{SCENE_LABELS.get(rec['scene'], rec['scene'])}的修改或核对需求。"
        else:
            reason = rec["reason"]
        lines.extend([f"可以试 [{rec['name']}]({rec['source_url']})：{reason}", "",
                      f"它提供的办法：{rec['capability']}", "",
                      f"怎么验：{rec['trial']}", ""])
        if index == 0 and result["audience"] == "developer":
            lines.extend(["推荐依据保存在 JSON 的画像、瓶颈和上下文引用中。" + rec["limitation"], ""])
    if not result.get("recommendations"):
        lines.extend(["目前的证据还不足以选定具体资源。", "", result["next_step"], ""])
    lines.extend([result["sample_summary"], "",
                  "这些是任务中的明确要求。资源效果尚未测定；没有后续反馈也不能当作满意。", ""])
    return "\n".join(lines)

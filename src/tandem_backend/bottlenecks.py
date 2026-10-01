"""Connect a requirement to an outcome before recommending an intervention.

Three identical-command failures are a repair-loop candidate, not proof of wasted work.
A request to refine an explanation is observed revision, not rejection.
"""

import re
from collections import defaultdict
from dataclasses import replace

from .content import canceled_length_surfaces, embedded_artifact_body, measure_length
from .feedback import Signal, task_contexts
from .models import Event, stable_id


def unexplained_terms(text: str) -> list[str]:
    """A local definition marker reduces false alarms; this is not semantic grading."""
    terms = []
    for match in re.finditer(r"\b(?:KL|JS|POMDP|latent|embedding|factorize|z_u)\b", text, re.I):
        following = text[match.end():match.end() + 120]
        definition = re.match(r"\s*(?:[:：（(]|是指?|表示|指的是|即)\s*([^。;；\n）)]+)", following)
        if definition and (len(re.findall(r"[\u4e00-\u9fff]", definition[1])) >= 4 or
                           len(re.findall(r"\b[a-z]+\b", definition[1], re.I)) >= 4):
            continue
        terms.append(match[0])
    return terms


def _expected_failure(text: str) -> bool:
    # A repair task may deliberately run negative tests afterwards. Bind the
    # exception to its own clause instead of treating every repair word as a veto.
    pattern = r"预期[^，,。；;\n]{0,8}(?:失败|错误|报错)|应该[^，,。；;\n]{0,8}(?:失败|报错|返回错误)|验证[^，,。；;\n]{0,8}失败路径|负例[^，,。；;\n]{0,6}(?:测试|用例)"
    normal = r"(?:运行|执行|跑|做)[^，,。；;\n]{0,8}(?:正常|正例|常规|成功)[^，,。；;\n]{0,6}(?:测试|检查|用例)"
    intent = False
    for match in re.finditer(pattern + "|" + normal, text):
        left = max(text.rfind(c, 0, match.start()) for c in "，,。；;\n") + 1
        prefix = text[max(left, match.start() - 24):match.start()]
        after = text[match.end():match.end() + 24]
        negated = bool(re.search(r"(?:不要|不用|无需|别|不需要|不|不能|禁止)[^，,。；;\n]{0,8}$", prefix))
        if re.fullmatch(normal, match[0]):
            if not negated:
                intent = False
            continue
        # A completed negative test is background, not an exception for the
        # next command. Without command semantics we only trust active intent.
        retrospective = re.match(r"[^，,。；;\n]{0,8}(?:已经|已)(?:经)?(?:完成|结束|通过)|(?:测试|用例)?(?:完成|结束|通过)了", after)
        past = re.search(r"之前|此前|上次|过去|刚才", prefix) and not re.search(r"运行|执行|跑|验证|请|再做", prefix)
        if retrospective or past:
            intent = False
            continue
        intent = not negated
    return intent


def diagnose(events: list[Event], observed: list[Signal], context_by_id: dict | None = None) -> tuple[list[dict], list[dict]]:
    context_by_id = task_contexts(events) if context_by_id is None else context_by_id
    events_by_id = {e.id: e for e in events}
    by_session = defaultdict(list)
    by_event = defaultdict(list)
    for e in events:
        by_session[e.session_id].append(e)
    for s in observed:
        by_event[s.event_id].append(s)
    findings, gaps = [], []
    for session_events in by_session.values():
        last_response = None
        last_response_task = None
        pending_request = None
        latest_request = None
        pending_requests = []
        pending_signals = []
        response_parts = []
        calls = {e.call_id: e for e in session_events if e.kind == "tool_call" and e.call_id}
        consecutive = []
        last_operation = None
        for e in sorted(session_events, key=lambda x: x.ordinal):
            if e.kind == "user_message":
                response_parts = []  # A new request ends the prior delivery sequence.
                current_signals = by_event[e.id]
                continuing = bool(pending_request and (not last_response or last_response.ordinal < pending_request.ordinal) and
                                  context_by_id[e.id]["task_id"] == context_by_id[pending_request.id]["task_id"])
                if continuing:
                    pending_signals = _supplement(pending_signals, current_signals, e.text)
                    pending_requests.append(e)
                else:
                    pending_request, pending_signals, pending_requests = e, list(current_signals), [e]
                latest_request = e
                communication = [s for s in current_signals if s.target == "communication"]
                revision = [s for s in communication if s.category in ("correction", "refinement")]
                if revision and last_response and last_response_task == context_by_id[e.id]["task_id"]:
                    findings.append(_finding("explanation_revision", e, last_response, revision,
                                             "你随后要求调整说明。这能证明发生过修改要求，不能单凭它断定上一版失败。",
                                             "observed_revision"))
                consecutive, last_operation = [], None
            elif e.kind == "assistant_message" and e.details.get("phase") not in ("commentary", "analysis"):
                response_parts.append(e)
                delivery = _combined_response(response_parts)
                if len(response_parts) > 1:
                    response_ids = {part.id for part in response_parts}
                    findings[:] = [f for f in findings if f["type"] not in ("long_response", "unexplained_terms") or
                                   not response_ids.intersection(f["evidence_ids"])]
                    gaps[:] = [g for g in gaps if g["response_event_id"] not in response_ids]
                if pending_request and pending_signals:
                    writing = [s for s in pending_signals if s.target == "communication"]
                    if writing and _delivery_content(delivery) == "artifact_delivery":
                        gaps.append({"code": "artifact_body_missing", "session_id": e.session_id,
                                     "request_event_id": writing[0].event_id, "response_event_id": e.id,
                                     "message": "日志记录了文件交付；未识别到完整正文，需要原文件核对可读性。"})
                    elif writing and _delivery_content(delivery) == "embedded_body_truncated":
                        gaps.append({"code": "artifact_body_truncated", "session_id": e.session_id,
                                     "request_event_id": writing[0].event_id, "response_event_id": e.id,
                                     "message": "原始回复附有正文，但当前保留内容已截断，需要原文件核对全文。"})
                    concise = [s for s in writing if s.dimension == "brevity"]
                    for signal in concise:
                        contracts = signal.output_contracts or [signal.output_contract or {"surface": "reply", "char_limit": None}]
                        for contract in contracts:
                            full = delivery.details.get("writing_measurements", {}).get(contract["surface"])
                            measure = full or measure_length(delivery.text, contract, delivery.details.get("original_chars"), DELIVERY_SEPARATOR)
                            if not full and delivery.details.get("partial_sequence"):
                                measure = {**measure, "complete": False, "quality": "truncated_lower_bound"}
                            source = "normalized_full_message_sequence" if full and len(response_parts) > 1 else "normalized_full_message" if full else "retained_message"
                            measure = {**measure, "source": source}
                            cap = contract.get("char_limit")
                            threshold = cap if cap is not None else (450 if contract["surface"] == "summary" else 2500)
                            if measure["chars"] > threshold:
                                surface = {"summary": "摘要", "body": "正文", "reply": "首层回复"}[contract["surface"]]
                                lower_bound = "至少 " if measure.get("complete") is False else ""
                                origin = events_by_id[signal.event_id]
                                supporting = [signal] + [s for s in writing if s is not signal and s.scene == signal.scene]
                                finding = _finding("long_response", origin, delivery, supporting,
                                                   f"你要求{surface}简洁；测得{lower_bound} {measure['chars']} 字符，超过本次核对阈值 {threshold}。可以回看哪些细节适合后移。", "rule_candidate")
                                finding["id"] = stable_id("long_response", signal.event_id, e.id, contract["surface"])
                                finding["measurement"] = {**measure, "threshold": threshold,
                                                           "threshold_basis": "requested_limit" if cap is not None else "review_heuristic"}
                                findings.append(finding)
                            elif measure.get("complete") is False:
                                gaps.append({"code": "reply_length_incomplete", "session_id": e.session_id,
                                             "request_event_id": pending_request.id, "response_event_id": e.id,
                                             "message": "未识别正文分界，无法单独核对正文篇幅。" if measure["quality"] == "body_boundary_missing" else "回复已截断且缺完整篇幅统计，当前下界不足以判断是否满足限制。"})
                    jargon = unexplained_terms(delivery.text[:500])
                    clarity = next((s for s in writing if s.dimension == "clarity"), None)
                    if clarity and len(jargon) >= 4:
                        supporting = [clarity] + [s for s in writing if s is not clarity and s.scene == clarity.scene]
                        findings.append(_finding("unexplained_terms", events_by_id[clarity.event_id], delivery, supporting,
                                                 f"你要求说明易懂；回复开头有 {len(jargon)} 处模型术语未找到紧邻的解释，需要回看是否解释到位。", "rule_candidate"))
                last_response = delivery
                last_response_task = context_by_id[pending_request.id]["task_id"] if pending_request else None
            elif e.kind == "tool_result":
                call = calls.get(e.call_id)
                operation = (e.turn_id, e.tool, call.details.get("argument_digest")) if call else None
                if pending_request and _expected_failure("\n".join(request.text for request in pending_requests)):
                    consecutive, last_operation = [], None
                    continue
                if not call or not call.details.get("argument_digest") or e.status != "failed":
                    consecutive, last_operation = [], None
                    continue
                if operation != last_operation:
                    consecutive = []
                consecutive.append(e)
                last_operation = operation
                if len(consecutive) == 3 and pending_request:
                    workflow = [s for s in pending_signals if s.target == "workflow"]
                    context = context_by_id[latest_request.id]
                    findings.append({
                        "id": stable_id("repeated_tool_failure", e.session_id, consecutive[0].id),
                        "type": "repeated_tool_failure", "scene": context["scene"], "language": context["language"], "status": "rule_candidate",
                        "session_id": e.session_id, "model": e.model,
                        "task_id": context["task_id"],
                        "dimensions": [s.dimension for s in workflow],
                        "readers": context["readers"],
                        "language_evidence_id": context["language_evidence_id"],
                        "language_basis": context["language_basis"],
                        "profile_evidence_ids": list(dict.fromkeys(s.event_id for s in workflow)),
                        "evidence_ids": [request.id for request in pending_requests] + [x.id for x in consecutive],
                        "reason": "同一轮中，相同工具参数连续三次返回失败；可能需要先补定位步骤。预期失败测试或环境问题也会产生这个模式。",
                        "observed_failures": 3,
                    })
    return list({x["id"]: x for x in findings}.values()), gaps


DELIVERY_SEPARATOR = "\n\n\x00TANDEM_MESSAGE_BOUNDARY\x00\n\n"


def _combined_response(responses: list[Event]) -> Event:
    """Measure an uninterrupted delivery, preserving all original evidence IDs.

    Synthetic boundaries keep Markdown blocks apart but do not count toward
    the user's character limit. Truncated sequences retain uncertainty.
    """
    if len(responses) == 1:
        return responses[0]
    text = DELIVERY_SEPARATOR.join(response.text for response in responses)
    original_chars = sum(response.details.get("original_chars", len(response.text)) for response in responses)
    original_chars += len(DELIVERY_SEPARATOR) * (len(responses) - 1)
    partial = original_chars > len(text)
    measurements = {} if partial else {
        surface: measure_length(text, {"surface": surface}, message_separator=DELIVERY_SEPARATOR)
        for surface in ("reply", "summary", "body")}
    if partial:
        full = [r.details.get("writing_measurements", {}).get("reply") for r in responses]
        if all(m and m.get("complete") and m.get("quality") == "first_layer" for m in full):
            measurements["reply"] = {"chars": sum(m["chars"] for m in full), "surface": "reply",
                                     "quality": "full_fragment_sum", "complete": True}
    return replace(responses[-1], text=text, details={**responses[-1].details,
                   "response_event_ids": [r.id for r in responses], "original_chars": original_chars,
                   "partial_sequence": partial, "artifact_body_present": embedded_artifact_body(text.replace(DELIVERY_SEPARATOR, "\n\n")),
                   "writing_measurements": measurements})


def _supplement(previous: list[Signal], added: list[Signal], text: str) -> list[Signal]:
    """Preserve unfulfilled requirements; an explicit cap replacement changes its surface."""
    surfaces = canceled_length_surfaces(text)
    if re.search(r"改成|改为|调整为|改到", text):
        surfaces.update(c["surface"] for s in added if s.dimension == "brevity" for c in s.output_contracts)
    if surfaces:
        retained = []
        for signal in previous:
            if signal.dimension != "brevity":
                retained.append(signal)
                continue
            remaining = [c for c in signal.output_contracts if c["surface"] not in surfaces]
            if remaining:
                retained.append(replace(signal, output_contracts=remaining, output_contract=remaining[0]))
        previous = retained
    return previous + list(added)


def _delivery_content(response: Event) -> str:
    if not _artifact_delivery(response.text):
        return "message"
    present = response.details.get("artifact_body_present")
    if present is None:
        present = embedded_artifact_body(response.text)
    if present and response.details.get("original_chars", len(response.text)) > len(response.text):
        return "embedded_body_truncated"
    return "embedded_body" if present else "artifact_delivery"


def _artifact_delivery(text: str) -> bool:
    """A file link plus a completed action supports delivery, never the file's quality."""
    completed = r"已(?:经)?(?:完成|写入|写到|保存|生成|更新|创建|写好|补充)|(?:完成|写入|保存|生成|更新|创建|写好)(?:了|完成)"
    uncertain = r"无法|不能|未能|尚未|还没|未|没有|计划|准备|打算|预计|接下来|随后|将|会|需要|请|待|是否|不确定"
    for link in re.finditer(r"\[[^\]]+\]\([^)]*\.(?:md|tex|docx)(?::\d+)?\)", text, re.I):
        left = max(text.rfind(c, 0, link.start()) for c in "。；;\n") + 1
        before = text[max(left, link.start() - 70):link.start()]
        for action in re.finditer(completed, before):
            # Negative or prospective wording around the action leaves delivery
            # unconfirmed. Do not inspect or execute the linked document.
            if not re.search(uncertain, before[max(0, action.start() - 12):]):
                return True
        after = text[link.end():link.end() + 24]
        if re.match(r"\s*(?:已(?:经)?(?:完成|写入|保存|生成|更新|创建)|保存完成|写入完成)", after):
            return True
        # Chinese often places the file inside the completed-action phrase:
        # '已将 [文件] 重写为…' or '已在 [文件] 中补充…'.
        enclosing = re.search(r"已(?:经)?(?:将|把|在|为|对)\s*$", before)
        if enclosing and not re.search(uncertain, before[max(0, enclosing.start() - 12):enclosing.start()]) and re.match(
                r"\s*(?:中|里)?\s*(?:重写|改写|补充|更新|保存|写入|生成|完成|整理|修改|加入|添加)", after):
            return True
    return False


def _finding(kind: str, request: Event, response: Event, evidence: list[Signal],
             reason: str, status: str) -> dict:
    return {"id": stable_id(kind, request.id, response.id), "type": kind,
            "scene": evidence[0].scene, "language": evidence[0].language, "status": status, "session_id": request.session_id,
            "model": response.model, "dimensions": list(dict.fromkeys(s.dimension for s in evidence)),
            "readers": evidence[0].readers,
            "language_evidence_id": evidence[0].language_evidence_id,
            "language_basis": evidence[0].language_basis,
            "request_preview": evidence[0].quote,
            "task_id": evidence[0].task_id,
            "response_content": _delivery_content(response),
            "profile_evidence_ids": list(dict.fromkeys(s.event_id for s in evidence)),
            "evidence_ids": list(dict.fromkeys([s.event_id for s in evidence] + response.details.get("response_event_ids", [response.id]))),
            "reason": reason}

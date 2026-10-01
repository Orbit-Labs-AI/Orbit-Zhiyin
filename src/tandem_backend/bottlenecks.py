"""Connect a requirement to an outcome before recommending an intervention.

Three identical-command failures are a repair-loop candidate, not proof of wasted work.
A request to refine an explanation is observed revision, not rejection.
"""

import re
from collections import defaultdict

from .content import measure_length
from .feedback import Signal, language_of
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
    if re.search(r"修复|排查|解决|不应该|不该", text):
        return False
    return bool(re.search(r"预期.{0,8}(?:失败|错误|报错)|应该.{0,8}(?:失败|报错|返回错误)|验证.{0,8}失败路径|负例.{0,6}(?:测试|用例)", text))


def diagnose(events: list[Event], observed: list[Signal]) -> tuple[list[dict], list[dict]]:
    by_session = defaultdict(list)
    by_event = defaultdict(list)
    for e in events:
        by_session[e.session_id].append(e)
    for s in observed:
        by_event[s.event_id].append(s)
    findings, gaps = [], []
    for session_events in by_session.values():
        last_response = None
        pending_request = None
        pending_signals = []
        calls = {e.call_id: e for e in session_events if e.kind == "tool_call" and e.call_id}
        consecutive = []
        last_operation = None
        for e in sorted(session_events, key=lambda x: x.ordinal):
            if e.kind == "user_message":
                pending_request = e
                pending_signals = by_event[e.id]
                communication = [s for s in pending_signals if s.target == "communication"]
                revision = [s for s in communication if s.category in ("correction", "refinement")]
                if revision and last_response:
                    findings.append(_finding("explanation_revision", e, last_response, revision,
                                             "你随后要求调整说明。这能证明发生过修改要求，不能单凭它断定上一版失败。",
                                             "observed_revision"))
                consecutive, last_operation = [], None
            elif e.kind == "assistant_message" and e.details.get("phase") not in ("commentary", "analysis"):
                if pending_request and pending_signals:
                    writing = [s for s in pending_signals if s.target == "communication"]
                    if writing and _artifact_delivery(e.text):
                        gaps.append({"code": "artifact_body_missing", "session_id": e.session_id,
                                     "request_event_id": pending_request.id, "response_event_id": e.id,
                                     "message": "日志记录了文件交付，但没有文档正文，无法核对可读性。"})
                    concise = [s for s in writing if s.dimension == "brevity"]
                    for signal in concise:
                        contracts = signal.output_contracts or [signal.output_contract or {"surface": "reply", "char_limit": None}]
                        for contract in contracts:
                            full = e.details.get("writing_measurements", {}).get(contract["surface"])
                            measure = full or measure_length(e.text, contract, e.details.get("original_chars"))
                            measure = {**measure, "source": "normalized_full_message" if full else "retained_message"}
                            cap = contract.get("char_limit")
                            threshold = cap if cap is not None else (450 if contract["surface"] == "summary" else 2500)
                            if measure["chars"] > threshold:
                                surface = "摘要" if contract["surface"] == "summary" else "首层回复"
                                lower_bound = "至少 " if measure.get("complete") is False else ""
                                finding = _finding("long_response", pending_request, e, writing,
                                                   f"你要求{surface}简洁；测得{lower_bound} {measure['chars']} 字符，超过本次核对阈值 {threshold}。可以回看哪些细节适合后移。", "rule_candidate")
                                finding["id"] = stable_id("long_response", pending_request.id, e.id, contract["surface"])
                                finding["measurement"] = {**measure, "threshold": threshold,
                                                           "threshold_basis": "requested_limit" if cap is not None else "review_heuristic"}
                                findings.append(finding)
                            elif measure.get("complete") is False:
                                gaps.append({"code": "reply_length_incomplete", "session_id": e.session_id,
                                             "request_event_id": pending_request.id, "response_event_id": e.id,
                                             "message": "回复已截断且缺完整篇幅统计，当前下界不足以判断是否满足限制。"})
                    jargon = unexplained_terms(e.text[:500])
                    if any(s.dimension == "clarity" for s in writing) and len(jargon) >= 4:
                        findings.append(_finding("unexplained_terms", pending_request, e, writing,
                                                 f"你要求说明易懂；回复开头有 {len(jargon)} 处模型术语未找到紧邻的解释，需要回看是否解释到位。", "rule_candidate"))
                last_response = e
            elif e.kind == "tool_result":
                call = calls.get(e.call_id)
                operation = (e.turn_id, e.tool, call.details.get("argument_digest")) if call else None
                if pending_request and _expected_failure(pending_request.text):
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
                    findings.append({
                        "id": stable_id("repeated_tool_failure", e.session_id, consecutive[0].id),
                        "type": "repeated_tool_failure", "scene": "coding", "language": workflow[0].language if workflow else language_of(pending_request.text), "status": "rule_candidate",
                        "session_id": e.session_id, "model": e.model,
                        "dimensions": [s.dimension for s in workflow],
                        "readers": workflow[0].readers if workflow else [],
                        "language_evidence_id": workflow[0].language_evidence_id if workflow else pending_request.id,
                        "language_basis": workflow[0].language_basis if workflow else "message_language",
                        "profile_evidence_ids": [s.event_id for s in workflow],
                        "evidence_ids": [pending_request.id] + [x.id for x in consecutive],
                        "reason": "同一轮中，相同工具参数连续三次返回失败；可能需要先补定位步骤。预期失败测试或环境问题也会产生这个模式。",
                        "observed_failures": 3,
                    })
    return list({x["id"]: x for x in findings}.values()), gaps


def _artifact_delivery(text: str) -> bool:
    return bool(re.search(r"(?:已|完成|写入|保存).{0,50}\[[^\]]+\]\([^)]*\.(?:md|tex|docx)", text))


def _finding(kind: str, request: Event, response: Event, evidence: list[Signal],
             reason: str, status: str) -> dict:
    return {"id": stable_id(kind, request.id, response.id), "type": kind,
            "scene": evidence[0].scene, "language": evidence[0].language, "status": status, "session_id": request.session_id,
            "model": response.model, "dimensions": list(dict.fromkeys(s.dimension for s in evidence)),
            "readers": evidence[0].readers,
            "language_evidence_id": evidence[0].language_evidence_id,
            "language_basis": evidence[0].language_basis,
            "request_preview": evidence[0].quote,
            "response_content": "artifact_delivery" if _artifact_delivery(response.text) else "message",
            "profile_evidence_ids": [request.id], "evidence_ids": [request.id, response.id],
            "reason": reason}

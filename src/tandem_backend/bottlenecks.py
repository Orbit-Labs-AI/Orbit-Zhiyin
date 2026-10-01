"""Connect a requirement to an outcome before recommending an intervention.

Three identical-command failures are a repair-loop candidate, not proof of wasted work.
A request to refine an explanation is observed revision, not rejection.
"""

import re
from collections import defaultdict

from .feedback import Signal, language_of
from .models import Event, stable_id


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
                    if any(s.dimension == "brevity" for s in writing) and e.details.get("original_chars", len(e.text)) > 2500:
                        findings.append(_finding("long_response", pending_request, e, writing,
                                                 "你要求说明简洁；这次回复超过 2500 字符，值得回看是否有可移出的细节。", "rule_candidate"))
                    jargon = re.findall(r"\b(?:KL|JS|POMDP|latent|embedding|factorize|z_u)\b", e.text[:500], re.I)
                    if any(s.dimension == "clarity" for s in writing) and len(jargon) >= 4:
                        findings.append(_finding("unexplained_terms", pending_request, e, writing,
                                                 f"你要求说明易懂；回复开头出现 {len(jargon)} 处模型术语，需要检查是否解释到位。", "rule_candidate"))
                last_response = e
            elif e.kind == "tool_result":
                call = calls.get(e.call_id)
                operation = (e.turn_id, e.tool, call.details.get("argument_digest")) if call else None
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
                        "type": "repeated_tool_failure", "scene": "coding", "language": language_of(pending_request.text), "status": "rule_candidate",
                        "session_id": e.session_id, "model": e.model,
                        "dimensions": [s.dimension for s in workflow],
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
            "scene": evidence[0].scene, "language": language_of(request.text), "status": status, "session_id": request.session_id,
            "model": response.model, "dimensions": list(dict.fromkeys(s.dimension for s in evidence)),
            "profile_evidence_ids": [request.id], "evidence_ids": [request.id, response.id],
            "reason": reason}

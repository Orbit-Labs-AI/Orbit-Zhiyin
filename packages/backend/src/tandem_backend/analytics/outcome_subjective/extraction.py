"""Conservative, local rules for explicit feedback; no sentiment or success inference."""

import re

from ...privacy import direct_user_text
from .linking import link_feedback_targets

RULE_VERSION = "subjective-outcome-v1"
_TARGET = r"(?:(?:这个|这版|这一版|这个结果|这份报告|这份文档|这个交付|这个任务)\s*)?"
_ACCEPT = re.compile(_TARGET + r"(?:可以了|没问题了|通过验收了?|我接受|我确认接受|符合要求了?|这样可以|很好)|(?:this |that |it )?(?:looks good|works(?: now)?|is acceptable)|accepted|lgtm", re.I)
_REJECT = re.compile(_TARGET + r"(?:还是不行|仍然不行|不对|不符合要求|不能接受|我不接受|我拒收|没有通过验收)|(?:this |that |it )?(?:does not work|doesn't work|still fails|is wrong|is not acceptable)|rejected|not what I (?:wanted|meant)", re.I)
_COMPLETE = re.compile(r"(?:我确认)?(?:(?:这个|整个)?任务(?:已经|已)?完成了?|(?:这个)?问题(?:已经|已)?解决了?|(?:已经)?解决了)|(?:the )?task (?:is |has been )?completed|(?:the )?(?:problem|issue) (?:is |has been )?(?:fixed|resolved)", re.I)
_INCOMPLETE = re.compile(r"(?:这个|整个)?任务(?:还没|尚未|没有)完成|(?:这个)?问题(?:还没|尚未|没有)解决|(?:the )?task (?:is )?(?:not complete|incomplete)|(?:the )?(?:problem|issue) (?:is )?not (?:fixed|resolved)", re.I)
_REWORK = re.compile(r"(?:请|麻烦)?(?:重新(?:修改|处理|生成|写|做|提交)|重写|重做|返工)(?:.*)|(?:please )?(?:rewrite|redo|revise|rework)(?:\s+.+)?", re.I)
_HYPOTHETICAL = re.compile(r"如果|假如|假设|要是|例如|比如|举例|示例|假想|用户说|他说|她说|你说|请回答|请回复|请输出|请翻译|不是说|不代表|不要说|\b(?:if|unless|when|once|suppose|example|says?|said|would|could)\b", re.I)
_META_REQUEST = re.compile(r"(?:分析|识别|提取|归类|判断|评估|翻译|总结|统计).{0,16}(?:反馈|句子|短语|文本|例子)|(?:以下|下面|如下|原文|示例|样例|例如)[:：]|\b(?:classify|translate|analy[sz]e|summari[sz]e)\b.{0,40}\b(?:feedback|sentences?|text|example)\b", re.I)
_QUOTES = re.compile(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"|(?<!\w)\x27[^\x27\n]*\x27(?!\w)|`[^`]*`')


def classify_feedback(text):
    """Recognize complete explicit clauses, retaining conflicting feedback as mixed.

    Questions, conditions, quoted material and unrecognized text provide no label.
    Evidence is normalized/redacted text, not a copy of the source log.
    """
    clean = _QUOTES.sub("[quoted]", direct_user_text(text or ""))
    # A later line in a quoted/example/conditional prompt is not a new assertion.
    if _META_REQUEST.search(clean) or _HYPOTHETICAL.search(clean):
        return None
    clean = re.sub(r"\.(?=\s|$)", "。", clean)
    accepted = rejected = complete = incomplete = False
    evidence, rework = [], []
    for sentence in re.findall(r"[^。！？!?；;\n]+[。！？!?；;\n]*", clean):
        if re.search(r"[?？]|(?:吗|么|是否|能否)", sentence) or _HYPOTHETICAL.search(sentence):
            continue
        for clause in re.split(r"[，,]|但是|不过|\bbut\b", sentence, flags=re.I):
            clause = clause.strip(" 。！!；;\n\t.")
            clause = re.sub(r"^(?:但|不过)\s*", "", clause)
            a, r = bool(_ACCEPT.fullmatch(clause)), bool(_REJECT.fullmatch(clause))
            c, i = bool(_COMPLETE.fullmatch(clause)), bool(_INCOMPLETE.fullmatch(clause))
            w = bool(_REWORK.fullmatch(clause))
            if a or r or c or i or w:
                evidence.append(clause)
                accepted |= a
                rejected |= r
                complete |= c
                incomplete |= i
                if w:
                    reason = re.search(r"(?:因为|原因是|\bbecause\b)\s*([^，,。！？!?；;\n]+)", sentence, re.I)
                    rework.append({"request": clause, "reason": reason[1].strip() if reason else None})
    if not evidence:
        return None
    acceptance = "mixed" if accepted and rejected else "accepted" if accepted else "rejected" if rejected else None
    completion = None if complete == incomplete else complete
    positive, negative = accepted or complete, rejected or incomplete or bool(rework)
    return {"user_acceptance": acceptance, "user_confirmed_completion": completion,
            "completion_conflict": complete and incomplete, "rework_feedback": rework,
            "signal": "mixed" if positive and negative else "positive" if positive else "negative",
            "evidence_text": "；".join(evidence), "rule_version": RULE_VERSION}


def collect_deliveries(events, main_ids):
    """Observe explicit assistant final messages in main sessions, never self-rated success."""
    output = []
    for event in events:
        attrs = event.get("attrs", {})
        if (event["session_uid"] not in main_ids or event["kind"] != "message.assistant"
                or attrs.get("phase") not in ("final", "final_answer") or not event.get("text")
                or event.get("actor") not in (None, "assistant", "unknown")
                or attrs.get("replayed_from") or attrs.get("duplicate_of")):
            continue
        output.append({"delivery_event_uid": event["event_uid"], "session_uid": event["session_uid"],
                       "seq": event["seq"], "ts": event.get("ts"), "task_id": attrs.get("task_id"),
                       "task_id_source": attrs.get("task_id_source", "explicit"),
                       "artifact_id": attrs.get("artifact_id"), "artifact_version": attrs.get("artifact_version")})
    return output


def extract_subjective_feedback(messages, deliveries, main_ids):
    """Return recognized human feedback including candidates with unresolved targets."""
    feedback = []
    for event in messages:
        attrs = event.get("attrs", {})
        if (event["session_uid"] not in main_ids or event["kind"] != "message.user"
                or attrs.get("origin") != "human" or event.get("actor") not in ("human", "user")
                or attrs.get("replayed_from") or attrs.get("duplicate_of")):
            continue
        label = classify_feedback(event.get("text"))
        if label is None:
            continue
        feedback.append({**label, "event_uid": event["event_uid"], "session_uid": event["session_uid"],
                         "seq": event["seq"], "ts": event.get("ts"), "available_at": event.get("ts"),
                         "time_quality": "reported" if event.get("ts") is not None else "sequence_only",
                         "task_id": attrs.get("task_id"), "task_id_source": attrs.get("task_id_source", "explicit"),
                         "requested_target": attrs.get("feedback_target"),
                         "text_truncated": bool(event.get("text_truncated")),
                         "ambiguous_text_target": bool(re.search(r"上一版|旧版|之前的|第[一二三四五六七八九十0-9]+版|\bv\d+\b|previous version|older version", label["evidence_text"], re.I))})
    for item in feedback:
        item["feedback_evidence"] = {k: item[k] for k in (
            "event_uid", "session_uid", "seq", "ts", "available_at", "time_quality", "evidence_text")}
        item["feedback_evidence"].update(source="confirmed_human_message", text_quality="truncated" if item["text_truncated"] else "normalized_redacted")
    return link_feedback_targets(feedback, deliveries)

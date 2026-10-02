"""Evidence-backed task candidates; session identity and task identity are distinct."""

import re
from collections import Counter, defaultdict

from ...models import stable_id
from ..common import chronological_messages, clauses, evidence, semantic_coverage, semantic_messages
from .taxonomy import DOMAINS, TASK_TYPES, TAXONOMY_VERSION

NEW_TASK = re.compile(r"^(?:好的[，, ]*)?(?:新任务|另一个任务|另外一个任务|换个任务|换一个任务|next task\b|new task\b)", re.I)
REVISION = re.compile(r"^(?:请)?(?:目标改为|目标改成|改为|改成|修改目标|change the goal\b)", re.I)
CLOSE = re.compile(r"^(?:这个)?任务(?:已经)?(?:结束|完成|取消)[了。.!！\s]*$|^(?:task complete|cancel this task)[.!\s]*$", re.I)
PREFERENCE_ONLY = re.compile(r"^(?:我(?:更)?(?:喜欢|偏好|倾向)|以后|今后|始终|默认|从现在起|撤销|取消之前|i prefer\b|from now on\b|always\b)", re.I)
NEGATIVE = re.compile(r"^(?:请)?(?:不要|不必|不用|无需|不需要|do not\b|don't\b|no need to\b)", re.I)
ARTIFACT = re.compile(r"(?<![\w.])(?:[\w.-]+/)*[\w.-]+\.(?:md|pdf|docx|tex|json|csv|xlsx|pptx|html|py|ts|js)\b|报告|文档|表格|脚本|讲义|\b(?:report|document|spreadsheet)\b", re.I)
PRODUCE = re.compile(r"写|生成|创建|输出|交付|保存|导出|提供|\b(?:write|create|generate|deliver|export|save)\b", re.I)


def request_clauses(text):
    """Do not classify forbidden actions, quoted material or enduring preferences as tasks."""
    parts = [p.strip() for p in re.split(r"[，,]|\bbut\b", text, flags=re.I)]
    return [c for part in parts for c in clauses(part) if not NEGATIVE.search(c) and not PREFERENCE_ONLY.search(c)
            and not re.match(r"例如|比如|假如|假设|如果|示例|他说|她说|\b(?:if|for example)\b", c, re.I)]


def extract_task_features(task_events):
    labels = {"domain": {}, "task_type": {}}
    artifacts, requests = {}, []
    for event in task_events:
        for clause in request_clauses(event["semantic_text"]):
            if CLOSE.fullmatch(clause):
                continue
            found_action = False
            for field, vocabulary in (("domain", DOMAINS), ("task_type", TASK_TYPES)):
                for label, pattern in vocabulary.items():
                    if re.search(pattern, clause, re.I):
                        labels[field].setdefault(label, []).append(evidence(event, clause))
                        found_action |= field == "task_type"
            if found_action:
                requests.append((event, clause))
            verb = PRODUCE.search(clause)
            if verb:
                for match in ARTIFACT.finditer(clause, verb.end()):
                    name = match.group(0)
                    artifacts.setdefault(name, {"name": name, "format": name.rsplit(".", 1)[1].lower() if "." in name else None,
                                                "evidence": evidence(event, clause), "status": "requested"})
    first = requests[0] if requests else None
    goal = first[1] if first else None
    # Goal amendments are explicit versions; ordinary follow-ups do not replace the goal.
    history = [{"goal": goal, "evidence": evidence(*first) if first else None}] if first else []
    for event, clause in requests[1:]:
        if REVISION.search(clause):
            goal = clause
            history.append({"goal": goal, "evidence": evidence(event, clause)})
    return {"domain": sorted(labels["domain"]) or None, "task_type": sorted(labels["task_type"]) or None,
            "task_title": goal[:60] if goal else None, "task_goal": goal,
            "task_goal_history": history, "expected_artifacts": list(artifacts.values()) or None,
            "label_evidence": labels, "taxonomy_version": TAXONOMY_VERSION, "method": "lexical_rules",
            "semantic_status": "candidate" if goal else "unknown",
            "missing_reasons": [key for key in ("domain", "task_type") if not labels[key]]
                               + ([] if goal else ["goal_not_explicit"]) + ([] if artifacts else ["artifact_not_explicit"])}


def segment_tasks(events, sessions):
    messages = semantic_messages(events, sessions)
    session_map = {s["session_uid"]: s for s in sessions}
    groups, active, message_groups, assignments = {}, {}, defaultdict(list), {}
    for event in messages:
        sid, text, attrs = event["session_uid"], event["semantic_text"], event.get("attrs", {})
        if not text:
            continue
        previous = active.get(sid)
        if CLOSE.fullmatch(text) and previous:
            span = groups[previous]["task_boundaries"][-1]
            span.update(end=evidence(event, text), end_inclusive=True, end_reason="user_explicit_close")
            assignments[event["event_uid"]] = previous
            active.pop(sid)
            continue
        native = attrs.get("task_id") if attrs.get("task_id_source") in ("native", "human_confirmed") else None
        # Similar paths or heuristic legacy task IDs never establish cross-session identity.
        session = session_map[sid]
        explicit_id = stable_id("task", session.get("source_id"), session.get("project_id"), native) if native else None
        is_new = previous is None or bool(NEW_TASK.search(text)) or (explicit_id is not None and explicit_id != previous)
        features = extract_task_features([event])
        if previous and not is_new and not REVISION.search(text):
            old_types = groups[previous]["initial_types"]
            # An explicit stage marker plus a new action produces a new candidate boundary.
            is_new = bool(re.match(r"^(?:现在|接下来|然后|now\b|next\b)", text, re.I)
                          and features["task_type"] and set(features["task_type"]) - set(old_types))
        if is_new and not request_clauses(text):
            continue
        if is_new:
            key = explicit_id or stable_id("task", sid, event["event_uid"])
            if previous:
                groups[previous]["task_boundaries"][-1].update(
                    end=evidence(event, text), end_inclusive=False, end_reason="next_task_boundary")
            record = groups.setdefault(key, {"task_id": key, "native_task_id": native,
                "related_session_ids": [], "session_relations": [], "task_boundaries": [],
                "project_id": session.get("project_id"), "legacy_project_id": session.get("legacy_project_id"),
                "initial_types": features["task_type"] or []})
            if sid not in record["related_session_ids"]:
                record["related_session_ids"].append(sid)
                record["session_relations"].append({"session_uid": sid, "basis": "explicit_task_id" if native else "local_boundary",
                                                     "evidence": evidence(event, text)})
            record["task_boundaries"].append({"session_uid": sid, "start": evidence(event, text),
                "end": None, "end_inclusive": None, "end_reason": "not_observed",
                "status": "explicit" if native or NEW_TASK.search(text) else "candidate"})
            active[sid] = key
        key = active[sid]
        assignments[event["event_uid"]] = key
        message_groups[key].append(event)
    records = []
    for key, record in groups.items():
        record.pop("initial_types")
        merged = chronological_messages(message_groups[key])
        records.append({**record, **extract_task_features(merged),
                        "goal_order_quality": "partial" if any(e.get("ts") is None for e in merged) else "reported_time_and_native_seq",
                        "human_evidence_ids": [e["event_uid"] for e in message_groups[key]],
                        "observed_message_count": len(message_groups[key])})
    return {"records": records, "task_by_event": assignments,
            "coverage": semantic_coverage(events, messages), "family_version": "task-v1"}


def summarize_task_distribution(tasks, scope=None):
    if tasks is None:
        return {"task_count": None, "domain": None, "task_type": None, "scope": scope}
    tasks = list({r["task_id"]: r for r in tasks}.values())
    out = {"task_count": len(tasks), "scope": scope, "counting": "distinct task_id; multi-label totals may exceed task_count"}
    for field in ("domain", "task_type"):
        counts = Counter(label for record in tasks for label in set(record[field] or []))
        known = sum(bool(t[field]) for t in tasks)
        out[field] = {"counts": dict(sorted(counts.items())), "effective_n": known,
                      "unknown_n": len(tasks) - known,
                      "rates": {k: v / known for k, v in sorted(counts.items())} if known else None}
    return out

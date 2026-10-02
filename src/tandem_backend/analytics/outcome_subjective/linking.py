"""Associate feedback with prior same-session deliveries and explicit object versions."""

from bisect import bisect_left
from collections import defaultdict


def link_feedback_targets(feedback, deliveries):
    """Use an explicit target, otherwise the latest delivery sharing a task ID.

    Explicit broken links never fall back to a convenient newer delivery. Legacy
    task IDs are heuristic; retain those associations only as candidates.
    Indexes keep a long single-task history at O((D + F) log(D + F)).
    """
    by_id, indexes = {}, defaultdict(list)
    for d in sorted(deliveries, key=lambda d: (d["session_uid"], d["seq"], d["delivery_event_uid"])):
        sid = d["session_uid"]
        by_id[(sid, d["delivery_event_uid"])] = d
        if isinstance(d.get("task_id"), str) and d["task_id"]:
            indexes[(sid, "task", d["task_id"], None)].append(d)
        if isinstance(d.get("artifact_id"), str) and d["artifact_id"]:
            indexes[(sid, "artifact", d["artifact_id"], None)].append(d)
            if isinstance(d.get("artifact_version"), str) and d["artifact_version"]:
                indexes[(sid, "artifact", d["artifact_id"], d["artifact_version"])].append(d)
    seqs = {key: [d["seq"] for d in rows] for key, rows in indexes.items()}
    output = []
    for original in sorted(feedback, key=lambda f: (f["session_uid"], f["seq"], f["event_uid"])):
        f = {**original, "delivery_event_uid": None, "feedback_target": None,
             "link_status": "unlinked", "link_reason": None, "completion_scope": None}
        target = f.get("requested_target")
        if target is not None and (not isinstance(target, dict) or any(
                key not in ("delivery_event_uid", "task_id", "artifact_id", "artifact_version")
                or not isinstance(value, str) or not value.strip() for key, value in target.items())):
            f["link_reason"] = "invalid_explicit_target"
            output.append(f)
            continue
        target = target or {}
        sid, task = f["session_uid"], target.get("task_id") or f.get("task_id")
        task = task if isinstance(task, str) and task else None
        d, basis = None, None
        if target.get("delivery_event_uid"):
            d = by_id.get((sid, target["delivery_event_uid"]))
            basis = "explicit_delivery"
        else:
            key = ((sid, "artifact", target["artifact_id"], target.get("artifact_version"))
                   if target.get("artifact_id") else (sid, "task", task, None))
            rows = indexes.get(key, [])
            position = bisect_left(seqs.get(key, []), f["seq"]) - 1
            if position >= 0:
                if position and rows[position - 1]["seq"] == rows[position]["seq"]:
                    f["link_reason"] = "ambiguous_delivery_order"
                else:
                    d = rows[position]
            basis = "explicit_artifact" if target.get("artifact_id") else "same_task_id"
        reason = f["link_reason"]
        if f.get("ambiguous_text_target") and not target:
            reason = "text_target_requires_explicit_reference"
        elif f.get("text_truncated"):
            reason = "truncated_feedback"
        elif target.get("artifact_version") and not target.get("artifact_id") and not target.get("delivery_event_uid"):
            reason = "version_without_object"
        elif d is None:
            reason = reason or ("target_not_in_selected_history" if target else "no_prior_same_task_delivery")
        elif d["seq"] >= f["seq"]:
            reason = "delivery_not_prior"
        elif task and d.get("task_id") != task:
            reason = "task_mismatch"
        elif any(target.get(k) is not None and target[k] != d.get(k) for k in ("artifact_id", "artifact_version")):
            reason = "artifact_mismatch"
        elif d.get("ts") is not None and f.get("ts") is not None and d["ts"] > f["ts"]:
            reason = "timestamp_conflict"
        if reason:
            f["link_reason"] = reason
        else:
            inferred = basis == "same_task_id" and (
                f.get("task_id_source", "explicit") != "explicit" or d.get("task_id_source", "explicit") != "explicit")
            f.update(delivery_event_uid=d["delivery_event_uid"], link_status="candidate" if inferred else "linked",
                     link_reason="heuristic_task_identity" if inferred else None,
                     feedback_target={k: d.get(k) for k in ("session_uid", "task_id", "delivery_event_uid", "artifact_id", "artifact_version")},
                     link_basis=basis,
                     completion_scope="artifact" if target.get("artifact_id") else "task" if task else "delivery")
        output.append(f)
    return output

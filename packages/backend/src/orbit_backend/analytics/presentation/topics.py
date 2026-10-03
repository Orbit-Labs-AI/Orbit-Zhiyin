"""Task-label incidence with source-session/project drill-down, never keyword frequency."""

from collections import defaultdict

from .statistics import project_identity_resolver


def topic_inventory(analysis):
    tasks = analysis.get("tasks", {}).get("records")
    if tasks is None:
        return {"status": "unavailable", "rows": None, "unknown_task_n": None}
    sessions = {s["session_uid"]: s for s in analysis.get("sessions", [])}
    resolve_project = project_identity_resolver(analysis)
    groups = defaultdict(lambda: {"task_ids": set(), "session_uids": set(), "projects": set(),
                                   "unassigned_session_uids": set()})
    unknown = 0
    for task in {t["task_id"]: t for t in tasks}.values():
        details = task.get("domain_details") or []
        unknown += not bool(details)
        for detail in details:
            group = groups[detail["id"]]
            group.update({k: detail.get(k) for k in ("id", "label", "parent_id", "parent_label", "taxonomy_version")})
            group["task_ids"].add(task["task_id"])
            refs = task.get("label_evidence", {}).get("domain_details", {}).get(detail["id"], [])
            ids = {r["session_uid"] for r in refs} & sessions.keys()
            group["session_uids"].update(ids)
            for sid in ids:
                row = sessions[sid]
                identity = resolve_project(row)
                if identity is not None:
                    group["projects"].add(identity)
                else:
                    group["unassigned_session_uids"].add(sid)
    rows = []
    for value in groups.values():
        rows.append({**{k: v for k, v in value.items() if not isinstance(v, set)},
                     "task_count": len(value["task_ids"]), "session_count": len(value["session_uids"]),
                     "project_count": len(value["projects"]),
                     "unknown_project_session_count": len(value["unassigned_session_uids"]),
                     "task_ids": sorted(value["task_ids"]), "session_uids": sorted(value["session_uids"]),
                     "projects": [{"identity_kind": kind, "id": key} for kind, key in sorted(value["projects"], key=str)]})
    return {"status": "partial" if unknown else "available", "unknown_task_n": unknown,
            "rows": sorted(rows, key=lambda r: (-r["task_count"], r["id"])),
            "basis": "distinct tasks with rule-supported subdomains; multi-label incidences, not word frequencies",
            "drilldown": "intersect session_uids with current selection; submit root_session_uids to recompute",
            "semantic_status": "candidate_labels_not_confirmed_personality"}

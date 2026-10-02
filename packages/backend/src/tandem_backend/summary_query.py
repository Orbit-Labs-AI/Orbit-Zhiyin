"""Bounded-memory overview for large imports; semantic analysis remains explicitly scoped."""

import json
from dataclasses import asdict

from tandem_data.query import current_projection


def overview_summary(store, scope):
    """Use canonical member filters; do not substitute aggregates for semantic features."""
    if scope.scene or scope.legacy_project_ids is not None:
        raise ValueError("SQL overview does not support semantic or legacy scopes")
    filters = [
        "v.session_uid NOT IN (SELECT value FROM json_each(:excluded))",
        "v.root_uid NOT IN (SELECT value FROM json_each(:excluded))",
    ]
    params = {"excluded": json.dumps(scope.excluded_session_uids)}
    if scope.agent_ids is not None:
        filters.append("v.session_uid IN (SELECT s.session_uid FROM session s JOIN source src USING(source_id) WHERE src.agent IN (SELECT value FROM json_each(:agents)))")
        params["agents"] = json.dumps(scope.agent_ids)
    if scope.source_ids is not None:
        filters.append("v.session_uid IN (SELECT session_uid FROM session WHERE source_id IN (SELECT value FROM json_each(:sources)))")
        params["sources"] = json.dumps(scope.source_ids)
    for column, values in (
        ("project_id", scope.project_ids),
        ("root_uid", scope.root_session_uids),
        ("effort_raw", scope.effort_raw),
    ):
        if values is not None:
            filters.append(f"v.{column} IN (SELECT value FROM json_each(:{column}))")
            params[column] = json.dumps(values)
    if not scope.include_children:
        filters.append("v.session_uid=v.root_uid")
    if scope.model_ids is not None:
        filters.append(
            "COALESCE((SELECT model_id FROM model_alias a WHERE a.provider=COALESCE(v.provider,'') AND a.model_raw=v.model_raw),"
            "(SELECT model_id FROM model_alias a WHERE a.provider='' AND a.model_raw=v.model_raw),v.model_raw) "
            "IN (SELECT value FROM json_each(:models))"
        )
        params["models"] = json.dumps(scope.model_ids)
    for name, operator in (("from_ts", ">="), ("until_ts", "<")):
        value = getattr(scope, name)
        if value is not None:
            filters.append(f"v.ts {operator} :{name}")
            params[name] = value
    where = " WHERE " + " AND ".join(filters) if filters else ""
    members = (
        "WITH members AS (SELECT v.event_uid,v.session_uid,v.root_uid,v.kind,v.ts,v.text_truncated,"
        "CASE WHEN v.kind='message.user' THEN json_extract(v.attrs,'$.origin') END AS origin "
        "FROM v_analysis_event v" + where + ") "
    )
    with store.connect() as db:
        manifest, run = current_projection(db)
        counts = dict(
            db.execute(
                members + "SELECT COUNT(*) AS events,COUNT(DISTINCT root_uid) AS main_sessions,"
                "COALESCE(SUM(kind='message.user' AND origin='human' AND session_uid=root_uid),0) AS human_messages,"
                "COALESCE(SUM(ts IS NULL),0) AS time_unknown_rows,COALESCE(SUM(text_truncated),0) AS truncated_rows "
                "FROM members",
                params,
            ).fetchone()
        )
        tools = [
            dict(row)
            for row in db.execute(
                members + "SELECT t.name_raw,COUNT(*) AS call_count FROM v_analysis_tool_call t "
                "WHERE t.call_event_uid IN (SELECT event_uid FROM members) OR t.result_event_uid IN (SELECT event_uid FROM members) "
                "GROUP BY t.name_raw ORDER BY call_count DESC,t.name_raw LIMIT 10",
                params,
            )
        ]
    for tool in tools:
        # Historical outcome classification needs the bounded feature engine and its context.
        tool.update(known_failure_count=None, unknown_status_count=None)
    return {
        "input_contract": "tandem-app-summary-v1",
        "analysis_mode": "aggregate_only",
        "message": "当前范围较大，先显示数据库基础统计。详细用量、结果与语义分析请按时间、Agent 或项目缩小范围。",
        "scope": asdict(scope),
        "versions": {
            "projection_run_id": run["run_id"],
            "db_schema_version": manifest["schema_version"],
        },
        "coverage": {
            "events": {
                "status": "partial",
                "rows": counts["events"],
                "time_unknown_rows": counts["time_unknown_rows"],
                "truncated_rows": counts["truncated_rows"],
                "reason": "aggregate_only",
            }
        },
        "overview": {
            "counts": counts,
            "usage": {"status": "excluded", "total_tokens": None, "cost_usd": None},
            "top_tools": tools,
            "subjective_outcomes": {
                "status": "excluded",
                "reason": "narrow_scope_for_semantic_analysis",
            },
        },
    }

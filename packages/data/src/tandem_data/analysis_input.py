"""A consistent, scoped analysis-input-v1 bundle. Metrics remain the analysis team's job."""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from tandem_data.query import current_projection
from tandem_data.store import readonly_connection


@dataclass(frozen=True)
class AnalysisScope:
    display_timezone: str
    project_ids: tuple[str, ...] | None = None
    model_ids: tuple[str, ...] | None = None
    effort_raw: tuple[str, ...] | None = None
    from_ts: int | None = None
    until_ts: int | None = None
    root_session_uids: tuple[str, ...] | None = None
    excluded_session_uids: tuple[str, ...] = ()
    include_children: bool = True

    def __post_init__(self):
        ZoneInfo(self.display_timezone)
        if self.from_ts is not None and self.until_ts is not None and self.from_ts > self.until_ts:
            raise ValueError("from_ts must not exceed until_ts")


JSON_COLUMNS = {
    "attrs",
    "ext",
    "files",
    "paths",
    "attribution",
    "native_key",
    "watermark",
    "source_stat",
    "note",
}


def decoded(row):
    result = dict(row)
    for name in JSON_COLUMNS:
        if isinstance(result.get(name), str):
            result[name] = json.loads(result[name])
    return result


def read_analysis(home: str | Path, scope: AnalysisScope, *, max_events=100000) -> dict:
    """Members are filtered facts; events additionally include their earlier turn context.

    Empty selections mean zero members. Time-unknown facts do not enter bounded statistics.
    A result after until_ts cannot enter historical context. No imported/review/auxiliary trees
    enter this default reader. Consumers of those sources can explicitly query the base tables.
    """
    with closing(readonly_connection(Path(home) / "tandem.db")) as connection:
        connection.execute("BEGIN")
        manifest, run = current_projection(connection)
        sources = [
            decoded(row) for row in connection.execute("SELECT * FROM source ORDER BY source_id")
        ]
        files = [
            decoded(row)
            for row in connection.execute(
                "SELECT * FROM source_file ORDER BY source_id,relative_path"
            )
        ]
        aliases = {
            (row["provider"], row["model_raw"]): row["model_id"]
            for row in connection.execute("SELECT * FROM model_alias")
        }

        def canonical_model(event):
            raw, provider = event["model_raw"], event["provider"] or ""
            return aliases.get((provider, raw), aliases.get(("", raw), raw))

        def permitted_session(row):
            return (
                row["session_uid"] not in scope.excluded_session_uids
                and row["root_uid"] not in scope.excluded_session_uids
                and (scope.root_session_uids is None or row["root_uid"] in scope.root_session_uids)
                and (scope.include_children or row["session_uid"] == row["root_uid"])
            )

        events = []
        for row in connection.execute("SELECT * FROM v_analysis_event ORDER BY session_uid,seq"):
            if permitted_session(row):
                events.append(decoded(row))
                if len(events) > max_events:
                    raise ValueError(
                        "Narrow root_session_uids or read SQL views in batches; event limit exceeded"
                    )

        def member(event):
            return (
                (scope.project_ids is None or event["project_id"] in scope.project_ids)
                and (scope.model_ids is None or canonical_model(event) in scope.model_ids)
                and (scope.effort_raw is None or event["effort_raw"] in scope.effort_raw)
                and (
                    scope.from_ts is None
                    or event["ts"] is not None
                    and event["ts"] >= scope.from_ts
                )
                and (
                    scope.until_ts is None
                    or event["ts"] is not None
                    and event["ts"] < scope.until_ts
                )
            )

        members = {event["event_uid"] for event in events if member(event)}
        selected_turns = {
            event["turn_uid"]
            for event in events
            if event["event_uid"] in members and event["turn_uid"]
        }
        last_seq = {}
        for event in events:
            if event["event_uid"] in members:
                last_seq[event["session_uid"]] = max(
                    last_seq.get(event["session_uid"], -1), event["seq"]
                )
        selected = [
            event
            for event in events
            if event["event_uid"] in members
            or (
                event["turn_uid"] in selected_turns
                and (
                    scope.until_ts is None
                    or event["ts"] is not None
                    and event["ts"] < scope.until_ts
                    or event["ts"] is None
                    and event["seq"] <= last_seq.get(event["session_uid"], -1)
                )
            )
        ]
        selected_ids = {event["event_uid"] for event in selected}
        tools = [
            decoded(row)
            for row in connection.execute("SELECT * FROM v_analysis_tool_call")
            if row["call_event_uid"] in members or row["result_event_uid"] in members
        ]
        # A later result must not leak status/exit code into a historical snapshot.
        event_lookup = {event["event_uid"]: event for event in events}
        for tool in tools:
            result = event_lookup.get(tool["result_event_uid"])
            if (
                result
                and scope.until_ts is not None
                and result["ts"] is not None
                and result["ts"] >= scope.until_ts
            ):
                tool.update(
                    result_event_uid=None,
                    status="unknown",
                    pairing_quality="outside_cutoff",
                    exit_code=None,
                    error_class=None,
                    ended_at=None,
                    duration_ms=None,
                    duration_source="unknown",
                    duration_quality="missing",
                    approval=None,
                    approval_wait_ms=None,
                )
        models = [
            decoded(row)
            for row in connection.execute("SELECT * FROM v_analysis_model_call")
            if row["usage_event_uid"] in members
        ]
        # Native unknown-time tool returns can be context for a selected invocation; never statistical members.
        for tool in tools:
            if tool["result_event_uid"] and tool["result_event_uid"] not in selected_ids:
                result = next(
                    (e for e in events if e["event_uid"] == tool["result_event_uid"]), None
                )
                if result and result["ts"] is None:
                    selected.append(result)
                    selected_ids.add(result["event_uid"])
        sessions = {event["session_uid"] for event in selected}
        roots = {event["root_uid"] for event in selected}
        session_rows = [
            decoded(row)
            for row in connection.execute("SELECT * FROM session")
            if row["session_uid"] in sessions | roots
        ]
        project_ids = {event["project_id"] for event in selected}
        project_rows = [
            decoded(row)
            for row in connection.execute("SELECT * FROM project")
            if row["project_id"] in project_ids
        ]
        turn_rows = [
            decoded(row)
            for row in connection.execute("SELECT * FROM turn")
            if row["turn_uid"] in selected_turns
        ]
        for turn in turn_rows:
            available = [event for event in selected if event["turn_uid"] == turn["turn_uid"]]
            if available:
                turn["first_event_uid"], turn["last_event_uid"] = (
                    available[0]["event_uid"],
                    available[-1]["event_uid"],
                )
            if (
                scope.until_ts is not None
                and turn["ended_at"] is not None
                and turn["ended_at"] >= scope.until_ts
            ):
                turn["ended_at"], turn["status"] = None, "unknown"
        snapshots = [
            decoded(row)
            for row in connection.execute("SELECT * FROM usage_snapshot")
            if row["event_uid"] in members
        ]
        unparsed = connection.execute(
            "SELECT COUNT(*) FROM v_raw_record_ledger WHERE is_current=1 AND disposition='unparsed'"
        ).fetchone()[0]
        unknown = sum(e["kind"] == "unknown" for e in selected)
        time_unknown = sum(e["ts"] is None for e in selected)
        truncated = sum(e["text_truncated"] for e in selected)
        reasons = []
        diagnostics = [
            decoded(row)
            for row in connection.execute(
                "SELECT * FROM ingest_issue ORDER BY stage,code,issue_uid"
            )
        ]
        capture_errors = sum(row["stage"] == "l1" for row in diagnostics)
        if capture_errors:
            reasons.append("capture_errors_or_incomplete_frames")
        if unparsed:
            reasons.append("unparsed_source_records")
        if unknown:
            reasons.append("unknown_event_types")
        if truncated:
            reasons.append("truncated_text")
        source_agents = {source["agent"] for source in sources}
        coverage = {
            "events": {
                "status": "partial" if reasons or time_unknown else "available",
                "rows": len(selected),
                "statistical_rows": len(members),
                "unknown_rows": unknown,
                "truncated_rows": truncated,
                "time_unknown_rows": time_unknown,
                "reasons": reasons,
            },
            "tool_call": {
                "status": "partial"
                if any(t["pairing_quality"] != "native_id" for t in tools)
                else "available",
                "rows": len(tools),
            },
            "model_call": {
                "status": "unavailable"
                if source_agents == {"hermes"}
                else "partial"
                if "hermes" in source_agents or unparsed
                else "available",
                "rows": len(models),
                "reason": "Hermes supplies cumulative snapshots rather than per-call usage"
                if "hermes" in source_agents
                else None,
            },
            "usage_snapshot": {"status": "available", "rows": len(snapshots)},
            "inventory": {
                "status": "unavailable",
                "reason": "Configuration scanning is a separate module",
            },
            "catalog": {"status": "unavailable", "reason": "Catalog is a separate dataset"},
        }
        return {
            "input_contract": "analysis-input-v1",
            "db_schema_version": manifest["schema_version"],
            "parser_version": run["mapper_version"],
            "derivation_version": run["reducer_version"],
            "redaction_version": manifest["redaction_version"],
            "projection_run_id": run["run_id"],
            "scope": asdict(scope),
            "sample_boundary": {
                "sources": sources,
                "files": files,
                "l1_revision_count": run["l1_revision_count"],
            },
            "catalog_snapshot": None,
            "coverage": coverage,
            "projects": project_rows,
            "sessions": session_rows,
            "turns": turn_rows,
            "events": sorted(selected, key=lambda e: (e["session_uid"], e["seq"])),
            "tool_calls": tools,
            "model_calls": models,
            "usage_snapshots": snapshots,
            "statistical_members": {
                "event_uids": sorted(members),
                "tool_call_uids": [t["call_uid"] for t in tools],
                "model_call_uids": [m["call_uid"] for m in models],
            },
            "diagnostics": diagnostics,
        }

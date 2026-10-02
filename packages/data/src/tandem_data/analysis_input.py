"""A consistent, scoped analysis-input-v1 bundle. Metrics remain the analysis team's job."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from tandem_data.coverage import dataset_coverage
from tandem_data.inventory import read_inventory_connection
from tandem_data.payload import restore_row
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
    agent_ids: tuple[str, ...] | None = None
    source_ids: tuple[str, ...] | None = None

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
    "detail",
}


def decoded(row):
    result = dict(row)
    for name in JSON_COLUMNS:
        if isinstance(result.get(name), str):
            result[name] = json.loads(result[name])
    return result


def read_analysis(
    home: str | Path, scope: AnalysisScope, *, max_events=None, include_native=True
) -> dict:
    """Members are filtered facts; events additionally include their earlier turn context.

    Empty selections mean zero members. Time-unknown facts do not enter bounded statistics.
    A result after until_ts cannot enter historical context. No imported/review/auxiliary trees
    enter this default reader. Consumers of those sources can explicitly query the base tables.
    """
    with readonly_connection(Path(home) / "tandem.db") as connection:
        connection.execute("BEGIN")
        manifest, run = current_projection(connection)
        sources = [
            decoded(row) for row in connection.execute("SELECT * FROM source ORDER BY source_id")
        ]
        source_agents = {source["source_id"]: source["agent"] for source in sources}
        session_agents = {
            row["session_uid"]: source_agents.get(row["source_id"])
            for row in connection.execute("SELECT session_uid,source_id FROM session")
        }
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

        # Filter in SQLite before decoding payloads or applying the memory budget.
        # json_each binds arbitrarily long selections without SQLite parameter-limit failures.
        allowed = [
            "session_uid NOT IN (SELECT value FROM json_each(:excluded))",
            "root_uid NOT IN (SELECT value FROM json_each(:excluded))",
        ]
        params = {"excluded": json.dumps(scope.excluded_session_uids)}
        if scope.agent_ids is not None:
            # Apply to members AND linked context before the event memory budget.
            allowed.append(
                "session_uid IN (SELECT s.session_uid FROM session s JOIN source src USING(source_id) "
                "WHERE src.agent IN (SELECT value FROM json_each(:agents)))"
            )
            params["agents"] = json.dumps(scope.agent_ids)
        if scope.root_session_uids is not None:
            allowed.append("root_uid IN (SELECT value FROM json_each(:roots))")
            params["roots"] = json.dumps(scope.root_session_uids)
        if not scope.include_children:
            allowed.append("session_uid=root_uid")
        if scope.source_ids is not None:
            allowed.append(
                "session_uid IN (SELECT session_uid FROM session WHERE source_id IN (SELECT value FROM json_each(:sources)))"
            )
            params["sources"] = json.dumps(scope.source_ids)
        members_sql = list(allowed)
        for field, values in (("project_id", scope.project_ids), ("effort_raw", scope.effort_raw)):
            if values is not None:
                members_sql.append(f"{field} IN (SELECT value FROM json_each(:{field}))")
                params[field] = json.dumps(values)
        if scope.model_ids is not None:
            members_sql.append(
                "COALESCE((SELECT model_id FROM model_alias a WHERE a.provider=COALESCE(v.provider,'') AND a.model_raw=v.model_raw),(SELECT model_id FROM model_alias a WHERE a.provider='' AND a.model_raw=v.model_raw),v.model_raw) IN (SELECT value FROM json_each(:models))"
            )
            params["models"] = json.dumps(scope.model_ids)
        for bound, operator in (("from_ts", ">="), ("until_ts", "<")):
            value = getattr(scope, bound)
            if value is not None:
                members_sql.append(f"ts {operator} :{bound}")
                params[bound] = value
        # The canonical selector below classifies members vs earlier turn context.
        # Metadata outside the selected turn is retained solely to reconstruct a cutoff.
        event_columns = "v.*"
        if not include_native:
            # Native extension payloads can dwarf all measured facts. Analysis and
            # reports use attrs/text/IDs; evidence readers keep the full default.
            names = [
                row["name"] for row in connection.execute("PRAGMA table_info(v_analysis_event)")
            ]
            event_columns = (
                ",".join(f'v."{name}"' for name in names if name != "ext") + ", '{}' AS ext"
            )
        query = (
            "WITH members AS (SELECT event_uid,session_uid,turn_uid FROM v_analysis_event v WHERE "
            + " AND ".join(members_sql)
            + ") SELECT "
            + event_columns
            + " FROM v_analysis_event v WHERE "
            + " AND ".join(allowed)
            + " AND (event_uid IN (SELECT event_uid FROM members) OR turn_uid IN (SELECT turn_uid FROM members)"
            + " OR event_uid IN (SELECT x.event_uid FROM tool_call_event x JOIN v_analysis_tool_call t USING(call_uid)"
            + " WHERE t.call_event_uid IN (SELECT event_uid FROM members) OR t.result_event_uid IN (SELECT event_uid FROM members))"
            + " OR (kind IN ('session.meta','setting.change','session.title') AND session_uid IN (SELECT session_uid FROM members)))"
            + " ORDER BY session_uid,seq"
        )
        if max_events is not None:
            # Check cardinality without loading/decoding potentially huge native payloads.
            # The same read transaction and selector keep this check consistent with the read.
            if not isinstance(max_events, int) or isinstance(max_events, bool) or max_events < 0:
                raise ValueError("max_events must be a nonnegative integer")
            budget_params = {**params, "event_budget": max_events + 1}
            budget_query = query.removesuffix(" ORDER BY session_uid,seq")
            count = connection.execute(
                "SELECT COUNT(*) FROM (" + budget_query + " LIMIT :event_budget)", budget_params
            ).fetchone()[0]
            if count > max_events:
                raise ValueError(
                    f"Analysis event limit exceeded ({max_events}, including turn context). "
                    "Narrow --project-id / --from-ts / --until-ts, or explicitly raise --max-events before the command. "
                    "No partial analysis was returned."
                )
        texts: dict = {}
        events = [
            decoded(restore_row(connection, row, texts))
            for row in connection.execute(query, params)
        ]

        def member(event):
            return (
                (scope.project_ids is None or event["project_id"] in scope.project_ids)
                and (
                    scope.agent_ids is None
                    or session_agents.get(event["session_uid"]) in scope.agent_ids
                )
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
                    and event["kind"]
                    not in (
                        "tool.result",
                        "permission.decision",
                        "turn.end",
                        "model.usage",
                        "subagent.result",
                    )
                    and event["seq"] <= last_seq.get(event["session_uid"], -1)
                )
            )
        ]
        selected_ids = {event["event_uid"] for event in selected}
        # Push member filters into SQLite: json_each binds any selection size, and only
        # matching rows are decoded (previously every call/model/session row was).
        # Unary + keeps these terms off indexes, so SQLite scans in the same order as
        # the former unfiltered reads and row order stays byte-identical.
        member_param = {"members": json.dumps(sorted(members))}
        tools = [
            decoded(row)
            for row in connection.execute(
                "SELECT * FROM v_analysis_tool_call"
                " WHERE +call_event_uid IN (SELECT value FROM json_each(:members))"
                " OR +result_event_uid IN (SELECT value FROM json_each(:members))",
                member_param,
            )
        ]
        # A later result must not leak status/exit code into a historical snapshot.
        event_lookup = {}
        for event in events:
            event_lookup.setdefault(event["event_uid"], event)
        last_decision_ts = {}
        if scope.until_ts is not None and tools:
            # One query for every call's last permission decision (was one query per call).
            last_decision_ts = dict(
                connection.execute(
                    "SELECT call_uid, ts FROM (SELECT c.call_uid, e.ts, ROW_NUMBER() OVER ("
                    "PARTITION BY c.call_uid ORDER BY e.seq DESC) AS rank FROM tool_call_event c"
                    " JOIN event e USING(event_uid) WHERE c.role='permission.decision'"
                    " AND c.call_uid IN (SELECT value FROM json_each(:calls))) WHERE rank=1",
                    {"calls": json.dumps([tool["call_uid"] for tool in tools])},
                ).fetchall()
            )
        for tool in tools:
            result = event_lookup.get(tool["result_event_uid"])
            if scope.until_ts is not None:
                decision_ts = last_decision_ts.get(tool["call_uid"])
                if decision_ts is None or decision_ts >= scope.until_ts:
                    tool["approval"], tool["approval_wait_ms"] = None, None
            if (
                result
                and scope.until_ts is not None
                and (result["ts"] is None or result["ts"] >= scope.until_ts)
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
            for row in connection.execute(
                "SELECT * FROM v_analysis_model_call"
                " WHERE +usage_event_uid IN (SELECT value FROM json_each(:members))",
                member_param,
            )
        ]
        # Native unknown-time tool returns can be context for a selected invocation; never statistical members.
        for tool in tools:
            if tool["result_event_uid"] and tool["result_event_uid"] not in selected_ids:
                result = event_lookup.get(tool["result_event_uid"])
                if result and result["ts"] is None and scope.until_ts is None:
                    selected.append(result)
                    selected_ids.add(result["event_uid"])
        sessions = {event["session_uid"] for event in selected}
        roots = {event["root_uid"] for event in selected}
        session_rows = [
            {**decoded(row), "agent": source_agents.get(row["source_id"])}
            for row in connection.execute(
                "SELECT * FROM session WHERE +session_uid IN (SELECT value FROM json_each(:ids))",
                {"ids": json.dumps(sorted(sessions | roots))},
            )
            if scope.agent_ids is None or source_agents.get(row["source_id"]) in scope.agent_ids
        ]
        if scope.until_ts is not None:
            last_ends = {
                event["session_uid"]: event for event in events if event["kind"] == "turn.end"
            }
            for session in session_rows:
                final_end = last_ends.get(session["session_uid"])
                uncertain_end = final_end is not None and (
                    final_end["ts"] is None or final_end["ts"] >= scope.until_ts
                )
                if (
                    session["ended_at"] is None
                    or session["ended_at"] >= scope.until_ts
                    or uncertain_end
                ):
                    session["ended_at"], session["status"] = None, "unknown"
                if session["started_at"] is not None and session["started_at"] >= scope.until_ts:
                    session["started_at"] = None
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
        # Query order is session/seq. Keep selected endpoints in one pass instead
        # of scanning the full event corpus once per turn (quadratic at real scale).
        turn_bounds = {}
        for event in selected:
            bounds = turn_bounds.setdefault(
                event["turn_uid"], [event["event_uid"], event["event_uid"]]
            )
            bounds[1] = event["event_uid"]
        for turn in turn_rows:
            if bounds := turn_bounds.get(turn["turn_uid"]):
                turn["first_event_uid"], turn["last_event_uid"] = bounds
            if scope.until_ts is not None and (
                turn["ended_at"] is None or turn["ended_at"] >= scope.until_ts
            ):
                turn["ended_at"], turn["status"] = None, "unknown"
        snapshots = [
            decoded(row)
            for row in connection.execute("SELECT * FROM usage_snapshot")
            if row["event_uid"] in members
        ]
        source_wide = (
            scope.root_session_uids is None
            and scope.project_ids is None
            and scope.model_ids is None
            and scope.agent_ids is None
            and scope.effort_raw is None
            and scope.from_ts is None
            and scope.until_ts is None
            and not scope.excluded_session_uids
            and scope.include_children
        )
        unrestricted = source_wide and scope.source_ids is None
        relevant_sources = {row["source_id"] for row in session_rows}
        relevant_files = set()
        ordered_sessions = sorted(sessions)
        for start in range(0, len(ordered_sessions), 500):
            chunk = ordered_sessions[start : start + 500]
            markers = ",".join("?" for _ in chunk)
            relevant_files.update(
                row[0]
                for row in connection.execute(
                    f"SELECT DISTINCT file_id FROM raw_record WHERE session_uid IN ({markers})",
                    chunk,
                )
            )
        if source_wide and scope.source_ids is not None:
            # Selecting a source includes its failed/unmapped files even if it has
            # no publishable session. Other sources cannot affect this selection.
            relevant_sources = {
                s["source_id"] for s in sources if s["source_id"] in scope.source_ids
            }
            relevant_files = {f["file_id"] for f in files if f["source_id"] in relevant_sources}
        if not unrestricted:
            sources = [source for source in sources if source["source_id"] in relevant_sources]
            files = [file for file in files if file["file_id"] in relevant_files]
        unparsed = sum(
            1
            for row in connection.execute(
                "SELECT file_id FROM v_raw_record_ledger WHERE is_current=1 AND disposition='unparsed'"
            )
            if unrestricted or row["file_id"] in relevant_files
        )
        if scope.until_ts is not None:
            historical_metadata = {}
            for event in events:
                if (
                    event["ts"] is not None
                    and event["ts"] < scope.until_ts
                    and event["kind"] in ("session.meta", "setting.change", "session.title")
                ):
                    historical_metadata.setdefault(event["session_uid"], []).append(event)
            latest_visible_turn = {}
            for turn in turn_rows:
                previous = latest_visible_turn.get(turn["session_uid"])
                if previous is None or previous["idx"] < turn["idx"]:
                    latest_visible_turn[turn["session_uid"]] = turn
            for session in session_rows:
                # Reconstruct mutable metadata from dated evidence, not the final L3 row.
                fields = (
                    "cwd",
                    "git_branch",
                    "git_sha",
                    "git_remote",
                    "client",
                    "harness_version",
                    "timezone",
                )
                for field_name in fields:
                    session[field_name] = None
                session["title"], session["title_source"] = None, None
                session["timezone_source"] = "unknown"
                session["project_id"] = None
                title_priority = -1
                for event in historical_metadata.get(session["session_uid"], []):
                    attrs = event["attrs"]
                    if event["kind"] in ("session.meta", "setting.change"):
                        for field_name in fields:
                            if attrs.get(field_name) is not None:
                                session[field_name] = attrs[field_name]
                        if attrs.get("timezone"):
                            session["timezone_source"] = attrs.get("timezone_source", "reported")
                        if attrs.get("cwd"):
                            session["project_id"] = event["project_id"]
                    if event["kind"] == "session.title":
                        priority = {"custom": 3, "native": 2, "ai": 1}.get(
                            attrs.get("title_source"), 0
                        )
                        if priority >= title_priority:
                            session["title"], session["title_source"] = (
                                event["text"],
                                attrs.get("title_source"),
                            )
                            title_priority = priority
                session["status"] = latest_visible_turn.get(session["session_uid"], {}).get(
                    "status", "unknown"
                )
                if session["ended_at"] is None or session["ended_at"] >= scope.until_ts:
                    session["ended_at"] = None
        unknown = sum(e["kind"] == "unknown" for e in selected)
        time_unknown = sum(e["ts"] is None for e in selected)
        truncated = sum(e["text_truncated"] for e in selected)
        reasons = []
        scans = [
            dict(row)
            for row in connection.execute("SELECT * FROM source_scan")
            if unrestricted or row["source_id"] in relevant_sources
        ]
        sampled_scans = sum(row["selection"] == "sample" for row in scans)
        incomplete_scans = sum(
            bool(
                row["cancelled"]
                or row["capture_errors"]
                or (row["selection"] == "full" and row["indexed_files"] < row["discovered_files"])
            )
            for row in scans
        )
        missing_scans = len(
            {row["source_id"] for row in sources} - {row["source_id"] for row in scans}
        )
        scan_reason_counts = {
            "sampled_source_files": sampled_scans,
            "source_scan_incomplete": incomplete_scans,
            "source_scan_boundary_unknown": missing_scans,
        }
        # Discovery completeness and selected-event evidence are separate dimensions.
        # An unknown source inventory must not downgrade unrelated, fully observed rows.
        diagnostics = [
            decoded(row)
            for row in connection.execute(
                "SELECT i.* FROM ingest_issue i LEFT JOIN raw_record r ON r.record_uid=i.record_uid ORDER BY i.stage,i.code,i.issue_uid"
            )
            if unrestricted
            or (
                row["source_id"] in relevant_sources
                and (row["file_id"] is None or row["file_id"] in relevant_files)
            )
        ]
        capture_errors = sum(
            row["stage"] == "l1" and row["detail"].get("status") != "resolved"
            for row in diagnostics
        )
        if capture_errors:
            reasons.append("capture_errors_or_incomplete_frames")
        if any(row["code"] == "source_unavailable" for row in diagnostics):
            reasons.append("source_unavailable_preserved_facts")
        if unparsed:
            reasons.append("unparsed_source_records")
        if any(row["code"] == "inherited_parent_evidence_unavailable" for row in diagnostics):
            reasons.append("inherited_parent_evidence_unavailable")
        if unknown:
            reasons.append("unknown_event_types")
        if truncated:
            reasons.append("truncated_text")
        if time_unknown:
            reasons.append("missing_timestamps")
        diagnostic_counts = Counter(row["code"] for row in diagnostics)
        reason_counts = {
            "capture_errors_or_incomplete_frames": capture_errors,
            "source_unavailable_preserved_facts": diagnostic_counts["source_unavailable"],
            "unparsed_source_records": unparsed,
            "inherited_parent_evidence_unavailable": diagnostic_counts[
                "inherited_parent_evidence_unavailable"
            ],
            "unknown_event_types": unknown,
            "truncated_text": truncated,
            "missing_timestamps": time_unknown,
        }
        pairing_counts = Counter(tool["pairing_quality"] or "unknown" for tool in tools)
        pairing_reasons = {
            "missing_call": "tool_results_without_calls",
            "missing_result": "tool_calls_without_results",
            "outside_cutoff": "tool_results_outside_time_scope",
        }
        tool_reason_counts = Counter()
        for quality, count in pairing_counts.items():
            if quality != "native_id":
                tool_reason_counts[pairing_reasons.get(quality, "ambiguous_tool_pairing")] += count
        source_agents = {source["agent"] for source in sources}
        inventory = read_inventory_connection(
            connection, until_ts=scope.until_ts, project_ids=scope.project_ids
        )
        coverage = {
            "source_scans": {
                **dataset_coverage(
                    None if missing_scans and not scans else len(scans),
                    reason_counts=scan_reason_counts,
                ),
                "scans": scans,
            },
            "sessions": dataset_coverage(len(session_rows)),
            "projects": dataset_coverage(len(project_rows)),
            "turns": dataset_coverage(len(turn_rows)),
            "events": {
                **dataset_coverage(len(selected), reasons=reasons, reason_counts=reason_counts),
                "statistical_rows": len(members),
                "unknown_rows": unknown,
                "truncated_rows": truncated,
                "time_unknown_rows": time_unknown,
                "truncated_by_kind": dict(
                    Counter(e["kind"] for e in selected if e["text_truncated"])
                ),
            },
            "tool_call": {
                **dataset_coverage(len(tools), reason_counts=tool_reason_counts),
                "pairing_quality_counts": dict(pairing_counts),
            },
            "model_call": {
                **dataset_coverage(
                    None if source_agents == {"hermes"} else len(models),
                    reasons=["cumulative_usage_only"]
                    if source_agents == {"hermes"}
                    else ["mixed_model_usage_granularity"]
                    if "hermes" in source_agents
                    else (),
                    reason_counts={"unparsed_source_records": unparsed},
                ),
                "reason": "Hermes supplies cumulative snapshots rather than per-call usage"
                if "hermes" in source_agents
                else None,
            },
            "usage_snapshot": dataset_coverage(len(snapshots)),
            "inventory": inventory["coverage"],
            "catalog": {
                **dataset_coverage(None, reasons=["catalog_not_connected"]),
                "reason": "Catalog is a separate dataset",
            },
        }
        if not include_native:
            coverage["native_event_payload"] = {
                **dataset_coverage(None, excluded=True, reasons=["native_payload_on_demand"]),
                "reason": "Analysis omits event.ext; complete stored evidence remains available by event/record UID",
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
                "inventory_scan_ids": inventory["coverage"].get("scan_ids", []),
            },
            "inventory": inventory["items"],
            "inventory_scans": inventory["scans"],
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

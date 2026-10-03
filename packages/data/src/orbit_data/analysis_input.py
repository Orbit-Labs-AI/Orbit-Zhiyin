"""A consistent, scoped analysis-input-v1 bundle. Metrics remain the analysis team's job."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from orbit_data.contract import TITLE_PRIORITY, TOKENS
from orbit_data.coverage import dataset_coverage
from orbit_data.inventory import read_inventory_connection
from orbit_data.models import PRICE_TABLE_VERSION
from orbit_data.payload import INLINE_TEXT_KINDS, TEXT_MARK, restore_row
from orbit_data.query import published_projection
from orbit_data.store import readonly_connection

# Bumped when read_analysis returns different values for the same database; analysis
# caches key on it. 1.1: undated session metadata stays visible under until_ts.
READER_VERSION = "analysis-input-reader-1.1"


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
    "command_spec",
}


def decoded(row):
    result = dict(row)
    for name in JSON_COLUMNS:
        if isinstance(result.get(name), str):
            result[name] = json.loads(result[name])
    return result


# Event columns whose values repeat across a selection (ids of sessions, turns and projects,
# kinds, model names). SQLite returns a new string per row; sharing one object per value
# saves ~1 KB per event (a real 7-day window holds 300k events, ~8 KB each).
SHARED_EVENT_COLUMNS = (
    "session_uid",
    "root_uid",
    "turn_uid",
    "project_id",
    "cwd",
    "kind",
    "actor",
    "provider",
    "model_raw",
    "effort_raw",
    "contract_version",
    "mapper_version",
)


def _compact(event: dict, shared: dict) -> dict:
    """Share repeated column values and ``attrs`` keys between the events of one read."""
    for name in SHARED_EVENT_COLUMNS:
        value = event.get(name)
        if isinstance(value, str):
            event[name] = shared.setdefault(value, value)
    attrs = event.get("attrs")
    if isinstance(attrs, dict):
        event["attrs"] = {shared.setdefault(key, key): value for key, value in attrs.items()}
    return event


def _without_external_text(connection, row, cache=None) -> dict:
    """``restore_row`` that leaves blob-stored non-message text unread (``None``)."""
    text = row["text"]
    if text and text[0] == TEXT_MARK and row["kind"] not in INLINE_TEXT_KINDS:
        if text[1:2] != TEXT_MARK:  # a doubled mark is inline text, not a reference
            event = dict(row)
            event["text"] = None
            return event
    return restore_row(connection, row, cache)


def _keys(values) -> str:
    return json.dumps(sorted(values))


ANALYSIS_SESSION_KINDS = ("main", "subagent", "workflow_agent")


def _excluded_trees(connection, candidates, scope) -> dict:
    """Sessions in scope that the v_analysis_* views leave out, with their usage.

    The views (migrations/001.sql) keep only main/subagent/workflow_agent sessions under
    a main root with resolved lineage. Review, automation, import and auxiliary trees and
    orphaned children are excluded, so totals built on the views undercount spend; this
    states by how much. Each session is counted once under its first matching reason.
    Token fields are None when no excluded call reported them (unknown, not zero).
    """
    where = [
        "NOT (s.kind IN (SELECT value FROM json_each(:kinds)) AND root.kind='main'"
        " AND s.lineage_unresolved=0)",
        "s.session_uid NOT IN (SELECT value FROM json_each(:excluded))",
        "s.root_uid NOT IN (SELECT value FROM json_each(:excluded))",
    ]
    params = {
        "kinds": json.dumps(ANALYSIS_SESSION_KINDS),
        "excluded": json.dumps(scope.excluded_session_uids),
    }
    if candidates is not None:
        where.append("s.session_uid IN (SELECT value FROM json_each(:candidates))")
        params["candidates"] = _keys(candidates)
    if not scope.include_children:
        where.append("s.session_uid=s.root_uid")
    reasons = Counter()
    uids = []
    for row in connection.execute(
        "SELECT s.session_uid,s.kind,s.lineage_unresolved,root.kind AS root_kind FROM session s"
        " LEFT JOIN session root ON root.session_uid=s.root_uid WHERE " + " AND ".join(where),
        params,
    ):
        uids.append(row["session_uid"])
        if row["lineage_unresolved"]:
            reasons["lineage_unresolved"] += 1
        elif row["kind"] not in ANALYSIS_SESSION_KINDS:
            reasons["kind_" + row["kind"]] += 1
        else:
            reasons["root_not_main"] += 1
    window = []
    call_params = {"uids": _keys(uids)}
    for bound, operator in (("from_ts", ">="), ("until_ts", "<")):
        value = getattr(scope, bound)
        if value is not None:
            window.append(f" AND ts {operator} :{bound}")
            call_params[bound] = value
    fields = (*TOKENS, "cost_usd")
    totals = connection.execute(
        "SELECT COUNT(*)," + ",".join(f"SUM({name})" for name in fields) + " FROM model_call"
        " WHERE session_uid IN (SELECT value FROM json_each(:uids))" + "".join(window),
        call_params,
    ).fetchone()
    # A coverage-v1 entry: rows are the excluded sessions, status 'excluded' when any are.
    return {
        **dataset_coverage(
            len(uids),
            excluded=bool(uids),
            reason_counts={"excluded_" + code: n for code, n in sorted(reasons.items())},
        ),
        "model_calls": totals[0],
        "tokens": {name: totals[i + 1] for i, name in enumerate(TOKENS)},
        "cost_usd": totals[-1],
    }


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _ordered_calls(connection, view: str, table: str, where: str, params: dict) -> list[dict]:
    """Rows of an analysis view for the calls matching ``where``, in base-table rowid order
    (the order a full view scan returns), fetched by primary key instead of a full scan."""
    order = [
        row[0]
        for row in connection.execute(
            f"SELECT call_uid FROM {table} WHERE {where} ORDER BY rowid", params
        )
    ]
    rows = {
        row["call_uid"]: row
        for row in connection.execute(
            f"SELECT * FROM {view} WHERE call_uid IN (SELECT value FROM json_each(?))",
            (json.dumps(order),),
        )
    }
    return [decoded(rows[uid]) for uid in order if uid in rows]


def model_call_row(row) -> dict:
    """A model_call row with the request-boundary contract the token/cost analysis needs.

    model_call only holds ``usage_scope='call'`` / ``measurement='delta'`` usage events (the
    event CHECK and the reducer enforce it; cumulative snapshots live in usage_snapshot), and
    identity and boundary quality remain explicit. The compatibility boolean is derived
    from those qualities; a stable row key alone never proves a request boundary.
    """
    result = decoded(row)
    result.setdefault("usage_scope", "call")
    result.setdefault("measurement", "delta")
    result["boundary_reliable"] = (
        bool(result.get("call_uid"))
        and result.get("request_identity_quality") in ("reported", "derived")
        and result.get("boundary_quality") in ("reported", "observed")
    )
    if result.get("cost_source") == "price_table":
        result.setdefault("price_table_version", PRICE_TABLE_VERSION)
    return result


def read_analysis(
    home: str | Path,
    scope: AnalysisScope,
    *,
    max_events=None,
    include_native=True,
    external_text=True,
) -> dict:
    """Members are filtered facts; events additionally include their earlier turn context.

    ``external_text=False`` leaves the large non-message texts that storage keeps in
    ``content_blob`` (tool output, reasoning, injected context) as ``None`` instead of
    fetching and decompressing each one: the feature analysis reads message texts only
    (identical results on a real 7-day window), and those texts were ~2 KB of every
    event's memory plus one blob lookup per event.

    Empty selections mean zero members. Time-unknown facts do not enter bounded statistics.
    A result after until_ts cannot enter historical context. No imported/review/auxiliary trees
    enter this default reader. Consumers of those sources can explicitly query the base tables.
    """
    with readonly_connection(Path(home) / "orbit.db") as connection:
        connection.execute("BEGIN")
        # The published run is one committed snapshot: newer captures that are still being
        # projected do not make it unreadable (the bundle names ``projection_run_id``).
        manifest, run, _ = published_projection(connection)
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
        context_sql = []  # Filters on event_context columns only (v = event_context or the view).
        for field, values in (("project_id", scope.project_ids), ("effort_raw", scope.effort_raw)):
            if values is not None:
                context_sql.append(f"v.{field} IN (SELECT value FROM json_each(:{field}))")
                params[field] = json.dumps(values)
        if scope.model_ids is not None:
            context_sql.append(
                "COALESCE((SELECT model_id FROM model_alias a WHERE a.provider=COALESCE(v.provider,'') AND a.model_raw=v.model_raw),(SELECT model_id FROM model_alias a WHERE a.provider='' AND a.model_raw=v.model_raw),v.model_raw) IN (SELECT value FROM json_each(:models))"
            )
            params["models"] = json.dumps(scope.model_ids)
        members_sql = allowed + context_sql
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
            # native_key (the source's own record locator, ~300 bytes decoded) is dropped
            # with them: analysis identifies events by event_uid / record_uid.
            event_columns = (
                ",".join(f'v."{name}"' for name in names if name not in ("ext", "native_key"))
                + ", '{}' AS ext, NULL AS native_key"
            )
        # Resolve the selection key-first. A scoped request must never scan the whole event
        # corpus: candidate sessions come from the narrow event_context / session tables,
        # then every event, call and context row is fetched through an indexed key list.
        candidates = None
        if context_sql:
            candidates = {
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT e.session_uid FROM event_context v CROSS JOIN event e"
                    " ON e.event_uid=v.event_uid WHERE " + " AND ".join(context_sql),
                    params,
                )
            }
        for clause in (
            "root_uid IN (SELECT value FROM json_each(:roots))"
            if scope.root_session_uids is not None
            else None,
            "source_id IN (SELECT value FROM json_each(:sources))"
            if scope.source_ids is not None
            else None,
            "source_id IN (SELECT source_id FROM source WHERE agent IN (SELECT value FROM json_each(:agents)))"
            if scope.agent_ids is not None
            else None,
        ):
            if clause is not None:
                found = {
                    row[0]
                    for row in connection.execute(
                        "SELECT session_uid FROM session WHERE " + clause, params
                    )
                }
                candidates = found if candidates is None else candidates & found
        if scope.from_ts is not None or scope.until_ts is not None:
            # Time windows: sessions with an event in the window, found on the (kind, ts)
            # index (one range per kind) instead of scanning every event through the view.
            # A superset of the members' sessions; the exact ts predicate stays below.
            bounds = " AND ".join(
                clause
                for clause, value in (
                    ("ts >= :from_ts", scope.from_ts),
                    ("ts < :until_ts", scope.until_ts),
                )
                if value is not None
            )
            kinds = [row[0] for row in connection.execute("SELECT DISTINCT kind FROM event")]
            found = {
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT session_uid FROM event WHERE kind IN"
                    " (SELECT value FROM json_each(:kinds)) AND " + bounds,
                    {
                        "kinds": json.dumps(kinds),
                        "from_ts": scope.from_ts,
                        "until_ts": scope.until_ts,
                    },
                )
            }
            candidates = found if candidates is None else candidates & found
        candidate_sql = []
        if candidates is not None:
            params["candidates"] = _keys(candidates)
            candidate_sql.append("v.session_uid IN (SELECT value FROM json_each(:candidates))")
        member_rows = connection.execute(
            "SELECT v.event_uid,v.session_uid,v.turn_uid FROM v_analysis_event v WHERE "
            + " AND ".join(candidate_sql + members_sql),
            params,
        ).fetchall()
        keys = {
            "members": _keys(row[0] for row in member_rows),
            "sessions": _keys({row[1] for row in member_rows}),
            "turns": _keys({row[2] for row in member_rows if row[2] is not None}),
        }
        # Tool calls whose call or result is a member. Their evidence is indexed by event
        # and by session; the exact predicate is then checked on the analysis view.
        keys["calls"] = _keys(
            row[0]
            for row in connection.execute(
                "SELECT call_uid FROM tool_call_event WHERE event_uid IN (SELECT value FROM json_each(:members))"
                " UNION SELECT call_uid FROM tool_call WHERE session_uid IN (SELECT value FROM json_each(:sessions))",
                keys,
            )
        )
        keys["calls"] = _keys(
            row[0]
            for row in connection.execute(
                "SELECT call_uid FROM v_analysis_tool_call WHERE call_uid IN (SELECT value FROM json_each(:calls))"
                " AND (call_event_uid IN (SELECT value FROM json_each(:members))"
                " OR result_event_uid IN (SELECT value FROM json_each(:members)))",
                keys,
            )
        )
        # Members, their turns' context, linked tool evidence and session metadata.
        selected_keys = {row[0] for row in member_rows}
        selected_keys.update(
            row[0]
            for row in connection.execute(
                "SELECT event_uid FROM event WHERE turn_uid IN (SELECT value FROM json_each(:turns))"
                " UNION ALL SELECT event_uid FROM event WHERE session_uid IN (SELECT value FROM json_each(:sessions))"
                " AND kind IN ('session.meta','setting.change','session.title')"
                " UNION ALL SELECT event_uid FROM tool_call_event WHERE call_uid IN (SELECT value FROM json_each(:calls))",
                keys,
            )
        )
        params["selected"] = _keys(selected_keys)
        selector = (
            " FROM v_analysis_event v WHERE v.event_uid IN (SELECT value FROM json_each(:selected)) AND "
            + " AND ".join(allowed)
        )
        if max_events is not None:
            # Check cardinality without loading/decoding potentially huge native payloads.
            # The same read transaction and selector keep this check consistent with the read.
            if not isinstance(max_events, int) or isinstance(max_events, bool) or max_events < 0:
                raise ValueError("max_events must be a nonnegative integer")
            budget_params = {**params, "event_budget": max_events + 1}
            count = connection.execute(
                "SELECT COUNT(*) FROM (SELECT 1" + selector + " LIMIT :event_budget)",
                budget_params,
            ).fetchone()[0]
            if count > max_events:
                raise ValueError(
                    f"Analysis event limit exceeded ({max_events}, including turn context). "
                    "Narrow --project-id / --from-ts / --until-ts, or explicitly raise --max-events before the command. "
                    "No partial analysis was returned."
                )
        texts: dict = {}
        shared: dict = {}
        restore = restore_row if external_text else _without_external_text
        events = [
            _compact(decoded(restore(connection, row, texts)), shared)
            for row in connection.execute(
                "SELECT " + event_columns + selector + " ORDER BY v.session_uid,v.seq", params
            )
        ]
        shared.clear()

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
        member_keys = {"members": _keys(members)}
        tools = [
            row
            for row in _ordered_calls(
                connection,
                "v_analysis_tool_call",
                "tool_call",
                "call_uid IN (SELECT value FROM json_each(:calls))",
                keys,
            )
            if row["call_event_uid"] in members or row["result_event_uid"] in members
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
                    wall_elapsed_ms=None,
                    native_execution_ms=None,
                    duration_source="unknown",
                    duration_quality="missing",
                    approval=None,
                    approval_wait_ms=None,
                )
        models = [
            model_call_row(row)
            for row in _ordered_calls(
                connection,
                "v_analysis_model_call",
                "model_call",
                "usage_event_uid IN (SELECT value FROM json_each(:members))",
                member_keys,
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
                "SELECT * FROM session WHERE session_uid IN (SELECT value FROM json_each(?))"
                " ORDER BY rowid",
                (_keys(sessions | roots),),
            )
            if (scope.agent_ids is None or source_agents.get(row["source_id"]) in scope.agent_ids)
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
            for row in connection.execute(
                "SELECT * FROM turn WHERE turn_uid IN (SELECT value FROM json_each(?)) ORDER BY rowid",
                (_keys(selected_turns),),
            )
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
            for row in connection.execute(
                "SELECT * FROM usage_snapshot WHERE event_uid IN (SELECT value FROM json_each(:members))"
                " ORDER BY rowid",
                member_keys,
            )
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
        # Only the relevant files' ledger rows: the ledger view costs subqueries per record.
        unparsed = connection.execute(
            "SELECT COUNT(*) FROM v_raw_record_ledger WHERE is_current=1 AND disposition='unparsed'"
            + ("" if unrestricted else " AND file_id IN (SELECT value FROM json_each(?))"),
            () if unrestricted else (_keys(relevant_files),),
        ).fetchone()[0]
        if scope.until_ts is not None:
            historical_metadata = {}
            for event in events:
                # Undated metadata (time quality missing, e.g. a title record) has no position
                # on the clock, so it belongs to the session in every cutoff; dated metadata
                # counts only before the cutoff. Events arrive in seq order.
                if event["kind"] in ("session.meta", "setting.change", "session.title") and (
                    event["ts"] is None or event["ts"] < scope.until_ts
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
                    if event["kind"] == "session.title" and event["text"] is not None:
                        priority = TITLE_PRIORITY.get(attrs.get("title_source"), 0)
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
        diagnostic_counts = Counter()
        for row in diagnostics:
            # Per-file diagnostics carry the number of records they stand for.
            per_file = row["code"] == "inherited_parent_evidence_unavailable"
            diagnostic_counts[row["code"]] += row["detail"].get("records", 1) if per_file else 1
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
        status_known = sum(
            (session.get("status") or "unknown") != "unknown" for session in session_rows
        )
        unmapped_models = sum(model.get("model_resolution") == "unmapped" for model in models)
        excluded_trees = _excluded_trees(connection, candidates, scope)
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
            "sessions": {
                **dataset_coverage(len(session_rows)),
                # Share of sessions whose final status is known (not 'unknown').
                "status_known_rows": status_known,
                "status_known_share": _share(status_known, len(session_rows)),
            },
            "excluded_sessions": excluded_trees,
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
                # Calls whose raw model name is not in the model table: spellings of one
                # model (e.g. "-latest" aliases) stay separate in per-model breakdowns.
                "unmapped_model_rows": unmapped_models,
                "unmapped_model_share": _share(unmapped_models, len(models)),
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

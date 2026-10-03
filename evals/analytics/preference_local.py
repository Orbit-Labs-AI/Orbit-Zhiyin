"""Opt-in diagnostics of published canonical message facts, without import or migration.

This narrow snapshot reader supports older canonical databases without requiring new
inventory tables. It does not claim the projection is current or measure extraction
accuracy. The feature implementation is reused, never copied into this script.
"""

import argparse
import json
import sqlite3
import tempfile
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from orbit_data.store import readonly_connection

from orbit_backend.analytics.common import semantic_messages
from orbit_backend.analytics.inputs import Scope
from orbit_backend.analytics.instruction import (
    INSTRUCTION_VERSION,
    extract_instruction_constraints,
)
from orbit_backend.analytics.preference import (
    PREFERENCE_EVIDENCE_VERSION,
    PREFERENCE_VERSION,
    build_preference_evidence,
    extract_explicit_preferences,
    summarize_preference_evidence,
)
from orbit_backend.analytics.task import segment_tasks
from orbit_backend.models import stable_id

ROOT = Path(__file__).resolve().parents[2]


def read_snapshot(database, scope, max_messages=100_000):
    """Read only message facts in one transaction, honoring the canonical analysis view."""
    if not database.is_file():
        raise ValueError("--db must be an existing canonical SQLite database")
    if max_messages < 1:
        raise ValueError("--max-messages must be positive")
    clauses = ["s.kind='main'", "e.kind='message.user'",
               "e.session_uid NOT IN (SELECT value FROM json_each(:excluded))",
               "e.root_uid NOT IN (SELECT value FROM json_each(:excluded))"]
    params = {"excluded": json.dumps(scope.excluded_session_uids), "limit": max_messages + 1}
    for name, operator in (("from_ts", ">="), ("until_ts", "<")):
        if (value := getattr(scope, name)) is not None:
            clauses.append(f"e.ts {operator} :{name}")
            params[name] = value
    if scope.project_ids is not None:
        clauses.append("e.project_id IN (SELECT value FROM json_each(:projects))")
        params["projects"] = json.dumps(scope.project_ids)
    query = (
        "SELECT e.event_uid,e.session_uid,e.kind,e.actor,e.seq,e.ts,e.turn_uid,"
        "e.text,e.text_truncated,e.attrs FROM v_analysis_event e "
        "JOIN session s ON e.session_uid=s.session_uid WHERE " + " AND ".join(clauses)
        + " ORDER BY e.session_uid,e.seq,e.event_uid LIMIT :limit"
    )
    with readonly_connection(database) as connection:
        connection.execute("BEGIN")
        manifest = connection.execute("SELECT * FROM schema_manifest").fetchone()
        if manifest is None or manifest["contract_id"] != "orbit-session-v1":
            raise ValueError("Expected canonical orbit-session-v1; staging and legacy ledgers are unsupported")
        events = [dict(row) for row in connection.execute(query, params)]
        if len(events) > max_messages:
            raise ValueError("Message limit exceeded; narrow the time/project filters or raise --max-messages")
        ids = sorted({e["session_uid"] for e in events})
        sessions = [dict(row) for row in connection.execute(
            "SELECT session_uid,root_uid,kind,project_id,started_at FROM session "
            "WHERE session_uid IN (SELECT value FROM json_each(?)) ORDER BY session_uid",
            (json.dumps(ids),))]
        schema = dict(manifest)
    for event in events:
        event["attrs"] = json.loads(event["attrs"])
    return sessions, events, schema


def diagnose(database, scope, max_messages=100_000):
    timings = {}

    def measured(name, action):
        started = time.perf_counter()
        result = action()
        timings[name] = round((time.perf_counter() - started) * 1000, 3)
        return result

    sessions, events, schema = measured("read_snapshot", lambda: read_snapshot(database, scope, max_messages))
    messages = semantic_messages(events, sessions)
    tasks = measured("task_segmentation", lambda: segment_tasks(events, sessions))
    mapping = tasks["task_by_event"]
    instructions = measured("instruction_extraction", lambda: extract_instruction_constraints(
        events, main_ids={s["session_uid"] for s in sessions}))
    preferences = measured("explicit_extraction", lambda: extract_explicit_preferences(events, sessions, mapping))
    evidence = measured("evidence_adapter", lambda: build_preference_evidence(
        preferences, instructions, sessions, mapping))
    summary = measured("evidence_summary", lambda: summarize_preference_evidence(
        evidence, instructions, sessions, mapping))
    eligible = {event["event_uid"] for event in messages}
    constraints = {c["constraint_uid"] for row in instructions for c in row["constraints"]}
    explicit = {p["preference_id"] for p in preferences["records"] + preferences["candidates"]}
    if len({e["evidence_id"] for e in evidence}) != len(evidence):
        raise ValueError("Duplicate evidence IDs")
    for item in evidence:
        sources = explicit if item["source_type"] == "explicit_preference" else constraints
        if not set(item["evidence_event_uids"]) <= eligible or item["source_id"] not in sources:
            raise ValueError("Evidence does not point to eligible human observations")
    report = {
        "status": "evidence_observed" if evidence else "no_evidence",
        "source_read_only": True, "scope": asdict(scope), "snapshot_schema": schema,
        "versions": {"instruction": INSTRUCTION_VERSION, "preference": PREFERENCE_VERSION,
                     "evidence": PREFERENCE_EVIDENCE_VERSION},
        "sample_digest": stable_id(events, sessions),
        "selected_user_messages": len(events), "human_messages": len(messages),
        "usable_human_texts": sum(bool(e["semantic_text"]) and not e.get("text_truncated") for e in messages),
        "explicit_records": len(preferences["records"]), "explicit_candidates": len(preferences["candidates"]),
        "instruction_messages_with_constraints": sum(bool(row["constraints"]) for row in instructions),
        "evidence_count": len(evidence), "by_source_type": summary["by_source_type"],
        "status_counts": dict(sorted(Counter(e["status"] for e in evidence).items())),
        "pending_reasons": dict(sorted(Counter(r for e in evidence if e["status"] == "pending"
                                               for r in e["missing_reasons"]).items())),
        "observed_tasks": summary["observed_tasks"],
        "historical_support": [
            {"dimension": d["dimension"], "explicit_evidence_count": len(d["explicit_evidence_ids"]),
             "values": [{k: v[k] for k in ("value", "support_tasks", "support_sessions", "task_rate")}
                        for v in d["historical_values"]], "conflicting_tasks": len(d["conflicting_tasks"])}
            for d in summary["dimensions"]],
        "timings_ms": timings,
        "checked": ["unique evidence IDs", "eligible human provenance", "source record references"],
        "limitations": ["Published snapshot only; projection freshness is not verified",
                        "No full API, tool/model or clustering analysis; no import or migration",
                        "Counts are historical evidence, not stable preferences or measured accuracy"],
    }
    preferences.update(evidence_schema_version=PREFERENCE_EVIDENCE_VERSION,
                       evidence=evidence, evidence_summary=summary)
    return report, preferences, instructions


def output_directory(requested=None):
    private = (ROOT / ".local").resolve()
    if requested is not None:
        target = requested.expanduser().resolve()
        if not target.is_relative_to(private) or target == private:
            raise ValueError("--output must be a fresh directory under this checkout's .local/")
        target.mkdir(parents=True, exist_ok=False)
        return target
    parent = private / "preference-check"
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="run-", dir=parent))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="existing canonical SQLite snapshot (read-only)")
    parser.add_argument("--from-ts", type=int, help="inclusive UTC milliseconds")
    parser.add_argument("--until-ts", type=int, help="exclusive UTC milliseconds")
    parser.add_argument("--project-id", action="append", help="repeat to select multiple canonical projects")
    parser.add_argument("--exclude-session", action="append", default=[], help="repeat to exclude sessions")
    parser.add_argument("--max-messages", type=int, default=100_000, help="fail rather than silently truncate")
    parser.add_argument("--output", type=Path, help="fresh .local/ directory; default creates a unique run directory")
    args = parser.parse_args(argv)
    try:
        scope = Scope(from_ts=args.from_ts, until_ts=args.until_ts, project_ids=args.project_id,
                      excluded_session_uids=args.exclude_session)
        report, preferences, instructions = diagnose(args.db.expanduser().resolve(), scope, args.max_messages)
        output = output_directory(args.output)
        report["output_directory"] = str(output)
        for filename, data in (("summary.json", report), ("preferences.json", preferences),
                               ("instruction.json", instructions)):
            (output / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

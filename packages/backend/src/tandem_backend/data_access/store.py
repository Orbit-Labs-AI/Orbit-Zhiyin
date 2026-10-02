"""Read-only application adapter. The canonical database remains the only fact store."""

from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from tandem_data.analysis_input import AnalysisScope, decoded, read_analysis
from tandem_data.query import current_projection
from tandem_data.store import readonly_connection

from ..models import Event, utc_time


def report_event(row):
    """Adapt published facts for the existing narrative engine, without parsing native logs."""
    attrs = dict(row["attrs"])
    kinds = {"message.user": "user_message", "message.assistant": "assistant_message",
             "tool.call": "tool_call", "tool.result": "tool_result", "model.usage": "usage",
             "turn.start": "turn_started", "turn.end": "turn_completed"}
    kind = kinds.get(row["kind"], row["kind"])
    # Injected/unknown-origin text cannot become a preference observation.
    if kind == "user_message" and attrs.get("origin") != "human":
        kind = "context"
    if row["kind"] == "turn.end" and attrs.get("status") == "interrupted":
        kind = "turn_interrupted"
    attrs.update(record_uid=row["record_uid"], event_path=row["event_path"],
                 text_truncated=bool(row["text_truncated"]))
    if row["text_truncated"]:
        # Existing narrative checks must treat the preview as incomplete.
        attrs.setdefault("original_chars", len(row.get("text") or "") + 1)
    if attrs.get("content_truncated"):
        attrs.setdefault("original_chars", len(row.get("text") or "") + 1)
    return Event(id=row["event_uid"], session_id=row["session_uid"], ordinal=row["seq"],
                 kind=kind, timestamp=utc_time(row["ts"]), model=row.get("model_raw") or "unknown",
                 turn_id=row.get("turn_uid"), text=row.get("text") or "", call_id=row.get("call_id"),
                 tool=attrs.get("name"), status=attrs.get("status"),
                 duration_ms=attrs.get("duration_ms"), details=attrs)


def report_session(row, project=None):
    return {**row, "id": row["session_uid"], "project_id": row.get("project_id") or "unknown",
            "project": (project or {}).get("name") or "未知项目", "model": row.get("model_raw") or "unknown",
            "title": row.get("title") or "未命名会话", "started_at": utc_time(row.get("started_at")),
            "source_kind": "user" if row["kind"] == "main" else row["kind"]}


class ReportSnapshot:
    """One bounded L2/L3 read transaction for all stages of a narrative report."""

    def __init__(self, bundle):
        self.bundle = bundle
        projects = {p["project_id"]: p for p in bundle["projects"]}
        self._sessions = [report_session(s, projects.get(s["project_id"])) for s in bundle["sessions"]]
        members = set(bundle["statistical_members"]["event_uids"])
        self._events = [report_event(e) for e in bundle["events"] if e["event_uid"] in members]
        mains = {s["session_uid"] for s in bundle["sessions"] if s["kind"] == "main"}
        calls = {c[key]: c for c in bundle["tool_calls"] for key in ("call_event_uid", "result_event_uid") if c[key]}
        for event in self._events:
            if event.kind == "user_message" and event.session_id not in mains:
                event.kind = "context"
            call = calls.get(event.id)
            if call:
                event.tool = call["name_raw"]
                if event.kind == "tool_result":
                    event.status = call["status"]
                    event.duration_ms = call["duration_ms"]
                    event.details.update(start=utc_time(call["started_at"]),
                                         duration_quality=call["duration_quality"],
                                         duration_source=call["duration_source"])
                for key in ("status_scope", "command_head", "argument_digest", "files"):
                    event.details[key] = call[key]

    def sessions(self, project_id=None):
        return [s for s in self._sessions if self.bundle["scope"]["project_ids"] is not None
                or project_id is None or s["project_id"] == project_id]

    def events(self, project_id=None, model=None, session_id=None):
        sessions = {s["id"] for s in self.sessions(project_id)}
        return [e for e in self._events if e.session_id in sessions
                and (self.bundle["scope"]["model_ids"] is not None or model is None or e.model == model)
                and (session_id is None or e.session_id == session_id)]

    def sample_policies(self):
        return [{"source_id": s["source_id"], "before": utc_time(self.bundle["scope"]["until_ts"]),
                 "excluded_sessions": len(self.bundle["scope"]["excluded_session_uids"])}
                for s in self.bundle["sample_boundary"]["sources"]]


class CanonicalStore:
    """Open one short query-only connection per read, safe across API worker threads."""

    def __init__(self, home: str | Path, *, max_events=100000):
        self.max_events = max_events
        self.home = Path(home).expanduser().resolve()
        self.path = self.home / "tandem.db"
        if not self.path.is_file():
            raise ValueError("统一数据库不存在；先运行 tandem init 或 tandem ingest --agent … --root …")

    @contextmanager
    def connect(self):
        with readonly_connection(self.path) as connection:
            connection.execute("BEGIN")
            current_projection(connection)
            yield connection

    def read_bundle(self, scope=None):
        from ..analytics.inputs import Scope
        scope = scope or Scope()
        if scope.legacy_project_ids is not None:
            raise ValueError("统一数据层使用 project_ids；legacy_project_ids 只用于 --db 兼容模式")
        fields = asdict(scope)
        fields.pop("scene")
        fields.pop("legacy_project_ids")
        return read_analysis(self.home, AnalysisScope(**fields), max_events=self.max_events)

    def analysis_bundle(self, scope=None):
        from ..analytics.inputs import AnalysisInputBundle
        return AnalysisInputBundle.from_dict(self.read_bundle(scope))

    def report_snapshot(self, project_id=None, model=None, before=None, *, from_ts=None, until_ts=None):
        from ..analytics.inputs import Scope, millis
        cutoff = millis(before) if before else None
        if before and cutoff is None:
            raise ValueError("before 必须是带时区的 ISO 时间")
        return ReportSnapshot(self.read_bundle(Scope(
            project_ids=[project_id] if project_id is not None else None,
            model_ids=[model] if model is not None else None, from_ts=from_ts,
            until_ts=cutoff if cutoff is not None else until_ts)))

    def counts(self):
        with self.connect() as db:
            return {"sessions": db.execute("SELECT count(*) FROM session").fetchone()[0],
                    "events": db.execute("SELECT count(*) FROM event").fetchone()[0],
                    "projects": db.execute("SELECT count(*) FROM project").fetchone()[0]}

    def sources(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT source_id,agent,label,enabled FROM source ORDER BY source_id")]

    def session_page(self, project_id=None, *, offset=0, limit=50):
        if offset < 0 or not 1 <= limit <= 200:
            raise ValueError("offset 必须非负，limit 必须在 1–200")
        clause, params = (" AND s.project_id=?", [project_id]) if project_id is not None else ("", [])
        base = (" FROM session s JOIN session root ON root.session_uid=s.root_uid "
                "LEFT JOIN project p ON p.project_id=s.project_id "
                "WHERE s.kind IN ('main','subagent','workflow_agent') "
                "AND root.kind='main' AND s.lineage_unresolved=0" + clause)
        with self.connect() as db:
            total = db.execute("SELECT count(*)" + base, params).fetchone()[0]
            rows = db.execute("SELECT s.*,p.name AS project_name" + base +
                              " ORDER BY s.started_at DESC,s.session_uid LIMIT ? OFFSET ?",
                              [*params, limit, offset])
            items = [report_session(dict(r), {"name": r["project_name"]}) for r in rows]
        return {"total": total, "items": items}

    def event_page(self, session_id, *, offset=0, after_seq=None, limit=100):
        if offset < 0 or not 1 <= limit <= 500 or (after_seq is not None and after_seq < -1):
            raise ValueError("无效的分页参数")
        with self.connect() as db:
            exists = db.execute("SELECT 1 FROM session s JOIN session root ON root.session_uid=s.root_uid "
                                "WHERE s.session_uid=? AND s.kind IN ('main','subagent','workflow_agent') "
                                "AND root.kind='main' AND s.lineage_unresolved=0", (session_id,)).fetchone()
            if not exists:
                return None
            total = db.execute("SELECT count(*) FROM v_analysis_event WHERE session_uid=?", (session_id,)).fetchone()[0]
            rows = [decoded(row) for row in db.execute(
                "SELECT * FROM v_analysis_event WHERE session_uid=? AND seq>? ORDER BY seq LIMIT ? OFFSET ?",
                (session_id, after_seq if after_seq is not None else -1, limit, offset))]
        return {"total": total, "items": [report_event(e).to_dict() for e in rows],
                "next_after_seq": rows[-1]["seq"] if rows else None}

    def evidence(self, event_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM v_analysis_event WHERE event_uid=?", (event_id,)).fetchone()
            return report_event(decoded(row)).to_dict() if row else None

    def sessions(self, project_id=None):
        return self.report_snapshot(project_id).sessions(project_id)

    def events(self, project_id=None, model=None, session_id=None):
        return self.report_snapshot(project_id, model).events(project_id, model, session_id)

    def sample_policies(self):
        return self.report_snapshot().sample_policies()

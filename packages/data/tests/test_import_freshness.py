"""Freshness of the published projection while agents keep writing (synthetic sources only).

Regression tests for the v0.0.2 import loop (docs/development/import-pipeline.md, RC-3/RC-4):
a file whose source changed again before its projection is retained, and that retained
revision must neither keep later imports of other sources rebuilding its source nor keep
the published snapshot "pending" forever; a live SQLite index projects the rows it was
captured with instead of failing against rows written a moment later.
"""

import json
import sqlite3

from orbit_data.contract import canonical
from orbit_data.query import current_projection, projection_state
from orbit_data.service import ImportRequest, ImportService
from orbit_data.store import Store, readonly_connection


def line(session, text):
    row = {"type": "user", "sessionId": session, "uuid": text, "message": {"content": text}}
    return canonical(row) + "\n"


def recorder(store, before_projection=None):
    """ImportService whose ``progress`` is recorded; ``before_projection`` runs at normalize."""
    stages = []

    def progress(update):
        stages.append(update)
        if update.get("stage") == "normalize" and before_projection:
            before_projection()

    return ImportService(store, progress=progress), stages


def runs(store):
    return store.db.execute("SELECT COUNT(*) FROM projection_run").fetchone()[0]


def state(home):
    with readonly_connection(home / "orbit.db") as db:
        db.execute("BEGIN")
        return projection_state(db)


def test_retained_file_neither_rebuilds_other_imports_nor_stays_pending(tmp_path):
    claude, pi = tmp_path / "claude", tmp_path / "pi"
    stable, live = claude / "projects/p/stable.jsonl", claude / "projects/p/live.jsonl"
    stable.parent.mkdir(parents=True)
    stable.write_text(line("a", "stable one"))
    live.write_text(line("b", "live one") + line("b", "live two"))
    session = pi / "sessions/one.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(
        canonical({"type": "session", "id": "pi-1", "cwd": "/work"})
        + "\n"
        + canonical({"type": "message", "message": {"role": "user", "content": "hi"}})
        + "\n"
    )

    def rewrite():
        live.write_text(line("b", "rewritten"))

    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("pi", pi))
        service, _ = recorder(store, rewrite)
        result = service.import_source(ImportRequest("claude_code", claude))
        assert result["skipped_files"] == 1  # Retained: its source changed under the projection.
        published = runs(store)

        fresh = state(store.home)
        assert not fresh["pending"] and fresh["retained_files"] == 1
        with readonly_connection(store.home / "orbit.db") as db:
            db.execute("BEGIN")
            current_projection(db)  # Settled: even the strict check reads it as current.

        # v0.0.2: every later import (of any source) rebuilt the retained file's source again.
        service, stages = recorder(store)
        result = service.import_source(ImportRequest("pi", pi))
        assert "projection" not in result
        assert not any(s.get("stage") == "reset_projection" for s in stages)
        assert runs(store) == published

        # The next capture of the live file records a new revision, which is projected.
        service, stages = recorder(store)
        result = service.import_source(ImportRequest("claude_code", claude))
        assert result["skipped_files"] == 0 and result["changed"] == 1
        watermark = json.loads(
            store.db.execute(
                "SELECT watermark FROM source_file WHERE relative_path LIKE '%live.jsonl'"
            ).fetchone()[0]
        )
        assert "retained_revision" not in watermark
        assert watermark["projected_revision"] == watermark["revision"]
        assert not store.db.execute(
            "SELECT 1 FROM ingest_issue WHERE code='source_unavailable'"
        ).fetchone()
        assert state(store.home)["retained_files"] == 0


def test_settled_retained_file_is_retained_from_the_first_attempt(tmp_path):
    claude = tmp_path / "claude"
    stable, live = claude / "projects/p/stable.jsonl", claude / "projects/p/live.jsonl"
    stable.parent.mkdir(parents=True)
    stable.write_text(line("a", "stable one"))
    live.write_text(line("b", "live one"))

    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("claude_code", claude))
        live.write_text(line("b", "live one") + line("b", "live two"))
        service, _ = recorder(store, lambda: live.write_text(line("b", "rewritten")))
        assert service.import_source(ImportRequest("claude_code", claude))["skipped_files"] == 1
        # Only the stable file is captured again; its source is rebuilt as a whole (two
        # files are too few for a session closure). The retained file's live source no
        # longer matches its captured revision: v0.0.2 read it anyway, rolled the whole
        # rebuild back and reran it with the file retained.
        stable.write_text(line("a", "stable one") + line("a", "stable two"))
        service, stages = recorder(store)
        result = service.import_source(ImportRequest("claude_code", claude, files=(stable,)))
        attempts = [s.get("attempt") for s in stages if s.get("stage") == "reset_projection"]
        assert attempts == [1]
        assert result["projection"]["skipped_files"] == 1
        texts = sorted(
            r[0] for r in store.db.execute("SELECT text FROM event WHERE kind='message.user'")
        )
        assert texts == ["live one", "stable one", "stable two"]


def codex_root(tmp_path):
    root = tmp_path / "codex"
    rollout = root / "sessions/rollout-t1.jsonl"
    rollout.parent.mkdir(parents=True)
    rows = [
        {
            "type": "session_meta",
            "timestamp": "2026-10-01T00:00:00.000Z",
            "payload": {"id": "t1", "cwd": "/work", "source": "cli"},
        },
        {
            "type": "event_msg",
            "timestamp": "2026-10-01T00:00:01.000Z",
            "payload": {"type": "user_message", "message": "hello"},
        },
    ]
    rollout.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with sqlite3.connect(root / "state_5.sqlite") as db:
        db.execute(
            "CREATE TABLE threads(id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT, "
            "updated_at INTEGER)"
        )
        db.execute("INSERT INTO threads VALUES('t1', ?, 'Captured title', 1)", (str(rollout),))
    return root


def test_live_sqlite_index_projects_the_rows_it_was_captured_with(tmp_path):
    root = codex_root(tmp_path)

    def codex_writes():
        with sqlite3.connect(root / "state_5.sqlite") as db:
            db.execute("UPDATE threads SET title='Written later', updated_at=2")

    with Store(tmp_path / "data") as store:
        service, stages = recorder(store, codex_writes)
        result = service.import_source(ImportRequest("codex", root))
        # v0.0.2: the digest check failed, the rebuild rolled back and reran, and the index
        # stayed retained (unparsed rows, job "partial") for as long as Codex kept writing.
        assert result["skipped_files"] == 0
        assert result["current_unparsed"] == 0
        assert [s.get("attempt") for s in stages if s.get("stage") == "reset_projection"] == [1]
        assert store.db.execute("SELECT title FROM session").fetchone()[0] == "Captured title"
        assert not state(store.home)["pending"]

        # The next scan captures the newer rows as a new revision and publishes them.
        result = ImportService(store).import_source(ImportRequest("codex", root))
        assert result["changed"] == 1 and result["skipped_files"] == 0
        assert store.db.execute("SELECT title FROM session").fetchone()[0] == "Written later"

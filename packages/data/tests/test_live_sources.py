"""Agents keep writing their logs while Tandem imports them (synthetic sources only)."""

import json

from tandem_data.contract import canonical
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store


def line(session, text):
    row = {"type": "user", "sessionId": session, "uuid": text, "message": {"content": text}}
    return canonical(row) + "\n"


def texts(store):
    return sorted(
        row[0] for row in store.db.execute("SELECT text FROM event WHERE kind='message.user'")
    )


def importer(store, before_projection=None):
    """Run ``before_projection`` after capture, just before the rebuild starts."""

    def progress(update):
        if update.get("stage") == "normalize" and before_projection:
            before_projection()

    return ImportService(store, progress=progress)


def test_append_after_capture_projects_captured_bytes_and_next_ingest_adds_tail(tmp_path):
    root = tmp_path / "claude"
    path = root / "projects/p/live.jsonl"
    path.parent.mkdir(parents=True)
    # The writer is mid-flush at capture time: the last line has no newline yet.
    path.write_text(line("s", "one") + line("s", "two") + line("s", "three")[:12])

    def keep_writing():
        with path.open("a") as handle:
            handle.write(line("s", "three")[12:] + line("s", "four"))

    request = ImportRequest("claude_code", root)
    with Store(tmp_path / "data") as store:
        result = importer(store, keep_writing).import_source(request)
        assert result["skipped_files"] == 0
        assert result["projection"]["skipped_files"] == 0
        assert store.db.execute("SELECT COUNT(*) FROM projection_run").fetchone()[0] == 1
        assert texts(store) == ["one", "two"]
        assert not store.db.execute("SELECT 1 FROM ingest_issue WHERE stage='l2'").fetchone()
        # The captured prefix is intact, so its evidence still verifies.
        assert store.verify()["integrity"] == "ok"

        result = ImportService(store).import_source(request)
        assert result["changed"] == 1
        assert result["skipped_files"] == result["current_unparsed"] == 0
        assert texts(store) == ["four", "one", "three", "two"]
        assert store.db.execute("SELECT COUNT(*) FROM projection_run").fetchone()[0] == 2


def test_rewritten_file_is_skipped_and_never_blocks_the_projection(tmp_path):
    root = tmp_path / "claude"
    stable, live = root / "projects/p/stable.jsonl", root / "projects/p/live.jsonl"
    stable.parent.mkdir(parents=True)
    stable.write_text(line("a", "stable one"))
    live.write_text(line("b", "live one") + line("b", "live two"))
    request = ImportRequest("claude_code", root)

    def rewrite():
        live.write_text(line("b", "rewritten"))

    def issues(store):
        return [
            json.loads(row[0])
            for row in store.db.execute(
                "SELECT detail FROM ingest_issue WHERE code='source_unavailable'"
            )
        ]

    with Store(tmp_path / "data") as store:
        # First import: nothing published yet, yet the other file is still projected.
        result = importer(store, rewrite).import_source(request)
        assert result["skipped_files"] == 1
        assert store.db.execute("SELECT COUNT(*) FROM projection_run").fetchone()[0] == 1
        assert texts(store) == ["stable one"]
        assert issues(store) == [{"facts": "previously_published", "status": "changed"}]
        live_status = "SELECT status FROM source_file WHERE relative_path LIKE '%live.jsonl'"
        assert store.db.execute(live_status).fetchone()[0] == "active"  # Not gone upstream.

        # The next import captures the new revision and projects it.
        result = ImportService(store).import_source(request)
        assert result["skipped_files"] == 0
        assert texts(store) == ["rewritten", "stable one"]
        assert issues(store) == []

        # With a published projection, a file rewritten after capture keeps its last facts.
        stable.write_text(line("a", "stable one") + line("a", "stable two"))
        live.write_text(line("b", "rewritten") + line("b", "appended"))

        def rewrite_again():
            live.write_text(line("b", "third version"))

        result = importer(store, rewrite_again).import_source(request)
        assert result["skipped_files"] == 1
        assert texts(store) == ["rewritten", "stable one", "stable two"]
        kept = store.db.execute("SELECT attrs FROM event WHERE text='rewritten'").fetchone()[0]
        assert json.loads(kept)["source_status"] == "changed"
        assert issues(store) == [{"facts": "previously_published", "status": "changed"}]
        assert store.verify()["integrity"] == "partial"

        result = ImportService(store).import_source(request)
        assert result["skipped_files"] == result["current_unparsed"] == 0
        assert texts(store) == ["stable one", "stable two", "third version"]
        assert "source_status" not in json.loads(
            store.db.execute("SELECT attrs FROM event WHERE text='third version'").fetchone()[0]
        )
        assert issues(store) == []
        assert store.verify()["integrity"] == "ok"

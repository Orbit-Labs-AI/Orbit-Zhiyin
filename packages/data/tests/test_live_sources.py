"""Agents keep writing their logs while Tandem imports them (synthetic sources only)."""

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
        assert "projection" in result
        assert store.db.execute("SELECT COUNT(*) FROM projection_run").fetchone()[0] == 1
        assert texts(store) == ["one", "two"]
        assert not store.db.execute("SELECT 1 FROM ingest_issue WHERE stage='l2'").fetchone()
        # The captured prefix is intact, so its evidence still verifies.
        assert store.verify()["integrity"] == "ok"

        result = ImportService(store).import_source(request)
        assert result["changed"] == 1
        assert result["current_unparsed"] == 0
        assert texts(store) == ["four", "one", "three", "two"]
        assert store.db.execute("SELECT COUNT(*) FROM projection_run").fetchone()[0] == 2

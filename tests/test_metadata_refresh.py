import sqlite3

import pytest
from fastapi.testclient import TestClient

from tandem_backend.api import create_app
from tandem_backend.cli import demo_home
from tandem_backend.importers.codex import metadata_index
from tandem_backend.store import Store, import_codex


@pytest.mark.parametrize("marker", ["guardian_review", "subagent"])
def test_metadata_change_excludes_unchanged_source(tmp_path, marker):
    home = demo_home(tmp_path / "codex")
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home)
    source = home / "sessions" / "demo-0.jsonl"
    original_stat = source.stat()
    with sqlite3.connect(home / "state_5.sqlite") as conn:
        conn.execute("CREATE TABLE threads (id TEXT, thread_source TEXT, title TEXT)")
        conn.execute("INSERT INTO threads VALUES (?,?,?)", ("demo-0", marker, "automatic"))
    result = import_codex(store, home)
    assert source.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert source.stat().st_size == original_stat.st_size
    assert result.skip_reasons["non_user_session"] == 1
    assert "demo-0" not in {s["id"] for s in store.sessions()}
    assert store.events(session_id="demo-0") == []


def test_metadata_only_title_change_refreshes_without_mutating_source(tmp_path):
    home = demo_home(tmp_path / "codex")
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home)
    with sqlite3.connect(home / "state_5.sqlite") as conn:
        conn.execute("CREATE TABLE threads (id TEXT, title TEXT)")
        conn.execute("INSERT INTO threads VALUES (?,?)", ("demo-0", "changed title"))
    result = import_codex(store, home)
    assert result.imported == 1
    assert result.unchanged == 2
    assert next(s for s in store.sessions() if s["id"] == "demo-0")["title"] == "changed title"
    assert import_codex(store, home).unchanged == 3


def test_metadata_version_is_numeric_not_lexicographic(tmp_path):
    for version, title in ((9, "old"), (10, "new")):
        with sqlite3.connect(tmp_path / f"state_{version}.sqlite") as conn:
            conn.execute("CREATE TABLE threads (id TEXT, title TEXT)")
            conn.execute("INSERT INTO threads VALUES (?,?)", ("s", title))
    assert metadata_index(tmp_path)["s"]["title"] == "new"


def test_metadata_titles_are_redacted_before_storage_and_api_listing(tmp_path):
    home = demo_home(tmp_path / "codex")
    secret = "sk-" + "X" * 24
    with sqlite3.connect(home / "state_5.sqlite") as conn:
        conn.execute("CREATE TABLE threads (id TEXT, title TEXT)")
        conn.execute("INSERT INTO threads VALUES (?,?)", ("demo-0", "debug " + secret))
    store = Store(tmp_path / "data.sqlite")
    import_codex(store, home)
    assert secret not in str(store.sessions())
    with TestClient(create_app(store.path)) as client:
        assert secret not in client.get("/v1/sessions").text
        assert "密钥已隐藏" in client.get("/v1/sessions").text

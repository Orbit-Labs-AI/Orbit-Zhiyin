"""Data and settings from before the rename to Orbit (orbit_data.legacy).

orbit-rename: keep-file — these tests write the legacy names on purpose.
"""

import sqlite3

from orbit_data import CONTRACT_ID, legacy
from orbit_data.query import projection_state
from orbit_data.store import Store


def test_old_settings_apply_when_the_new_ones_are_unset():
    environ = {"TANDEM_HOME": "/old", "TANDEM_ANALYSIS_WORKERS": "2", "ORBIT_ANALYSIS_WORKERS": "4"}
    legacy.adopt_env(environ)
    assert environ["ORBIT_HOME"] == "/old"
    assert environ["ORBIT_ANALYSIS_WORKERS"] == "4"


def test_old_app_folder_moves_once_and_leaves_a_link(tmp_path):
    old, home = tmp_path / "Tandem", tmp_path / "Orbit"
    (old / "hooks").mkdir(parents=True)
    (old / "hooks/events.jsonl").write_text("{}\n")
    legacy.move_app_dir(home)
    assert (home / "hooks/events.jsonl").read_text() == "{}\n"
    assert old.is_symlink() and (old / "hooks/events.jsonl").read_text() == "{}\n"
    legacy.move_app_dir(home)  # idempotent
    assert old.is_symlink()


def test_existing_orbit_folder_is_never_replaced(tmp_path):
    (tmp_path / "Tandem").mkdir()
    (tmp_path / "Orbit").mkdir()
    (tmp_path / "Orbit/keep").write_text("x")
    legacy.move_app_dir(tmp_path / "Orbit")
    assert (tmp_path / "Tandem").is_dir() and not (tmp_path / "Tandem").is_symlink()
    assert (tmp_path / "Orbit/keep").read_text() == "x"


def test_old_database_is_renamed_and_its_contract_id_rewritten(tmp_path):
    home = tmp_path / "home"
    with Store(home):
        pass
    (home / "orbit.db").rename(home / "tandem.db")
    with sqlite3.connect(home / "tandem.db") as db:
        db.execute("UPDATE schema_manifest SET contract_id = ?", (legacy.CONTRACT_ID,))
    db.close()
    # readers accept the old id until the writer has rewritten it
    reader = sqlite3.connect(home / "tandem.db")
    reader.row_factory = sqlite3.Row
    try:
        projection_state(reader)
    except ValueError as exc:
        assert "Expected canonical" not in str(exc)
    reader.close()
    (home / "agent-cwd").mkdir()
    (home / "agent-cwd" / legacy.AI_MARKER_FILE).write_text("{}\n")
    with Store(home):
        pass
    assert (home / "orbit.db").is_file() and not (home / "tandem.db").exists()
    assert (home / "agent-cwd/.orbit-ai").is_file()
    with sqlite3.connect(home / "orbit.db") as db:
        assert db.execute("SELECT contract_id FROM schema_manifest").fetchone()[0] == CONTRACT_ID
    db.close()


def test_old_ai_artifact_placeholders_are_upgraded():
    text = '{"command": "python3 \\"{tandem.hooks}/retry-breaker@1.py\\"", "target": "tandem.hooks/x.json"}'
    assert legacy.upgrade_artifact(text) == text.replace("tandem.hooks", "orbit.hooks")
    assert legacy.upgrade_artifact("<!-- tandem:rule id=a -->") == "<!-- orbit:rule id=a -->"
    assert legacy.upgrade_artifact(None) is None


def test_bundled_catalog_sources_keep_their_rows(tmp_path):
    conn = sqlite3.connect(tmp_path / "catalog.db", isolation_level=None)
    conn.executescript("""
        CREATE TABLE catalog_source (source_id TEXT PRIMARY KEY, spec TEXT NOT NULL);
        CREATE TABLE sync_run (run_id TEXT PRIMARY KEY, source_id TEXT NOT NULL);
        CREATE TABLE item_source (source_id TEXT NOT NULL, native_id TEXT NOT NULL, item_id TEXT,
                                  PRIMARY KEY(source_id, native_id));
        INSERT INTO catalog_source VALUES ('tandem-seeds', '{"source_id": "tandem-seeds"}'), ('tandem-kb', '{}'),
                                          ('orbit-kb', '{}');
        INSERT INTO sync_run VALUES ('r1', 'tandem-seeds'), ('r2', 'tandem-kb');
        INSERT INTO item_source VALUES ('tandem-seeds', 'a', 'i1'), ('tandem-kb', 'k', 'i2'), ('orbit-kb', 'k', 'i2');
    """)
    assert legacy.has_catalog_sources(conn)
    conn.execute("BEGIN")
    legacy.rename_catalog_sources(conn)
    conn.execute("COMMIT")
    assert not legacy.has_catalog_sources(conn)
    assert conn.execute("SELECT source_id, spec FROM catalog_source ORDER BY 1").fetchall() == [
        ("orbit-kb", "{}"),
        ("orbit-seeds", '{"source_id": "orbit-seeds"}'),
    ]
    assert conn.execute("SELECT source_id FROM sync_run ORDER BY run_id").fetchall() == [
        ("orbit-seeds",),
        ("orbit-kb",),
    ]
    assert sorted(conn.execute("SELECT source_id, native_id FROM item_source").fetchall()) == [
        ("orbit-kb", "k"),
        ("orbit-seeds", "a"),
    ]
    conn.close()

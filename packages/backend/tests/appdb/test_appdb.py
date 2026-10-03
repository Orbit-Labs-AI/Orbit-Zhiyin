import sqlite3
import threading

import pytest

from orbit_backend.appdb import AppDB
from orbit_backend.appdb.store import _statements


def test_open_twice_and_refuse_foreign_db(tmp_path):
    db = AppDB(tmp_path / "app.db")
    with db.write() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER) STRICT")
        conn.execute("INSERT INTO t VALUES (1)")
    with db.read() as conn:
        assert conn.execute("SELECT x FROM t").fetchone()[0] == 1
    db.close()
    AppDB(tmp_path / "app.db").close()
    sqlite3.connect(tmp_path / "other.db").execute("CREATE TABLE a (x)").connection.commit()
    with pytest.raises(ValueError):
        AppDB(tmp_path / "other.db")


def test_writer_rolls_back_and_serializes(tmp_path):
    db = AppDB(tmp_path / "app.db")
    with db.write() as conn:
        conn.execute("CREATE TABLE c (n INTEGER) STRICT")
        conn.execute("INSERT INTO c VALUES (0)")
    with pytest.raises(RuntimeError), db.write() as conn:
        conn.execute("UPDATE c SET n = 99")
        raise RuntimeError
    def bump():
        for _ in range(50):
            with db.write() as conn:
                conn.execute("UPDATE c SET n = n + 1")
    threads = [threading.Thread(target=bump) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with db.read() as conn:
        assert conn.execute("SELECT n FROM c").fetchone()[0] == 200
    db.close()


def test_statement_split_keeps_trigger_bodies():
    sql = "CREATE TABLE a (x);\nCREATE TRIGGER t AFTER INSERT ON a BEGIN\n SELECT 1;\n SELECT 2;\nEND;\n"
    assert len(list(_statements(sql))) == 2


def _old_install_ledger_db(path):
    """An app.db as an earlier release left it: install_ledger without inv_id / catalog_item_id
    and no schema_version table, with one ledger row."""
    from orbit_backend.appdb.store import APPLICATION_ID

    db = sqlite3.connect(path)
    db.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    db.execute("CREATE TABLE install_ledger (entry_id TEXT PRIMARY KEY, ts INTEGER NOT NULL, "
               "actor TEXT NOT NULL, action TEXT NOT NULL, install_id TEXT, note TEXT) STRICT")
    db.execute("INSERT INTO install_ledger VALUES ('e1', 5, 'user', 'install', 'in_1', 'kept')")
    db.commit()
    db.close()


def test_old_database_is_upgraded_and_keeps_rows(tmp_path):
    from orbit_backend.appdb import migrations

    _old_install_ledger_db(tmp_path / "app.db")
    db = AppDB(tmp_path / "app.db")
    with db.read() as conn:
        cols = migrations.columns(conn, "install_ledger")
        row = conn.execute("SELECT entry_id, install_id, note, inv_id, catalog_item_id "
                           "FROM install_ledger").fetchone()
        version = conn.execute("SELECT version FROM schema_version WHERE module = 'install'").fetchone()[0]
    assert {"inv_id", "catalog_item_id"} <= cols
    assert tuple(row) == ("e1", "in_1", "kept", None, None)
    assert version == len(migrations.MIGRATIONS["install"]) == 2
    with db.write() as conn:  # the new column is writable
        conn.execute("INSERT INTO install_ledger (entry_id, ts, actor, action, inv_id) "
                     "VALUES ('e2', 6, 'orbit', 'link', 'inv-9')")
    db.close()
    AppDB(tmp_path / "app.db").close()  # reopening runs nothing twice (no duplicate-column error)


def test_fresh_database_marks_steps_applied_without_altering(tmp_path):
    db = AppDB(tmp_path / "app.db")
    with db.read() as conn:
        assert dict(conn.execute("SELECT module, version FROM schema_version").fetchall())["install"] == 2
    db.close()


def test_steps_run_in_order_once_and_refuse_newer_db(tmp_path):
    from orbit_backend.appdb import migrations

    db = AppDB(tmp_path / "app.db")
    with db.write() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS demo (a TEXT) STRICT")
    ran = []

    def backfill(conn):
        ran.append("backfill")
        conn.execute("UPDATE demo SET b = 'x'")

    steps = {"demo": [migrations.add_column("demo", "b", "TEXT"), backfill]}
    assert migrations.apply(db, steps)["demo"] == 2
    assert migrations.apply(db, steps)["demo"] == 2 and ran == ["backfill"]
    with pytest.raises(RuntimeError):
        migrations.apply(db, {"demo": steps["demo"][:1]})  # app.db from a newer build
    db.close()


def test_failed_step_rolls_back_with_its_version(tmp_path):
    from orbit_backend.appdb import migrations

    db = AppDB(tmp_path / "app.db")

    def broken(conn):
        conn.execute("CREATE TABLE half (x INTEGER)")
        raise sqlite3.OperationalError("boom")

    with pytest.raises(sqlite3.OperationalError):
        migrations.apply(db, {"m": [broken]})
    with db.read() as conn:
        assert conn.execute("SELECT version FROM schema_version WHERE module = 'm'").fetchone() is None
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'half'").fetchone() is None
    db.close()

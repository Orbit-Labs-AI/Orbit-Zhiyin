import sqlite3
import threading

import pytest

from tandem_backend.appdb import AppDB
from tandem_backend.appdb.store import _statements


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

"""Prevent per-row foreign-key table scans during multi-source projection replacement."""

from tandem_data.store import Store


def test_reverse_foreign_key_lookups_have_indexed_plans(tmp_path):
    with Store(tmp_path / "data") as store:
        names = [
            row[0] for row in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        for table in names:
            for fk in store.db.execute(f'PRAGMA foreign_key_list("{table}")'):
                column = fk["from"]
                plan = store.db.execute(
                    f'EXPLAIN QUERY PLAN SELECT rowid FROM "{table}" WHERE "{column}"=?',
                    ("fixture",),
                ).fetchall()
                assert all("SCAN " not in row[3] for row in plan), (
                    table,
                    column,
                    [row[3] for row in plan],
                )

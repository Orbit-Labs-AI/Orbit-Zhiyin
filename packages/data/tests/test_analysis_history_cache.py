"""analysis.sqlite v2: in-place upgrade, verified caches, exclusions and retention."""

import sqlite3
from importlib.resources import files

import pytest

from tandem_data.analysis_history import SCHEMA_VERSION, AnalysisHistory


def v1_database(path):
    """Create a v1 history exactly as the previous release wrote it."""
    connection = sqlite3.connect(path)
    connection.executescript(
        files("tandem_data").joinpath("migrations/analysis/001.sql").read_text()
        + "\nPRAGMA user_version=1;"
    )
    connection.close()


def test_v1_history_upgrades_in_place_and_old_runs_stay_readable(tmp_path):
    path = tmp_path / "analysis.sqlite"
    v1_database(path)
    # Write a v1 run with the v1 column set before the upgrade exists.
    connection = sqlite3.connect(path)
    import hashlib
    import zlib

    data = b'{"value":1}'
    sid = hashlib.sha256(data).hexdigest()
    connection.execute(
        "INSERT INTO analysis_snapshot VALUES(?,?,?,?,?,?)",
        (sid, None, "v1", len(data), zlib.compress(data), 1),
    )
    connection.execute(
        "INSERT INTO analysis_run(run_id,engine,status,started_at,finished_at,request_json,snapshot_id)"
        " VALUES('old','features','completed',1,2,'{}',?)",
        (sid,),
    )
    connection.commit()
    connection.close()

    history = AnalysisHistory(path)
    with history.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 3
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"session_result", "analysis_section", "analysis_row", "session_exclusion"} <= tables
    assert history.result("old") == {"value": 1}
    old = history.get_run("old")
    assert old["request_key"] is None and old["cache_hit"] == 0
    # Reopening a current database is a no-op; a newer one is refused.
    AnalysisHistory(path)
    with history.connect() as db:
        db.execute("PRAGMA user_version=4")
    with pytest.raises(ValueError, match="Unsupported"):
        AnalysisHistory(path)


def test_sections_rows_and_session_results_round_trip_with_checksums(tmp_path):
    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    rows = [(f"s{i}", {"session_uid": f"s{i}", "n": i}) for i in range(5)]
    history.put_sections(
        "rk", "fp1", {"overview": {"a": 1}, "sessions": {"count": 5}}, {"sessions": rows}
    )
    assert history.sections("rk", "fp1", ["overview", "missing"]) == {"overview": {"a": 1}}
    assert history.sections("rk", "fp2", ["overview"]) == {}
    page = history.section_rows("rk", "fp1", "sessions", offset=3, limit=10)
    assert page["total"] == 5 and [r["n"] for r in page["items"]] == [3, 4]
    assert history.section_row("rk", "fp1", "sessions", "s2") == {"session_uid": "s2", "n": 2}
    assert history.section_row("rk", "fp1", "sessions", "nope") is None
    # Republishing replaces the rows rather than appending to them.
    history.put_sections("rk", "fp1", {"sessions": {"count": 1}}, {"sessions": rows[:1]})
    assert history.section_rows("rk", "fp1", "sessions")["total"] == 1
    with history.connect() as db:
        hits = db.execute("SELECT hits FROM analysis_section WHERE section='overview'").fetchone()
    assert hits[0] == 1

    history.put_session_results("full", "algo-1", {"r1": ("t1", {"x": 1}), "r2": ("t2", {"x": 2})})
    assert history.session_results("full", "algo-1", {"r1": "t1", "r2": "changed"}) == {
        "r1": {"x": 1}
    }
    assert history.session_results("other", "algo-1", {"r1": "t1"}) == {}
    # A new algorithm version replaces the root's old rows.
    history.put_session_results("full", "algo-2", {"r1": ("t1", {"x": 10})})
    assert history.session_results("full", "algo-1", {"r1": "t1"}) == {}
    assert history.session_results("full", "algo-2", {"r1": "t1"}) == {"r1": {"x": 10}}


@pytest.mark.parametrize(
    ("table", "reader"),
    [
        ("analysis_section", lambda h: h.sections("rk", "fp", ["overview"])),
        ("analysis_row", lambda h: h.section_rows("rk", "fp", "sessions")),
        ("session_result", lambda h: h.session_results("full", "a", {"r": "t"})),
    ],
)
def test_tampered_payloads_raise_checksum_errors(tmp_path, table, reader):
    import zlib

    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    history.put_sections(
        "rk", "fp", {"overview": {"v": 1}, "sessions": {}}, {"sessions": [("s", {"v": 1})]}
    )
    history.put_session_results("full", "a", {"r": ("t", {"v": 1})})
    with history.connect() as db:
        # Same length, different content: only the checksum can catch it.
        db.execute(f"UPDATE {table} SET payload=?", (zlib.compress(b'{"v":2}'),))
    with pytest.raises(ValueError, match="checksum"):
        reader(history)
    with history.connect() as db:
        db.execute(f"UPDATE {table} SET payload=?", (b"not zlib",))
    with pytest.raises(ValueError, match="corrupt"):
        reader(history)


def test_exclusions_persist_and_can_be_removed(tmp_path):
    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    first = history.exclude("s1", "噪声")
    again = history.exclude("s1", "重复")
    assert again["created_at"] == first["created_at"] and again["reason"] == "重复"
    history.exclude("s0")
    assert [e["session_uid"] for e in AnalysisHistory(history.path).exclusions()] == ["s0", "s1"]
    assert history.include("s1") is True and history.include("s1") is False
    assert [e["session_uid"] for e in history.exclusions()] == ["s0"]


def test_prune_keeps_three_inputs_per_request_and_old_failures(tmp_path):
    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    for index in range(5):
        history.put_sections("rk", f"fp{index}", {"overview": {"i": index}})
        with history.connect() as db:
            db.execute(
                "UPDATE analysis_section SET created_at=?,last_hit_at=? WHERE input_fp=?",
                (index, index, f"fp{index}"),
            )
    history.put_sections("other", "fp0", {"overview": {}})
    # Using an old input makes it recent again.
    history.sections("rk", "fp0", ["overview"])
    old = history.start("features", {})
    history.fail(old, ValueError("old"))
    recent = history.start("features", {})
    history.fail(recent, ValueError("recent"))
    day = 24 * 3600 * 1000
    with history.connect() as db:
        db.execute("UPDATE analysis_run SET finished_at=? WHERE run_id=?", (0, old))
    history.put_session_results("full", "algo-old", {"r": ("t", {})})
    history.put_session_results("full", "algo-new", {"q": ("t", {})})
    stats = history.prune(algo_version="algo-new", now=31 * day + 1)
    assert stats["stale_inputs"] == 2 and stats["failed_runs"] == 1
    assert stats["old_session_results"] == 1
    with history.connect() as db:
        kept = {
            r[0] for r in db.execute("SELECT input_fp FROM analysis_section WHERE request_key='rk'")
        }
        runs = {r[0] for r in db.execute("SELECT run_id FROM analysis_run")}
    assert kept == {"fp0", "fp3", "fp4"}
    assert history.sections("other", "fp0", ["overview"]) == {"overview": {}}
    assert runs == {recent}
    assert history.session_results("full", "algo-new", {"q": "t"}) == {"q": {}}


def test_prune_evicts_least_recently_hit_sections_over_the_size_limit(tmp_path):
    import os

    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    blob = os.urandom(200_000).hex()  # incompressible, ~400 KB of JSON per section
    for index in range(4):
        history.put_sections(
            f"rk{index}", "fp", {"text": {"blob": blob}}, {"text": [("k", {"b": blob})]}
        )
        with history.connect() as db:
            db.execute(
                "UPDATE analysis_section SET last_hit_at=? WHERE request_key=?",
                (index, f"rk{index}"),
            )
    history.sections("rk0", "fp", ["text"])  # rk0 is now the most recently used
    before = history.stored_bytes()
    stats = history.prune(max_bytes=before // 2)
    assert stats["evicted"] >= 2 and history.stored_bytes() <= before // 2
    with history.connect() as db:
        left = {r[0] for r in db.execute("SELECT request_key FROM analysis_section")}
        orphan_rows = db.execute(
            "SELECT count(*) FROM analysis_row r LEFT JOIN analysis_section s"
            " USING(request_key,input_fp,section) WHERE s.section IS NULL"
        ).fetchone()[0]
    assert "rk0" in left and "rk1" not in left and orphan_rows == 0

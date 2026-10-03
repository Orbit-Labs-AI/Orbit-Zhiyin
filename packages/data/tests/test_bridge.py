"""bridge.import_connector failure paths: every staging inconsistency is refused loudly."""

import hashlib
import sqlite3

import pytest
import zstandard

from tandem_data.bridge import import_connector
from tandem_data.contract import canonical
from tandem_data.store import Store

SCHEMA = (
    "CREATE TABLE source(source_id TEXT,agent TEXT,root_path TEXT,label TEXT);"
    "CREATE TABLE source_file(file_id TEXT,source_id TEXT,path TEXT,role TEXT,format TEXT,"
    "status TEXT);"
    "CREATE TABLE archive_chunk(file_id TEXT,generation INTEGER,offset INTEGER,byte_len INTEGER,"
    "sha256 TEXT,path TEXT);"
    "CREATE TABLE raw_record(record_uid TEXT,file_id TEXT,generation INTEGER,line_no INTEGER,"
    "sha256 TEXT);"
)


def line(name):
    return (canonical({"type": "session_meta", "payload": {"id": name}}) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_chunk(directory, data):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (sha(data) + ".zst")
    path.write_bytes(zstandard.ZstdCompressor().compress(data))
    return path


def staging(tmp_path, chunks, records, *, status="active", drop=None):
    """chunks: (generation, offset, byte_len, sha256, path); records: (uid, gen, line, sha)."""
    home = tmp_path / "staging"
    (home / "raw").mkdir(parents=True, exist_ok=True)
    root = tmp_path / "source"
    with sqlite3.connect(home / "tandem.db") as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO source VALUES('src','codex',?,NULL)", (str(root),))
        db.execute(
            "INSERT INTO source_file VALUES('f','src',?,'transcript','jsonl',?)",
            (str(root / "rollout.jsonl"), status),
        )
        db.executemany(
            "INSERT INTO archive_chunk VALUES('f',?,?,?,?,?)",
            [(g, o, n, h, str(p)) for g, o, n, h, p in chunks],
        )
        db.executemany("INSERT INTO raw_record VALUES(?,'f',?,?,?)", records)
        if drop:
            db.execute(f"DROP TABLE {drop}")
    return home


def one_chunk(tmp_path, data=None, **overrides):
    data = data or line("a")
    path = write_chunk(tmp_path / "staging" / "raw", data)
    chunk = {"offset": 0, "byte_len": len(data), "sha256": sha(data), "path": path, **overrides}
    return (0, chunk["offset"], chunk["byte_len"], chunk["sha256"], chunk["path"]), data


def run(tmp_path, home):
    with Store(tmp_path / "data") as store:
        return import_connector(store, home)


def test_chunk_gap_is_refused(tmp_path):
    a, b = line("a"), line("b")
    pa, pb = write_chunk(tmp_path / "staging/raw", a), write_chunk(tmp_path / "staging/raw", b)
    # The second chunk starts 5 bytes after the first ends.
    home = staging(
        tmp_path,
        [(0, 0, len(a), sha(a), pa), (0, len(a) + 5, len(b), sha(b), pb)],
        [("r1", 0, 1, sha(a))],
    )
    with pytest.raises(ValueError, match="Connector archive contains a gap"):
        run(tmp_path, home)


@pytest.mark.parametrize("field", ["sha256", "byte_len"])
def test_chunk_checksum_or_length_mismatch_is_refused(tmp_path, field):
    bad = {"sha256": "0" * 64} if field == "sha256" else {"byte_len": 1}
    chunk, data = one_chunk(tmp_path, **bad)
    home = staging(tmp_path, [chunk], [("r1", 0, 1, sha(data))])
    with pytest.raises(ValueError, match="Connector chunk checksum mismatch"):
        run(tmp_path, home)


@pytest.mark.parametrize("where", ["absolute_outside", "relative_dotdot"])
def test_chunk_path_outside_raw_is_refused(tmp_path, where):
    data = line("a")
    outside = write_chunk(tmp_path / "elsewhere", data)
    path = outside if where == "absolute_outside" else "raw/../../elsewhere/" + outside.name
    home = staging(tmp_path, [(0, 0, len(data), sha(data), path)], [("r1", 0, 1, sha(data))])
    with pytest.raises(ValueError, match="escapes its raw directory"):
        run(tmp_path, home)


def test_record_crosswalk_mismatch_is_refused(tmp_path):
    chunk, _ = one_chunk(tmp_path)
    home = staging(tmp_path, [chunk], [("r1", 0, 1, "f" * 64)])
    with pytest.raises(ValueError, match="crosswalk checksum mismatch"):
        run(tmp_path, home)


def test_missing_staging_table_is_refused(tmp_path):
    chunk, data = one_chunk(tmp_path)
    home = staging(tmp_path, [chunk], [("r1", 0, 1, sha(data))], drop="archive_chunk")
    with pytest.raises(ValueError, match="Unsupported connector staging schema"):
        run(tmp_path, home)


def test_generations_import_as_revisions_and_negative_ones_are_skipped(tmp_path):
    a, b = line("a"), line("b")
    rotated = a + b  # generation 1 is the rewritten file: both lines
    raw = tmp_path / "staging" / "raw"
    p0, p1, pending = write_chunk(raw, a), write_chunk(raw, rotated), write_chunk(raw, b)
    home = staging(
        tmp_path,
        [
            (0, 0, len(a), sha(a), p0),
            (1, 0, len(rotated), sha(rotated), p1),
            (-1, 0, len(b), sha(b), pending),  # not yet sealed: never imported
        ],
        [
            ("g0-1", 0, 1, sha(a)),
            ("g1-1", 1, 1, sha(a)),
            ("g1-2", 1, 2, sha(b)),
        ],
    )
    with Store(tmp_path / "data") as store:
        assert import_connector(store, home) == {"imported_revisions": 2, "unchanged_manifests": 0}
        assert import_connector(store, home) == {"imported_revisions": 0, "unchanged_manifests": 2}
        revisions = store.db.execute("SELECT revision FROM source_revision ORDER BY 1").fetchall()
        assert [r[0] for r in revisions] == [1, 2]
        links = dict(
            store.db.execute("SELECT external_record_uid,record_uid FROM connector_record_link")
        )
        assert set(links) == {"g0-1", "g1-1", "g1-2"}
        assert store.read_raw(links["g1-2"]) == b
        assert store.read_raw(links["g0-1"]) == a


@pytest.mark.parametrize("status", ["gone_upstream", "error"])
def test_upstream_file_status_is_written_back(tmp_path, status):
    chunk, data = one_chunk(tmp_path)
    home = staging(tmp_path, [chunk], [("r1", 0, 1, sha(data))], status=status)
    with Store(tmp_path / "data") as store:
        import_connector(store, home)
        assert store.db.execute("SELECT status FROM source_file").fetchone()[0] == status


def test_staging_home_must_differ_from_canonical_home(tmp_path):
    with Store(tmp_path / "data") as store:
        with pytest.raises(ValueError, match="must differ"):
            import_connector(store, tmp_path / "data")

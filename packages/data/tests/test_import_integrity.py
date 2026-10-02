"""Import integrity regression over the deterministic synthetic tree (small preset only).

Nothing here reads a real agent directory: sources, data homes and HOME are all tmp paths.
"""

import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

from tandem_data.inventory import InventoryRequest, scan_inventory
from tandem_data.query import event_page
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store, readonly_connection
from tandem_data.validation.integrity import invariants, logical_digest, section_digests

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from benchmarks.data.synthetic import generate  # noqa: E402


def _import(out: Path, manifest: dict, home: Path) -> Path:
    with Store(home) as store:
        service = ImportService(store)
        for agent, relative in sorted(manifest["sources"].items()):
            result = service.import_source(ImportRequest(agent, out / relative))
            assert result["capture_errors"] == 0
        inventory = manifest["inventory"]
        scan_inventory(store, InventoryRequest(inventory["agent"], out / inventory["root"]))
    return home


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        base = tmp_path_factory.mktemp("integrity")
        patch.setenv("HOME", str(base / "home"))
        out = base / "synthetic"
        manifest = generate(out, "small")
        homes = [_import(out, manifest, base / f"data-{i}") for i in range(2)]
        yield out, manifest, homes


def _copy(home: Path, target: Path) -> Path:
    target.mkdir()
    with (
        sqlite3.connect(home / "tandem.db") as source,
        sqlite3.connect(target / "tandem.db") as copy,
    ):
        source.backup(copy)
    return target


def _write(home: Path, sql: str, params=()) -> int:
    db = sqlite3.connect(home / "tandem.db")
    try:
        changed = db.execute(sql, params).rowcount
        db.commit()
    finally:
        db.close()
    return changed


def test_generator_is_byte_deterministic(tmp_path):
    first = generate(tmp_path / "a", "small")
    second = generate(tmp_path / "b", "small")
    assert first == second

    def files(root):
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    left, right = files(tmp_path / "a"), files(tmp_path / "b")
    assert left.keys() == right.keys() and left == right
    assert any(name.endswith("opencode.db") for name in left)


def test_independent_imports_have_identical_logical_digest(synthetic):
    _, _, (first, second) = synthetic
    assert section_digests(first) == section_digests(second)
    assert logical_digest(first) == logical_digest(second)


def test_invariants_hold(synthetic):
    _, manifest, (home, _) = synthetic
    result = invariants(home)
    assert result["problems"] == []
    assert result["verify"]["integrity"] == "ok"
    assert result["verify"]["records"] == manifest["totals"]["records"]
    assert result["foreign_key_violations"] == 0
    assert result["ledger_inconsistent"] == 0
    assert result["current_unparsed"] == 0
    assert result["events"] == manifest["totals"]["events"]
    with readonly_connection(home / "tandem.db") as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_counts_match_manifest(synthetic):
    _, manifest, (home, _) = synthetic
    with readonly_connection(home / "tandem.db") as db:
        sessions = dict(
            db.execute(
                "SELECT s.agent,COUNT(*) FROM session x JOIN source s USING(source_id) GROUP BY 1"
            ).fetchall()
        )
        events = dict(
            db.execute(
                "SELECT s.agent,COUNT(*) FROM event e JOIN session_identity i USING(session_uid) "
                "JOIN source s USING(source_id) GROUP BY 1"
            ).fetchall()
        )
        records = dict(
            db.execute(
                "SELECT s.agent,COUNT(*) FROM raw_record r JOIN source_file f USING(file_id) "
                "JOIN source s USING(source_id) GROUP BY 1"
            ).fetchall()
        )
        files = dict(
            db.execute(
                "SELECT s.agent,COUNT(*) FROM source_file JOIN source s USING(source_id) GROUP BY 1"
            ).fetchall()
        )
    expected = manifest["agents"]
    assert set(expected) >= {"claude_code", "pi", "dsh", "opencode"}
    assert sessions == {agent: value["sessions"] for agent, value in expected.items()}
    assert events == {agent: value["events"] for agent, value in expected.items()}
    assert records == {agent: value["records"] for agent, value in expected.items()}
    assert files == {agent: value["files"] for agent, value in expected.items()}


def test_large_outputs_round_trip_through_event_page(synthetic):
    _, manifest, (home, _) = synthetic
    large = manifest["large_outputs"]
    assert {item["agent"] for item in large} >= {"claude_code", "pi", "dsh", "opencode"}
    with readonly_connection(home / "tandem.db") as db:
        uids = {
            (row[0], row[1]): row[2]
            for row in db.execute(
                "SELECT s.agent,x.native_id,x.session_uid FROM session x JOIN source s USING(source_id)"
            )
        }
    for item in large:
        assert item["bytes"] >= manifest["large_output_min_bytes"]
        session_uid = uids[(item["agent"], item["session"])]
        digests = {
            hashlib.sha256(event["text"].encode()).hexdigest()
            for event in event_page(home, session_uid, limit=1000)
            if event["text"]
        }
        assert item["sha256"] in digests, item


def test_inventory_matches_manifest(synthetic):
    _, manifest, (home, _) = synthetic
    with readonly_connection(home / "tandem.db") as db:
        rows = db.execute(
            "SELECT s.agent,i.type,i.name,i.locator,i.content_hash FROM inventory_item i "
            "JOIN inventory_scan s USING(scan_id) ORDER BY 2,3,4,5"
        ).fetchall()
    expected = manifest["inventory"]
    assert {row[0] for row in rows} == {expected["agent"]}
    actual = [{"type": r[1], "name": r[2], "locator": r[3], "content_hash": r[4]} for r in rows]

    def key(item):
        return (item["type"], item["name"], item["locator"], item["content_hash"])

    assert sorted(actual, key=key) == sorted(expected["items"], key=key)
    assert {item["type"] for item in expected["items"]} == {
        "skill",
        "mcp",
        "hook",
        "plugin",
        "rule",
    }


@pytest.mark.parametrize(
    "mutation",
    ["event_text_byte", "delete_record_event", "inventory_item"],
)
def test_digest_detects_logical_changes(synthetic, tmp_path, mutation):
    _, _, (home, _) = synthetic
    baseline = logical_digest(home)
    copy = _copy(home, tmp_path / "copy")
    assert logical_digest(copy) == baseline
    if mutation == "event_text_byte":
        with readonly_connection(copy / "tandem.db") as db:
            uid, text = db.execute(
                "SELECT event_uid,text FROM event WHERE text GLOB '[a-z]*' ORDER BY event_uid LIMIT 1"
            ).fetchone()
        changed = ("A" if text[0] != "A" else "B") + text[1:]
        assert len(changed.encode()) == len(text.encode())
        assert _write(copy, "UPDATE event SET text=? WHERE event_uid=?", (changed, uid)) == 1
        section = "event"
    elif mutation == "delete_record_event":
        assert (
            _write(
                copy,
                "DELETE FROM record_event WHERE rowid=(SELECT rowid FROM record_event "
                "ORDER BY record_uid,event_uid LIMIT 1)",
            )
            == 1
        )
        section = "record_event"
    else:
        assert (
            _write(
                copy,
                "UPDATE inventory_item SET content_hash=? WHERE rowid=(SELECT MIN(rowid) FROM inventory_item)",
                ("0" * 64,),
            )
            == 1
        )
        section = "inventory"
    assert logical_digest(copy) != baseline
    changed_sections = {
        name
        for name, value in section_digests(copy).items()
        if value != section_digests(home)[name]
    }
    assert changed_sections == {section}


def test_digest_ignores_physical_representation(synthetic, tmp_path):
    _, _, (home, _) = synthetic
    baseline = logical_digest(home)
    copy = _copy(home, tmp_path / "copy")
    db = sqlite3.connect(copy / "tandem.db")
    try:
        # Rewrite pages and every index; rowids of non-INTEGER-PRIMARY-KEY tables may move.
        db.execute("REINDEX")
        db.execute("VACUUM")
        db.execute("ANALYZE")
    finally:
        db.close()
    assert logical_digest(copy) == baseline

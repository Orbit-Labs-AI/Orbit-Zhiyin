import fcntl
import os

import pytest

from orbit_data.contract import canonical
from orbit_data.maintenance import (
    LAYERS,
    PURGE_CONFIRMATION,
    PurgeRefused,
    layer_of,
    purge_all,
    storage_usage,
)
from orbit_data.service import ImportRequest, ImportService
from orbit_data.store import Store
from orbit_data.validation.fixtures import create_sources


def build(tmp_path):
    roots = create_sources(tmp_path / "fixtures")
    home = tmp_path / "home"
    with Store(home) as store:
        service = ImportService(store)
        for agent, root in roots.items():
            service.import_source(ImportRequest(agent, root))
        # A bridged stream is archived under raw/, so every layer is non-empty.
        source = store.add_source("pi", tmp_path / "stream")
        rows = [
            {"type": "session", "id": "s"},
            {"type": "message", "id": "u", "message": {"role": "user", "content": "hello"}},
        ]
        store.capture_stream(source, "s.jsonl", [(canonical(r) + "\n").encode() for r in rows])
        store.rebuild()
    (home / "catalog.db").write_bytes(b"keep")
    return home


def snapshot(path):
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


def test_layer_mapping():
    assert layer_of("raw_record") == "l1"
    assert layer_of("event") == "l2"
    assert layer_of("tool_call") == "l3"
    assert layer_of("event_fts_data") == "fts" and layer_of("event_search_idx") == "fts"
    assert layer_of("inventory_item") == "inventory"
    assert layer_of("schema_manifest") == "other"


def test_storage_usage_layers_add_up(tmp_path):
    home = build(tmp_path)
    usage = storage_usage(home)
    layers = usage["layers"]
    assert set(layers) == set(LAYERS)
    for layer in ("raw", "l1", "l2", "l3", "fts"):
        assert layers[layer] > 0, layer
    database = usage["database"]
    in_db = sum(layers[name] for name in ("l1", "l2", "l3", "fts", "inventory", "other"))
    assert in_db == database["dbstat_bytes"]
    pages = database["page_size"] * database["page_count"]
    assert abs(in_db + layers["free"] - pages) <= 0.01 * pages
    walked = sum(p.stat().st_size for p in (home / "raw").rglob("*") if p.is_file())
    assert layers["raw"] == walked == usage["raw"]["bytes"]
    assert usage["total_bytes"] == sum(layers.values())
    assert sum(usage["tables"].values()) == database["dbstat_bytes"]


def test_storage_usage_of_empty_home(tmp_path):
    usage = storage_usage(tmp_path / "missing")
    assert usage["total_bytes"] == 0


@pytest.mark.parametrize("confirm", ["", "delete all local data", "yes"])
def test_wrong_confirmation_deletes_nothing(tmp_path, confirm):
    home = build(tmp_path)
    before = snapshot(home)
    with pytest.raises(PurgeRefused):
        purge_all(home, confirm)
    assert snapshot(home) == before


def test_symlink_escape_in_raw_is_refused(tmp_path):
    home = build(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("outside")
    (home / "raw" / "escape").symlink_to(victim)
    before = snapshot(home)
    with pytest.raises(PurgeRefused, match="symbolic link"):
        purge_all(home, PURGE_CONFIRMATION)
    assert snapshot(home) == before and victim.read_text() == "outside"


def test_symlinked_cache_dir_and_home_are_refused(tmp_path):
    home = build(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "capabilities.json").write_text("{}")
    (home / "cache").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PurgeRefused, match="outside"):
        purge_all(home, PURGE_CONFIRMATION)
    assert (outside / "capabilities.json").exists() and (home / "orbit.db").exists()
    link = tmp_path / "link-home"
    link.symlink_to(home, target_is_directory=True)
    with pytest.raises(PurgeRefused, match="symbolic link"):
        purge_all(link, PURGE_CONFIRMATION)
    assert (home / "orbit.db").exists()


def test_non_orbit_directory_is_refused(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "notes.txt").write_text("x")
    with pytest.raises(PurgeRefused, match="not a Orbit"):
        purge_all(folder, PURGE_CONFIRMATION)
    assert (folder / "notes.txt").exists()


def test_active_import_blocks_purge(tmp_path):
    home = build(tmp_path)
    descriptor = os.open(home / "import.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        with pytest.raises(RuntimeError, match="import"):
            purge_all(home, PURGE_CONFIRMATION)
    finally:
        os.close(descriptor)
    assert (home / "orbit.db").exists()


def test_confirmed_purge_clears_data_and_store_reinitialises(tmp_path):
    home = build(tmp_path)
    from orbit_data.capabilities import capabilities

    capabilities(home)
    result = purge_all(home, PURGE_CONFIRMATION)
    assert result["deleted_files"] > 2 and result["deleted_bytes"] > 0
    assert not (home / "orbit.db").exists() and not (home / "raw").exists()
    assert not (home / "cache" / "capabilities.json").exists()
    assert (home / "catalog.db").read_bytes() == b"keep"
    assert "orbit.db" not in result["kept"]
    with Store(home) as store:
        assert store.db.execute("SELECT COUNT(*) FROM event").fetchone()[0] == 0
        assert store.verify()["unparsed"] == 0
        assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert storage_usage(home)["layers"]["raw"] == 0


def test_cli_data_service_commands(tmp_path, capsys):
    import json

    from orbit_data.cli import main

    home = build(tmp_path)

    def run(*args):
        main(["--home", str(home), *args])
        return json.loads(capsys.readouterr().out)

    found = run("search", "git status")
    assert found["total"] >= 6
    session = found["hits"][0]["session_uid"]
    assert run("resume", "--session", session)["session_uid"] == session
    assert run("capabilities")["sources"]
    assert run("storage")["layers"]["l2"] > 0
    assert run("privacy-rules")["count"] == 11
    preview = run("privacy-preview", "--text", "Bearer abcdefghijklmnop")
    assert "<redacted:token>" in preview["redacted"]
    usage = tmp_path / "usage-data" / "session-meta"
    usage.mkdir(parents=True)
    (usage / "demo.json").write_text('{"session_id": "demo", "tool_counts": {"Bash": 1}}')
    report = run("insights", "--path", str(usage.parent), "--match")
    assert report["matches"][0]["orbit"]["tool_calls"] == 1
    with pytest.raises(PurgeRefused):
        main(["--home", str(home), "purge", "--confirm", "no"])
    assert (home / "orbit.db").exists()
    assert run("purge", "--confirm", PURGE_CONFIRMATION)["deleted_files"] > 0
    assert not (home / "orbit.db").exists()

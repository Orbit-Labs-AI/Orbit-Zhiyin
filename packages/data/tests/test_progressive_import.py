"""Progressive first import, consistent reader snapshots, and paused collection."""

import os
import threading
import time

from _integrity import assert_integrity, build_relation_tree, differing_tables, mutate

from tandem_data.query import event_page
from tandem_data.scheduler import collection_state, plan_batches, session_group
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store, readonly_connection


def _age(roots):
    """Distinct mtimes: higher session numbers are newer; a few are older than 7 days."""
    now = time.time()
    files = sorted(p for root in roots.values() for p in root.rglob("*") if p.is_file())
    for index, path in enumerate(files):
        age = (len(files) - index) * 60 + (10 * 86_400 if index < 6 else 0)
        os.utime(path, (now - age, now - age))


def _full(tmp_path, roots, name="full"):
    with Store(tmp_path / name) as store:
        service = ImportService(store, workers=4)
        for agent, root in sorted(roots.items()):
            service.import_source(ImportRequest(agent, root))
        service.close()
        assert_integrity(store)
    return tmp_path / name


def test_progressive_import_publishes_consistent_batches(tmp_path):
    roots = build_relation_tree(tmp_path / "tree", sessions=24)
    _age(roots)
    home = tmp_path / "progressive"
    published = threading.Event()
    stop = threading.Event()
    errors, reads = [], []

    def reader():
        published.wait(60)
        while not stop.is_set():
            try:
                with readonly_connection(home / "tandem.db") as probe:
                    session = probe.execute(
                        "SELECT session_uid FROM session ORDER BY session_uid LIMIT 1"
                    ).fetchone()[0]
                reads.append(len(event_page(home, session, limit=10)))
            except ValueError as error:  # pending / obsolete projection
                errors.append(str(error))
            time.sleep(0.1)

    thread = threading.Thread(target=reader)
    thread.start()
    batches = []
    try:
        with Store(home) as store:
            service = ImportService(store, workers=4)
            service.pool.threshold = 0

            def on_batch(event):
                batches.append(event)
                published.set()
                time.sleep(0.25)  # Let the reader observe intermediate snapshots.

            summary = service.import_progressive(
                [ImportRequest(agent, root) for agent, root in sorted(roots.items())],
                first_sessions=8,
                on_batch=on_batch,
            )
            service.close()
            assert summary["complete"] and summary["batches"] == len(batches) >= 3
            scans = {row[0] for row in store.db.execute("SELECT selection FROM source_scan")}
            assert scans == {"full"}
            assert_integrity(store)
    finally:
        stop.set()
        published.set()
        thread.join()
    assert errors == []
    assert len(reads) >= 3
    assert differing_tables(_full(tmp_path, roots), home) == []


def test_first_batch_is_newest_sessions_and_groups_stay_together():
    entries = [
        {"group": ("s", "a"), "mtime": 100},
        {"group": ("s", "a"), "mtime": 1},
        {"group": ("s", "b"), "mtime": 90},
        {"group": ("s", "c"), "mtime": 80},
        {"group": ("s", "d"), "mtime": 10},
    ]
    batches = plan_batches(entries, first_sessions=2, first_days=7, now=100)
    assert [e["group"][1] for e in batches[0]] == ["a", "a", "b"]
    assert [[e["group"][1] for e in batch] for batch in batches[1:]] == [["c", "d"]]
    old = plan_batches(entries, first_sessions=9, first_days=0, now=10**9)
    assert [e["group"][1] for e in old[0]] == ["a", "a"]  # Nothing recent: newest group only.
    # The first batch is bounded by bytes (event volume), never empty; the rest is
    # one batch per source, in order of each source's newest remaining group.
    sized = [{**e, "size": 40} for e in entries] + [{"group": ("t", "e"), "mtime": 85, "size": 1}]
    budget = plan_batches(sized, first_sessions=9, first_days=7, first_bytes=100, now=100)
    assert [e["group"][1] for e in budget[0]] == ["a", "a"]
    assert [[e["group"] for e in batch] for batch in budget[1:]] == [
        [("s", "b"), ("s", "c"), ("s", "d")],
        [("t", "e")],
    ]
    tiny = plan_batches(sized, first_sessions=9, first_days=7, first_bytes=1, now=100)
    assert [e["group"][1] for e in tiny[0]] == ["a", "a"]
    assert session_group("claude_code", "projects/p/s1/subagents/agent-a.jsonl") == "projects/p/s1"
    assert session_group("claude_code", "projects/p/s1.jsonl") == "projects/p/s1"
    assert session_group("dsh", "sessions/p/s/session.v3.jsonl") == "sessions/p/s"


def test_paused_collection_creates_no_revision_and_resume_catches_up(tmp_path):
    import random
    import shutil

    roots = build_relation_tree(tmp_path / "tree", sessions=8)
    shutil.copytree(tmp_path / "tree", tmp_path / "snapshot")
    home = tmp_path / "data"
    with Store(home) as store:
        service = ImportService(store, workers=4)
        for agent, root in sorted(roots.items()):
            service.import_source(ImportRequest(agent, root))
        revisions = store.db.execute("SELECT COUNT(*) FROM source_revision").fetchone()[0]
        state = service.pause_collection()
        assert state["paused"] and collection_state(home)["paused"]
        rng = random.Random(3)
        for step in range(6):
            mutate(roots, rng, step)
        stop = threading.Event()
        for agent, root in sorted(roots.items()):
            assert next(service.watch(ImportRequest(agent, root), stop))["paused"]
        summary = service.import_progressive(
            [ImportRequest(agent, root) for agent, root in sorted(roots.items())]
        )
        assert summary["paused"] and summary["batches"] == 0
        assert store.db.execute("SELECT COUNT(*) FROM source_revision").fetchone()[0] == revisions
        state = service.resume_collection()
        assert not state["paused"] and state["resumed_at"] >= state["paused_at"]
        for agent, root in sorted(roots.items()):
            result = next(service.watch(ImportRequest(agent, root), stop))
            assert not result.get("paused")
        service.close()
        assert_integrity(store)
    # Uninterrupted: same tree path and edits, collected without a pause.
    shutil.rmtree(tmp_path / "tree")
    shutil.copytree(tmp_path / "snapshot", tmp_path / "tree")
    with Store(tmp_path / "uninterrupted") as store:
        service = ImportService(store, workers=4)
        for agent, root in sorted(roots.items()):
            service.import_source(ImportRequest(agent, root))
        rng = random.Random(3)
        for step in range(6):
            mutate(roots, rng, step)
        for agent, root in sorted(roots.items()):
            service.import_source(ImportRequest(agent, root))
        service.close()
        assert_integrity(store)
    assert differing_tables(home, tmp_path / "uninterrupted") == []

"""Closure increments must equal a full in-place rebuild after arbitrary source edits."""

import random
from collections import Counter

from _integrity import (
    assert_integrity,
    build_relation_tree,
    copy_home,
    differing_tables,
    logical_digest,
    mutate,
)

from tandem_data.pipeline import rebuild
from tandem_data.scheduler import closure, stale_files
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store


def _scan(service, roots):
    kinds = Counter()
    for agent, root in sorted(roots.items()):
        result = service.import_source(ImportRequest(agent, root))
        assert result["capture_errors"] == 0
        if "projection" in result:
            kinds[result["projection"]["scope"]["kind"]] += 1
    return kinds


def test_random_edits_match_full_rebuild(tmp_path):
    roots = build_relation_tree(tmp_path / "tree", sessions=12)
    rng = random.Random(20261002)
    kinds, actions = Counter(), Counter()
    with Store(tmp_path / "data") as store:
        service = ImportService(store, workers=4)
        try:
            _scan(service, roots)
            for step in range(24):
                description = mutate(roots, rng, step)
                actions[description.split(":")[0]] += 1
                kinds.update(_scan(service, roots))
                assert_integrity(store)
                reference = copy_home(store, tmp_path / f"reference-{step}")
                with Store(reference) as full:
                    rebuild(full)  # The original serial path over every source.
                    assert_integrity(full)
                assert differing_tables(store.home, reference) == [], description
                assert logical_digest(store.home) == logical_digest(reference)
        finally:
            service.close()
    assert kinds["closure"] >= 5, kinds
    assert {"append", "rewrite", "delete", "new"} <= set(actions), actions


def test_unchanged_rescan_publishes_nothing(tmp_path):
    roots = build_relation_tree(tmp_path / "tree", sessions=8)
    with Store(tmp_path / "data") as store:
        service = ImportService(store, workers=4)
        _scan(service, roots)
        runs = store.db.execute("SELECT COUNT(*) FROM projection_run").fetchone()[0]
        revisions = store.db.execute("SELECT COUNT(*) FROM source_revision").fetchone()[0]
        assert _scan(service, roots) == Counter()
        assert store.db.execute("SELECT COUNT(*) FROM projection_run").fetchone()[0] == runs
        assert store.db.execute("SELECT COUNT(*) FROM source_revision").fetchone()[0] == revisions
        service.close()


def test_closure_follows_resume_copies_and_lineage(tmp_path):
    roots = build_relation_tree(tmp_path / "tree", sessions=12)
    with Store(tmp_path / "data") as store:
        service = ImportService(store, workers=4)
        _scan(service, roots)
        service.close()
        # The resumed copy of cc001 shares replayed events with its origin.
        resumed = next(roots["claude_code"].rglob("cc001r.jsonl"))
        with resumed.open("a") as handle:
            handle.write(
                '{"type":"user","uuid":"late","sessionId":"cc001r","message":{"content":"x"}}\n'
            )
        source_id = store.db.execute(
            "SELECT source_id FROM source WHERE agent='claude_code'"
        ).fetchone()[0]
        service = ImportService(store, workers=1)
        from tandem_data.parallel import WorkerPool, capture

        counts = {"files": 0, "changed": 0, "capture_errors": 0, "cancelled": False}
        files = [
            item
            for item in __import__("tandem_data.discovery").discovery.inputs(
                "claude_code", roots["claude_code"].resolve()
            )
        ]
        with WorkerPool(1) as pool:
            capture(
                store,
                source_id,
                roots["claude_code"].resolve(),
                files,
                pool,
                None,
                lambda _: None,
                counts,
                "claude_code",
            )
        stale = stale_files(store.db)[source_id]
        scope = closure(store, source_id, stale)
        assert scope is not None
        paths = {
            row[0]
            for row in store.db.execute(
                f"SELECT relative_path FROM source_file WHERE file_id IN ({','.join('?' * len(scope.files))})",
                sorted(scope.files),
            )
        }
        assert any(p.endswith("cc001.jsonl") for p in paths), paths
        assert any(p.endswith("cc001r.jsonl") for p in paths), paths
        assert len(paths) < 6

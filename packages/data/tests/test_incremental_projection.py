"""Closure increments must equal a full in-place rebuild after arbitrary source edits."""

import random
from collections import Counter

import pytest
from _integrity import (
    assert_integrity,
    build_relation_tree,
    copy_home,
    differing_tables,
    logical_digest,
    mutate,
)

from tandem_data import parallel
from tandem_data.pipeline import rebuild
from tandem_data.scheduler import closure, stale_files
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store


def _scan(service, roots):
    kinds = Counter()
    for agent, root in sorted(roots.items()):
        result = service.import_source(ImportRequest(agent, root))
        assert result["capture_errors"] == 0
        # The memoised count must equal a fresh count after every kind of edit.
        assert (
            result["current_unparsed"]
            == service.store.db.execute(
                "SELECT COUNT(*) FROM raw_record r JOIN file_record c USING(record_uid) "
                "JOIN source_file f ON f.file_id=r.file_id WHERE f.source_id=? "
                "AND r.disposition='unparsed'",
                (result["source_id"],),
            ).fetchone()[0]
        )
        if "projection" in result:
            kinds[result["projection"]["scope"]["kind"]] += 1
    return kinds


@pytest.mark.parametrize("defer_search_index", [False, True])
def test_random_edits_match_full_rebuild(tmp_path, monkeypatch, defer_search_index):
    if defer_search_index:
        # Exercise the bulk search-index path even for these small rebuilds.
        monkeypatch.setattr(parallel, "DEFER_SEARCH_INDEX_FILES", 0)
        finish = parallel.DeferredSearchIndex.finish
        finished = []
        monkeypatch.setattr(
            parallel.DeferredSearchIndex,
            "finish",
            lambda self: finished.append(1) or finish(self),
        )
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
    if defer_search_index:
        assert len(finished) >= 24  # Each changed rescan used the bulk search index.


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


def test_orphan_subagent_keeps_session_closures(tmp_path):
    """An unresolved lineage is a per-session finding: it must not disable closures.

    v0.0.2 wrote ``unresolved_session_lineage`` without a file or record, which
    ``closure()`` reads as a source-wide finding; one orphan (a Claude Code workflow
    ``journal.jsonl`` or a subagent whose parent was cleaned up) made every later change
    to ``~/.claude`` a whole-source rebuild (docs/development/import-pipeline.md, RC-2).
    """
    import json as _json

    def turn(session, uuid, text):
        return (
            _json.dumps(
                {"type": "user", "sessionId": session, "uuid": uuid, "message": {"content": text}}
            )
            + "\n"
        )

    root = tmp_path / "claude"
    for n in range(10):
        path = root / f"projects/p/s{n}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(turn(f"s{n}", f"u{n}", f"session {n}"))
    orphan = root / "projects/p/gone/subagents/agent-x.jsonl"
    orphan.parent.mkdir(parents=True)
    orphan.write_text(turn("gone", "child", "orphaned child"))
    with Store(tmp_path / "data") as store:
        service = ImportService(store, workers=4)
        service.import_source(ImportRequest("claude_code", root))
        issue = store.db.execute(
            "SELECT file_id,record_uid FROM ingest_issue WHERE code='unresolved_session_lineage'"
        ).fetchone()
        assert issue is not None and issue["record_uid"] is not None
        with (root / "projects/p/s3.jsonl").open("a") as handle:
            handle.write(turn("s3", "u3b", "appended"))
        result = service.import_source(ImportRequest("claude_code", root))
        service.close()
        assert result["projection"]["scope"]["kind"] == "closure"
        issues = sorted(
            tuple(row)
            for row in store.db.execute(
                "SELECT code,file_id,record_uid,detail FROM ingest_issue WHERE stage='l3'"
            )
        )
        reference = copy_home(store, tmp_path / "reference")
    with Store(reference) as full:
        rebuild(full)
        assert issues == sorted(
            tuple(row)
            for row in full.db.execute(
                "SELECT code,file_id,record_uid,detail FROM ingest_issue WHERE stage='l3'"
            )
        )
    assert differing_tables(tmp_path / "data", reference) == []


@pytest.mark.parametrize("sidecar", ["title", "journal"])
def test_new_file_of_a_session_outside_the_closure_escalates(tmp_path, sidecar):
    """A new file whose records belong to an existing session outside the closure.

    A brand-new file has no mapped records yet, so ``closure()`` cannot know its sessions:
    a session title sidecar written later for an existing session, or one more Claude
    Code workflow ``journal.jsonl`` (all of them map into one session). Its events used to
    be inserted with the closure's fresh sequence numbers and failed the import with
    ``UNIQUE constraint failed: event.session_uid, event.seq`` on every later scan; now
    the rebuild escalates to include that session, and the result equals a full rebuild.
    """
    import json as _json

    def turn(session, uuid, text):
        return (
            _json.dumps(
                {"type": "user", "sessionId": session, "uuid": uuid, "message": {"content": text}}
            )
            + "\n"
        )

    root = tmp_path / "claude"
    for n in range(10):
        path = root / f"projects/p/s{n}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(turn(f"s{n}", f"u{n}", f"session {n}"))
    journal = root / "projects/p/s0/subagents/workflows/wf_a/journal.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text(_json.dumps({"type": "launched", "agentId": "a1"}) + "\n")
    with Store(tmp_path / "data") as store:
        service = ImportService(store, workers=4)
        service.import_source(ImportRequest("claude_code", root))
        if sidecar == "title":
            added = root / "projects/p/s3/custom-title.json"
            added.parent.mkdir(parents=True)
            added.write_text(_json.dumps({"sessionId": "s3", "customTitle": "Renamed"}))
        else:
            added = root / "projects/p/s1/subagents/workflows/wf_b/journal.jsonl"
            added.parent.mkdir(parents=True)
            added.write_text(_json.dumps({"type": "launched", "agentId": "b1"}) + "\n")
        result = service.import_source(ImportRequest("claude_code", root))
        service.close()
        assert "error" not in result and result["projection"]["scope"]["kind"] == "closure"
        if sidecar == "title":
            assert (
                store.db.execute("SELECT title FROM session WHERE native_id='s3'").fetchone()[0]
                == "Renamed"
            )
        reference = copy_home(store, tmp_path / "reference")
    with Store(reference) as full:
        rebuild(full)
    assert differing_tables(tmp_path / "data", reference) == []

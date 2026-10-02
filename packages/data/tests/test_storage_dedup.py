"""Content-addressed ext payloads: lossless reads, no envelope copy, consistent refcounts.

Synthetic Claude Code transcripts only; no real sessions are read.
"""

import hashlib
import json
from pathlib import Path

import pytest

from tandem_data import payload
from tandem_data.query import event_page, trajectory_page
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store, insert_rows

BIG = 48_000


def _big(seed: int) -> str:
    line = f"run {seed}: " + "第 {i} 行输出 ok " * 3 + "\n"
    return "".join(line.replace("{i}", str(i)) for i in range(BIG // len(line) + 1))[:BIG]


def _iso(second: int) -> str:
    return f"2026-10-02T00:{second // 60:02d}:{second % 60:02d}.000Z"


def write_sessions(root: Path) -> dict[str, str]:
    """Two sessions; returns {tool_use_id: sha256(stdout)} for every large output."""
    digests = {}
    shared = _big(0)  # Same output in two sessions -> one blob, two references.
    for s in range(2):
        sid = f"cc-{s}"
        base = {"sessionId": sid, "cwd": "/work/demo", "version": "2.1.0"}
        rows = []
        clock = 0
        for k in range(4):
            call = f"{sid}-c{k}"
            rows.append(
                {
                    **base,
                    "type": "user",
                    "uuid": f"{sid}-u{k}",
                    "timestamp": _iso(clock),
                    "message": {"role": "user", "content": f"请修复第 {k} 个问题，会话 {s}"},
                }
            )
            rows.append(
                {
                    **base,
                    "type": "assistant",
                    "uuid": f"{sid}-a{k}",
                    "parentUuid": f"{sid}-u{k}",
                    "timestamp": _iso(clock + 1),
                    "message": {
                        "id": f"{sid}-r{k}",
                        "model": "fixture-model",
                        "stop_reason": "tool_use",
                        "content": [
                            {"type": "text", "text": "我来检查一下。"},
                            {
                                "type": "tool_use",
                                "id": call,
                                "name": "Bash",
                                "input": {"command": f"pytest -q tests/test_{k}.py"},
                            },
                        ],
                        "usage": {"input_tokens": 100, "output_tokens": 5},
                    },
                }
            )
            out = shared if k == 0 else (_big(10 * s + k) if k == 1 else "ok " * 20)
            if len(out) >= 40_000:
                digests[call] = hashlib.sha256(out.encode()).hexdigest()
            result = {
                "durationMs": 800,
                "stdout": out,
                "stderr": "",
                "interrupted": False,
                # Native data shaped like a reference must survive unchanged.
                "meta": {"$blob": "0" * 64, "len": 3},
                "chunks": [out[:5000], {"x": [out[:4100]]}],
            }
            if k == 3:
                result = "Error: tool crashed " + "!" * 5000  # Non-dict results are kept too.
            rows.append(
                {
                    **base,
                    "type": "user",
                    "uuid": f"{sid}-o{k}",
                    "parentUuid": f"{sid}-a{k}",
                    "timestamp": _iso(clock + 2),
                    "toolUseResult": result,
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": call,
                                "content": out,
                                "is_error": k == 3,
                            }
                        ],
                    },
                }
            )
            clock += 5
        path = root / "projects" / "-work-demo" / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return digests


def import_home(home: Path, source: Path) -> Store:
    store = Store(home)
    ImportService(store).import_source(ImportRequest("claude_code", source))
    return store


def dump(home: Path) -> tuple[str, str]:
    with Store(home) as store:
        sessions = [r[0] for r in store.db.execute("SELECT session_uid FROM session ORDER BY 1")]
    events = "\n".join(
        json.dumps(event_page(home, s, limit=1000), ensure_ascii=False) for s in sessions
    )
    trajectories = "\n".join(
        json.dumps(trajectory_page(home, s, limit=1000), ensure_ascii=False) for s in sessions
    )
    return events, trajectories


@pytest.fixture
def corpus(tmp_path):
    source = tmp_path / "claude"
    digests = write_sessions(source)
    return source, digests


def test_packed_reads_are_byte_identical_to_inline_storage(tmp_path, corpus, monkeypatch):
    source, digests = corpus
    with monkeypatch.context() as patch:
        # Inline: no blob is ever written.
        patch.setattr(payload, "THRESHOLD", 1 << 40)
        patch.setattr(payload, "TEXT_THRESHOLD", 1 << 40)
        import_home(tmp_path / "inline", source).db.close()
    import_home(tmp_path / "packed", source).db.close()
    with Store(tmp_path / "inline") as inline:
        assert inline.db.execute("SELECT COUNT(*) FROM content_blob").fetchone()[0] == 0
    with Store(tmp_path / "packed") as packed:
        assert packed.db.execute("SELECT COUNT(*) FROM content_blob").fetchone()[0] > 0
    assert dump(tmp_path / "inline") == dump(tmp_path / "packed")

    events, _ = dump(tmp_path / "packed")
    restored = {}
    for page in events.splitlines():
        for event in json.loads(page):
            result = event["ext"].get("toolUseResult")
            if event["kind"] == "tool.result" and isinstance(result, dict):
                restored[event["call_id"]] = hashlib.sha256(result["stdout"].encode()).hexdigest()
                assert result["meta"] == {"$blob": "0" * 64, "len": 3}
            if event["kind"] == "tool.result" and event["call_id"].endswith("c3"):
                assert result.startswith("Error: tool crashed")
    assert digests and {k: restored[k] for k in digests} == digests


def test_envelope_never_copies_tool_use_result(tmp_path, corpus):
    source, _ = corpus
    with import_home(tmp_path / "home", source) as store:
        assert store.db.execute("SELECT COUNT(*) FROM event").fetchone()[0] > 0
        assert not store.db.execute(
            "SELECT event_uid FROM event WHERE json_extract(ext,'$.envelope.toolUseResult') IS NOT NULL "
            "OR json_type(ext,'$.envelope.toolUseResult') IS NOT NULL"
        ).fetchall()
        # Each tool result record keeps exactly one copy of its native toolUseResult.
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM event WHERE kind='tool.result' AND json_type(ext,'$.toolUseResult') IS NOT NULL"
            ).fetchone()[0]
            == 8
        )


def test_refcounts_dedup_and_garbage_collection(tmp_path, corpus):
    source, _ = corpus
    with import_home(tmp_path / "home", source) as store:
        report = store.verify()
        assert report["integrity"] == "ok"
        assert report["content_blobs"]["references"] > report["content_blobs"]["blobs"]
        assert not store.db.execute("PRAGMA foreign_key_check").fetchall()
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM v_raw_record_ledger WHERE (disposition IN ('mapped','folded','replayed','duplicate') AND event_count=0) OR (disposition IN ('ignored','unparsed') AND event_count>0)"
            ).fetchone()[0]
            == 0
        )
        shared = hashlib.sha256(_big(0).encode()).hexdigest()
        # ext.toolUseResult.stdout and the tool.result event.text, in both sessions.
        assert (
            store.db.execute("SELECT refs FROM content_blob WHERE sha256=?", (shared,)).fetchone()[
                0
            ]
            == 4
        )
        # The four large tool outputs are stored as references, not inline.
        assert not store.db.execute("SELECT 1 FROM event WHERE length(text) >= 40000").fetchall()
        assert (
            store.db.execute(
                f"SELECT COUNT(*) FROM event WHERE kind='tool.result' AND {payload.TEXT_REFERENCE_SQL}"
            ).fetchone()[0]
            == 4
        )
        assert not store.db.execute("SELECT 1 FROM content_blob WHERE refs=0").fetchall()
        before = store.db.execute("SELECT COUNT(*) FROM content_blob").fetchone()[0]
        # Republishing deletes and reinserts events; counts must return to the same values.
        store.rebuild()
        assert store.db.execute("SELECT COUNT(*) FROM content_blob").fetchone()[0] == before
        assert payload.verify(store.db)["blobs"] == before
        # Removing every event (FK enforcement off: only refcount triggers matter here)
        # must release every reference.
        store.db.execute("PRAGMA foreign_keys=OFF")
        store.db.execute("DELETE FROM event")
        assert (
            store.db.execute("SELECT COUNT(*) FROM content_blob WHERE refs<>0").fetchone()[0] == 0
        )
        assert payload.collect_garbage(store.db) == before
        assert payload.verify(store.db) == {"blobs": 0, "references": 0}


def test_verify_rejects_dangling_and_miscounted_references(tmp_path, corpus):
    source, _ = corpus
    with import_home(tmp_path / "home", source) as store:
        digest = store.db.execute("SELECT sha256 FROM content_blob LIMIT 1").fetchone()[0]
        store.db.execute("UPDATE content_blob SET refs=refs+1 WHERE sha256=?", (digest,))
        with pytest.raises(ValueError, match="reference count"):
            store.verify()
        store.db.execute("UPDATE content_blob SET refs=refs-1 WHERE sha256=?", (digest,))
        store.db.execute("DELETE FROM content_blob WHERE sha256=?", (digest,))
        with pytest.raises(ValueError, match="missing content_blob"):
            store.verify()


def test_insert_rows_packs_like_insert(tmp_path):
    with Store(tmp_path / "home") as store:
        store.db.execute("CREATE TEMP TABLE probe(id INTEGER, ext TEXT)")
        assert insert_rows(store.db, "probe", [{"id": 1, "ext": "{}"}]) == 1
        big = "长" * 3000
        packed = payload.pack_row(store.db, "event", {"ext": json.dumps({"a": [big]})})
        reference = json.loads(packed["ext"])["a"][0]
        assert payload.is_reference(reference) and reference["len"] == 3000
        assert payload.restore_json(store.db, packed["ext"]) == {"a": [big]}
        with pytest.raises(ValueError):
            insert_rows(store.db, "probe", [{"id": 1, "ext": "{}"}, {"ext": "{}", "id": 2}])


def test_event_search_indexes_only_messages_and_titles(tmp_path, corpus):
    source, _ = corpus
    with import_home(tmp_path / "home", source) as store:
        db = store.db
        kinds = "('message.user','message.assistant','session.title')"
        indexed = db.execute("SELECT COUNT(*) FROM event_search").fetchone()[0]
        expected = db.execute(
            f"SELECT COUNT(*) FROM event WHERE kind IN {kinds} AND text IS NOT NULL"
        ).fetchone()[0]
        assert indexed == expected > 0
        assert (
            db.execute(
                f"SELECT COUNT(*) FROM event_search s JOIN event e ON e.rowid=s.rowid WHERE e.kind NOT IN {kinds}"
            ).fetchone()[0]
            == 0
        )
        hits = {
            r[0]
            for r in db.execute(
                "SELECT e.event_uid FROM event_search s JOIN event e ON e.rowid=s.rowid WHERE event_search MATCH ?",
                ('"修复第 2 个"',),
            )
        }
        like = {
            r[0]
            for r in db.execute(
                f"SELECT event_uid FROM event WHERE kind IN {kinds} AND text LIKE '%修复第 2 个%'"
            )
        }
        assert hits == like and len(hits) == 2
        # Tool output (which repeats 行输出) is not in the full-text index.
        assert not db.execute(
            "SELECT 1 FROM event_search WHERE event_search MATCH '\"行输出\"'"
        ).fetchall()
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'event_fts%'"
        ).fetchall()


def test_compaction_keeps_logical_contents(tmp_path, corpus):
    from tandem_data.validation.integrity import logical_digest

    source, _ = corpus
    home = tmp_path / "home"
    import_home(home, source).db.close()
    before, digest = dump(home), logical_digest(home)
    with Store(home) as store:
        assert not store.compact()  # Small stores are never rewritten implicitly.
        assert store.compact(force=True)
        assert store.verify()["integrity"] == "ok"
    assert dump(home) == before
    assert logical_digest(home) == digest

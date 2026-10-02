"""SQLite ledger, atomic source publication and rebuildable retrieval projections."""

import fcntl
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

from .contracts import Page, Resource, SourceSpec, canonical_json, digest
from .features import CHUNK_VERSION, FEATURE_VERSION, chunks, extract, lexical_tokens

APPLICATION_ID = 0x54434C47  # TCLG; prevents accidentally opening tandem.db/analysis.db.
SCHEMA_VERSION = 2


class CatalogBusy(RuntimeError):
    pass


class CatalogStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Opening an existing catalog for search must work during another process's sync.
        if self.path.is_file() and self.path.stat().st_size:
            with self.connect(True) as conn:
                app_id = conn.execute("PRAGMA application_id").fetchone()[0]
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if app_id == APPLICATION_ID and version == SCHEMA_VERSION:
                    return
        with self.writer(), self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            app_id = conn.execute("PRAGMA application_id").fetchone()[0]
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if app_id not in (0, APPLICATION_ID) or (app_id == 0 and tables):
                raise ValueError("not_a_catalog_database")
            if version not in (0, 1, SCHEMA_VERSION):
                raise ValueError("unsupported_catalog_schema")
            if version == 0:
                schema = files("tandem_catalog").joinpath("schema.sql").read_text()
                conn.executescript("BEGIN IMMEDIATE;\n" + schema +
                                   f"\nPRAGMA application_id={APPLICATION_ID};"
                                   f"\nPRAGMA user_version={SCHEMA_VERSION}; COMMIT;")
            elif version == 1:
                migration = files("tandem_catalog").joinpath("migrations/002.sql").read_text()
                conn.executescript("BEGIN IMMEDIATE;\n" + migration + "\nPRAGMA user_version=2; COMMIT;")
            conn.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def writer(self):
        """One writer process, including network sync; readers continue through WAL."""
        with self.path.with_suffix(".writer.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CatalogBusy("catalog_writer_busy") from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    @contextmanager
    def connect(self, readonly: bool = False):
        target = self.path.as_uri() + "?mode=ro" if readonly else str(self.path)
        conn = sqlite3.connect(target, uri=readonly, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        if readonly:
            conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def register(self, sources: list[SourceSpec]) -> None:
        with self.writer(), self.connect() as conn:
            for source in sources:
                old = conn.execute("SELECT spec FROM catalog_source WHERE source_id=?", (source.source_id,)).fetchone()
                spec = source.model_dump_json()
                if old and SourceSpec.model_validate_json(old[0]) == source:
                    continue
                conn.execute("INSERT INTO catalog_source(source_id,spec,enabled,priority) VALUES(?,?,?,?) "
                             "ON CONFLICT(source_id) DO UPDATE SET spec=excluded.spec,enabled=excluded.enabled,"
                             "priority=excluded.priority,revision=NULL,watermark=NULL,next_due_at=0",
                             (source.source_id, spec, source.enabled, source.priority))
                conn.execute("UPDATE sync_run SET status='cancelled' WHERE source_id=? AND "
                             "status IN ('running','paused','failed','ready')", (source.source_id,))
                ids = conn.execute("SELECT DISTINCT item_id FROM item_source WHERE source_id=?", (source.source_id,))
                for row in ids.fetchall():
                    self._materialize(conn, row[0], int(time.time() * 1000))

    def sources(self) -> list[dict]:
        with self.connect(True) as conn:
            rows = conn.execute("SELECT * FROM catalog_source ORDER BY priority DESC,source_id").fetchall()
            return [{**dict(row), "spec": json.loads(row["spec"])} for row in rows]

    def begin_run(self, source_id: str) -> dict:
        """Caller owns writer(); resume staged pages rather than moving a committed watermark."""
        with self.connect() as conn:
            run = conn.execute("SELECT * FROM sync_run WHERE source_id=? AND status IN "
                               "('running','paused','failed','ready') ORDER BY started_at DESC LIMIT 1", (source_id,)).fetchone()
            if not run:
                run_id = uuid.uuid4().hex
                conn.execute("INSERT INTO sync_run(run_id,source_id,status,started_at) VALUES(?,?,'running',?)",
                             (run_id, source_id, int(time.time() * 1000)))
                run = conn.execute("SELECT * FROM sync_run WHERE run_id=?", (run_id,)).fetchone()
            return {**dict(run), "checkpoint": json.loads(run["checkpoint"])}

    def stage(self, run_id: str, page: Page) -> None:
        with self.connect() as conn:
            for record in page.records:
                resource = record.resource
                if resource.body_policy == "metadata":
                    resource = resource.model_copy(update={"body": ""})
                conn.execute("INSERT INTO sync_stage VALUES(?,?,?,?) ON CONFLICT(run_id,native_id) "
                             "DO UPDATE SET resource=excluded.resource,raw=excluded.raw",
                             (run_id, record.native_id, resource.model_dump_json(), canonical_json(record.raw)))
            conn.execute("UPDATE sync_run SET checkpoint=?,mode=?,revision=?,watermark=?,status=? WHERE run_id=?",
                         (canonical_json(page.checkpoint), page.mode, page.revision, page.watermark,
                          "ready" if page.complete else "running", run_id))

    def publish(self, run_id: str) -> dict:
        """Whole source revision, tombstones, FTS, features and cursor commit together."""
        now = int(time.time() * 1000)
        with self.connect() as conn:
            run = conn.execute("SELECT * FROM sync_run WHERE run_id=?", (run_id,)).fetchone()
            if not run or run["status"] != "ready":
                raise ValueError("source_revision_incomplete")
            affected = ({r[0] for r in conn.execute("SELECT item_id FROM item_source WHERE source_id=?", (run["source_id"],))}
                        if run["mode"] == "full" else set())
            staged = conn.execute("SELECT * FROM sync_stage WHERE run_id=?", (run_id,)).fetchall()
            for row in staged:
                resource = Resource.model_validate_json(row["resource"])
                previous = conn.execute("SELECT item_id FROM item_source WHERE source_id=? AND native_id=?",
                                        (run["source_id"], row["native_id"])).fetchone()
                if previous:
                    affected.add(previous[0])
                affected.add(resource.item_id)
                conn.execute("INSERT INTO item_source VALUES(?,?,?,?,?,'active',?,?) "
                             "ON CONFLICT(source_id,native_id) DO UPDATE SET item_id=excluded.item_id,"
                             "resource=excluded.resource,raw=excluded.raw,status='active',seen_run=excluded.seen_run,"
                             "fetched_at=excluded.fetched_at",
                             (run["source_id"], row["native_id"], resource.item_id, row["resource"], row["raw"], run_id, now))
            if run["mode"] == "full":
                conn.execute("UPDATE item_source SET status='removed' WHERE source_id=? AND seen_run!=?",
                             (run["source_id"], run_id))
            changed, retired = 0, 0
            for item_id in sorted(affected):
                change, removal = self._materialize(conn, item_id, now)
                changed += change
                retired += removal
            spec = SourceSpec.model_validate_json(conn.execute("SELECT spec FROM catalog_source WHERE source_id=?",
                                                              (run["source_id"],)).fetchone()[0])
            conn.execute("UPDATE catalog_source SET revision=?,watermark=?,completed_at=?,next_due_at=?,failures=0,error=NULL "
                         "WHERE source_id=?", (run["revision"], run["watermark"], now, now + spec.refresh_seconds * 1000, run["source_id"]))
            conn.execute("UPDATE sync_run SET status='completed',finished_at=?,seen=?,changed=?,retired=?,error=NULL WHERE run_id=?",
                         (now, len(staged), changed, retired, run_id))
            conn.execute("DELETE FROM sync_stage WHERE run_id=?", (run_id,))
            conn.execute("UPDATE catalog_meta SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
            return dict(conn.execute("SELECT * FROM sync_run WHERE run_id=?", (run_id,)).fetchone())

    def _materialize(self, conn, item_id: str, now: int) -> tuple[int, int]:
        winner = conn.execute("SELECT s.resource FROM item_source s JOIN catalog_source c USING(source_id) "
                              "WHERE s.item_id=? AND s.status='active' AND c.enabled=1 "
                              "ORDER BY c.priority DESC,(json_extract(s.resource,'$.repo_path') IS NOT NULL) DESC,"
                              "c.source_id,s.native_id LIMIT 1", (item_id,)).fetchone()
        old = conn.execute("SELECT * FROM catalog_item WHERE item_id=?", (item_id,)).fetchone()
        if winner is None:
            if old and old["status"] != "deleted":
                conn.execute("UPDATE catalog_item SET status='deleted',last_seen=? WHERE item_id=?", (now, item_id))
                self._clear_projections(conn, item_id)
                return 0, 1
            return 0, 0
        resource = Resource.model_validate_json(winner[0])
        resource = resource.model_copy(update={"features": extract(resource)})
        # Popularity changes do not force content re-embedding; it is presentation metadata.
        document = resource.model_dump(exclude={"popularity"})
        content_hash = digest({"body": resource.body, "name": resource.name, "summary": resource.summary,
                               "type": resource.type, "manifest": resource.manifest,
                               "install": resource.install, "agents": resource.agents})
        version_id = digest([FEATURE_VERSION, CHUNK_VERSION, content_hash, document])
        same = old and old["latest_version"] == version_id and old["status"] == resource.status
        metadata = resource.model_dump(exclude={"body", "features"})
        conn.execute("INSERT INTO catalog_item VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                     "ON CONFLICT(item_id) DO UPDATE SET type=excluded.type,name=excluded.name,summary=excluded.summary,"
                     "url=excluded.url,status=excluded.status,license=excluded.license,agents=excluded.agents,"
                     "language=excluded.language,difficulty=excluded.difficulty,official=excluded.official,"
                     "latest_version=excluded.latest_version,content_hash=excluded.content_hash,metadata=excluded.metadata,"
                     "last_seen=excluded.last_seen",
                     (item_id, resource.type, resource.name, resource.summary, resource.url, resource.status, resource.license,
                      canonical_json(resource.agents), resource.language, resource.difficulty, resource.official, version_id,
                      content_hash, canonical_json(metadata), now, now))
        conn.execute("INSERT OR IGNORE INTO item_version VALUES(?,?,?,?,?)",
                     (version_id, item_id, content_hash, canonical_json(document), now))
        if same:
            return 0, 0
        self._clear_projections(conn, item_id)
        if resource.status != "active":
            return 1, 1
        conn.executemany("INSERT INTO item_feature VALUES(?,?,?,?,?,?)",
                         [(item_id, f.feature, f.value, f.weight, f.origin, f.evidence) for f in resource.features])
        conn.executemany("INSERT INTO item_component VALUES(?,?)", [(item_id, child) for child in set(resource.components)])
        for chunk in chunks(resource):
            chunk_id = digest([version_id, chunk["ordinal"], chunk["text_hash"]])
            inserted = conn.execute("INSERT INTO resource_chunk VALUES(?,?,?,?,?,?,?,?,?)",
                         (chunk_id, item_id, version_id, chunk["field"], chunk["heading"], chunk["ordinal"],
                          chunk["start"], chunk["text"], chunk["text_hash"]))
            conn.execute("INSERT INTO chunk_fts(rowid,chunk_id,item_id,title,content) VALUES(?,?,?,?,?)", (inserted.lastrowid, chunk_id, item_id,
                         " ".join(lexical_tokens(resource.name)), " ".join(lexical_tokens(chunk["text"]))))
            conn.execute("INSERT INTO chunk_embedding SELECT ?,model_id,text_hash,dimensions,vector,? "
                         "FROM embedding_cache WHERE text_hash=?", (chunk_id, now, chunk["text_hash"]))
        if resource.type == "model":
            conn.execute("INSERT INTO model_info VALUES(?,?,?,?)", (item_id, resource.metadata.get("provider", "unknown"),
                         resource.metadata.get("model_id", resource.name), canonical_json(resource.manifest)))
        elif resource.type == "benchmark":
            m = resource.manifest
            conn.execute("INSERT INTO benchmark_result VALUES(?,?,?,?,?,?,?,?)", (item_id, m.get("model_id", resource.name),
                         m.get("effort"), m.get("harness"), m.get("benchmark", "unknown"), m.get("benchmark_version"),
                         m.get("measured_at"), canonical_json(m)))
        return 1, 0

    @staticmethod
    def _clear_projections(conn, item_id: str):
        for table in ("resource_chunk", "item_feature", "item_component", "model_info", "benchmark_result"):
            key = "parent_id" if table == "item_component" else "item_id"
            conn.execute(f"DELETE FROM {table} WHERE {key}=?", (item_id,))

    def finish_interrupted(self, run_id: str, error: str | None = None, retry_after: int = 0) -> dict:
        with self.connect() as conn:
            status = "failed" if error else "paused"
            conn.execute("UPDATE sync_run SET status=?,error=? WHERE run_id=?", (status, error, run_id))
            run = conn.execute("SELECT * FROM sync_run WHERE run_id=?", (run_id,)).fetchone()
            if error:
                failures = conn.execute("SELECT failures FROM catalog_source WHERE source_id=?", (run["source_id"],)).fetchone()[0] + 1
                delay = max(retry_after, min(86400, 60 * 2 ** min(failures - 1, 10)))
                conn.execute("UPDATE catalog_source SET failures=?,error=?,next_due_at=? WHERE source_id=?",
                             (failures, error, int(time.time() * 1000) + delay * 1000, run["source_id"]))
            return dict(run)

    def stats(self) -> dict:
        with self.connect(True) as conn:
            def count(sql):
                return conn.execute(sql).fetchone()[0]
            return {"contract": "catalog-v1", "schema_version": SCHEMA_VERSION,
                    "generation": int(count("SELECT value FROM catalog_meta WHERE key='generation'")),
                    "items": count("SELECT count(*) FROM catalog_item WHERE status='active'"),
                    "chunks": count("SELECT count(*) FROM resource_chunk"),
                    "versions": count("SELECT count(*) FROM item_version"),
                    "features": count("SELECT count(*) FROM item_feature"),
                    "by_type": {r[0]: r[1] for r in conn.execute("SELECT type,count(*) FROM catalog_item WHERE status='active' GROUP BY type")},
                    "embeddings": [{**dict(r), "descriptor": json.loads(r["descriptor"])} for r in conn.execute(
                        "SELECT m.*,count(e.chunk_id) AS indexed_chunks FROM embedding_model m LEFT JOIN chunk_embedding e USING(model_id) GROUP BY m.model_id")]}

    def detail(self, item_id: str) -> dict | None:
        with self.connect(True) as conn:
            row = conn.execute("SELECT i.*,v.document FROM catalog_item i JOIN item_version v ON v.version_id=i.latest_version WHERE i.item_id=?", (item_id,)).fetchone()
            if row is None:
                return None
            return {"resource": {**json.loads(row["document"]), "status": row["status"]},
                    "version_id": row["latest_version"], "content_hash": row["content_hash"],
                    "first_seen": row["first_seen"], "last_seen": row["last_seen"],
                    "sources": [dict(r) for r in conn.execute("SELECT source_id,native_id,status,fetched_at FROM item_source WHERE item_id=?", (item_id,))],
                    "chunks": [dict(r) for r in conn.execute("SELECT chunk_id,field,heading,ordinal,start,text FROM resource_chunk WHERE item_id=? ORDER BY ordinal", (item_id,))]}

    def rebuild(self):
        """Recompute feature/chunk projections from normalized source records, without network."""
        with self.writer(), self.connect() as conn:
            ids = [r[0] for r in conn.execute("SELECT DISTINCT item_id FROM item_source")]
            changed = sum(self._materialize(conn, item_id, int(time.time() * 1000))[0] for item_id in ids)
            conn.execute("UPDATE catalog_meta SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
        return {"items_checked": len(ids), "changed": changed}

    def verify(self):
        with self.connect(True) as conn:
            integrity = [r[0] for r in conn.execute("PRAGMA quick_check")]
            foreign_keys = [tuple(r) for r in conn.execute("PRAGMA foreign_key_check")]
            missing_fts = conn.execute("SELECT count(*) FROM resource_chunk c LEFT JOIN chunk_fts f ON f.rowid=c.rowid "
                                       "WHERE f.chunk_id IS NULL OR f.chunk_id!=c.chunk_id").fetchone()[0]
            orphan_fts = conn.execute("SELECT count(*) FROM chunk_fts f LEFT JOIN resource_chunk c ON c.rowid=f.rowid "
                                      "WHERE c.chunk_id IS NULL OR c.chunk_id!=f.chunk_id").fetchone()[0]
            invalid_vectors = conn.execute("SELECT count(*) FROM chunk_embedding e JOIN resource_chunk c USING(chunk_id) "
                                           "JOIN embedding_model m USING(model_id) WHERE e.text_hash!=c.text_hash OR e.dimensions!=m.dimensions "
                                           "OR length(e.vector)!=e.dimensions*4").fetchone()[0]
            invalid_versions = conn.execute("SELECT count(*) FROM catalog_item i LEFT JOIN item_version v "
                                            "ON v.version_id=i.latest_version WHERE v.version_id IS NULL OR i.content_hash!=v.content_hash").fetchone()[0]
            return {"ok": integrity == ["ok"] and not (foreign_keys or missing_fts or orphan_fts or invalid_vectors or invalid_versions),
                    "sqlite": integrity, "foreign_key_errors": foreign_keys, "missing_fts": missing_fts,
                    "orphan_fts": orphan_fts, "invalid_vectors": invalid_vectors, "invalid_versions": invalid_versions}

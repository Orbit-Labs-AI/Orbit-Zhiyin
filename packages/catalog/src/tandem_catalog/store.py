"""SQLite ledger, atomic source publication and rebuildable retrieval projections (schema v3).

Text is stored once in the content-addressed ``blob`` table; ``item_source`` and
``item_version`` keep hashes. Unchanged records are skipped on publish, so a nightly
re-sync of an unchanged source only touches ``seen_run``.
"""

import fcntl
import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
import zlib
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from importlib.resources import files
from pathlib import Path

from .contracts import Page, Resource, SourceSpec, canonical_json, digest
from .features import CHUNK_VERSION, FEATURE_VERSION, chunks, extract, lexical_tokens
from .risk import assess

APPLICATION_ID = 0x54434C47  # TCLG; prevents accidentally opening tandem.db/analysis.db.
SCHEMA_VERSION = 3
KEEP_VERSIONS = 5
BATCH = 500
LOCAL_SOURCE = "local"
UNLISTED_TYPES = ("model", "benchmark")
log = logging.getLogger(__name__)


class CatalogBusy(RuntimeError):
    pass


def _now() -> int:
    return int(time.time() * 1000)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put_blob(conn, data: bytes, sha: str | None = None) -> str:
    """Content-addressed, deduplicated; payloads >=200 B are zlib level 6."""
    sha = sha or _sha(data)
    if conn.execute("SELECT 1 FROM blob WHERE sha=?", (sha,)).fetchone() is None:
        codec, payload = (0, data) if len(data) < 200 else (1, zlib.compress(data, 6))
        conn.execute("INSERT INTO blob VALUES(?,?,?,?)", (sha, codec, len(data), payload))
    return sha


def get_blob(conn, sha: str | None) -> bytes | None:
    if sha is None:
        return None
    row = conn.execute("SELECT codec,data FROM blob WHERE sha=?", (sha,)).fetchone()
    if row is None:
        return None
    return zlib.decompress(row[1]) if row[0] == 1 else bytes(row[1])


def _pragmas(conn, readonly: bool) -> None:
    for pragma in ("foreign_keys=ON", f"busy_timeout={5000 if readonly else 30000}", "synchronous=NORMAL",
                   "mmap_size=268435456", "cache_size=-65536", "temp_store=MEMORY"):
        conn.execute("PRAGMA " + pragma)
    if readonly:
        conn.execute("PRAGMA query_only=ON")


def _ms(value) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value * 1000) if value < 1e11 else int(value)
    if isinstance(value, str) and value:
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return None
    return None


def _text(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("name")
    return str(value)[:200] if isinstance(value, (str, int, float)) and value != "" else None


def _count(value) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return int(value) if isinstance(value, str) and value.isdigit() else 0


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _flag(value):
    return int(value) if isinstance(value, bool) else None


class CatalogStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._index = None
        self._index_lock = threading.Lock()
        self._chunk_cache = {}
        self._chunk_lock = threading.Lock()
        # Opening an existing catalog for search must work during another process's sync.
        if self.path.is_file() and self.path.stat().st_size:
            with self.connect(True) as conn:
                app_id = conn.execute("PRAGMA application_id").fetchone()[0]
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if app_id == APPLICATION_ID and version == SCHEMA_VERSION:
                    return
        with self.writer():
            self._create_or_upgrade()

    def _create_or_upgrade(self):
        conn = sqlite3.connect(self.path, isolation_level=None)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            app_id = conn.execute("PRAGMA application_id").fetchone()[0]
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if app_id not in (0, APPLICATION_ID) or (app_id == 0 and tables):
                raise ValueError("not_a_catalog_database")
            if version in (1, 2):
                # Unreleased cache format: keep a backup, rebuild from sources on next sync.
                conn.close()
                conn = None
                for suffix in ("", "-wal", "-shm"):
                    source = Path(str(self.path) + suffix)
                    if source.exists():
                        source.replace(Path(str(self.path) + ".v2.bak" + suffix))
                log.warning("catalog schema v%s moved to %s.v2.bak; rebuilding v3", version, self.path.name)
                conn = sqlite3.connect(self.path, isolation_level=None)
                version = 0
            elif version not in (0, SCHEMA_VERSION):
                raise ValueError("unsupported_catalog_schema")
            if version == 0:
                # Staging pages are deleted after every publish; incremental vacuum returns them.
                conn.execute("PRAGMA page_size=8192")
                conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
                schema = files("tandem_data").joinpath("migrations/catalog/schema.sql").read_text()
                conn.executescript("BEGIN IMMEDIATE;\n" + schema +
                                   f"\nPRAGMA application_id={APPLICATION_ID};"
                                   f"\nPRAGMA user_version={SCHEMA_VERSION}; COMMIT;")
            conn.execute("PRAGMA journal_mode=WAL")
        finally:
            if conn is not None:
                conn.close()

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
        conn = sqlite3.connect(target, uri=readonly, timeout=5 if readonly else 30)
        conn.row_factory = sqlite3.Row
        _pragmas(conn, readonly)
        conn.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def reader(self):
        """Thread-local cached read-only connection; reentrant, one snapshot per outer block."""
        local = self._local
        conn = getattr(local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5, isolation_level=None)
            conn.row_factory = sqlite3.Row
            _pragmas(conn, True)
            local.conn, local.depth = conn, 0
        if local.depth == 0:
            conn.execute("BEGIN")
        local.depth += 1
        try:
            yield conn
        finally:
            local.depth -= 1
            if local.depth == 0:
                conn.execute("ROLLBACK")

    @staticmethod
    def generation(conn) -> int:
        return int(conn.execute("SELECT value FROM catalog_meta WHERE key='generation'").fetchone()[0])

    @staticmethod
    def _bump(conn) -> None:
        conn.execute("UPDATE catalog_meta SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")

    def index(self, conn=None):
        """In-memory snapshot (see index.py), rebuilt lazily when the generation moves."""
        if conn is None:
            with self.reader() as conn:
                return self.index(conn)
        generation = self.generation(conn)
        current = self._index
        if current is not None and current.generation >= generation:
            return current
        with self._index_lock:
            if self._index is None or self._index.generation < generation:
                from .index import CatalogIndex
                self._index = CatalogIndex.build(conn, generation)
            return self._index

    # -- sources and sync ----------------------------------------------------------------
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
                ids = {r[0] for r in conn.execute("SELECT DISTINCT item_id FROM item_source WHERE source_id=?",
                                                  (source.source_id,))}
                if ids:
                    self._materialize_many(conn, ids, _now())
                    self._bump(conn)

    def _ensure_local(self, conn) -> None:
        # Stored as enabled=0 so network sync never visits it; materialization treats 'local' as
        # always enabled (see the `c.source_id='local'` terms).
        spec = SourceSpec(source_id=LOCAL_SOURCE, kind="local", url="local:", priority=100, enabled=False,
                          refresh_seconds=10 * 365 * 86400)
        conn.execute("INSERT OR IGNORE INTO catalog_source(source_id,spec,enabled,priority,next_due_at) "
                     "VALUES(?,?,0,?,?)", (LOCAL_SOURCE, spec.model_dump_json(), spec.priority,
                                           _now() + spec.refresh_seconds * 1000))

    def ensure_local_source(self) -> None:
        with self.writer(), self.connect() as conn:
            self._ensure_local(conn)

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
                             (run_id, source_id, _now()))
                run = conn.execute("SELECT * FROM sync_run WHERE run_id=?", (run_id,)).fetchone()
            return {**dict(run), "checkpoint": json.loads(run["checkpoint"])}

    def stage(self, run_id: str, page: Page) -> None:
        rows = []
        for record in page.records:
            resource = record.resource
            if resource.body_policy == "metadata":
                resource = resource.model_copy(update={"body": ""})
            # Staging is transient: fast zlib level keeps page writes cheap.
            rows.append((run_id, record.native_id, zlib.compress(canonical_json(resource.model_dump()).encode(), 1),
                         zlib.compress(canonical_json(record.raw).encode(), 1)))
        with self.connect() as conn:
            conn.executemany("INSERT INTO sync_stage VALUES(?,?,?,?) ON CONFLICT(run_id,native_id) "
                             "DO UPDATE SET resource=excluded.resource,raw=excluded.raw", rows)
            conn.execute("UPDATE sync_run SET checkpoint=?,mode=?,revision=?,watermark=?,status=? WHERE run_id=?",
                         (canonical_json(page.checkpoint), page.mode, page.revision, page.watermark,
                          "ready" if page.complete else "running", run_id))

    def _write_source(self, conn, source_id, native_id, doc, body, raw_bytes, run_id, now) -> tuple[str, str | None, str]:
        res_bytes = canonical_json(doc).encode()
        res_sha = put_blob(conn, res_bytes)
        body_sha = put_blob(conn, body.encode()) if body else None
        raw_sha = put_blob(conn, raw_bytes)
        conn.execute("INSERT INTO item_source VALUES(?,?,?,'active',?,?,?,?,?,?) "
                     "ON CONFLICT(source_id,native_id) DO UPDATE SET item_id=excluded.item_id,status='active',"
                     "seen_run=excluded.seen_run,fetched_at=excluded.fetched_at,res_sha=excluded.res_sha,"
                     "body_sha=excluded.body_sha,raw_sha=excluded.raw_sha,has_path=excluded.has_path",
                     (source_id, native_id, doc["item_id"], run_id, now, res_sha, body_sha, raw_sha,
                      int(doc.get("repo_path") is not None)))
        return res_sha, body_sha, raw_sha

    def publish(self, run_id: str) -> dict:
        """Whole source revision, tombstones, FTS, features and cursor commit together."""
        now = _now()
        with self.connect() as conn:
            run = conn.execute("SELECT * FROM sync_run WHERE run_id=?", (run_id,)).fetchone()
            if not run or run["status"] != "ready":
                raise ValueError("source_revision_incomplete")
            source_id = run["source_id"]
            if source_id == LOCAL_SOURCE:
                raise ValueError("local_source_not_syncable")
            affected, seen = self._apply_stage(conn, run_id, source_id, now)
            seen += run["seen"] or 0  # Rows already made visible by publish_partial().
            if run["mode"] == "full":
                affected.update(r[0] for r in conn.execute(
                    "UPDATE item_source SET status='removed' WHERE source_id=? AND seen_run!=? AND status='active' "
                    "RETURNING item_id", (source_id, run_id)).fetchall())
            changed, retired = self._materialize_many(conn, affected, now)
            changed += run["changed"] or 0
            spec = SourceSpec.model_validate_json(conn.execute("SELECT spec FROM catalog_source WHERE source_id=?",
                                                              (source_id,)).fetchone()[0])
            conn.execute("UPDATE catalog_source SET revision=?,watermark=?,completed_at=?,next_due_at=?,failures=0,error=NULL "
                         "WHERE source_id=?", (run["revision"], run["watermark"], now, now + spec.refresh_seconds * 1000, source_id))
            conn.execute("UPDATE sync_run SET status='completed',finished_at=?,seen=?,changed=?,retired=?,error=NULL WHERE run_id=?",
                         (now, seen, changed, retired, run_id))
            conn.execute("DELETE FROM sync_stage WHERE run_id=?", (run_id,))
            if affected:
                self._bump(conn)
            if changed or retired:
                self._vacuum_blobs(conn)
            conn.execute("PRAGMA optimize")
            result = dict(conn.execute("SELECT * FROM sync_run WHERE run_id=?", (run_id,)).fetchone())
        self._release_free_pages()
        return result

    def publish_partial(self, run_id: str) -> dict:
        """Make the pages staged so far visible while a long scan continues.

        No retirement, cursor/watermark or schedule change: the final `publish()` still decides which
        items disappeared (rows published here keep `seen_run=run_id`). A scan that fails later keeps
        these items instead of losing the whole first sync.
        """
        now = _now()
        with self.connect() as conn:
            run = conn.execute("SELECT * FROM sync_run WHERE run_id=?", (run_id,)).fetchone()
            if not run or run["status"] != "running":
                raise ValueError("source_run_not_running")
            if run["source_id"] == LOCAL_SOURCE:
                raise ValueError("local_source_not_syncable")
            affected, seen = self._apply_stage(conn, run_id, run["source_id"], now)
            changed, _ = self._materialize_many(conn, affected, now)
            conn.execute("UPDATE sync_run SET seen=COALESCE(seen,0)+?,changed=COALESCE(changed,0)+? WHERE run_id=?",
                         (seen, changed, run_id))
            conn.execute("DELETE FROM sync_stage WHERE run_id=?", (run_id,))
            if affected:
                self._bump(conn)
            return {"run_id": run_id, "seen": seen, "changed": changed}

    def _apply_stage(self, conn, run_id: str, source_id: str, now: int) -> tuple[set, int]:
        """Staged rows → item_source; returns (item ids to re-materialize, rows seen)."""
        prior = {r["native_id"]: r for r in conn.execute(
            "SELECT native_id,item_id,res_sha,body_sha,raw_sha,status FROM item_source WHERE source_id=?", (source_id,))}
        affected, touched, seen, last = set(), [], 0, ""
        while batch := conn.execute("SELECT native_id,resource,raw FROM sync_stage WHERE run_id=? AND native_id>? "
                                    "ORDER BY native_id LIMIT ?", (run_id, last, BATCH)).fetchall():
            last = batch[-1][0]
            for native_id, resource_z, raw_z in batch:
                seen += 1
                doc = json.loads(zlib.decompress(resource_z))
                body = doc.pop("body", "") or ""
                raw_bytes = zlib.decompress(raw_z)
                prev = prior.get(native_id)
                if prev is not None and prev["status"] == "active" and prev["item_id"] == doc["item_id"] \
                        and prev["body_sha"] == (_sha(body.encode()) if body else None) \
                        and prev["res_sha"] == _sha(canonical_json(doc).encode()):
                    raw_sha = _sha(raw_bytes)
                    if raw_sha != prev["raw_sha"]:
                        put_blob(conn, raw_bytes, raw_sha)
                    touched.append((run_id, now, raw_sha, source_id, native_id))
                    continue
                self._write_source(conn, source_id, native_id, doc, body, raw_bytes, run_id, now)
                affected.add(doc["item_id"])
                if prev is not None:
                    affected.add(prev["item_id"])
        conn.executemany("UPDATE item_source SET seen_run=?,fetched_at=?,raw_sha=? WHERE source_id=? AND native_id=?", touched)
        return affected, seen

    # -- materialization -----------------------------------------------------------------
    def _materialize_many(self, conn, item_ids, now: int, force: bool = False) -> tuple[int, int]:
        ids = sorted(item_ids)
        if not ids:
            return 0, 0
        key = json.dumps(ids)
        winners = {}
        for row in conn.execute("SELECT s.item_id,s.source_id,s.native_id,s.res_sha,s.body_sha,s.has_path,c.priority "
                                "FROM item_source s JOIN catalog_source c USING(source_id) WHERE s.status='active' "
                                "AND (c.enabled=1 OR c.source_id='local') AND s.item_id IN (SELECT value FROM json_each(?))", (key,)):
            rank = (-row["priority"], -row["has_path"], row["source_id"], row["native_id"])
            if row["item_id"] not in winners or rank < winners[row["item_id"]][0]:
                winners[row["item_id"]] = (rank, row)
        olds = {r["item_id"]: dict(r) for r in conn.execute(
            "SELECT item_id,latest_version,status,content_hash FROM catalog_item "
            "WHERE item_id IN (SELECT value FROM json_each(?))", (key,))}
        if force:
            for old in olds.values():
                old["latest_version"] = None
        changed, retired, hashes = 0, 0, set()
        for item_id in ids:
            winner = winners.get(item_id)
            change, removal = self._materialize(conn, item_id, now, winner and winner[1], olds.get(item_id), hashes)
            changed += change
            retired += removal
        self._dedupe(conn, hashes)
        return changed, retired

    def _materialize(self, conn, item_id: str, now: int, winner, old, hashes: set) -> tuple[int, int]:
        if old is not None:
            hashes.add(old["content_hash"])
        if winner is None:
            if old and old["status"] != "deleted":
                conn.execute("UPDATE catalog_item SET status='deleted',listable=0,last_seen=? WHERE item_id=?", (now, item_id))
                self._clear_projections(conn, item_id)
                return 0, 1
            return 0, 0
        doc = json.loads(get_blob(conn, winner["res_sha"]))
        body = get_blob(conn, winner["body_sha"]).decode() if winner["body_sha"] else ""
        resource = Resource.model_validate({**doc, "body": body})
        resource = resource.model_copy(update={"features": extract(resource)})
        # Popularity changes do not force content re-embedding; it is presentation metadata.
        document = resource.model_dump(exclude={"popularity"})
        content_hash = digest({"body": resource.body, "name": resource.name, "summary": resource.summary,
                               "type": resource.type, "manifest": resource.manifest,
                               "install": resource.install, "agents": resource.agents})
        version_id = digest([FEATURE_VERSION, CHUNK_VERSION, content_hash, document])
        hashes.add(content_hash)
        flags, level = assess(resource)
        md, popularity = resource.metadata, resource.popularity
        display = (_text(md.get("author") or resource.manifest.get("author")),
                   resource.version or _text(resource.manifest.get("version")),
                   _count(popularity.get("installs", popularity.get("downloads"))), _count(popularity.get("stars")),
                   _ms(md.get("source_updated_at")) or now, canonical_json(flags), level,
                   canonical_json({"metadata": md, "install": resource.install, "popularity": popularity,
                                   # Raw-byte sha256 of the body (= blob sha) for inventory hash linking.
                                   "body_sha256": winner["body_sha"]}))
        if old and old["latest_version"] == version_id and old["status"] == resource.status:
            conn.execute("UPDATE catalog_item SET author=?,version=?,installs=?,stars=?,updated_at=?,risk=?,risk_level=?,"
                         "metadata=?,last_seen=? WHERE item_id=?", (*display, now, item_id))
            return 0, 0
        pieces = chunks(resource)
        listable = int(resource.status == "active" and resource.type not in UNLISTED_TYPES)
        conn.execute("INSERT INTO catalog_item(item_id,type,name,name_key,summary,url,status,license,agents,language,"
                     "difficulty,official,origin,author,version,installs,stars,updated_at,risk,risk_level,canonical_of,"
                     "listable,body_policy,verification,body_len,latest_version,content_hash,metadata,first_seen,last_seen) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET "
                     "type=excluded.type,name=excluded.name,name_key=excluded.name_key,summary=excluded.summary,url=excluded.url,"
                     "status=excluded.status,license=excluded.license,agents=excluded.agents,language=excluded.language,"
                     "difficulty=excluded.difficulty,official=excluded.official,origin=excluded.origin,author=excluded.author,"
                     "version=excluded.version,installs=excluded.installs,stars=excluded.stars,updated_at=excluded.updated_at,"
                     "risk=excluded.risk,risk_level=excluded.risk_level,canonical_of=NULL,listable=excluded.listable,"
                     "body_policy=excluded.body_policy,verification=excluded.verification,body_len=excluded.body_len,"
                     "latest_version=excluded.latest_version,content_hash=excluded.content_hash,metadata=excluded.metadata,"
                     "last_seen=excluded.last_seen",
                     (item_id, resource.type, resource.name, resource.name.casefold(), resource.summary, resource.url,
                      resource.status, resource.license, canonical_json(resource.agents), resource.language,
                      resource.difficulty, resource.official, "local" if md.get("origin") == "local" else "remote",
                      *display[:7], listable, resource.body_policy, _text(md.get("verification")), len(body),
                      version_id, content_hash, display[7], now, now))
        conn.execute("INSERT INTO item_version VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(version_id) DO UPDATE SET "
                     "created_at=excluded.created_at", (version_id, item_id, content_hash, resource.version, resource.commit_sha,
                                                        winner["res_sha"], winner["body_sha"], len(body), now))
        conn.execute("DELETE FROM item_version WHERE item_id=?1 AND version_id!=?2 AND version_id NOT IN (SELECT version_id "
                     "FROM item_version WHERE item_id=?1 AND version_id!=?2 ORDER BY created_at DESC,rowid DESC LIMIT ?3)",
                     (item_id, version_id, KEEP_VERSIONS - 1))
        self._clear_projections(conn, item_id)
        if resource.status != "active":
            return 1, 1
        conn.executemany("INSERT INTO item_feature VALUES(?,?,?,?,?,?)",
                         [(item_id, f.feature, f.value, f.weight, f.origin, f.evidence) for f in resource.features])
        conn.executemany("INSERT OR IGNORE INTO item_agent VALUES(?,?)", [(agent, item_id) for agent in resource.agents])
        children = sorted(set(resource.components))
        conn.executemany("INSERT INTO item_component VALUES(?,?)", [(item_id, child) for child in children])
        conn.executemany("INSERT OR IGNORE INTO item_relation VALUES(?,?,'depends')", [(item_id, child) for child in children])
        conn.execute("INSERT OR IGNORE INTO item_relation SELECT ?,item_id,'alternative_to' FROM catalog_item WHERE listable=1 "
                     "AND name_key=? AND type=? AND item_id!=? AND content_hash!=? LIMIT 5",
                     (item_id, resource.name.casefold(), resource.type, item_id, content_hash))
        end = int(conn.execute("UPDATE catalog_meta SET value=CAST(value AS INTEGER)+? WHERE key='chunk_seq' "
                               "RETURNING value", (len(pieces),)).fetchone()[0])
        rowids = range(end - len(pieces) + 1, end + 1)
        conn.executemany("INSERT INTO resource_chunk VALUES(?,?,?,?,?,?,?)",
                         [(item_id, c["ordinal"], rowid, c["field"], c["heading"], bytes.fromhex(c["text_hash"]) if c["embed"] else None, c["embed"])
                          for rowid, c in zip(rowids, pieces, strict=True)])
        title = " ".join(lexical_tokens(resource.name))
        conn.executemany("INSERT INTO chunk_fts(rowid,title,content) VALUES(?,?,?)",
                         [(rowid, title if c["ordinal"] == 0 else "", " ".join(lexical_tokens(c["text"])))
                          for rowid, c in zip(rowids, pieces, strict=True)])
        if resource.type == "model":
            self._write_model(conn, item_id, resource, winner["source_id"])
        elif resource.type == "benchmark":
            self._write_benchmark(conn, item_id, resource, winner["source_id"])
        return 1, 0

    @staticmethod
    def _write_model(conn, item_id: str, resource: Resource, source_id: str) -> None:
        md = resource.metadata
        provider = _text(md.get("provider")) or "unknown"
        model_id = _text(md.get("model_id")) or resource.name
        aliases = md.get("aliases") if isinstance(md.get("aliases"), list) else []
        modalities = md.get("modalities") if isinstance(md.get("modalities"), (list, dict)) else []
        conn.execute("INSERT INTO model_info VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (item_id, _text(md.get("canonical_id")) or f"{provider}/{model_id}", provider, model_id,
                      _text(md.get("family")), canonical_json(aliases), _number(md.get("context_window")),
                      _number(md.get("max_output")), _number(md.get("input_per_mtok")), _number(md.get("output_per_mtok")),
                      _number(md.get("cache_read_per_mtok")), _flag(md.get("reasoning")), _flag(md.get("tool_call")),
                      canonical_json(modalities), _text(md.get("knowledge_cutoff")), source_id, canonical_json(resource.manifest)))

    @staticmethod
    def _write_benchmark(conn, item_id: str, resource: Resource, source_id: str) -> None:
        m = resource.manifest
        model_id = _text(m.get("model_id")) or resource.name
        conn.execute("INSERT INTO benchmark_result VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     (item_id, _text(m.get("canonical_model_id")) or model_id, model_id, _text(m.get("effort")),
                      _text(m.get("harness")), _text(m.get("benchmark")) or "unknown", _text(m.get("benchmark_version")),
                      _number(m.get("score")), _text(m.get("unit")), _text(m.get("measured_at")), source_id, canonical_json(m)))

    @staticmethod
    def _clear_projections(conn, item_id: str):
        for table, key in (("resource_chunk", "item_id"), ("item_feature", "item_id"), ("item_agent", "item_id"),
                           ("item_component", "parent_id"), ("model_info", "item_id"), ("benchmark_result", "item_id")):
            conn.execute(f"DELETE FROM {table} WHERE {key}=?", (item_id,))
        conn.execute("DELETE FROM item_relation WHERE a=? AND relation IN ('depends','alternative_to')", (item_id,))

    @staticmethod
    def _dedupe(conn, hashes: set) -> None:
        """Same content hash -> one canonical (official > source priority > earliest); copies are unlisted."""
        if not hashes:
            return
        rows = conn.execute(
            "SELECT i.item_id,i.content_hash,i.status,i.official,i.first_seen,i.type,i.canonical_of,i.listable,"
            "(SELECT max(c.priority) FROM item_source s JOIN catalog_source c USING(source_id) WHERE s.item_id=i.item_id "
            "AND s.status='active' AND (c.enabled=1 OR c.source_id='local')) AS priority FROM catalog_item i "
            "WHERE i.content_hash IN (SELECT value FROM json_each(?))", (json.dumps(sorted(hashes)),)).fetchall()
        groups = defaultdict(list)
        for row in rows:
            groups[row["content_hash"]].append(row)
        updates, relinks = [], []
        for members in groups.values():
            active = sorted((r for r in members if r["status"] == "active"),
                            key=lambda r: (-r["official"], -(r["priority"] or 0), r["first_seen"], r["item_id"]))
            canonical = active[0]["item_id"] if active else None
            for r in members:
                if r["status"] != "active":
                    want = (None, 0)
                elif r["item_id"] == canonical:
                    want = (None, int(r["type"] not in UNLISTED_TYPES))
                else:
                    want = (canonical, 0)
                if (r["canonical_of"], r["listable"]) != want:
                    updates.append((*want, r["item_id"]))
                if r["canonical_of"] != want[0]:
                    relinks.append((r["item_id"], want[0]))
        conn.executemany("UPDATE catalog_item SET canonical_of=?,listable=? WHERE item_id=?", updates)
        for item_id, target in relinks:
            conn.execute("DELETE FROM item_relation WHERE a=? AND relation='duplicate'", (item_id,))
            if target:
                conn.execute("INSERT OR IGNORE INTO item_relation VALUES(?,?,'duplicate')", (item_id, target))

    # -- local items ---------------------------------------------------------------------
    def upsert_local(self, resource: Resource) -> dict:
        """Idempotent by item_id ('local:' + content hash); one transaction, visible immediately."""
        native_id = resource.item_id.removeprefix("local:")
        now = _now()
        with self.writer(), self.connect() as conn:
            self._ensure_local(conn)
            existing = conn.execute("SELECT i.latest_version FROM item_source s JOIN catalog_item i USING(item_id) "
                                    "WHERE s.source_id=? AND s.native_id=? AND s.status='active' AND i.status='active'",
                                    (LOCAL_SOURCE, native_id)).fetchone()
            if existing:
                return {"item_id": resource.item_id, "created": False, "version_id": existing[0]}
            doc = resource.model_dump()
            body = doc.pop("body", "") or ""
            self._write_source(conn, LOCAL_SOURCE, native_id, doc, body, b"{}", "local", now)
            self._materialize_many(conn, {resource.item_id}, now)
            self._bump(conn)
            version = conn.execute("SELECT latest_version FROM catalog_item WHERE item_id=?", (resource.item_id,)).fetchone()
            return {"item_id": resource.item_id, "created": True, "version_id": version[0]}

    def remove_local(self, item_id: str) -> bool:
        with self.writer(), self.connect() as conn:
            cursor = conn.execute("UPDATE item_source SET status='removed' WHERE source_id=? AND item_id=? AND status='active'",
                                  (LOCAL_SOURCE, item_id))
            if not cursor.rowcount:
                return False
            self._materialize_many(conn, {item_id}, _now())
            self._bump(conn)
            return True

    def known_resources(self, source_id: str) -> dict:
        """native_id -> (upstream blob sha | None, Resource, raw) for incremental connectors."""
        result = {}
        with self.reader() as conn:
            for row in conn.execute("SELECT native_id,res_sha,body_sha,raw_sha FROM item_source "
                                    "WHERE source_id=? AND status='active'", (source_id,)).fetchall():
                doc = json.loads(get_blob(conn, row["res_sha"]))
                body = get_blob(conn, row["body_sha"])
                resource = Resource.model_validate({**doc, "body": body.decode() if body else ""})
                md = resource.metadata
                result[row["native_id"]] = (md.get("blob_sha") or md.get("source_blob_sha"), resource,
                                            json.loads(get_blob(conn, row["raw_sha"]) or b"{}"))
        return result

    # -- maintenance and inspection ------------------------------------------------------
    def finish_interrupted(self, run_id: str, error: str | None = None, retry_after: int = 0) -> dict:
        with self.connect() as conn:
            status = "failed" if error else "paused"
            conn.execute("UPDATE sync_run SET status=?,error=? WHERE run_id=?", (status, error, run_id))
            run = conn.execute("SELECT * FROM sync_run WHERE run_id=?", (run_id,)).fetchone()
            if error:
                failures = conn.execute("SELECT failures FROM catalog_source WHERE source_id=?", (run["source_id"],)).fetchone()[0] + 1
                delay = max(retry_after, min(86400, 60 * 2 ** min(failures - 1, 10)))
                conn.execute("UPDATE catalog_source SET failures=?,error=?,next_due_at=? WHERE source_id=?",
                             (failures, error, _now() + delay * 1000, run["source_id"]))
            return dict(run)

    def stats(self) -> dict:
        with self.connect(True) as conn:
            def count(sql):
                return conn.execute(sql).fetchone()[0]
            return {"contract": "catalog-v1", "schema_version": SCHEMA_VERSION,
                    "generation": int(count("SELECT value FROM catalog_meta WHERE key='generation'")),
                    "items": count("SELECT count(*) FROM catalog_item WHERE status='active'"),
                    "listable": count("SELECT count(*) FROM catalog_item WHERE listable=1"),
                    "chunks": count("SELECT count(*) FROM resource_chunk"),
                    "versions": count("SELECT count(*) FROM item_version"),
                    "features": count("SELECT count(*) FROM item_feature"),
                    "blobs": count("SELECT count(*) FROM blob"),
                    "by_type": {r[0]: r[1] for r in conn.execute("SELECT type,count(*) FROM catalog_item WHERE status='active' GROUP BY type")},
                    "embeddings": [{**dict(r), "descriptor": json.loads(r["descriptor"])} for r in conn.execute(
                        "SELECT m.*,(SELECT count(*) FROM resource_chunk c JOIN embedding_cache e ON e.model_key=m.model_key "
                        "AND e.text_hash=c.text_hash WHERE c.embed=1) AS indexed_chunks FROM embedding_model m")]}

    def load_resource(self, conn, doc_sha: str, body_sha: str | None) -> Resource:
        """A stored version as a Resource, with features re-extracted exactly as at publish."""
        body = get_blob(conn, body_sha)
        resource = Resource.model_validate({**json.loads(get_blob(conn, doc_sha)), "body": body.decode() if body else ""})
        return resource.model_copy(update={"features": extract(resource)})

    def chunk_texts(self, conn, item_id: str) -> list[str]:
        """Chunk text by ordinal for the latest version, recomputed (FTS is contentless) and LRU-cached."""
        row = conn.execute("SELECT v.version_id,v.doc_sha,v.body_sha FROM catalog_item i JOIN item_version v "
                           "ON v.version_id=i.latest_version WHERE i.item_id=?", (item_id,)).fetchone()
        if row is None:
            return []
        with self._chunk_lock:
            cached = self._chunk_cache.get(row["version_id"])
        if cached is None:
            cached = [c["text"] for c in chunks(self.load_resource(conn, row["doc_sha"], row["body_sha"]))]
            with self._chunk_lock:
                self._chunk_cache[row["version_id"]] = cached
                while len(self._chunk_cache) > 512:
                    self._chunk_cache.pop(next(iter(self._chunk_cache)))
        return cached

    def detail(self, item_id: str) -> dict | None:
        """Legacy detail shape (resource/version/sources/chunks) plus readme, versions and risk."""
        from .query import get_item
        with self.reader() as conn:
            row = conn.execute("SELECT i.*,v.doc_sha,v.body_sha FROM catalog_item i JOIN item_version v "
                               "ON v.version_id=i.latest_version WHERE i.item_id=?", (item_id,)).fetchone()
            if row is None:
                return None
            resource = self.load_resource(conn, row["doc_sha"], row["body_sha"])
            texts = self.chunk_texts(conn, item_id)
            item = get_item(self, item_id)
            return {"resource": {**resource.model_dump(exclude={"popularity"}), "status": row["status"]},
                    "version_id": row["latest_version"], "content_hash": row["content_hash"],
                    "first_seen": row["first_seen"], "last_seen": row["last_seen"],
                    "sources": item["sources"], "readme": item["readme"], "versions": item["versions"],
                    "risk": {"flags": item["risk"], "level": item["risk_level"], "estimate": True},
                    "chunks": [{"chunk_id": str(r["chunk_rowid"]), "field": r["field"], "heading": r["heading"],
                                "ordinal": r["ordinal"], "start": None, "text": texts[r["ordinal"]]}
                               for r in conn.execute("SELECT * FROM resource_chunk WHERE item_id=? ORDER BY ordinal", (item_id,))]}

    @staticmethod
    def _vacuum_blobs(conn) -> int:
        return conn.execute(
            "DELETE FROM blob WHERE sha NOT IN (SELECT res_sha FROM item_source UNION SELECT body_sha FROM item_source "
            "WHERE body_sha IS NOT NULL UNION SELECT raw_sha FROM item_source UNION SELECT doc_sha FROM item_version "
            "UNION SELECT body_sha FROM item_version WHERE body_sha IS NOT NULL)").rowcount

    def vacuum_blobs(self) -> int:
        with self.writer(), self.connect() as conn:
            return self._vacuum_blobs(conn)

    def rebuild(self):
        """Recompute feature/chunk projections from normalized source records, without network."""
        with self.writer(), self.connect() as conn:
            ids = {r[0] for r in conn.execute("SELECT DISTINCT item_id FROM item_source")}
            changed, _ = self._materialize_many(conn, ids, _now(), force=True)
            self._vacuum_blobs(conn)
            self._bump(conn)
            conn.execute("PRAGMA optimize")
        self._release_free_pages()
        return {"items_checked": len(ids), "changed": changed}

    def _release_free_pages(self) -> None:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            conn.execute("PRAGMA incremental_vacuum").fetchall()
        finally:
            conn.close()

    def verify(self):
        with self.connect(True) as conn:
            def count(sql):
                return conn.execute(sql).fetchone()[0]
            integrity = [r[0] for r in conn.execute("PRAGMA quick_check")]
            foreign_keys = [tuple(r) for r in conn.execute("PRAGMA foreign_key_check")]
            chunk_ids = {r[0] for r in conn.execute("SELECT chunk_rowid FROM resource_chunk")}
            fts_ids = {r[0] for r in conn.execute("SELECT rowid FROM chunk_fts")}
            missing_fts, orphan_fts = len(chunk_ids - fts_ids), len(fts_ids - chunk_ids)
            invalid_vectors = count("SELECT count(*) FROM embedding_cache e JOIN embedding_model m USING(model_key) "
                                    "WHERE e.dimensions!=m.dimensions OR length(e.vector)!=e.dimensions*2")
            invalid_versions = count("SELECT count(*) FROM catalog_item i LEFT JOIN item_version v ON v.version_id=i.latest_version "
                                     "WHERE v.version_id IS NULL OR i.content_hash!=v.content_hash")
            invalid_canonical = count("SELECT count(*) FROM catalog_item i LEFT JOIN catalog_item c ON c.item_id=i.canonical_of "
                                      "WHERE i.canonical_of IS NOT NULL AND (c.item_id IS NULL OR c.canonical_of IS NOT NULL)")
            missing_blobs = count("SELECT count(*) FROM item_version v WHERE NOT EXISTS(SELECT 1 FROM blob WHERE sha=v.doc_sha) "
                                  "OR (v.body_sha IS NOT NULL AND NOT EXISTS(SELECT 1 FROM blob WHERE sha=v.body_sha))")
            invalid_blobs = 0
            for row in conn.execute("SELECT sha,codec,data FROM blob ORDER BY random() LIMIT 200"):
                data = zlib.decompress(row["data"]) if row["codec"] == 1 else bytes(row["data"])
                invalid_blobs += _sha(data) != row["sha"]
            problems = (foreign_keys or missing_fts or orphan_fts or invalid_vectors or invalid_versions
                        or invalid_canonical or missing_blobs or invalid_blobs)
            return {"ok": integrity == ["ok"] and not problems, "sqlite": integrity, "foreign_key_errors": foreign_keys,
                    "missing_fts": missing_fts, "orphan_fts": orphan_fts, "invalid_vectors": invalid_vectors,
                    "invalid_versions": invalid_versions, "invalid_canonical": invalid_canonical,
                    "missing_blobs": missing_blobs, "invalid_blobs": invalid_blobs}

-- Catalog bootstrap (schema v3). Separate database; never applied to orbit.db.
-- Text payloads live once in `blob` (sha256 of the uncompressed bytes, zlib when >=200 B);
-- projections keep only hashes. chunk_fts is contentless: chunk text is recomputed from the
-- version's document + body (deterministic, pinned by CHUNK_VERSION inside version_id).
CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID, STRICT;
INSERT INTO catalog_meta VALUES ('contract', 'catalog-v1'), ('generation', '0'), ('chunk_seq', '0');
-- Rowid table on purpose: multi-KB rows fill WITHOUT ROWID b-tree pages poorly (measured ~3x).
CREATE TABLE blob (
 sha TEXT PRIMARY KEY, codec INTEGER NOT NULL, size INTEGER NOT NULL, data BLOB NOT NULL
) STRICT;
CREATE TABLE catalog_source (
 source_id TEXT PRIMARY KEY, spec TEXT NOT NULL, enabled INTEGER NOT NULL,
 priority INTEGER NOT NULL, revision TEXT, watermark TEXT, completed_at INTEGER,
 next_due_at INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0, error TEXT
) STRICT;
CREATE TABLE sync_run (
 run_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES catalog_source,
 status TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'full', checkpoint TEXT NOT NULL DEFAULT '{}',
 revision TEXT, watermark TEXT, started_at INTEGER NOT NULL, finished_at INTEGER,
 seen INTEGER NOT NULL DEFAULT 0, changed INTEGER NOT NULL DEFAULT 0,
 retired INTEGER NOT NULL DEFAULT 0, error TEXT
) STRICT;
CREATE INDEX sync_source_status ON sync_run(source_id, status, started_at);
-- resource/raw: zlib-compressed canonical JSON.
CREATE TABLE sync_stage (
 run_id TEXT NOT NULL REFERENCES sync_run ON DELETE CASCADE, native_id TEXT NOT NULL,
 resource BLOB NOT NULL, raw BLOB NOT NULL, PRIMARY KEY(run_id, native_id)
) WITHOUT ROWID, STRICT;
CREATE TABLE catalog_item (
 item_id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL, name_key TEXT NOT NULL,
 summary TEXT NOT NULL, url TEXT NOT NULL, status TEXT NOT NULL, license TEXT, agents TEXT NOT NULL,
 language TEXT NOT NULL, difficulty INTEGER NOT NULL, official INTEGER NOT NULL,
 origin TEXT NOT NULL DEFAULT 'remote', author TEXT, version TEXT,
 installs INTEGER NOT NULL DEFAULT 0, stars INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL,
 risk TEXT NOT NULL DEFAULT '[]', risk_level INTEGER NOT NULL DEFAULT 0, canonical_of TEXT,
 listable INTEGER NOT NULL DEFAULT 0, body_policy TEXT NOT NULL, verification TEXT,
 body_len INTEGER NOT NULL DEFAULT 0, latest_version TEXT NOT NULL, content_hash TEXT NOT NULL,
 metadata TEXT NOT NULL, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL
) STRICT;
CREATE INDEX catalog_content ON catalog_item(content_hash);
CREATE INDEX catalog_filter ON catalog_item(status, type, difficulty);
CREATE INDEX ix_list_updated_at ON catalog_item(updated_at DESC, item_id DESC) WHERE listable=1;
CREATE INDEX ix_list_type_updated_at ON catalog_item(type, updated_at DESC, item_id DESC) WHERE listable=1;
CREATE INDEX ix_list_installs ON catalog_item(installs DESC, item_id DESC) WHERE listable=1;
CREATE INDEX ix_list_type_installs ON catalog_item(type, installs DESC, item_id DESC) WHERE listable=1;
CREATE INDEX ix_list_name_key ON catalog_item(name_key DESC, item_id DESC) WHERE listable=1;
CREATE INDEX ix_list_type_name_key ON catalog_item(type, name_key DESC, item_id DESC) WHERE listable=1;
CREATE TABLE item_source (
 source_id TEXT NOT NULL REFERENCES catalog_source, native_id TEXT NOT NULL,
 item_id TEXT NOT NULL, status TEXT NOT NULL, seen_run TEXT NOT NULL, fetched_at INTEGER NOT NULL,
 res_sha TEXT NOT NULL, body_sha TEXT, raw_sha TEXT NOT NULL, has_path INTEGER NOT NULL,
 PRIMARY KEY(source_id, native_id)
) WITHOUT ROWID, STRICT;
CREATE INDEX item_source_identity ON item_source(item_id, status, source_id);
-- doc_sha: winning source Resource without body (features are re-extracted on read).
CREATE TABLE item_version (
 version_id TEXT PRIMARY KEY, item_id TEXT NOT NULL, content_hash TEXT NOT NULL,
 version TEXT, commit_sha TEXT, doc_sha TEXT NOT NULL, body_sha TEXT,
 size INTEGER NOT NULL, created_at INTEGER NOT NULL
) STRICT;
CREATE INDEX item_versions ON item_version(item_id, created_at DESC);
CREATE TABLE item_feature (
 item_id TEXT NOT NULL, feature TEXT NOT NULL, value TEXT NOT NULL, weight REAL NOT NULL,
 origin TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(item_id, feature, value, origin)
) WITHOUT ROWID, STRICT;
CREATE INDEX feature_lookup ON item_feature(feature, value, item_id);
CREATE TABLE item_agent (agent TEXT NOT NULL, item_id TEXT NOT NULL, PRIMARY KEY(agent, item_id)) WITHOUT ROWID, STRICT;
CREATE TABLE item_component (
 parent_id TEXT NOT NULL, child_id TEXT NOT NULL, PRIMARY KEY(parent_id, child_id)
) WITHOUT ROWID, STRICT;
-- relation: duplicate (a is a copy of canonical b) | depends (a bundles b) | alternative_to.
CREATE TABLE item_relation (
 a TEXT NOT NULL, b TEXT NOT NULL, relation TEXT NOT NULL, PRIMARY KEY(a, b, relation)
) WITHOUT ROWID, STRICT;
CREATE INDEX item_relation_reverse ON item_relation(b, relation);
-- Rows describe the item's latest version; embed=1 chunks carry text_hash (vector cache key).
-- chunk_rowid is the FTS rowid (allocated from catalog_meta.chunk_seq, never reused); rowid ->
-- (item, ordinal) is resolved by the in-memory index, so it needs no separate SQL index.
CREATE TABLE resource_chunk (
 item_id TEXT NOT NULL, ordinal INTEGER NOT NULL, chunk_rowid INTEGER NOT NULL, field TEXT NOT NULL,
 heading TEXT NOT NULL, text_hash BLOB, embed INTEGER NOT NULL, PRIMARY KEY(item_id, ordinal)
) WITHOUT ROWID, STRICT;
CREATE VIRTUAL TABLE chunk_fts USING fts5(
 title, content, content='', contentless_delete=1, detail=column,
 tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER chunk_deleted AFTER DELETE ON resource_chunk BEGIN
 DELETE FROM chunk_fts WHERE rowid = old.chunk_rowid;
END;
CREATE TABLE embedding_model (
 model_key INTEGER PRIMARY KEY, model_id TEXT NOT NULL UNIQUE, dimensions INTEGER NOT NULL,
 descriptor TEXT NOT NULL, created_at INTEGER NOT NULL
) STRICT;
-- vector: little-endian float16, L2-normalised before quantisation; text_hash: 16-byte chunk digest.
-- Rowid table: rows arrive in random text_hash order, which leaves a WITHOUT ROWID b-tree ~30% empty.
CREATE TABLE embedding_cache (
 model_key INTEGER NOT NULL REFERENCES embedding_model, text_hash BLOB NOT NULL,
 dimensions INTEGER NOT NULL, vector BLOB NOT NULL,
 PRIMARY KEY(model_key, text_hash), CHECK(length(vector) = dimensions * 2)
) STRICT;
CREATE TABLE model_info (
 item_id TEXT PRIMARY KEY REFERENCES catalog_item, canonical_id TEXT NOT NULL,
 provider TEXT NOT NULL, model_id TEXT NOT NULL, family TEXT, aliases TEXT NOT NULL,
 context_window INTEGER, max_output INTEGER, input_per_mtok REAL, output_per_mtok REAL,
 cache_read_per_mtok REAL, reasoning INTEGER, tool_call INTEGER, modalities TEXT NOT NULL,
 knowledge_cutoff TEXT, source_id TEXT, specification TEXT NOT NULL
) STRICT;
CREATE INDEX model_canonical ON model_info(canonical_id);
CREATE TABLE benchmark_result (
 item_id TEXT PRIMARY KEY REFERENCES catalog_item, canonical_model_id TEXT NOT NULL,
 model_id TEXT NOT NULL, effort TEXT, harness TEXT, benchmark TEXT NOT NULL,
 benchmark_version TEXT, score REAL, unit TEXT, measured_at TEXT, source_id TEXT,
 result TEXT NOT NULL
) STRICT;
CREATE INDEX benchmark_model ON benchmark_result(canonical_model_id, benchmark);

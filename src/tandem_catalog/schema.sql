-- Owned only by tandem_catalog. Session/analysis databases are never opened here.
CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
INSERT INTO catalog_meta VALUES ('contract', 'catalog-v1'), ('generation', '0');
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
CREATE TABLE sync_stage (
 run_id TEXT NOT NULL REFERENCES sync_run ON DELETE CASCADE, native_id TEXT NOT NULL,
 resource TEXT NOT NULL, raw TEXT NOT NULL, PRIMARY KEY(run_id, native_id)
) STRICT;
CREATE TABLE catalog_item (
 item_id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL, summary TEXT NOT NULL,
 url TEXT NOT NULL, status TEXT NOT NULL, license TEXT, agents TEXT NOT NULL,
 language TEXT NOT NULL, difficulty INTEGER NOT NULL, official INTEGER NOT NULL,
 latest_version TEXT NOT NULL, content_hash TEXT NOT NULL, metadata TEXT NOT NULL,
 first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL
) STRICT;
CREATE INDEX catalog_filter ON catalog_item(status, type, difficulty);
CREATE INDEX catalog_content ON catalog_item(content_hash);
CREATE TABLE item_source (
 source_id TEXT NOT NULL REFERENCES catalog_source, native_id TEXT NOT NULL,
 item_id TEXT NOT NULL, resource TEXT NOT NULL, raw TEXT NOT NULL,
 status TEXT NOT NULL, seen_run TEXT NOT NULL, fetched_at INTEGER NOT NULL,
 PRIMARY KEY(source_id, native_id)
) STRICT;
CREATE INDEX item_source_identity ON item_source(item_id, status, source_id);
CREATE TABLE item_version (
 version_id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES catalog_item,
 content_hash TEXT NOT NULL, document TEXT NOT NULL, created_at INTEGER NOT NULL
) STRICT;
CREATE INDEX item_versions ON item_version(item_id, created_at);
CREATE TABLE item_feature (
 item_id TEXT NOT NULL REFERENCES catalog_item ON DELETE CASCADE,
 feature TEXT NOT NULL, value TEXT NOT NULL, weight REAL NOT NULL,
 origin TEXT NOT NULL, evidence TEXT NOT NULL,
 PRIMARY KEY(item_id, feature, value, origin)
) STRICT;
CREATE INDEX feature_lookup ON item_feature(feature, value, item_id);
CREATE TABLE item_component (
 parent_id TEXT NOT NULL REFERENCES catalog_item ON DELETE CASCADE,
 child_id TEXT NOT NULL, PRIMARY KEY(parent_id, child_id)
) STRICT;
CREATE TABLE resource_chunk (
 chunk_id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES catalog_item ON DELETE CASCADE,
 version_id TEXT NOT NULL REFERENCES item_version,
 field TEXT NOT NULL, heading TEXT NOT NULL, ordinal INTEGER NOT NULL,
 start INTEGER NOT NULL, text TEXT NOT NULL, text_hash TEXT NOT NULL
) STRICT;
CREATE INDEX chunks_item ON resource_chunk(item_id, version_id);
CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_id UNINDEXED, item_id UNINDEXED, title, content);
CREATE TRIGGER chunk_deleted AFTER DELETE ON resource_chunk BEGIN
 DELETE FROM chunk_fts WHERE rowid = old.rowid;
END;
CREATE TABLE embedding_model (
 model_id TEXT PRIMARY KEY, dimensions INTEGER NOT NULL, descriptor TEXT NOT NULL,
 created_at INTEGER NOT NULL
) STRICT;
CREATE TABLE chunk_embedding (
 chunk_id TEXT NOT NULL REFERENCES resource_chunk ON DELETE CASCADE,
 model_id TEXT NOT NULL REFERENCES embedding_model, text_hash TEXT NOT NULL,
 dimensions INTEGER NOT NULL, vector BLOB NOT NULL, created_at INTEGER NOT NULL,
 PRIMARY KEY(chunk_id, model_id), CHECK(length(vector) = dimensions * 4)
) STRICT;
CREATE INDEX embedding_space ON chunk_embedding(model_id, chunk_id);
CREATE TABLE embedding_cache (
 model_id TEXT NOT NULL REFERENCES embedding_model, text_hash TEXT NOT NULL,
 dimensions INTEGER NOT NULL, vector BLOB NOT NULL,
 PRIMARY KEY(model_id, text_hash), CHECK(length(vector) = dimensions * 4)
) STRICT;
CREATE INDEX embedding_text_reuse ON embedding_cache(text_hash, model_id);
CREATE TABLE model_info (
 item_id TEXT PRIMARY KEY REFERENCES catalog_item ON DELETE CASCADE,
 provider TEXT NOT NULL, model_id TEXT NOT NULL, specification TEXT NOT NULL
) STRICT;
CREATE TABLE benchmark_result (
 item_id TEXT PRIMARY KEY REFERENCES catalog_item ON DELETE CASCADE,
 model_id TEXT NOT NULL, effort TEXT, harness TEXT, benchmark TEXT NOT NULL,
 benchmark_version TEXT, measured_at TEXT, result TEXT NOT NULL
) STRICT;

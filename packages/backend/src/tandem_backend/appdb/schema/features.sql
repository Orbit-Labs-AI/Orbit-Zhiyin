-- features module: vocabulary ids, materialized session features, profile cache,
-- inventory links and component size cache. All derivable; safe to drop and rebuild.
CREATE TABLE IF NOT EXISTS feat_vocab (
  fid INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE
) STRICT;
CREATE TABLE IF NOT EXISTS sess_feat (
  session_uid TEXT NOT NULL, fid INTEGER NOT NULL, n INTEGER NOT NULL,
  PRIMARY KEY(session_uid, fid)
) STRICT, WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS sess_feat_fid ON sess_feat(fid, session_uid);
CREATE TABLE IF NOT EXISTS sess_feat_state (
  session_uid TEXT PRIMARY KEY, sig TEXT NOT NULL, updated_at INTEGER NOT NULL
) STRICT, WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS feat_profile (
  scope_hash TEXT, data_rev INTEGER, inventory_rev INTEGER, catalog_rev TEXT, vocab TEXT,
  scope TEXT NOT NULL, body BLOB NOT NULL, centroid BLOB, n_sessions INTEGER NOT NULL,
  computed_at INTEGER NOT NULL, build_ms INTEGER NOT NULL, accessed_at INTEGER NOT NULL,
  PRIMARY KEY(scope_hash, data_rev, inventory_rev, catalog_rev, vocab)
) STRICT, WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS inv_link (
  inv_id TEXT PRIMARY KEY, catalog_item_id TEXT NOT NULL, method TEXT NOT NULL,
  confidence REAL NOT NULL, catalog_rev TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE TABLE IF NOT EXISTS inv_size (
  content_hash TEXT PRIMARY KEY, tokens_est INTEGER, basis TEXT, measured_at INTEGER
) STRICT, WITHOUT ROWID;
-- Skill / MCP usage aggregate per data revision, project scope and UTC day (features.linked).
CREATE TABLE IF NOT EXISTS inv_usage (
  data_rev TEXT NOT NULL, scope TEXT NOT NULL, day INTEGER NOT NULL, body TEXT NOT NULL,
  computed_at INTEGER NOT NULL, PRIMARY KEY(data_rev, scope, day)
) STRICT, WITHOUT ROWID;

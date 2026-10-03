-- export: fixed-caliber snapshots of reports, share cards and other frozen views (AN-14).
-- created_at is epoch milliseconds; scope / payload are compact JSON. Newest 50 per kind kept.
CREATE TABLE IF NOT EXISTS report_snapshot (
  snapshot_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('report','share_card','persona_fixed','rec_top')),
  scope_hash TEXT NOT NULL,
  scope TEXT NOT NULL CHECK(json_valid(scope)),
  created_at INTEGER NOT NULL,
  rules_digest TEXT,
  payload TEXT NOT NULL CHECK(json_valid(payload))
) STRICT;
CREATE INDEX IF NOT EXISTS report_snapshot_kind ON report_snapshot(kind, scope_hash, created_at DESC);

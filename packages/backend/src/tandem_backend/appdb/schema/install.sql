-- install: plans (re-buildable, swept after 30 days), the append-only ledger and per-install
-- lifecycle state. inv_id/catalog_item_id link a written target to its inventory item and
-- catalog entry (features' linked inventory reads them as method=ledger); InstallService adds
-- them to ledgers created before they existed.
-- ts / *_at columns are epoch milliseconds; JSON columns are compact UTF-8.
CREATE TABLE IF NOT EXISTS install_plan (
  plan_id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_id TEXT,
  spec TEXT NOT NULL,
  spec_hash TEXT NOT NULL,
  targets TEXT NOT NULL,
  agents TEXT NOT NULL,
  scope TEXT NOT NULL,
  project_path TEXT,
  status TEXT NOT NULL DEFAULT 'ready',
  warnings TEXT,
  created_at INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS install_plan_source ON install_plan(source_type, source_id);

CREATE TABLE IF NOT EXISTS install_ledger (
  entry_id TEXT PRIMARY KEY,
  ts INTEGER NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  install_id TEXT,
  candidate_id TEXT,
  plan_id TEXT,
  target_idx INTEGER,
  target_agent TEXT,
  path TEXT,
  op TEXT,
  before_hash TEXT,
  after_hash TEXT,
  backup_path TEXT,
  created_file INTEGER,
  applied TEXT,
  blob_ref TEXT,
  evidence_refs TEXT,
  tracking_id TEXT,
  note TEXT,
  inv_id TEXT,
  catalog_item_id TEXT
) STRICT;
CREATE INDEX IF NOT EXISTS install_ledger_install ON install_ledger(install_id, ts);
CREATE INDEX IF NOT EXISTS install_ledger_ts ON install_ledger(ts DESC);
CREATE TRIGGER IF NOT EXISTS install_ledger_no_update BEFORE UPDATE ON install_ledger
BEGIN SELECT RAISE(ABORT, 'install_ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS install_ledger_no_delete BEFORE DELETE ON install_ledger
BEGIN SELECT RAISE(ABORT, 'install_ledger is append-only'); END;

CREATE TABLE IF NOT EXISTS install_state (
  install_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL,
  candidate_id TEXT,
  source_type TEXT NOT NULL,
  source_id TEXT,
  title TEXT NOT NULL,
  kind TEXT NOT NULL,
  agents TEXT NOT NULL,
  scope TEXT NOT NULL,
  preview_digest TEXT NOT NULL,
  state TEXT NOT NULL,
  installed_at INTEGER NOT NULL,
  observe_until INTEGER,
  last_triggered_at INTEGER,
  pinned INTEGER NOT NULL DEFAULT 0,
  archived_at INTEGER,
  reverted_at INTEGER,
  tracking_id TEXT,
  risk_level TEXT
) STRICT;
CREATE INDEX IF NOT EXISTS install_state_source ON install_state(source_type, source_id, state);

-- Recommendation runs, exposures, labels, tracking and outcomes (recommend module).
-- Idempotent: applied on every open of app.db when the file digest changes.
CREATE TABLE IF NOT EXISTS rec_run (
  run_id TEXT PRIMARY KEY, scope_hash TEXT NOT NULL, scope TEXT NOT NULL,
  inputs_digest TEXT NOT NULL, data_rev TEXT, inventory_rev INTEGER,
  engine_version TEXT NOT NULL, kb_version TEXT, catalog_generation INTEGER, memory_rev TEXT,
  status TEXT NOT NULL, problems TEXT NOT NULL DEFAULT '[]', routes TEXT NOT NULL DEFAULT '{}',
  diagnostics TEXT NOT NULL DEFAULT '[]', created_at INTEGER NOT NULL, duration_ms INTEGER,
  pinned INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE UNIQUE INDEX IF NOT EXISTS rec_run_digest ON rec_run(scope_hash, inputs_digest);
CREATE INDEX IF NOT EXISTS rec_run_scope ON rec_run(scope_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS rec_candidate (
  candidate_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, rec_key TEXT NOT NULL, problem_key TEXT,
  kind TEXT NOT NULL, dim TEXT NOT NULL, level INTEGER, audience_min INTEGER,
  title TEXT NOT NULL, rank INTEGER, priority REAL NOT NULL DEFAULT 0, passed INTEGER NOT NULL,
  card TEXT NOT NULL, created_at INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS rec_candidate_run ON rec_candidate(run_id, passed, rank);
CREATE INDEX IF NOT EXISTS rec_candidate_key ON rec_candidate(rec_key);

CREATE TABLE IF NOT EXISTS rec_state (
  rec_key TEXT PRIMARY KEY, status TEXT NOT NULL, snooze_until INTEGER,
  shown_count INTEGER NOT NULL DEFAULT 0, first_shown_at INTEGER, last_shown_at INTEGER,
  last_evidence REAL, install_id TEXT, updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS rec_exposure (
  exposure_id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, run_id TEXT, candidate_id TEXT,
  rec_key TEXT NOT NULL,
  surface TEXT NOT NULL CHECK(surface IN ('A7','A1','lite','menubar','widget','palette','ask','hud')),
  position INTEGER, priority REAL,
  action TEXT NOT NULL CHECK(action IN ('view','open','preview','copy','install','dismiss','snooze'))
) STRICT;
CREATE INDEX IF NOT EXISTS rec_exposure_key ON rec_exposure(rec_key, ts);
CREATE INDEX IF NOT EXISTS rec_exposure_surface ON rec_exposure(surface, ts);

CREATE TABLE IF NOT EXISTS label (
  label_id TEXT PRIMARY KEY,
  target_kind TEXT NOT NULL CHECK(target_kind IN ('candidate','problem','profile','signal',
    'key_moment','facet','narrative','reader_case')),
  target_id TEXT NOT NULL, rec_key TEXT, labeler TEXT NOT NULL DEFAULT 'user',
  label TEXT NOT NULL CHECK(label IN ('not_applicable','snooze','useful','not_useful','not_me',
    'inaccurate','confirm','mute')),
  reason TEXT CHECK(reason IS NULL OR reason IN ('has_equivalent','dont_want','wrong_diagnosis',
    'env_mismatch','other','never_triggered','reverted')),
  ts INTEGER NOT NULL, undone_at INTEGER
) STRICT;
CREATE INDEX IF NOT EXISTS label_target ON label(target_kind, target_id, ts);
CREATE INDEX IF NOT EXISTS label_rec_key ON label(rec_key);

CREATE TABLE IF NOT EXISTS rec_top (
  surface TEXT, scope_hash TEXT, run_id TEXT NOT NULL, rec_keys TEXT NOT NULL,
  created_at INTEGER NOT NULL, PRIMARY KEY(surface, scope_hash)
) STRICT;

CREATE TABLE IF NOT EXISTS tracking (
  tracking_id TEXT PRIMARY KEY, install_id TEXT NOT NULL UNIQUE, candidate_id TEXT NOT NULL,
  rec_key TEXT NOT NULL, problem_type TEXT, problem_key TEXT, kind TEXT NOT NULL,
  registered_at INTEGER NOT NULL, baseline_from INTEGER NOT NULL, baseline_to INTEGER NOT NULL,
  follow_days INTEGER NOT NULL DEFAULT 7, extend_days INTEGER NOT NULL DEFAULT 28,
  scope_filter TEXT NOT NULL DEFAULT '{}', metrics TEXT NOT NULL,
  min_sessions INTEGER NOT NULL DEFAULT 5, effect_status TEXT NOT NULL DEFAULT 'tracking',
  reverted_at INTEGER
) STRICT;

CREATE TABLE IF NOT EXISTS rec_outcome (
  install_id TEXT, window TEXT CHECK(window IN ('7d','28d')), metric TEXT,
  layer TEXT CHECK(layer IN ('triggered','mechanical','behavioral','guardrail')),
  before REAL, after REAL, lo REAL, hi REAL, n_before INTEGER, n_after INTEGER,
  status TEXT CHECK(status IN ('ok','insufficient','guardrail_hit')), computed_at INTEGER,
  PRIMARY KEY(install_id, window, metric)
) STRICT;

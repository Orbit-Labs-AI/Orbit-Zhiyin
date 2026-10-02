-- platform: local, opt-in telemetry rollups, settings, maintenance log, storage reports.
-- ts columns are epoch milliseconds; tags is a compact sorted JSON object.
CREATE TABLE IF NOT EXISTS platform_kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS metric_minute (
  ts INTEGER NOT NULL,
  name TEXT NOT NULL,
  tags TEXT NOT NULL,
  n INTEGER NOT NULL,
  sum REAL NOT NULL,
  min REAL NOT NULL,
  max REAL NOT NULL,
  buckets TEXT,
  PRIMARY KEY (name, tags, ts)
) WITHOUT ROWID, STRICT;
CREATE INDEX IF NOT EXISTS metric_minute_ts ON metric_minute(ts);

CREATE TABLE IF NOT EXISTS metric_hour (
  ts INTEGER NOT NULL,
  name TEXT NOT NULL,
  tags TEXT NOT NULL,
  n INTEGER NOT NULL,
  sum REAL NOT NULL,
  min REAL NOT NULL,
  max REAL NOT NULL,
  buckets TEXT,
  PRIMARY KEY (name, tags, ts)
) WITHOUT ROWID, STRICT;
CREATE INDEX IF NOT EXISTS metric_hour_ts ON metric_hour(ts);

CREATE TABLE IF NOT EXISTS maintenance_run (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task TEXT NOT NULL,
  started_at INTEGER NOT NULL,
  ms INTEGER NOT NULL,
  ok INTEGER NOT NULL,
  detail TEXT NOT NULL DEFAULT '{}'
) STRICT;
CREATE INDEX IF NOT EXISTS maintenance_run_task ON maintenance_run(task, id DESC);

CREATE TABLE IF NOT EXISTS storage_report (
  ts INTEGER PRIMARY KEY,
  body TEXT NOT NULL
) STRICT;

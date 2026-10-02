-- Derived analysis history lives in analysis.sqlite, never in the canonical fact database.
CREATE TABLE IF NOT EXISTS analysis_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    analysis_digest TEXT,
    schema_version TEXT,
    json_bytes INTEGER NOT NULL CHECK(json_bytes >= 0),
    payload BLOB NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_run (
    run_id TEXT PRIMARY KEY,
    engine TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    snapshot_id TEXT REFERENCES analysis_snapshot(snapshot_id),
    error_type TEXT,
    error_message TEXT,
    CHECK((status = 'completed' AND snapshot_id IS NOT NULL AND finished_at IS NOT NULL)
          OR (status = 'failed' AND error_type IS NOT NULL AND finished_at IS NOT NULL)
          OR (status = 'running' AND snapshot_id IS NULL AND finished_at IS NULL))
);
CREATE INDEX IF NOT EXISTS analysis_run_started ON analysis_run(started_at DESC, run_id);
CREATE INDEX IF NOT EXISTS analysis_run_engine_status ON analysis_run(engine, status, started_at DESC);

-- v2: reusable derived results. Everything here can be deleted and recomputed from orbit.db.
-- Runs remember which cached request/input they answered; v1 rows keep NULL keys.
ALTER TABLE analysis_run ADD COLUMN request_key TEXT;
ALTER TABLE analysis_run ADD COLUMN input_fp TEXT;
ALTER TABLE analysis_run ADD COLUMN cache_hit INTEGER NOT NULL DEFAULT 0 CHECK(cache_hit IN (0, 1));
CREATE INDEX IF NOT EXISTS analysis_run_cache
    ON analysis_run(engine, request_key, input_fp, status, started_at DESC);

-- One materialized session row per root session, valid only for the same tree fingerprint.
CREATE TABLE IF NOT EXISTS session_result (
    root_session_uid TEXT NOT NULL,
    scope_class TEXT NOT NULL,
    algo_version TEXT NOT NULL,
    tree_fp TEXT NOT NULL,
    payload BLOB NOT NULL,
    json_bytes INTEGER NOT NULL CHECK(json_bytes >= 0),
    sha256 TEXT NOT NULL,
    computed_at INTEGER NOT NULL,
    PRIMARY KEY(root_session_uid, scope_class, algo_version)
);

-- One cached API section per request and input fingerprint; read without decoding others.
CREATE TABLE IF NOT EXISTS analysis_section (
    request_key TEXT NOT NULL,
    input_fp TEXT NOT NULL,
    section TEXT NOT NULL,
    payload BLOB NOT NULL,
    json_bytes INTEGER NOT NULL CHECK(json_bytes >= 0),
    sha256 TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    last_hit_at INTEGER NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0 CHECK(hits >= 0),
    PRIMARY KEY(request_key, input_fp, section)
);
CREATE INDEX IF NOT EXISTS analysis_section_last_hit ON analysis_section(last_hit_at);

-- Large arrays of a cached section, stored one row each for LIMIT/OFFSET paging.
CREATE TABLE IF NOT EXISTS analysis_row (
    request_key TEXT NOT NULL,
    input_fp TEXT NOT NULL,
    section TEXT NOT NULL,
    idx INTEGER NOT NULL CHECK(idx >= 0),
    row_key TEXT,
    payload BLOB NOT NULL,
    json_bytes INTEGER NOT NULL CHECK(json_bytes >= 0),
    sha256 TEXT NOT NULL,
    PRIMARY KEY(request_key, input_fp, section, idx),
    FOREIGN KEY(request_key, input_fp, section)
        REFERENCES analysis_section(request_key, input_fp, section) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS analysis_row_key ON analysis_row(request_key, input_fp, section, row_key);

-- Sessions the user removed from every analysis (AN-16.1); facts stay in orbit.db.
CREATE TABLE IF NOT EXISTS session_exclusion (
    session_uid TEXT PRIMARY KEY,
    reason TEXT,
    created_at INTEGER NOT NULL
);

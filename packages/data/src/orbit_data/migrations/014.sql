-- Cost and failure evidence the reducer previously dropped. Values are filled only by a
-- rebuild (REDUCER_VERSION 1.8.0) from evidence. NULL means "not reported", never zero.
ALTER TABLE model_call ADD COLUMN cache_write_1h_tokens INTEGER
  CHECK(cache_write_1h_tokens >= 0);
ALTER TABLE model_call ADD COLUMN service_tier TEXT;
ALTER TABLE tool_call ADD COLUMN failure_kind TEXT CHECK(failure_kind IS NULL OR failure_kind IN
  ('permission_denied','interrupted','nonzero_exit','harness_error'));
-- One row per file a tool call names. op is what the arguments state (patch headers,
-- change kinds). quality is 'reported' when stated, 'missing' when only the path is known.
CREATE TABLE IF NOT EXISTS tool_call_file (
  call_uid TEXT NOT NULL REFERENCES tool_call, session_uid TEXT NOT NULL REFERENCES session,
  path TEXT NOT NULL,
  op TEXT NOT NULL CHECK(op IN ('add','update','delete','move','unknown')),
  quality TEXT NOT NULL CHECK(quality IN ('reported','missing')),
  PRIMARY KEY(call_uid, path),
  CHECK((op = 'unknown') = (quality = 'missing'))
) STRICT;
CREATE INDEX IF NOT EXISTS tool_call_file_by_session ON tool_call_file(session_uid);
CREATE INDEX IF NOT EXISTS tool_call_file_by_path ON tool_call_file(path);

CREATE TABLE source (
  source_id TEXT PRIMARY KEY, agent TEXT NOT NULL, root_path TEXT NOT NULL UNIQUE,
  label TEXT, enabled INTEGER NOT NULL DEFAULT 1, discovered_at INTEGER NOT NULL
) STRICT;
CREATE TABLE source_file (
  file_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source, path TEXT NOT NULL,
  role TEXT NOT NULL, format TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0,
  dev TEXT, inode TEXT, size INTEGER NOT NULL DEFAULT 0, mtime_ns TEXT,
  head_sha256 TEXT, head_len INTEGER NOT NULL DEFAULT 0, tail_sha256 TEXT,
  watermark TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'active',
  last_scan_at INTEGER, UNIQUE(source_id, path)
) STRICT;
CREATE TABLE archive_chunk (
  file_id TEXT NOT NULL REFERENCES source_file, generation INTEGER NOT NULL,
  offset INTEGER NOT NULL, byte_len INTEGER NOT NULL, sha256 TEXT NOT NULL, path TEXT NOT NULL,
  PRIMARY KEY(file_id, generation, offset)
) STRICT;
CREATE TABLE raw_record (
  record_uid TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES source_file,
  generation INTEGER NOT NULL, line_no INTEGER NOT NULL, ordinal INTEGER NOT NULL,
  byte_offset INTEGER NOT NULL, byte_len INTEGER NOT NULL, sha256 TEXT NOT NULL,
  native_type TEXT NOT NULL, harness_version TEXT, ts INTEGER, session_uid TEXT,
  turn_native_id TEXT, body TEXT, disposition TEXT NOT NULL DEFAULT 'unparsed'
    CHECK(disposition IN ('mapped','folded','replayed','duplicate','ignored','unparsed')),
  ref_event_uid TEXT, note TEXT, UNIQUE(file_id,generation,line_no)
) STRICT;
CREATE INDEX raw_by_session ON raw_record(session_uid, file_id, generation, ordinal);
CREATE TABLE project (
  project_id TEXT PRIMARY KEY, key_type TEXT NOT NULL, key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL, git_remote TEXT, paths TEXT NOT NULL DEFAULT '[]'
) STRICT;
CREATE TABLE session (
  session_uid TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source, native_id TEXT NOT NULL,
  kind TEXT NOT NULL, parent_uid TEXT, root_uid TEXT, depth INTEGER NOT NULL DEFAULT 0,
  forked_from TEXT, imported_from TEXT, project_id TEXT REFERENCES project,
  cwd TEXT, git_branch TEXT, git_sha TEXT, client TEXT, harness_version TEXT,
  title TEXT, title_source TEXT, started_at INTEGER, ended_at INTEGER, status TEXT,
  timezone TEXT, model_raw TEXT, effort_raw TEXT, metadata TEXT NOT NULL DEFAULT '{}'
) STRICT;
CREATE TABLE event (
  event_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL REFERENCES session, seq INTEGER NOT NULL,
  ts INTEGER NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, turn_uid TEXT, parent_uid TEXT,
  call_id TEXT, text TEXT, text_truncated INTEGER NOT NULL DEFAULT 0,
  attrs TEXT NOT NULL DEFAULT '{}', ext TEXT NOT NULL DEFAULT '{}',
  record_uid TEXT NOT NULL REFERENCES raw_record, native_id TEXT
) STRICT;
CREATE INDEX event_by_session ON event(session_uid, seq);
CREATE INDEX event_by_call ON event(session_uid, call_id);
CREATE VIRTUAL TABLE event_fts USING fts5(event_uid UNINDEXED, text);
CREATE TRIGGER event_fts_insert AFTER INSERT ON event BEGIN
  INSERT INTO event_fts(event_uid,text) VALUES(new.event_uid,new.text);
END;
CREATE TRIGGER event_fts_delete AFTER DELETE ON event BEGIN
  DELETE FROM event_fts WHERE event_uid=old.event_uid;
END;
CREATE TABLE turn (
  turn_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL REFERENCES session, idx INTEGER NOT NULL,
  trigger TEXT, status TEXT, started_at INTEGER, ended_at INTEGER,
  first_event_uid TEXT, last_event_uid TEXT
) STRICT;
CREATE TABLE tool_call (
  call_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL REFERENCES session, turn_uid TEXT,
  call_event_uid TEXT, result_event_uid TEXT, name_raw TEXT NOT NULL, kind TEXT NOT NULL,
  mcp_server TEXT, mcp_tool TEXT, command_head TEXT, files TEXT, status TEXT, exit_code INTEGER,
  started_at INTEGER, ended_at INTEGER, duration_ms INTEGER, approval TEXT,
  is_wrapper INTEGER NOT NULL DEFAULT 0, attribution TEXT
) STRICT;
CREATE TABLE model_call (
  call_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL REFERENCES session, turn_uid TEXT,
  request_id TEXT, provider TEXT, model_raw TEXT, model_id TEXT, effort_raw TEXT, effort_rank INTEGER,
  purpose TEXT, input_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
  output_tokens INTEGER, reasoning_tokens INTEGER, cost_usd REAL, cost_source TEXT,
  latency_ms INTEGER, ttft_ms INTEGER, ts INTEGER, estimated INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE TABLE dirty_session (session_uid TEXT PRIMARY KEY) STRICT;
CREATE TABLE format_fingerprint (
  source_id TEXT NOT NULL, harness_version TEXT NOT NULL, native_type TEXT NOT NULL,
  fingerprint TEXT NOT NULL, keys TEXT NOT NULL, first_seen INTEGER NOT NULL,
  PRIMARY KEY(source_id,harness_version,native_type,fingerprint)
) STRICT;
CREATE TABLE diagnostic (
  diagnostic_uid TEXT PRIMARY KEY, source_id TEXT NOT NULL, file_id TEXT, record_uid TEXT,
  code TEXT NOT NULL, message TEXT NOT NULL, seen_at INTEGER NOT NULL
) STRICT;
CREATE VIEW current_record AS
  SELECT r.* FROM raw_record r JOIN source_file f USING(file_id) WHERE r.generation=f.generation;
CREATE VIEW main_model_usage AS
  SELECT m.*,s.project_id,COALESCE(s.root_uid,s.session_uid) AS root_session_uid
  FROM model_call m JOIN session s USING(session_uid)
  LEFT JOIN session root ON root.session_uid=s.root_uid
  WHERE s.kind='main' OR (s.kind='subagent' AND root.kind='main');

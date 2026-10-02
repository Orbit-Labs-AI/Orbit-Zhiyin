-- Analysis input v1: L2/L3 can be rebuilt from the retained L1 cache and L0 manifests.
DROP TRIGGER event_fts_insert;
DROP TRIGGER event_fts_delete;
DELETE FROM event_fts;
DELETE FROM tool_call;
DELETE FROM model_call;
DELETE FROM turn;
DROP TABLE event;
CREATE TABLE event (
  event_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL REFERENCES session, seq INTEGER NOT NULL,
  ts INTEGER, kind TEXT NOT NULL, actor TEXT NOT NULL, turn_uid TEXT, parent_uid TEXT,
  call_id TEXT, text TEXT, text_truncated INTEGER NOT NULL DEFAULT 0,
  attrs TEXT NOT NULL DEFAULT '{}', ext TEXT NOT NULL DEFAULT '{}',
  record_uid TEXT NOT NULL REFERENCES raw_record, native_id TEXT,
  native_key TEXT NOT NULL, event_path TEXT NOT NULL,
  contract_version INTEGER NOT NULL DEFAULT 1, mapper_version TEXT NOT NULL,
  UNIQUE(session_uid,seq),
  CHECK(json_valid(attrs) AND json_valid(ext) AND json_valid(native_key)),
  CHECK((ts IS NULL AND json_extract(attrs,'$.time.quality')='missing') OR
    (ts IS NOT NULL AND json_extract(attrs,'$.time.quality') IN ('reported','estimated')))
) STRICT;
CREATE INDEX event_by_session ON event(session_uid,seq);
CREATE INDEX event_by_call ON event(session_uid,call_id);
CREATE TRIGGER event_fts_insert AFTER INSERT ON event BEGIN
  INSERT INTO event_fts(event_uid,text) VALUES(new.event_uid,new.text);
END;
CREATE TRIGGER event_fts_delete AFTER DELETE ON event BEGIN
  DELETE FROM event_fts WHERE event_uid=old.event_uid;
END;
CREATE TABLE record_event (
  record_uid TEXT NOT NULL REFERENCES raw_record, event_uid TEXT NOT NULL REFERENCES event,
  relation TEXT NOT NULL CHECK(relation IN ('mapped','folded','replayed','duplicate')),
  PRIMARY KEY(record_uid,event_uid)
) STRICT;
CREATE TABLE event_context (
  event_uid TEXT PRIMARY KEY REFERENCES event, project_id TEXT REFERENCES project,
  cwd TEXT, provider TEXT, model_raw TEXT, effort_raw TEXT
) STRICT;
ALTER TABLE session ADD COLUMN timezone_source TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE session ADD COLUMN spawn_call_uid TEXT;
ALTER TABLE session ADD COLUMN lineage_unresolved INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tool_call ADD COLUMN duration_source TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE tool_call ADD COLUMN duration_quality TEXT NOT NULL DEFAULT 'missing';
ALTER TABLE tool_call ADD COLUMN status_scope TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE tool_call ADD COLUMN argument_digest TEXT;
ALTER TABLE tool_call ADD COLUMN approval_wait_ms INTEGER;
ALTER TABLE tool_call ADD COLUMN error_class TEXT;
ALTER TABLE tool_call ADD COLUMN skill TEXT;
ALTER TABLE tool_call ADD COLUMN subagent_session_uid TEXT;
ALTER TABLE model_call ADD COLUMN usage_scope TEXT NOT NULL DEFAULT 'call';
ALTER TABLE model_call ADD COLUMN measurement TEXT NOT NULL DEFAULT 'delta';
ALTER TABLE model_call ADD COLUMN coverage TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE model_call ADD COLUMN request_key TEXT;
ALTER TABLE model_call ADD COLUMN usage_event_uid TEXT;
CREATE TABLE usage_snapshot (
  snapshot_uid TEXT PRIMARY KEY, event_uid TEXT NOT NULL REFERENCES event,
  session_uid TEXT NOT NULL REFERENCES session, turn_uid TEXT,
  snapshot_key TEXT NOT NULL, usage_scope TEXT NOT NULL, measurement TEXT NOT NULL DEFAULT 'cumulative',
  coverage TEXT NOT NULL, provider TEXT, model_raw TEXT, effort_raw TEXT, purpose TEXT,
  observation_seq INTEGER NOT NULL, ts INTEGER,
  input_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
  output_tokens INTEGER, reasoning_tokens INTEGER, reported TEXT NOT NULL
) STRICT;
CREATE TABLE session_feature (
  session_uid TEXT NOT NULL REFERENCES session, feature TEXT NOT NULL, value TEXT NOT NULL,
  n INTEGER NOT NULL, PRIMARY KEY(session_uid,feature,value)
) STRICT;
CREATE TABLE link (
  link_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL REFERENCES session, turn_uid TEXT,
  event_uid TEXT NOT NULL REFERENCES event, kind TEXT NOT NULL, ref TEXT NOT NULL, ts INTEGER
) STRICT;
CREATE TABLE pipeline_version (
  component TEXT PRIMARY KEY, version TEXT NOT NULL
) STRICT;
CREATE TABLE source_boundary (
  source_id TEXT PRIMARY KEY REFERENCES source, last_ingest_scope TEXT NOT NULL,
  observed_at INTEGER NOT NULL
) STRICT;
INSERT INTO pipeline_version VALUES('parser','codex-connector/0.2.1'),('derivation','codex-derive/0.2.1'),('redaction','codex-redact/0.2.1');
INSERT OR IGNORE INTO dirty_session SELECT session_uid FROM session;
INSERT OR IGNORE INTO dirty_session SELECT DISTINCT session_uid FROM current_record WHERE session_uid IS NOT NULL;
UPDATE session SET started_at=NULL WHERE started_at=0;
UPDATE raw_record SET ref_event_uid=NULL WHERE ref_event_uid IS NOT NULL;

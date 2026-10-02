-- Contract v1. Timestamps are UTC milliseconds; NULL means unavailable.
CREATE TABLE schema_manifest (
  contract_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, redaction_version TEXT NOT NULL
) STRICT;
INSERT INTO schema_manifest VALUES('tandem-session-v1',1,'1.0.0');
CREATE TABLE source (
  source_id TEXT PRIMARY KEY, agent TEXT NOT NULL, root_path TEXT NOT NULL,
  label TEXT, enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
  discovered_at INTEGER NOT NULL, UNIQUE(agent, root_path)
) STRICT;
CREATE TABLE source_file (
  file_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source,
  relative_path TEXT NOT NULL, role TEXT NOT NULL, format TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','gone_upstream','error')),
  watermark TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(watermark)),
  last_scan_at INTEGER, UNIQUE(source_id, relative_path)
) STRICT;
CREATE TABLE archive_blob (
  archive_uid TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL,
  byte_len INTEGER NOT NULL CHECK(byte_len >= 0), stored_len INTEGER NOT NULL,
  codec TEXT NOT NULL CHECK(codec = 'zstd'), created_at INTEGER NOT NULL
) STRICT;
CREATE TABLE source_revision (
  revision_uid TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES source_file,
  revision INTEGER NOT NULL CHECK(revision > 0), archive_uid TEXT NOT NULL REFERENCES archive_blob,
  captured_at INTEGER NOT NULL, source_stat TEXT NOT NULL CHECK(json_valid(source_stat)),
  record_count INTEGER NOT NULL CHECK(record_count >= 0), UNIQUE(file_id, revision)
) STRICT;
CREATE TABLE session_identity (
  session_uid TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source,
  native_id TEXT NOT NULL, identity_key TEXT NOT NULL, UNIQUE(source_id, identity_key)
) STRICT;
CREATE TABLE raw_record (
  record_uid TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES source_file,
  revision_uid TEXT NOT NULL REFERENCES source_revision,
  locator TEXT NOT NULL CHECK(json_valid(locator)), version INTEGER NOT NULL CHECK(version > 0),
  ordinal INTEGER NOT NULL CHECK(ordinal >= 0), byte_offset INTEGER NOT NULL CHECK(byte_offset >= 0),
  byte_len INTEGER NOT NULL CHECK(byte_len > 0), sha256 TEXT NOT NULL,
  native_type TEXT NOT NULL, native_id TEXT, harness_version TEXT, shape_hash TEXT,
  session_uid TEXT REFERENCES session_identity DEFERRABLE INITIALLY DEFERRED,
  disposition TEXT NOT NULL DEFAULT 'unparsed'
    CHECK(disposition IN ('mapped','folded','replayed','duplicate','ignored','unparsed')),
  note TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(note)),
  UNIQUE(file_id, locator, version), UNIQUE(revision_uid, ordinal)
) STRICT;
CREATE TABLE file_record (
  file_id TEXT NOT NULL REFERENCES source_file, locator TEXT NOT NULL,
  record_uid TEXT NOT NULL REFERENCES raw_record, PRIMARY KEY(file_id, locator)
) STRICT;
CREATE TABLE project (
  project_id TEXT PRIMARY KEY, key_type TEXT NOT NULL CHECK(key_type IN ('git_remote','git_root','path','bucket')),
  key TEXT NOT NULL UNIQUE, name TEXT NOT NULL, git_remote TEXT,
  paths TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(paths))
) STRICT;
-- User-maintained tables survive projection rebuilds.
CREATE TABLE project_override (
  pattern TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project
) STRICT;
CREATE TABLE model_alias (
  provider TEXT NOT NULL, model_raw TEXT NOT NULL, model_id TEXT NOT NULL, family TEXT,
  PRIMARY KEY(provider, model_raw)
) STRICT;
CREATE TABLE event (
  event_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL REFERENCES session_identity,
  record_uid TEXT NOT NULL REFERENCES raw_record, native_id TEXT,
  native_key TEXT NOT NULL CHECK(json_valid(native_key)), event_path TEXT NOT NULL,
  kind TEXT NOT NULL, actor TEXT NOT NULL
    CHECK(actor IN ('human','assistant','system','tool','hook','subagent','harness')),
  seq INTEGER NOT NULL CHECK(seq >= 0), ts INTEGER,
  parent_uid TEXT REFERENCES event DEFERRABLE INITIALLY DEFERRED,
  turn_uid TEXT REFERENCES turn DEFERRABLE INITIALLY DEFERRED,
  call_id TEXT, text TEXT, text_truncated INTEGER NOT NULL DEFAULT 0 CHECK(text_truncated IN (0,1)),
  attrs TEXT NOT NULL CHECK(json_valid(attrs) AND json_type(attrs) = 'object'),
  ext TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(ext) AND json_type(ext) = 'object'),
  contract_version INTEGER NOT NULL CHECK(contract_version = 1), mapper_version TEXT NOT NULL,
  UNIQUE(session_uid, seq),
  CHECK(json_type(attrs,'$.time') IS 'object'),
  CHECK((ts IS NULL AND json_extract(attrs,'$.time.quality') IS 'missing') OR
    (ts IS NOT NULL AND json_extract(attrs,'$.time.quality') IN ('reported','estimated')
     AND json_type(attrs,'$.time.source_field') IS 'text')),
  CHECK(kind <> 'model.usage' OR
    (json_extract(attrs,'$.usage_scope') IS 'call' AND json_extract(attrs,'$.measurement') IS 'delta'
      AND json_type(attrs,'$.request_key') IS 'array') OR
    (json_extract(attrs,'$.usage_scope') IN ('session_snapshot','session_model_snapshot')
      AND json_extract(attrs,'$.measurement') IS 'cumulative'
      AND json_type(attrs,'$.snapshot_key') IS 'text'))
) STRICT;
CREATE TABLE record_event (
  record_uid TEXT NOT NULL REFERENCES raw_record,
  event_uid TEXT NOT NULL REFERENCES event DEFERRABLE INITIALLY DEFERRED,
  relation TEXT NOT NULL CHECK(relation IN ('mapped','folded','replayed','duplicate')),
  contribution TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(contribution)),
  PRIMARY KEY(record_uid, event_uid)
) STRICT;
CREATE TABLE session (
  session_uid TEXT PRIMARY KEY REFERENCES session_identity,
  source_id TEXT NOT NULL REFERENCES source, native_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('main','subagent','workflow_agent','review','automation','import','auxiliary')),
  parent_uid TEXT REFERENCES session_identity, root_uid TEXT NOT NULL REFERENCES session_identity,
  forked_from TEXT REFERENCES session_identity, imported_from TEXT REFERENCES session_identity,
  spawn_call_uid TEXT REFERENCES tool_call DEFERRABLE INITIALLY DEFERRED,
  depth INTEGER NOT NULL DEFAULT 0 CHECK(depth >= 0), lineage_unresolved INTEGER NOT NULL DEFAULT 0,
  project_id TEXT REFERENCES project, cwd TEXT, git_branch TEXT, git_sha TEXT, git_remote TEXT,
  client TEXT, harness_version TEXT, title TEXT, title_source TEXT,
  started_at INTEGER, ended_at INTEGER, timezone TEXT,
  timezone_source TEXT NOT NULL DEFAULT 'unknown' CHECK(timezone_source IN ('reported','local_inferred','unknown')),
  status TEXT NOT NULL DEFAULT 'unknown' CHECK(status IN ('active','completed','interrupted','failed','unknown')),
  CHECK((timezone IS NULL AND timezone_source = 'unknown') OR
    (timezone IS NOT NULL AND timezone_source <> 'unknown'))
) STRICT;
CREATE TABLE event_context (
  event_uid TEXT PRIMARY KEY REFERENCES event, project_id TEXT REFERENCES project,
  cwd TEXT, provider TEXT, model_raw TEXT, effort_raw TEXT
) STRICT;
CREATE TABLE turn (
  turn_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL REFERENCES session,
  idx INTEGER NOT NULL CHECK(idx >= 0), native_id TEXT, trigger TEXT NOT NULL,
  boundary_source TEXT NOT NULL CHECK(boundary_source IN ('reported','derived')),
  project_id TEXT REFERENCES project, status TEXT NOT NULL,
  started_at INTEGER, ended_at INTEGER,
  trigger_event_uid TEXT REFERENCES event, first_event_uid TEXT NOT NULL REFERENCES event,
  last_event_uid TEXT NOT NULL REFERENCES event, UNIQUE(session_uid, idx)
) STRICT;
CREATE TABLE tool_call (
  call_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL REFERENCES session,
  turn_uid TEXT REFERENCES turn, project_id TEXT REFERENCES project, native_call_id TEXT,
  call_event_uid TEXT REFERENCES event, result_event_uid TEXT REFERENCES event,
  name_raw TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
  mcp_server TEXT, mcp_tool TEXT, skill TEXT, subagent_session_uid TEXT REFERENCES session_identity,
  command_head TEXT, files TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(files)),
  status TEXT NOT NULL, pairing_quality TEXT NOT NULL, exit_code INTEGER, error_class TEXT,
  is_wrapper INTEGER NOT NULL DEFAULT 0 CHECK(is_wrapper IN (0,1)),
  argument_digest TEXT, status_scope TEXT NOT NULL DEFAULT 'unknown',
  started_at INTEGER, ended_at INTEGER, duration_ms INTEGER CHECK(duration_ms >= 0),
  duration_source TEXT NOT NULL CHECK(duration_source IN ('reported','native_bounds','event_difference','unknown')),
  duration_quality TEXT NOT NULL CHECK(duration_quality IN ('reported','estimated','missing')),
  approval TEXT, approval_wait_ms INTEGER CHECK(approval_wait_ms >= 0),
  attribution TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attribution)),
  CHECK((duration_ms IS NULL AND duration_quality = 'missing') OR
    (duration_ms IS NOT NULL AND duration_quality IN ('reported','estimated')))
) STRICT;
CREATE TABLE tool_call_event (
  call_uid TEXT NOT NULL REFERENCES tool_call, event_uid TEXT NOT NULL REFERENCES event,
  role TEXT NOT NULL, PRIMARY KEY(call_uid, event_uid)
) STRICT;
CREATE TABLE model_call (
  call_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL REFERENCES session,
  turn_uid TEXT REFERENCES turn, project_id TEXT REFERENCES project,
  usage_event_uid TEXT NOT NULL UNIQUE REFERENCES event, request_id TEXT,
  provider TEXT, model_raw TEXT, model_id TEXT, model_resolution TEXT NOT NULL,
  effort_raw TEXT, effort_rank INTEGER, purpose TEXT, coverage TEXT NOT NULL,
  input_tokens INTEGER CHECK(input_tokens >= 0), cache_read_tokens INTEGER CHECK(cache_read_tokens >= 0),
  cache_write_tokens INTEGER CHECK(cache_write_tokens >= 0), output_tokens INTEGER CHECK(output_tokens >= 0),
  reasoning_tokens INTEGER CHECK(reasoning_tokens >= 0), cost_usd REAL CHECK(cost_usd >= 0), cost_source TEXT,
  latency_ms INTEGER CHECK(latency_ms >= 0), ttft_ms INTEGER CHECK(ttft_ms >= 0), stop_reason TEXT, ts INTEGER
) STRICT;
CREATE TABLE usage_snapshot (
  snapshot_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL REFERENCES session,
  event_uid TEXT NOT NULL UNIQUE REFERENCES event, snapshot_key TEXT NOT NULL, counter_cycle TEXT NOT NULL,
  usage_scope TEXT NOT NULL CHECK(usage_scope IN ('session_snapshot','session_model_snapshot')),
  coverage TEXT NOT NULL, provider TEXT, model_raw TEXT, model_id TEXT, purpose TEXT,
  observation_seq INTEGER NOT NULL, ts INTEGER, observed_at INTEGER NOT NULL,
  input_tokens INTEGER CHECK(input_tokens >= 0), cache_read_tokens INTEGER CHECK(cache_read_tokens >= 0),
  cache_write_tokens INTEGER CHECK(cache_write_tokens >= 0), output_tokens INTEGER CHECK(output_tokens >= 0),
  reasoning_tokens INTEGER CHECK(reasoning_tokens >= 0), cost_usd REAL CHECK(cost_usd >= 0), cost_source TEXT
) STRICT;
CREATE TABLE link (
  link_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL REFERENCES session, turn_uid TEXT REFERENCES turn,
  event_uid TEXT NOT NULL REFERENCES event, kind TEXT NOT NULL, ref TEXT NOT NULL, ts INTEGER
) STRICT;
CREATE TABLE session_feature (
  session_uid TEXT NOT NULL REFERENCES session, feature TEXT NOT NULL, value TEXT NOT NULL,
  n INTEGER NOT NULL CHECK(n > 0), PRIMARY KEY(session_uid, feature, value)
) STRICT;
CREATE TABLE ingest_issue (
  issue_uid TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source,
  file_id TEXT REFERENCES source_file, record_uid TEXT REFERENCES raw_record,
  stage TEXT NOT NULL CHECK(stage IN ('l1','l2','l3')), code TEXT NOT NULL,
  severity TEXT NOT NULL CHECK(severity IN ('info','warning','error')),
  detail TEXT NOT NULL CHECK(json_valid(detail)), detected_at INTEGER NOT NULL
) STRICT;
CREATE TABLE projection_run (
  run_id INTEGER PRIMARY KEY, contract_version INTEGER NOT NULL, mapper_version TEXT NOT NULL,
  reducer_version TEXT NOT NULL, completed_at INTEGER NOT NULL, event_count INTEGER NOT NULL
  ,l1_revision_count INTEGER NOT NULL
) STRICT;
CREATE TABLE connector_checkpoint (
  connector_db TEXT NOT NULL, external_file_id TEXT NOT NULL, generation INTEGER NOT NULL,
  fingerprint TEXT NOT NULL, file_id TEXT NOT NULL REFERENCES source_file,
  PRIMARY KEY(connector_db, external_file_id, generation)
) STRICT;
CREATE TABLE connector_record_link (
  connector_db TEXT NOT NULL, external_record_uid TEXT NOT NULL,
  record_uid TEXT NOT NULL REFERENCES raw_record, PRIMARY KEY(connector_db, external_record_uid)
) STRICT;
CREATE INDEX record_by_file ON raw_record(file_id, ordinal);
CREATE INDEX record_by_session ON raw_record(session_uid);
CREATE INDEX event_by_call ON event(session_uid, call_id);
CREATE INDEX event_by_kind_time ON event(kind, ts);
CREATE INDEX evidence_by_event ON record_event(event_uid);
CREATE INDEX tool_by_project ON tool_call(project_id, started_at);
CREATE INDEX model_by_project_model ON model_call(project_id, model_id, ts);
CREATE INDEX snapshot_by_key ON usage_snapshot(session_uid, snapshot_key, observation_seq);
CREATE VIRTUAL TABLE event_fts USING fts5(text, content='event', content_rowid='rowid');
CREATE TRIGGER event_ai AFTER INSERT ON event BEGIN
  INSERT INTO event_fts(rowid,text) VALUES(new.rowid,new.text);
END;
CREATE TRIGGER event_ad AFTER DELETE ON event BEGIN
  INSERT INTO event_fts(event_fts,rowid,text) VALUES('delete',old.rowid,old.text);
END;
CREATE TRIGGER event_au AFTER UPDATE OF text ON event BEGIN
  INSERT INTO event_fts(event_fts,rowid,text) VALUES('delete',old.rowid,old.text);
  INSERT INTO event_fts(rowid,text) VALUES(new.rowid,new.text);
END;
CREATE VIEW v_raw_record_ledger AS SELECT r.*,
  EXISTS(SELECT 1 FROM file_record f WHERE f.record_uid=r.record_uid) AS is_current,
  (SELECT re.event_uid FROM record_event re JOIN event e USING(event_uid)
    WHERE re.record_uid=r.record_uid ORDER BY e.seq,e.event_uid LIMIT 1) AS ref_event_uid,
  (SELECT COUNT(*) FROM record_event re WHERE re.record_uid=r.record_uid) AS event_count
  FROM raw_record r;
CREATE VIEW v_analysis_event AS SELECT e.*, c.project_id, c.cwd, c.provider, c.model_raw, c.effort_raw,
  s.root_uid FROM event e JOIN session s USING(session_uid)
  JOIN session root ON root.session_uid=s.root_uid JOIN event_context c USING(event_uid)
  WHERE s.kind IN ('main','subagent','workflow_agent') AND root.kind='main' AND s.lineage_unresolved=0;
CREATE VIEW v_human_message AS SELECT e.* FROM v_analysis_event e JOIN session s USING(session_uid)
  WHERE s.kind='main' AND e.kind='message.user' AND json_extract(e.attrs,'$.origin')='human';
CREATE VIEW v_analysis_tool_call AS SELECT t.*, s.root_uid FROM tool_call t
  JOIN session s USING(session_uid) JOIN session root ON root.session_uid=s.root_uid
  WHERE s.kind IN ('main','subagent','workflow_agent') AND root.kind='main' AND s.lineage_unresolved=0;
CREATE VIEW v_analysis_model_call AS SELECT m.*, s.root_uid FROM model_call m
  JOIN session s USING(session_uid) JOIN session root ON root.session_uid=s.root_uid
  WHERE s.kind IN ('main','subagent','workflow_agent') AND root.kind='main' AND s.lineage_unresolved=0;
-- ONLY observed call/delta usage. Cumulative snapshots are never added.
CREATE VIEW v_session_call_usage AS SELECT session_uid, COUNT(*) AS observed_call_count,
  CASE WHEN COUNT(input_tokens)=COUNT(*) THEN SUM(input_tokens) END AS input_tokens,
  CASE WHEN COUNT(cache_read_tokens)=COUNT(*) THEN SUM(cache_read_tokens) END AS cache_read_tokens,
  CASE WHEN COUNT(cache_write_tokens)=COUNT(*) THEN SUM(cache_write_tokens) END AS cache_write_tokens,
  CASE WHEN COUNT(output_tokens)=COUNT(*) THEN SUM(output_tokens) END AS output_tokens,
  CASE WHEN COUNT(reasoning_tokens)=COUNT(*) THEN SUM(reasoning_tokens) END AS reasoning_tokens,
  CASE WHEN COUNT(cost_usd)=COUNT(*) THEN SUM(cost_usd) END AS cost_usd
  FROM v_analysis_model_call GROUP BY session_uid;
CREATE VIEW v_latest_usage_snapshot AS SELECT * FROM (
  SELECT u.*, ROW_NUMBER() OVER(PARTITION BY session_uid,snapshot_key,counter_cycle
    ORDER BY observation_seq DESC) AS observation_rank FROM usage_snapshot u
) WHERE observation_rank=1;
PRAGMA user_version = 1;

-- Storage v8 (idempotent, so a store whose version was rewound can reapply it): physical indexes, content-addressed ext payloads and a message-only search index.
-- 007 is reserved for feat/data-app-integration's FK indexes; the same names are repeated here
-- with IF NOT EXISTS so either merge order upgrades to identical indexes.
CREATE INDEX IF NOT EXISTS fk_project_override_project_id ON project_override(project_id);
CREATE INDEX IF NOT EXISTS fk_event_record_uid ON event(record_uid);
CREATE INDEX IF NOT EXISTS fk_session_project_id ON session(project_id);
CREATE INDEX IF NOT EXISTS fk_session_spawn_call_uid ON session(spawn_call_uid);
CREATE INDEX IF NOT EXISTS fk_session_imported_from ON session(imported_from);
CREATE INDEX IF NOT EXISTS fk_session_forked_from ON session(forked_from);
CREATE INDEX IF NOT EXISTS fk_session_root_uid ON session(root_uid);
CREATE INDEX IF NOT EXISTS fk_session_parent_uid ON session(parent_uid);
CREATE INDEX IF NOT EXISTS fk_session_source_id ON session(source_id);
CREATE INDEX IF NOT EXISTS fk_event_context_project_id ON event_context(project_id);
CREATE INDEX IF NOT EXISTS fk_turn_last_event_uid ON turn(last_event_uid);
CREATE INDEX IF NOT EXISTS fk_turn_first_event_uid ON turn(first_event_uid);
CREATE INDEX IF NOT EXISTS fk_turn_trigger_event_uid ON turn(trigger_event_uid);
CREATE INDEX IF NOT EXISTS fk_turn_project_id ON turn(project_id);
CREATE INDEX IF NOT EXISTS fk_tool_call_subagent_session_uid ON tool_call(subagent_session_uid);
CREATE INDEX IF NOT EXISTS fk_tool_call_result_event_uid ON tool_call(result_event_uid);
CREATE INDEX IF NOT EXISTS fk_tool_call_call_event_uid ON tool_call(call_event_uid);
CREATE INDEX IF NOT EXISTS fk_tool_call_turn_uid ON tool_call(turn_uid);
CREATE INDEX IF NOT EXISTS fk_tool_call_session_uid ON tool_call(session_uid);
CREATE INDEX IF NOT EXISTS fk_model_call_turn_uid ON model_call(turn_uid);
CREATE INDEX IF NOT EXISTS fk_model_call_session_uid ON model_call(session_uid);
CREATE INDEX IF NOT EXISTS fk_link_event_uid ON link(event_uid);
CREATE INDEX IF NOT EXISTS fk_link_turn_uid ON link(turn_uid);
CREATE INDEX IF NOT EXISTS fk_link_session_uid ON link(session_uid);
CREATE INDEX IF NOT EXISTS fk_ingest_issue_record_uid ON ingest_issue(record_uid);
CREATE INDEX IF NOT EXISTS fk_ingest_issue_file_id ON ingest_issue(file_id);
CREATE INDEX IF NOT EXISTS fk_ingest_issue_source_id ON ingest_issue(source_id);
CREATE INDEX IF NOT EXISTS fk_connector_checkpoint_file_id ON connector_checkpoint(file_id);
CREATE INDEX IF NOT EXISTS fk_connector_record_link_record_uid ON connector_record_link(record_uid);
CREATE INDEX IF NOT EXISTS fk_inventory_scan_project_id ON inventory_scan(project_id);

-- The former projection_fk_* indexes duplicated the fk_* set above.
DROP INDEX IF EXISTS projection_fk_tool_session;
DROP INDEX IF EXISTS projection_fk_tool_turn;
DROP INDEX IF EXISTS projection_fk_model_session;
DROP INDEX IF EXISTS projection_fk_model_turn;
DROP INDEX IF EXISTS projection_fk_link_session;
DROP INDEX IF EXISTS projection_fk_link_turn;
DROP INDEX IF EXISTS projection_fk_session_spawn;

-- Product query paths (session lists, per-tool history, per-file version lookup).
CREATE INDEX IF NOT EXISTS session_by_started ON session(started_at);
CREATE INDEX IF NOT EXISTS session_by_project_started ON session(project_id, started_at);
CREATE INDEX IF NOT EXISTS session_by_source_started ON session(source_id, started_at);
CREATE INDEX IF NOT EXISTS tool_by_name_started ON tool_call(name, started_at);
CREATE INDEX IF NOT EXISTS record_by_file_locator ON raw_record(file_id, locator, version);
-- Freshness checks read these instead of parsing every watermark per query.
CREATE INDEX IF NOT EXISTS source_file_unprojected ON source_file(file_id)
  WHERE COALESCE(json_extract(watermark,'$.projected_revision'),-1) <> COALESCE(json_extract(watermark,'$.revision'),0);
CREATE INDEX IF NOT EXISTS source_file_projection_versions ON source_file(
  json_extract(watermark,'$.mapper_version'),
  json_extract(watermark,'$.reducer_version'),
  json_extract(watermark,'$.redaction_version'));

-- Large ext strings are stored once, zstd-compressed, addressed by the sha256 of their UTF-8.
-- event.ext keeps {"$blob":sha256,"len":chars}; readers restore the original string.
CREATE TABLE IF NOT EXISTS content_blob (
  sha256 TEXT PRIMARY KEY CHECK(length(sha256) = 64),
  codec TEXT NOT NULL CHECK(codec IN ('zstd')),
  raw_len INTEGER NOT NULL CHECK(raw_len >= 0),
  data BLOB NOT NULL,
  refs INTEGER NOT NULL DEFAULT 0 CHECK(refs >= 0)
) STRICT;
CREATE TRIGGER IF NOT EXISTS event_blob_ai AFTER INSERT ON event WHEN instr(new.ext, '"$blob"') BEGIN
  UPDATE content_blob SET refs = refs + (
    SELECT COUNT(*) FROM json_tree(new.ext) t WHERE t.key = '$blob' AND t.type = 'text' AND t.path NOT LIKE '%."$lit"' AND t.value = content_blob.sha256
  ) WHERE sha256 IN (SELECT value FROM json_tree(new.ext) WHERE key = '$blob');
END;
CREATE TRIGGER IF NOT EXISTS event_blob_ad AFTER DELETE ON event WHEN instr(old.ext, '"$blob"') BEGIN
  UPDATE content_blob SET refs = refs - (
    SELECT COUNT(*) FROM json_tree(old.ext) t WHERE t.key = '$blob' AND t.type = 'text' AND t.path NOT LIKE '%."$lit"' AND t.value = content_blob.sha256
  ) WHERE sha256 IN (SELECT value FROM json_tree(old.ext) WHERE key = '$blob');
END;
CREATE TRIGGER IF NOT EXISTS event_blob_au AFTER UPDATE OF ext ON event
WHEN instr(old.ext, '"$blob"') OR instr(new.ext, '"$blob"') BEGIN
  UPDATE content_blob SET refs = refs - (
    SELECT COUNT(*) FROM json_tree(old.ext) t WHERE t.key = '$blob' AND t.type = 'text' AND t.path NOT LIKE '%."$lit"' AND t.value = content_blob.sha256
  ) WHERE sha256 IN (SELECT value FROM json_tree(old.ext) WHERE key = '$blob');
  UPDATE content_blob SET refs = refs + (
    SELECT COUNT(*) FROM json_tree(new.ext) t WHERE t.key = '$blob' AND t.type = 'text' AND t.path NOT LIKE '%."$lit"' AND t.value = content_blob.sha256
  ) WHERE sha256 IN (SELECT value FROM json_tree(new.ext) WHERE key = '$blob');
END;

-- Full-text search covers human/assistant messages and titles only. Tool output is searched
-- through tool_call columns; trigram tokens support CJK substrings without word breaks.
DROP TRIGGER IF EXISTS event_ai;
DROP TRIGGER IF EXISTS event_ad;
DROP TRIGGER IF EXISTS event_au;
DROP TABLE IF EXISTS event_fts;
CREATE VIRTUAL TABLE IF NOT EXISTS event_search USING fts5(
  text, content='', contentless_delete=1, tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS event_search_ai AFTER INSERT ON event
WHEN new.kind IN ('message.user','message.assistant','session.title') AND new.text IS NOT NULL BEGIN
  INSERT INTO event_search(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS event_search_ad AFTER DELETE ON event
WHEN old.kind IN ('message.user','message.assistant','session.title') AND old.text IS NOT NULL BEGIN
  DELETE FROM event_search WHERE rowid = old.rowid;
END;
CREATE TRIGGER IF NOT EXISTS event_search_au AFTER UPDATE OF text, kind ON event BEGIN
  DELETE FROM event_search WHERE rowid = old.rowid
    AND old.kind IN ('message.user','message.assistant','session.title') AND old.text IS NOT NULL;
  INSERT INTO event_search(rowid, text) SELECT new.rowid, new.text
    WHERE new.kind IN ('message.user','message.assistant','session.title') AND new.text IS NOT NULL;
END;
DELETE FROM event_search;
INSERT INTO event_search(rowid, text)
  SELECT rowid, text FROM event
  WHERE kind IN ('message.user','message.assistant','session.title') AND text IS NOT NULL;

UPDATE schema_manifest SET schema_version=8;
PRAGMA user_version=8;

-- Storage v10 (idempotent): drop redundant index entries; logical contents are unchanged.
-- Every foreign key keeps an index whose leading column is the key column.

-- Strict prefixes of the v8 list indexes session_by_source_started(source_id, started_at) and
-- session_by_project_started(project_id, started_at), which serve the same lookups and FK checks.
DROP INDEX IF EXISTS fk_session_source_id;
DROP INDEX IF EXISTS fk_session_project_id;
-- tool_call.subagent_session_uid is NULL except on Agent/Task calls; an FK lookup
-- subagent_session_uid=? implies IS NOT NULL, so the partial index serves it.
DROP INDEX IF EXISTS fk_tool_call_subagent_session_uid;
CREATE INDEX IF NOT EXISTS fk_tool_call_subagent_session_set ON tool_call(subagent_session_uid)
  WHERE subagent_session_uid IS NOT NULL;

UPDATE schema_manifest SET schema_version=10;
PRAGMA user_version=10;

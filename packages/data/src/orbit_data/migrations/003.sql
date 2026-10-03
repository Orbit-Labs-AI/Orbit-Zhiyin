-- Deleting/replacing L2 must not scan the complete event table once per FK.
CREATE INDEX IF NOT EXISTS event_by_parent ON event(parent_uid);
CREATE INDEX IF NOT EXISTS event_by_turn ON event(turn_uid);
CREATE INDEX IF NOT EXISTS tool_evidence_by_event ON tool_call_event(event_uid);
UPDATE schema_manifest SET schema_version=3;
PRAGMA user_version=3;

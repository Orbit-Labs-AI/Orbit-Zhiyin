-- Index source identities and evidence reverse lookups used by replay detection.
CREATE INDEX IF NOT EXISTS event_by_native ON event(native_key);
CREATE INDEX IF NOT EXISTS current_record_by_uid ON file_record(record_uid);
CREATE INDEX IF NOT EXISTS revision_by_archive ON source_revision(archive_uid);
UPDATE schema_manifest SET schema_version=2;
PRAGMA user_version=2;

-- L0 is a source reference for native imports. Historical archives remain readable.
CREATE TABLE source_revision_new (
  revision_uid TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES source_file,
  revision INTEGER NOT NULL CHECK(revision > 0), archive_uid TEXT REFERENCES archive_blob,
  captured_at INTEGER NOT NULL, source_stat TEXT NOT NULL CHECK(json_valid(source_stat)),
  record_count INTEGER NOT NULL CHECK(record_count >= 0), UNIQUE(file_id, revision)
) STRICT;
INSERT INTO source_revision_new SELECT * FROM source_revision;
DROP TABLE source_revision;
ALTER TABLE source_revision_new RENAME TO source_revision;
CREATE TABLE source_reference (
  revision_uid TEXT PRIMARY KEY REFERENCES source_revision,
  sha256 TEXT NOT NULL, byte_len INTEGER NOT NULL CHECK(byte_len >= 0),
  encoding TEXT NOT NULL CHECK(encoding IN ('jsonl','jsonl_zstd','json','sqlite_rows'))
) STRICT;
CREATE TABLE record_location (
  record_uid TEXT NOT NULL REFERENCES raw_record,
  revision_uid TEXT NOT NULL REFERENCES source_reference,
  ordinal INTEGER NOT NULL, byte_offset INTEGER NOT NULL, byte_len INTEGER NOT NULL,
  PRIMARY KEY(record_uid, revision_uid)
) STRICT;
CREATE INDEX record_location_revision ON record_location(revision_uid, ordinal);
CREATE INDEX source_revision_archive ON source_revision(archive_uid);
CREATE INDEX raw_record_session ON raw_record(session_uid, file_id, ordinal);
-- Small cumulative numeric observations survive mutable native SQLite rows.
CREATE TABLE usage_observation (
  record_uid TEXT PRIMARY KEY REFERENCES raw_record,
  observation TEXT NOT NULL CHECK(json_valid(observation))
) STRICT;
CREATE TABLE source_scan (
  source_id TEXT PRIMARY KEY REFERENCES source,
  scanned_at INTEGER NOT NULL, selection TEXT NOT NULL,
  discovered_files INTEGER NOT NULL, indexed_files INTEGER NOT NULL,
  capture_errors INTEGER NOT NULL, cancelled INTEGER NOT NULL
) STRICT;
UPDATE schema_manifest SET schema_version=5;
PRAGMA user_version=5;

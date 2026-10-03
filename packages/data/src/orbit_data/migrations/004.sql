-- A path can acquire a Git identity. Keep both historical IDs and user overrides.
CREATE TABLE project_v4 (
  project_id TEXT PRIMARY KEY,
  key_type TEXT NOT NULL CHECK(key_type IN ('git_remote','git_root','path','bucket')),
  key TEXT NOT NULL, name TEXT NOT NULL, git_remote TEXT,
  paths TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(paths)),
  UNIQUE(key_type, key)
) STRICT;
INSERT INTO project_v4 SELECT * FROM project;
DROP TABLE project;
ALTER TABLE project_v4 RENAME TO project;
UPDATE schema_manifest SET schema_version=4;
PRAGMA user_version=4;

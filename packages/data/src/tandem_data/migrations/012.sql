ALTER TABLE tool_call ADD COLUMN command_spec TEXT CHECK(command_spec IS NULL OR
  (json_valid(command_spec) AND json_type(command_spec)='object'));
UPDATE schema_manifest SET schema_version=12;
PRAGMA user_version=12;

ALTER TABLE tool_call ADD COLUMN wall_elapsed_ms INTEGER CHECK(wall_elapsed_ms >= 0);
ALTER TABLE tool_call ADD COLUMN native_execution_ms INTEGER CHECK(native_execution_ms >= 0);
-- Historical native-bounds rows establish elapsed span, never process CPU or
-- human work time. Native duration is filled only by an evidence-backed rebuild.
UPDATE tool_call SET wall_elapsed_ms=ended_at-started_at
  WHERE duration_source='native_bounds' AND duration_quality='reported'
    AND ended_at>=started_at;
UPDATE schema_manifest SET schema_version=9;
PRAGMA user_version=9;

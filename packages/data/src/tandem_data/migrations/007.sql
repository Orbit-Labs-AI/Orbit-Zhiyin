-- model_call is a call/delta projection by construction. Identity and boundary
-- quality are independent: a row hash alone does not prove a request boundary.
ALTER TABLE model_call ADD COLUMN request_identity_quality TEXT NOT NULL DEFAULT 'unknown'
  CHECK(request_identity_quality IN ('reported','derived','unknown'));
ALTER TABLE model_call ADD COLUMN boundary_quality TEXT NOT NULL DEFAULT 'unknown'
  CHECK(boundary_quality IN ('reported','observed','unknown','conflict'));
UPDATE model_call SET request_identity_quality = CASE
  WHEN request_id IS NOT NULL AND request_id <> '' THEN 'reported'
  WHEN json_array_length((SELECT json_extract(attrs,'$.request_key') FROM event WHERE event_uid=usage_event_uid)) > 0 THEN 'derived'
  ELSE 'unknown' END,
  boundary_quality = CASE
  WHEN request_id IS NOT NULL AND request_id <> '' THEN 'reported'
  WHEN (SELECT json_extract(attrs,'$.boundary_evidence') FROM event WHERE event_uid=usage_event_uid) = 'changed_cumulative_usage' THEN 'observed'
  ELSE 'unknown' END;
UPDATE schema_manifest SET schema_version=7;
PRAGMA user_version=7;

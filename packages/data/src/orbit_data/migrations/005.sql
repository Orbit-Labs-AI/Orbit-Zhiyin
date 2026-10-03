-- Independent, immutable observations; session projection rebuilds never delete these.
CREATE TABLE inventory_scan (
  scan_id INTEGER PRIMARY KEY, source_key TEXT NOT NULL, agent TEXT NOT NULL,
  root_path TEXT NOT NULL, scope TEXT NOT NULL CHECK(scope IN ('global','project')),
  project_id TEXT REFERENCES project, observed_at INTEGER NOT NULL,
  scanner_version TEXT NOT NULL,
  coverage TEXT NOT NULL CHECK(json_valid(coverage)),
  diagnostics TEXT NOT NULL CHECK(json_valid(diagnostics))
) STRICT;
CREATE INDEX inventory_scan_source ON inventory_scan(source_key, scan_id DESC);
CREATE TABLE inventory_item (
  scan_id INTEGER NOT NULL REFERENCES inventory_scan, inv_id TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('skill','mcp','hook','plugin','rule','scheduled_task')),
  name TEXT NOT NULL, config_path TEXT NOT NULL, locator TEXT NOT NULL,
  enabled INTEGER CHECK(enabled IN (0,1)),
  evidence TEXT NOT NULL CHECK(evidence IN ('file','configured','cached','installed')),
  config TEXT NOT NULL CHECK(json_valid(config)), content_hash TEXT NOT NULL,
  PRIMARY KEY(scan_id, inv_id)
) STRICT;
UPDATE schema_manifest SET schema_version=5;
PRAGMA user_version=5;

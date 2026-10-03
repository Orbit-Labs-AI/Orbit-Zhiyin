-- Inventory gains first-class 'command' (slash-command documents such as Claude Code
-- commands/**/*.md) and 'agent' (subagent definitions such as agents/**/*.md) types.
-- Scanner 1.3.0 stored both as type 'skill' with config.component naming the real kind;
-- those observations are re-typed in place. inv_id is kept so earlier scans stay
-- addressable; newer scans derive inv_id from the new type. SQLite cannot alter a CHECK
-- constraint, so the table is copied (no table references inventory_item).
CREATE TABLE inventory_item_v15 (
  scan_id INTEGER NOT NULL REFERENCES inventory_scan, inv_id TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN
    ('skill','mcp','hook','plugin','rule','scheduled_task','command','agent')),
  name TEXT NOT NULL, config_path TEXT NOT NULL, locator TEXT NOT NULL,
  enabled INTEGER CHECK(enabled IN (0,1)),
  evidence TEXT NOT NULL CHECK(evidence IN ('file','configured','cached','installed')),
  config TEXT NOT NULL CHECK(json_valid(config)), content_hash TEXT NOT NULL,
  PRIMARY KEY(scan_id, inv_id)
) STRICT;
INSERT INTO inventory_item_v15
SELECT scan_id, inv_id,
  CASE WHEN type='skill' AND json_extract(config,'$.component') IN ('command','agent')
       THEN json_extract(config,'$.component') ELSE type END,
  name, config_path, locator, enabled, evidence, config, content_hash
FROM inventory_item;
DROP TABLE inventory_item;
ALTER TABLE inventory_item_v15 RENAME TO inventory_item;

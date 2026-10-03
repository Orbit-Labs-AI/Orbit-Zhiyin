-- Notification delivery (FE-18.1), attention queue (AN-13.1) and collection pause (DT-02.1).
-- notification.state: delivered | suppressed | acked | resolved
CREATE TABLE IF NOT EXISTS notification (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  last_ts INTEGER NOT NULL,
  type TEXT NOT NULL,
  dedupe_key TEXT NOT NULL,
  session_uid TEXT,
  severity TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL DEFAULT '{}',
  channels TEXT NOT NULL DEFAULT '[]',
  state TEXT NOT NULL,
  suppressed_reason TEXT,
  acked_at INTEGER,
  count INTEGER NOT NULL DEFAULT 1
) STRICT;
CREATE INDEX IF NOT EXISTS notification_state_ts ON notification(state, ts DESC);
CREATE INDEX IF NOT EXISTS notification_key_ts ON notification(dedupe_key, ts DESC);

CREATE TABLE IF NOT EXISTS notification_policy (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  body TEXT NOT NULL,
  updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS notification_snooze (
  scope TEXT PRIMARY KEY,
  until INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS collection_pause (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at INTEGER NOT NULL,
  ended_at INTEGER,
  reason TEXT NOT NULL DEFAULT 'user'
) STRICT;
CREATE INDEX IF NOT EXISTS collection_pause_open ON collection_pause(ended_at);

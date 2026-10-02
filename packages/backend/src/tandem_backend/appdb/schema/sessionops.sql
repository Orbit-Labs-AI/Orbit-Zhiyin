-- sessionops: sessions the user excluded from analysis (AN-16.1). excluded_at is epoch ms.
CREATE TABLE IF NOT EXISTS session_exclusion (
  session_uid TEXT PRIMARY KEY,
  reason TEXT CHECK(reason IS NULL OR reason IN ('test','private','duplicate','other')),
  note TEXT,
  excluded_at INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'user' CHECK(source IN ('user','auto'))
) STRICT;
CREATE INDEX IF NOT EXISTS session_exclusion_at ON session_exclusion(excluded_at);

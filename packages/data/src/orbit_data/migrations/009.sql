-- Storage v9 (idempotent): smaller physical layout, identical logical contents.
-- Column names, order, types, constraints and values are unchanged; only indexes and the row
-- storage of three link tables change. Large non-message event.text moves to content_blob
-- at write time (payload.py); rows written before v9 stay inline and remain valid.

-- event.text of a non-message kind may hold char(64976)||sha256 (U+FDD0, a Unicode
-- noncharacter) referring to content_blob; a native text starting with U+FDD0 is stored with
-- one extra leading U+FDD0. Escape any such pre-v9 text so it keeps its meaning (only on a
-- store that has not been v9 yet, so reapplying this file never escapes twice).
UPDATE event SET text = char(64976) || text
  WHERE (SELECT schema_version FROM schema_manifest) < 9
    AND kind NOT IN ('message.user','message.assistant','session.title')
    AND substr(text,1,1) = char(64976);
CREATE TRIGGER IF NOT EXISTS event_text_blob_ai AFTER INSERT ON event
WHEN new.kind NOT IN ('message.user','message.assistant','session.title') AND length(new.text)=65
  AND substr(new.text,1,1)=char(64976) AND substr(new.text,2,1)<>char(64976) BEGIN
  UPDATE content_blob SET refs = refs + 1 WHERE sha256 = substr(new.text,2);
END;
CREATE TRIGGER IF NOT EXISTS event_text_blob_ad AFTER DELETE ON event
WHEN old.kind NOT IN ('message.user','message.assistant','session.title') AND length(old.text)=65
  AND substr(old.text,1,1)=char(64976) AND substr(old.text,2,1)<>char(64976) BEGIN
  UPDATE content_blob SET refs = refs - 1 WHERE sha256 = substr(old.text,2);
END;
CREATE TRIGGER IF NOT EXISTS event_text_blob_au AFTER UPDATE OF text, kind ON event BEGIN
  UPDATE content_blob SET refs = refs - 1 WHERE sha256 = substr(old.text,2)
    AND old.kind NOT IN ('message.user','message.assistant','session.title') AND length(old.text)=65
    AND substr(old.text,1,1)=char(64976) AND substr(old.text,2,1)<>char(64976);
  UPDATE content_blob SET refs = refs + 1 WHERE sha256 = substr(new.text,2)
    AND new.kind NOT IN ('message.user','message.assistant','session.title') AND length(new.text)=65
    AND substr(new.text,1,1)=char(64976) AND substr(new.text,2,1)<>char(64976);
END;

-- Exact duplicates or strict prefixes of other indexes:
-- record_by_file_locator == UNIQUE(file_id, locator, version); record_by_session is a prefix
-- of raw_record_session(session_uid, file_id, ordinal).
DROP INDEX IF EXISTS record_by_file_locator;
DROP INDEX IF EXISTS record_by_session;
-- No query filters event by call_id (the reducer pairs calls in memory); session_uid lookups
-- use UNIQUE(session_uid, seq).
DROP INDEX IF EXISTS event_by_call;
-- Native-key lookups (fork/seed replay) match a short, selective tail of the canonical key and
-- then compare the full key: WHERE substr(native_key,-24)=substr(?1,-24) AND native_key=?1.
DROP INDEX IF EXISTS event_by_native;
CREATE INDEX IF NOT EXISTS event_by_native_tail ON event(substr(native_key, -24));
-- Most events have no parent; the FK lookup parent_uid=? implies parent_uid IS NOT NULL.
DROP INDEX IF EXISTS event_by_parent;
CREATE INDEX IF NOT EXISTS event_by_parent_set ON event(parent_uid) WHERE parent_uid IS NOT NULL;

-- Link tables whose rows are little more than their primary key are stored WITHOUT ROWID, so
-- the key is not stored twice (table row + automatic unique index). None of them is the parent
-- of a foreign key. event_context and file_record stay rowid tables: their secondary indexes
-- would carry the 70-character key instead of a rowid and cancel the saving.
-- Views refer to these tables by name; renames must not rewrite them.
PRAGMA legacy_alter_table=ON;
CREATE TABLE IF NOT EXISTS record_event_v9 (
  record_uid TEXT NOT NULL REFERENCES raw_record,
  event_uid TEXT NOT NULL REFERENCES event DEFERRABLE INITIALLY DEFERRED,
  relation TEXT NOT NULL CHECK(relation IN ('mapped','folded','replayed','duplicate')),
  contribution TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(contribution)),
  PRIMARY KEY(record_uid, event_uid)
) STRICT, WITHOUT ROWID;
INSERT INTO record_event_v9 SELECT record_uid, event_uid, relation, contribution FROM record_event;
DROP TABLE record_event;
ALTER TABLE record_event_v9 RENAME TO record_event;
CREATE INDEX IF NOT EXISTS evidence_by_event ON record_event(event_uid);

CREATE TABLE IF NOT EXISTS record_location_v9 (
  record_uid TEXT NOT NULL REFERENCES raw_record,
  revision_uid TEXT NOT NULL REFERENCES source_reference,
  ordinal INTEGER NOT NULL, byte_offset INTEGER NOT NULL, byte_len INTEGER NOT NULL,
  PRIMARY KEY(record_uid, revision_uid)
) STRICT, WITHOUT ROWID;
INSERT INTO record_location_v9 SELECT record_uid, revision_uid, ordinal, byte_offset, byte_len FROM record_location;
DROP TABLE record_location;
ALTER TABLE record_location_v9 RENAME TO record_location;
CREATE INDEX IF NOT EXISTS record_location_revision ON record_location(revision_uid, ordinal);

CREATE TABLE IF NOT EXISTS tool_call_event_v9 (
  call_uid TEXT NOT NULL REFERENCES tool_call, event_uid TEXT NOT NULL REFERENCES event,
  role TEXT NOT NULL, PRIMARY KEY(call_uid, event_uid)
) STRICT, WITHOUT ROWID;
INSERT INTO tool_call_event_v9 SELECT call_uid, event_uid, role FROM tool_call_event;
DROP TABLE tool_call_event;
ALTER TABLE tool_call_event_v9 RENAME TO tool_call_event;
CREATE INDEX IF NOT EXISTS tool_evidence_by_event ON tool_call_event(event_uid);
PRAGMA legacy_alter_table=OFF;

UPDATE schema_manifest SET schema_version=9;
PRAGMA user_version=9;

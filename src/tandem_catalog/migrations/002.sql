-- Align FTS rowids with chunk rowids: O(1) deletes instead of scanning an UNINDEXED column.
CREATE TEMP TABLE fts_rebuild AS
 SELECT c.rowid AS chunk_rowid,f.chunk_id,f.item_id,f.title,f.content
 FROM resource_chunk c JOIN chunk_fts f USING(chunk_id);
DELETE FROM chunk_fts;
INSERT INTO chunk_fts(rowid,chunk_id,item_id,title,content)
 SELECT chunk_rowid,chunk_id,item_id,title,content FROM fts_rebuild;
DROP TABLE fts_rebuild;
DROP TRIGGER chunk_deleted;
CREATE TRIGGER chunk_deleted AFTER DELETE ON resource_chunk BEGIN
 DELETE FROM chunk_fts WHERE rowid = old.rowid;
END;
CREATE INDEX IF NOT EXISTS embedding_text_reuse ON embedding_cache(text_hash, model_id);

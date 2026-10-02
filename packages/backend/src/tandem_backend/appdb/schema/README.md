One idempotent DDL file per module (`catalog_link.sql`, `recommend.sql`, `install.sql`,
`ai.sql`, `platform.sql`, …). Use `CREATE TABLE IF NOT EXISTS … STRICT` and
`CREATE INDEX IF NOT EXISTS`; to change a table add a new table or column-adding
statement guarded by the module's own version table — files are re-applied when edited.

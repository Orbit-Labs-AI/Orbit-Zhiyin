One idempotent DDL file per module (`catalog_link.sql`, `recommend.sql`, `install.sql`,
`ai.sql`, `platform.sql`, …). Use `CREATE TABLE IF NOT EXISTS … STRICT` and
`CREATE INDEX IF NOT EXISTS`. A file is re-applied when its sha256 changes
(`module_schema`), but that only creates what is missing: it never changes an existing table.

To change a table that users already have (add a column, an index on a new column, a
backfill), edit the DDL for fresh databases **and** append a numbered step for the module in
`appdb/migrations.py` (`MIGRATIONS`). `schema_version(module, version)` records how many steps
ran; steps run in order on open, each in its own transaction with its version bump, and must
be no-ops on a fresh database that the DDL already built (`add_column` checks first). Never
reorder or edit a released step; add a new one. Upgrade tests live in `tests/appdb/test_appdb.py`.

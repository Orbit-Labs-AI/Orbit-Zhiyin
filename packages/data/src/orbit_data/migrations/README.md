# orbit.db 迁移

`NNN.sql` 是 `orbit.db`（契约 `orbit-session-v1`）的权威 DDL，按编号顺序在 `Store.__init__`（`store.py`）中应用；`schema_export` 重放同一组文件生成 `../schemas/tables-v1.schema.json`。`analysis/` 与 `catalog/` 是另外两个库的迁移，不在本约定内。

## 版本号由 Store 盖章

- 007 起的每个迁移由 `Store` 在同一事务里执行：`BEGIN IMMEDIATE; <文件内容>; UPDATE schema_manifest SET schema_version=N; PRAGMA user_version=N; COMMIT;`。所以 014 及以后的迁移文件**不写**版本更新语句；版本与 DDL 同时提交，中断的升级可从上一个已发布版本续跑。
- 001–013 中自带的 `UPDATE schema_manifest … / PRAGMA user_version=…` 是历史写法，保留不改（重复设置同一个值无副作用）。
- 新增迁移：新建下一个编号的文件，把 `orbit_data/__init__.py` 的 `SCHEMA_VERSION` 改成该编号，然后运行 `uv run python -m orbit_data.schema_export --output packages/data/src/orbit_data/schemas/tables-v1.schema.json`。
- 007 为保留编号，`Store` 在文件不存在时跳过。
- 只追加列的事实迁移（011–014）经 `_fact_migration` 跳过已存在的同类型列，以兼容未发布的分析预览库。
- SQLite 不能修改 CHECK 约束：改约束用复制表（如 015：建新表、`INSERT … SELECT`、删除旧表、改名），并保留原有行与主键。

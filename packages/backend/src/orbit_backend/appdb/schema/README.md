# App 状态库 Schema

每个模块使用一个幂等 DDL 文件，例如 `recommend.sql`、`install.sql`、`ai.sql`、`platform.sql`。使用 STRICT 表、`CREATE TABLE IF NOT EXISTS` 与相应索引；文件哈希变化时会重新执行，但这些语句不会修改已经存在的表。

## 升级已有数据库

新增列、依赖新列的索引或回填时，同时更新新库 DDL，并在 `appdb/migrations.py` 的 `MIGRATIONS` 为该模块追加编号步骤。`schema_version(module, version)` 记录完成位置；各步骤在事务中连同版本更新执行。

步骤必须能处理已经由最新 DDL 建好的新库，例如先检查再加列。已发布步骤不重排或重写，修正通过新步骤完成。不要将 app.db 迁移混入 data 的 canonical 或 catalog 迁移序列。

升级回归位于 `packages/backend/tests/appdb/test_appdb.py`，需覆盖旧库和新库。所有权见[App 服务](../../../../../../docs/architecture/app-services.md)。

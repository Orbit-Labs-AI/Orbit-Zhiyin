# 契约入口

状态：当前入口；核对基线：main `c008688`。契约修改随所属模块维护。

- [L1–L3 数据契约](data.md)。
- [analysis-input-v1](analysis-inputs.md)。
- [权威会话库迁移](../../packages/data/src/orbit_data/migrations/)。
- [事件 Schema](../../packages/data/src/orbit_data/schemas/event-v1.schema.json)与[字段字典](../../packages/data/src/orbit_data/schemas/tables-v1.schema.json)。
- [TypeScript staging schema](../../packages/connectors/schema/)，仅用于桥接，不能当 canonical 数据库打开。
- API 路由由 [backend/api](../../packages/backend/src/orbit_backend/api/) 实现，运行服务后访问 `/docs` 与 `/openapi.json`。

这里维护语义、边界和版本说明，不复制另一套机器 Schema。改变字段需要同时更新生产者、消费者、相关契约测试与迁移说明。

- 独立资源目录使用 [catalog-v1 字段字典](../../packages/data/src/orbit_data/schemas/catalog-v1.schema.json)与 [catalog 迁移](../../packages/data/src/orbit_data/migrations/catalog/)，由 Catalog 包消费，不混入会话库。

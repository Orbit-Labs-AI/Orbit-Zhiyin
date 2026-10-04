# 数据与接口契约

本区解释已经实现的字段语义和消费边界。数据库迁移、机器 Schema 和当前入口的路由实现是权威来源；早期设计草图不能替代它们。

| 契约 | 说明 | 权威实现 |
| --- | --- | --- |
| [会话数据](data.md) | L0–L3、计量、版本、桥接 | [迁移](../../packages/data/src/orbit_data/migrations/)、[事件 Schema](../../packages/data/src/orbit_data/schemas/event-v1.schema.json)、[字段字典](../../packages/data/src/orbit_data/schemas/tables-v1.schema.json) |
| [分析输入](analysis-inputs.md) | Scope、统计成员、覆盖、证据 | [analysis_input.py](../../packages/data/src/orbit_data/analysis_input.py)、[后端输入适配](../../packages/backend/src/orbit_backend/analytics/inputs.py) |
| [个性化产物](personalization-output.md) | 推荐候选到可解析安装规格 | [install](../../packages/backend/src/orbit_backend/install/)、[安装路由](../../packages/backend/src/orbit_backend/services/routes_install.py) |
| Catalog | 独立资源库与检索 | [目录字段字典](../../packages/data/src/orbit_data/schemas/catalog-v1.schema.json)、[目录迁移](../../packages/data/src/orbit_data/migrations/catalog/)、[模块说明](../modules/catalog/architecture.md) |
| TypeScript staging | Codex 归档生产者的独立格式 | [connector/schema](../../packages/connectors/schema/)、[桥接入口](../../packages/connectors/README.md) |

App gateway 的路由在 [services](../../packages/backend/src/orbit_backend/services/)，报告 API 在 [api](../../packages/backend/src/orbit_backend/api/)。查询 `/docs`、`/openapi.json` 时遵守对应入口的鉴权，不能假设两者路由相同。

DDL 改动先添加迁移，再用 `uv run python -m orbit_data.schema_export --output packages/data/src/orbit_data/schemas/tables-v1.schema.json` 更新字典，并同步生产者、消费者、事件校验和契约测试。历史库应可升级，未知值语义不能在升级中丢失。

返回[文档首页](../README.md)。

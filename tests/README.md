# 跨包与服务流程测试

根 `tests/` 管理跨模块行为，模块内部测试随各包维护。

| 目录 | 验证什么 |
| --- | --- |
| `integration` | data/backend/TypeScript staging 的契约、桥接、范围、分页和来源只读 |
| `e2e` | CLI、API、导入、证据、报告与评价隔离的服务流程 |
| `regression` | 跨包固定行为与分析结果等价性等回归 |

`pnpm check:integration` 会先构建 producer，再运行相应测试；缺构建产物时必须失败。按[测试指南](../docs/development/testing.md)使用 heavy 闸门和适当并发。

Web UI 行为在 `prototypes/advance/tests`，原生 App 验证另见[Mac App](../docs/development/mac-app.md)。服务流程通过不等于系统通知、菜单、权限等原生体验通过。

fixtures 只含构造或充分脱敏数据，不读取默认个人 home，不提交真实日志、数据库、token 或运行截图。

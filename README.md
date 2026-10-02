# Orbit

ActionMesh-AI 的本地跨 Agent 会话分析项目，目标交付为 macOS App。当前可运行部分是统一数据层、Python 后端、CLI、本机 API 和两套独立 UI 原型；尚无原生 App target 或安装包。

## 开始开发

需要 Python 3.13、uv、Node ≥24.7、pnpm 11.25.0；完整检查还需 Swift 5.9+（macOS Command Line Tools）。在仓库根运行：

```sh
bash scripts/bootstrap.sh
uv run tandem demo
pnpm dev --home .local/demo/data
```

Demo 只使用虚构数据。API 默认监听本机 8765 端口，接口说明位于 <http://127.0.0.1:8765/docs>。
上面的启动命令读取刚生成的 Demo 数据库。使用自己的已初始化开发库时可运行 `pnpm dev --home .tandem`；实际来源须显式执行 `tandem ingest` 才会导入。
完整 CLI、真实来源授权和旧库兼容说明见[使用指南](docs/development/usage.md)。

## 仓库入口

| 位置 | 职责 |
| --- | --- |
| [packages/backend](packages/backend/README.md) | 应用编排、API/CLI、画像、特征分析、推荐、报告 |
| [packages/data](packages/data/README.md) | 原生来源、L0–L3、canonical SQLite、查询与导入服务 |
| [packages/catalog](packages/catalog/README.md) | 资源采集、版本、索引与检索 |\n| [packages/catalog-macos](packages/catalog-macos/README.md) | macOS Swift 异步客户端 |\n| [packages/connectors](packages/connectors/README.md) | TypeScript Codex staging producer |
| [prototypes](prototypes/README.md) | Lite / Advance 示例数据原型 |
| [tests](tests/README.md) | 跨模块集成与服务流程验收 |
| [evals](evals/README.md) | 质量评测及显式启用的真实数据验收 |
| [benchmarks](benchmarks/README.md) | 性能与内存评测 |
| [scripts](scripts/README.md) | 启动、检查与安装验证入口 |
| [docs](docs/README.md) | 架构、契约、开发指南、计划、研究与版本记录 |

正式桌面入口未来放在 `apps/desktop/`；Catalog 和 Swift 客户端已接入，但仍没有原生 App target。

## 验证

```sh
pnpm check                 # 模块、跨包、服务流程、文档、构建与安装后验收
pnpm check:integration     # 只跑跨包与服务流程，自动构建 staging producer
pnpm --filter @tandem/prototype-advance exec playwright install chromium
pnpm check:ui              # Lite 数据检查 + Advance 浏览器行为测试
```

CI 调用同一套命令。测试不自动读取本机 Agent 历史；性能与真实数据评测单独运行。
分类和执行条件见[测试指南](docs/development/testing.md)。

## 集成约定

- [前端指标计算规则](docs/modules/analytics/presentation-metrics.md)：八族特征、画像与瓶颈的呈现口径。
- [UI 分析与端到端验收](docs/modules/analytics/analysis-products.md)：工具占比、调用转移、情绪表达及开发者本地 session 验证。
- [分析补全建议](docs/plans/analysis-review.md)：八族边界与 Lite / Advance 的分析功能缺口。
- [后端缺口](docs/plans/backend-gap.md)：数据、分析、推荐与横切后端程序对照两版 UI 的差距与补齐顺序。
- [模块接入表](docs/architecture/module-map.md)：功能、入口、实现、契约、测试与缺口。
- [目录迁移说明](docs/development/structure-migration.md)：活跃分支如何接入新结构。
- [设计资料](docs/design/README.md)：Lite 属于 `genius-FXC`，Advance 属于 `yhyfhgs`；MVP 范围仍由三位成员共同确认。
- [协作规则](AGENTS.md)：`main` 通过 PR 更新，合并与关闭由 `yhyfhgs` 决定。

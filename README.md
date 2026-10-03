<p align="center"><img src="docs/design/logo/orbit-icon.png" width="96" alt="Orbit"></p>

# Orbit

[![App integration](https://github.com/ActionMesh-AI/Hackathon/actions/workflows/backend.yml/badge.svg?branch=main)](https://github.com/ActionMesh-AI/Hackathon/actions/workflows/backend.yml)
[![Connector runtime matrix](https://github.com/ActionMesh-AI/Hackathon/actions/workflows/connectors.yml/badge.svg?branch=main)](https://github.com/ActionMesh-AI/Hackathon/actions/workflows/connectors.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Stage: Prototype](https://img.shields.io/badge/stage-prototype-orange)](docs/product/scope.md)
[![Platform: macOS](https://img.shields.io/badge/platform-macOS-000000?logo=apple&logoColor=white)](docs/product/scope.md)
[![Python: 3.13](https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Node.js: ≥24.7](https://img.shields.io/badge/node.js-%E2%89%A524.7-339933?logo=nodedotjs&logoColor=white)](package.json)
[![Conventional Commits: 1.0.0](https://img.shields.io/badge/commits-Conventional_Commits_1.0.0-FE5196)](https://www.conventionalcommits.org/en/v1.0.0/)

ActionMesh-AI 的本地跨 Agent 会话分析 macOS App：读取本机 Claude Code、Codex 等 Agent 的会话记录，生成协作人格画像与会话轨迹，并推荐 Skills、Hooks、规则等可一键安装、可撤销的改进。数据只在本机处理。

当前可运行部分是统一数据层、Python 后端、CLI、本机 API 和一个 UI 原型（Lite / Advance 同一个 App，示例数据）；尚无原生 App target 或安装包。产品名为 Orbit，代码标识（`orbit_*` 包、`orbit` CLI、数据目录）暂沿用旧代号，见[品牌](docs/design/brand.md#名称)。

## 开始开发

需要 Python 3.13、uv、Node ≥24.7、pnpm 11.25.0；完整检查还需 Swift 5.9+（macOS Command Line Tools）。在仓库根运行：

```sh
bash scripts/bootstrap.sh
uv run orbit demo
pnpm dev --home .local/demo/data
```

Demo 只使用虚构数据。API 默认监听本机 8765 端口，接口说明位于 <http://127.0.0.1:8765/docs>。
上面的启动命令读取刚生成的 Demo 数据库。使用自己的已初始化开发库时可运行 `pnpm dev --home .orbit`；实际来源须显式执行 `orbit ingest` 才会导入。
完整 CLI、真实来源授权和旧库兼容说明见[使用指南](docs/development/usage.md)。

## 仓库入口

| 位置 | 职责 |
| --- | --- |
| [packages/backend](packages/backend/README.md) | 应用编排、API/CLI、画像、特征分析、推荐、报告 |
| [packages/data](packages/data/README.md) | 原生来源、L0–L3、canonical SQLite、查询与导入服务 |
| [packages/catalog](packages/catalog/README.md) | 资源采集、版本、索引与检索 |
| [packages/catalog-macos](packages/catalog-macos/README.md) | macOS Swift 异步客户端 |
| [packages/connectors](packages/connectors/README.md) | TypeScript Codex staging producer |
| [prototypes](prototypes/README.md) | Lite / Advance 统一 App 原型（示例数据） |
| [tests](tests/README.md) | 跨模块集成与服务流程验收 |
| [evals](evals/README.md) | 质量评测及显式启用的真实数据验收 |
| [benchmarks](benchmarks/README.md) | 性能与内存评测 |
| [scripts](scripts/README.md) | 启动、检查与安装验证入口 |
| [docs](docs/README.md) | 全部文档导航：产品与设计、架构与契约、开发、模块、方案、审计、调研与历史 |

正式桌面入口未来放在 `apps/desktop/`；Catalog 和 Swift 客户端已接入，但仍没有原生 App target。

## 验证

```sh
pnpm check                 # 模块、跨包、服务流程、文档、构建与安装后验收
pnpm check:integration     # 只跑跨包与服务流程，自动构建 staging producer
pnpm --filter @orbit/prototype-advance exec playwright install chromium
pnpm check:ui              # Lite 数据检查 + Advance 浏览器行为测试
```

CI 调用同一套命令。测试不自动读取本机 Agent 历史；性能与真实数据评测单独运行。
分类和执行条件见[测试指南](docs/development/testing.md)。

## 集成约定

- [前端指标计算规则](docs/modules/analytics/presentation-metrics.md)：八族特征、画像与瓶颈的呈现口径。
- [UI 分析与端到端验收](docs/modules/analytics/analysis-products.md)：工具占比、调用转移、情绪表达及开发者本地 session 验证。
- [分析补全建议](docs/plans/analysis-review.md)：八族边界与 Lite / Advance 的分析功能缺口。
- [后端缺口](docs/audits/backend-gap.md)：数据、分析、推荐与横切后端程序对照两版 UI 的差距与补齐顺序。
- [模块接入表](docs/architecture/module-map.md)：功能、入口、实现、契约、测试与缺口。
- [目录迁移说明](docs/development/structure-migration.md)：活跃分支如何接入新结构。
- [设计资料](docs/design/README.md)：Lite 属于 `genius-FXC`，Advance 属于 `yhyfhgs`，两版是同一个 App；[品牌](docs/design/brand.md)与 [Demo 说明](docs/design/demo.md)。
- [协作规则](AGENTS.md)：`main` 通过 PR 更新，合并与关闭由 `yhyfhgs` 决定。

## 参与与协作

- [贡献指南](CONTRIBUTING.md)：开发环境、分支与提交规范、验证要求和 PR 流程。
- [行为准则](CODE_OF_CONDUCT.md)：讨论、审查与协作中的基本约定。
- [安全政策](SECURITY.md)：安全问题的私下报告方式与数据保护要求。
- [问题与建议](https://github.com/ActionMesh-AI/Hackathon/issues/new/choose)：使用 Bug / 功能建议模板提供可复现的信息。

CI badges 指向 `main` 的实际工作流状态；私有仓库的状态徽章不能在外部站点展示。

## 许可证

Orbit 原创代码与文档采用 [Apache License 2.0](LICENSE)。仓库当前仍为私有，访问权限与代码许可分别管理。`third_party/` 引用项目及其他带有独立许可声明的第三方材料遵循各自许可证，项目许可证不覆盖这些声明。

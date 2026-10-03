# Orbit 文档导航

状态：现行目录约定 · 维护者 `yhyfhgs` · 2026-10-02 整理（产品改名 Orbit、设计资料拆分、审计与模块文档归位）

本页列出 `docs/` 下的全部文档。先看「现行」再看「方案」：**现行**描述当前代码与约定；**方案**是设计与待完成工作，不能直接等同当前能力；**审计**是某一基线上的核对结果；**调研**与**历史**只作参考。

产品名统一写 **Orbit**（全名 Orbit·知音）；Python 包、CLI、环境变量、数据目录等代码标识自 2026-10-03 起同样统一为 `orbit`，旧名的兼容见[品牌](design/brand.md#名称)。

## 1. 产品与设计（现行）

| 文档 | 内容 |
| --- | --- |
| [产品与交付边界](product/scope.md) | 已实现的数据链路、原型与正式 App 的差距 |
| [设计资料](design/README.md) | Lite / Advance 设计归属、存档记录与设计文档入口 |
| [品牌](design/brand.md) | Orbit 名称、代码标识与旧名兼容、标志、字标与 App 图标、字体 |
| [路演组件素材](design/ppt-assets/README.md) | UI 页面、独立组件、品牌与矢量素材的提取和使用 |
| [Demo 说明](design/demo.md) | 统一 App 怎么看、交互清单、修改与发布 |
| [画板与设计决定](design/boards.md) | Advance v1 画板索引、设计决定、v1 之后的现行决定 |
| [Lite 审查](design/lite-review.md) | Lite 原稿的需求对应、交互说明与自查 |

## 2. 架构与契约（现行）

| 文档 | 内容 |
| --- | --- |
| [模块接入表](architecture/module-map.md) | 依赖方向、功能入口、实现、契约、测试与缺口 |
| [后端怎么工作](architecture/backend.md) | 报告编排、画像与推荐的默认入口 |
| [数据流程](architecture/data-pipeline.md) | macOS App 的模块化数据入口、存储位置与兼容 |
| [App 服务层](architecture/app-services.md) | 本地服务封装、UI 衔接、分析快照与网关 |
| [契约入口](contracts/README.md) | 机器 Schema 位置与修改规则 |
| [会话数据契约](contracts/data.md) | L1–L3 字段语义 |
| [analysis-input-v1](contracts/analysis-inputs.md) | 分析输入包 |

## 3. 开发（现行）

| 文档 | 内容 |
| --- | --- |
| [贡献指南](../CONTRIBUTING.md) | 开发环境、提交规范、检查与 PR 流程 |
| [行为准则](../CODE_OF_CONDUCT.md) | 协作约定与争议处理 |
| [安全政策](../SECURITY.md) | 漏洞报告渠道、支持范围与隐私保护 |
| [使用指南](development/usage.md) | CLI、真实来源授权、旧库兼容 |
| [测试与验收](development/testing.md) | 检查分类、执行条件与 CI |
| [导入流程](development/import-pipeline.md) | 导入状态机、阶段与数字含义、v0.0.2 导入循环的根因与排障 |
| [后端九小时改进计划](development/backend-improvement-plan.md) | 契约、任务关系、语义、鲁棒性与推荐效用验收 |
| [分析与推荐鲁棒性验收](development/analytics-robustness.md) | 受控扰动、证据关系、全量增量、损坏恢复与规模 |
| [过去到未来推荐 Benchmark](../evals/benchmark/README.md) | 效用、Regret、时间与个性化的统一评测协议 |
| [链路验收](development/acceptance.md) | 本地 Codex 记录 → 证据 → 画像 → 推荐的验收步骤 |
| [目录迁移](development/structure-migration.md) | 活跃分支如何接入新结构（含本次文档搬迁） |

## 4. 模块说明（现行）

算法、验证与限制，按模块分目录，入口见[模块说明](modules/README.md)。

| 模块 | 文档 |
| --- | --- |
| 数据 | [Agent 连接器](modules/data/agent-connectors.md)、[本地数据服务](modules/data/data-services.md)、[来源索引与轨迹读取](modules/data/indexed-trajectories.md)、[本机安装清单](modules/data/local-inventory.md)、[安装清单测试](modules/data/inventory-testing.md)、[安装清单复核](modules/data/inventory-audit.md) |
| 分析 | [统计与分析记录](modules/analytics/statistics-history.md)、[画像推导](modules/analytics/profiling.md)、[特征分析](modules/analytics/feature-analytics.md)、[特征与 Skill 诊断](modules/analytics/fact-diagnostics.md)、[瓶颈特征](modules/analytics/bottleneck-features.md)、[Signal 层](modules/analytics/signals.md)、[前端指标](modules/analytics/presentation-metrics.md)、[UI 分析与验收](modules/analytics/analysis-products.md)、[原始 UI 对应](modules/analytics/original-ui-mapping.md)、[数字的含义](modules/analytics/modeling.md)、[Preference](modules/analytics/preference.md)、[Task](modules/analytics/task.md)、[任务领域分类](modules/analytics/task-taxonomy.md)、[Instruction 验收](modules/analytics/instruction-validation.md)、[验证范围](modules/analytics/validation.md) |
| 资源目录 | [Catalog 架构](modules/catalog/architecture.md)、[十万级公共资源索引](modules/catalog/large-corpus.md)、[实测记录](modules/catalog/validation.md) |
| 推荐 | [推荐引擎](modules/recommendation/engine.md)、[偏好与收益测试](modules/recommendation/validation.md)、[个性化产物输出接口](contracts/personalization-output.md) |
| 评测 | [读者评价](modules/evaluation/reader-review.md) |

## 5. 方案（不等同当前能力）

| 文档 | 内容 |
| --- | --- |
| [模块契约](plans/module-contract.md) | 分层、feature ID、字段级契约与写法模板（四份模块方案的共同依据） |
| [功能映射与分工](plans/feature-map.md)（[CSV](plans/feature-map.csv)） | Demo 前端功能 → 后端 feature、三人分工与里程碑 |
| [数据获取与标准化](plans/data-acquisition.md) | 连接器、四层无损模型、资源目录与存储默认值 |
| [分析模块](plans/analysis-module.md) | 跨 Agent / 项目 / 模型的会话分析体系 |
| [推荐模块](plans/recommendation-module.md) | 用分析结果做匹配推荐 |
| [AI 接入](plans/ai-module.md) | 分析侧与推荐侧如何用模型 |
| [评测](plans/evaluation-module.md) | Benchmark 与评测（EV） |
| [分析补全建议](plans/analysis-review.md) | 八族边界与 Lite / Advance 的分析功能缺口 |

## 6. 审计（某一基线上的核对）

| 文档 | 内容 |
| --- | --- |
| [后端缺口](audits/backend-gap.md) | 数据、分析、推荐与横切程序对照两版 UI 的差距与补齐顺序 |
| [数据模块审计](audits/data-audit.md) | DT 完成度、导入性能与优化任务包 |
| [分析模块审计](audits/analysis-audit.md) | AN 功能覆盖、持久化与性能 |
| [导入可靠性审计](audits/ingestion-reliability-2026-10-03.md) | 七类 Agent 内容覆盖、发现补扫、捕获重试、标准化与开发日志 |
| [分析与 AI 可靠性审计](audits/analysis-ai-reliability-2026-10-03.md) | 范围隔离、证据校验、专业分析模板和 UI 输入输出映射 |
| [推荐与资源库可靠性审计](audits/recommendation-reliability-2026-10-03.md) | 多路召回、质量维度、目录扩充、AI 专家建议和评测边界 |
| [端到端集成审计](audits/integration-reliability-2026-10-03.md) | 设置并发、问答范围、页面接线、交互证据与本轮验收 |
| [向量规模审计](audits/catalog-vector-scale-2026-10-03.md) | 100K 构造基准、真实 E5 吞吐、分片物化与覆盖口径 |

## 7. 调研

| 文档 | 内容 |
| --- | --- |
| [调研总结](research/landscape.md) | 主流 Agent、设计哲学、开源项目与算法选型 |
| [竞品分析](research/competitors.md) | 7 类约 60 个产品与开源项目 |
| [先借鉴哪些项目](research/backend-research.md) | 已核对的开源实现与取舍 |
| [Apple macOS 指南对照](research/apple-macos-guidelines.md) | HIG 与 AppKit / WebKit 文档对照 Orbit 原生壳与 UI 的 Mac 习惯符合度 |
| [Agent 会话格式对比](research/agent-sessions/README.md) | [Claude Code](research/agent-sessions/claude-code.md)、[Codex](research/agent-sessions/codex.md)、[DSH](research/agent-sessions/dsh.md)、[Hermes](research/agent-sessions/hermes-agent.md)、[OpenCode](research/agent-sessions/opencode.md)、[pi](research/agent-sessions/pi.md) 的落盘格式 |

## 8. 历史

| 文档 | 内容 |
| --- | --- |
| [后端版本记录](releases/backend/README.md) | v0.1–v0.13.6 当时的交付记录 |
| [MVP 首版计划](archive/backend-mvp-plan.md) | 已被模块接入表与开发指南替代 |

## 写作约定

- 新增关键文档注明状态、适用模块、维护者与核对版本，并在本页登记。
- 包内 README 说明如何使用该模块，根 README 说明如何启动整个项目；同一规范只维护一个正文，其他位置链接引用。
- 历史与审计文档保留当时的基线和数字，不随代码回改；结论过时时在现行文档里说明。

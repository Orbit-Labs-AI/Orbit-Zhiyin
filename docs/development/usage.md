# 使用指南

ActionMesh AI 团队的 Hackathon 比赛项目。

## 项目资料

- 仓库初始化：2026-09-30
- 设计参考：[docs/design](../design/README.md)（Lite / Advance 的设计归属、Demo 与视觉案例）
- 数据方案：[docs/plans/data-acquisition.md](../plans/data-acquisition.md)（模块 1、5 的会话与生态数据获取、标准化、基础统计与存储）
- 会话格式调研：[docs/research/agent-sessions](../research/agent-sessions/README.md)（pi、Hermes Agent、DeepSeek Harness、OpenCode、Codex、Claude Code 的会话与轨迹数据形态，源码级对比）
- 分析开发输入：[docs/contracts/analysis-inputs.md](../contracts/analysis-inputs.md)（输入来源、L2/L3 字段解释、统计口径与当前实现差异）
- Codex 数据连接器：[packages/connectors](../../packages/connectors/README.md)（只读采集、L0/L1 归档、analysis-input-v1 标准事件与派生表）
- 会话数据实现：[packages/data](../../packages/data/README.md)（实际 SQLite 数据库、L0/L1 归档、L2/L3 预处理和 connector 桥接）
- App 数据入口：[模块边界与接入方式](../architecture/data-pipeline.md)（macOS、统一 workspace、分页查询、重算与旧库兼容）

## App 版本

| 版本 | 设计来源 | 设计参考 |
| --- | --- | --- |
| **Lite** | `genius-FXC` 的个人协作 Benchmark 设计（[PR #12](https://github.com/ActionMesh-AI/Hackathon/pull/12)） | [Lite Demo](../../prototypes/lite/tandem-benchmark-demo.html)、[范围与审查](../design/lite-review.md) |
| **Advance** | `yhyfhgs` 的桌面 App 设计 | [Advance Demo](../../prototypes/advance/tandem-demo.html)、[视觉案例 v1](../design/visual-cases-v1/) |

版本名统一使用 **Lite / Advance**；历史材料中的 `Advanced` 指 **Advance**。这项规定仅记录现有设计的版本归属，两套设计并行保留，具体说明见[设计资料](../design/README.md)。画板与 Demo 仍是使用示例数据的设计参考，MVP 功能范围由三位成员共同确认；现有界面与交互的调整由对应设计任务另行推进。

## 先试后端

Tandem 面向 macOS App。后端通过统一 L0–L3 数据层读取本地 Agent 记录，按项目和模型整理，再分析协作要求、卡点与资源。支持 Codex、Claude Code、DeepSeek Harness、pi、Hermes、OpenCode、Kimi；实际信息覆盖以原生证据为准。前端 [Lite Demo](../../prototypes/lite/tandem-benchmark-demo.html) 与 [Advance Demo](../../prototypes/advance/tandem-demo.html) 仍是设计参考。

分析入口遵循 [analysis-input-v1](../contracts/analysis-inputs.md)，目标契约与当前存储支持范围分开说明。

需要 Python 3.13 和 uv（`.python-version` 固定运行时）。backend 与 data 共用根目录 `uv.lock`：

```sh
uv sync --locked --all-packages --dev
uv run tandem demo
uv run tandem evaluate
uv run pytest -q packages/backend/tests tests
uv run pytest -q packages/data/tests
```

demo 使用虚构数据，CLI 按“数据 → 画像 → 瓶颈 → 推荐”直接展示。结果目录同时保存 `profile.md / bottlenecks.md / process.md / report.md` 及对应 JSON。评价结果在 `.local/evaluation.json`。通过自动检查表示已排除部分明显错误，仍需要读者验收。

```sh
.venv/bin/tandem demo --view profile
.venv/bin/tandem demo --view bottlenecks
.venv/bin/tandem demo --view process
```

不指定想要哪个 skill，也能先生成画像与瓶颈；资源目录只参与最后的匹配。推导过程见 [画像怎样产生](../modules/analytics/profiling.md)。这次展示使用 CLI，无需接入前端。

`evaluate` 跑文字对照、整条链路的构造场景，以及新增措辞和组合要求；`--suite pipeline / probe` 可以分别选择。结果保留误报、漏报和证据检查。这些样例用于改进规则；在独立临时数据库中运行，正常数据不会被改写。

## 导入本地数据

```sh
uv run tandem discover
uv run tandem ingest --agent codex --root "$HOME/.codex"
uv run tandem ingest --agent claude_code --root "$HOME/.claude"
uv run tandem verify
uv run tandem report
uv run tandem analytics --display-timezone Asia/Shanghai
uv run tandem serve
```

`discover` 只列来源，`ingest` 才启用指定根目录。CLI、App 和 API 默认共用 `~/Library/Application Support/Tandem/`（`tandem.db` 与 `raw/`），可用 `TANDEM_HOME` 或 `--home` 指定；仓库开发可用 `--home .tandem`。报告在 `.local/report/`，API 文档在 <http://127.0.0.1:8765/docs>。真实数据只留在本地，API 默认只监听本机。

统一数据层完整保留 L0，分析用 `analytics --from-ts / --until-ts`（UTC 毫秒、右端不包含）与 `--exclude-session`（canonical session UID）选择样本，范围与数据版本随结果返回。不要把评价中用户给出的标准重新当作历史偏好导入。旧命令 `import --codex-home` 默认也进入新数据层。

已有 MVP 库需显式通过 `--db .local/tandem.sqlite` 使用兼容模式，原有持久采样策略保持原样。新入口不会改写旧库或静默忽略旧采样参数。迁移需显式从原始来源或 staging 重新导入；旧 JSON ledger 无法补出缺失的 L0/L1。

## 核对推荐来源

离线目录自带 10 个公开来源的固定版本。需要重新核对时运行：

```sh
.venv/bin/tandem catalog-refresh
```

它从 GitHub 官方 API 读取仓库信息和 Markdown，核对版本与内容哈希，结果保存在 `.local/catalog.json`。`--latest` 才会更新到当前默认分支，`--resource-id humanizer-zh` 可以只核对一个来源。导入和分析不需要联网。

目录包括规则、skills、插件、MCP、hooks、基准和代理。现阶段只对分析中有明确匹配的 skill 建议一次小范围试用：必须同时有画像证据、瓶颈证据，以及适合场景和语言的资源。真实收益需要另测。

## 看实现与版本报告

- [Preference 与 Task 特征族：实现及五类验证](../modules/analytics/validation.md)
  — 新增 `/v1/analytics/preferences`、`/v1/analytics/tasks`；证据、范围、版本与未知状态可追溯。
- [Feature Analytics MVP：真实数据案例、特征字典与输入缺口](../modules/analytics/feature-analytics.md)
  — 运行 `.venv/bin/tandem --db .local/history.sqlite analytics --display-timezone Asia/Shanghai --output .local/feature-analytics/analytics.json`；新增 `/v1/analytics/*`，未知值不填零。
- [先验这条链路](../development/acceptance.md)
- [今晚先跑通什么](../archive/backend-mvp-plan.md)
- [当前版本：完整过滤凭据并核对交付证据](../releases/backend/v0.13.6.md)
- [怎样验“说人话”](../modules/evaluation/reader-review.md)
- [各版记录](../releases/backend/README.md)
- [模块与接口](../architecture/backend.md)
- [这些数字说明什么](../modules/analytics/modeling.md)
- [调研与取舍](../research/backend-research.md)

官方 dsh 源码作为固定版本的 submodule 放在 `third_party/deepseek-harness`。需要查源码时运行 `git submodule update --init --depth 1`；它不参与后端启动。

## 使用标准 Codex Connector

采集进程使用 TypeScript、Node ≥24.7 与 pnpm，输出独立 staging 库；通过 `packages/data` 的归档桥接进入统一数据库，避免两套 schema 共写同一个文件。

```sh
cd packages/connectors
pnpm install --frozen-lockfile
pnpm check
pnpm tandem --help
```

初始化、增量导入、重算、监听、数据契约和真实来源验证范围见 [Connector README](../../packages/connectors/README.md)。

已有 staging 用 `uv run tandem import-connector --connector-home .local/codex-staging` 接入，源文件已删除也可从归档处理。普通 `tandem ingest --agent codex` 可直接使用 Python canonical connector。两种采集方式最终使用同一份 Python L2/L3 规则，两个包不得共写同一份 SQLite。
- [多 Agent 数据导入模块与一键验收](../modules/data/agent-connectors.md)（统一 Python canonical 链路）

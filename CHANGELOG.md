# 更新日志

本文件记录 **Orbit（Orbit·知音）** 桌面 App 的版本发布与主线重要变更。

Orbit·知音已于 2026-10-14 停止新功能开发，仅保留维护性更新。各版本的完整安装包、校验值与许可快照见 [GitHub Releases](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases) 及 `releases/<版本>/`（0.0.4 起）；发布规范见 [RELEASING.md](RELEASING.md)。早期后端阶段交付记录（`v0.1`–`v0.13.6`，编号独立于桌面 `0.0.x`）见 [docs/releases/backend/README.md](docs/releases/backend/README.md)。

## 未发布

### 维护与文档

- 标明维护状态并清理 `AGENTS.md` 中的子代理规则与历史记录（[#115](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/115)）。
- 移除界面原型中已下线的 `Orbit-Labs-AI/Confluo` 链接（[#116](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/116)）。

## 0.0.5 — 2026-10-22

[GitHub Release](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/tag/v0.0.5) · [版本说明](releases/0.0.5/README.md) · [变更对比](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/compare/v0.0.4...v0.0.5)

### 新增

- 首次提供独立的 **Windows 预览版**安装包（Node 网关 + Microsoft Edge `--app` 窗口，首次启动空白，随后只读扫描本机 Claude Code / Codex / DeepSeek Harness 会话日志；[#114](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/114)）。
- Lite / Advance 合并为一套侧栏，新增渲染后中英双语界面（默认英文，可在「显示 → 语言」或设置中切换中文；[#113](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/113)）。

### 修复

- 数据层在 `derive()` 写入 `session` 前按最终值归一化 `timezone` / `timezone_source`，导入发布不再被 SQLite CHECK 拒绝（`REDUCER_VERSION` 1.9.2、`READER_VERSION` 1.3；[#112](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/112)）。
- 修复会话轨迹列表在窗格模式下不滚动、选中行不滚入视野，以及默认英文时 `<html lang>` 仍为 `zh-CN` 的问题（[#113](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/113)）。
- 合入 `v0.0.4` 发布后的集中排查修复（[#101](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/101)）：
  - **数据与隐私**：处理原生 JSON 中未配对的 UTF-16 代理项与 NaN/Infinity；修正 Claude Code 首行记录与旧版 summary 行解析；Python 与 TypeScript staging 两端补齐截断私钥块、OpenPGP 私钥及含 `@` 的 URL 密码脱敏。
  - **分析、推荐与 AI**：项目对比日均会话按请求时区本地日计数；人格页超大天数周期返回 422；概览刷选 `from_ts=0` 按纪元起点计算；分词器不再读写系统临时目录；已装 KB 方案不再重复推荐；AI 缓存按引擎和模型区分；常驻 token 占比不超过 100%。
  - **平台与界面**：工具明细、CSV 导出、菜单栏、引导和揭晓排除已停用来源；诊断包隐藏相对路径；旧版数据库启动时自动重建；库重建或读取失败时显示明确错误态。

### 仓库与文档

- 统一 Orbit / Orbit Labs 品牌名称与仓库入口（[#105](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/105)、[#106](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/106)、[#107](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/107)）。
- 合并原发布仓库至 `Orbit-Zhiyin`，说明 Orbit·知音自 2026-10-14 停止开发并调整 TeamHub 文档分工（[#108](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/108)、[#109](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/109)、[#110](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/110)、[#111](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/111)）。
- 清理死代码、未使用的兼容层与 fixture（[#102](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/102)、[#103](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/103)）。

> 注：标签 `v0.0.5`（`358182a9`）早于随后在 `release/v0.0.5`（[#114](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/114)）上补交的 macOS 干净重建 DMG/ZIP 说明与校验值更新，最终发布产物与校验值以 `releases/0.0.5/README.md` 及 GitHub Release 为准。

## 0.0.4 — 2026-10-04

[GitHub Release](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/tag/v0.0.4) · [版本说明](releases/0.0.4/README.md) · [变更对比](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/compare/v0.0.3...v0.0.4)

### 协作人格与展示

- 引入 16 型人格之花、独立 Agent 曲线与徽章，增加人格切换与首次揭晓动效（[#74](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/74)、[#83](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/83)、[#86](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/86)）。
- 分享卡、菜单栏及桌面小组件同步新设计，支持减少动态效果并保持 Lite / Advance 共用界面体系（[#72](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/72)、[#73](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/73)、[#75](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/75)、[#76](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/76)、[#78](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/78)、[#81](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/81)）。

### 分析、推荐与数据

- 完成 Tandem → Orbit 代码标识与品牌统一，并保留旧目录迁移兼容（[#79](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/79)）。
- 改进时间与筛选范围处理、特征与画像缓存及并发物化，改进 AI 预算预留、取消、重试与问答迟到响应处理（[#88](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/88)、[#92](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/92)、[#93](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/93)）。
- 改进会话发现、来源映射、Hook 与通知脱敏、数据清除与设置并发更新；资源清单支持独立 `command` / `agent` 类型及旧清单迁移。
- 保留省时 / 省 token 估算与个性化输出，整合 Catalog 来源、十万级资源全文向量化与多路检索及安装限制，改进安装失败回滚与效果跟踪（[#84](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/84)、[#85](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/85)、[#91](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/91)、[#95](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/95)）。[#94](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/94) 的历史技能学习功能已由 [#98](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/98) 撤回，本版不包含。

### macOS 桌面宿主与文档

- 改进退出清理、退出期间重启处理、helper 崩溃重试与原生标题栏 / 全屏适配。
- 重写 README 并按读者任务重组文档（[#96](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/96)）。

## 0.0.3 — 2026-10-03

[GitHub Release](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/tag/v0.0.3) · [变更对比](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/compare/v0.0.2...v0.0.3)

### 导入稳定性

- 修复 0.0.2 重复整源导入及 Codex 导入途中文件变化导致回滚的问题（[#71](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/71)）。
- 新数据尚未发布时保留显示上一份已发布数据，不再出现 `projection_pending` 与「0 个会话」。
- 细化导入进度展示与 15 分钟卡住自动停止重试；恢复设置内「立即重新索引」。
- 每次导入后截断 SQLite WAL 日志并清理中断遗留的临时目录。

### 交互、界面与后端

- 首次安装默认进入 Lite，并将界面偏好持久化到 `ui-prefs.json`；补齐菜单栏「文件」「帮助」「前往」及快捷键；支持窗口四边与标题栏空白处拖动；导入期间不再整页刷新（[#67](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/67)、[#68](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/68)、[#71](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/71)）。
- 协作人格 1 个会话即可得出 4 字母类型；字体切换为系统字体（苹方 / SF Pro / SF Mono）；侧栏重排并用高频词词云替换「语义主题」与「情绪前因」；设置接入登录启动、菜单栏角标、通知与外观。
- 合入后端分析集成与审计改进（[#58](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/58)、[#63](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/63)、[#65](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/65)、[#70](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/70)），补充社区规范文档（[#66](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/66)、[#69](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/69)）。

## 0.0.2 — 2026-10-03

[GitHub Release](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/tag/v0.0.2) · [变更对比](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/compare/v0.0.1...v0.0.2)

- **支持 macOS 14 Sonoma**：最低系统要求从 macOS 15.0 降至 14.0，并在构建时校验包内全部原生二进制的最低系统声明（[#61](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/61)、[#62](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/62)）。
- **导入与分析提速**：首次导入事件改为批量写入并合并外键校验；分析冷算在各时间范围间复用中间结果（[#60](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/60)）。

## 0.0.1 — 2026-10-02

[GitHub Release](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/tag/v0.0.1)

- **首个可安装版本**（Apple Silicon，macOS 15+；[#53](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/pull/53)）：本地读取 Claude Code、Codex、DeepSeek Harness、pi、Kimi、Hermes、OpenCode 会话记录，支持渐进导入。
- **Advance / Lite 一体界面**：支持侧栏一键切换（`⌃⌘L`），提供概览、16 型协作人格、会话轨迹与对比、工具调用、项目习惯、情绪语义、带证据的建议与资源库（支持计划 → 预览 diff → 写入 → 撤销）、AI 生成工坊、问答与命令面板（`⌘K`）。
- **原生体验**：菜单栏面板、悬浮 HUD、桌面小组件（`⌥⌘H` / `⌥⌘W`）、系统通知与本地报告 / CSV / 分享卡导出。

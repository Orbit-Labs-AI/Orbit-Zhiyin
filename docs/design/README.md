# 设计资料

本目录存放 Hackathon 产品（暂定名 **Tandem / 同频**）的设计参考与存档：一个本地的跨 Agent 会话分析 Mac App，做协作人格分析、会话轨迹可视化，并给出 Skills、Hooks、规则等优化建议。

> App 版本与设计归属按下表执行。画板与 Demo 的具体内容仍是视觉与交互参考，MVP 功能范围须由 `yhyfhgs`、`MistyHuang03`、`genius-FXC` 三人共同确认。
>
> Advance 的画板与 Demo 是 2026-10-01 定下的视觉与交互参考。之后确定的数据口径、分析方法和页面改动见下文「v1 之后的决定」，与画板不一致时以那里列出的文档为准。

## App 版本与设计归属

2026-10-02，`yhyfhgs` 明确以下对应关系：

| App 版本 | 设计来源 | 当前设计入口 |
| --- | --- | --- |
| **Lite** | `genius-FXC` 的个人协作 Benchmark 设计（[PR #12](https://github.com/ActionMesh-AI/Hackathon/pull/12)） | [`../../prototypes/lite/tandem-benchmark-demo.html`](../../prototypes/lite/tandem-benchmark-demo.html)；范围与审查见 [`lite-review.md`](lite-review.md) |
| **Advance** | `yhyfhgs` 的桌面 App 设计 | [`../../prototypes/advance/tandem-demo.html`](../../prototypes/advance/tandem-demo.html)、源码 [`../../prototypes/advance/src/`](../../prototypes/advance/src)、画板存档 [`visual-cases-v1/`](visual-cases-v1/) |

- 版本名统一使用 **Lite / Advance**；历史材料中的 `Advanced` 指 **Advance**。
- 个人 Benchmark Demo 对应 Lite，原版桌面 Demo 与 v1 画板对应 Advance。两套设计并行保留，引用设计或功能说明时注明适用版本。
- 版本归属保持不变；结构整理已将可运行原型迁移到 prototypes，并保留界面与交互行为。界面与交互的调整由对应设计任务另行推进，版本归属本身不新增功能或替代 MVP 范围确认。

## 存档记录

| App 版本 | 设计存档 | 日期 | 内容 | 位置 |
| --- | --- | --- | --- | --- |
| Advance | v1 | 2026-10-01 | Mac App 视觉案例：5 页、26 块画板，含逐屏交互标注 | 在线画布、`visual-cases-v1/` |
| Advance | v1.1 | 2026-10-01 | 修正 A5「跨项目对比」的拟合线与相关系数（标注 r = 0.71 与示例点不符，按示例点重算为 0.91） | 同上 |
| Advance | v1.2 | 2026-10-01 | 把视觉案例做成可交互 HTML Demo，所有页面和按钮都有逻辑 | 在线 Demo、`../../prototypes/advance/tandem-demo.html` |
| Advance | v1.3 | 2026-10-02 | Demo 源码拆到 `demo/src/`（现 `prototypes/advance/src/`），加入构建与 Playwright 测试；修复来源筛选、临时静音、模式状态与跨筛选跳转；在线 Demo 重新发布为 main（`c97c818`）的构建 | 在线 Demo、`../../prototypes/advance/` |
| Lite | Benchmark Demo（PR #12） | 2026-10-02 | `genius-FXC` 的八页个人协作 Benchmark 设计 | `../../prototypes/lite/tandem-benchmark-demo.html`、`lite-review.md` |

## 如何查看

- **Lite Demo**：[`../../prototypes/lite/tandem-benchmark-demo.html`](../../prototypes/lite/tandem-benchmark-demo.html)，用浏览器直接打开即可，无需构建、依赖或联网。
- **Advance 在线画布**（可平移缩放、留评论）：<https://claude.ai/artifact/DgXdy7dfYpuA7oi2JSv3sV>，内容停在 v1.1。
- **Advance 画板源文件**：`visual-cases-v1/` 下的 `canvas.json` 与 `*.dc.html`。它们依赖 claude.ai Design 画布的运行时（`support.js`），不能直接用浏览器打开，用于留档、比对和必要时重新发布。
- **Advance Demo**：在线版 <https://claude.ai/artifact/7LeNQA95yCZgtC1icS45T8>，每次 Demo 合入 main 后按下文「修改 Demo」最后一行重新发布；本地版 `../../prototypes/advance/tandem-demo.html` 是单个 HTML 文件，用浏览器直接打开即可，不需要构建或联网（联网时会加载 Google Fonts）。它由 `../../prototypes/advance/src/` 构建生成，修改方法见下文「修改 Demo」。

## Logo

`logo/` 存放项目 logo：一段洛伦茨吸引子（σ=10, ρ=28, β=8/3）轨道的纯色线稿，颜色为低饱和板岩灰 `#5f6b6f`。它由莫比乌斯带线稿演化而来，沿用同一套线条语言：一笔画成，近处粗、远处细，投影交叉处较远的一支断开，两端渐细收笔。轨道左右两翼各绕两圈；吸引子的拓扑模板本身是一条带扭转的分支带，与莫比乌斯带同源。

| 文件 | 用途 |
| --- | --- |
| [`logo/tandem-mark.svg`](logo/tandem-mark.svg) | 主标志，透明底、紧凑画布 |
| [`logo/tandem-mark-light.svg`](logo/tandem-mark-light.svg) | 浅色线（暖纸色），用于深色底 |
| [`logo/tandem-mark-small.svg`](logo/tandem-mark-small.svg) | 线宽拉平加粗，用于 48 px 以下或 favicon |
| [`logo/tandem-icon.svg`](logo/tandem-icon.svg)、[`logo/tandem-icon.png`](logo/tandem-icon.png) | 方形 App 图标，暖纸底圆角方块，1024 px |

文件由 [`logo/generate.py`](logo/generate.py) 生成（`python3 docs/design/logo/generate.py`，纯 Python，无第三方依赖，积分初值与步长固定，可复现）。取哪几圈轨道、起止点、视角、线宽和交叉留白都是脚本顶部的常量。断口是真正断开的，可直接放在任意底色上。PNG 由浏览器截图导出，改 SVG 后需同步更新。此前的莫比乌斯带版本见 git 历史（`391203a` 及更早）。

## 可交互 Demo

### Lite：genius-FXC 的个人 Benchmark Demo（2026-10-02）

- 打开 [`../../prototypes/lite/tandem-benchmark-demo.html`](../../prototypes/lite/tandem-benchmark-demo.html)，无需构建或联网。它作为 Lite 的设计参考，与 Advance 的 `tandem-demo.html` 并行保留。
- 沿用原版暖白底色、衬线标题、等宽数字、侧栏和 Agent 配色，按个人协作 Benchmark 的需求收敛为八页：概览、协作画像、会话与轨迹、工具调用、项目分析、情绪与语义、优化建议、资源库。
- 项目分析保持独立；暂不实现生成工坊。移除桌面小组件、悬浮面板、首次启动、人格揭晓、会话回放 / 对比和通知模拟等额外流程。保留全局搜索、浅深色、筛选、同步入口、导出与分享。
- 日期、Agent、项目筛选共同作用于各页；月度画像使用同 Agent / 项目的完整历史。Markdown 报告、会话 CSV 与 SVG 分享卡支持真实下载；同步、安装和社区推荐均为明确标记的演示，不接入真实日志、不调用模型、不写入 Agent 配置。
- 需求对应、交互说明和自查结果见 [`lite-review.md`](lite-review.md)。这仍是设计原型，不替代三位成员对 MVP 的共同确认。

### Advance：yhyfhgs 的桌面 Demo

Advance Demo 把画布里的主应用、菜单栏面板、悬浮组件、桌面小组件和关键流程放在一个模拟的 Mac 桌面里。所有统计都由同一份示例会话数据实时计算，切换时间范围、Agent、项目或筛选条件后，各页面的数字、图表和人格会一起变化。

| 部分 | 可以操作的内容 |
| --- | --- |
| A1–A9 九个页面 | 筛选与对比、图表 ↔ 表格、热力图下钻、轨迹回放与拖动播放头、双会话对比、工具明细排序与展开、跨项目回归散点、情绪曲线、建议分级与教程、资源库匹配度、生成工坊的分步运行 |
| 菜单栏 | 「Tandem / 文件 / 显示 / 窗口 / 帮助」菜单，右侧图标打开菜单栏面板（运行中、空闲、需要关注三种状态） |
| 悬浮组件 | 五种收起态；点击展开、拖动吸附到 6 个位置，按住 ⌥ 自由放置 |
| 桌面小组件 | 宽度 ≥ 1500px 时默认显示，窄屏时在「显示」菜单中打开 |
| 流程 | 安装闭环（预览 → 确认 → 10 秒撤销 → 7 天效果追踪）、首次启动四步、人格揭晓动效、分享卡、导出报告与 CSV、命令面板、问本地 Agent、设置窗口六个分区 |

- 菜单栏右侧的 **「演示」** 菜单可以模拟会话完成、等你确认、连续失败、上下文即将压缩、每周报告、发现新数据源，以及切换空闲状态、重播首次启动与人格揭晓、重置数据。
- 快捷键：⌘K 命令面板，⌘, 设置，⌘⇧S 分享卡，⌘⇧E 报告，⌥⌘P 悬浮组件，⌃⌥T 菜单栏面板，Space 回放轨迹，? 查看全部。浏览器占用的组合在 Demo 中改用 ⌥（如 ⌥1–⌥9 切换页面）。
- 限制：数据是示例；写文件、运行命令、调用 Agent 与下载都只是模拟，导出内容以可复制的文本给出。

## 修改 Demo

本节是 **Advance Demo** 的维护方式。Lite 是独立 HTML，其现有检查命令见 [`lite-review.md`](lite-review.md)。版本归属的文档同步不涉及两套 Demo 的实现修改。

Advance 的 `../../prototypes/advance/tandem-demo.html` 是构建产物，**不要直接改它**：源码在 `../../prototypes/advance/src/`，下一次构建会覆盖对产物的直接修改。

- `src/index.html` 是页面骨架，`/*@css*/` 与 `/*@js*/` 两个占位符各出现一次；`src/styles/*.css` 与 `src/js/*.js` 按文件名排序后拼接进去，文件之间隔一行空行。
- 文件名必须是 `NN-名称.css` 或 `NN-名称.js`，两位数字前缀决定拼接顺序；其他名字的文件会让构建报错。`00-utils.js` 必须排在第一位，因为它开头的 `"use strict"` 对整段脚本生效。
- 后面的文件会改写前面文件里的同名函数：`80-history.js` 改写 `go` 并包装 `ACT.studioStart`，`42-a3-sessions.js` 改写 `base`。改这些函数时两处一起看。
- 测试用系统里的 Google Chrome（`channel: 'chrome'`）；没装 Chrome 时先运行 `npx playwright install chrome`。依赖用 pnpm 11 安装，需要 Node 20 以上。

| 命令（在 `demo/` 下运行） | 作用 |
| --- | --- |
| `pnpm install` | 安装依赖 |
| `pnpm build` | 由 `src/` 生成 `tandem-demo.html` |
| `pnpm check` | 检查提交的 `tandem-demo.html` 是否与源码一致，提交前必须通过 |
| `pnpm test` | 构建后跑 Playwright：每个页面在 6 种窗口尺寸下的渲染与横向溢出检查，以及浮层、菜单、模拟事件和快捷键的交互检查 |
| `pnpm test:ui` | 只在 mac-14 尺寸下构建并测试 |
| `node tools/shoot.mjs --sizes mac-14,compact --full` | 把各页面截图到 `demo/shots/`（不提交），用于目视检查 |
| `node build.mjs --artifact <文件>` | 生成发布到 claude.ai 的版本（去掉 doctype、html、head、body 这几行），再发布到上面的同一个 Demo 地址 |

源码与产物一起提交；PR 中 `tandem-demo.html` 的差异会被折叠（见仓库根目录的 `.gitattributes`）。

## 画板索引

以下均为 **Advance** 的 `visual-cases-v1/` 存档；Lite 的页面范围见上方 Lite Demo 说明。

| 页面 | 画板 | 文件 | 内容 |
| --- | --- | --- | --- |
| 主应用 | A1 概览 | `Main.dc.html` | AI 解读、指标卡、Agent 使用趋势、人格迷你卡、活跃节律、工具 Top、本周建议 |
| 主应用 | A2 协作人格 | `Persona.dc.html` | 类型代号 DIMV、协作指纹、四个维度、优势与盲点、Agent 契合度、演变 |
| 主应用 | A3 会话与轨迹 | `Sessions.dc.html` | 会话列表、泳道时间轴、播放头、关键时刻、会话启示 |
| 主应用 | A4 工具调用 | `Tools.dc.html` | 工具明细表、调用链矩阵、失败原因、审批负担、MCP 与子代理 |
| 主应用 | A5 项目习惯 | `Projects.dc.html` | 项目表、跨项目对比散点、项目与整体对比、识别到的工作流、规则覆盖 |
| 主应用 | A6 情绪与语义 | `Sentiment.dc.html` | 情绪曲线、摩擦分类、语义主题、高频反馈语、情绪前因 |
| 主应用 | A7 优化建议 | `Recs.dc.html` | 七个维度、L1–L4 难度、按用户水平筛选、依据、收益、预览与安装 |
| 主应用 | A8 资源库 | `Library.dc.html` | 按人格精选、匹配度拆解、相似用户 |
| 主应用 | A9 生成工坊 | `Studio.dc.html` | 上下文包、本地 Agent 执行、分步流程、流式预览、自检 |
| 主应用 | A10 设置 | `Settings.dc.html` | 数据源、索引方式、分析引擎、脱敏规则、数据存储 |
| 人格系统 | P1 16 型图谱 | `TypeMap.dc.html` | 四个维度的定义、信号与计算方法，16 种类型 |
| 人格系统 | P2 分享卡 | `ShareCard.dc.html` | 1080×1350 分享图（深色，可切浅色） |
| 人格系统 | P3 揭晓动效 | `Reveal.dc.html` | 3 秒动效分镜与减弱动态效果方案 |
| 菜单栏 · 悬浮 · 小组件 | B1 桌面全景 | `Desktop.dc.html` | 菜单栏、面板、悬浮胶囊、小组件同屏 |
| 菜单栏 · 悬浮 · 小组件 | B2 菜单栏面板 | `MenuBar.dc.html` | 运行中、空闲、需要关注三态，状态图标 |
| 菜单栏 · 悬浮 · 小组件 | B3 悬浮组件 | `FloatHUD.dc.html` | 五种收起态、展开态、吸附与隐身规则 |
| 菜单栏 · 悬浮 · 小组件 | B4 桌面小组件 | `Widgets.dc.html` | 小、中、大三种尺寸，全彩与着色 |
| 菜单栏 · 悬浮 · 小组件 | B5 系统通知 | `Notify.dc.html` | 通知分级与投递矩阵 |
| 关键流程 | C1 首次启动 | `Onboarding.dc.html` | 四步引导 |
| 关键流程 | C2 安装闭环 | `InstallFlow.dc.html` | 建议、预览、确认、撤销、7 天效果追踪 |
| 关键流程 | C3 生成工作流 | `GenFlow.dc.html` | 本地 Agent 生成流程与数据边界 |
| 关键流程 | C4 状态规范 | `States.dc.html` | 8 种空、加载、异常状态 |
| 关键流程 | C5 键盘 · 动效 · 无障碍 | `Interaction.dc.html` | 命令面板、快捷键、动效令牌、无障碍要求 |
| 设计语言 | D1 设计令牌 | `Tokens.dc.html` | 颜色、字体、间距、圆角、层级 |
| 设计语言 | D2 组件 | `Components.dc.html` | 按钮、选择控件、标签、卡片、会话行、步骤等 |
| 设计语言 | D3 侧边栏组件 | `Sidebar.dc.html` | 被 A1–A9 引用的侧边栏 |

## 关键设计决定

以下记录 **Advance** 画板的原始设计决定。Lite 当前的功能与操作边界见 [`lite-review.md`](lite-review.md)，不因版本命名自动扩充。

- **视觉语言**延续 Confluo v2 Demo（`Confluo/docs/plan/v2/demo/paper-feed-demo.html`）：暖白纸感底色、衬线标题、等宽数字与小标题，整体以单色为主。
- **颜色只承载身份与状态**：五个 Agent 用同一套可视化色板中的五色，按固定顺序分配、颜色跟随实体；亮色与暗色下相邻色的色觉差异 ΔE 最差为 9.2 与 8.4（≥ 8），已用校验脚本验证。紫色只用来标记 AI 生成的内容。
- **协作人格**：四个维度（委托 / 掌舵、规划 / 即兴、多线 / 专注、求证 / 信任）组合成 16 型；少于 30 个会话或维度落在 45–55 时不下结论，展示时标「实验性」。
- **隐私边界**：Tandem 只读本地会话日志，不上传数据，自己也不调用云端模型。交给本机 Agent 的内容会经该 Agent 发往它的服务商，用的是用户自己的登录与额度，发送前可以逐项预览。
- **所有写入**都要经过预览、确认，写入后可撤销，并在安装后对照效果。

## v1 之后的决定

画板没有回改。下表是 v1 之后定下的改动，Demo 后续修改以它们为准；表中「调研总结」指 [docs/research/landscape.md](../research/landscape.md) §1 的编号。

| v1 的做法 | 现行做法 | 依据 |
| --- | --- | --- |
| 以 Agent 为主要分组：A1 按 Agent 堆叠的趋势图、侧边栏 Agent 列表、A2 Agent 契合度 | 按项目、模型与思考档位分组；Agent 只作来源属性，用于去重、兼容性判断与标注数据来自哪里 | [数据方案 §4.5](../plans/data-acquisition.md) |
| 页面里的指标由 Demo 自己从示例数据算出 | 指标来自后端的确定性计算，不开 AI 也能出数；后端 MVP 先读 Codex 记录，按「数据 → 画像 → 瓶颈 → 推荐」输出 | 调研总结第 3 条、[仓库 README](../../README.md) |
| A3 泳道时间轴，窄窗口需要横向滚动 | 脊柱概览 + 语义泳道 + 按轮次的事件账本 + 检查器；默认按活跃时间投影、折叠空闲、不横向滚动；规则检出的关键时刻画实心，AI 推断的画空心并附引用 | 调研总结第 14 条 |
| 图表标题描述图表本身，数字不标来源 | 标题写结论句；每个数字标来源与新鲜度（官方、官方缓存、估算、过期、无数据）；样本不够时显示「数据不足」 | 调研总结第 15 条 |
| A2「与全体用户比较」、A8「同类型用户在用」与「和你相似的人」 | 删除，没有跨用户的数据来源 | 调研总结第 15 条 |
| A7 建议卡用示例收益（如「review 轮次 −60%」） | 推荐由问题驱动，机制由代码决策表选择，一次最多推荐 2–3 个 skill；装后效果分是否触发、机械效果、行为效果三层报告，不写提速百分比 | 调研总结第 6、7、11 条 |
| 没有用量与额度视图 | 新增「用量与额度」视图，作为分析的分母；Lite 版只放一张卡 | 调研总结第 13 条 |

## 假设

- 产品名暂用 Tandem / 同频。
- 画板与 Demo 里的数值都是示例数据；项目名与使用习惯参考了 `yhyfhgs` 本机的 Claude Code Insights 报告，数字为虚构。
- Demo 里 Gemini CLI、Copilot CLI 的会话目录沿用 v1 的写法；实际接入哪些 Agent、各自的会话格式，以[数据方案](../plans/data-acquisition.md)和[会话格式调研](../research/agent-sessions/README.md)为准。
- 人格维度的信号与权重是初版设想，接入真实数据后按区间判定。

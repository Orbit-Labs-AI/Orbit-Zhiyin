# 设计资料

状态：现行入口 · 维护者 `yhyfhgs` · 适用：Lite / Advance

**Orbit** 是一个本地的跨 Agent 会话分析 Mac App：做协作人格分析、会话轨迹可视化，并给出 Skills、Hooks、规则等优化建议。本目录存放它的品牌、设计规范、画板存档与 Demo 说明；可运行原型在仓库根的 [`prototypes/`](../../prototypes/README.md)。

| 文档 | 内容 |
| --- | --- |
| [品牌](brand.md) | 产品名 Orbit、代码标识的沿用规则、标志与 App 图标、备选与历史版本 |
| [Demo 说明](demo.md) | 统一 App（Lite + Advance）怎么看、有哪些交互、怎么修改与发布 |
| [画板与设计决定](boards.md) | Advance v1 画板索引、原始设计决定、v1 之后的现行决定、假设 |
| [Lite 审查](lite-review.md) | `genius-FXC` 的 Lite 原稿：需求对应、交互说明与自查 |
| [`logo/`](logo/generate.py) | 标志源文件与生成脚本 |
| [`visual-cases-v1/`](visual-cases-v1/) | Advance 画板源文件（`canvas.json` 与 `*.dc.html`，依赖 claude.ai Design 画布运行时，不能直接用浏览器打开） |

## App 版本与设计归属

| App 版本 | 设计来源 | 设计入口 |
| --- | --- | --- |
| **Lite** | `genius-FXC` 的个人协作 Benchmark 设计（[PR #12](https://github.com/ActionMesh-AI/Hackathon/pull/12)） | 原稿 [`prototypes/lite/tandem-benchmark-demo.html`](../../prototypes/lite/tandem-benchmark-demo.html)；范围与审查见 [lite-review.md](lite-review.md) |
| **Advance** | `yhyfhgs` 的桌面 App 设计 | 源码 [`prototypes/advance/src/`](../../prototypes/advance/src/)、画板 [`visual-cases-v1/`](visual-cases-v1/) |

- 版本名统一使用 **Lite / Advance**；历史材料中的 `Advanced` 指 **Advance**。
- 自 2026-10-02 起两版是**同一个 App**（[`prototypes/advance/tandem-demo.html`](../../prototypes/advance/tandem-demo.html)），侧栏顶部一键切换，共用侧栏、卡片、栏目标题、KPI、控件、桌面小组件与动效；Lite 只在页面数量与尺度上做减法。`prototypes/lite/` 保留原稿作为 Lite 的设计来源。
- 引用设计或功能说明时注明适用版本。

## 存档记录

| App 版本 | 版本 | 日期 | 内容 | 位置 |
| --- | --- | --- | --- | --- |
| Advance | v1 | 2026-10-01 | Mac App 视觉案例：5 页、26 块画板，含逐屏交互标注 | 在线画布、`visual-cases-v1/` |
| Advance | v1.1 | 2026-10-01 | 修正 A5「跨项目对比」的拟合线与相关系数（标注 r = 0.71 与示例点不符，按示例点重算为 0.91） | 同上 |
| Advance | v1.2 | 2026-10-01 | 把视觉案例做成可交互 HTML Demo，所有页面和按钮都有逻辑 | 在线 Demo、`prototypes/advance/` |
| Advance | v1.3 | 2026-10-02 | Demo 源码拆到 `src/`，加入构建与 Playwright 测试；修复来源筛选、临时静音、模式状态与跨筛选跳转；在线 Demo 重新发布为 main（`c97c818`）的构建 | 在线 Demo、`prototypes/advance/` |
| Lite | Benchmark Demo（PR #12） | 2026-10-02 | `genius-FXC` 的八页个人协作 Benchmark 设计 | `prototypes/lite/`、[lite-review.md](lite-review.md) |
| Lite + Advance | v1.4 | 2026-10-02 | 两版合为同一个 App：侧栏顶部一键切换；Lite 收敛为四页并复用 Advance 组件；共用换页编排、数字滚动、页面导读与微动效；首次启动改为连贯的 Genesis 序列 | `prototypes/advance/`（`26-edition.js`、`37-motion.js`、`39-lite-pages.js`、`56-onboarding.js`） |
| Lite + Advance | v1.5 | 2026-10-02 | 产品改名 **Orbit**：菜单栏与 App 图标换成锥形螺旋标志、品牌色 `--orbit`；协作指纹改为罗盘表盘（玫瑰、协作重心指针、Agent 轨道环带与行星）；Genesis 统一为 Orbit 母题 | `prototypes/advance/`、[品牌](brand.md)、[`logo/`](logo/orbit-mark.svg) |
| Advance | v1.6 | 2026-10-02 | 画板文字改为 Orbit，标志换成原型 `orbitMark` 的原样输出；在线画布与在线 Demo 重新发布 | 在线画布、`visual-cases-v1/`、在线 Demo |

画板与 Demo 的数值都是示例数据，不替代 MVP 范围；当前实现边界见[产品与交付边界](../product/scope.md)。

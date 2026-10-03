# 可交互 Demo：查看与修改

状态：现行 · 维护者 `yhyfhgs` · 适用：统一 App（Lite + Advance），Lite 原稿另注

Lite 与 Advance 自 2026-10-02 起是**同一个 App**，源码在 [`prototypes/advance/`](../../prototypes/advance/)。Demo 使用示例数据，所有统计由同一份示例会话实时计算；写文件、运行命令、调用 Agent 与下载都只是模拟。

## 如何查看

| 入口 | 位置 | 说明 |
| --- | --- | --- |
| 统一 App（本地） | [`prototypes/advance/orbit-demo.html`](../../prototypes/advance/orbit-demo.html) | 单个 HTML，浏览器直接打开，不需构建或联网（联网时加载 Google Fonts）；侧栏顶部切换版本（也可用「显示」菜单、⌘K 或 ⌃⌘L），地址加 `#l-home` 直接以 Lite 打开 |
| 统一 App（在线） | <https://claude.ai/artifact/7LeNQA95yCZgtC1icS45T8> | 每次 Demo 合入 main 后按下文「修改 Demo」最后一行重新发布 |
| Lite 原稿 | [`prototypes/lite/orbit-benchmark-demo.html`](../../prototypes/lite/orbit-benchmark-demo.html) | `genius-FXC` 的八页设计来源，直接打开，范围与审查见 [lite-review.md](lite-review.md) |
| Advance 画板 | 在线画布 <https://claude.ai/artifact/DgXdy7dfYpuA7oi2JSv3sV>、[`visual-cases-v1/`](visual-cases-v1/) | 版式停在 v1.1，文字与标志已改为 Orbit（v1.6），见 [画板与设计决定](boards.md) |

## Lite 与 Advance：同一个 App

| 部分 | 做法 |
| --- | --- |
| 切换 | 侧栏顶部 Lite \| Advance 滑块；「显示」菜单、命令面板、⌃⌘L 同样可切。滑块先移动，再以 View Transition 交叉淡入侧栏与内容；选择会被记住 |
| 路由 | 概览、画像、会话、建议两版一一对应，切换时停在对应页面；Lite 中打开工具、项目、情绪、资源库、工坊等 Advance 独有页面时自动切到 Advance，并给出「回到 Lite」 |
| 共用组件 | 侧栏（分组、导航行、Agents、页脚隐私卡与用户行）、标题栏 `tbar`、卡片与栏目标题、KPI、`seg` / `chip` / 按钮、建议卡、会话行、协作指纹、桌面小组件、悬浮组件与菜单栏 |
| Lite 四页 | 概览（AI 一句话 + 大字人格码、四个大数字、30 天活跃条、本周最值得做的一件事）、协作画像（超大四字母码、罗盘、四条大刻度、月度演变）、会话轨迹（最近关键会话 + 关键步骤时间线）、优化建议（前三条大卡，可应用 / 撤销）。不显示筛选行，只保留时间范围；有 Advance 筛选时给出「清除」 |
| 共用动效 | 换页时区块依次上浮淡入、`data-count` 数字滚动、标题栏下的「这页回答」导读（可收起并记住）、按钮按下回弹、可点卡片抬升、分段控件滑块、筛选 chip 增删；`prefers-reduced-motion` 时全部关闭 |
| 协作人格罗盘 | 协作指纹画成罗盘表盘：120 道刻度与每 3 小时方位数字、00 外侧基准三角。内盘是协作人格的花：16 型各一朵，花型由四个字母决定（瓣数 = 多线 M 12 瓣 / 专注 F 5 瓣；即兴 I 旋卷圆头 / 规划 P 端正尖头；委托 D 长瓣小花心 / 掌舵 S 短阔瓣大花心带舵环；求证 V 重瓣 / 信任 T 单瓣），比例随轴强度微调；整朵花按协作重心旋转，`--orbit` 色领瓣指向它。外环学宣传片的极光，用一组平滑曲线画轨道：每个 Agent 一层，层内淡色、外缘一条 Agent 色细线，色带越宽该 Agent 占比越高；Agent 用各自标志（lobe-icons，单色、Agent 识别色）的徽章停在各自的协作重心，重心相近时往里错开。进入画像页时花阻尼晃动、轨道扫描展开、徽章从 00 运行到重心。算法说明的 16 型表附每型的花 |
| 首次启动 Genesis | 以 Orbit 母题连续播放约 6.7 s：倾斜的 Orbit 轨道翻正成罗盘外框、标志内弧收拢成领瓣，合拢的花苞快转、会话粒子沿轨道螺旋汇入 → 花苞扫一圈、粒子按开始时间落位、轨道与 Agent 徽章长出 → 花苞开成该类型的花、字母翻牌锁定、领瓣摆向协作重心 → 相近人格卡比对并入 → 「查看完整画像」时人格码与罗盘飞到当前版本的画像页。可随时跳过、Esc、在后台继续；「播放人格揭晓」复用后四段 |
| 分享卡 | 每个时间长度一张：近 7 / 30 / 90 天、全部（人格页在看某个月且与近 30 天不同时再加这个月）各自按窗口算人格，所以同一个人可以在周卡和全时卡上是不同类型。卡上依次是标签胶囊（周卡 WEEKLY / 月卡 MONTHLY / 季卡 QUARTERLY / 全时卡 ALL TIME / N 月卡）与日期、带活跃日历环的花（每格一天，超过 92 天每格一周，深浅 = 会话数）、SF Pro Rounded 类型码与四轴强度、类型名与人格描述、会话 / 活跃天数 / Agent / 对话轮次与一行页脚；版式以留白为先，16 型各自的金句放进「复制分享文案」，不上卡。预览（SVG）与 1080×1350 PNG 执行同一份绘制指令；「全部保存」逐张导出，文件名 `orbit-persona-<7d\|30d\|90d\|all>-<code>-<日期>.png`。App 里每张卡来自 `POST /v1/export/share_card`（`period` = 该长度），网关不可用时退回 App 本地算出的人格 |

## Advance 页面与桌面组件

Demo 把主应用、菜单栏面板、悬浮组件、桌面小组件和关键流程放在一个模拟的 Mac 桌面里。切换时间范围、Agent、项目或筛选条件后，各页面的数字、图表和人格一起变化。

| 部分 | 可以操作的内容 |
| --- | --- |
| A1–A9 九个页面 | 筛选与对比、图表 ↔ 表格、热力图下钻、轨迹回放与拖动播放头、双会话对比、工具明细排序与展开、跨项目回归散点、情绪曲线、建议分级与教程、资源库匹配度、生成工坊的分步运行 |
| 菜单栏 | 「Orbit / 文件 / 显示 / 窗口 / 帮助」菜单，右侧 Orbit 图标打开菜单栏面板（运行中、空闲、需要关注三种状态） |
| 悬浮组件 | 五种收起态；点击展开、拖动吸附到 6 个位置，按住 ⌥ 自由放置 |
| 桌面小组件 | 宽度 ≥ 1500px 时默认显示，窄屏时在「显示」菜单中打开 |
| 流程 | 安装闭环（预览 → 确认 → 10 秒撤销 → 7 天效果追踪）、首次启动、人格揭晓、分享卡、导出报告与 CSV、命令面板、问本地 Agent、设置窗口六个分区 |

### 滚动区域

主从分栏并排时（内容列 ≥ 800px；项目习惯 ≥ 1100px），页面本身不滚：「这页回答」与筛选行固定，分栏填满窗口剩余高度，每个窗格各自滚动，滚到头也不带动外层。分栏堆叠的窄窗口退回整页滚动。样式在 `src/styles/88-panes.css`，选中项保持可见在 `src/js/88-panes.js`，用例见 `tests/p-pane-scroll.spec.mjs`。

| 页面 | 滚动区域 |
| --- | --- |
| 会话与轨迹、Lite 会话轨迹 | 会话列表（搜索头固定，只滚行）｜ 会话详情 |
| 优化建议 | 建议卡列表 ｜ 建议详情 |
| 项目习惯 | 项目表 + 散点 ｜ 项目详情（内容列 < 1100px 时堆叠，整页滚动） |
| 生成工坊 | 新建任务 ｜ 运行 ｜ 产物三张卡各自滚动（800–999px 时产物卡移到运行卡下方）；「开始生成」固定在任务卡底部 |
| 概览、协作人格、情绪与语义、工具调用、资源库、Lite 概览 / 画像 / 建议 | 一列堆叠的卡片，保持整页滚动 |
| 设置窗口、sheet、菜单栏面板、首次启动 | 设置的分区标签固定、正文滚动；sheet 的标题与按钮固定、正文滚动，导出分享卡的预览与选项两栏各自滚动 |

- 菜单栏右侧的 **「演示」** 菜单可以模拟会话完成、等你确认、连续失败、上下文即将压缩、每周报告、发现新数据源，以及切换空闲状态、重播首次启动与人格揭晓、重置数据。
- 快捷键：⌘K 命令面板，⌘, 设置，⌘⇧S 分享卡，⌘⇧E 报告，⌥⌘P 悬浮组件，⌃⌥T 菜单栏面板，Space 回放轨迹，? 查看全部。浏览器占用的组合在 Demo 中改用 ⌥（如 ⌥1–⌥9 切换页面）。

## Lite 原稿（genius-FXC）

- 沿用暖白底色、衬线标题、等宽数字、侧栏和 Agent 配色，按个人协作 Benchmark 的需求收敛为八页：概览、协作画像、会话与轨迹、工具调用、项目分析、情绪与语义、优化建议、资源库。
- 不含生成工坊、桌面小组件、悬浮面板、首次启动、人格揭晓、会话回放 / 对比和通知模拟；保留全局搜索、浅深色、筛选、同步入口、导出与分享。
- 日期、Agent、项目筛选共同作用于各页；Markdown 报告、会话 CSV 与 SVG 分享卡支持真实下载；同步、安装和社区推荐均为明确标记的演示。
- 可运行的 Lite 已并入统一 App；原稿保留为设计来源，检查命令见 [lite-review.md](lite-review.md)。

## 修改 Demo

`prototypes/advance/orbit-demo.html` 是构建产物，**不要直接改它**：源码在 [`prototypes/advance/src/`](../../prototypes/advance/src/)，下一次构建会覆盖对产物的直接修改。

- `src/index.html` 是页面骨架，`/*@css*/` 与 `/*@js*/` 两个占位符各出现一次；`src/styles/*.css` 与 `src/js/*.js` 按文件名排序后拼接进去。
- 文件名必须是 `NN-名称.css` 或 `NN-名称.js`，两位数字前缀决定拼接顺序；`00-utils.js` 必须排在第一位，它开头的 `"use strict"` 对整段脚本生效。
- 后面的文件会改写前面文件里的同名函数：`80-history.js` 改写 `go` 并包装 `ACT.studioStart`，`42-a3-sessions.js` 改写 `base`。改这些函数时两处一起看。
- 版本切换与路由映射在 `26-edition.js`，Lite 四页在 `39-lite-pages.js`，两版共用的动效在 `37-motion.js`，Orbit 标志在 `00-utils.js`。
- 测试用系统里的 Google Chrome（`channel: 'chrome'`）；没装时先运行 `npx playwright install chrome`。浏览器测试细则见 [`prototypes/advance/TESTING.md`](../../prototypes/advance/TESTING.md)。

| 命令（在 `prototypes/advance/` 下运行） | 作用 |
| --- | --- |
| `pnpm build` | 由 `src/` 生成 `orbit-demo.html`（仓库根可用 `pnpm --filter @orbit/prototype-advance build`） |
| `pnpm check` | 检查提交的 `orbit-demo.html` 与源码一致，提交前必须通过 |
| `pnpm test` | 构建后跑 Playwright：各页面在 6 种窗口尺寸下的渲染与横向溢出，以及浮层、菜单、模拟事件和快捷键 |
| `pnpm test:ui` | 只在 mac-14 尺寸下构建并测试 |
| `node tools/shoot.mjs --sizes mac-14,compact --full`（`--ed lite` 拍 Lite 四页） | 截图到 `shots/`（不提交），用于目视检查 |
| `node build.mjs --artifact <文件>` | 生成发布到 claude.ai 的版本（去掉 doctype、html、head、body 行），再发布到上面的在线 Demo 地址 |

仓库根的 `pnpm check:ui` 同时跑 Lite 数据检查与 Advance 浏览器测试。源码与产物一起提交；PR 中 `orbit-demo.html` 的差异会被折叠（见仓库根 `.gitattributes`）。

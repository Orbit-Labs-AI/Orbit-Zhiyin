# 可交互 Demo：查看与修改

状态：现行 · 维护者 `yhyfhgs` · 适用：统一 App（Lite + Advance），Lite 原稿另注

Lite 与 Advance 自 2026-10-02 起是**同一个 App**，源码在 [`prototypes/advance/`](../../prototypes/advance/)。Demo 使用示例数据，所有统计由同一份示例会话实时计算；写文件、运行命令、调用 Agent 与下载都只是模拟。

## 如何查看

| 入口 | 位置 | 说明 |
| --- | --- | --- |
| 统一 App（本地） | [`prototypes/advance/tandem-demo.html`](../../prototypes/advance/tandem-demo.html) | 单个 HTML，浏览器直接打开，不需构建或联网（联网时加载 Google Fonts）；侧栏顶部切换版本（也可用「显示」菜单、⌘K 或 ⌃⌘L），地址加 `#l-home` 直接以 Lite 打开 |
| 统一 App（在线） | <https://claude.ai/artifact/7LeNQA95yCZgtC1icS45T8> | 每次 Demo 合入 main 后按下文「修改 Demo」最后一行重新发布 |
| Lite 原稿 | [`prototypes/lite/tandem-benchmark-demo.html`](../../prototypes/lite/tandem-benchmark-demo.html) | `genius-FXC` 的八页设计来源，直接打开，范围与审查见 [lite-review.md](lite-review.md) |
| Advance 画板 | 在线画布 <https://claude.ai/artifact/DgXdy7dfYpuA7oi2JSv3sV>、[`visual-cases-v1/`](visual-cases-v1/) | 版式停在 v1.1，文字与标志已改为 Orbit（v1.6），见 [画板与设计决定](boards.md) |

## Lite 与 Advance：同一个 App

| 部分 | 做法 |
| --- | --- |
| 切换 | 侧栏顶部 Lite \| Advance 滑块；「显示」菜单、命令面板、⌃⌘L 同样可切。滑块先移动，再以 View Transition 交叉淡入侧栏与内容；选择会被记住 |
| 路由 | 概览、画像、会话、建议两版一一对应，切换时停在对应页面；Lite 中打开工具、项目、情绪、资源库、工坊等 Advance 独有页面时自动切到 Advance，并给出「回到 Lite」 |
| 共用组件 | 侧栏（分组、导航行、Agents、页脚隐私卡与用户行）、标题栏 `tbar`、卡片与栏目标题、KPI、`seg` / `chip` / 按钮、建议卡、会话行、协作指纹、桌面小组件、悬浮组件与菜单栏 |
| Lite 四页 | 概览（AI 一句话 + 大字人格码、四个大数字、30 天活跃条、本周最值得做的一件事）、协作画像（超大四字母码、罗盘、四条大刻度、月度演变）、会话轨迹（最近关键会话 + 关键步骤时间线）、优化建议（前三条大卡，可应用 / 撤销）。不显示筛选行，只保留时间范围；有 Advance 筛选时给出「清除」 |
| 共用动效 | 换页时区块依次上浮淡入、`data-count` 数字滚动、标题栏下的「这页回答」导读（可收起并记住）、按钮按下回弹、可点卡片抬升、分段控件滑块、筛选 chip 增删；`prefers-reduced-motion` 时全部关闭 |
| 协作人格罗盘 | 协作指纹画成罗盘表盘：120 道刻度与每 3 小时方位数字、00 外侧基准三角；内盘玫瑰四个主角朝 D I M V、长度随轴强度；指针指向协作重心（0.8 × 半径，北半 `--orbit`）；外环是每个 Agent 一层的平滑轨道环带，Agent 行星停在各自的协作重心。进入画像页时指针阻尼晃动、环带扫描展开、行星从 00 运行到重心 |
| 首次启动 Genesis | 以 Orbit 母题连续播放约 6.7 s：倾斜的 Orbit 轨道翻正成罗盘外框、标志内弧收拢成指针，会话粒子沿轨道螺旋汇入 → 指针扫一圈、粒子按开始时间落位、环带与行星长出 → D I M V 玫瑰伸展、字母翻牌锁定、指针摆向协作重心 → 相近人格卡比对并入 → 「查看完整画像」时人格码与罗盘飞到当前版本的画像页。可随时跳过、Esc、在后台继续；「播放人格揭晓」复用后四段 |

## Advance 页面与桌面组件

Demo 把主应用、菜单栏面板、悬浮组件、桌面小组件和关键流程放在一个模拟的 Mac 桌面里。切换时间范围、Agent、项目或筛选条件后，各页面的数字、图表和人格一起变化。

| 部分 | 可以操作的内容 |
| --- | --- |
| A1–A9 九个页面 | 筛选与对比、图表 ↔ 表格、热力图下钻、轨迹回放与拖动播放头、双会话对比、工具明细排序与展开、跨项目回归散点、情绪曲线、建议分级与教程、资源库匹配度、生成工坊的分步运行 |
| 菜单栏 | 「Orbit / 文件 / 显示 / 窗口 / 帮助」菜单，右侧 Orbit 图标打开菜单栏面板（运行中、空闲、需要关注三种状态） |
| 悬浮组件 | 五种收起态；点击展开、拖动吸附到 6 个位置，按住 ⌥ 自由放置 |
| 桌面小组件 | 宽度 ≥ 1500px 时默认显示，窄屏时在「显示」菜单中打开 |
| 流程 | 安装闭环（预览 → 确认 → 10 秒撤销 → 7 天效果追踪）、首次启动、人格揭晓、分享卡、导出报告与 CSV、命令面板、问本地 Agent、设置窗口六个分区 |

- 菜单栏右侧的 **「演示」** 菜单可以模拟会话完成、等你确认、连续失败、上下文即将压缩、每周报告、发现新数据源，以及切换空闲状态、重播首次启动与人格揭晓、重置数据。
- 快捷键：⌘K 命令面板，⌘, 设置，⌘⇧S 分享卡，⌘⇧E 报告，⌥⌘P 悬浮组件，⌃⌥T 菜单栏面板，Space 回放轨迹，? 查看全部。浏览器占用的组合在 Demo 中改用 ⌥（如 ⌥1–⌥9 切换页面）。

## Lite 原稿（genius-FXC）

- 沿用暖白底色、衬线标题、等宽数字、侧栏和 Agent 配色，按个人协作 Benchmark 的需求收敛为八页：概览、协作画像、会话与轨迹、工具调用、项目分析、情绪与语义、优化建议、资源库。
- 不含生成工坊、桌面小组件、悬浮面板、首次启动、人格揭晓、会话回放 / 对比和通知模拟；保留全局搜索、浅深色、筛选、同步入口、导出与分享。
- 日期、Agent、项目筛选共同作用于各页；Markdown 报告、会话 CSV 与 SVG 分享卡支持真实下载；同步、安装和社区推荐均为明确标记的演示。
- 可运行的 Lite 已并入统一 App；原稿保留为设计来源，检查命令见 [lite-review.md](lite-review.md)。

## 修改 Demo

`prototypes/advance/tandem-demo.html` 是构建产物，**不要直接改它**：源码在 [`prototypes/advance/src/`](../../prototypes/advance/src/)，下一次构建会覆盖对产物的直接修改。

- `src/index.html` 是页面骨架，`/*@css*/` 与 `/*@js*/` 两个占位符各出现一次；`src/styles/*.css` 与 `src/js/*.js` 按文件名排序后拼接进去。
- 文件名必须是 `NN-名称.css` 或 `NN-名称.js`，两位数字前缀决定拼接顺序；`00-utils.js` 必须排在第一位，它开头的 `"use strict"` 对整段脚本生效。
- 后面的文件会改写前面文件里的同名函数：`80-history.js` 改写 `go` 并包装 `ACT.studioStart`，`42-a3-sessions.js` 改写 `base`。改这些函数时两处一起看。
- 版本切换与路由映射在 `26-edition.js`，Lite 四页在 `39-lite-pages.js`，两版共用的动效在 `37-motion.js`，Orbit 标志在 `00-utils.js`。
- 测试用系统里的 Google Chrome（`channel: 'chrome'`）；没装时先运行 `npx playwright install chrome`。浏览器测试细则见 [`prototypes/advance/TESTING.md`](../../prototypes/advance/TESTING.md)。

| 命令（在 `prototypes/advance/` 下运行） | 作用 |
| --- | --- |
| `pnpm build` | 由 `src/` 生成 `tandem-demo.html`（仓库根可用 `pnpm --filter @tandem/prototype-advance build`） |
| `pnpm check` | 检查提交的 `tandem-demo.html` 与源码一致，提交前必须通过 |
| `pnpm test` | 构建后跑 Playwright：各页面在 6 种窗口尺寸下的渲染与横向溢出，以及浮层、菜单、模拟事件和快捷键 |
| `pnpm test:ui` | 只在 mac-14 尺寸下构建并测试 |
| `node tools/shoot.mjs --sizes mac-14,compact --full`（`--ed lite` 拍 Lite 四页） | 截图到 `shots/`（不提交），用于目视检查 |
| `node build.mjs --artifact <文件>` | 生成发布到 claude.ai 的版本（去掉 doctype、html、head、body 行），再发布到上面的在线 Demo 地址 |

仓库根的 `pnpm check:ui` 同时跑 Lite 数据检查与 Advance 浏览器测试。源码与产物一起提交；PR 中 `tandem-demo.html` 的差异会被折叠（见仓库根 `.gitattributes`）。

## 区域渲染

数据或筛选变化时，App 只刷新依赖它的组件，其它节点原样保留，所以滚动条、展开的下拉 / 菜单、焦点、选中的文字、hover 状态和正在播放的动画都不受影响。框架在 [`src/js/24-regions.js`](../../prototypes/advance/src/js/24-regions.js)。

- **整页渲染**只发生在首次进入、切换路由和切换 Lite / Advance 时（`window.__renderCount` 计数）；`go()` 到当前已显示的页面（侧栏当前页、在项目习惯页点置顶项目、先设筛选再跳回本页的通知或命令面板入口）不算导航，按区域刷新并保留滚动。全部页面都已迁移（`RG.pages`：Advance 九页与 Lite 四页），其它所有 `render()`（筛选、开关、实时帧、feed 到达、导入进度）都是区域刷新；只有隐藏的组件画廊 `vizkit` 仍整页渲染，并沿用滚动与焦点恢复。
- **外壳**也是区域：侧栏的导入入口 `side:import`、页面列表 `side:insight` / `side:action`、`side:agents`、`side:pins`、页脚 `side:foot`；菜单栏、标题行和整个侧栏用 `rgPut` 原地 morph。设置面板、菜单栏面板、悬浮组件（含 live 的静止 / 暂停态）与桌面小组件也用 `rgPut`，打开设置时来一帧实时数据不会重置它的滚动与表单。实时状态条与导入进度条也原地 morph。
- **实时数据**：`90-live-core.js` 的 `lvFlush` 在可区域刷新时只把实时相关的键（`facts`、当前路由的 `feed:<route>`、`live`、`tl`、`job`）交给本轮刷新，不再推迟到用户停止滚动或关闭下拉；导入期间的 4 秒间隔仍保留。导入的 job 帧只 `RG.bump('job')`，刷新 `side:import` 与进度条。

### API

| 写法 | 作用 |
| --- | --- |
| `region(key, deps, fn, { after, wrap })` | 返回 `fn()` 的 HTML，并在根元素上加 `data-region="key"`；注册区域。`fn` 每次刷新都会重新运行，必须现读状态，不能引用页面函数里的局部变量。`after(el, first)` 在区域进入 DOM 和每次输入变化后运行（挂图表）。`fn` 返回多个根元素时传 `wrap: true`（外包 `display:contents`）。空字符串会留一个隐藏占位，之后可原位出现。 |
| `deps` | `'S.a.b'`（状态路径，Set / Map 按内容比较）、`'filters'`（`sel()` 读取的全部筛选）、`'facts'`（ALL / AG / PJ）、`'feed:<route>'`、`'live'`、`'job'`、`'tl'`（任何 TandemLive 变化）、`RG.bump(name)` 的任意名字，或返回可比较值的函数；`'*'` 表示每轮都重算。依赖值算出签名，签名未变的区域整块跳过；HTML 未变也不碰 DOM。 |
| `RG.refresh(keys, why)` / `RG.refreshNow(keys, why)` | 按依赖键失效；前者同一帧合并（rAF，120 ms 兜底），后者同步。 |
| `RG.bump(name)` | 递增命名版本并刷新依赖它的区域。 |
| `RG.memo(name, fn)` | 每轮刷新只算一次的共享数据（如概览的 `ovCtx()`：`sel()`、`stats()`、人格与 feed）。 |
| `RG.prep(route, fn)` | 该页每轮区域刷新前运行（如 live 建议的 `lvRecSync`）。 |
| `rgPut(el, html)` / `rgSwap(el, html)` | 把元素的子节点 / 元素本身 morph 成新 HTML。 |

morph 按 `data-region`、`id`、`data-key`、`data-vz` 匹配有键的子节点，其余按位置与标签匹配；聚焦中的输入框保留用户正在输入的值；`[data-vz]` 图表容器归 vizkit 所有，morph 不碰其属性与内容，由区域的 `after` 重新挂载（概览用 `ovMount`：图表输入不变就不重画）。

### 新增或迁移一个区域

1. 把页面拆成卡片级区域，键名用页面前缀（`a3:list`、`a4:table`）。每个区域一个函数，状态从 `RG.memo` 的共享上下文里读。
2. 页面函数只拼骨架：`RG.pages.add('<route>')`，然后 `PAGES.x = () => region(...) + '<div class="content" id="content">' + region(...) + …`。工具栏 `.tbar` 必须是 `#main` 的直接子元素，它所在区域的 `after` 调 `tbarFit()`。
3. 原来的 `PAGES.x.after` 拆进各区域的 `after`；原来直接改 DOM 的局部更新（如概览刷选）改成改状态后 `RG.refreshNow(['S.…'])`。
4. 动效自动按区域生效：`data-count` 数字从该区域刷新前的值滚到新值（`37-motion.js` 的区域钩子），筛选 chip 弹入、seg 滑块、图表 ↔ 表格淡入照旧；只有首次进入页面才播放入场编排；`prefers-reduced-motion` 下直接显示终值。
5. 页面整体有几种形态（读取中 / 空 / 正常）时，外层放一个只依赖形态函数的区域（如 `a4:body`、`a5:body`），正常形态里再嵌卡片区域；页面的所有卡片由一个 `RG.memo` 部件函数一次算出（演示与 live 各一份：`toolsParts` / `lvToolsParts`、`projectsParts` / `lvProjectsParts`）。被命令式逐帧更新的节点（会话轨迹的 `#tlBox`、`#tlOv`、`#tlRead`、`#tlInsp`、对比时间线）带 `data-vz`，morph 不碰，由区域的 `after` 同步，所以回放进行中数据刷新不会打断它。live 的按需详情（`LV.detail`）用函数依赖返回该条目的 `state` 与数据身份，详情到达只刷新读它的卡片。用例：[`tests/region-render-pages.spec.mjs`](../../prototypes/advance/tests/region-render-pages.spec.mjs)（会话与轨迹、工具调用、项目习惯）、[`tests/region-render-lite-persona.spec.mjs`](../../prototypes/advance/tests/region-render-lite-persona.spec.mjs)（Lite 四页、协作人格、情绪与语义）、[`tests/region-render-recs-library-studio.spec.mjs`](../../prototypes/advance/tests/region-render-recs-library-studio.spec.mjs)（建议、资源库、生成工坊与三个原生面板）、[`tests/region-render-shell.spec.mjs`](../../prototypes/advance/tests/region-render-shell.spec.mjs)（同页 `go()`、设置面板）。

### 调试

- `window.__renderCount`：整页渲染次数；`window.__regionRenders[key]`：每个区域的刷新次数。
- 地址加 `?debug=render`，控制台打印 `[render]`（整页）与 `[region] key ← 来源`（区域与失效来源）。
- 每次区域刷新后派发 `tandem:regions` 事件；原生壳的拖拽区域上报（`23-native-drag.js`）由 MutationObserver 节流（200 ms），只有被 morph 的节点产生变更记录。
- 回归用例：[`tests/region-render.spec.mjs`](../../prototypes/advance/tests/region-render.spec.mjs)。
- 真实导入验收：`JOURNEY_SPEC=tests/region-import-audit.spec.mjs bash scripts/check-app-journey.sh`（`AUDIT_ED=lite` 测 Lite，`JOURNEY_SRC` 换更大的合成数据，`JOURNEY_ASSETS` 指向旧构建做对比）。源码网关 + 临时数据目录跑一次首次导入并转入后台，逐页停留滚动，统计导航以外的整页渲染、各区域刷新、长任务、滚动跳动、停留期间被替换的区域根节点、下拉是否保持，以及三个原生面板与拖拽区域上报，结果写到 `test-results/region-import-audit-<ed>.json`。

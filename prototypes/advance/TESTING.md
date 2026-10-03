# Demo 测试说明

测试用 Playwright 在本机 Chrome 中运行，覆盖 6 种 Mac 窗口尺寸（mac-14 1512×982、mac-13 1280×800、mac-16 1728×1117、studio 2560×1440、small 1024×700、compact 820×760）。交互类用例只在 mac-14 运行，布局类用例在全部尺寸运行。

## 运行

```bash
pnpm install                                         # 在仓库根运行，统一使用根锁
cd prototypes/advance && pnpm test
```

- 只跑一个文件：`npx playwright test tests/effects.spec.mjs --project=mac-14`
- 截图检查：`node tools/shoot.mjs --sizes mac-14,small,compact --routes overview,sessions --theme light --out shots`
- 构建产物是否最新：`pnpm check`

## 测试文件与测试流程

下表由各测试文件开头的注释生成，每个文件的完整流程（前置状态 → 操作 → 期望）写在文件顶部。

### behavior.spec.mjs（9 个用例）

（见文件内注释）

### effects.spec.mjs（10 个用例）

Guards the motion and live effects of the baseline demo (artifact v2 = main c97c818). Redesigns may change how these
look, but each effect must keep working; replacing one needs an equal-or-better substitute and an update here.

Test flow (each test starts from a fresh page at mac-14 unless noted):
 1 keyframes      stylesheet still defines spin / pulse / blink (caret) / shim (shimmer) / fadein / grow
 2 reveal         openReveal() plays a staged ~3 s sequence (stage label advances), click skips to the end;
                  with prefers-reduced-motion it opens already settled
 3 onboarding     step 3 of first launch completes its steps one by one (OB.prog 0 → 3 over time)
 4 replay         startPlay() advances S.sess.ph over ~8 s and stops at the end; ⌘/Ctrl + wheel zooms;
                  the time/step axis toggle switches S.sess.axis; the playhead can be set and re-rendered
 5 studio         a generation run walks its steps, streams code lines, keeps a live log, and can be stopped
 6 typing         「重新生成」types the AI lede progressively; 「问本地 Agent」streams its answer with a caret
 7 hud            dragging the pill shows 6 snap points and snaps on release; ⌥ places it freely;
                  the live timer ticks
 8 status         menu-bar badge differs by shape and colour per state and pulses while running;
                  notifications slide in and stay while hovered; the undo toast counts down
 9 transitions    switch knob, sidebar and window close/minimise animate; reduced motion collapses durations

### p-live.spec.mjs（8 个用例）

Live surfaces (branch ui/p-live): menu-bar panel, floating HUD, desktop widgets, the simulated-event state machine and
the settings sections that drive them. Flow:
 1. matrix channels   notify matrix columns act independently: a「会话完成」with only 悬浮组件 ticked changes S.hudSim and
                      leaves the menu-bar badge (S.sim) alone, and vice versa (BUG-40); muting blocks the HUD channel but
                      the badge still updates (BUG-44)
 2. settle / idle     stuck + ctx then ignoring stuck falls back to ctx, ignoring ctx to the resting state (BUG-74);
                      from idle, an alert that is ignored (or a「完成」after its 8 s) returns to idle and the HUD stays hidden
                      (BUG-41); the demo menu's idle / running entries reflect S.simBase
 3. done → trajectory 「查看」after a「完成」opens the finished session, not the running one (BUG-42)
 4. newsrc twice      two「发现新的数据来源」banners both clicked add Cursor once (BUG-43)
 5. panel             running: live card with the shared context bar, 7-day columns with counts and「今」; idle: yesterday's
                      metrics carry a 30-day baseline; 预览 / Codex row close the panel before jumping (BUG-82)
 6. HUD               density band and pill bars come from the running session's trajectory (same numbers as liveBuckets),
                      not random; the metric grid uses the context bar; a render() during a drag does not strand it (BUG-45)
 7. widgets           three sizes change the card count and column height; the week chart has 7 weekday labels and only the
                      top segment is rounded; size persists in localStorage
 8. settings          默认时间范围 persists across reload (BUG-51); 不再提示此类 can be undone in 设置 › 通知 (BUG-83);
                      the matrix shows per-column counts; AI 通道 switches follow the engine; settings window and its
                      controls stay inside the viewport at the compact size and in full screen (BUG-78)

### p-overview-persona.spec.mjs（9 个用例）

A1 概览 + A2 协作人格（分支 ui/p-overview-persona）。每个用例从新页面开始，只在 mac-14 跑一次。

测试流程：
 1 kpi        五张指标卡用环比三件套（▲/▼ + 变化量 + 「上期」），摩擦率按极性着色；关掉「对比上一周期」后环比消失；
              自主比写成绝对差「+2.1」而不是「2.1×」（A1-V01）
 2 trend      度量 / 堆叠·分组·100% / 图表↔表格 切换都重绘；表格视图带 sticky 表头容器；
              点图例只隐藏本图系列，S.agents 不变（A1-V09）；拖选一段后指标卡按范围重算并出现「清除刷选」，清除后恢复
 3 heat       消息数 / 纠偏率切换；点格子只按小时筛选并在提示里说明不分星期（BUG-10）
 4 evidence   「做得好」的证据数等于完成会话数，点击后 A3 的筛选是 结果=完成（BUG-11）；会话结果条点一段同样下钻
 5 regen      连点「重新生成」只保留一个定时器（最终文本是完整的一句话）；重绘后导语与「刚刚已同步」保留（BUG-66）
 6 scope      设置主题筛选后，侧栏、A1 人格卡、A2、导出报告的人格代码一致，并注明「主题筛选不计入人格」（BUG-06）
 7 persona    周期切换、与过去 / 与全体对照、四维度双向条有 45–55 带与参照刻度、演变折线挂载、指纹外环点一段展开会话点再点收起
 8 fit        契合度条有 95% 区间；停用来源的 Agent 不可点、点击 soloAgent 不改筛选（BUG-49）
 9 low-sample 样本不足时列出「移除后 n≈」的放宽芯片并可一键放宽（A2-V08）；全部来源停用时给「打开设置 · 数据源」（BUG-50）

### p-pane-scroll.spec.mjs（2 个用例）

窗格独立滚动（styles/88-panes.css + js/88-panes.js）：主从分栏并排时各窗格自己滚，页面不滚；堆叠时退回整页滚动。
流程：
  1. mac-14：会话轨迹、优化建议、生成工坊、导出分享卡里，对每个窗格滚动滚轮 → 只有它动，其他窗格与 #content 不动；
     从别页进入会话页时，列表里靠后的选中行在列表窗格内可见，#content 不滚。
  2. 全部尺寸：内容列够宽（≥ 800px）时会话页进入窗格模式且 #content 不溢出，否则整页滚动。

### p-share.spec.mjs（2 个用例）

分享卡（src/js/55-exports.js）：每个时间长度一张卡，卡上的人格就是该窗口算出的人格；预览（SVG）与 PNG 共用一份绘制指令。
流程（mac-14，示例数据）：
  1. openShare() 列出 近 7 / 30 / 90 天与全部；点每一行，预览换成那个窗口的类型码与标签（周卡 / 月卡 / 季卡 / 全时卡）；
     Lite 的「导出分享卡」打开同一个弹窗
  2. sharePNG 是 1080 × 1350，画出的文字与 SVG 预览完全相同；页眉是 Orbit·知音 字标，类型码用 --font-type

### p-recs-library.spec.mjs（8 个用例）

A7 优化建议 + A8 资源库 + 安装闭环（branch ui/p-recs-library）。

Test flow (fresh page per test; interaction tests run once at mac-14, layout checks at every project):
 1 recs list      cards are sorted by the saving share (省时 %, the token % where time is not measured), each shows the
                  time / token percentages of the whole trajectory, the agent dots and the resident-token share; the detail head has the three KPI cells; cards are keyboard-selectable
                  (Enter on a focused card, BUG-61) and a double click on「不适用」strikes one card only (BUG-65)
 2 install loop   预览 (scope「仅项目」→ the target path moves into the project, BUG-22) → 下一步 (a double click does not
                  skip the confirmation, BUG-64) → 确认写入 → the sheet stays on「已写入」with a counting-down undo →
                  完成 hands the remaining seconds to the toast → the card shows 追踪中 with the scope → ⌘Z undoes once
                  and a second ⌘Z reports nothing to undo (BUG-24)
 3 primary kinds  openInstall on a tutorial rec opens the tutorial tab instead of installing it (BUG-25); an installed
                  rec cannot be installed twice (BUG-37)
 4 tracking       快进 7 天 renders the ▲ timeline, one dumbbell per metric with n and a 95% interval, and a verdict
 5 evidence       「依据 · N 个会话」leaves other session filters behind and lands on A3 (BUG-27)
 6 library search typing re-renders the results but not the input; pinyin composition (CDP IME) is not interrupted and
                  ends with「钩子」in the box (BUG-32)
 7 library install「获取」on cloudflare-deploy previews the plugin's own file, marks only that item installed (BUG-28),
                  the toolbar count equals the sheet count (BUG-29), and 撤销 removes it again
 8 library misc   「不感兴趣」hides the card without changing「和你相似的人」(BUG-31); the sort toggle reorders the picks;
                  the match bar has three segments and the peer bars carry the all-users tick
 9 layout         recs and library have no horizontal overflow at any project size, light and dark

### p-sessions.spec.mjs（6 个用例）

A3 会话轨迹（src/js/42-a3-sessions.js + styles/43-a3-sessions.css）。只在 mac-14 跑一次。
流程：
  1. 列表口径：结果 = 放弃 时今天 / 运行中的会话也要满足筛选（BUG-02），页头不再写死「1 个运行中」（BUG-03）；
     「全部历史」只渲染 120 行时给出截断提示，「加载更多」追加（BUG-05）；运行中时长按真实分钟（BUG-68）；
     标记为不计入分析的会话仍留在列表并带标签（BUG-19）。
  2. 搜索：组字中的 input 事件不改状态；真正输入后只重绘列表，输入框是同一个节点且保持焦点（BUG-12）。
  3. 轨迹：总览条与时间线都由 VZ 挂载（含上下文装饰层与顶部相对时间轴）；+ 以播放头为锚缩放并更新「适应」与视窗；
     ⌘/Ctrl + 滚轮缩放后「适应」不再高亮（BUG-17）；「适应」复位；步数模式有整数刻度（BUG-18）；
     点关键时刻列表跳转播放头并高亮徽章，检视面板跟随；‹ › 逐事件；点击空白处移动播放头；拖播放头手柄；刷选显示选段统计。
  4. 从其他入口切到另一个会话：播放头回到末尾、视窗复位（BUG-15）；回放中离开页面即停止（BUG-16）。
  5. 对比：两条时间线是独立的 VZ 实例、标题各自对应（BUG-13）；依次点选先换 A 再换 B（BUG-14）；差异列有 Δ 与阶段占比。
  6. F25 对人友好：「这次会话发生了什么」摘要卡（目标 / 过程 / 阶段表 / 卡点 / 结果）的分阶段计数加起来等于会话自身的工具、失败、消息数，
     不标 AI；卡点可跳转播放头；泳道与图例用通俗说法、阶段带有时间范围与悬停说明、等你批准画在「你的消息」泳道；
     关键时刻写「为什么重要」；列表与详情各自滚动，页头卡不被压扁。

### p-studio-flows.spec.mjs（7 个用例）

Branch ui/p-studio-flows: A9 studio workflow, command palette, ask-the-local-agent, exports and first launch / reveal.
Runs once, at mac-14 (behaviour does not depend on the window size; the layout is covered by smoke + screenshots).

Test flow:
 1 context pack   the token stack has one segment per ticked item and a budget mark; ticking「原始对话片段」pushes the total
                  over the 24k budget (bar turns critical, log warns); redaction hits follow the ticked items; the per-item
                  preview sheet lists samples with placeholders when redaction is on and raw values when it is off;
                  an empty pack cannot start a run (BUG-38)
 2 workflow       a v1 run walks 6 steps in order, streams the draft, shows four check rows (spec / safety / replay with
                  three session rows / judge), then marks the artifact「待审阅」; the quick template skips the checks
                  (rows read「已跳过」) and the strict template adds a cross-check step (BUG-81)
 3 run guards     while running the type is locked (BUG-33) and studioStart / ⌘↩ is ignored (BUG-34); typing in the goal box
                  keeps focus and caret across the per-step redraw (BUG-35); a redraw while typing on another page does not
                  steal focus (BUG-67); stopping keeps the partial draft
 4 artifact       install → confirm marks the run installed (button reads「已安装」, undo row appears) and refuses a second
                  install (BUG-37); saving to the library twice yields one item plus a toast (BUG-36); history lists only
                  studio output (BUG-86); the ask sheet's「交给生成工坊」does not wipe a running run (BUG-39)
 5 palette        ⌘K while the first-launch overlay is open does nothing (BUG-53); Return during IME composition does not run
                  a result (BUG-56); after picking a page focus lands on the page title, not <body> (BUG-59)
 6 ask / export   the figma answer follows the installed state (BUG-21); the report's persona uses the filtered set and
                  names the filter (BUG-06)
 7 first launch   Space on a source checkbox keeps focus there; the progress page redraw keeps focus (BUG-54); facts ignore
                  the main window's project filter (BUG-84); Tab cycles inside the overlay (BUG-55); reveal takes focus

### p-tools-projects-sentiment.spec.mjs（4 个用例）

A4 工具调用 / A5 项目习惯 / A6 情绪语义 页面测试（分支 ui/p-tools-projects-sentiment）。流程：
  A4：1. 打开 demo 进入 tools；KPI 四卡各带迷你线与环比；2. 点「工具」列头两次，行顺序按名称升 / 降变化（BUG-20）；
      3. 「仅看失败」后列头与 KPI 口径同步为「失败次数」；4. 展开 Bash 行，出现最近调用与「在轨迹中查看」，点击跳到会话页；
      5. 调用链矩阵为 HTML grid（36 个格子 + 6 个行 n），悬停一格高亮整行整列（.hl）；6. 展开一类失败原因，「相关会话」把 S.fric 设为工具失败并进入 sessions；
      7. 切到 7 天后迷你线列头随范围（BUG-85）；8. 标记 figma 已移除后页头变为 1 个 MCP，S.tools.figma 同步（BUG-21）。
  A5：1. 项目表任何单元格不被裁切（scrollWidth ≤ clientWidth），含摩擦率列；2. 散点挂载为 pscatter：有拟合线、置信带、残差竖线与尺寸图例；
      3. 对比模式下点第二个项目：表中出现 A / B 徽标、散点出现 B 环；4. 全局项目筛选 → 详情定位到该项目（BUG-07）；
      5. 退出对比后 A 选成原 B → B 被清掉（BUG-71）；6. 覆盖矩阵格子数 = 配置类型数 × 项目用到的 Agent 数。
  A6：1. 情绪图为 moodcorr：分布带 + 中位线 + 纠偏柱共用一张 svg，一条游标跨两图；指针移动后游标可见、tooltip 含「情绪中位数」与「纠偏」；
      2. 「看表格」切到表格视图并可切回；3. 点一个主题后其它主题仍在（BUG-72）；4. 不同反馈语的出处不同（BUG-73）；
      5. 90 天时说明文字为「每周」（BUG-69）；6. AI 抽取内容带紫色 .aib 标识；7. 三页浅 / 深色均无页面错误。

### shell.spec.mjs（14 个用例）

Shell (window model + global controls) tests. Each runs in all six Mac viewports (see playwright.config.mjs).

Flow per test:
 1. window model     open the demo → read #win (left/top/size/data-mode). Stage too small for 900×600 → "fit" (16px margins).
                     Otherwise the default is the published layout: the window fills the stage (24px sides, 18px top /
                     bottom) and on stages ≥ 1500px starts at x = 412 so the desktop widgets keep their column (visible,
                     never covered); shrinking the viewport re-fits an untouched window. Then: drag the title row by (60,40)
                     → window moved (clamped to the stage); drag the SE handle by (−100,−80) → smaller; drag it far →
                     clamped to 900×600; a viewport change now keeps the user's size; double-click the title → zoom (fills
                     the area under the menu bar) → double-click → restored; ⌃⌘F → full screen (menu bar slides away,
                     window fills the stage) → green light → restored; reload → rect comes back from localStorage.
 2. sidebar          ⌃⌘S hides / shows the sidebar (toolbar shifts right of the lights); in a window narrower than 900px the
                     sidebar is hidden by default and the toggle shows it as an overlay that the content scrim closes.
 3. container query  at the same viewport, narrow the window (S.win.w = 1000) → the overview .two grid drops to one column
                     and the metric tiles to 3 per row; widen again → restored. Narrow stages assert the single column.
                     Thresholds follow 90-responsive.css: .two, .sess and .tiles 800 (tiles again at 640), in content-column px.
                     A toolbar that cannot fit its page title moves items into the » popover instead of clipping it.
 4. settings         openSettings() → #set fully inside the viewport, six tabs visible, each tab renders, main window
                     inactive (grey lights); Esc closes it.
 5. menu-bar panel   click the Orbit status item → #pop right edge aligns with the status item (±1.5px), 6px under the bar.
 6. HUD              the pill never covers the window's title row; when any snap point is free of the window and the
                     visible desktop widgets it covers neither — checked at the default layout and again with the window
                     shrunk to 900×600 in a corner, where the top row is certainly free.
 7. sheet            openModal() → focus lands on the default (.btn.p) button, the scrim covers exactly the window, the sheet
                     hangs 52px under the window top; Return triggers the default button, Esc closes.
 8. shortcuts        ⌥2 → persona, ⌘K → palette, ⌥0 restores a closed window; menu labels match the bindings.
 9. page hook/event  PAGES[route].keys(e) returning true consumes the key, false lets globals run; toggling the sidebar
                     dispatches window 'orbit:layout' with {win, side, main}.
10. dark contrast    selected sidebar row vs sidebar ≥ 1.3; window / sidebar / card pairwise ≥ 1.15 in dark mode.
11. overflow         no horizontal overflow (document, #main, #win inside the viewport) with the sidebar shown / hidden,
                     zoomed and in full screen, on three representative pages.
12. type & chrome    shell text only uses the macOS type scale (10/11/12/13/15/17/22/26); every surface uses the system sans (SF Pro + PingFang SC, 600-weight
                     title, tabular counts), keycaps SF Mono, no web fonts; resize handles are invisible
                     (no background, no pseudo content); notifications are 344px wide, 16px from the stage edge, and reveal
                     their actions on hover.
13. motion           every effect of the published demo is still wired up (mac-14 only): keyframes blink / fadein / grow /
                     pulse / shim / spin plus popin / sheetin / slidein / slideout; .nt slides + fades in and survives hover;
                     the toast undo countdown ticks; the menu-bar badge changes shape / colour per state and pulses while
                     running; the switch knob slides; the window scales away on close; the HUD drag shows six snap points,
                     ⌥-release places it freely, the expanded card grows away from the anchor, the timer / tool name tick;
                     the reveal runs its 3s storyboard; onboarding step 3 appears line by line (obRun).

### smoke.spec.mjs（2 个用例）

Every page renders without runtime errors and nothing scrolls sideways; every overlay, menu, simulated
event and shortcut opens cleanly. Together they fail when a source file goes missing from the build.

### vizkit.spec.mjs（18 个用例）

VZ 组件库测试。流程：
  1. 打开 demo，go('vizkit') 进入隐藏的组件画廊，取 VZ_DEMO.specs() 得到每种组件的示例 spec（新增示例自动纳入 1–2）；
  2. 在 #content 顶部挂一个实验区，把每个 spec 分别 mount 到 360 / 720 / 1200px 宽的容器里；
  3. 逐个断言：innerHTML 无 NaN / Infinity / undefined、容器不横向溢出、SVG 不宽于容器、文字不越出 SVG；
  4. 坐标文字的 computed font-size 在三种宽度下相同（恒定像素，不随宽度缩放）；
  5. 交互：十字准线 tooltip（hover）、图例点击隐藏 / ⌥ 点击只看 / 悬停淡出其他系列、brush 拖选回调、键盘 ← → / Enter；
  6. 状态：空数据与样本不足；深色模式下系列色、文字色与语义色（--vz-*）取自主题变量；表格视图行数与数据一致；
  7. 时间线原语：密度泳道的桶数 ≤ 像素桶数且无逐事件刻度、关键时刻在窄宽度合并成簇、now 标记、range 收窄后窗外事件不画、只有阶段也有有效范围；
  8. minimap：拖视窗平移（位移 = 鼠标位移）、拖手柄缩放（另一端不动）、Home 复位并报告 null、↑ 缩小视窗；
  9. 其他：bar 的 hatch 斜纹与 <pattern>、diverging 的 deadband、mood 色阶 6 档、KPI 环比文案（▲▼ + 变化量 + 上期）；
 10. 视觉语言：刻度 / 数值 / KPI 环比用 tabular 数字（var(--font-num)），与名称说明同为系统无衬线；spec.head 输出 .eb / .ct / .cap 层级；
 11. 动效：首次绘制 svg 带 vz-in（线描入、柱升起），重绘不再带；prefers-reduced-motion 下 computed animation-name 为 none；
 12. 回放：播放头可拖并吸附到事件、onPlayhead 回调；[ ] 逐事件；VZ.replay 走到末尾自动停且回放中未发生的事件隐藏；
     axisMode 'steps' 事件等距、刻度为整数步；⌘ / Ctrl + 滚轮以光标为锚缩放并通过 onView 同步 minimap 视窗，Home 复位。

## 动效守护

`tests/effects.spec.mjs` 以线上版（main c97c818）为基准，锁定人格揭晓、首次启动、轨迹回放与缩放、生成工坊流式、打字与流式回答、悬浮组件吸附、状态提示、过渡与减弱动态效果。改版时这些用例不能删减；替换效果需给出等价替代并同步更新用例。

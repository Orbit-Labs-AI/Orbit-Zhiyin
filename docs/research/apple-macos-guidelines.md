# Apple macOS 指南对照：Orbit 原生壳与 UI

> 文档状态：研究快照。正文保留原基线、日期与证据；其中的状态和数字不代表当前版本。现行入口见[文档导航](../README.md)。


> 状态：调研 · 日期：2026-10-03 · 核对版本：`fix/app-deep-debug`（`d4f2edd7`，Orbit 0.0.2 / macOS 14+）
>
> 目的：对照 Apple 官方资料，审查 Orbit 原生宿主（`apps/desktop/Orbit.swift`）与页面中原生相关部分（`prototypes/advance/src/js` 的 22 / 25 / 30 / 57 / 60 / 61 / 62 / 85 / 95 / 97 系列）的 Mac 习惯符合度，给出「指南要点 → Orbit 现状 → 建议」。
>
> **依据**：官方页面正文由 `developer.apple.com` 的文档数据接口抓取（2026-10-03），要点为概括而非引用原文；HIG 中以表格给出的内容（标准菜单项清单、macOS 文本样式字号表）未抓到，相关数字取自 Apple 公开的惯例，已在文中标明「惯例」。**现状**一栏来自对源码的阅读，未做真机交互验证的推断都标了「待实机验证」。
>
> **范围说明**：第一阶段 `fix/app-interaction-bugs` 正在修复且本文不重复处理的问题：首次启动进 Lite 与偏好丢失（WKWebView `nonPersistent` + 随机端口）、窗口只能在边缘拖动、导入时持续重渲染、人格样本门槛与「?」、Agent 下拉默认未全选、字体（换 PingFang SC + SF Pro + tabular-nums）、原生菜单缺「文件」「帮助」与引导入口、导入失败。涉及这些的小节只写指南要点并注明「已在第一阶段处理」。

## 0. 摘要

| 主题 | 总体 | 最值得先修的点 |
| --- | --- | --- |
| 窗口 | 用了系统窗口与系统红绿灯，方向正确 | 拖动区（第一阶段）、`⌘W` 缺失（并入「文件」菜单） |
| 菜单栏 | 有 App / 编辑 / 显示 / 窗口四个菜单 | 快捷键冲突（隐藏其他与 HUD 同为 ⌥⌘H）；页面快捷键不在菜单里 |
| 状态栏项 | 左键弹出、右键菜单，有模板图标 | 「菜单栏角标」渠道在原生端不存在；无 Dock 菜单兜底 |
| 设置 | `⌘,` 可用 | 设置是页内伪窗口；「登录时启动」开关是假的 |
| 通知 | 已接 UserNotifications | 只在页面隐藏时才发系统通知，测试通知触发不了授权弹窗 |
| 深色模式 / 无障碍 | 已处理减少动态效果、增强对比度、降低透明度 | 窗口底色固定浅色；全局禁用文本选择 |
| 分发 | ad-hoc 与 Developer ID 两条路径都有 | Developer ID 路径未带 entitlements，PyInstaller 随包 helper 在 Hardened Runtime 下可能起不来 |

## 1. macOS 设计总则

**指南要点**（[Designing for macOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos)、[macOS 开发者主页](https://developer.apple.com/macos/)）

- Mac 的显示器大、可外接多屏，用大屏减少嵌套层级与模态；观看距离约 1–3 英尺，人们常同时开多个 App，并期待 App 在活动与非活动状态之间平滑过渡。
- 让人能调整、隐藏、显示、移动窗口，并支持全屏。
- 用菜单栏承载「所有命令」，用键盘快捷键加速，支持个性化。

**Orbit 现状**：主窗口可缩放、可全屏（`⌃⌘F`），尺寸与位置由 `setFrameAutosaveName("OrbitMainWindow")` 记忆，且会在显示器消失后重新居中（`resetFrameIfOffscreen`）。大屏利用较好（侧栏 + 内容 + 小组件列）。页面里大量命令只存在于页内 JS 快捷键与命令面板，没有进入菜单栏（见 §3）。

**建议**：把「可发现性」当成 Mac 化的主线：菜单栏是命令的权威目录，命令面板与快捷键只是它的加速层。

## 2. 窗口

**指南要点**（[Windows](https://developer.apple.com/design/human-interface-guidelines/windows)）

- 主窗口承载主导航与内容；辅助窗口只做一件事并带关闭按钮。
- 避免自定义窗口外观与控件；做不到与系统完全一致会让 App 显得「坏了」。
- 窗口有主窗口 / 关键窗口 / 非活动三种状态，外观应随状态变化（红绿灯在非活动时变灰，内容失去活力色）。
- 底部栏里不要放关键信息；用户常把窗口挪到屏幕外而遮住底边。
- 对用户说「窗口」，不说 scene。

**AppKit 相关**（[`performDrag(with:)`](https://developer.apple.com/documentation/appkit/nswindow/performdrag(with:))、[`isMovableByWindowBackground`](https://developer.apple.com/documentation/appkit/nswindow/ismovablebywindowbackground)、[`setFrameAutosaveName(_:)`](https://developer.apple.com/documentation/appkit/nswindow/setframeautosavename(_:))、[`isRestorable`](https://developer.apple.com/documentation/appkit/nswindow/isrestorable)、[`titlebarAppearsTransparent`](https://developer.apple.com/documentation/appkit/nswindow/titlebarappearstransparent)）

- `performDrag(with:)` 把拖动交给 Window Server，窗口因此能参与切换空间等系统行为；它在收到 mouseDown 后由视图调用。
- `isMovableByWindowBackground` 让整个窗口背景可拖，适合内容全是自绘的窗口；`titlebarAppearsTransparent` 只有在 `fullSizeContentView` 下才有意义。
- 带 `titled` 样式的窗口默认 `isRestorable = true`；启用状态保留应同时给出 restoration class。

**Orbit 现状**

- 主窗口：`titled + closable + miniaturizable + resizable + fullSizeContentView`，标题隐藏、标题栏透明、`isMovableByWindowBackground = false`，内容视图是铺满的 WKWebView。红绿灯是系统的（页面里的 `.lights` 在 `body.native` 下被隐藏），符合「不自绘窗口控件」。
- 拖动：WKWebView 吞掉了标题栏区域的鼠标事件，所以只有边缘能拖 —— **已在第一阶段处理**（四周拖动带与标题栏空白拖动）。建议实现时走 `performDrag(with:)` 而不是页面里模拟移动，这样才能参与空间切换与窗口吸附。
- 浮动面板（HUD、桌面小组件）：`FloatingPanel` 是无边框 `NSPanel`，按住 ⌘ 或点击顶部 12 pt 拖动，已经用 `performDrag`，位置用 `setFrameAutosaveName` 记忆。

**建议**

1. 页面里 `22-window.js` 仍保留整套「模拟窗口」逻辑（拖动、8 px 缩放边、双击缩放、全屏菜单栏悬停）。它只在非原生环境（浏览器、mock）生效，原生下 `winRect()` 直接返回 `mode: 'native'`。可以保留作演示，但原生行为的任何修复都不要再往这里加。
2. 面板没有设置 `title`，VoiceOver 与「窗口」菜单里读不出名字，见 §8。
3. HIG 说「不要在底部放关键信息」：原生壳里没有底栏，无需处理。

## 3. 菜单栏与菜单

**指南要点**（[The menu bar](https://developer.apple.com/design/human-interface-guidelines/the-menu-bar)、[Menus](https://developer.apple.com/design/human-interface-guidelines/menus)）

- 标准顺序：App 名、文件、编辑、格式、显示、App 专属菜单、窗口、帮助；Apple 菜单在最左，菜单栏扩展在最右。
- 始终显示同一组菜单项，不可用时置灰而不是隐藏；菜单本身即使全部置灰也要能打开。
- 为标准菜单项支持标准快捷键；自定义快捷键只在必要时才用。
- 自定义命令一律放进菜单栏（哪怕不常用）：这样才好找、能配快捷键，也才能被 Full Keyboard Access 触达。
- 窗口菜单即使只有一个窗口也要提供，含「最小化」「缩放」；显示/隐藏类菜单项的标题要反映当前状态（如「隐藏侧边栏 / 显示侧边栏」）。
- 菜单项标题用动词或动词短语，标题式大写（英文）；需要进一步输入的命令加省略号「…」；子菜单少用且只放一层。
- 动态菜单项（按住修饰键变化）不能是完成任务的唯一途径。
- 菜单栏扩展：用符号做图标，点击时显示菜单而不是弹出框（除非内容复杂到菜单放不下）；是否出现在菜单栏应由用户决定，最好在设置里或首次设置时给选项；不要依赖它一定可见，同时给 Dock 菜单兜底。
- 「设置…」放在 App 菜单，快捷键 `⌘,`。

**Orbit 现状**（`buildMenu()`）

- App 菜单：关于、设置…（⌘,）、隐藏 / 隐藏其他 / 全部显示、退出，结构标准。没有「服务」子菜单（惯例上 App 菜单应有，影响不大）。
- 编辑：撤销 / 重做 / 剪切 / 拷贝 / 粘贴 / 全选，用响应链选择器，标准；缺「删除」与「查找」。
- 显示：命令面板（⌘K）、切换 Lite / Advance（⌃⌘L）、刷新（⌘R）、重新载入页面（⇧⌘R）。**没有「显示 / 隐藏侧边栏」**，页面里的 `⌃⌘S` 只在页内 JS 生效。
- 窗口：最小化（⌘M）、缩放、进入全屏幕（⌃⌘F）、Orbit 主窗口（⌘0）、显示 HUD（⌥⌘H）、桌面小组件（⌥⌘W）。「进入全屏幕」标题是静态的，进入全屏后不会变成「退出全屏幕」。
- 缺「文件」「帮助」与关闭窗口（⌘W）—— **已在第一阶段处理**（并加侧栏引导入口）。第一阶段合入后请确认 ⌘W 对应 `performClose` 且菜单项存在。
- 页面里的快捷键（`85-keyboard.js`）：⌘1–9 切页、⌘F 页内搜索、⇧⌘S 分享卡、⇧⌘E 报告、⌘T 图表/表格、⌘[ 返回、⌘↩ 主操作、⌘Z 撤销安装、⌥⌘P HUD、⌃⌥T 面板，**只在 WKWebView 的 keydown 里处理，菜单栏里没有对应项**。

**建议**

1. 修快捷键冲突：「隐藏其他」与「显示 HUD」同为 ⌥⌘H，先注册的「隐藏其他」赢，HUD 快捷键实际无效；`apps/desktop/README.md` 写 HUD 为 ⌥⌘H，设置页与快捷键面板写 ⌥⌘P，三处不一致。统一为 ⌥⌘P（页面已用），小组件的 ⌥⌘W 与系统「全部关闭」的惯例键相同，建议改为无快捷键或 ⌥⌘D（见 findings）。
2. 增加「前往 / 页面」菜单（或放进「显示」），列出 Advance 的页面并带 ⌘1–9；加「导出」「分享卡」「报告」「重新索引」项。菜单点击仍通过 `orbit:command` 派发，页面 JS 快捷键保留给浏览器与 mock。
3. `⌘Z`：Edit 菜单的 `undo:` 先于页面 keydown 被菜单拦截，WKWebView 对 `undo:` 的校验结果决定页面的「撤销安装」是否还能收到按键 —— **待实机验证**。更稳的做法是编辑菜单的「撤销」在页面有可撤销安装时走 `orbit:command undo`。
4. 显示 / 隐藏项按状态改标题：全屏、HUD、小组件、侧栏。HUD 与小组件已用 `validateMenuItem` 打勾表示开关状态（菜单栏与状态栏菜单一致），可保持。
5. 菜单项标题检查：「刷新」「重新载入页面」含义相近，建议合并为「刷新」，「重新载入页面」放到按住 ⌥ 的动态项里（只能是辅助途径）。

## 4. 状态栏项（菜单栏扩展）与 Dock 菜单

**指南要点**：见 §3 末段，以及 [`NSStatusItem`](https://developer.apple.com/documentation/appkit/nsstatusitem)、[`NSPanel`](https://developer.apple.com/documentation/appkit/nspanel)。

**Orbit 现状**

- 状态栏项：模板图标（随浅色 / 深色菜单栏着色，尺寸 16 pt），左键弹出 `NSPopover`（360 × 560，内容是 `/app?surface=panel`），右键或 ⌃-点击出菜单（打开 Orbit / 显示 HUD / 桌面小组件 / 退出）。左键弹出框而非菜单，属于 HIG 说的「内容复杂才用」的例外，合理。
- 用户可否隐藏：没有设置项控制状态栏项显隐（用户可 ⌘-拖出菜单栏，系统允许）。`statusItem.autosaveName` 未设置，系统会自动命名，顺序在多次启动间不保证稳定。
- 页面承诺了「菜单栏角标」：设置 › 通知 › 投递矩阵有「菜单栏角标」列，设置 › 数据源写着「暂停后菜单栏图标不显示状态角标」。**原生端没有任何改变状态栏图标的桥接消息**（`nativeFeatures` 里没有，`Orbit.swift` 里没有对应代码），角标只在模拟的菜单栏（`#mbar`）上存在，而 `body.native` 下 `#mbar` 被隐藏。这是宣传了但不存在的功能。
- 没有 Dock 菜单（`applicationDockMenu`）。HIG 明确建议为菜单栏扩展提供 Dock 菜单兜底。

**建议**

1. 要么实现角标（桥接 `statusBadge`，状态栏按钮换成带点 / 着色的图像变体，模板图像配彩色角标需用非模板图或叠加层），要么在原生下隐藏该列并改文案。
2. 加 `applicationDockMenu`：打开 Orbit、显示 HUD、桌面小组件、暂停提醒。
3. `statusItem.autosaveName = "OrbitStatusItem"`；设置里加「在菜单栏显示 Orbit 图标」开关（`statusItem.isVisible`），并在引导里提一句。
4. 状态栏点击弹出框时没有调用 `NSApp.activate`，popover 内的输入框依赖 `makeKey()`，目前可用；改动时要保留。

## 5. 设置窗口

**指南要点**（[Settings](https://developer.apple.com/design/human-interface-guidelines/settings)）

- 默认值要对大多数人最优，设置项要少；不要把可从系统获取的信息放进设置，也不要重复系统全局选项（如外观、滚动、无障碍）。
- macOS：点 App 菜单的「设置…」打开自定义设置窗口，带工具栏切换窗格；窗口的最小化 / 全屏按钮置灰；工具栏不可定制且始终标出当前窗格；窗口标题随窗格变化（单窗格则用「App 名 设置」）；**恢复最近查看的窗格**。
- 任务相关的选项应放在任务现场而不是设置里。

**Orbit 现状**

- `⌘,` 与 App 菜单「设置…」可用，但设置不是 `NSWindow`，而是页面里的 `#set`：一张可拖动的浮卡，自带 `.lights` 假红黄绿灯（黄、绿置灰），位置存在页面内存 `S.setPos`，且受主窗口限制（不能拖出主窗口）。菜单点「设置…」会先 `showMain`，所以主窗口隐藏时会被拉出来。
- 窗格：通用 / 数据源 / 隐私 / 分析 / 通知 / 关于，顶部标签切换，窗口标题随窗格变化（`ptitle`），做对了。最近窗格 `S.setTab` 只在页面内存里，重载即丢（第一阶段的偏好持久化落地后可顺带存）。
- 「外观：跟随系统 / 浅色 / 深色」是 App 级外观设置，HIG（Dark Mode）明确建议避免。
- 「登录时启动」开关是假的：`S.login` 默认 `true`，`setLogin` 只翻转页面变量，仓库里没有 `SMAppService` 或任何登录项实现，原生 `nativeFeatures` 也没有对应能力。用户看到「已开启」，实际重启后不会启动。
- 「关于」页在 mock 下写死 `1.0（演示版）· 2026-10-01`，live 下会被网关 / 原生版本覆盖（`tlsSetPost`），这点没问题。

**建议**

1. 短期：保留页内设置浮卡（视觉语言一致），但把最近窗格持久化；原生下去掉假红黄绿灯，只留一个关闭按钮，或让 Esc / ⌘W 关闭它。
2. 中期：用 `/app?surface=settings` 在独立 `NSWindow`（`styleMask` 去掉 `miniaturizable` 与 `resizable`，标题随窗格，`setFrameAutosaveName`）里承载，真正符合 Mac 的设置窗口，并解决「主窗口隐藏时设置也出不来」。
3. 「登录时启动」：原生提供 `SMAppService.mainApp.register()` / `unregister()` / `status`（macOS 13+，项目最低 14），桥接 `loginItem` 的读写，开关状态以系统为准；非原生环境隐藏该行，默认值改为 `false`。
4. 外观分段：默认「跟随系统」保持，「浅色 / 深色」建议收进「高级」或删除；若保留，则必须同步 `NSApp.appearance`（见 §9）。

## 6. 引导（Onboarding）

**指南要点**（[Onboarding](https://developer.apple.com/design/human-interface-guidelines/onboarding)）

- 快速、有趣、可选；在启动流程之后出现，不属于启动体验。
- 用交互教学，给上下文提示，而不是一大段说明；教程应可跳过，跳过后别再反复出现，但要在设置、帮助里易于找回。
- 需要访问私有数据时，可在引导里解释并请求权限；否则在首次使用相关功能时再请求。
- 推迟非必要的设置，给合理默认。

**Orbit 现状**：首次启动由 `95-live-native.js` 在「没有投影或没有启用来源」时自动打开引导；四阶段进度（导入历史会话 → 统计 → 语义 → 画像）与「在后台继续」符合「可跳过 / 不阻塞」；引导完成后才由原生显示 HUD（`onboarded`）。通知权限在首次通知时请求，属于「在使用时请求」，合理。重新打开引导的入口缺失 —— **已在第一阶段处理**（侧栏入口）。

**建议**：「后台继续」之后的通知已经做了（`协作画像已生成`）；建议在引导的数据源步骤里提一句「Orbit 只读会话日志，不读凭据」，与设置 › 数据源的文案一致，降低选择文件夹时的疑虑。

## 7. 排版

**指南要点**（[Typography](https://developer.apple.com/design/human-interface-guidelines/typography)）

- macOS 系统字体是 SF Pro，且 **macOS 不支持动态字体（Dynamic Type）**；需要匹配系统控件的文本时用动态系统字体变体。
- 用系统字体不要内嵌；自定义字体必须保证可读，粗细过细时字号要更大；遵循各平台的默认与最小字号（惯例：macOS 正文 13 pt，说明文字约 10–11 pt，不低于 10 pt）。
- 数字列用等宽数字（tabular）。

**Orbit 现状**：正文 `13px/1.5`，与 macOS 正文一致；`tabular-nums` 已全局开启；字体栈当前含 Source Serif 4 与 JetBrains Mono 的内嵌字体包，中文没有 PingFang SC 优先 —— **已在第一阶段处理**（改为 PingFang SC + SF Pro）。样式表里有 15 行使用 9–10 px 字号，低于 HIG 惯例的最小可读字号。

**建议**

1. 第一阶段换字体后复查 9–10 px 的用法（图例、角标、`.cap` 小字），至少提到 11 px，等宽数字用 `ui-monospace`（SF Mono）。
2. 因为 macOS 没有动态字体，建议在「显示」菜单加「放大 / 缩小 / 实际大小」（⌘+ / ⌘− / ⌘0），用 `WKWebView.pageZoom` 实现并持久化；这是 Mac 上网页型 App 满足「可放大 200%」（HIG 无障碍里对文字放大的要求）的最低成本手段。

## 8. 无障碍

**指南要点**（[Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)）

- 支持更大的文字；颜色对比至少 WCAG AA（4.5:1），开启「增强对比度」时提供更高对比；不要只靠颜色传达信息。
- 为 VoiceOver 描述界面与内容；控件尺寸与间距要足够；支持键盘独立操作与完整键盘访问，不要覆盖系统快捷键。
- 开启「减少动态效果」时，用淡入淡出替代位移与旋转，收紧弹簧，去掉闪烁与视差。
- 不自动播放音视频，不闪烁。

**Orbit 现状**

- 做得好：`prefers-reduced-motion`、`prefers-contrast: more`、`prefers-reduced-transparency` 都有处理（`90-responsive.css`、`37-motion.css` 等）；全站约 180 处 `aria-*`；弹层有 `role="dialog" aria-modal`、焦点陷阱与回焦；焦点环 3 px；`isComposing` 已处理输入法回车。
- 不足：
  1. `body { user-select: none }`，仅 input / textarea / pre / 表格单元格例外，会话标题、项目名、路径、数字都无法选中复制，这与 Mac 用户的预期相悖（见 findings）。
  2. 页面快捷键不在菜单里，完整键盘访问用户无法通过菜单触达（§3）。
  3. 浮动面板没有窗口标题 / 辅助功能名称。
  4. 图表是否有文字替代：`ctxBar` 有 `role="img"` 和 `aria-label`，这是好样板，建议其它 vizkit 图也对齐（本次未逐一核查）。

## 9. 深色模式

**指南要点**（[Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode)）

- **避免 App 专属的外观设置**：用户会因为要改两处而困惑，甚至以为 App 坏了。
- 在浅色与深色（含「自动」切换，可能发生在 App 运行期间）下都要好看；在「增强对比度 + 降低透明度」组合下测可读性。
- 使用随外观自适应的语义颜色，避免硬编码；对比至少 4.5:1，小字争取 7:1；白底图片适当压暗。
- macOS：选「石墨」强调色时系统给窗口加桌面着色；自定义组件背景可以带一点透明度，只在中性状态下使用。

**Orbit 现状**：页面 CSS 同时响应 `prefers-color-scheme` 与 `data-theme` 手动覆盖；原生窗口底色 `window.backgroundColor` 写死为浅色 `#f5f4f0`，WKWebView 透明（`drawsBackground=false`，`underPageBackgroundColor=.clear`），所以深色模式下首帧加载、窗口缩放、橡皮筋过度滚动时会露出浅色底。页内「浅色 / 深色」覆盖不会同步到 `NSApp.appearance`，系统的 `NSOpenPanel` / `NSSavePanel`、通知、弹出框边框仍按系统外观，与页面不一致。

**建议**：窗口底色换成随外观的动态 `NSColor`（`NSColor(name:dynamicProvider:)`，浅色 paper、深色取页面 `--bg`）；新增桥接 `appearance` 同步 `NSApp.appearance`（`nil` 表示跟随系统）；见 §5 对外观分段的建议。`drawsBackground` 用的是 KVC 私有键，建议长期换成公开 API（`underPageBackgroundColor` 已设，另加透明 `NSVisualEffectView` 或保持 `NSWindow` 背景色）。

## 10. WKWebView 与数据存储

**指南要点**（[`WKWebsiteDataStore`](https://developer.apple.com/documentation/webkit/wkwebsitedatastore)、[`nonPersistent()`](https://developer.apple.com/documentation/webkit/wkwebsitedatastore/nonpersistent())、[`isInspectable`](https://developer.apple.com/documentation/webkit/wkwebview/isinspectable)、[`WKUserScript`](https://developer.apple.com/documentation/webkit/wkuserscript)）

- 默认数据存储持久化到磁盘；`nonPersistent()` 只存在内存里，文档的用途是「隐私浏览」；若要「配置档」式持久化，用 `init(forIdentifier:)`。
- 数据存储必须在创建 web view 之前赋给 `WKWebViewConfiguration`。
- `isInspectable` 默认 `false`，设为 `true` 才能用 Safari 的「开发」菜单检查。
- `WKUserScript` 要在创建 web view 之前加进 `userContentController`。

**Orbit 现状**

- `config.websiteDataStore = .nonPersistent()`：与随机端口叠加，导致页面 `localStorage` 偏好每次启动全丢 —— **第一阶段正在改为原生 `ui-prefs.json` 持久化**。补充一点：即使改为持久化数据存储，origin 含随机端口也会让 `localStorage` 按 origin 隔离而失效，所以原生持久化方案是对的；若将来想用 `localStorage`，需要给网关固定端口或用 `WKWebsiteDataStore(forIdentifier:)` 配合稳定 origin。
- 脚本：`bootstrapScript` 在文档开始时注入 `__ORBIT_TOKEN__`、`__ORBIT_ENDPOINT__`、`__ORBIT_NATIVE__`；消息处理器校验 `isMainFrame` 与 origin（host + port），这是对的。
- 没有设置 `isInspectable`，发布版无法用 Safari 检查页面，排查「原生壳里的 UI 与浏览器里不一致」只能靠日志。
- 导航策略：非网关来源的 http(s) 链接交给默认浏览器，`window.open` / `target=_blank` 不新开 WebView，符合预期。

**建议**：加环境变量开关（如 `ORBIT_DEBUG_INSPECT=1`）才设置 `webView.isInspectable = true`，既保持发布版安全又方便调试；`webViewWebContentProcessDidTerminate` 里重新加载会丢掉页面内状态，第一阶段持久化落地后会好很多。

## 11. 通知

**指南要点**：HIG 引导章节建议「在首次使用相关功能时再请求权限」；macOS 通知由 [UserNotifications](https://developer.apple.com/documentation/usernotifications) 提供，App 在前台时默认不展示，需在 `willPresent` 里返回展示选项。

**Orbit 现状**：`notify()` 首次使用时请求授权，`willPresent` 返回 `.banner / .list / .sound`，点击通知通过 `route` 打开主窗口对应页面，流程完整。问题在页面侧：`notify` 的系统通知分支条件是 `ORBIT.native.isNative && document.hidden`，即只有页面不可见（最小化或遮挡）才投递系统通知。窗口可见但 Orbit 不是前台（常见：Orbit 在副屏，用户在别的 App 工作）时 `document.hidden` 为 `false`，只出现页内横幅，错过通知。设置 › 通知的「测试通知」传了 `force:true`，但没有绕过 `document.hidden` 条件，因此窗口可见时测试通知也不会走系统，**授权弹窗永远不会被触发**；授权被拒绝也没有任何提示（`center.add` 的错误被吞，`granted == false` 静默）。

**建议**：条件改为「Orbit 不是活动 App（`!document.hasFocus()` 或原生下发 `isActive`）或页面隐藏」；`force` 一律走系统；设置 › 通知显示授权状态（通过桥接 `notificationStatus` 读 `getNotificationSettings`），被拒时给「打开系统设置」按钮（`x-apple.systempreferences:com.apple.Notifications-Settings.extension`）。

## 12. 生命周期

**指南要点**（[`applicationShouldTerminateAfterLastWindowClosed`](https://developer.apple.com/documentation/appkit/nsapplicationdelegate/applicationshouldterminateafterlastwindowclosed(_:))、[`applicationShouldHandleReopen`](https://developer.apple.com/documentation/appkit/nsapplicationdelegate/applicationshouldhandlereopen(_:hasvisiblewindows:))、[`NSApplication.helpMenu`](https://developer.apple.com/documentation/appkit/nsapplication/helpmenu)）

- 最后一个窗口关闭时是否退出由代理决定；返回 `false` 则 App 继续运行（菜单栏常驻类 App 的常规做法）。
- Dock 图标被再次点击会发 reopen 事件；系统默认只在没有可见 `NSWindow`（不含 `NSPanel`）时才创建新窗口，实现该方法可以接管。
- 设置 `helpMenu` 后系统会把 Spotlight 帮助搜索挂在该菜单上。

**Orbit 现状**：`applicationShouldTerminateAfterLastWindowClosed → false`、`applicationShouldHandleReopen → showMain`，关闭窗口只隐藏，状态栏项继续运行，Dock 点击恢复窗口，做法标准。单实例用 `flock` 数据目录锁，第二次启动激活已有实例，很好。退出时给 helper 发 SIGTERM 并等待至多 8 秒再 SIGKILL，处理得当。

**不足**

1. 退出时不检查正在进行的导入 / 分析任务，直接终止，下次启动任务被标为 `interrupted`。Mac 惯例是退出前提示「有任务正在运行」。
2. `NSApp.activate(ignoringOtherApps: true)`：macOS 14 起已弃用（参数不再起作用），应改 `NSApp.activate()`（项目最低 macOS 14）。
3. 没有实现 `applicationSupportsSecureRestorableState(_:) -> Bool`（返回 `true`）：macOS 14+ 对使用状态保留的 App 会在控制台警告。
4. 没关 `NSWindow.allowsAutomaticWindowTabbing`：系统可能给窗口菜单加「显示标签页栏 / 合并所有窗口」，而 Orbit 的页面无法承载标签页，应设为 `false`。
5. `desktop.log` 以追加方式写，无上限、无轮转。

## 13. 分发、签名与调试（简要）

**官方要点**（[Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)、[Hardened Runtime](https://developer.apple.com/documentation/security/hardened-runtime)、[Distributing your app for beta testing and releases](https://developer.apple.com/documentation/xcode/distributing-your-app-for-beta-testing-and-releases)、[Develop in Swift](https://developer.apple.com/tutorials/develop-in-swift/)）

- 在 App Store 之外分发应使用 Developer ID 签名并交给 Apple 公证（自动化扫描，不是 App 审核），公证后把票据 staple 到制品，Gatekeeper 首次启动时才会显示更友好的提示；可公证 App、磁盘映像（UDIF）与安装包。
- 公证要求启用 Hardened Runtime；Hardened Runtime 默认禁止 JIT、未签名可执行内存、动态库注入等，需要时用 entitlements 逐项放开，且只开必要的；entitlements 只加在可执行文件上，共享库、框架继承宿主的。
- 调试：Xcode 调试器、Instruments、Organizer；WKWebView 用 Safari Web Inspector（需 `isInspectable`）。

**Orbit 现状**（`apps/desktop/build.py`）：ad-hoc 签名为默认，设置 `ORBIT_SIGN_IDENTITY` 时加 `--options runtime --timestamp`，设置 `ORBIT_NOTARY_PROFILE` 时 `notarytool submit --wait` 并 staple。`LSMinimumSystemVersion = 14.0`、`NSHighResolutionCapable`、`LSApplicationCategoryType` 都有，并有 Mach-O `minos` 检查，这点做得细。

**不足**

1. Developer ID 路径只传了 `--options runtime`，没有任何 `--entitlements`；随包的 `orbit-helper` 是 PyInstaller `--onedir` 产物，这类产物在 Hardened Runtime 下通常需要 `com.apple.security.cs.allow-unsigned-executable-memory` 与 `com.apple.security.cs.disable-library-validation`，否则公证通过后启动会闪退 —— **待用真实 Developer ID 验证**，目前本机只走 ad-hoc。
2. 使用 `codesign --deep` 一次签整个包。Apple 不推荐用 `--deep` 做签名（嵌套代码应由内向外逐个签），在公证时更容易被拒。
3. 未沙盒化（App Sandbox 关闭，读取 `~/.claude` 等目录靠用户选择与完整磁盘访问），所以 `chooseFolder` 里保存的 security-scoped bookmark 其实用不上，反而每次选择都追加一份到 `UserDefaults`，重复选择同一目录会不断累积并重复 `startAccessingSecurityScopedResource`。

## 14. 汇总建议顺序

1. 立即（小改动、收益高）：修 ⌥⌘H 冲突与快捷键文档不一致；「登录时启动」要么实现要么隐藏；通知触发条件与测试通知。
2. 随后：菜单补全（页面菜单、导出、缩放）、Dock 菜单、状态栏角标取舍、窗口底色与 `NSApp.appearance` 同步、全站文本选择。
3. 中期：设置独立窗口；退出确认；Developer ID 路径的 entitlements 与逐层签名验证。

对应的可执行条目与证据见本次任务返回的 findings（未重复第一阶段已知问题）。

## 15. 官方资料索引

- macOS 概览：<https://developer.apple.com/macos/>
- HIG：[Designing for macOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos)、[Windows](https://developer.apple.com/design/human-interface-guidelines/windows)、[The menu bar](https://developer.apple.com/design/human-interface-guidelines/the-menu-bar)、[Menus](https://developer.apple.com/design/human-interface-guidelines/menus)、[Typography](https://developer.apple.com/design/human-interface-guidelines/typography)、[Onboarding](https://developer.apple.com/design/human-interface-guidelines/onboarding)、[Settings](https://developer.apple.com/design/human-interface-guidelines/settings)、[Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)、[Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode)
- AppKit：[`NSWindow.performDrag(with:)`](https://developer.apple.com/documentation/appkit/nswindow/performdrag(with:))、[`isMovableByWindowBackground`](https://developer.apple.com/documentation/appkit/nswindow/ismovablebywindowbackground)、[`setFrameAutosaveName(_:)`](https://developer.apple.com/documentation/appkit/nswindow/setframeautosavename(_:))、[`isRestorable`](https://developer.apple.com/documentation/appkit/nswindow/isrestorable)、[`titlebarAppearsTransparent`](https://developer.apple.com/documentation/appkit/nswindow/titlebarappearstransparent)、[`NSStatusItem`](https://developer.apple.com/documentation/appkit/nsstatusitem)、[`NSPanel`](https://developer.apple.com/documentation/appkit/nspanel)、[`NSApplication.helpMenu`](https://developer.apple.com/documentation/appkit/nsapplication/helpmenu)
- WebKit：[`WKWebsiteDataStore`](https://developer.apple.com/documentation/webkit/wkwebsitedatastore)、[`nonPersistent()`](https://developer.apple.com/documentation/webkit/wkwebsitedatastore/nonpersistent())、[`WKWebView.isInspectable`](https://developer.apple.com/documentation/webkit/wkwebview/isinspectable)、[`WKUserScript`](https://developer.apple.com/documentation/webkit/wkuserscript)
- 分发与调试：[Notarizing macOS software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)、[Hardened Runtime](https://developer.apple.com/documentation/security/hardened-runtime)、[Distributing your app](https://developer.apple.com/documentation/xcode/distributing-your-app-for-beta-testing-and-releases)、[Debugging（Xcode）](https://developer.apple.com/documentation/xcode/debugging)

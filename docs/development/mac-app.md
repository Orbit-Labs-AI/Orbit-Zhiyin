# Orbit Mac App

Orbit v0.0.2 是本地 macOS App：原生 AppKit/WKWebView 宿主 + 冻结的 Python gateway（`tandem-helper`）+ 单文件 Advance UI（Lite 是同一界面内的侧栏切换）。宿主外壳移植自 PR #41；后端统一使用 `tandem_backend.services` gateway，不再有单独的桌面服务。代码标识（`tandem_*`、`tandem-helper`、`Application Support/Tandem`）保持不变。

## 构建

构建机需要 Python 3.13 + uv、Node ≥24.7、Xcode Command Line Tools；用户机器不需要。

```sh
bash scripts/bootstrap.sh
uv run python apps/desktop/build.py              # 完整构建
uv run python apps/desktop/build.py --skip-helper  # 复用上次 PyInstaller 结果，只重打宿主/UI/图标
```

步骤：

1. `node prototypes/advance/build.mjs --out Resources/orbit.html` 生成单文件 UI。页面只用 macOS 系统字体（SF Pro、PingFang SC、SF Mono，见 [品牌](../design/brand.md#字体)），不内联网页字体；产物若含远程字体链接则构建失败。
2. PyInstaller 6.22.3（`uv run --with`，不新增锁文件）以 onedir 打包 `apps/desktop/server_entry.py` 为 `Resources/backend/tandem-helper`；`--collect-all` 工作区包（含 SQL/JSON/模板等包数据）与 jieba，`--copy-metadata` 读取发行元数据的包，并显式加入 uvicorn 与 worker 模块。
3. `swiftc -O -target arm64-apple-macos14.0` 编译 `Orbit.swift`（AppKit、WebKit、Security、UserNotifications）。
4. 图标 `Orbit.icns` 只用现有原稿：1024 px 直接取 `docs/design/logo/orbit-icon.png`，其他尺寸由 `render_svg.swift` 原样渲染 `orbit-icon.svg`；低于 128 px 按 `prototypes/advance/tools/brand-icon.mjs` 的规则换用 `orbit-mark-small.svg`（同一底板与变换）。菜单栏图标 `StatusIcon.png`/`@2x` 由 `render_svg.swift` 按原始宽高比原样渲染 `orbit-mark-small.svg`（16 pt 高），宿主作为模板图使用。不重绘、不调整线宽。
5. 扫描 `.app` 内全部 Mach-O 的最低系统版本（`LC_BUILD_VERSION` / `LC_VERSION_MIN_MACOSX`），任一高于 `MIN_MACOS`（14.0，同时决定 swiftc target 与 `LSMinimumSystemVersion`）即构建失败；helper 的下限来自第三方 wheel（当前 numpy/scipy 为 14.0），升级依赖时据此发现兼容性回退。
6. `codesign --force --deep` 签名并 `--verify --deep --strict` 校验。
7. 输出到 `.local/macos-build/`（已忽略）：`Orbit.app`、`Orbit-0.0.2-arm64.zip`（ditto）、`Orbit-0.0.2-arm64.dmg`（UDZO，含 `/Applications` 链接）。

## 运行组成

```text
Orbit.app (AppKit / WKWebView, 非持久 WebsiteDataStore)
  ├─ 启动 tandem-helper gateway --home <home> --port 0 --assets Resources/orbit.html
  │    env: TANDEM_API_TOKEN（每次启动 32 字节随机 hex）、TANDEM_PARENT_PID
  ├─ 读取 stdout 首行 {"port": N}，带 Bearer 轮询 /v1/status，就绪后各界面加载 http://127.0.0.1:N/app[?surface=…]
  │    主窗口 /app · 菜单栏 NSPopover /app?surface=panel · HUD /app?surface=hud · 小组件 /app?surface=widgets
  ├─ 每个 WKWebView 在 document-start 注入 window.__TANDEM_TOKEN__ / __TANDEM_ENDPOINT__ /
  │    __ORBIT_NATIVE__ = {v: 1, app: '0.0.2', platform: 'macos', features: [...]}（页面也应把旧的 true 视为原生）
  └─ 消息桥 window.webkit.messageHandlers.tandem（所有界面共用一个处理实现；仅主框架、同源）
gateway (FastAPI + uvicorn, 127.0.0.1 动态端口)
  ├─ GET / → /app；GET /app、/lite：单文件 UI，无需 token（仍校验 Host/Origin）
  └─ 其余 /v1/* 需要 Bearer；worker ingest / analysis 由同一可执行文件以 `worker <role>` 再启动
```

页面 CSP：`default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; font-src 'self' data:`。gateway 返回页面时也会去掉指向外部的 `<link>`；页面只用系统字体，离线显示与在线一致。

### 消息桥

页面通过 `webkit.messageHandlers.tandem.postMessage({type, id?, ...})` 调用（旧字段 `action` 仍兼容）。结果事件发回发起消息的那个界面：

| type | 参数 | 结果 |
|---|---|---|
| `chooseFolder` | `id, purpose, agent?, defaultPath?` | 目录选择面板（purpose/agent 作提示语，defaultPath 为初始目录）；保存 security-scoped bookmark；派发 `tandem:folder`，`detail: {id, path, cancelled}` |
| `save` | `id, filename, mime, text` 或 `base64` | 保存面板；派发 `tandem:saved`，`detail: {id, ok, path?, cancelled?, error?}` |
| `openExternal` | `url` | 仅 http/https，用默认浏览器打开 |
| `reveal` | `path` | 在 Finder 中显示 |
| `close` / `minimize` / `zoom` / `fullscreen` | — | 主窗口控制；在 panel 上 `close` 关闭弹出框，在 HUD/小组件上 `close` 隐藏该面板 |
| `notify` | `id?, title, body, route?` | 系统通知（UNUserNotificationCenter）；首次使用时请求授权，被拒绝则静默；点击通知激活主窗口（带 route 时同时下发） |
| `openMain` | `route?` | 关闭弹出框，激活主窗口；有 route 时向主窗口派发 `tandem:command {cmd: 'route', route}` |
| `resizeSurface` | `height` | 调整 panel 弹出框高度，或 HUD/小组件面板高度（保持顶边；限制 80–900 pt） |

宿主 → 页面事件：`tandem:folder`、`tandem:saved`、`tandem:endpoint {endpoint, token}`、`tandem:command {cmd, route?}`，其中 `cmd` 为 `settings`、`palette`、`about`、`route`、`toggleEdition`、`refresh`。

helper 异常退出时宿主重启一次：新 token 与端口重新注入每个界面，并派发 `tandem:endpoint`，`detail: {endpoint, token}`（`prototypes/shared/tandem-live.js` 监听它）；再次退出则弹窗提示，日志见 `<home>/desktop.log`。

### 原生界面

- **菜单栏**：NSStatusItem（模板图标）。左键打开 360×560 的 NSPopover（`surface=panel`，点击外部自动收起）；右键为快捷菜单（打开 Orbit、显示 HUD、桌面小组件、退出）。
- **HUD**：无边框、透明、非激活的浮动 NSPanel（`surface=hud`，初始 340×80，随页面上报的胶囊宽高收缩，透明区不挡其他窗口；屏幕右上角），所有空间与全屏下可见；窗口 › 显示 HUD（⌥⌘P）切换，默认显示，记住显隐与位置。
- **桌面小组件**：同类浮动面板（`surface=widgets`，宽 364 与页面一致，菜单打开时总是渲染），窗口 › 桌面小组件（⌥⌘D）切换，默认关闭。
- 浮动面板可接收键盘输入但不激活 Orbit；按住 ⌘ 拖动任意位置，或拖动顶部 12 pt，移动面板。
- 页面在 surface 模式下只渲染对应组件（`body.native.surface-<x>`，透明背景）；原生模式下 `body.native` 隐藏演示用的假桌面（菜单栏、壁纸、假红绿灯、假 Dock 与桌面小组件），主窗口铺满并为真实透明标题栏留出 `--titlebar-inset`（28px）。这部分由页面实现。

### 窗口与生命周期

- 透明标题栏、full-size content view，Web UI 自绘标题区域；最小 960×640，窗口位置与大小自动记忆。
- 菜单（中文）：Orbit（关于 Orbit → `about`、设置… ⌘, → `settings`、隐藏、退出）、编辑（撤销/重做/剪切/拷贝/粘贴/全选，输入框可用）、显示（命令面板 ⌘K → `palette`、切换 Lite / Advance ⌃⌘L → `toggleEdition`、刷新 ⌘R → `refresh`、重新载入页面 ⇧⌘R）、窗口（最小化、缩放、全屏、Orbit 主窗口 ⌘0、显示 HUD ⌥⌘P、桌面小组件 ⌥⌘D）。命令先激活主窗口，再以 `tandem:command` 派发给主窗口页面。
- 关闭主窗口只隐藏窗口，Orbit 继续在菜单栏运行；点 Dock 图标、菜单栏或 `openMain` 恢复，⌘Q 退出。
- 单实例：对 `<home>/orbit.lock` 加 `flock`；同一数据目录的第二次启动会激活已运行的 Orbit 并退出。
- 退出时向 helper 发 SIGTERM 并等待（最多 8 秒，超时 SIGKILL）；宿主崩溃时 helper 通过 `TANDEM_PARENT_PID` 自行退出。

## 数据目录

默认 `~/Library/Application Support/Tandem`；环境变量 `TANDEM_HOME` 可覆盖。演示与验收使用独立目录，例如：

```sh
open -n --env TANDEM_HOME=/absolute/private/demo .local/macos-build/Orbit.app
```

冒烟检查（无需辅助功能权限）可加 `ORBIT_DEBUG_SURFACES=panel,hud,widgets`，启动时直接打开这些界面且不记住显隐：

```sh
TANDEM_HOME=$(mktemp -d) ORBIT_DEBUG_SURFACES=panel,widgets .local/macos-build/Orbit.app/Contents/MacOS/Orbit
```

来源只在用户明确启用后导入；真实会话、数据库与日志不进入仓库。

## 验收

```sh
python3 scripts/check-macos-app.py [--app .local/macos-build/Orbit.app] [--keep]
```

脚本在临时目录启动随包 helper（同时重定向 HOME，发现逻辑看不到本机会话），检查握手、无 token 访问 `/app` 与 `/lite` 及页面 CSP、无 token 访问 API 被拒、带 token 的 `/v1/status`、由冻结 analysis worker 返回的分析接口（非 500/ImportError）以及 SIGTERM 正常退出。gateway 侧的页面路由测试见 `packages/backend/tests/services/test_pages.py`。

## 签名与分发

默认 ad-hoc 签名，未公证。从下载的 zip/dmg 首次打开时 Gatekeeper 会拦截：在 Finder 中右键 › 打开，或执行

```sh
xattr -dr com.apple.quarantine /Applications/Orbit.app
```

对外分发设置 `TANDEM_SIGN_IDENTITY`（Developer ID Application 身份）与可选 `TANDEM_NOTARY_PROFILE`（notarytool keychain profile），构建脚本会使用 Hardened Runtime、公证并 staple。当前是非 Sandbox 的独立分发 App，不面向 Mac App Store。

# Orbit Mac App

Orbit v0.0.1 是本地 macOS App：原生 AppKit/WKWebView 宿主 + 冻结的 Python gateway（`tandem-helper`）+ 单文件 Advance UI（Lite 是同一界面内的侧栏切换）。宿主外壳移植自 PR #41；后端统一使用 `tandem_backend.services` gateway，不再有单独的桌面服务。代码标识（`tandem_*`、`tandem-helper`、`Application Support/Tandem`）保持不变。

## 构建

构建机需要 Python 3.13 + uv、Node ≥24.7、Xcode Command Line Tools；用户机器不需要。

```sh
bash scripts/bootstrap.sh
uv run python apps/desktop/build.py              # 完整构建
uv run python apps/desktop/build.py --skip-helper  # 复用上次 PyInstaller 结果，只重打宿主/UI/图标
```

步骤：

1. `node prototypes/advance/build.mjs --out Resources/orbit.html` 生成单文件 UI。
2. PyInstaller 6.22.3（`uv run --with`，不新增锁文件）以 onedir 打包 `apps/desktop/server_entry.py` 为 `Resources/backend/tandem-helper`；`--collect-all` 工作区包（含 SQL/JSON/模板等包数据）与 jieba，`--copy-metadata` 读取发行元数据的包，并显式加入 uvicorn 与 worker 模块。
3. `swiftc -O -target arm64-apple-macos15.0` 编译 `Orbit.swift`。
4. 图标 `Orbit.icns` 只用现有原稿：1024 px 直接取 `docs/design/logo/orbit-icon.png`，其他尺寸由 `render_svg.swift` 原样渲染 `orbit-icon.svg`；低于 128 px 按 `prototypes/advance/tools/brand-icon.mjs` 的规则换用 `orbit-mark-small.svg`（同一底板与变换）。不重绘、不调整线宽。
5. `codesign --force --deep` 签名并 `--verify --deep --strict` 校验。
6. 输出到 `.local/macos-build/`（已忽略）：`Orbit.app`、`Orbit-0.0.1-arm64.zip`（ditto）、`Orbit-0.0.1-arm64.dmg`（UDZO，含 `/Applications` 链接）。

## 运行组成

```text
Orbit.app (AppKit / WKWebView, 非持久 WebsiteDataStore)
  ├─ 启动 tandem-helper gateway --home <home> --port 0 --assets Resources/orbit.html
  │    env: TANDEM_API_TOKEN（每次启动 32 字节随机 hex）、TANDEM_PARENT_PID
  ├─ 读取 stdout 首行 {"port": N}，带 Bearer 轮询 /v1/status，就绪后加载 http://127.0.0.1:N/app
  ├─ document-start 注入 window.__TANDEM_TOKEN__ / __TANDEM_ENDPOINT__ / __ORBIT_NATIVE__ = true
  └─ 消息桥 window.webkit.messageHandlers.tandem（仅主框架、同源）
gateway (FastAPI + uvicorn, 127.0.0.1 动态端口)
  ├─ GET / → /app；GET /app、/lite：单文件 UI，无需 token（仍校验 Host/Origin）
  └─ 其余 /v1/* 需要 Bearer；worker ingest / analysis 由同一可执行文件以 `worker <role>` 再启动
```

页面 CSP：`default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; font-src 'self' data:`。gateway 返回页面时去掉指向外部的 `<link>`（如 Google Fonts），App 离线可用，字体回退到系统字体。

### 消息桥

页面通过 `webkit.messageHandlers.tandem.postMessage({action, ...})` 调用：

| action | 参数 | 结果 |
|---|---|---|
| `chooseFolder` | `id` | 目录选择面板；保存 security-scoped bookmark；派发 `tandem:folder`，`detail: {id, path}`（取消时 path 为 null） |
| `save` | `id, filename, text` 或 `base64, mime` | 保存面板；派发 `tandem:saved`，`detail: {id, ok, path?, error?}` |
| `openExternal` | `url` | 仅 http/https，用默认浏览器打开 |
| `reveal` | `path` | 在 Finder 中显示 |
| `close` / `minimize` / `zoom` / `fullscreen` | — | 窗口控制 |

helper 异常退出时宿主重启一次：新 token 与端口重新注入，并派发 `tandem:endpoint`，`detail: {endpoint, token}`（`prototypes/shared/tandem-live.js` 监听它）；再次退出则弹窗提示，日志见 `<home>/desktop.log`。

### 窗口与生命周期

- 透明标题栏、full-size content view，Web UI 自绘标题区域；最小 960×640，窗口位置与大小自动记忆。
- 菜单：Orbit（关于 Orbit 0.0.1、隐藏、退出）、编辑（撤销/重做/剪切/复制/粘贴/全选，输入框可用）、窗口（最小化、缩放、全屏、重新载入）。
- 单实例：对 `<home>/orbit.lock` 加 `flock`；同一数据目录的第二次启动会激活已运行的 Orbit 并退出。
- 退出时向 helper 发 SIGTERM 并等待（最多 8 秒，超时 SIGKILL）；宿主崩溃时 helper 通过 `TANDEM_PARENT_PID` 自行退出。

## 数据目录

默认 `~/Library/Application Support/Tandem`；环境变量 `TANDEM_HOME` 可覆盖。演示与验收使用独立目录，例如：

```sh
open -n --env TANDEM_HOME=/absolute/private/demo .local/macos-build/Orbit.app
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

# macOS App 开发与分发

原生宿主位于 `apps/desktop`：AppKit/WKWebView 提供窗口、系统菜单、通知、文件面板与 helper 生命周期；冻结的 Python gateway 执行业务；统一 Web UI 提供 Lite / Advance。构建目标是 Apple Silicon、macOS 14+。

## 构建

构建机需要[开发环境](setup.md)和 Xcode Command Line Tools。用户机器不需要 Python 或 Node。

```sh
bash scripts/bootstrap.sh
python3 scripts/heavy.py uv run python apps/desktop/build.py
```

产物写入忽略的 `.local/macos-build/`：`Orbit.app`、带版本和 arm64 标识的 ZIP/DMG。版本、最低系统与输出命名以 [build.py](../../apps/desktop/build.py)为准，不从文档中的旧版本号复制。

构建步骤为统一 UI 单文件、PyInstaller onedir helper、Swift 宿主、原样复制品牌图标、扫描 Mach-O 最低系统要求、签名验证和打包。`--skip-helper` 复用上次 helper，只有未改变 Python/依赖/资源时才适用；不能以它验收新后端。

## 运行与鉴权

宿主启动 `orbit-helper gateway --home <目录> --port 0 --assets <页面>`，通过 stdout 握手取得端口，再带 `ORBIT_API_TOKEN` 检查状态。token 每次启动生成，经环境与 WebView 注入传递，不作为日志或共享 URL 内容。

各界面加载同源 `/app`，surface 区分主窗口、panel、hud、widgets。API 需要 Bearer，页面仍校验 Host/Origin。WebView 使用非持久数据存储；页面由 gateway 提供 CSP 并避免外部字体依赖。

helper 再以 `worker ingest` 或 `worker analysis` 启动受监督任务。宿主退出时停止 helper，父进程消失时 helper 自行退出；异常重启需要向所有 WebView 更新端口/token 并发出 `orbit:endpoint`。

## 原生桥

页面通过 `window.webkit.messageHandlers.orbit` 发送请求，宿主只接受可信主框架和同源消息。完整字段以 [Orbit.swift](../../apps/desktop/Orbit.swift) 和前端 `90-live-core.js` 为准。

| 能力 | 消息族 | 结果或限制 |
| --- | --- | --- |
| 目录与保存 | `chooseFolder`、`save` | 系统面板，保留取消/错误与请求 ID |
| 打开与定位 | `openExternal`、`reveal` | 外链按允许协议，定位文件由宿主执行 |
| 窗口 | `close`、`minimize`、`zoom`、`fullscreen`、`openMain` | surface 与主窗口语义不同 |
| 通知 | `notify`、`notificationStatus`、`openNotificationSettings` | 授权与实际投递分别返回 |
| 偏好 | `appearance`、`loginItem`、`statusBadge` | 系统回读状态为准 |
| UI 同步 | `menuState`、`resizeSurface` | 菜单标题和面板尺寸随页面更新 |

新增回包类型要在前端 REPLY 映射登记。宿主下发的 `orbit:command` 承载菜单命令，不能把只发出消息当成操作已经成功。

## 生命周期与数据

关闭主窗口只隐藏，`⌘Q` 完全退出。菜单栏、浮动 HUD 和小组件共用 gateway；同一 home 的单实例锁避免重复服务。窗口/面板的显隐与位置由相应偏好恢复，系统通知与登录项受用户授权控制。

默认 home 为 `~/Library/Application Support/Orbit`，`ORBIT_HOME` 可覆盖。测试一律用独立目录；旧品牌路径和文件由兼容层迁移，不能用手动改名替代数据库转换。

## 验证

```sh
python3 scripts/heavy.py python3 scripts/check-macos-app.py
```

helper 冒烟在临时 home 中验证冻结程序启动、页面/CSP、鉴权、分析 worker 与停止；它不覆盖通知权限、所有窗口行为或完整用户体验。原生菜单相关回归、Web UI 行为与必要人工检查按本次改动选择。

## 签名与发布

默认 ad-hoc 签名、未公证。签名由内向外处理 helper 内 Mach-O、helper 和 App，验证可使用 deep/strict；不要把 `codesign --deep` 作为当前的签名实现描述。

设置 `ORBIT_SIGN_IDENTITY` 使用 Developer ID，按需要设置 `ORBIT_NOTARY_PROFILE` 公证并 staple；`--runtime` 可在本地启用 Hardened Runtime 验证。密钥与配置不进仓库。公开上传前核对产物、目标系统、校验和、Release 说明和实际签名状态；创建安装包不等于发布已完成。

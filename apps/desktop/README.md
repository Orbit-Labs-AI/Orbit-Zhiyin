# Orbit 桌面宿主

原生 macOS 宿主由 `Orbit.swift` 提供 AppKit/WKWebView 窗口、菜单栏、HUD、小组件、通知和系统面板，并管理随包 `orbit-helper`。业务数据与分析运行在 Python gateway，UI 使用 `prototypes/advance` 的统一 Lite / Advance 界面。

## 构建与运行

```sh
bash scripts/bootstrap.sh
python3 scripts/heavy.py uv run python apps/desktop/build.py
open .local/macos-build/Orbit.app
```

目标是 Apple Silicon / macOS 14+。版本号、最低系统与产物位置以 [build.py](build.py)为准；`server_entry.py` 是冻结 helper 入口。构建不会自动发布 Release。

## 宿主职责

- 启动 loopback gateway，完成端口/token 握手并给 WebView 注入能力。
- 提供可信的文件、窗口、通知和系统偏好桥接。
- 关闭主窗口后保留菜单栏运行，`⌘Q` 退出并停止 helper。
- 使用同一 home 的单实例锁，并处理 helper 异常与重启。

默认数据目录为 `~/Library/Application Support/Orbit`，`ORBIT_HOME` 可指定独立目录。测试不能连接用户正在使用的真实 home。

图标直接复制 `docs/design/logo/kit` 的既有产物，界面使用系统字体。默认本地构建为 ad-hoc 签名；Developer ID、公证、原生消息协议与验收见[Mac App 手册](../../docs/development/mac-app.md)。安装发布版见[用户安装指南](../../docs/getting-started/installation.md)。

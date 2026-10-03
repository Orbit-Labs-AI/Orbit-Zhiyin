# Orbit Mac 宿主

`Orbit.swift` 是原生宿主：主窗口、菜单栏弹出框（`/app?surface=panel`）、浮动 HUD 与桌面小组件、菜单命令、系统通知、系统面板与随包 `tandem-helper` 的生命周期；全部数据逻辑在 helper（`tandem_backend.services` gateway）中。`server_entry.py` 是冻结 helper 的入口，`build.py` 打包，`render_svg.swift` 只用于把现有 logo SVG 原样渲染成图标与菜单栏图标尺寸；UI 只用 macOS 系统字体，`orbit.html` 不含网页字体。

```sh
bash scripts/bootstrap.sh                      # 首次：uv sync + pnpm install（含字体包）
uv run python apps/desktop/build.py            # -> .local/macos-build/Orbit.app、.zip、.dmg
python3 scripts/check-macos-app.py             # helper 冒烟检查（临时数据目录）
open .local/macos-build/Orbit.app
```

- 关闭主窗口只隐藏，Orbit 留在菜单栏，⌘Q 退出；窗口 › 显示 HUD（⌥⌘P）、桌面小组件（⌥⌘D）；菜单快捷键不得重复，由 `tests/regression/test_desktop_menu.py` 检查。
- 版本 0.0.2，bundle id `ai.actionmesh.orbit`，Apple Silicon，macOS 14+。
- 数据目录：`~/Library/Application Support/Tandem`；设置环境变量 `TANDEM_HOME` 可改用其他目录（演示、验收一律用独立目录）。
- 本地构建为 ad-hoc 签名，未公证：首次打开需在 Finder 中右键 › 打开，或执行 `xattr -dr com.apple.quarantine /Applications/Orbit.app`。配置 `TANDEM_SIGN_IDENTITY`（Developer ID）与 `TANDEM_NOTARY_PROFILE` 可签名并公证。签名由内向外逐个进行（不用 `--deep`）：helper 内的 Mach-O → `tandem-helper`（`helper.entitlements`：allow-unsigned-executable-memory、disable-library-validation）→ App（`Orbit.entitlements`）；Developer ID 带 Hardened Runtime。`build.py --runtime` 在 ad-hoc 下也启用 Hardened Runtime，用于本地确认 helper 能启动。

详见 [Mac App 开发说明](../../docs/development/mac-app.md)。

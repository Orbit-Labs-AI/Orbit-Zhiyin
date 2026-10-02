# Orbit Mac 宿主

`Orbit.swift` 是原生宿主：主窗口、菜单栏弹出框（`/app?surface=panel`）、浮动 HUD 与桌面小组件、菜单命令、系统通知、系统面板与随包 `tandem-helper` 的生命周期；全部数据逻辑在 helper（`tandem_backend.services` gateway）中。`server_entry.py` 是冻结 helper 的入口，`build.py` 打包，`render_svg.swift` 只用于把现有 logo SVG 原样渲染成图标与菜单栏图标尺寸；`build.py` 还会把网页字体（`@fontsource-variable`，latin/latin-ext）内联进 `orbit.html`，离线显示一致。

```sh
bash scripts/bootstrap.sh                      # 首次：uv sync + pnpm install（含字体包）
uv run python apps/desktop/build.py            # -> .local/macos-build/Orbit.app、.zip、.dmg
python3 scripts/check-macos-app.py             # helper 冒烟检查（临时数据目录）
open .local/macos-build/Orbit.app
```

- 关闭主窗口只隐藏，Orbit 留在菜单栏，⌘Q 退出；窗口 › 显示 HUD（⌥⌘H）、桌面小组件（⌥⌘W）。
- 版本 0.0.1，bundle id `ai.actionmesh.orbit`，Apple Silicon，macOS 15+。
- 数据目录：`~/Library/Application Support/Tandem`；设置环境变量 `TANDEM_HOME` 可改用其他目录（演示、验收一律用独立目录）。
- 本地构建为 ad-hoc 签名，未公证：首次打开需在 Finder 中右键 › 打开，或执行 `xattr -dr com.apple.quarantine /Applications/Orbit.app`。配置 `TANDEM_SIGN_IDENTITY`（Developer ID）与 `TANDEM_NOTARY_PROFILE` 可签名并公证。

详见 [Mac App 开发说明](../../docs/development/mac-app.md)。

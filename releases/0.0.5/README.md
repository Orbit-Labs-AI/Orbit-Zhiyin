# Orbit 0.0.5

Orbit·知音的维护性升级：合并导入时区修复（#112）与新版合并版式 / 中英双语界面（#113），并首次提供 **Windows 预览版**安装包。

本次 macOS 安装包为 2026-10-22 从 `v0.0.5` 标签源码在 Mac 上干净重建（0.0.5 / build 5，ad-hoc 签名、未公证），已包含新界面与时区修复；构建使用不含个人用户名的干净路径，DMG 与 ZIP 均已提供。

## 系统要求与下载

| 项目 | 要求或说明 |
| --- | --- |
| 系统（macOS） | macOS 14 Sonoma 及以上 |
| 处理器（macOS） | Apple Silicon（arm64）；本次不提供 Intel Mac 安装包 |
| App 版本（macOS） | 0.0.5，内部构建号 5（本地构建；ad-hoc 签名、未公证） |
| 运行环境（macOS） | 安装包自带后端运行时，无需另外安装 Python 或 Node |
| 签名（macOS） | ad-hoc 签名，未经过 Apple Developer ID 签名及公证 |
| 系统（Windows 预览） | Windows 10 / 11 x64；需要 Microsoft Edge 与 Node.js 26+（或使用包内说明的工作区 Node） |
| 其他平台 | 本次不提供 Linux 桌面安装包 |

- **[下载 macOS DMG（推荐）](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/download/v0.0.5/Orbit-0.0.5-arm64.dmg)**：约 80 MB，打开后将 Orbit 拖入「应用程序」。
- **[下载 macOS ZIP](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/download/v0.0.5/Orbit-0.0.5-arm64.zip)**：约 68 MB，解压后将 `Orbit.app` 移入「应用程序」。
- **[下载 Windows 预览版 ZIP](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/download/v0.0.5/Orbit-0.0.5-windows-x64.zip)**：约 2.1 MB，解压后双击 `Orbit.exe`。首次启动为空白，随后扫描运行者本机日志。
- **[SHA256SUMS](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/download/v0.0.5/SHA256SUMS)**：用于确认安装包完整性。

macOS 用户下载 DMG 或 ZIP 之一即可（推荐 DMG）；Windows 预览版为独立构建，不是 macOS App 的等价移植。GitHub 自动生成的 **Source code (zip / tar.gz)** 是 `v0.0.5` 标签对应的源码，不是安装包。

## 安装与首次打开（macOS）

1. 下载 DMG 或 ZIP：DMG 打开后把 `Orbit.app` 拖入 `/Applications`；ZIP 解压后同样放入。不要长期直接从 DMG / 解压目录运行。
2. 从「应用程序」打开 Orbit。首次运行时按引导明确选择允许读取的 Agent 来源。
3. 等待首次索引与分析完成；耗时取决于日志数量、文件体积和机器负载。已有结果时可先查看上一份结果。

### macOS 拦截时的处理命令

由于当前安装包未经过 Apple 公证，首次启动可能被 Gatekeeper 拦截；这并不意味着已经完成 Apple 的安全审核。安装包为本地构建并做了 ad-hoc 签名，若仍被拦截，请先确认下载来自本 Release 且 SHA-256 与下方一致。

可尝试在 Finder 中右键 Orbit →「打开」，或按系统提示前往「系统设置 → 隐私与安全性」选择「仍要打开」。如果仍被隔离属性拦截，确认信任此安装包后，在「终端」执行：

```bash
xattr -dr com.apple.quarantine /Applications/Orbit.app
open /Applications/Orbit.app
```

上述命令只针对指定的 Orbit.app。不要将路径替换成整个「应用程序」目录，也不要全局关闭 Gatekeeper。若提示文件不存在，请先确认 App 已移入 `/Applications`；若遇到权限错误，不要盲目添加 `sudo`，先检查安装位置及文件权限。

### 校验下载文件

```bash
cd "$HOME/Downloads"
shasum -a 256 Orbit-0.0.5-arm64.dmg Orbit-0.0.5-arm64.zip
```

预期值：

```text
1c47a27cd2671474369c89dc6c747baa94b13e61e6b231900984a3189ac6e662  Orbit-0.0.5-arm64.dmg
8a67f840abc239b741ebd0456f8ce653011fd8f3cd6b35b2ab7a407978ba0d18  Orbit-0.0.5-arm64.zip
a682cd22ff5b8e8a61bc4ea1d508c52b7e3047d645d8135467877daf2c7a94df  Orbit-0.0.5-windows-x64.zip
```

如果同时下载了安装包与 `SHA256SUMS`，把文件放在同一目录后运行 `shasum -a 256 -c SHA256SUMS`。哈希不一致时不要继续打开，请重新下载。

## 安装与首次打开（Windows 预览版）

1. 解压 `Orbit-0.0.5-windows-x64.zip` 到任意目录。
2. 双击 `Orbit.exe`（或 `启动 Orbit.vbs`；调试可用 `Orbit.bat`）。
3. **首次启动是空白数据**；随后自动只读扫描**运行者这台电脑**上的 Claude Code / Codex / DeepSeek Harness 会话日志（约 3 秒），完成后页面自动刷新显示其自己的会话 / 项目 / 画像 / 概览。
4. 关闭窗口即整体退出；`StopOrbit.exe` / `停止 Orbit.bat` 可停止后台。新开会话后使用 `Ctrl+K → 重新索引`。

Windows 预览版需要 Node.js 26+。发布包内不含任何会话数据、真实标题或真实截图；每台电脑首次启动都会扫描自己的日志。

## 从旧版升级（macOS）

1. 使用 Orbit 菜单中的退出或 `⌘Q` 完全退出旧版本；仅关闭主窗口不会退出菜单栏进程。
2. 如需备份，在退出后复制整个数据目录，不要只复制正在使用的 SQLite 主文件。
3. 使用 0.0.5 的 `Orbit.app` 替换 `/Applications/Orbit.app`，然后重新打开。

默认数据目录是 `~/Library/Application Support/Orbit`，可用 `open "$HOME/Library/Application Support/Orbit"` 在 Finder 中打开。替换或移除 `Orbit.app` 通常不会删除 Application Support 中的数据；来源 Agent 的原始记录也不在 App 安装目录内。

## 0.0.5 本版更新

### 数据层（#112）

- `derive()` 写 `session` 前按最终值归一化 `timezone` / `timezone_source`，导入发布不再被 SQLite CHECK 拒绝；`analysis_input` 的历史重建共用同一规则。
- `REDUCER_VERSION` 1.9.2、`READER_VERSION` 1.3；新增 15 项回归测试。
- 修复后，带时区但来源缺失/后到事件覆盖的会话会稳定落为 `(zone, 'reported')`，单条脏数据不会拖垮整条来源的发布。

### 界面（#113）

- Lite / Advance 合并为一套侧栏，新增渲染后翻译层：默认英文，可在「显示 → 语言」或 设置 → 通用 → 语言 切换中文。
- 修复会话轨迹列表在窗格模式下不滚动、选中行不滚入视野。
- 修复默认英文时 `<html lang>` 仍为 `zh-CN`。

### Windows 预览版（本版本新增）

- 独立构建：Node 网关 + Microsoft Edge `--app` 窗口 + 原生桥，零第三方依赖，不安装 Electron / Tauri。
- 与 macOS App 使用同一套新版合并版式 / 中英双语界面，并完成 Windows 适配：Segoe UI / 微软雅黑、Cascadia Mono；⌘→Ctrl、⌥→Alt；Finder→文件资源管理器；`~/…`→`%USERPROFILE%\…`；真实窗口控制与保存 / 选择文件夹对话框。
- 首次启动空白，随后扫描运行者本机日志；发布包不含数据。建议 / 资源库 / 工具明细仍为示例。

## 使用提示与数据边界

- macOS 在侧栏切换 Lite / Advance；关闭主窗口后 App 可继续在菜单栏运行，完全退出使用 `⌘Q`。
- 只有明确启用的来源才会被导入。首次导入或大范围分析可能需要等待，文件数、记录数与会话数是不同的进度单位。
- 基础导入和确定性分析在本机运行，不要求远端模型。启用 AI 后，本机 Agent 或所选引擎可能调用其配置的远端模型；资源目录同步、安装和可选模型下载也可能联网。
- Windows 预览版默认只读统计，不读消息正文、不上传；建议、资源库、工具明细为示例数据。
- 数据层的时区修复使用 stdlib `zoneinfo`。若后续把 Python 数据层搬到 Windows，需要把 `tzdata` 加入依赖并打进产物，否则 IANA 时区会被静默降级；不要通过放宽 CHECK 或跳过事件“修复”数据问题。

## 已知限制与排障

- macOS 安装包为本地构建，内部版本号 `0.0.5`（build 5），ad-hoc 签名、未公证；与官方 0.0.4 安装包 bundle id 相同，安装会覆盖同名 App。
- Windows 预览版是独立界面构建，不是 macOS App 的等价移植：没有 Python 分析 / 推荐 / 安装后端；需要 Node 26+，不是单文件绿色版。
- 大量会话、30 天或全部范围的首次分析仍可能较慢；不要通过反复重启强行打断数据库操作。
- 如无法启动，先核对系统版本、芯片架构、安装位置、哈希及上面的首次打开步骤。反馈时注明是系统拦截、进程退出还是窗口未显示。

请在 [Orbit Issues](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/issues) 提供 App 版本、系统版本、芯片型号、复现步骤与脱敏截图。不要公开上传真实会话数据库、访问令牌、私人路径或 `.env`。

## 验证记录

本次 macOS 构建从 `v0.0.5` 标签源码在 Mac 上干净重建（内容等同 `release/v0.0.5` 分支合并 #112 / #113 的原始提交）：

- 数据层：`packages/data/tests` **717 passed**（基线 702 + 新增 15）；ruff check / format 通过。
- 界面：`node prototypes/advance/build.mjs --check` 通过；界面测试 789 passed / 4 既有 flaky（基线可复现）；生成物与参考 `Orbit-Prototype-2026-10-21.html` 最终版一致（sha256 `6299ef60…47df5`）。
- Windows 预览版：`node --test host/test/*.test.mjs` **54/54**；`tools/smoke.mjs` **8/8**；空白首启截图 0 JS 异常；删除本机缓存后首次启动约 3 秒完成扫描并自动刷新。
- macOS：从 `v0.0.5` 标签源码在 Mac 上干净重建（构建路径不含个人用户名）；`codesign --verify --deep --strict` 通过；`scripts/check-macos-app.py` 冻结冒烟全部通过（helper 握手、`/app`+`/lite`、无 token 401、冻结导入与分析、SIGTERM 优雅退出）；DMG `hdiutil verify` 与 ZIP 完整性校验通过；包内无会话数据、无真实标题。
- 安装包 SHA-256 见 `SHA256SUMS`。

## 本版本许可与附件

Orbit 原创代码与文档采用 [Apache License 2.0](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/blob/v0.0.5/LICENSE)；第三方组件遵循各自许可证。

- [LICENSE-APACHE-2.0.txt](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/download/v0.0.5/LICENSE-APACHE-2.0.txt)：Apache-2.0 许可全文。
- [THIRD-PARTY-NOTICES.md](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/download/v0.0.5/THIRD-PARTY-NOTICES.md)：第三方许可说明。
- [BUNDLED-LICENSES.zip](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/download/v0.0.5/BUNDLED-LICENSES.zip)：安装包内已有许可文件副本。

## 源码与关联 PR

构建来源为本标签 `v0.0.5` 所指的提交。主要关联：#112（时区归一化）、#113（新版合并版式 / 中英双语界面）、#114（本发布分支）。Windows 预览版是独立构建，源码与构建说明随 ZIP 内的 `README.md`、`docs/VERIFICATION.md` 提供。

# Orbit 0.0.5

> 维护性升级：合并导入时区修复（#112）与新版合并版式 / 中英双语界面（#113），并首次提供 **Windows 预览版**安装包。
> 构建来源：本版本标签 `v0.0.5` 对应的提交（即 `release/v0.0.5` 分支 HEAD）。
> 发布日期：2026-10-22。

## 下载

| 平台 | 文件 | 说明 |
| --- | --- | --- |
| macOS（Apple Silicon） | `Orbit-0.0.5-arm64.zip` | 解压后把 `Orbit.app` 拖入「应用程序」；已清理构建机路径并 ad-hoc 重签（DMG 暂时下架，待 Mac 侧重建） |
| Windows（x64，预览） | `Orbit-0.0.5-windows-x64.zip` | 独立构建的 Windows 预览版：同一套新界面；首次启动空白，随后扫描**运行者本机**日志显示其自己的会话统计；解压后双击 `Orbit.exe` |

SHA-256 校验值见 [SHA256SUMS](SHA256SUMS)。Mac 安装包为 2026-10-22 本地构建（内部构建号仍为 `0.0.4 / 4`，
不冒充官方 0.0.4 发布版），内容已包含本次新界面与时区修复；ZIP 已移除构建机的 `direct_url.json` 路径并重新 ad-hoc 签名。
DMG 因内含同一构建路径已暂时下架，待 Mac 侧用干净路径重建后补发。Windows 预览版为独立构建（版本标记 `0.1.0-preview`），与 macOS App 不是同一运行时。

## 本次改动

### 数据层（#112）

- `derive()` 写 `session` 前用 `normalize_timezone()` 对 `timezone` / `timezone_source` 的**最终值**做与事件顺序无关的归一化；
  空 / 非法 IANA → `(NULL, 'unknown')`，有效时区保留 `reported` / `local_inferred`，来源缺失记为 `reported`。
- `analysis_input.py` 的 `until_ts` 历史重建共用同一规则；`REDUCER_VERSION` 1.9.2、`READER_VERSION` 1.3。
- 修复后导入发布不再因 `CHECK constraint failed ... timezone_source` 整条回滚，界面不再误报「本机服务没有响应」。
- 新增 15 项回归测试；`packages/data/tests` 717 passed。

### 界面（#113）

- Lite / Advance 合并为一套侧栏，新增渲染后翻译层（默认英文，可在「显示 → 语言」/ 设置 → 通用 → 语言切换中文）。
- 修复会话轨迹列表在窗格模式下不滚动、选中行不滚入视野；修复默认英文时 `<html lang>` 仍为 `zh-CN`。

### Windows 预览版（本版本新增）

- 独立构建：Node 网关 + Microsoft Edge `--app` 窗口 + 原生桥，零第三方依赖、不装 Electron/Tauri。
- 界面与 macOS 版使用同一套新版合并版式 / 中英双语界面，并做 Windows 适配：Segoe UI / 微软雅黑、⌘→Ctrl、
  Finder→文件资源管理器、`~/…`→`%USERPROFILE%\…`、真实窗口最小化 / 最大化 / 关闭、真实保存 / 选择文件夹对话框。
- **首次启动空白 → 扫描运行者自己的会话**：应用启动时页面是空白；后台只读解析**运行者这台电脑**上的
  Claude Code / Codex / DeepSeek Harness 会话日志（只统计时间、轮次、工具调用、错误、token、标题；**不读正文、不上传**），
  完成后通过 SSE 通知页面自动刷新显示会话 / 项目 / 画像 / 概览。**发布包内不含任何会话数据、真实标题或真实截图**；
  每台电脑首次启动都会扫描自己的日志。优化建议 / 资源库 / 工具明细仍为示例。
- 详细说明见 [Windows 预览版文档](../../docs/getting-started/windows-preview.md)。

## Windows 适配注意（给后续 Python / Windows 版本）

- 本次 macOS 数据修复使用 stdlib `zoneinfo`。Windows 的 Python 默认没有 IANA 时区库；若后续把 Python 数据层搬到 Windows，
  必须把 PyPI `tzdata` 加入依赖并 collect 到打包产物，否则所有时区会被静默降级为 `unknown`。
- Windows 预览版是独立 Node 构建，不含 Python 数据层，因此不受该问题影响；也不要通过放宽 CHECK 或跳过事件来“修复”数据问题。

## 安装与首次打开（macOS）

1. 下载 ZIP，解压后把 `Orbit.app` 拖入「应用程序」（DMG 待 Mac 侧重建后补发）。
2. 首次打开若提示「Apple 无法验证…」：Finder 中右键 Orbit → 打开，或到「系统设置 → 隐私与安全性」点「仍要打开」。
3. 若仍被拦截：确认来源可信后执行 `xattr -dr com.apple.quarantine /Applications/Orbit.app`。
4. 首次启动按引导选择允许读取的 Agent 来源（Claude Code / Codex 等）；不选择就不会读取。

## 安装与首次打开（Windows 预览版）

1. 解压 `Orbit-0.0.5-windows-x64.zip` 到任意目录。
2. 双击 `Orbit.exe`（或 `启动 Orbit.vbs`）。首次启动会解析本机会话日志（约 3 秒）。
3. 关闭窗口即整体退出；`StopOrbit.exe` / `停止 Orbit.bat` 可停止后台。
4. 需要 Node.js 26+：默认使用 `D:\Codex\Orbit\.tools` 下工作区自带的 Node；拷到别的电脑请安装 Node.js 26+。
   新开会话后用 `Ctrl+K → 重新索引` 刷新。

## 已知限制

- macOS 安装包为本地构建，内部版本号仍显示 `0.0.4`（build 4），ad-hoc 签名、未公证；与官方 0.0.4 安装包 bundle id 相同，安装会覆盖同名 App。
- macOS DMG 暂时下架：本地 DMG 内含构建机路径；ZIP 已清理并重签，待 Mac 侧重建 DMG 后补发。
- Windows 预览版是独立界面构建，不是 macOS App 的等价移植：没有 Python 分析 / 推荐 / 安装后端，建议 / 资源库 / 工具明细为示例数据；发布包不含任何会话数据。
- Windows 预览版需要 Node 26+（或工作区自带 Node）；不是单文件绿色版。
- 数据层修复不改变 DDL / 事件契约；已导入库在下次导入时重新归并，不需要删数据或迁移。

## 验证摘要

- `packages/data/tests` 717 passed（基线 702 + 新增 15）；ruff check / format 通过。
- UI：`node prototypes/advance/build.mjs --check` 通过；界面测试 789 passed / 4 既有 flaky（基线可复现）。
- Windows 预览版：`node --test host/test/*.test.mjs` 54/54；`tools/smoke.mjs` 8/8；空白首启 → 扫描运行者本机会话 → 自动刷新（发布包不含数据）；
  会话列表窗格滚动与 `html lang` 跟随语言两项界面修复已实测。
- 安装包 SHA-256 见 `SHA256SUMS`。

## 许可

Orbit 原创代码与文档采用 [Apache License 2.0](../../LICENSE)；第三方组件遵循各自许可证，随包声明见
[THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES.md) 与 [BUNDLED-LICENSES.zip](BUNDLED-LICENSES.zip)。

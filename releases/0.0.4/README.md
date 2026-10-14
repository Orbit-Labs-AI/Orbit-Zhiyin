# Orbit 0.0.4

Orbit·知音的 macOS 桌面版本，Lite / Advance 共用一个 App，可在侧栏顶部切换。本次将现有 0.0.4 安装包原样发布到新的公开下载仓库，安装包内容、签名与 SHA-256 均保持不变。

## 系统要求与下载

| 项目 | 要求或说明 |
| --- | --- |
| 系统 | macOS 14 Sonoma 及以上 |
| 处理器 | Apple Silicon（arm64）；本次不提供 Intel Mac 安装包 |
| App 版本 | 0.0.4，内部构建号 4 |
| 运行环境 | 安装包自带后端运行时，无需另外安装 Python、Node 或开发工具 |
| 签名 | ad-hoc 签名，未经过 Apple Developer ID 签名及公证 |
| 其他平台 | 本次不提供 Windows / Linux 桌面安装包 |

- **[下载 DMG（推荐）](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/download/v0.0.4/Orbit-0.0.4-arm64.dmg)**：约 82.6 MB，打开后将 Orbit 拖入「应用程序」。
- **[下载 ZIP](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/download/v0.0.4/Orbit-0.0.4-arm64.zip)**：约 72.0 MB，解压后将 `Orbit.app` 移入「应用程序」。
- **[SHA256SUMS](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases/download/v0.0.4/SHA256SUMS)**：用于确认安装包完整性。

DMG 与 ZIP 二选一即可。GitHub 自动生成的 **Source code (zip / tar.gz)** 只是本发布仓库的文档归档，不是 App 安装包。

## 安装与首次打开

1. 下载 DMG 或 ZIP，并按下方命令核对校验值。
2. 将 `Orbit.app` 放入 `/Applications`，不要长期直接从 DMG 中运行。
3. 从「应用程序」打开 Orbit。首次运行时按引导明确选择允许读取的 Agent 来源。
4. 等待首次索引与分析完成；耗时取决于日志数量、文件体积和机器负载。已有结果时可先查看上一份结果。

### macOS 拦截时的处理命令

本节补充自 0.0.2 的安装指南。由于当前安装包未经过 Apple 公证，首次启动可能被 Gatekeeper 拦截；这并不意味着已经完成 Apple 的安全审核。

先确认下载来自本 Release，且 SHA-256 与下方一致。可尝试在 Finder 中右键 Orbit →「打开」，或按系统提示前往「系统设置 → 隐私与安全性」选择「仍要打开」。不同 macOS 版本显示的入口可能不同。

如果仍被隔离属性拦截，确认信任此安装包后，在「终端」执行以下命令，仅移除 **Orbit.app** 的下载隔离属性，再启动 App：

```bash
xattr -dr com.apple.quarantine /Applications/Orbit.app
open /Applications/Orbit.app
```

上述命令只针对指定的 Orbit.app。不要将路径替换成整个「应用程序」目录，也不要全局关闭 Gatekeeper。若提示文件不存在，请先确认 App 已移入 `/Applications`；若遇到权限错误，不要盲目添加 `sudo`，先检查安装位置及文件权限。

### 校验下载文件

假设文件下载到「下载」目录，只下载 DMG 时运行：

```bash
cd "$HOME/Downloads"
shasum -a 256 Orbit-0.0.4-arm64.dmg
```

只下载 ZIP 时运行：

```bash
cd "$HOME/Downloads"
shasum -a 256 Orbit-0.0.4-arm64.zip
```

预期值如下：

```text
e66489b12dcf61415c95a5568f39a10542e90b3aa290b6715b43b69fcf441f96  Orbit-0.0.4-arm64.dmg
c786924e627ff10ab245b982a971d41086bba1f45f615ef65262320e652650c6  Orbit-0.0.4-arm64.zip
```

如果同时下载了两个安装包和 `SHA256SUMS`，把三个文件放在同一目录，然后运行：

```bash
cd "$HOME/Downloads"
shasum -a 256 -c SHA256SUMS
```

应看到两个文件均显示 `OK`。只下载其中一个安装包时，批量检查会报告另一个文件缺失，请改用上面的单文件命令。哈希不一致时不要继续打开，请重新下载。

## 从旧版升级

1. 使用 Orbit 菜单中的退出或 `⌘Q` 完全退出旧版本；仅关闭主窗口不会退出菜单栏进程。
2. 如需备份，在退出后复制整个数据目录，不要只复制正在使用的 SQLite 主文件。
3. 使用 0.0.4 的 `Orbit.app` 替换 `/Applications/Orbit.app`，然后重新打开。

0.0.4 默认数据目录是：

```text
~/Library/Application Support/Orbit
```

可用以下命令在 Finder 中打开：

```bash
open "$HOME/Library/Application Support/Orbit"
```

旧版历史品牌目录由兼容逻辑处理：当新目录尚不存在且满足迁移条件时，应用会迁移旧目录并保留兼容链接。如果新旧目录同时存在，不应假设它们会自动合并。不要手动将旧数据库文件改名为 `orbit.db`。如使用自定义 `ORBIT_HOME`，应备份实际指定的目录。

替换或移除 `Orbit.app` 通常不会删除 Application Support 中的数据。来源 Agent 的原始记录也不在 App 安装目录内；Orbit 的索引目录不一定包含所有原始会话，不能替代来源数据的独立备份。

## 0.0.4 本版更新

### 协作人格与展示

- 引入 16 型人格之花、独立 Agent 曲线与徽章。
- 增加人格切换与首次揭晓动效。
- 分享卡、菜单栏及桌面小组件同步新设计。
- 支持减少动态效果，Lite / Advance 保持共用界面体系。

### 分析与 AI 可靠性

- 改进时间与筛选范围处理、特征和画像缓存，以及并发物化。
- 改进 AI 预算预留、取消与重试处理。
- 修正问答范围和迟到响应处理，减少旧请求影响当前结果的情况。

### 数据与隐私

- 改进会话发现、来源映射、Hook 与通知脱敏。
- 改进数据清除以及设置并发更新。
- 资源清单支持独立的 command / agent 类型，并包含旧清单数据迁移。

### 推荐与资源库

- 保留省时、省 token 估算和个性化输出。
- 整合 Catalog 来源、检索及安装限制。
- 改进安装失败回滚和效果跟踪的范围处理。

推荐中的省时、省 token 数值属于估算，不代表已经验证的实际收益。本版不包含历史技能学习功能。

### macOS 桌面宿主

- 改进退出清理和退出期间的重新启动处理。
- 改进 helper 崩溃后的重试。
- 改进原生标题栏和全屏适配。

## 使用提示与数据边界

- 在侧栏顶部切换 Lite / Advance；HUD 与桌面小组件可通过「窗口」菜单控制。
- 关闭主窗口后，App 可以继续在菜单栏运行；需要完全退出时使用 `⌘Q`。
- 只有明确启用的来源才会被导入。首次导入或大范围分析可能需要等待，文件数、记录数与会话数是不同的进度单位。
- 基础导入和确定性分析在本机运行，不要求远端模型。启用 AI 后，本机 Agent 或所选引擎可能调用其配置的远端模型；资源目录同步、资源安装和可选模型权重下载也可能联网。
- 使用基于本机 Agent 的 AI 能力时，需要相应工具已安装并完成登录，并在 Orbit 中授权。不要把“本地 App”理解成所有可选功能都绝不联网。
- 暂停采集、排除会话与删除数据是不同操作；删除前请核对界面展示的范围。

## 已知限制与排障

- 当前仅提供 arm64 版本，未进行 Apple 公证；不承诺未经验证的平台兼容性。
- 大量会话、30 天或全部范围的首次分析仍可能较慢。等待当前任务完成，必要时缩小范围；不要通过反复重启强行打断数据库操作。
- 安装包二进制的最低系统声明已检查，但原发布未覆盖所有 macOS 14 实机、原生窗口生命周期与系统权限场景。
- 原 UI 测试中曾出现人格揭晓动画时序断言失败，单独重跑通过；保留这一时序波动记录。
- 如无法启动，先核对系统版本、芯片架构、安装位置、哈希及上面的首次打开步骤。反馈时注明是系统拦截、进程退出还是窗口未显示。

请在 [Orbit Issues](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/issues) 提供 App 版本、macOS 版本、芯片型号、复现步骤与脱敏截图。不要公开上传真实会话数据库、访问令牌、私人路径或 `.env`。

## 验证记录

原安装包基于提交 `805f9b5385489f524f161fe88fa041e645e8dc2a` 构建。以下是原发布时的记录，**不是本次迁移重新执行的测试**：

- 完整构建 Python helper、Swift 宿主和统一 UI，生成 DMG / ZIP；签名 deep / strict 校验通过，167 个 Mach-O 文件的最低系统声明均不高于 macOS 14。
- 冻结 helper 冒烟通过：启动、页面加载、API 鉴权、构造数据导入、分析计算和正常退出。
- 跨包与服务集成 128 项通过；菜单及数据库迁移定向回归 3 项通过；文档与 UI 生成产物检查通过。
- 真实 gateway 构造数据旅程：112 个步骤成功，0 个页面脚本错误；请求失败记录为 25 次查询取消和 1 次预期的 `ai_disabled` 拒绝。
- UI 整轮：770 项通过、1 项人格揭晓动画时序断言失败、1,341 项条件跳过。唯一失败项随后单独重跑通过；跳过项不计为通过。

原发布未运行全量 `pnpm check`，未人工验收全部原生窗口生命周期与系统权限场景。构造回归不验证真实模型质量或推荐的因果收益。

本次迁移核对了原 Release 的附件名称、字节数和 SHA-256，并读取安装包内的版本、构建号及最低系统声明；未重新构建或修改安装包。

## 本版本许可与附件

0.0.4 是已有版本的原样再发布，保留原有 Apache-2.0 与第三方组件许可，**不追溯适用发布仓库专有协议中的禁止逆向条款**。

- [LICENSE-SCOPE.md](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/blob/v0.0.4/releases/0.0.4/LICENSE-SCOPE.md)：本版本适用的许可范围。
- [LICENSE-APACHE-2.0.txt](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/blob/v0.0.4/releases/0.0.4/LICENSE-APACHE-2.0.txt)：原有 Apache-2.0 许可全文。
- [THIRD-PARTY-NOTICES.md](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/blob/v0.0.4/releases/0.0.4/THIRD-PARTY-NOTICES.md)：依据安装包现有内容整理的第三方许可说明。
- `BUNDLED-LICENSES.zip`：安装包内 30 个已有许可文件的原样副本，方便单独查阅；不是完整依赖审计的声明。

上述许可文件也随本 Release 作为附件提供，请与安装包一并保留。它们没有被重新写入原 DMG / ZIP，因此不会改变原安装包的哈希和签名。

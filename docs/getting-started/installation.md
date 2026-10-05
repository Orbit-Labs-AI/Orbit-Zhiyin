# 安装与升级

Orbit 桌面 App 面向 **Apple Silicon、macOS 14 及以上**。安装包自带后端运行时，使用 App 不需要 Python、Node 或开发工具。Intel Mac、Windows 与 Linux 桌面安装包不在当前交付范围。

## 安装

1. 打开 [GitHub Releases](https://github.com/ActionMesh-AI/Orbit/releases/latest)，阅读该版本说明与已知问题。
2. 下载 `arm64.dmg`，打开后将 Orbit 拖入「应用程序」；也可解压 `arm64.zip` 后移动 `Orbit.app`。
3. 打开 Orbit，按首次引导选择允许读取的 Agent 来源。只想先看界面时，可先[体验示例](demo.md)。

当前构建脚本默认使用 ad-hoc 签名，未公证；具体下载版本以 Release 声明为准。如 macOS 拦截，请先核实来自本项目的 Release，再按系统提示在「系统设置 → 隐私与安全性」中允许打开。不要为运行 App 全局关闭系统安全保护。已公证的后续构建不需要这一步。

## 第一次打开

选择来源后，Orbit 会索引和整理本机记录。首次导入耗时受日志数量、文件体积与机器负载影响；进度中的文件数、记录数与会话数是不同单位。已有结果时可先看上一份已发布数据，新的分析完成后再更新。

侧栏顶部切换 Lite / Advance；关闭主窗口后 App 仍可在菜单栏运行，使用 `⌘Q` 完全退出。HUD 和桌面小组件由「窗口」菜单控制。

接下来阅读[导入会话](../guides/importing-data.md)和[理解分析结果](../guides/understanding-analysis.md)。

## 升级与数据

先从 Orbit 菜单退出旧版本，再替换应用。升级前如需备份，请在 App 退出后复制整个数据目录；只复制正在使用的 SQLite 主文件可能遗漏 WAL 中的数据。

当前源码默认数据目录为 `~/Library/Application Support/Orbit`。旧版本使用的历史品牌目录由兼容模块迁移；不要手动把旧 MVP 数据库改名为 `orbit.db`。`ORBIT_HOME` 可以指定独立数据目录，详见[隐私与数据](../guides/privacy.md)。

源码版本与公开发布版本可能不同：`apps/desktop/build.py` 的版本号不等于已公开下载的最新版。请用 Release 标签报告安装问题，用提交 SHA 报告源码问题。

## 遇到问题

参见[排障指南](../guides/troubleshooting.md)。构建自己的安装包请转到[Mac App 开发](../development/mac-app.md)。返回[开始使用](README.md)。

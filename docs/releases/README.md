# 发布与版本记录

桌面 App 的安装包、签名说明和已知问题在 [GitHub Releases](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases)。草稿 Release 不是公开可下载版本，源码的构建版本号也不代表已经发布。每个版本的说明、校验值与许可快照保存在仓库根目录的 `releases/<版本>/`（如 [0.0.4](../../releases/0.0.4/README.md)），发布流程见 [RELEASING.md](../../RELEASING.md)。

[后端版本记录](backend/README.md)保留最初 v0.1–v0.13.6 的阶段交付，编号属于后端包，与桌面 0.0.x 分开。data、catalog 和 backend 各有独立包版本，见各自 `pyproject.toml`。

使用当前源码请阅读[开发环境](../development/setup.md)，安装发布版请阅读[安装指南](../getting-started/installation.md)。返回[文档首页](../README.md)。

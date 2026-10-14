# Orbit 文档

从你要完成的事情进入文档。这里的现行手册跟随 `main`；本轮重写已整合后续主线实现；具体接口和默认值以当前代码及各模块文档为准。下载版本的安装要求、功能与限制，以 [GitHub Release](https://github.com/Orbit-Labs-AI/Orbit-Zhiyin/releases) 为准。

## 使用 Orbit

| 目标 | 入口 |
| --- | --- |
| 安装或先看示例 | [开始使用](getting-started/README.md) |
| 导入、分析、推荐、AI 与排障 | [使用指南](guides/README.md) |
| 了解当前能做什么 | [产品说明与边界](product/README.md) |
| 查看停止开发前的方向与历史方案 | [历史方案](archive/plans/README.md) |

## 参与开发

| 目标 | 入口 |
| --- | --- |
| 提交问题、文档或代码 | [贡献指南](../CONTRIBUTING.md)、[开发手册](development/README.md) |
| 理解进程、依赖与数据所有权 | [架构](architecture/README.md) |
| 对接数据库、分析对象和安装产物 | [契约](contracts/README.md) |
| 修改导入、分析、资源、推荐或 AI | [模块参考](modules/README.md) |
| 修改界面、品牌或展示素材 | [设计](design/README.md)、[UI 源码](../prototypes/README.md) |
| 运行验证 | [测试指南](development/testing.md)、[评测](../evals/README.md)、[性能基准](../benchmarks/README.md) |

## 查找依据与历史

| 目录 | 内容与使用方式 |
| --- | --- |
| [audits](audits/README.md) | 某个版本上的检查、实测与验证记录；数字仅对原文基线成立 |
| [research](research/README.md) | 代码直接依据的外部源码、日志格式与平台规范快照；引用时核对版本 |
| [releases](releases/README.md) | 桌面 Release 入口与独立的后端历史记录 |
| [archive](archive/README.md) | 已被替代的设计、计划、事故复盘和目录迁移资料 |

`getting-started` 与 `guides` 是用户手册；`architecture`、`contracts`、`development`、`modules` 和 `design` 是当前实现参考。`plans` 只记录待确认方向，旧的长篇方案已放入 `archive/plans`。`research` 只收代码直接依据的开发调研；产品需求、提案、竞品与方法研究和团队的模块设计在 TeamHub 的 [Orbit 项目页](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/README.md) 维护。各目录的 README 维护本区完整索引，避免首页变成数百项文件清单。

命令从仓库根执行，另有说明除外。文档组织、状态标签与搬迁规则见[文档维护](development/documentation.md)；安全与协作规则见[安全政策](../SECURITY.md)、[行为准则](../CODE_OF_CONDUCT.md)和[项目指令](../AGENTS.md)。

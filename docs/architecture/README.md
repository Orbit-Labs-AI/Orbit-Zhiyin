# 架构

Orbit 的交互层是 macOS 原生宿主与共享 Web UI，应用逻辑运行在本机 Python gateway，事实与应用状态由独立 SQLite 库持有。

| 问题 | 文档 |
| --- | --- |
| 一个功能应该修改哪个包？ | [模块与依赖](module-map.md) |
| gateway、worker、快照和 UI 如何协作？ | [App 服务](app-services.md) |
| 原生日志怎样成为可分析事实？ | [数据流程](data-pipeline.md) |
| 分析、推荐、报告怎样组织？ | [后端编排](backend.md) |

字段语义见[契约](../contracts/README.md)，具体算法见[模块参考](../modules/README.md)。返回[文档首页](../README.md)。

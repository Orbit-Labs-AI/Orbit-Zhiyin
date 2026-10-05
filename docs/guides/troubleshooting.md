# 排障指南

先记下 App 版本或源码 SHA、macOS 版本、使用的 Agent 与当前步骤。判断问题来自安装、导入、分析还是可选服务，可以减少重复操作。

| 现象 | 先检查 | 下一步 |
| --- | --- | --- |
| macOS 阻止打开 | Release 来源、架构、系统版本与签名说明 | 按[安装指南](../getting-started/installation.md)处理 |
| 找不到会话 | 来源是否启用、目录是否正确、筛选是否为空 | 回到数据源与会话筛选，区分发现和导入 |
| 导入似乎停住 | 当前阶段、最近进度、文件/记录单位、错误原因 | 等当前大文件阶段结束；确实失败后再重试同一任务 |
| 显示旧数据 | 导入是否已发布、分析是否仍计算、快照时间 | 保留上一份结果，等对应任务完成后刷新 |
| 指标为 `—` | 是否缺用量、状态、时间或必要样本 | 查覆盖说明和证据，不手工补成零 |
| 推荐为空 | 范围、证据、候选适用性、目录状态 | 阅读空态原因；资源多不代表每个问题都有匹配 |
| AI 无法使用 | 引擎可用性、授权类别、配置与预算 | 在 AI 设置和任务错误中定位；基础分析仍可用 |
| 向量检索不可用 | 模型目录、可选依赖、所选 home 的编码状态 | 按 [Catalog 指南](../../packages/catalog/README.md)配置，或继续词法检索 |
| API 返回 401 / 403 | 是否调用 App gateway、令牌和来源是否匹配 | 使用当前启动实例的授权，不复用旧 token |
| 源原文不可读 | 原文件是否删除、改写或路径失效 | 索引模式无法恢复不存在的原文；检查来源与备份 |

## 命令行诊断

在明确选定的数据目录上运行：

```sh
uv run orbit --home /absolute/orbit-home verify
uv run orbit --home /absolute/orbit-home analytics --no-text --output .local/diagnostic.json
```

`--no-text` 跳过昂贵的文本表示，不是跳过全部分析。需要限制规模时可以缩小时间/项目范围，或在子命令前指定 `--max-events`；超预算应明确失败，不返回看似完整的部分结果。

原生宿主日志位于所选 home 的 `desktop.log`。不要直接上传整份日志或数据库。先截取最小错误片段并脱敏，再通过 [Bug 模板](https://github.com/ActionMesh-AI/Orbit-Source/issues/new/choose)提供复现步骤、预期和实际结果。

开发者可继续查看[导入流程](../development/import-pipeline.md)、[App 服务](../architecture/app-services.md)及[测试指南](../development/testing.md)。返回[使用指南](README.md)。

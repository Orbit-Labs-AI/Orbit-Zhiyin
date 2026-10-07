# 团队早期技术方案（2026-10）

2026-10-07 从团队 Vault 迁入的完整历史正文。保留原有日期、提案、讨论及验收边界，不用当前实现改写当时结论；仅更新导航、空白和不可公开访问的对话定位。原始字节及旧名保留在团队 Archive。

这些页面不是当前任务清单。旧名称、目录、函数和命令仅用于理解当时方案，不能直接照做。现行参考见 [架构](../../../architecture/README.md)、[数据契约](../../../contracts/data.md)、[分析](../../../modules/analytics/README.md)和[推荐引擎](../../../modules/recommendation/engine.md)。

## 原始设计与功能清单

- [后端-处理流程](<backend-flow.md>)
- [前端-交互流程](<frontend-flow.md>)
- [数据标准化+预处理](<data-normalization.md>)
- [数据标准化构想](<feature-representation-proposal.md>)
- [推荐端目录设计](<recommendation-layout.md>)
- [分析Feature一览](<feature-inventory-2026-10-02.md>)

## 八族分析的协作定义与阶段记录

- [分析模块分类](<analytics/classification.md>)
- [Task 任务](<analytics/task.md>)
- [Instruction 指令／控制方式](<analytics/instruction.md>)
- [Interaction 交互行为](<analytics/interaction.md>)
- [Preference 主观偏好](<analytics/preference.md>)
- [Respond Agent 回应与执行](<analytics/respond.md>)
- [Cost-Time 用量与时间](<analytics/cost-time.md>)
- [Outcome 主观结果](<analytics/subjective-outcome.md>)
- [Outcome 客观结果](<analytics/objective-outcome.md>)

这里的部分页面同时包含草案与当时验收，不拆掉上下文。另四份独立实现报告见 [2026-10-02 四族记录](../../../audits/feature-families-2026-10-02/README.md)；不要把历史的“PR 尚未合并”或测试条数当今天状态。

## 两个原始占位项

团队原 `数据/数据获取.md` 只有一个指引：参考 Agent 的基本组件和流程构建一般 trajectory 表述；该原意保留在此，不将其包装成已完成采集方案。原 `数据/数据存储.md` 是空文件，没有可迁入的设计内容。二者原文件均由团队 Archive 保留。

返回[历史方案](../README.md)。

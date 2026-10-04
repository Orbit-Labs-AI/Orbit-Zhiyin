# 执行与瓶颈特征

Interaction、Respond、Cost-Time 和 Outcome 描述协作过程中的可观察事实。它们提供诊断输入，不直接把一次失败、长耗时或多轮交互解释为浪费。

## 四族职责

| 族 | 核心输入 | 核心输出 |
| --- | --- | --- |
| Interaction | 已确认真人消息、可见标注、任务关系 | 介入位置、纠偏候选/确认、重复要求与分母 |
| Respond | 标准事件、配对调用、父子身份 | 调用序列、明确状态、重试关系、执行区间 |
| Cost-Time | model_call、累计快照、可靠时间 | token 桶、活动、墙钟/原生/审批耗时和覆盖 |
| Outcome | 执行检查、验收条件、版本与范围 | 验证结果、逐项验收、未知或不匹配原因 |

实现分别位于 [interaction](../../../packages/backend/src/orbit_backend/analytics/interaction/README.md)、[respond](../../../packages/backend/src/orbit_backend/analytics/respond/README.md)、[cost_time](../../../packages/backend/src/orbit_backend/analytics/cost_time/README.md) 与 [outcome](../../../packages/backend/src/orbit_backend/analytics/outcome/README.md)。

## 关系先于计数

调用按明确身份配对，同一调用的 call/result 只算一次；冲突保留证据。确认重试需要失败、同任务、工具/状态范围及参数或显式重试关系。仅相邻同名工具不足以确认。

验证需要执行证据与可解释结果，不能把命令提及、dry run 或外层成功当作内部检查通过。验收还要求任务、产物版本和覆盖范围匹配；不存在完整条件集合时，任务是否成功保持未知。

## 从事实到问题

八族结果交给 [Signal 层](signals.md)和推荐的问题构建器，后者保留机会分母、证据层级和未升级原因。重复模式只是候选线索；没有足够证据时允许不产生推荐。

共同范围规则见[分析输入](../../contracts/analysis-inputs.md)，扰动与失败恢复见[鲁棒性验收](../../development/analytics-robustness.md)。

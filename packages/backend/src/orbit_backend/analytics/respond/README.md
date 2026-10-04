# Respond：执行与调用关系

将工具、模型和子代理过程整理成有身份的执行关系。调用次数、结果状态、轨迹转移、确认重试和可靠并行区间分别输出。

## 输入与入口

`analyze_respond` 组合 `pair_tool_calls`、`normalize_tool_calls`、`analyze_execution_sequence`、`build_execution_relations` 和 `execution_intervals`。

输入必须已按同一 Scope 选择，并保留 statistical members、上下文、覆盖及历史可见时间。不能在族内读取其他来源补齐缺口。实现从 [analyzer.py](analyzer.py) 进入，字段与版本在本模块字典/常量中维护。

## 证据与缺失

call/result 只算一次调用；重复身份去重，冲突保留证据。确认重试需要失败、同任务、工具/状态范围及参数或显式关系；同名相邻调用不够。subagent 的 spawn/activity/message/wait/result/close 分开，实例按明确 child_session_uid 去重，UI item ID 不能代替。可靠半开区间相邻不算重叠。

返回已知数、未知数、证据与规则版本；可用空集和不可用输入不同。语义推断、词面候选、确认标注和协议事实各自保留依据，不能在聚合时无声升级。

## 修改与验证

先明确字段粒度、单位、分母和关系，再补正例、反例、空输入与截止边界。相关回归见 [测试](../../../../tests/bottleneck/test_respond.py)；跨族入口验证见根[测试指南](../../../../../../docs/development/testing.md)。不要复制历史测试总数作为本次通过证明。

全局设计见[分析模块](../../../../../../docs/modules/analytics/README.md)，输入合同见[analysis-input-v1](../../../../../../docs/contracts/analysis-inputs.md)。

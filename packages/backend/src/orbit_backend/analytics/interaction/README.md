# Interaction：介入与纠偏

描述真人消息在执行过程中的位置、纠偏目标、重复要求和摩擦。新增功能、补充信息与纠正已有交付分别处理，不能都算作纠偏。

## 输入与入口

`analyze_interaction` 组合意图校验、介入位置与汇总；`classify_message_intents`、`locate_interventions`、`summarize_interactions` 可供局部使用。

输入必须已按同一 Scope 选择，并保留 statistical members、上下文、覆盖及历史可见时间。不能在族内读取其他来源补齐缺口。实现从 [features.py](features.py) 进入，字段与版本在本模块字典/常量中维护。

## 证据与缺失

confirmed 需要可见的有效标注与同会话/同任务的先前对象；关键词只构成候选。纠偏比例使用来源和意图可判定的真人消息分母，同一消息多标签只计一次，未知分列。后补标注不能提前进入历史窗口。

返回已知数、未知数、证据与规则版本；可用空集和不可用输入不同。语义推断、词面候选、确认标注和协议事实各自保留依据，不能在聚合时无声升级。

## 修改与验证

先明确字段粒度、单位、分母和关系，再补正例、反例、空输入与截止边界。相关回归见 [测试](../../../../tests/bottleneck/test_interaction.py)；跨族入口验证见根[测试指南](../../../../../../docs/development/testing.md)。不要复制历史测试总数作为本次通过证明。

全局设计见[分析模块](../../../../../../docs/modules/analytics/README.md)，输入合同见[analysis-input-v1](../../../../../../docs/contracts/analysis-inputs.md)。

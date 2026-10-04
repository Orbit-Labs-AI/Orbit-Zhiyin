# Outcome：客观检查与验收

记录实际执行的检查，并将其与明确验收条件、产物版本和覆盖范围匹配。局部测试通过不能证明整个任务成功。

## 输入与入口

`analyze_outcome` 组合 `extract_validation_runs`、`collect_acceptance_criteria`、`match_acceptance_criteria` 和 `summarize_objective_outcomes`。

输入必须已按同一 Scope 选择，并保留 statistical members、上下文、覆盖及历史可见时间。不能在族内读取其他来源补齐缺口。实现从 [analyzer.py](analyzer.py) 进入，字段与版本在本模块字典/常量中维护。

## 证据与缺失

命令提及、dry run、拒绝执行和外层脚本成功不能冒充内部检查通过。验收按任务、会话树、对象版本、类型和 full/subset 覆盖匹配，结果可见时间优先于调用开始时间。缺少明确完整条件集合时 task_success 保持 null；旧版本通过不能覆盖新版本要求。

返回已知数、未知数、证据与规则版本；可用空集和不可用输入不同。语义推断、词面候选、确认标注和协议事实各自保留依据，不能在聚合时无声升级。

## 修改与验证

先明确字段粒度、单位、分母和关系，再补正例、反例、空输入与截止边界。相关回归见 [测试](../../../../tests/bottleneck/test_outcome.py)；跨族入口验证见根[测试指南](../../../../../../docs/development/testing.md)。不要复制历史测试总数作为本次通过证明。

全局设计见[分析模块](../../../../../../docs/modules/analytics/README.md)，输入合同见[analysis-input-v1](../../../../../../docs/contracts/analysis-inputs.md)。

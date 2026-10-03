# Instruction：本次执行要求

提取当前真人请求中的自主程度、先后顺序、验证、范围、禁止动作、验收、格式和工具要求。持续偏好由 Preference 解释，提取结果本身不授予任何执行权限。

## 输入与入口

公共函数为 `instruction_text`、`structure`、`extract_instruction_constraints`、`resolve_instruction_scope` 和 `summarize_control_patterns`。正文清理、结构统计、约束提取与历史作用域分别维护。

输入必须已按同一 Scope 选择，并保留 statistical members、上下文、覆盖及历史可见时间。不能在族内读取其他来源补齐缺口。实现从 [extraction.py](extraction.py) 进入，字段与版本在本模块字典/常量中维护。

## 证据与缺失

每项约束保留原话证据、对象、条件、任务和时间。只分析可确认的直接要求，排除代码、引用、假设和元语言；否定及例外不能丢失。替换旧要求需要明确关系，冲突保留待确认。

返回已知数、未知数、证据与规则版本；可用空集和不可用输入不同。语义推断、词面候选、确认标注和协议事实各自保留依据，不能在聚合时无声升级。

## 修改与验证

先明确字段粒度、单位、分母和关系，再补正例、反例、空输入与截止边界。相关回归见 [测试](../../../../tests/analytics/instruction)；跨族入口验证见根[测试指南](../../../../../../docs/development/testing.md)。不要复制历史测试总数作为本次通过证明。

全局设计见[分析模块](../../../../../../docs/modules/analytics/README.md)，输入合同见[analysis-input-v1](../../../../../../docs/contracts/analysis-inputs.md)。

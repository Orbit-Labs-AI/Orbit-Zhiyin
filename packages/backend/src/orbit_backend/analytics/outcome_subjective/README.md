# Subjective Outcome：交付反馈

从直接真人反馈中分别观察接受、确认完成和返工，并关联具体交付。礼貌、沉默、情绪、新增需求与对假设内容的讨论不自动成为验收。

## 输入与入口

`analyze_subjective_outcomes` 组合交付收集、反馈提取、目标关联与汇总。user_acceptance、user_confirmed_completion、rework_feedback、feedback_target 和 link_status 分开。

输入必须已按同一 Scope 选择，并保留 statistical members、上下文、覆盖及历史可见时间。不能在族内读取其他来源补齐缺口。实现从 [__init__.py](__init__.py) 进入，字段与版本在本模块字典/常量中维护。

## 证据与缺失

只将同会话、同任务/对象且在反馈前的可见交付作为确认目标；显式坏链接不能回退到其他交付。linked、candidate、unlinked 各自保留；矛盾完成陈述为未知并标冲突。任务、产物和单次交付的完成范围不能互相扩大。

返回已知数、未知数、证据与规则版本；可用空集和不可用输入不同。语义推断、词面候选、确认标注和协议事实各自保留依据，不能在聚合时无声升级。

## 修改与验证

先明确字段粒度、单位、分母和关系，再补正例、反例、空输入与截止边界。相关回归见 [测试](../../../../tests/regression/test_subjective_outcomes.py)；跨族入口验证见根[测试指南](../../../../../../docs/development/testing.md)。不要复制历史测试总数作为本次通过证明。

全局设计见[分析模块](../../../../../../docs/modules/analytics/README.md)，输入合同见[analysis-input-v1](../../../../../../docs/contracts/analysis-inputs.md)。

# 特征与推荐诊断

诊断用于回答“这项测量来自哪里、为何有或没有建议”。它应保留每个特征族的有效输入、未知原因、关系和推荐证据，而不只输出最终分数。

## 阅读顺序

1. 确认 home、Scope、排除项、数据与算法版本。
2. 检查事件、调用、任务和安装清单的覆盖。
3. 找到异常计数引用的事件/调用，核对任务与时间关系。
4. 查看问题是否满足升级条件，再看候选的召回、资格与排序。
5. 核对安装状态和效果证据；没有观察到效果时保持未测量。

## 使用工具

常规入口为 `orbit analytics` 和 `orbit analysis-report`。专门诊断工具位于 [evals/analytics](../../../evals/analytics/)，具体输入用相应模块的 `--help` 核对；真实快照必须显式给定，不从开发机自动取样。

按[鲁棒性指南](../../development/analytics-robustness.md)运行扰动案例可检查计数和推荐是否随有效证据变化。诊断输出保存在新的 `.local/` 子目录；不要把用户全文和数据库作为公开附件。

## 结论边界

`needs_context`、空目录、无匹配和未知效用是不同原因，不应合并成成功或 0 分。构造样本验证规则的可重复行为；它不能证明真实语义准确率或 Skill 的因果收益。当前推荐主栈与分析侧栈见[推荐引擎](../recommendation/engine.md)。

## 开发诊断与 App 卡片

`analytics/diagnostics.py` 通过 `evals.analytics.local_diagnostics` 和 `scripts/check-feature-diagnostics.sh` 等开发工具运行，核对模块覆盖；gateway 没有该诊断器的直接路由。App 问题卡来自 `presentation/diagnostics.py` 与 `/v1/analytics/presentation`，两者的读者和输出不同。

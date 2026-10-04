# Cost-Time：用量与时间

度量观察到的模型请求、token 桶、累计快照和活动时间。日志跨度、原生执行、墙钟并集、审批等待及模型延迟不混成一种工时。

## 输入与入口

`analyze_cost_time` 组合 `usage`、`activity`、`normalize_token_buckets` 与 `summarize_durations`；输入使用统一契约中的 sessions/events/calls/model_calls 与 Scope。

输入必须已按同一 Scope 选择，并保留 statistical members、上下文、覆盖及历史可见时间。不能在族内读取其他来源补齐缺口。实现从 [analyzer.py](analyzer.py) 进入，字段与版本在本模块字典/常量中维护。

## 证据与缺失

input_tokens 是未缓存输入，缓存读写分桶，reasoning 是 output 的子集；不同来源的转换由适配器声明。累计 100、150 取同周期末次 150，不相加为 250。未知成本、请求边界和端点不补零；原生耗时不反推结束时刻。0–10 与 5–15 的区间和为 20、并集为 15，均不是人工投入。

返回已知数、未知数、证据与规则版本；可用空集和不可用输入不同。语义推断、词面候选、确认标注和协议事实各自保留依据，不能在聚合时无声升级。

## 修改与验证

先明确字段粒度、单位、分母和关系，再补正例、反例、空输入与截止边界。相关回归见 [测试](../../../../tests/bottleneck/test_cost_time.py)；跨族入口验证见根[测试指南](../../../../../../docs/development/testing.md)。不要复制历史测试总数作为本次通过证明。

全局设计见[分析模块](../../../../../../docs/modules/analytics/README.md)，输入合同见[analysis-input-v1](../../../../../../docs/contracts/analysis-inputs.md)。

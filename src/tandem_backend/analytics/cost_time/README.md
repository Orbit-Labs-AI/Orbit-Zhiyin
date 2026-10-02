# Cost / Time：用量与时间

负责人：genius-FXC。范围：非语义 × bottleneck。耗时依赖 Respond 提供的可靠区间；不估算人工投入。

## 已完成

- `analyzer.py` 接管 `usage`、`activity` 与 Token 计量；`analyze_cost_time` 为组合入口，`summarize_durations` 汇总执行时间。
- 逐请求要求 call/delta、明确调用 ID 和可靠边界。相同请求去重，冲突请求隔离并暴露 ID；累计快照不能作为模型请求。
- Token 分成未缓存输入、缓存读取、缓存写入、输出。`reasoning_tokens` 已包含在输出，不重复相加。缺失、负数、布尔值、NaN 和不明包含关系保持未知。
- 完整总量与已知请求小计分开；部分覆盖不能给出完整总量。累计快照只取同会话、同周期的末次有效值；回退周期失效，root_tree 不与子调用相加。
- 原生端点／明确报告的执行耗时、日志间隔估算、会话跨度分别输出；可靠区间用并集去重。每条记录保留证据、来源、质量及有效／未知数。
- 主会话开始、真人消息、工具调用、模型请求分别按日／小时分桶，使用显式显示时区；没有原生会话开始时间就保留未知。

## 输入与使用

```python
from tandem_backend.analytics.cost_time import analyze_cost_time
from tandem_backend.analytics.inputs import Scope
result = analyze_cost_time(sessions, events, calls, model_calls, {"s"},
                           Scope(display_timezone="Asia/Shanghai"))
```

输入沿用 analysis-input-v1。默认 input_tokens 为规范的未缓存输入；适配器若保留包含缓存的来源值，必须明确提供 `input_tokens_semantics="includes_cache"`，此时减去缓存读写得到未缓存输入。unknown 或不支持的语义不提供输入总量。默认契约也要求 reasoning 已含于 output；来源不同应在适配层转换，不能在这里猜测。

`duration_source=reported/native_report` 代表原生耗时报告；event_difference 或 duration_quality=estimated 单列估算。可靠端点由 Respond 处理，reported duration 不能推造 ended_at。会话只有一个有效时间时跨度为 0，同时记录有效数；没有有效时间为 null。

旧 usage.cost_usd 等兼容字段仍保留既有逻辑，但本次不增加费用分析、价格表、首次验收时间或真实人工工作时长。新的 benchmark 应优先使用 Token 与可靠执行时间；不得把跨度或日志间隔当作人工成本。

## 验收与后续

合成用例：`tests/bottleneck/test_cost_time.py`。覆盖缓存包含关系、未知分项、请求去重／冲突、累计 100→150 不相加、跨会话快照、并行 0–10 与 5–15 秒得到 20 秒总和／15 秒并集、缺时间、时区和非法时延。运行：`pytest -q tests/bottleneck/test_cost_time.py`。

待补充：每种 Agent 来源的缓存包含关系与原生请求适配；可靠时钟覆盖；大范围快照的可组合性证明。旧导入器只有无覆盖口径的累计报告时，逐请求统计仍不可用。费用、到首次验收时间与人工投入继续暂缓，需独立数据契约和团队确认。

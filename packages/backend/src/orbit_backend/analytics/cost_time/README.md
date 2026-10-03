---
created: 2026-10-02
added: 2026-10-02
---

# Cost-Time 用量与时间

## Feature TODO

- [ ] **输入／输出 Token `usage.token_buckets`**：[实现](tokens.py)；代码与合成样例已完成，待团队验收。
- [ ] **缓存 Token `usage.token_buckets`**：[实现](tokens.py)；代码与合成样例已完成，待团队验收。
- [ ] **执行耗时 `durations.execution_durations`**：[实现](durations.py)；代码与合成样例已完成，待团队验收。
- [ ] **会话跨度 `durations.session_spans`**：[实现](durations.py)；代码与合成样例已完成，待团队验收。
- [ ] **按日活动 `activity_rhythm.*.by_day`**：[实现](activity.py)；代码与合成样例已完成，待团队验收。
- [ ] **按小时活动 `activity_rhythm.*.by_hour`**：[实现](activity.py)；代码与合成样例已完成，待团队验收。

认领：[genius-FXC](https://github.com/genius-FXC)；关联 Issue：[#4](https://github.com/ActionMesh-AI/Hackathon/issues/4)。实现与合成样例的技术检查已完成；勾选需按团队模板完成最终口径确认和验收，本页不代替成员确认。未来补充项见末尾。

[四模块总览](../../../../../../docs/modules/analytics/bottleneck-features.md) · [合成测试](../../../../tests/bottleneck/test_cost_time.py) · [共享虚构数据集](../../../../tests/fixtures/bottleneck-features-v1.json)

## 范围

非语义 × bottleneck。描述记录可以支持的 Token 和时间；逐请求与累计快照分别处理，执行耗时、日志间隔和会话跨度分别解释。费用分析、首次验收时间和真实人工投入继续暂缓。

## 目录与职责

| 文件 | 职责 |
| --- | --- |
| [__init__.py](__init__.py) | 稳定的特征族公共导出 |
| [analyzer.py](analyzer.py) | 组合入口及兼容导出，不集中实现所有分析 |
| [tokens.py](tokens.py) | Token 包含关系、分项规范化、请求身份与冲突 |
| [features.py](features.py) | 逐请求用量、累计快照、覆盖及旧 usage 字段 |
| [durations.py](durations.py) | 执行耗时、可靠区间并集、日志估算和会话跨度 |
| [activity.py](activity.py) | 显式时区下按日／小时活动及缺时间覆盖 |
| [dictionary.py](dictionary.py) | 本特征族的机器可读字段口径 |

沿用 PR #13 的特征族目录和规则／提取／字段字典分工。`analyzer.py` 只做组合，旧 `analytics.features` 和本目录公共导出继续兼容；没有新增 Agent、模型调用或语义分类器。

## 特征口径

| 字段（相对本模块输出） | 粒度／类型 | 定义与提取规则 |
| --- | --- | --- |
| `usage.token_buckets` | 模型请求 · Token 数 | 输入为未缓存输入；输出已含 reasoning，不能重复相加；必要分项未知时不声称完整总量。 |
| `usage.token_buckets` | 模型请求 · Token 数 | 区分缓存读／写；includes_cache 明确声明后才从输入扣除，缺包含关系保持未知。 |
| `durations.execution_durations` | 调用 · 毫秒 | 墙钟跨度与原生执行报告独立保留；event_difference 单列估算，reported 耗时不推造 ended_at。 |
| `durations.session_spans` | 会话 · 毫秒 | 有效事件最大时间减最小时间；一个有效时间为 0，无有效时间为 null，不能等同人工工作时长。 |
| `activity_rhythm.*.by_day` | 所选范围 · 计数分布 | 真人消息、主会话开始、工具调用和可靠模型请求分别统计；累计快照不能冒充模型请求。 |
| `activity_rhythm.*.by_hour` | 所选范围 · 计数分布 | 使用 Scope.display_timezone；无时间不入桶，不推造会话开始时间。 |

统一输出位于 `bottleneck_features.cost_time`，同时提供总体、会话树和项目范围。缺失保持 `null`，候选不当确认，已知子集不等于完整总体；有效数、未知数与证据一起解释指标。

## 分析函数

| 已实现函数 | 输入 → 输出 | 主要处理 |
| --- | --- | --- |
| [`normalize_token_buckets(row)`](tokens.py) | 请求 → 规范 Token 分项 | 处理缓存包含关系，拒绝负数、布尔值和非法分项。 |
| [`prepare_requests(model_calls)`](tokens.py) | 模型调用 → 唯一可靠请求与异常 | 要求 call/delta、调用 ID 和可靠边界；冲突请求隔离。 |
| [`usage(model_calls, events, sessions, scope, records_complete=True)`](features.py) | 请求／快照 → 用量及覆盖 | 对应草案 summarize_token_usage；累计快照不相加、不混入请求。 |
| [`summarize_durations(calls, events, intervals=None)`](durations.py) | 调用／日志／区间 → 耗时与跨度 | 调用时长总和与区间并集分开，保留来源和未知数。 |
| [`activity(sessions, events, calls, model_calls, main_ids, scope)`](activity.py) | 带时间记录 → 日／小时分布 | 对应草案 analyze_activity_rhythm；按事件来源分别分桶。 |
| [`analyze_cost_time(sessions, events, calls, model_calls, main_ids, scope, …)`](analyzer.py) | 同范围记录 → 完整 Cost-Time 结果 | 组合用量、耗时和活动，不估算人工投入。 |

表中 `…` 省略可选参数，完整签名以对应代码为准。函数直接调用接收同一筛选范围的记录；推荐通过 `analytics.service.analyze_bundle` 统一筛选，时间窗口为 `[from_ts, until_ts)`。

## 对接已有分析

- `features.py`、`activity.py`、`tokens.py` 分别处理 `usage`、活动与 Token 计量；`analyze_cost_time` 为组合入口，`summarize_durations` 汇总执行时间。
- 逐请求要求 call/delta、明确调用 ID 和可靠边界。相同请求去重，冲突请求隔离并暴露 ID；累计快照不能作为模型请求。
- Token 分成未缓存输入、缓存读取、缓存写入、输出。`reasoning_tokens` 已包含在输出，不重复相加。缺失、负数、布尔值、NaN 和不明包含关系保持未知。
- 完整总量与已知请求小计分开；部分覆盖不能给出完整总量。累计快照只取同会话、同周期的末次有效值；回退周期失效，root_tree 不与子调用相加。
- 原生端点／明确报告的执行耗时、日志间隔估算、会话跨度分别输出；可靠区间用并集去重。每条记录保留证据、来源、质量及有效／未知数。
- 主会话开始、真人消息、工具调用、模型请求分别按日／小时分桶，使用显式显示时区；没有原生会话开始时间就保留未知。


## 输入与使用

```python
from orbit_backend.analytics.cost_time import analyze_cost_time
from orbit_backend.analytics.inputs import Scope
result = analyze_cost_time(sessions, events, calls, model_calls, {"s"},
                           Scope(display_timezone="Asia/Shanghai"))
```

输入沿用 analysis-input-v1。默认 input_tokens 为规范的未缓存输入；适配器若保留包含缓存的来源值，必须明确提供 `input_tokens_semantics="includes_cache"`，此时减去缓存读写得到未缓存输入。unknown 或不支持的语义不提供输入总量。默认契约也要求 reasoning 已含于 output；来源不同应在适配层转换，不能在这里猜测。

`duration_source=reported/native_report` 代表原生耗时报告；event_difference 或 duration_quality=estimated 单列估算。可靠端点由 Respond 处理，reported duration 不能推造 ended_at。会话只有一个有效时间时跨度为 0，同时记录有效数；没有有效时间为 null。

旧 usage.cost_usd 等兼容字段仍保留既有逻辑，但本次不增加费用分析、价格表、首次验收时间或真实人工工作时长。新的 benchmark 应优先使用 Token 与可靠执行时间；不得把跨度或日志间隔当作人工成本。


## 验收样例

| 输入／场景 | 预期结果 |
| --- | --- |
| 累计快照依次为 100、150 Token | 同会话同周期取末次 150，不相加为 250。 |
| 可靠区间为 0–10 秒和 5–15 秒 | 执行耗时总和 20 秒、并集 15 秒。 |
| 相同模型请求重复出现／同 ID 内容冲突 | 重复只计一次；冲突隔离并输出 ID。 |
| 用量或时间缺失 | 不填 0、不入时间桶；完整且已知为空的请求集合才可返回零。 |

自动验收：[`test_cost_time.py`](../../../../tests/bottleneck/test_cost_time.py)；跨模块范围、未来信息隔离和 CLI/API 一致性见 [test_integration.py](../../../../tests/bottleneck/test_integration.py)。全部使用合成事件、虚构数据或临时 SQLite，不读取个人 Agent 历史。

```bash
uv run python -m pytest -q packages/backend/tests/bottleneck/test_cost_time.py packages/backend/tests/bottleneck/test_integration.py
uv run ruff check packages/backend/src packages/backend/tests packages/data/src packages/data/tests tests
```

2026-10-02 技术复核：目录拆分后 467 项测试通过；同步 main 的全部已合入特征族、保留并行共存回归并修复四项 P1 后，在隔离提交副本中 775 项测试通过，Ruff 通过。此次文件拆分的 30 个函数逐一比对语法树，93 条全局字段定义保持一致；这是自动技术验证，不是团队人工验收。

## 补充特征与函数

待补充：每种 Agent 来源的缓存包含关系与原生请求适配；可靠时钟覆盖；大范围快照的可组合性证明。旧导入器只有无覆盖口径的累计报告时，逐请求统计仍不可用。费用、到首次验收时间与人工投入继续暂缓，需独立数据契约和团队确认。

新增内容先更新 Feature TODO、字段表和函数表，再补字段类型／单位、输入证据、分母与缺失语义、正反例、认领 GitHub 账号、[#4](https://github.com/ActionMesh-AI/Hackathon/issues/4) 及实现链接；验收后再勾选，进度以 Issue 为准。

## 讨论

各来源 Token 包含关系和请求覆盖仍需适配器声明。默认显示时区由 Scope 指定；本模块不引入价格表或人工工时估计，避免超出当前象限。

## 结论与下一步

当前已完成模块拆分、统一入口接入和合成样例检查；接下来由团队确认口径，并让上游适配器补齐本页注明的证据。业务口径确认人：待确认；本次实现认领：[genius-FXC](https://github.com/genius-FXC)。四目录重构已由 yhyfhgs 通过 [PR #19](https://github.com/ActionMesh-AI/Hackathon/pull/19) 合并；合并发生在最后两项 P1 修复推送前，补充修复在 `fix/genius-FXC-bottleneck-coverage` 提交 PR。按用户约定仅 P0/P1 阻塞，低优先级问题可后续处理。

补充验证（main `4bccf1f` 基线）：Python 3.13 隔离副本中 789 项后端测试、91 项数据层测试通过；35 项连接器构造测试、Ruff、格式检查和全包构建通过；synthetic demo 与 evaluate 通过。没有读取个人 Agent 历史。

## 契约修复后的口径

L3 model_call 本身保证 call/delta，消费者校验 request_identity_quality 与 boundary_quality。原生请求 ID 与累计变化观察分列，边界未知保留诊断原因；不以行哈希证明边界。

wall_elapsed、native_execution、approval_wait 分别输出 P50/P90/P99、样本覆盖、前 16 项及超过一小时的贡献。model_latency 在 usage 单列；没有报告时保持未知。旧 execution_duration_sum_ms 现在只指原生执行报告之和，reliable_interval_union_ms 指墙钟区间并集；二者不能相互替代，也不描述人类工作时间。

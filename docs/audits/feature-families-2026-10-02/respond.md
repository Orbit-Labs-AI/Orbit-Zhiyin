---
created: 2026-10-02
added: 2026-10-02
---

# Respond Agent 回应与执行-实现与验收

> 本页是 2026-10-02 的实现与验收记录，内容待团队确认；文中的“当前”、TODO、测试数量和命令只对当时成立。现行入口：[分析模块](<../../modules/analytics/README.md>)。

本页内容与代码说明 [respond/README.md](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/README.md) 同步，对应提交 `3cdebe6`、[PR #19](https://github.com/Orbit-Labs-AI/Orbit-Source/pull/19)；原始草案见 [Respond Agent 回应与执行](https://github.com/Orbit-Labs-AI/TeamHub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/04-%E6%A8%A1%E5%9D%97%E8%AE%BE%E8%AE%A1/%E5%88%86%E6%9E%90%E6%A8%A1%E5%9D%97/%E5%88%86%E6%9E%90%E7%BB%93%E6%9E%9C%E5%B1%82%E6%AC%A1/Respond%20Agent%20%E5%9B%9E%E5%BA%94%E4%B8%8E%E6%89%A7%E8%A1%8C.md)。

[返回分析模块分类](https://github.com/Orbit-Labs-AI/TeamHub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/04-%E6%A8%A1%E5%9D%97%E8%AE%BE%E8%AE%A1/%E5%88%86%E6%9E%90%E6%A8%A1%E5%9D%97/%E5%88%86%E6%9E%90%E7%BB%93%E6%9E%9C%E5%B1%82%E6%AC%A1/Home-%E5%88%86%E6%9E%90%E6%A8%A1%E5%9D%97%E5%88%86%E7%B1%BB.md) · [对照现有 Feature](https://github.com/Orbit-Labs-AI/TeamHub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/04-%E6%A8%A1%E5%9D%97%E8%AE%BE%E8%AE%A1/%E5%88%86%E6%9E%90%E6%A8%A1%E5%9D%97/%E5%88%86%E6%9E%90Feature%E4%B8%80%E8%A7%88.md)

四目录重构已由 yhyfhgs 合并；最后两项 P1 的补充修复见 [PR #24](https://github.com/Orbit-Labs-AI/Orbit-Source/pull/24)，本页含该补充版本的验证记录。

## Feature TODO

- [ ] **对话轮次 `turn_count`**：[实现](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/analyzer.py)；代码与合成样例已完成，待团队验收。
- [ ] **调用序列 `tool_sequence`**：[实现](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/calls.py)；代码与合成样例已完成，待团队验收。
- [ ] **结果与失败原因 `tool_result_status / failure_reasons`**：[实现](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/rules.py)；代码与合成样例已完成，待团队验收。
- [ ] **重试关系 `retry_links`**：[实现](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/sequence.py)；代码与合成样例已完成，待团队验收。
- [ ] **子代理关系 `subagent_relations`**：[实现](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/relations.py)；代码与合成样例已完成，待团队验收。
- [ ] **执行区间 `execution_intervals / parallel_intervals`**：[实现](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/relations.py)；代码与合成样例已完成，待团队验收。

认领：[genius-FXC](https://github.com/genius-FXC)；关联 Issue：[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。实现与合成样例的技术检查已完成；各项需按团队模板完成最终口径确认和验收后再勾选。未来补充项见末尾。

[四模块总览](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/docs/backend/bottleneck-features.md) · [合成测试](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/tests/bottleneck/test_respond.py) · [共享虚构数据集](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/tests/fixtures/bottleneck-features-v1.json)

## 范围

非语义 × bottleneck。记录 Agent 的响应与执行，提供调用状态、失败证据、重试与关系。调用成功只说明明确调用范围；任务验收交给 Outcome，耗时汇总交给 Cost-Time。

## 目录与职责

| 文件 | 职责 |
| --- | --- |
| [__init__.py](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/__init__.py) | 稳定的特征族公共导出 |
| [analyzer.py](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/analyzer.py) | 组合入口及兼容导出，不集中实现所有分析 |
| [rules.py](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/rules.py) | 协议状态、结果字段和流程状态词表 |
| [calls.py](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/calls.py) | L2 调用／返回配对，L3 去重与冲突处理 |
| [sequence.py](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/sequence.py) | 状态转移、失败原因和确认／候选重试 |
| [relations.py](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/relations.py) | 显式子代理、分叉关系和可靠并行区间 |
| [features.py](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/features.py) | 按工具统计次数、状态分母、耗时与覆盖 |
| [dictionary.py](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/dictionary.py) | 本特征族的机器可读字段口径 |

沿用 PR #13 的特征族目录和规则／提取／字段字典分工。`analyzer.py` 只做组合，旧 `analytics.features` 和本目录公共导出继续兼容；没有新增 Agent、模型调用或语义分类器。

## 特征口径

| 字段（相对本模块输出） | 粒度／类型 | 定义与提取规则 |
| --- | --- | --- |
| `turn_count` | 会话范围 · 轮次数 | 按明确 turn_uid 去重；没有边界时保留未知，一轮不等于一个任务。 |
| `tool_sequence` | 调用 · 有序记录 | 按来源、会话、原生调用 ID 配对；调用加返回仍为一次调用，镜像去重，冲突保留证据。 |
| `tool_result_status / failure_reasons` | 调用 · 状态／原因 | 只消费协议状态和明确错误原因；保留 raw_status/status_scope，包装层成功不覆盖内部未知。 |
| `retry_links` | 调用对 · 关系 | 前次失败且同任务、工具和结果范围；同参数还需摘要身份一致，显式 retry_of_call_uid 可允许参数修改。 |
| `subagent_relations` | 会话／代理 · 关系 | 只接受 parent_uid 或明确 spawn/join ID；角色名不能证明父子，fork 单列。 |
| `execution_intervals / parallel_intervals` | 调用 · UTC 毫秒区间 | 仅可靠原生端点构成半开区间；相邻端点不算并行，日志差不证明实际执行区间。 |

统一输出位于 `bottleneck_features.respond`，同时提供总体、会话树和项目范围。缺失保持 `null`，候选不当确认，已知子集不等于完整总体；有效数、未知数与证据一起解释指标。

## 分析函数

| 已实现函数 | 输入 → 输出 | 主要处理 |
| --- | --- | --- |
| [`pair_tool_calls(events)`](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/calls.py) | L2 事件 → 调用、孤立返回与冲突 | 按明确身份配对，返回记录顺序必须晚于调用。 |
| [`normalize_tool_calls(calls)`](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/calls.py) | L3 记录 → 唯一调用与冲突证据 | 冲突不能贡献成功、可靠耗时或验收结论。 |
| [`analyze_execution_sequence(calls)`](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/sequence.py) | 调用 → 重试与失败证据 | 严格检查任务、工具、摘要身份及结果范围。 |
| [`build_execution_relations(events, sessions)`](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/relations.py) | 事件及会话 → 父子、汇合与分叉关系 | 显式关系优先，缺 ID 保留未决。 |
| [`execution_intervals(calls)`](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/relations.py) | 调用 → 可靠区间与并行片段 | 扫描半开区间端点，单列缺失端点。 |
| [`analyze_respond(events, calls, sessions, main_ids, …)`](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/src/tandem_backend/analytics/respond/analyzer.py) | 同范围记录 → 完整 Respond 结果 | 调用配对、统计与关系的组合入口。 |

表中 `…` 省略可选参数，完整签名以对应代码为准。函数直接调用接收同一筛选范围的记录；推荐通过 `analytics.service.analyze_bundle` 统一筛选，时间窗口为 `[from_ts, until_ts)`。

## 对接已有分析

- `features.py` 与 `sequence.py` 接管原 `tool_summary`、`workflow`，保留兼容字段；状态统一由 `result_status` 解释。
- `pair_tool_calls(events)` 根据来源、会话、原生调用 ID 配对 L2；调用与返回只算一次调用。镜像事件去重，多调用／多返回冲突、孤立返回和未配对项保留证据。返回必须位于调用之后。
- `normalize_tool_calls` 去重 L3 调用；冲突不能贡献已知成功状态、耗时或验证结果。不修改输入。
- `analyze_execution_sequence` 输出失败原因与重试关系。明确失败之后，同任务、工具、参数摘要类型与结果范围一致才确认同参数重试；显式 retry_of_call_uid 可支持修改参数后的重试。缺信息保留候选，跨任务／跨会话不猜测重试。
- `build_execution_relations` 使用 parent_uid 或明确 spawn/join 事件关联子代理；forked_from 单列，角色名不构成父子关系。回滚／重启只接受明确事件。
- `execution_intervals` 从可靠端点构建半开区间并计算同时运行片段；日志时间差不证明并行。
- `analyze_respond` 汇总调用、轮次覆盖、执行序列、关系与配对诊断；L3 缺失且 L2 有实际调用时可返回标为 partial 的配对结果；coverage.tool_calls.status=excluded 时禁止回退重建，并保留 excluded 状态。

## 输入与使用

```python
from tandem_backend.analytics.respond import analyze_respond
result = analyze_respond(events, calls, sessions, main_ids={"s"})
```

输入沿用 analysis-input-v1。L2 `call_id` 可位于事件或 attrs，工具名为 attrs.name/name_raw，分类为 attrs.category；L3 使用 call_uid。源身份可用 event.source_id，session_uid 必须稳定。错误原因仅消费明确 error_class/failure_reason，不读取 stdout 词语来判断成败。

可选扩展：task_uid、argument_digest_kind、retry_of_call_uid、child_session_uid/parent_session_uid。调用结果范围使用 status_scope；外层成功遇内部失败为失败，内部未知为未知，原始状态仍保留。设置历史截止时间时，validation_result 和 validation_report 均需在截止前可见，无时间或未来报告不返回。已知成功+失败是成功率分母，拒绝／中断／运行中／未知另列。

可靠区间要求 UTC 毫秒端点与 interval_reliable=true 或 duration_source=native_bounds。L2 配对时，调用和返回都必须明确声明可靠原生端点；不把事件写入时间冒充执行时间。Cost/Time 消费此处的区间；Outcome 消费此处的状态与证据，工具成功不等于任务成功。

旧 `workflow.confirmed_same_argument_failed_retries` 为兼容保留原邻接失败对口径；新消费者使用 `retry_links`，它额外检查任务及摘要类型。

## 验收样例

| 输入／场景 | 预期结果 |
| --- | --- |
| 一次调用有调用事件和返回事件 | 调用数仍为 1；缺返回时不自动算失败。 |
| 同工具相邻失败，但缺任务或参数摘要 | 仅保留候选，不算确认同参数重试。 |
| 外层 exec 成功，内部返回未知 | 结果保持 unknown；不能用 stdout 文案补足状态。 |
| 两个原生区间为 0–10 秒和 10–20 秒 | 没有重叠，不算并行；fork 也不算子代理 spawn。 |

自动验收：[`test_respond.py`](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/tests/bottleneck/test_respond.py)；跨模块范围、未来信息隔离和 CLI/API 一致性见 [test_integration.py](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/3cdebe6ec9951bab4d5138f51e17867675334bfd/tests/bottleneck/test_integration.py)。全部使用合成事件、虚构数据或临时 SQLite，不读取个人 Agent 历史。

```bash
python -m pytest -q tests/bottleneck/test_respond.py tests/bottleneck/test_integration.py
ruff check src tests
```

2026-10-02 技术复核：目录拆分后 467 项测试通过；同步 main 的全部已合入特征族、保留并行共存回归并修复四项 P1 后，在隔离提交副本中 775 项测试通过，Ruff 通过。此次文件拆分的 30 个函数逐一比对语法树，93 条全局字段定义保持一致。

## 补充特征与函数

待补充：各 Agent 导入器保留原生错误分类、任务 ID、摘要类型、spawn/join 和可靠时钟；流式多段返回需要独立协议适配，当前多返回保守标冲突；超大调用序列可按需分页。没有端点或明确错误原因时继续保留未知，不由结果文案或角色名推断。

新增内容先更新 Feature TODO、字段表和函数表，再补字段类型／单位、输入证据、分母与缺失语义、正反例、认领 GitHub 账号、[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4) 及实现链接；验收后再勾选，进度以 Issue 为准。

## 讨论

各 Agent 的原生错误、调用 ID、摘要类型和可靠端点需要适配器保留。PR #13 的任务映射目前仅涵盖真人消息，执行事件与子代理仍需显式关联；不能直接用它的 task_id 替代原生日志 task_uid。

## 结论与下一步

当前已完成模块拆分、统一入口接入和合成样例检查；接下来由团队确认口径，并让上游适配器补齐本页注明的证据。业务口径确认人：待确认；本次实现认领：[genius-FXC](https://github.com/genius-FXC)。四目录重构已由 yhyfhgs 通过 [PR #19](https://github.com/Orbit-Labs-AI/Orbit-Source/pull/19) 合并；合并发生在最后两项 P1 修复推送前，补充修复在 `fix/genius-FXC-bottleneck-coverage` 提交 PR。按约定仅 P0/P1 阻塞，低优先级问题可后续处理。

补充验证（main `4bccf1f` 基线）：Python 3.13 隔离副本中 789 项后端测试、91 项数据层测试通过；35 项连接器构造测试、Ruff、格式检查和全包构建通过；synthetic demo 与 evaluate 通过。没有读取个人 Agent 历史。

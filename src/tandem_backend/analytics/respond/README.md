# Respond：回应与执行

负责人：genius-FXC。范围：非语义 × bottleneck；实现口径依据团队 Respond 草案，暂不扩展 Task/Instruction 的语义处理。

## 已完成

- `analyzer.py` 接管原 `tool_summary`、`workflow`，保留兼容字段；状态统一由 `result_status` 解释。
- `pair_tool_calls(events)` 根据来源、会话、原生调用 ID 配对 L2；调用与返回只算一次调用。镜像事件去重，多调用／多返回冲突、孤立返回和未配对项保留证据。返回必须位于调用之后。
- `normalize_tool_calls` 去重 L3 调用；冲突不能贡献已知成功状态、耗时或验证结果。不修改输入。
- `analyze_execution_sequence` 输出失败原因与重试关系。明确失败之后，同任务、工具、参数摘要类型与结果范围一致才确认同参数重试；显式 retry_of_call_uid 可支持修改参数后的重试。缺信息保留候选，跨任务／跨会话不猜测重试。
- `build_execution_relations` 使用 parent_uid 或明确 spawn/join 事件关联子代理；forked_from 单列，角色名不构成父子关系。回滚／重启只接受明确事件。
- `execution_intervals` 从可靠端点构建半开区间并计算同时运行片段；日志时间差不证明并行。
- `analyze_respond` 汇总调用、轮次覆盖、执行序列、关系与配对诊断；L3 缺失且 L2 有实际调用时可返回标为 partial 的配对结果。

## 输入与输出约定

```python
from tandem_backend.analytics.respond import analyze_respond
result = analyze_respond(events, calls, sessions, main_ids={"s"})
```

输入沿用 analysis-input-v1。L2 `call_id` 可位于事件或 attrs，工具名为 attrs.name/name_raw，分类为 attrs.category；L3 使用 call_uid。源身份可用 event.source_id，session_uid 必须稳定。错误原因仅消费明确 error_class/failure_reason，不读取 stdout 词语来判断成败。

可选扩展：task_uid、argument_digest_kind、retry_of_call_uid、child_session_uid/parent_session_uid。调用结果范围使用 status_scope；外层成功遇内部失败为失败，内部未知为未知，原始状态仍保留。已知成功+失败是成功率分母，拒绝／中断／运行中／未知另列。

可靠区间要求 UTC 毫秒端点与 interval_reliable=true 或 duration_source=native_bounds。L2 配对时，调用和返回都必须明确声明可靠原生端点；不把事件写入时间冒充执行时间。Cost/Time 消费此处的区间；Outcome 消费此处的状态与证据，工具成功不等于任务成功。

旧 `workflow.confirmed_same_argument_failed_retries` 为兼容保留原邻接失败对口径；新消费者使用 `retry_links`，它额外检查任务及摘要类型。

## 验收与后续

合成用例：`tests/bottleneck/test_respond.py`，覆盖来源／会话隔离、乱序时钟、缺 ID、重复及冲突返回、包装结果、重试对象、原生重叠区间、子代理／分叉边界。运行：`pytest -q tests/bottleneck/test_respond.py`。

待补充：各 Agent 导入器保留原生错误分类、任务 ID、摘要类型、spawn/join 和可靠时钟；流式多段返回需要独立协议适配，当前多返回保守标冲突；超大调用序列可按需分页。没有端点或明确错误原因时继续保留未知，不由结果文案或角色名推断。

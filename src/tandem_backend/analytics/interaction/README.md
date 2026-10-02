# Interaction：交互行为

负责人：genius-FXC。范围：非语义 × bottleneck。依据团队《分析模块分类》及《Interaction 交互行为》草案；以下是代码实现口径，尚不代表团队确认标签词表。

## 已完成

- `analyzer.py`：`classify_message_intents` 消费有来源的确认标注；原 `correction_terms` 仍只提供关键词候选，不自动确认语义。
- `locate_interventions` 按记录顺序关联前后执行步骤；有任务 ID 时不跨任务，无任务 ID 时明确标为 session_only。
- `summarize_interactions`：同消息多标签只计一次；纠偏率分母是同范围内真人来源和意图均已确认的消息。零分母为 null。
- 同任务、同对象和同要求的后续消息计重复强调；未知对象不靠文本相似度猜测。
- 摩擦支持 understanding/scope/execution/verification 多标签，保留证据和未知数。
- `analyze_interaction` 提供统一入口、数据覆盖及来源未知计数；不修改输入。

## 输入与使用

```python
from tandem_backend.analytics.interaction import analyze_interaction
result = analyze_interaction(events, main_ids={"s"}, until_ts=None)
```

输入沿用 analysis-input-v1 事件。可选 `attrs.interaction` 为上游标注扩展：

```json
{"state":"confirmed","source":"reviewer-or-labeler-version","available_at":200,
 "intents":["correction","feedback"],"target_event_uid":"previous-answer",
 "friction_types":["scope"],
 "requirements":[{"object_uid":"export","requirement_uid":"csv"}]}
```

- intents 允许 request/clarification/correction/feedback/other；一条消息可多意图。仅确认主会话中的真人消息参与统计。
- 纠偏对象必须是同会话、同明确任务中先前的事件；任务字段支持 `task_uid` 和旧 `attrs.task_id`。跨会话对象目前保留未知。
- `available_at` 是标注可见的 UTC 毫秒，不是原消息时间；设置 until_ts 时，缺时间或晚于截止时间的标注均不使用。
- 未提供 requirements/friction_types 为未知；显式空列表表示已检查且没有。
- 顶层分析范围由 service 统一筛选；直接调用者须传入同一范围内事件。原始文本不会出现在本模块输出。

## 验收与后续

合成样例位于 `tests/bottleneck/test_interaction.py`：新增需求与纠偏候选、确认分母、多意图去重、对象与任务边界、重复强调、逆序时钟、来源排除、未来标注隔离。命令：`pytest -q tests/bottleneck/test_interaction.py`。

待补充：团队确认意图／摩擦词表与上游标注来源；人工或独立语义模块产出已审标注；跨会话任务和要求 ID；标注版本冲突处理。当前不实现情绪、人格、满意度或语义自动分类，旧日志没有这些标注时正常返回未知。

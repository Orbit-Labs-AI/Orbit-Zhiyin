---
created: 2026-10-02
added: 2026-10-02
---

# Interaction 交互行为

## Feature TODO

- [ ] **消息意图 `message_intents`**：[实现](features.py)；代码与合成样例已完成，待团队验收。
- [ ] **人工介入位置 `intervention_points`**：[实现](features.py)；代码与合成样例已完成，待团队验收。
- [ ] **确认纠偏次数 `confirmed_correction_count`**：[实现](features.py)；代码与合成样例已完成，待团队验收。
- [ ] **确认纠偏比例 `confirmed_correction_rate`**：[实现](features.py)；代码与合成样例已完成，待团队验收。
- [ ] **重复强调 `repeated_requirement_count`**：[实现](features.py)；代码与合成样例已完成，待团队验收。
- [ ] **摩擦类型 `friction_types`**：[实现](features.py)；代码与合成样例已完成，待团队验收。

认领：[genius-FXC](https://github.com/genius-FXC)；关联 Issue：[#4](https://github.com/ActionMesh-AI/Hackathon/issues/4)。实现与合成样例的技术检查已完成；勾选需按团队模板完成最终口径确认和验收，本页不代替成员确认。未来补充项见末尾。

[四模块总览](../../../../../../docs/modules/analytics/bottleneck-features.md) · [合成测试](../../../../tests/bottleneck/test_interaction.py) · [共享虚构数据集](../../../../tests/fixtures/bottleneck-features-v1.json)

## 范围

非语义 × bottleneck。描述真人何时介入以及已确认介入标签的分布；消费上游确认标注，关键词只作候选。新增需求、正常澄清与纠偏分别处理，不推断情绪、人格或主观接受。

## 目录与职责

| 文件 | 职责 |
| --- | --- |
| [__init__.py](__init__.py) | 稳定的特征族公共导出 |
| [analyzer.py](analyzer.py) | 组合入口及兼容导出，不集中实现所有分析 |
| [rules.py](rules.py) | 意图／摩擦词表、执行事件类型、纠偏关键词候选 |
| [features.py](features.py) | 确认标注校验、介入定位、纠偏与重复要求汇总 |
| [dictionary.py](dictionary.py) | 本特征族的机器可读字段口径 |

沿用 PR #13 的特征族目录和规则／提取／字段字典分工。`analyzer.py` 只做组合，旧 `analytics.features` 和本目录公共导出继续兼容；没有新增 Agent、模型调用或语义分类器。

## 特征口径

| 字段（相对本模块输出） | 粒度／类型 | 定义与提取规则 |
| --- | --- | --- |
| `message_intents` | 真人消息 · 多标签及证据 | 仅确认主会话中的真人正文；有效且可见的 attrs.interaction 标注才为 confirmed，候选不进入确认分母。 |
| `intervention_points` | 真人消息 · 事件关系 | 按 seq 关联前后执行步骤；明确任务时不跨任务，无任务 ID 时标明 session_only。 |
| `confirmed_correction_count` | 所选范围 · 消息数 | 同消息多纠偏标签只计一次；对象必须是同会话、同明确任务中的先前事件。没有可判定意图时为 null。 |
| `confirmed_correction_rate` | 所选范围 · 比例 | 确认纠偏消息数 ÷ 真人来源和意图均可判定的消息数；零分母为 null，并输出有效数和未知数。 |
| `repeated_requirement_count` | 所选范围 · 消息数 | 同会话、任务、对象和要求 ID 的首次要求之后，按消息计数；对象不明保持未知。 |
| `friction_types` | 所选范围 · 多标签计数 | 消费有有效纠偏对象的 understanding/scope/execution/verification 标签；缺标注与显式空列表分别处理。 |

统一输出位于 `bottleneck_features.interaction`，同时提供总体、会话树和项目范围。缺失保持 `null`，候选不当确认，已知子集不等于完整总体；有效数、未知数与证据一起解释指标。

## 分析函数

| 已实现函数 | 输入 → 输出 | 主要处理 |
| --- | --- | --- |
| [`classify_message_intents(events, main_ids, until_ts=None)`](features.py) | 事件 → 标注消息、候选、确认状态及证据 | 校验来源、标签、可见时间和被纠正对象。 |
| [`locate_interventions(events, main_ids)`](features.py) | 有序事件 → 介入位置 | 记录顺序优先，保留任务／会话关系范围。 |
| [`summarize_interactions(labeled_messages)`](features.py) | 标注消息 → 纠偏、重复强调和摩擦汇总 | 去重；统一确认分母；输出有效数和未知数。 |
| [`analyze_interaction(events, main_ids, …)`](analyzer.py) | 已筛选事件 → 完整 Interaction 结果 | 统一入口，保留事件和来源覆盖。 |

表中 `…` 省略可选参数，完整签名以对应代码为准。函数直接调用接收同一筛选范围的记录；推荐通过 `analytics.service.analyze_bundle` 统一筛选，时间窗口为 `[from_ts, until_ts)`。

## 对接已有分析

- `features.py`：`classify_message_intents` 消费有来源的确认标注；原 `correction_terms` 仍只提供关键词候选，不自动确认语义。
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


## 验收样例

| 输入／场景 | 预期结果 |
| --- | --- |
| 不对，我要的是 A | 只有关键词时保留候选；有确认标注及同任务先前对象时计一条纠偏。 |
| 再加一个导出按钮 | 新增需求不自动算纠偏。 |
| 两条已审消息，其中一条含 correction 和 feedback | 纠偏次数 1、比例 0.5；同消息不重复计数。 |
| 没有可判定意图或标注晚于截止时间 | 纠偏比例 null，并报告未知数。 |

自动验收：[`test_interaction.py`](../../../../tests/bottleneck/test_interaction.py)；跨模块范围、未来信息隔离和 CLI/API 一致性见 [test_integration.py](../../../../tests/bottleneck/test_integration.py)。全部使用合成事件、虚构数据或临时 SQLite，不读取个人 Agent 历史。

```bash
uv run python -m pytest -q packages/backend/tests/bottleneck/test_interaction.py packages/backend/tests/bottleneck/test_integration.py
uv run ruff check packages/backend/src packages/backend/tests packages/data/src packages/data/tests tests
```

2026-10-02 技术复核：目录拆分后 467 项测试通过；同步 main 的 Instruction 与连接器并修复两项 P1 后，在隔离提交副本中 564 项测试通过，Ruff 通过。此次文件拆分的 30 个函数逐一比对语法树，93 条全局字段定义保持一致；这是自动技术验证，不是团队人工验收。

## 补充特征与函数

待补充：团队确认意图／摩擦词表与上游标注来源；人工或独立语义模块产出已审标注；跨会话任务和要求 ID；标注版本冲突处理。当前不实现情绪、人格、满意度或语义自动分类，旧日志没有这些标注时正常返回未知。

新增内容先更新 Feature TODO、字段表和函数表，再补字段类型／单位、输入证据、分母与缺失语义、正反例、认领 GitHub 账号、[#4](https://github.com/ActionMesh-AI/Hackathon/issues/4) 及实现链接；验收后再勾选，进度以 Issue 为准。

## 讨论

意图／摩擦词表及标注来源待团队确认；PR #13 的 Preference/Task 不生成 attrs.interaction。Task 的候选边界不能自动当作已确认的纠偏对象或要求身份。

## 结论与下一步

当前已完成模块拆分、统一入口接入和合成样例检查；接下来由团队确认口径，并让上游适配器补齐本页注明的证据。业务口径确认人：待确认；本次实现认领：[genius-FXC](https://github.com/genius-FXC)。审查按当前约定以 P0/P1 为阻塞，低优先级问题可后续处理；提交 PR 不代表已合并 main。

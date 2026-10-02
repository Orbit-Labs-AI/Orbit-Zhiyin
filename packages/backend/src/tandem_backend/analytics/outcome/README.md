---
created: 2026-10-02
added: 2026-10-02
---

# Outcome 客观结果

## Feature TODO

- [ ] **验证记录 `validation_runs`**：[实现](validation.py)；代码与合成样例已完成，待团队验收。
- [ ] **验证结果 `validation_runs[*].validation_result`**：[实现](validation.py)；代码与合成样例已完成，待团队验收。
- [ ] **逐项验收 `acceptance_results`**：[实现](acceptance.py)；代码与合成样例已完成，待团队验收。
- [ ] **验证范围 `validation_runs[*].validation_scope`**：[实现](rules.py)；代码与合成样例已完成，待团队验收。
- [ ] **结果证据 `validation_runs[*].validation_evidence`**：[实现](validation.py)；代码与合成样例已完成，待团队验收。

认领：[genius-FXC](https://github.com/genius-FXC)；关联 Issue：[#4](https://github.com/ActionMesh-AI/Hackathon/issues/4)。实现与合成样例的技术检查已完成；勾选需按团队模板完成最终口径确认和验收，本页不代替成员确认。未来补充项见末尾。

[四模块总览](../../../../../../docs/modules/analytics/bottleneck-features.md) · [合成测试](../../../../tests/bottleneck/test_outcome.py) · [共享虚构数据集](../../../../tests/fixtures/bottleneck-features-v1.json)

## 范围

非语义 × bottleneck。描述明确检查证据支持的客观结果；测试／构建通过与用户接受分开。验收条件来自上游 Instruction 的确认标注，调用证据来自 Respond；缺依据时不生成任务成功结论。

## 目录与职责

| 文件 | 职责 |
| --- | --- |
| [__init__.py](__init__.py) | 稳定的特征族公共导出 |
| [analyzer.py](analyzer.py) | 组合入口及兼容导出，不集中实现所有分析 |
| [rules.py](rules.py) | 验证类别、完整直接命令识别、版本与覆盖范围比较 |
| [validation.py](validation.py) | 实际检查、调用／报告结果和旧候选字段 |
| [acceptance.py](acceptance.py) | 消费确认条件、逐项匹配、完整验收集合汇总 |
| [dictionary.py](dictionary.py) | 本特征族的机器可读字段口径 |

沿用 PR #13 的特征族目录和规则／提取／字段字典分工。`analyzer.py` 只做组合，旧 `analytics.features` 和本目录公共导出继续兼容；没有新增 Agent、模型调用或语义分类器。

## 特征口径

| 字段（相对本模块输出） | 粒度／类型 | 定义与提取规则 |
| --- | --- | --- |
| `validation_runs` | 实际检查 · 记录列表 | 有来源且 executed=true 的元数据，或完整直接检查命令加命令级返回；提及、干跑和拒绝执行不算实际验证。 |
| `validation_runs[*].validation_result` | 检查 · 通过／失败／中断／未知 | 直接命令结果或匹配内部报告才能支持结论；包装层成功不证明内部通过。 |
| `acceptance_results` | 验收项 · 状态及证据 | 按验收项 ID、任务、会话树、种类、对象版本与覆盖匹配；缺依据保留未知。 |
| `validation_runs[*].validation_scope` | 检查 · 覆盖范围 | 要求项目、产物、修订和 full/subset；subset 还须 files/test_ids，不跨版本或向全量外推。 |
| `validation_runs[*].validation_evidence` | 检查／验收项 · 引用 | 保留调用、报告和修订；按结果可见时间或同一会话的返回顺序选择证据，不按调用开始时间。 |

统一输出位于 `bottleneck_features.outcome`，同时提供总体、会话树和项目范围。缺失保持 `null`，候选不当确认，已知子集不等于完整总体；有效数、未知数与证据一起解释指标。

## 分析函数

| 已实现函数 | 输入 → 输出 | 主要处理 |
| --- | --- | --- |
| [`extract_validation_runs(calls, until_ts=None)`](validation.py) | 规范调用 → 已执行检查、候选及结果 | 识别执行证据、状态范围和后补报告可见时间。 |
| [`collect_acceptance_criteria(events, main_ids, until_ts=None)`](acceptance.py) | 真人事件 → 确认验收条件 | 消费 attrs.acceptance，不从目标文本补造验收标准。 |
| [`match_acceptance_criteria(criteria, validations)`](acceptance.py) | 条件／检查 → 逐项状态及缺失原因 | 精确匹配任务、对象、版本、覆盖和证据新旧关系。 |
| [`summarize_objective_outcomes(results)`](acceptance.py) | 逐项结果 → 状态计数及 task_results | 只有明确完整条件集合才能判断对应 task_success；未知不算通过。 |
| [`analyze_outcome(calls, events, main_ids, …)`](analyzer.py) | 同范围记录 → 完整 Outcome 结果 | 组合检查、验收匹配与覆盖。 |

表中 `…` 省略可选参数，完整签名以对应代码为准。函数直接调用接收同一筛选范围的记录；推荐通过 `analytics.service.analyze_bundle` 统一筛选，时间窗口为 `[from_ts, until_ts)`。

## 对接已有分析

- `validation.py`：`extract_validation_runs` 分离实际验证与命令候选，保留 test/build/check/lint/typecheck 的结果和证据。
- 有来源且 executed=true 的验证元数据可以识别检查；完整的直接 pytest/ruff/mypy/tsc/cargo/go 检查命令也可识别，但不会猜测其验收项或覆盖版本。仅 command_head、不完整命令、帮助／收集／列表模式、复合命令和被拒绝执行的请求不算已执行验证。
- 命令级协议返回支持通过／失败／中断／未知。包装层成功不能证明内部通过；内部报告须有匹配调用 ID、报告 ID、对象范围和可见时间。
- `collect_acceptance_criteria` 消费上游 Instruction 的确认标签；`match_acceptance_criteria` 按验收项 ID、任务、会话树、检查类别、对象版本及覆盖范围匹配。
- 局部范围不扩展到全量，v1 不证明 v2。重复检查按结果可见时间／结果记录顺序更新，不能按调用开始顺序挑选较新的结论；无法比较且互相矛盾时保留未知；不同会话的局部 result_seq 不能用于相互排序。
- `summarize_objective_outcomes` 仅在明确且完整的验收集合下计算对应 task_success；无条件、集合不完整、多集合汇总或有未验证项时不声称全部成功。某项明确失败可以证明该完整集合没有全部通过。


## 输入与使用

```python
from tandem_backend.analytics.outcome import analyze_outcome
result = analyze_outcome(calls, events, main_ids={"s"})
```

调用的可选 `validation` 扩展（也可由 L2 调用 attrs 传入）：

```json
{"kind":"test","executed":true,"source":"check-adapter-v1","available_at":100,
 "check_name":"unit-tests","criterion_uids":["unit"],
 "scope":{"project_id":"p","artifact_uid":"app","artifact_revision":"v1","coverage":"full"}}
```

真人事件 `attrs.acceptance` 接收已确认验收集合，任务来自同事件 task_uid/attrs.task_id：

```json
{"state":"confirmed","source":"instruction-labels-v1","available_at":50,
 "criteria_set_uid":"release-v1","complete":true,
 "scope":{"project_id":"p","artifact_uid":"app","artifact_revision":"v1","coverage":"full"},
 "criteria":[{"criterion_uid":"unit","kind":"test"},{"criterion_uid":"build","kind":"build"}]}
```

`coverage=subset` 时还须提供 files 或 test_ids。范围严格匹配，缺 project_id、artifact_uid、artifact_revision 或覆盖依据时不确认验收。一个新版本应更新范围和验收集合；相同集合后续明确修订覆盖前一份条件，历史验证记录保留。

可选 `validation_result` 报告须包含 status、source、report_uid、call_uid、scope、available_at。所有时间均为 UTC 毫秒。设置截止时间时，缺少可见时间的后补标注／结果不用于历史结论；原始状态与未知原因保留。直接调用者负责传入筛选后的同范围记录。


## 验收样例

| 输入／场景 | 预期结果 |
| --- | --- |
| 测试通过、构建未执行 | 测试项通过、构建项未知；task_success 为 null。 |
| 外层脚本退出码 0，内部无匹配报告 | 不能补造内部测试通过。 |
| v1 已通过，当前验收要求 v2 或更大范围 | 旧验证保留；当前验收仍未知。 |
| 明确完整验收集合全部通过 | 只对该集合返回 task_success=true；无集合时仍为 null。 |

自动验收：[`test_outcome.py`](../../../../tests/bottleneck/test_outcome.py)；跨模块范围、未来信息隔离和 CLI/API 一致性见 [test_integration.py](../../../../tests/bottleneck/test_integration.py)。全部使用合成事件、虚构数据或临时 SQLite，不读取个人 Agent 历史。

```bash
uv run python -m pytest -q packages/backend/tests/bottleneck/test_outcome.py packages/backend/tests/bottleneck/test_integration.py
uv run ruff check packages/backend/src packages/backend/tests packages/data/src packages/data/tests tests
```

2026-10-02 技术复核：目录拆分后 467 项测试通过；同步 main 的 Instruction 与连接器并修复两项 P1 后，在隔离提交副本中 564 项测试通过，Ruff 通过。此次文件拆分的 30 个函数逐一比对语法树，93 条全局字段定义保持一致；这是自动技术验证，不是团队人工验收。

## 补充特征与函数

待补充：各 Agent 的检查报告适配；Instruction 产出的规范验收 ID；产物修订追踪；人工明确验收的独立来源协议；复合命令的逐内部调用结果。旧导入器通常缺检查身份、版本和验收标注，所以输出候选／未知是预期行为，不能凭工具退出码补造任务成功。

旧 `objective_outcomes` 候选字段通过 `legacy_objective_candidates` 保留兼容；新消费者应使用 `bottleneck_features.outcome`。

新增内容先更新 Feature TODO、字段表和函数表，再补字段类型／单位、输入证据、分母与缺失语义、正反例、认领 GitHub 账号、[#4](https://github.com/ActionMesh-AI/Hackathon/issues/4) 及实现链接；验收后再勾选，进度以 Issue 为准。

## 讨论

PR #13 的 task_goal/expected_artifacts 是任务描述与预期产物，不等同已确认验收条件或实际产物版本。main 已有的 Instruction 目前提供词面要求和原话，不生成这里需要的确认验收集合、检查 ID 和产物版本。本模块仍需规范化的验收映射、检查适配器和产物修订证据。新增跨模块回归验证：识别到验收标准文本且两个检查通过，没有明确集合时任务成功仍为 null。

## 结论与下一步

当前已完成模块拆分、统一入口接入和合成样例检查；接下来由团队确认口径，并让上游适配器补齐本页注明的证据。业务口径确认人：待确认；本次实现认领：[genius-FXC](https://github.com/genius-FXC)。审查按当前约定以 P0/P1 为阻塞，低优先级问题可后续处理；提交 PR 不代表已合并 main。

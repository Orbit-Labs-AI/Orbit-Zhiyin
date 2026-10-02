# Outcome：客观结果

负责人：genius-FXC。只处理非语义 × bottleneck 的客观结果；用户接受／拒收和满意度属于主观 Outcome，不迁入这里。

## 已完成

- `analyzer.py`：`extract_validation_runs` 分离实际验证与命令候选，保留 test/build/check/lint/typecheck 的结果和证据。
- 有来源且 executed=true 的验证元数据可以识别检查；完整的直接 pytest/ruff/mypy/tsc/cargo/go 检查命令也可识别，但不会猜测其验收项或覆盖版本。仅 command_head、不完整命令、帮助／收集／列表模式、复合命令和被拒绝执行的请求不算已执行验证。
- 命令级协议返回支持通过／失败／中断／未知。包装层成功不能证明内部通过；内部报告须有匹配调用 ID、报告 ID、对象范围和可见时间。
- `collect_acceptance_criteria` 消费上游 Instruction 的确认标签；`match_acceptance_criteria` 按验收项 ID、任务、会话树、检查类别、对象版本及覆盖范围匹配。
- 局部范围不扩展到全量，v1 不证明 v2。重复检查按结果可见时间／结果记录顺序更新，不能按调用开始顺序挑选较新的结论；无法比较且互相矛盾时保留未知。
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

## 验收与后续

合成样例：`tests/bottleneck/test_outcome.py`，覆盖测试通过但构建未知、完整验收集合、包装层结果、版本／子集失配、命令提及和干跑、未来信息、结果顺序、子代理归属与拒绝执行。运行：`pytest -q tests/bottleneck/test_outcome.py`。

待补充：各 Agent 的检查报告适配；Instruction 产出的规范验收 ID；产物修订追踪；人工明确验收的独立来源协议；复合命令的逐内部调用结果。旧导入器通常缺检查身份、版本和验收标注，所以输出候选／未知是预期行为，不能凭工具退出码补造任务成功。

旧 `objective_outcomes` 候选字段通过 `legacy_objective_candidates` 保留兼容；新消费者应使用 `bottleneck_features.outcome`。

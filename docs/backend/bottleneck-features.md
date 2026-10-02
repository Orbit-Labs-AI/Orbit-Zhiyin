# 非语义 × Bottleneck 特征重构

基于 main `c97c818`，个人分支 `refactor/genius-FXC-bottleneck`。依据团队《分析模块分类》以及四份开发草案，聚焦交互、执行、用量／时间、客观结果，不扩展人格、情绪或主观满意度。

## main 的结构与本次调整

原有链路为 Codex 导入 → 隐私清理与统一事件 → SQLite → CLI/API。画像、瓶颈诊断、资源建议是一条既有分析链；`analytics` 是独立的测量链，接收 analysis-input-v1 或只读适配旧数据库，输出覆盖情况、特征和文本表示。

本次拆分原来集中于 `analytics/features.py` 的测量，保留旧导入及字段含义。未属于本象限的 prompt 结构、语言信号和主观反馈候选仍留在兼容层，避免误归入客观 Outcome。新的四组特征由 `analytics/bottleneck.py` 编排，统一经过 `inputs.select` 的项目、时间、模型、会话树及排除筛选。

## 模块与交付位置

| 模块 | 主要工作文件与进度文档 | 输出重点 |
| --- | --- | --- |
| Interaction | [analyzer.py](../../src/tandem_backend/analytics/interaction/analyzer.py)、[README](../../src/tandem_backend/analytics/interaction/README.md) | 意图标注、介入位置、确认纠偏、重复要求、摩擦 |
| Respond | [analyzer.py](../../src/tandem_backend/analytics/respond/analyzer.py)、[README](../../src/tandem_backend/analytics/respond/README.md) | 调用配对、状态与失败原因、重试、子代理、执行区间 |
| Cost / Time | [analyzer.py](../../src/tandem_backend/analytics/cost_time/analyzer.py)、[README](../../src/tandem_backend/analytics/cost_time/README.md) | 请求 Token、缓存包含关系、耗时／区间并集、跨度、活动分布 |
| Outcome | [analyzer.py](../../src/tandem_backend/analytics/outcome/analyzer.py)、[README](../../src/tandem_backend/analytics/outcome/README.md) | 实际验证、结果证据、逐项验收、版本和覆盖范围 |

每个 README 包含已完成内容、接口／扩展字段、验收方法与未来待补工作。测试位于 `tests/bottleneck/`，共享数据集为 [bottleneck-features-v1.json](../../tests/fixtures/bottleneck-features-v1.json)，全部为人工构造的虚构记录。

## 使用

```python
import json
from pathlib import Path
from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.service import analyze_bundle

raw = json.loads(Path("tests/fixtures/bottleneck-features-v1.json").read_text())
result = analyze_bundle(AnalysisInputBundle.from_dict(raw), Scope(**raw["scope"]), with_text=False)
families = result["bottleneck_features"]
print(families["interaction"]["confirmed_correction_rate"])
print(families["outcome"]["acceptance_results"])
```

统一 JSON 的 `bottleneck_features` 包含 interaction/respond/cost_time/outcome；`sessions[*]` 和 `projects[*]` 也含相同结构，使用各自成员范围。`GET /v1/analytics/bottleneck` 返回总体四组结果及原有 scope/coverage/digest 等元数据；会话详情 API 可查看单会话树。`tandem analytics --output ...` 自动包含新结构，无需新 CLI。

版本为 `feature-analytics-v2`，四组输出子契约为 `bottleneck-features-v1`。旧导入位置和字段仍可使用；新 benchmark 应读取新分组。v2 还修正重复调用计数、模型活动误计累计记录、会话缺开始时间时错误补造开始、非法 Token／时延和缓存重复计量。机器可读定义在 `analytics/dictionary.py`。

## 口径与依赖

- Interaction 的确定性处理负责消费确认标注和统计；关键词只是候选。没有上游意图标注就返回未知，不假装已完成语义确认。
- Respond 提供执行证据，Cost/Time 消费区间，Outcome 消费调用结果。一个工具成功并不自动证明任务完成。
- Outcome 的条件来自明确的 Instruction 标注；没有验收项、产物版本或覆盖依据时保持未知。task_success 只描述指定完整验收集合。
- 日志时间差、可靠执行时间、会话跨度分开；不计算真实人工投入。费用相关旧字段兼容保留，不扩展费用分析。
- 缺失不是零，已知子集不是完整总体，比例分母为零返回 null。来源覆盖、有效数、未知数、证据 ID 与标注／结果可见时间共同解释数值。
- 时间范围是 `[from_ts, until_ts)`。未来结果及后补标注不会进入早期快照；没有标注可见时间时，有限截止范围保守排除。时间窗口之外的验收条件／纠偏对象目前不自动补入，可能降低覆盖率。
- 各模块直接函数处理已选择的同范围记录；推荐统一使用 analyze_bundle。所有计算只读，不执行日志中的命令，不调用模型或联网服务。

## 当前数据缺口

代码能力与数据覆盖是两件事。旧 SQLite 适配器尚不提供可靠逐模型请求、完整检查命令、产物版本、完整子代理树及确认意图／验收条件。新模块已可消费这些可选扩展，但旧日志会相应返回候选或未知；不修改旧隐私规则来恢复被丢弃的内容。

后续工作是让各 Agent 导入器与 Instruction/Task/标注模块提供这些字段，并由团队确认意图词表、摩擦词表和验收映射。需要新来源适配时，应继续使用脱敏或合成样本。当前未对个人电脑的 Agent 历史执行端到端导入／测试。

## 验证与审查

```bash
ruff check src tests
pytest -q
tandem demo --output /tmp/tandem-synthetic-demo
tandem evaluate --output /tmp/tandem-synthetic-evaluation.json
```

最后两条只生成仓库自带的虚构数据；本次实际运行使用独立临时目录。逐模块用例验证文档正反例，集成用例验证共同筛选、子代理排除、未来证据隔离、输入不变、重复去重及 CLI/API 一致性。

自查已修正：外层成功误充内部检查结果；验收可见时间早于条件确认；未来标注通过 L2 回退输出泄露；未知会话身份误记零；重复调用在旧字段与新分组统计不一致；同名快照跨会话覆盖。未合并 main，后续按仓库既有 Codex review 与负责人审批流程处理。

本轮验收记录（2026-10-02）：

- main 基线 398 项测试通过；重构后 467 项通过，新增 69 项。Ruff 与 `git diff --check` 通过。
- 隔离临时目录中的 synthetic demo 通过；evaluate 的 readability 8/8、pipeline 34/34、probe 12/12，history_updated=false。
- 四模块合成数据：确认纠偏率 0.5，工具调用 2 次，Token 350；执行耗时总和 20,000 ms、并集 15,000 ms；显式完整验收集合通过。排除子代理后，构建验收回到未知。
- 可在本地 `.local/bottleneck-fixture-result.json` 查看该虚构样本的完整结果；生成物不进入 Git。
- 审查按用户本轮要求，仅将 P0/P1 作为阻断项；其他问题可记录为后续工作，后续合并沿用同一优先级标准。本轮是本地逐模块自查，不冒充 PR 的 Codex review。测试中已有一条 Starlette/AnyIO 弃用提示，不影响通过，未扩大依赖升级范围。

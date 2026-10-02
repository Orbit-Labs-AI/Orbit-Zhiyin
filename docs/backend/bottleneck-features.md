# 非语义 × Bottleneck 特征重构

最初基于 main `c97c818`，四目录重构在个人分支 `refactor/genius-FXC-bottleneck` 实现，已由 yhyfhgs 通过 [PR #19](https://github.com/ActionMesh-AI/Hackathon/pull/19) 合并为 `d15f054`。合并后两项尚未进入 main 的 P1 修复在 `fix/genius-FXC-bottleneck-coverage` 补充提交，基于 main `4bccf1f`，保留统一数据层及 Preference、Task、Instruction、主观 Outcome。范围仍为四个非语义瓶颈特征族，不扩展人格或情绪分析。

## main 的结构与本次调整

原有链路为 Codex 导入 → 隐私清理与统一事件 → SQLite → CLI/API。画像、瓶颈诊断、资源建议是一条既有分析链；`analytics` 是独立的测量链，接收 analysis-input-v1 或只读适配旧数据库，输出覆盖情况、特征和文本表示。

本次拆分原来集中于 `analytics/features.py` 的测量，保留旧导入及字段含义。prompt 结构沿用 main 的 Instruction 实现和输入校验；主观反馈沿用 main 的 `outcome_subjective`，客观验证独立放在 `outcome`。新的四组特征由 `analytics/bottleneck.py` 编排，统一经过 `inputs.select` 的项目、时间、模型、会话树及排除筛选。

## 模块与交付位置

| 模块 | 主要工作文件与进度文档 | 输出重点 |
| --- | --- | --- |
| Interaction | [features.py](../../src/tandem_backend/analytics/interaction/features.py)、rules.py、[README](../../src/tandem_backend/analytics/interaction/README.md) | 意图标注、介入位置、确认纠偏、重复要求、摩擦 |
| Respond | [calls.py](../../src/tandem_backend/analytics/respond/calls.py)、sequence.py、relations.py、features.py、rules.py、[README](../../src/tandem_backend/analytics/respond/README.md) | 调用配对、状态与失败原因、重试、子代理、执行区间 |
| Cost / Time | [tokens.py](../../src/tandem_backend/analytics/cost_time/tokens.py)、features.py、durations.py、activity.py、[README](../../src/tandem_backend/analytics/cost_time/README.md) | 请求 Token、缓存包含关系、耗时／区间并集、跨度、活动分布 |
| Outcome | [validation.py](../../src/tandem_backend/analytics/outcome/validation.py)、acceptance.py、rules.py、[README](../../src/tandem_backend/analytics/outcome/README.md) | 实际验证、结果证据、逐项验收、版本和覆盖范围 |

每个目录另有 `__init__.py` 稳定导出、`analyzer.py` 组合入口与 `dictionary.py` 字段口径；`analyzer.py` 保留此前的公开函数导入。共享字典只汇集各族定义，不再维护四族的规则实现。

每个 README 仿照团队 Interaction 模板，包含 Feature TODO、范围、目录职责、字段表、真实函数表、已有分析对接、输入示例、验收正反例、讨论与下一步。代码与合成样例的技术验收和待团队确认的业务口径分别记录。测试位于 `tests/bottleneck/`，共享数据集为 [bottleneck-features-v1.json](../../tests/fixtures/bottleneck-features-v1.json)，全部为人工构造的虚构记录。

## 与 Preference / Task 的关系

参考 [PR #13](https://github.com/ActionMesh-AI/Hackathon/pull/13) 的特征族目录、规则与字典分工；该 PR 已进入 main，本分支同步继承其实现。Preference 记录显式偏好与有效范围，Task 提取任务边界、目标和预期产物，和四族职责互补，统一 service 同时保留全部输出。

PR #13 的任务 ID 经来源／项目命名空间哈希，内部 `task_by_event` 只关联真人消息且未对外输出；本分支依赖事件与调用上的 `task_uid`／`attrs.task_id`。以后跨族联合分析时需要统一任务身份，并明确执行事件和子代理关联，不能直接按两个 ID 字段连接。Task 的目标／预期产物也不能替代 Interaction 的确认标签或 Outcome 的验收条件。

早期基于 `0c0d0f5` 与 PR #13 `d030c2a` 的临时整合验证有 530 项测试通过；共享文件已在同步 main 时正式整合。整体特征版本递增到 `feature-analytics-v2.2-bottleneck`，使包含四族的新结果与 main 的 `v2.1-subjective` 生成不同分析摘要；任务身份对齐仍是后续接入工作，不因代码共存就自动完成。

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

整体版本为 `feature-analytics-v2.2-bottleneck`，四组输出子契约为 `bottleneck-features-v1`。旧导入位置和字段仍可使用；新 benchmark 应读取新分组。本次还修正重复调用计数、模型活动误计累计记录、会话缺开始时间时错误补造开始、非法 Token／时延和缓存重复计量。机器可读定义在各特征族的 `dictionary.py`，由 `analytics/dictionary.py` 汇集。

## 口径与依赖

- Interaction 的确定性处理负责消费确认标注和统计；关键词只是候选。没有上游意图标注就返回未知，不假装已完成语义确认。
- Respond 提供执行证据，Cost/Time 消费区间，Outcome 消费调用结果。一个工具成功并不自动证明任务完成。
- Outcome 的条件来自明确的 Instruction 标注；没有验收项、产物版本或覆盖依据时保持未知。task_success 只描述指定完整验收集合。
- main 的 Instruction 当前输出原话与词面要求，尚不生成 `attrs.acceptance` 所需的确认验收集合、检查 ID 和产物版本。新增共存回归验证：即使识别了“验收标准”且两次检查通过，没有该结构化集合时 Outcome 仍不声明任务成功。
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

自查已修正：外层成功误充内部检查结果；验收可见时间早于条件确认；未来标注通过 L2 回退输出泄露；未知会话身份误记零；重复调用在旧字段与新分组统计不一致；同名快照跨会话覆盖。四目录重构已经合并；最后两项 P1 的补充 PR 仍交由负责人决定是否合并。

本轮验收记录（2026-10-02）：

- main 基线 398 项测试通过；重构后 467 项通过，新增 69 项。Ruff 与 `git diff --check` 通过。
- 同步 main 后按职责进一步拆分四目录，再次运行 467 项测试全部通过；逐一核对 30 个函数的语法树及 93 条字段定义，拆分前后相同。
- main 后续合入 Instruction 与连接器后，解决共享字段字典、兼容函数和 service 的冲突；包含一项新增跨模块边界回归的隔离提交副本，556 项测试和 Ruff 通过。隔离副本不包含工作区中另一项推荐模块开发的未提交文件。
- PR #19 首轮 review 的两项 P1 已修复：`validation_report` 在 L2/L3 都按截止时间过滤；缺少结果时间时只在同一会话内按 `result_seq` 排序，跨会话相互矛盾的证据保持未知。增加 8 项回归后，564 项测试通过，本分支合计新增 78 项瓶颈测试。
- 连接器未作代码修改；在临时 Linux Node 24.7.0 环境运行 `pnpm check`，typecheck、35 项构造样本测试、build 和构建后 CLI 帮助均通过。Windows 原生补充运行因该已有模块的路径／POSIX 权限假设失败，本 PR 不扩大到连接器的平台兼容改造。
- 隔离临时目录中的 synthetic demo 通过；evaluate 的 readability 8/8、pipeline 34/34、probe 12/12，history_updated=false。
- 四模块合成数据：确认纠偏率 0.5，工具调用 2 次，Token 350；执行耗时总和 20,000 ms、并集 15,000 ms；显式完整验收集合通过。排除子代理后，构建验收回到未知。
- 可在本地 `.local/bottleneck-fixture-result.json` 查看该虚构样本的完整结果；生成物不进入 Git。
- 审查按用户本轮要求，仅将 P0/P1 作为阻断项；其他问题可记录为后续工作，后续合并沿用同一优先级标准。本轮是本地逐模块自查，不冒充 PR 的 Codex review。测试中已有一条 Starlette/AnyIO 弃用提示，不影响通过，未扩大依赖升级范围。

并行提交 `5b17961` 附带的整合记录（2026-10-02，保留原记录）：同步 main `2029e2d`，保留 Preference/Task、Instruction、主观结果与四组瓶颈分析入口和字段字典。新增共存回归验证：显式用户接受与客观检查失败分别保留，不能相互覆盖。任务身份的跨族统一仍为后续工作。

该并行提交记录的验证（非本机复跑结论）：Python 3.11 下 770 项测试、Ruff、`git diff --check`、synthetic demo 和 evaluate（8/8、34/34、12/12）通过。本机锁定的 SciPy 1.15.3 wheel 存在 macOS 动态库加载错误，临时测试环境使用 SciPy 1.16.3；仓库锁文件不变，锁定依赖另由 Linux CI 验证。


本机 `929934c` 复核（2026-10-02）：保留并行提交 `5b17961` 的共存回归，并修复复审中的两项 P1——明确 excluded 的工具数据不再通过 L2 回退重建，Go 列表参数的等号形式不算实际验证。Linux 隔离副本中 775 项后端测试通过，其中 84 项为本 PR 的瓶颈与共存回归；Ruff 与相对 main 的空白检查通过。累计四项 P1 均有对应回归，仍未将个人 Agent 历史用于端到端测试。

补充 PR 验证（2026-10-02）：PR #19 实际合并的是 `5b17961`，未包含随后推送的两项 P1 修复。从最新 main `4bccf1f` 建立修复分支并合入 `929934c`，保留双方历史。Python 3.13.12 隔离副本、锁定依赖下 789 项后端测试和 91 项数据层测试通过，84 项瓶颈与共存回归全部保留。连接器 35 项构造测试、typecheck 和 build 通过，staging 桥接回归未跳过；Ruff、数据包格式检查、全包构建和 synthetic demo 通过。evaluate 为 8/8、34/34、12/12，history_updated=false；没有读取个人 Agent 历史。

# 非语义瓶颈推荐

将 interaction、respond、cost_time、outcome 的**已确认且可追溯的特征**转换为可执行的 skill、agent、hook、prompt 试用建议。算法不调用 LLM，运行时不联网，不自动安装或执行外部代码。现有基于画像的 `tandem_backend.recommend` 保持独立。

## 已完成

- 七组证据规则、缺失与未达门槛说明；每个根会话树独立判断，沿用输入的时间、项目和子会话筛选。
- 可调整且有版本的门槛、确定性排序、资源去重、每类问题最多两条建议。
- 每条卡片包含指标、证据 ID、作用范围、适配 Agent、来源固定版本、操作步骤、预览、限制及验证计划。
- 5 个本项目原创 prompt，7 个逐文件核验的社区资源；覆盖 skill / agent / hook / prompt。
- 全部收益标为 `unmeasured`；排序分数只表示试用优先级。原始提示词、工具参数和错误正文不进入推荐卡片。
- 仅用人工合成数据做规则、目录、兼容性、排序和接口测试。

## 输入与输出

```python
from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.analytics.recommendations import recommend_bottlenecks, RecommendationPolicy

features = analyze_bundle(synthetic_bundle, with_text=False)
result = recommend_bottlenecks(
    features, target_agent="codex", kind="skill", limit=6,
    policy=RecommendationPolicy(retry_min_count=2),
)
```

输入为已经过 `analyze_bundle` / `analyze_store` 筛选的完整分析结果，特征版本为 `bottleneck-features-v1`。算法读取 `sessions[].bottleneck_features`；没有可独立分析的根会话时返回证据不足，不使用可能混合多个根的整体聚合补足样本。不要把自行拼接的跨会话聚合伪装成单会话输入。

输出 `schema_version=bottleneck-recommendations-v1`，包含：

| 字段 | 用途 |
| --- | --- |
| `recommendations` | 可显示的卡片，最多 `limit` 条 |
| `signals` | 所有达到门槛的机会，资源筛选不会改变它们 |
| `assessments` | 每会话每条规则的 `triggered` / `below_threshold` / `insufficient_evidence` 与原因 |
| `policy` | 本次实际门槛，便于复现实验 |
| `catalog_digest` | 所用资源目录内容摘要 |
| `analysis_digest` / `scope` | 上游分析标识与选择条件 |
| `excluded_resources` | 未通过来源或契约检查的资源及原因 |

资源筛选支持 `target_agent=generic/codex/claude_code`、`kind=skill/agent/hook/prompt`、`limit=1..20`。`catalog=[]` 可只计算信号与门槛检查。

`analyze_bundle` / `analyze_store` 的默认结果包含 `bottleneck_recommendations`，因此 `tandem analytics --output ... --no-text` 的完整 JSON 也包含推荐。前端可调用 `GET /v1/analytics/recommendations?target_agent=codex&kind=skill&limit=6`，继承现有时间、项目、根会话、子代理及排除筛选。

无需导入任何本机聊天数据即可体验：`python scripts/demo_bottleneck_recommendations.py --output .local/recommendation-demo.json`。脚本只构造虚拟消息、工具调用和模型用量。

## 特征 → 干预

| 规则 | 初始触发条件 | 推荐能力 |
| --- | --- | --- |
| `correction_density` | ≥8 条确认意图，标注覆盖 ≥60%，确认纠偏 ≥3 且占比 ≥25%；必须有纠偏目标证据 | 按已标注 understanding/scope、execution、verification 分别匹配范围对齐、诊断、验证；无类型时保留通用对齐试验 |
| `repeated_requirements` | ≥4 条要求标注、覆盖 ≥60%，同会话同任务同对象要求重复强调 ≥2 次 | 要求记录、阶段计划 |
| `identical_retries` | ≥2 对确认的失败后同参数重试，有任务、状态范围及参数摘要证据 | 根因诊断、重试检查点 |
| `tool_failures` | 同一工具 ≥10 次已知结果、覆盖 ≥70%，失败 ≥3 且占比 ≥20% | 有足够结构化环境/输入错误时匹配调用前检查，否则先诊断 |
| `validation_failures` | 同任务、同产物版本、同范围和验证类型的实际失败 ≥2 次 | 诊断、验证流程、审查角色 |
| `acceptance_evidence_gap` | 有明确验收集合且工具采集完整，≥2 项没有匹配验证证据 | 验收记录与证据核对；不能解读为没有执行测试 |
| `context_pressure` | ≥5 次完整逐请求用量，未缓存输入 ≥20k 且占总量 ≥80%，同会话树还存在确认重试或压缩记录 | 阶段摘要/任务边界规划；共现不代表已证明因果 |

候选纠偏、未知工具状态、拒绝请求、累计 Token 快照、估算时长都不能替代上述证据。不会仅凭调用量高、会话长、串行执行或没看到子代理就推荐并行 Agent。

## 排序与效果验证

先做能力交集匹配；不同能力是可选干预方向，并非全部必需。分数：

```text
100 × 能力匹配 × 证据置信度 × 兼容系数
    × (0.60 × 严重程度 + 0.25 × 重复程度 + 0.15 × 接入便利度)
```

置信度为有效覆盖 × 样本饱和度；具体值、分子、分母随卡片输出。原生/手动兼容系数为 1，需要适配为 0.55，不支持则排除。接入便利度低/中/高成本分别为 1/0.6/0.3。按分数、规则 ID、资源 ID、信号 ID 稳定排序，同资源只保留分数最高的一条，每类问题最多两条。较低分不代表资源质量差。

效果必须通过固定任务输入、模型配置、产物版本与验收范围的对照实验测量。除目标瓶颈指标，还要记录通过率、验证覆盖、新增提示与工具调用、Token 和可靠时长。不能通过减少验证或丢弃错误让指标变好。数据不足则继续显示未知。

## 来源与适配

外部目录位于 `data/bottleneck-resources.json`，固定 Git commit、文件路径、Git blob SHA、内容 SHA-256、核验时间与许可。记录的是核验时快照，算法本身不会实时验证来源可用性。更新记录时需重新读目标文件及许可、重新计算摘要并跑目录测试，不能只把 SHA 改成最新值。

- [Superpowers](https://github.com/obra/superpowers/tree/8ca22dba9a94f28898bbce59f2537ff4d87c747d)：debugging / verification / writing plans 与 reviewer 角色模板。
- [Spec Kit](https://github.com/github/spec-kit/tree/838f1184d1b2ed254a99e8b818dbc23aa80a7f1f)：需求澄清与需求质量 checklist；checklist 不等于程序测试通过。
- [Claude Agent SDK Python](https://github.com/anthropics/claude-agent-sdk-python/tree/bfb895c6ef46e095191938b4eda798a025957c09)：hook 接入示例，需要工程适配；不是现成的重试限制器。

社区内容均只作为元数据与链接纳入；`preview` 是本项目编写的简述。没有在用户电脑上安装或运行这些资源。`agent` 为审查角色模板，不是独立可执行应用；`hook` 需要适配对应执行环境，不声称 Codex 可原生加载 Claude SDK hook。

## 文件职责与未来补充

| 文件 | 职责 |
| --- | --- |
| `analyzer.py` | 公共入口、根会话边界与输出合同 |
| `rules.py` | 七组特征证据规则与弃权原因 |
| `policy.py` | 版本与可调整门槛 |
| `catalog.py` | 原创 prompt、目录加载与来源准入 |
| `ranking.py` | 能力匹配、排序与试验卡片 |

后续工作：用团队批准的 benchmark 校准阈值和权重；把“试用/采纳/撤回/实际效果”反馈作为独立数据，不把点击当收益；补充资源版本再核验流程和真实适配测试。真实耗时、价格与长尾故障归因需要更完整的边界与同类任务基准，暂不把耗时长或花费高直接判成低效。界面安装、配置写入及一键回滚属于后续接入工作。

## 验证记录

新增 90 项合成测试覆盖规则门槛、候选/未知/未来证据、跨任务/版本/根会话隔离、资源准入、排序以及 service/API/CLI 对接。独立审查发现的孤立子代理跨根凑样本 P1 已修复并加入回归。Ruff、现有 synthetic demo 与 evaluate 通过；评测结果 readability 8/8、pipeline 34/34、probe 12/12，这些分数验证的是既有合成规则，不代表推荐的真实收益。未读取个人历史进行端到端测试。

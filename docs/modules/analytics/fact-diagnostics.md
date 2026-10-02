# 按特征族与 Skill 查看诊断

Orbit 的诊断输出把八个特征族的输入数量、有效观察、未知原因和可回查证据放在一起，同时保留每个 Skill 的筛选、召回、排序与入选结果。它用于检查模块覆盖情况，不把数量增长当成准确率或推荐收益。

## 根目录命令

已有本地 canonical 快照和仓库 `.venv` 时，从仓库根运行：

```sh
bash scripts/check-feature-diagnostics.sh
```

命令直接在终端输出，不依赖 `uv`，不调用模型，也不重新扫描或导入来源。默认优先读取 `.local/backend-nine-hour/current-data/tandem.db`，没有该目录时使用 `.local/backend-nine-hour/p0-data/tandem.db`；这些是本机验收快照的位置，其他机器需显式指定已经导入的 canonical 数据目录：

```sh
bash scripts/check-feature-diagnostics.sh --home /path/to/canonical-home --days 7
```

默认七天窗口以快照中最近一条有时间戳的事件为截止点，不以当前时钟为截止点。`--from-ts / --until-ts` 可以固定 UTC 毫秒窗口，截止点不包含在范围内。旧库需先按照数据层契约完成迁移；该诊断不会偷偷迁移或重新导入。

每次生成新的 `.local/feature-diagnostics/run-…/`，保留完整 `analytics.json`、`recommendations.json`、`diagnostics.json` 与 `terminal.txt`。`--output` 必须指向忽略的 `.local/` 下一个新目录，不覆盖已有结果。原始来源和派生结果均不得提交。

默认 Skill 目录是 `evals/recommendation/fixtures/reviewed-skills.json` 中四个有固定来源审阅元数据的条目；`--catalog` 可指定另一个 `recommendation-catalog-v1`、`family=skills` envelope。缺失 `items` 会报错，显式空列表保留为空，不回退到内置资源。

## 八族口径

| 特征族 | 主要观察 | 需要保留的未知项 |
| --- | --- | --- |
| Interaction | 真人消息、确认意图、模型推断意图、关联纠偏与词面候选 | 未解析意图、未关联的目标、语义精度 |
| Respond | 工具调用和结果、子代理实例与活动 | 包装调用的内部结果、失败根因、创建者关系 |
| Cost / Time | 有效请求、四类 Token、墙钟与原生执行时间 | 请求边界、价格、审批等待、模型延迟 |
| Outcome 客观 | 已执行检查、检查失败、验收条件 | 是否覆盖完整任务及对应产物版本 |
| Outcome 主观 | 交付、反馈、目标关联与确认完成 | 沉默、部分接受与无法关联的反馈 |
| Task | 共享任务记录、领域与类型分布 | 候选边界和未识别领域 |
| Preference | 显式偏好、复用指令的偏好证据、证据来源 | 不可提升为长期配置的任务要求 |
| Instruction | 要求覆盖、八类控制要求、显式与推断来源 | 未匹配要求、截断和不可作为执行授权的推断 |

每个度量声明 `unit`、字段路径与分母。真人消息、工具调用、验证尝试和验收条件属于不同单位，不组成统一的递减漏斗。不可用来源中的兼容性零值会在诊断中显示为未知；独立可用的时间或工具数据仍可报告。

有真人输入但没有可用意图观察时，Interaction 显示 `input_only`；仅有词面纠偏候选时显示 `candidates_only`。这两种状态均不意味着用户没有需求或摩擦。

## 候选推荐与实际效用

每个有效 Skill 的 `resource_assessments` 保留环境筛选、召回路由、评估与排序数量、匹配信号以及最终选择原因。排序后落选的 Skill 也保留它使用过的信号和证据；零推荐仍能看出是没有观察、没有匹配，还是被条件或排序限制排除。

模型推断的纠偏在同一根会话内满足样本、覆盖、次数、比例和目标关联门槛后，可产生 `evidence_tier=model_inferred` 的候选试验。人工标注用于精度校准；产品产生候选输出不以人工标注为前提。该路径不修改确认纠偏计数，不提升任务成功，也不解除环境条件或执行权限。

`confidence` 和 `priority_score` 是样本支持与排序启发式，均不是语义正确率、成功概率或因果收益。模型推断的语义概率和推荐的效用概率保持 `null`。不提供同一任务起点的干预与对照证据时，实际增益、节省 Token、节省分钟均为未知；显式假设下的场景估计另行列出。

画像只描述窗口中领域、任务类型、验证活动与协作事实。负面执行结果沿共享任务轨迹列为复核候选，严重度、额外成本与根因需要各自的证据，不能从重复边、工具失败或工具耗时自动推断人格和劳动效率。

## 验证边界

构造测试覆盖不可用与已知空数据、不同计数单位、目录无回退、排序落选的证据保留，以及无人工意图标注的模型候选路径。它们验证实现边界；真实语义精度和实际 Skill 效用仍需要独立标签与同起点干预实验。

本地来源导入验收 `evals.recommendation.local_codex` 也保存 `diagnostics.json / diagnostics.txt`，与终端诊断使用相同投影。

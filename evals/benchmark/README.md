# 推荐的过去到未来 Benchmark

三类评测共用同一份冻结样本：过去 `[t0-history_days, t0)` 只用于生成推荐；之后最多 72 小时内接下来的 K 个用户目标只用于评价。主设置是 7 天历史、5 个未来任务；不按消息数扩充样本，不随机混合过去和未来。

从仓库根使用已有 `.venv`：

```sh
bash scripts/check-benchmark.sh
.venv/bin/python -m evals.benchmark.local --home /path/to/canonical --output .local/benchmark/run-01
```

默认三个相隔一天的滚动锚点，最近锚点距离快照最后观测 72 小时；历史 3/7/14/30 天、未来 1/3/5/10 个任务。`--anchor-ts UTC_MS` 可重复指定锚点。来源为已有 canonical 数据库，不再扫描或启用来源，不调用模型、不安装或执行 Skill；真实输出只写入新建的忽略目录。默认资源为四个有固定来源的审阅 Skill。

脚本优先使用 `.local/backend-nine-hour/current-data`，未准备时回退到原阶段的 `p0-data`；其他快照用 `--home` 指定。旧 Mapper 投影不能直接分析，须先按数据契约重建；脚本不会隐式替用户迁移或重建数据。

## 三类评测

| 类别 | 指标与用途 | 当前自动运行做什么 |
| --- | --- | --- |
| Forward Utility | Pass@5k/10k/20k；同预算成功任务的 Token、轮次、工具调用与墙钟改善 | 冻结五种方法的输入／执行计划，读取实际未来任务观察；没有配对执行时保持未证实 |
| Recommendation Quality | Regret@1/@K、Harm、无需干预时的误触发 | 把 no_intervention 放进固定 plausible action 集合；只在完整同环境 action sweep 后计算 oracle 与效用差 |
| Temporal Robustness & Personalization | 相同指标在滚动锚点、窗口、缺失、跨项目与个性化／表示消融中的变化 | 实际重放结构化匹配，检查时间隔离、推荐选择与证据；效用缺失时 Jaccard 仅作选择稳定性诊断 |

五种方法是 no_recommendation、固定通用推荐、raw_history_llm、ours、hindsight oracle。通用推荐固定为审阅目录第一项，不根据未来任务挑选。Ours 使用锚点之前的分析；方法对照只测试当时 Top-1，Top-K 的 action sweep 另外评价候选集合。

真实任务片段来自共享 Task/Work Graph。没有独立审阅的边界继续标记 candidate/unreviewed；没有任务开始前的完整仓库状态则 checkpoint=missing。未来的命令检查不等于整个用户目标通过。未来 Task ID 无法关联的模型调用不补成零 Token。未来任务数量不足 K 且日志尚未覆盖 72 小时时，窗口明确为 right-censored。

## 控制与防泄漏

每个预测保存范围、事件清单、输入摘要、八族诊断、逐 Skill 诊断、推荐和关系校验；模型／语义观察必须遵守各自 available_at。读取 canonical 数据时按每个锚点重新构建对应范围，避免后来的 L3 状态回填过去。全量 episode index 仅用于抽样未来目标，不进入推荐输入。

未来另存于 `anchor-*-future/`，没有运行推荐引擎。主程序和测试检查过去事件时间 `<t0`、未来事件与过去输入不相交、推荐证据回溯及原数据库前后摘要／非空数据库文件哈希不变。SQLite 只读打开可能产生空 WAL 文件；空文件不代表新增事实。

历史缺失以主 root session 为单位，使用固定种子 7/11/19 的三组排列，分别移除 10/30/50% 的 roots，避免只删除起止事件的一半而制造悬空关系；报告实际删除数、比例和原分母。跨项目设置从过去排除未来任务所在项目，其推荐只看到剩余过去项目。没有第二个独立用户数据库时，wrong-user 标记 unavailable，不把自己的数据改标签冒充他人。

显式提供 wrong-user 历史时，要求不同的用户标识、数据库路径与不重叠的原生主会话身份，并核对该数据库运行前后不变。复制数据库、把同一份原生日志导入另一目录不能通过这个对照；这些检查不独立证明用户归属真实性。

本地执行的表示对照是 full_system、structured_features（不提供图／词汇／画像／统计投影）、task_context_only（只提供任务／环境，不提供瓶颈或偏好）。当前匹配器是否使用某层由实际输入与结果反映，不能预设“完整系统一定更好”。Raw history 和 UI profile 的有界输入（每种最多 12,000 字符）只在本地准备；未获得具体外部传输授权时不调用 LLM，不给这两个 baseline 填伪分数。

## 执行测量契约

`contracts.py` 中 `TemporalSample` 和 `ExecutionRecord` 是权威约束。执行记录显式区分 paired_execution、historical_observation、constructed_execution。以下信息缺失时不能计入实测 headline：

- 精确 checkpoint（包括工作区文件）、任务输入、环境和验收检查定义的摘要。
- 实际干预内容与原始执行日志摘要；方法、固定锚点、种子、模型及推理档位。
- 四类执行 Token 和推荐自身 Token、轮次、工具调用、墙钟时间、停止原因与验收结果。

同任务不同方法必须使用相同 checkpoint、输入、环境、验收检查、模型、seed 和预算。默认模型固定 gpt-6.1-sol / medium；预算分别为 5k/10k/20k 总 Token、20 轮、50 个工具调用和 300 秒。总 Token 含未缓存输入、缓存读、缓存写、输出以及推荐开销。推荐开销与执行调用分开记录，不能重复相加。

Pass@Budget 只有验收通过、正常完成且所有预算均满足才为通过。未知 Token 或结果不当成失败或零；缺失运行列出分母，headline 保持未证实。Token／轮次改善只在两个方法都成功的配对任务上统计，零基线不计算相对改善。源为构造测量的结果单列 constructed_only。

质量评测的固定效用是同预算未来任务通过率；不临时调整效用权重。完整测量所有 plausible actions 和 no_intervention 后才有 hindsight oracle。Regret@K 是事后候选集合最佳值，不代表执行时能够知道哪个最好；no_intervention 在通过率平局时优先，从而评价不必要干预。历史推断的严重度或改善假设不能代替 Y(a)。

滚动窗口可能重用同一任务，因此报告唯一任务数和每个锚点的结果，不把 pooled 数字作为独立用户样本量，不在单用户重叠窗口上生成误导性的显著性结论。提供的执行记录仍是调用方测量；该工具校验结构、公平性和绑定，不独立证明日志或人工标签真实性。

## 产物与后续执行

输出包含 `episode-index.json`、`samples.json`、各案例诊断、未来观察、`method-plan.json`、`forward-utility.json`、`recommendation-quality.json`、`summary.json` 和六问报告 `report.md`。自动重放 status=passed 只指时间与证据校验通过；效用／质量有独立状态，缺少实测时为 unproven。

先由独立人员确认任务单位并保存开始前 checkpoint，随后按执行计划运行对照及 action sweep。测量 JSON 数组通过 `--execution-records` 提供。改变模型、预算、锚点，或用非冻结推荐动作冒充 Ours，会得到 invalid 并使运行失败。未执行的 raw_history_llm／oracle 方法比较没有冻结策略，不能仅提交声称属于这些方法的结果来获得分数。

`study-manifest.json` 冻结样本、执行计划和全部过去输入／预测摘要。后续人工复核使用 `TaskReview` 数组，来源必须明确为 independent_human，包含边界、目标、证据、checkpoint、验收定义与复核时间；保持预测不变，另行评分：

```sh
.venv/bin/python -m evals.benchmark.score --study .local/benchmark/run-01 --executions /path/to/executions.json --task-reviews /path/to/reviews.json --output .local/benchmark/score-01
```

评分不会修改冻结样本，也不重新生成推荐或调用模型。缺少复核或执行仍为 unproven；冻结文件被改动、动作与当时 Top-1 不符、预算或 checkpoint 不同，会被拒绝。人工认为任务边界不对时，须另建任务 cohort，不能丢弃坏样本后静默提升已有分数。

独立人工审阅、已观察的真实目标与已验证的精确 checkpoint 必须同时具备，才能计入实测效用。`needs_context` 或需适配的推荐不能冒充当时可执行的 Ours：须在锚点之前补齐环境，另建冻结研究。Action sweep 只接受冻结 plausible actions 中的动作，预算固定为 10k、使用共同 seed；额外未登记动作不能改变 oracle。

准备未填答案的复核与执行清单：

```sh
.venv/bin/python -m evals.benchmark.prepare --study .local/benchmark/run-01 --output .local/benchmark/prepared-01
```

准备包只列出未来任务的真人证据身份、待复核字段和执行格子。`task-reviews.json` 与 `executions.json` 都为空数组，measurement 均为空；有待补环境、预测未冻结和缺少 checkpoint 的格子分别报告，不自动产生标签或执行结果。

评分和准备都支持 `--expected-study-digest SHA256`，核对独立留存的 `study-manifest.json` 摘要。工具还检查每个样本的过去预测均被清单覆盖。仅有同目录哈希能发现意外修改，不能阻止调用方改完全部文件后自行重签；独立记录的摘要和日志真实性仍需研究者保障。

原始历史、数据库、未来输入、测量日志和审阅包不能提交 Git。该目录提交协议、工具、构造测试和方法说明；本机实测报告保留在 `.local`。

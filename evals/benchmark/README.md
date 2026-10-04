# 过去到未来的推荐 Benchmark

此协议用锚点之前的历史生成推荐，用锚点之后的任务评价；不能随机混合过去和未来。结构回放、实际配对执行和独立人工验收分别记录，缺失实测时效用保持 unproven。

## 冻结研究

```sh
python3 scripts/heavy.py uv run python -m evals.benchmark.local --home /absolute/orbit-home --output .local/benchmark/run-01
```

显式指定已有 canonical home，不扩大为重新扫描来源。默认主设置为 7 天历史、之后最多 72 小时内的 5 个用户目标；滚动锚点和多种窗口以参数为准。资源、模型在历史锚点时是否实际可部署需另证，回放不能冒充当时已部署效果。

冻结样本、过去输入/预测、资源目录正文摘要、方法计划与 manifest。未来输入单独保存，不运行推荐引擎；每个锚点重新读取相应 Scope，避免最新 L3 结果泄漏到过去。规则、语义观察与人工标注均遵守 available_at。

## 评价问题

| 评价 | 必要证据 |
| --- | --- |
| Forward Utility | 同任务、checkpoint、模型、环境与预算的真实配对执行 |
| Recommendation Quality | 固定 plausible actions 和 no_intervention 的完整 action sweep，才可计算 oracle/regret |
| Temporal Robustness / Personalization | 滚动窗口、缺失、跨项目及表示消融；选择稳定性不能代替效用 |

方法包括 no_recommendation、固定通用推荐、raw_history_llm、ours 与 hindsight oracle。没有模型授权或实际运行时，相应方法不填伪分数。wrong-user 对照需要独立用户历史，不能把同一数据库复制后改名。

## 执行合同

权威定义在 [contracts.py](contracts.py)。记录区分 paired_execution、historical_observation 与 constructed_execution。实测需要精确 checkpoint、任务输入/验收定义、环境、模型、种子、预算、实际干预和原始执行日志摘要。

Skill 实际正文摘要必须与冻结目录一致，不能只照抄期望值代替执行证据。总 token 包含规范输入/缓存/输出桶和推荐开销，避免重复相加。通过预算要求验收、正常结束和全部预算均满足；未知计量不填零，也不任意算失败。

改善只在同一条件下两个方法都成功的配对任务中比较。oracle 依赖完整动作测量，不能用历史推断的收益取代 Y(a)。重叠窗口报告唯一任务数，不当作多个独立用户。

## 人工复核与评分

```sh
uv run python -m evals.benchmark.prepare --study .local/benchmark/run-01 --output .local/benchmark/prepared-01
uv run python -m evals.benchmark.score --study .local/benchmark/run-01 --executions /absolute/executions.json --task-reviews /absolute/reviews.json --output .local/benchmark/score-01
```

prepare 生成空的待复核/待执行清单，不生成标签或测量。独立人工确认任务边界、目标、checkpoint 和验收后再评分。改变冻结样本、动作或环境应另建研究，不能静默丢弃不利样本。

`--expected-study-digest` 可与独立保存的摘要核对；同目录哈希只能发现部分意外修改，不能独立证明日志或标签真实性。自动 status=passed 仅代表相应结构/隔离检查通过，效用与质量有独立状态。

历史、未来输入、测量日志和数据库不提交 Git。普通文档与功能修改无需运行该 Benchmark；验证选择见[测试指南](../../docs/development/testing.md)。

# 质量与真实数据评测

评测检查语义、推荐、证据和读者理解，普通测试检查可重复工程行为；两者不能互相代替。真实数据工具必须显式选择输入，产物保存在新的忽略目录。

| 任务 | 入口 |
| --- | --- |
| 构造的文字与报告链路 | `uv run orbit evaluate` |
| 八族与 UI 组合产物 | `uv run python -m evals.analytics.products --synthetic --output .local/products` |
| 主观反馈质量 | `uv run python -m evals.analytics.subjective_outcomes` |
| 偏好快照诊断 | `evals.analytics.preference_local`、`scripts/check-preference.sh` |
| 受控扰动和原生等价 | [鲁棒性方法](../docs/development/analytics-robustness.md) |
| 推荐匹配 | `evals.recommendation.demo` 与对应 fixtures |
| 未来任务效用 | [Benchmark 协议](benchmark/README.md) |
| 表达是否易读 | [读者评价](../docs/modules/evaluation/reader-review.md) |

先查看工具 `--help`，不要沿用其他研究者的 `.local` 路径。`--real-db`、`--codex-home`、`--home` 等参数是否触发真实读取以工具为准；真实语义外发还需要对应授权。大规模流程经 `scripts/heavy.py` 调度。

报告保留 SHA、输入范围、排除项、方法版本、已完成/失败/未知和独立标签来源。构造标签参与过规则调试后属于回归集，不能宣称独立效果；未执行配对实验时不填写收益分数。

运行时评价函数与随包样本仍在 backend，确保 wheel 安装后可用。性能工具在 [benchmarks](../benchmarks/README.md)，不与质量分数混算。

[Artificial benchmark](artificial_benchmark/README.md)提供冻结任务、运行配置与对照协议；轨迹、计量和结果按协议保留在本地，不能用结构回放代替实际配对执行。

# 性能基准

性能工具以明确规模报告耗时、吞吐和内存，不作为每次 PR 的固定正确性门槛。默认使用构造数据，不读取本机 Agent 历史。

## 选择入口

| 内容 | 入口 |
| --- | --- |
| 分析全流程 | `uv run python -m benchmarks.analytics.full_pipeline --sizes 500 1000 2500 --repeats 3` |
| Instruction | `uv run python -m benchmarks.analytics.instruction --output .local/benchmarks/instruction.json` |
| 语义族 | `uv run python -m benchmarks.analytics.semantic_families --sizes 100 1000 --repeats 3` |
| 主观反馈 | `uv run python -m benchmarks.analytics.subjective_outcomes --sizes 1000 10000 --repeats 3` |
| 数据导入与同步 | [数据基准](data/README.md) |
| Catalog | `uv run python benchmarks/catalog_bench.py --items 20000 --seed 7` |

以上重负载入口前加 `python3 scripts/heavy.py` 排队。实际参数以各工具 `--help` 为准，输出放 `.local/`。

## 测量合同

记录提交、运行时、硬件、负载、规模、seed、预热、重复次数和计时边界。分析 full_pipeline 将读取、计算、序列化和历史写入等阶段分开；`--with-text`、`--canonical`、`--profile` 改变测量范围，比较时需一致。

性能优化同时核对逻辑结果。分析使用[等价性回归](../tests/regression/test_analysis_equivalence.py)，数据使用逻辑摘要；有意改变结果时解释差异，不为通过测试重生成金标。

ToyHash 等构造向量仅用于流程测量，不代表真实模型吞吐或质量；单机耗时也不是产品 SLA。质量与收益见 [evals](../evals/README.md)。

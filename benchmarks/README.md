# 性能评测

只使用构造数据，按规模输出耗时与内存；不属于每次 PR 的硬件无关正确性门禁。

```sh
uv run python -m benchmarks.analytics.instruction --output .local/benchmarks/instruction.json
uv run python -m benchmarks.analytics.semantic_families --sizes 100 1000 --repeats 3
uv run python -m benchmarks.analytics.subjective_outcomes --sizes 1000 10000 --repeats 3
uv run python -m benchmarks.analytics.full_pipeline --sizes 500 1000 2500 --repeats 3
```

## 分析全流程

`analytics/full_pipeline.py` 按读取、bundle、select、会话行、文本、lexical、statistics、聚合、products、JSON 序列化、历史写入输出各阶段独占耗时（重复取中位数，先预热一次，生成或导入耗时单列为 setup）。

- `--with-text` 计入文本表示；`--canonical` 先把构造来源经 ingest 写入临时 `tandem.db`，再测量 `read_analysis`；`--profile` 对最大规模跑一次 cProfile，报告前 30 行；`--output` 另存 JSON。
- 输入来自 `analytics/synthetic.py`：固定种子、完全虚构，不读本机会话。同一生成器也驱动 [结果等价性回归](../docs/development/testing.md#性能与等价性)。
- 基准不作 CI 硬门槛。性能改动应同时通过等价性回归；金标更新须在 PR 描述中说明原因与差异。

保留运行时、硬件、样本规模、重复次数和计时边界。性能与语义质量分开解释；质量评测见 [evals](../evals/README.md)。

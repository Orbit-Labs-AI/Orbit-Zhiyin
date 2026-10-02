# 性能评测

只使用构造数据，按规模输出耗时与内存；不属于每次 PR 的硬件无关正确性门禁。

```sh
uv run python -m benchmarks.analytics.instruction --output .local/benchmarks/instruction.json
uv run python -m benchmarks.analytics.semantic_families --sizes 100 1000 --repeats 3
uv run python -m benchmarks.analytics.subjective_outcomes --sizes 1000 10000 --repeats 3
```

保留运行时、硬件、样本规模、重复次数和计时边界。性能与语义质量分开解释；质量评测见 [evals](../evals/README.md)。

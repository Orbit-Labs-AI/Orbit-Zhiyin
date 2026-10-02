# 质量与真实数据验收

从仓库根通过模块方式运行：

```sh
uv run tandem evaluate
uv run python -m evals.analytics.subjective_outcomes
uv run python -m evals.analytics.instruction_real --help
uv run python -m evals.analytics.semantic_history --help
```

subjective_outcomes 默认只使用构造质量样本；真实历史必须同时明确提供 --real-db 和 --codex-home。其他真实数据工具也需显式输入路径。输出保留在忽略的 .local 下，不能提交真实会话。

原来 subjective_outcomes 中的性能测试已拆到 [benchmarks](../benchmarks/README.md)。运行时 API 使用的评价函数与内置 JSON 样本仍随 backend wheel 分发，不能移到仓库工具后造成安装版本缺文件。

这里的构造预期用于发现规则错误；读者评价另见[方法与限制](../docs/modules/evaluation/reader-review.md)。自动通过不代表真实推荐效果或人类认可。

推荐构造验收：`uv run python -m evals.recommendation.demo`；显式资源目录验证：`uv run python -m evals.recommendation.catalog /path/to/catalog --agent codex`。后者只校验提供的 JSON，不读取历史、不抓取资源。

UI 分析组合验收：`uv run python -m evals.analytics.products --synthetic`；真实来源通过 `--source AGENT=ROOT` 显式启用，命令、样本范围和报告见[分析验收](../docs/modules/analytics/analysis-products.md)。

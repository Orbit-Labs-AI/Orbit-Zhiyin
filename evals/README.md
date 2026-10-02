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

推荐偏好／收益验收：`bash scripts/test-recommend.sh`。运行推荐模块和报告集成测试，再用四个已抓取公共 Skill 的内容审阅元数据生成用户／项目／任务对照案例、收益敏感性与边界报告。输出在 `.local/recommendation-validation/`，失败返回非零退出码。`--skip-tests` 只重生成案例并明确标记自动测试未运行，`--output /path/to/output` 可指定目录。该工具不执行上游 Skill，不读取真实用户历史，不自动联网；可选的本地抓取快照仅用于核对固定来源。

报告快照见[推荐测试报告](../docs/modules/recommendation-validation.md)。自动运行的案例带预先固定的预期首选和净收益断言；所有改善比例／成本均为构造假设，不是实测效果。四项评测元数据不是对 1033 项抓取结果的批量审核，也不随 backend wheel 默认发布。

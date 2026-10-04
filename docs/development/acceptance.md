# 来源到建议的链路验收

链路验收检查同一输入是否经过导入、证据、分析、推荐和输出保持一致。构造数据用于可重复回归；真实数据只在明确授权后用于额外核对。

## 构造入口

```sh
uv run orbit demo --output .local/demo
uv run orbit demo --output .local/demo --view profile
uv run orbit demo --output .local/demo --view bottlenecks
uv run orbit demo --output .local/demo --view process
uv run orbit evaluate --output .local/evaluation.json
```

查看同目录中的画像、瓶颈、过程和报告。以实际报告中的事件 ID，经相同 home 的 `orbit evidence` 回查；不要继续套用旧教程的 demo.sqlite 路径。

## 核对结果

1. 范围、来源与覆盖一致，计数能回到标准事实和原始贡献。
2. 要求、交付、工具过程与反馈具有明确任务/时间关系，缺失材料可见。
3. 建议保留问题与资源依据；证据不足或不适用时允许为空。
4. CLI、API、报告与 UI 使用同范围结果，未知和陈旧状态一致。
5. 评价与生成不会被导入成个人历史事实；安装需要独立预览与确认。

App live 路径另按[开发入口](setup.md)和[原生验证](mac-app.md)检查。读者是否理解、语义准确率和实际收益分别见[评价](../modules/evaluation/reader-review.md)与 [Benchmark](../../evals/benchmark/README.md)。

本页不固定测试总数或宣称某次运行已通过；每个 PR 按[测试指南](testing.md)记录自己的 SHA、命令、环境和结果。

# 分析与推荐鲁棒性

鲁棒性验证使用可解释扰动检查事实、关系和推荐如何变化，不能把规则自身生成的标签当作独立真值。工具不默认调用模型、安装资源或启用个人来源。

## 验证维度

| 变化 | 应保持或改变什么 |
| --- | --- |
| 同身份重复、输入重排、无关 UI 字段 | 有效事实与推荐保持一致；冲突身份明确失败 |
| 增加有依据的重试 | 对应关系和次数变化，原失败数不凭空变化 |
| 删除失败事实 | 相应信号改变，其他无关族不被污染 |
| 全量与分批增量 | 同源树各逻辑层和分析结果一致 |
| 未知类型、坏行、半帧 | 保留记账和原因，恢复后可继续投影 |
| 空范围、子代理、历史截止 | 不串范围、不引入未来结果 |
| 库存、权限和偏好变化 | 只改变相应适用条件和排序，不篡改历史事实 |
| 更大数据规模 | 记录实际范围、耗时和内存，超限不冒充全量 |

## 运行入口

先查看工具 `--help`，使用明确的 canonical home 与新的忽略输出目录：

```sh
python3 scripts/heavy.py uv run python -m evals.analytics.robustness --home /absolute/orbit-home --output .local/robustness/run-01
python3 scripts/heavy.py uv run python -m evals.analytics.robustness_native --home /absolute/orbit-home --output .local/robustness/native-01
python3 scripts/heavy.py uv run python -m evals.analytics.robustness_faults --output .local/robustness/faults-01
```

原生重建只使用已授权、已索引的输入清单；时间比较显式传同一对 `--from-ts / --until-ts`，不要混用工具不同的默认窗口。未完成案例和错误单独记录，不能用已完成部分表示整次成功。

## 解释结果

比较前声明允许忽略的过程字段；事实、覆盖、证据和关系均参与比较。改变查询范围要重新读取 canonical bundle，不能只过滤旧 events 后继续复用旧 L3。

构造案例验证工程行为，真实任务边界与语义精度仍需要独立人工标注。未来收益需要任务开始前 checkpoint 和配对执行，参见 [Benchmark](../../evals/benchmark/README.md)。按[测试指南](testing.md)决定本次是否需要这些检查，不作为每个文档 PR 的固定门槛。

# 特征分析

`analytics` 将 canonical 事实转换为有范围、证据和覆盖说明的测量结果。计算本身不调用远端模型；显式产生并通过校验的语义观察可作为独立输入。

## 计算结构

读取统一输入 → 构建同范围 `AnalysisContext` → 八族计算 → 横向信号与任务关系 → 聚合及展示产品。请求内索引复用身份和关系，跨请求缓存按输入与算法版本区分，详见[统计与历史](statistics-history.md)。

| 族 | 回答的问题 | 主要边界 |
| --- | --- | --- |
| Task | 在处理什么任务？ | 明确任务身份与规则分段候选分开 |
| Instruction | 这一次要求如何执行？ | 不把识别结果当作执行权限 |
| Preference | 明确偏好及历史支持是什么？ | 任务/项目/全局作用域不混合 |
| Interaction | 用户何时介入、纠偏或补充？ | 新需求不自动算纠偏 |
| Respond | Agent 如何执行、调用和协作？ | 重复转移不自动等于重试 |
| Cost-Time | 观察到多少用量与时间？ | 累计、逐次、墙钟和原生耗时分开 |
| Outcome | 哪些检查和验收有证据？ | 测试通过不等于整个任务成功 |
| Subjective Outcome | 用户如何评价具体交付？ | 沉默、礼貌或情绪不等于接受 |

字段定义分布在各族 `dictionary.py`，汇总入口为 [analytics/dictionary.py](../../../packages/backend/src/orbit_backend/analytics/dictionary.py)。新增字段写明粒度、单位、分母、来源、未知条件和版本，不再维护另一个手写字段全集。

## 运行与接入

```sh
uv run orbit --home .local/my-orbit analytics --no-text --display-timezone Asia/Shanghai --output .local/analytics.json
uv run orbit --home .local/my-orbit analysis-report --output .local/analysis-report
```

前置条件是所选 home 已有导入结果。`--no-text` 跳过文本表示；Scope、覆盖与统计成员的语义见[输入契约](../../contracts/analysis-inputs.md)。App 页面经 `uiview` 组合，报告和分析接口仍可单独消费底层结果。

## 解释与验证

结果保留有效数、未知数、规则版本和证据，不能把缺失值填成 0 或将候选升级为确认。规则阈值和展示门槛不代表经人群校准的概率。

使用构造正反例、范围隔离、关系验证和等价性回归验证实现；真实准确率与用户收益需要独立标签与评价。早期案例和当时效果记录见[归档](../../archive/implementation/feature-analytics.md)。

## 标准输入与字段导出

```sh
uv run orbit analytics --analysis-input .local/analysis-input.json --output .local/analytics.json --feature-output .local/features
```

`--analysis-input` 消费 data.read_analysis 的标准输出，`--data-home` 可直接只读查询规范库。继承输入的范围、排除项和时区，只能进一步缩小范围。关联上下文不计入统计，模型请求需要原生用量事件同时证明 call/delta 和一致身份。

`--feature-output` 生成索引和每族 JSON/Markdown，使用 RFC6901 source_path 回到同次结果。字典外的测量、候选、证据和缺失原因保留在 payload；0、false、null 与空列表原样保留。八个分析族与兼容导出的基础 section 是不同组织层次。

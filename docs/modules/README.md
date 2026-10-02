# 模块说明

各能力的算法、验证与限制，按模块分目录。算法说明中的实验结果属于原文注明的版本和样本，目录迁移没有重新证明历史结论。模块方案（尚未实现的部分）见 [docs/plans](../README.md#5-方案不等同当前能力)。

## 数据 `data/`

- [Agent 连接器](data/agent-connectors.md)：七类 Agent 的原生来源与解析。
- [本地数据服务](data/data-services.md)：检索、resume、能力、占用与清除、脱敏规则、insights。
- [来源索引与轨迹读取](data/indexed-trajectories.md)：来源索引、完整正文与 App 轨迹读取。
- [本机安装清单](data/local-inventory.md)、[测试与验收](data/inventory-testing.md)、[完整性复核](data/inventory-audit.md)。

## 分析 `analytics/`

- [后端怎么工作](../architecture/backend.md)：当前默认入口与历史算法语义。
- [统计分析与完整分析记录](analytics/statistics-history.md)：词频、分布、对比与持久化历史。
- [画像推导](analytics/profiling.md)、[特征分析](analytics/feature-analytics.md)、[瓶颈特征](analytics/bottleneck-features.md)。
- [Signal 层](analytics/signals.md)：八族之上的横向派生层、指标引擎与下钻。
- [前端指标](analytics/presentation-metrics.md)、[UI 分析与端到端验收](analytics/analysis-products.md)、[原始 UI 对应](analytics/original-ui-mapping.md)。
- [这些数字说明什么](analytics/modeling.md)。
- [Preference](analytics/preference.md)、[Task](analytics/task.md)、[任务领域分类](analytics/task-taxonomy.md)、[Instruction 验收](analytics/instruction-validation.md)及[验证范围](analytics/validation.md)。

## 资源目录 `catalog/`

- [Catalog 架构](catalog/architecture.md)：资源数据与混合检索。
- [实测记录](catalog/validation.md)。

## 推荐 `recommendation/`

- [推荐引擎](recommendation/engine.md)：七类资源合同、召回、排序、解释与当前限制。
- [偏好与收益测试报告](recommendation/validation.md)。

## 评测 `evaluation/`

- [读者评价](evaluation/reader-review.md)：怎样验「说人话」。

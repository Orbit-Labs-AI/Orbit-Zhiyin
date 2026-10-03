# Task：任务边界与文本表示

任务分段、领域标签与文本相似性分别维护。`features.py` 提供 `segment_tasks`、`extract_task_features` 和 `summarize_task_distribution`；原生任务身份与规则候选不能混为确认关系。

## 表示与新颖度

`representation.py` 在本地计算 TF-IDF/SVD、聚类、坐标和词项，不调用远端服务。依赖延迟加载，普通模块导入不应触发重型计算。

全量当前语料拟合的表示用于探索；时间新颖度使用无拟合状态的字符哈希向量，与严格更早的会话计算最大余弦相似度后取 `1 - max_cos`。同时间对象不互为过去，未知时间或无更早对象返回 null。

`VECTOR_VERSION` 区分旧前缀拟合方法与当前哈希方法，跨版本数值不可直接比较。分块稀疏计算控制工作内存，不改变候选时间边界。

领域规则见 [taxonomy.py](taxonomy.py)和[任务分类说明](../../../../../../docs/modules/analytics/task-taxonomy.md)；关系图见[Work Graph](../work_graph/README.md)。新增方法同步版本、范围回归和等价性预期，不能只更新金标来消除失败。

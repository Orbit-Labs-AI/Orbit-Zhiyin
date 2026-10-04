# 任务、文本与关系

Task 描述用户当前请求的任务内容与边界。会话和轮次是原生日志粒度，分析任务是另一种关系；只有明确证据才能把工具、交付、验证与反馈归到同一个任务。

## 三种结果

| 结果 | 来源 | 解释 |
| --- | --- | --- |
| 任务分段 | 原生 ID、显式边界及规则候选 | 原生确认与推断边界分开 |
| 领域标签 | 当前真人请求中的可解释规则 | 多标签候选，不表示能力或兴趣强度 |
| 文本表示 | 本地 TF-IDF/SVD、聚类与坐标 | 用于相近文本探索，不确定真实任务身份 |

`segment_tasks`、`extract_task_features`、`summarize_task_distribution` 从[任务模块](../../../packages/backend/src/orbit_backend/analytics/task/)导出。领域细分见[分类规则](task-taxonomy.md)。

## Work Graph

共享任务图连接 Task、Turn、ToolCall、ModelCall、SubagentRun、产物及版本、交付、验证、反馈与指令。每条关系保留证据、来源、覆盖和可见时间。文件编辑次数不能自行生成产物版本；候选任务不证明验收、重试或长期偏好。

`/v1/analytics/work-graph` 与 `/v1/analytics/tasks/{task_uid}/trajectory` 沿用同范围读取，范围外任务返回未找到。详见 [Work Graph](../../../packages/backend/src/orbit_backend/analytics/work_graph/README.md)。

## 时间新颖度

聚类坐标可在当前语料上拟合；时间新颖度只能比较严格更早记录。当前实现使用无拟合状态的字符哈希向量计算前缀相似度，避免未来语料改变过去表示。未知时间或没有更早对象时返回未知，详见[任务实现](../../../packages/backend/src/orbit_backend/analytics/task/README.md)。

验证应包含引用、否定、新主题、短跟进、跨任务目标、混合任务模型调用和历史截止；真实边界准确率仍需要独立标注。

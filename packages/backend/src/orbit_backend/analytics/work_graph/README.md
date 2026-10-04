# Work Graph：共享任务关系

Work Graph 为同一任务的工具、模型、子代理、验证、交付、反馈和指令提供共享身份。分析在请求内建立关系索引，各特征族复用 task_uid 和证据；来源保持只读，图不形成第二份持久事实库。

## 节点、边与证据

节点包含 Task、Turn、ToolCall、ModelCall、SubagentRun、Artifact、ArtifactVersion、Delivery、ValidationAttempt、Feedback、Instruction、PreferenceObservation。边包含 BELONGS_TO_TASK、SPAWNS、RETRIES、PRODUCES、REVISES、VALIDATES、EVALUATES、CORRECTS、SUPERSEDES、DERIVED_FROM、VERSION_OF。

所有节点和边提供 `evidence_uids`、`source`、`confidence`、`coverage`、`available_at`。confidence 是证据层级，校准概率保持未知；available_at 包含证据和后补标注的可见时间，不把后来识别的版本提前放入历史。版本必须由明确修订字段提供，文件编辑次数不能生成 v1/v2。

原生任务标识和明确任务边界可支持已确认关系；本地分段是候选。候选任务不会确认失败重试、完整任务验收或长期偏好。子代理只有选中的创建事件或创建调用明确落在任务内，才继承父任务。仅有 parent 元数据不能确定委托的是哪个任务。混合多个任务的模型轮次不强行分配。

## 接口与范围

`GET /v1/analytics/work-graph` 返回完整关系及覆盖诊断；`GET /v1/analytics/tasks/{task_uid}/trajectory` 返回该任务的执行、验证、重试、返工、反馈和证据节点。两个接口沿用 analytics 的项目、时间、来源和会话范围；不在范围内的任务返回 404。独立请求 work_graph 不触发词频、统计和推荐计算。

任务验收仍要求明确、完整且版本/范围匹配的条件集；助手 final 只表示交付观察。文件参数只证明操作意图；未知版本、未知任务和缺少证据分别保留。指令替换必须有明确引用、同一会话和任务、更早的旧要求、相同字段/对象/条件。

## 验证与限制

构造轨迹、历史截止、跨项目、子代理委托、混合任务模型、幂等投影、后补标注时间、非法指令替换和 API 见 [测试](../../../../tests/analytics/test_work_graph.py)。尚无独立人工标注的真实任务边界与产物版本，不能以图节点增加宣称关系准确率。

任务分段与领域标签见[Task](../../../../../../docs/modules/analytics/task.md)，跨层输入边界见[分析契约](../../../../../../docs/contracts/analysis-inputs.md)。

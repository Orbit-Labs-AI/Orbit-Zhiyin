# 推荐引擎

Orbit 保留 App 主推荐栈、analytics 的资源匹配栈以及旧报告兼容入口。它们复用部分事实与资源，但接口和输出不能互换。

| 栈 | 入口 | 实现与用途 |
| --- | --- | --- |
| App engine | `/v1/recommendations*` | `runs.py → engine.build_slate`，供各 surface 卡片 |
| analytics service | `/v1/analytics/recommendations` | `service.recommend`，七类资源匹配与分析输出 |
| 旧报告 | 原画像/报告入口 | `legacy.py` 兼容固定目录匹配 |

## App 主链

同范围事实和问题 → 多路召回 → 加权 RRF → 资格筛选 → 排序 → 多样性/配额选择 → 卡片解释。实现位于 [recommend](../../../packages/backend/src/orbit_backend/recommend/)，路由位于 [routes_recommend.py](../../../packages/backend/src/orbit_backend/services/routes_recommend.py)。

召回包括知识库、精简建议、规则模板、Catalog、模型配置、画像/特征/关系、生成占位和冷启动路径。目录向量未就绪时可能使用词面哈希回退；哈希相似度不是语义 embedding。

资格判断检查来源、兼容性、权限、上下文、已安装与用户反馈等条件。不能因为资源名或类型看似匹配，就跳过不支持、未知或需要更多上下文的状态。生成占位不是已生成产物。

## 分数与收益

RRF 融合不同召回列表的排名；后续排序结合收益、证据置信、效果先验、匹配、安装/常驻成本、风险与个性化。权重和先验属于启发式，权威值在 `recall`、`ranking`、`units` 与 `narrate`，不作为用户效果概率。

App 的 `ui.save` 根据当前范围的轨迹成本、问题操作占比和改善假设给情景估算。审批等待、失败工具、常驻上下文与返工轮次使用不同计量依据。缺计量时保持未估算；同一问题的替代方案不直接相加。估算不证明真实节省，也不自动扣除未知配置成本。

## 偏好与资源输入

analytics service 接收七类资源：`rules_prompts`、`skills`、`plugins`、`mcp`、`hooks`、`model_configs`、`workflows`。资源契约由 [catalog.py](../../../packages/backend/src/orbit_backend/recommend/catalog.py)及其 Schema/校验定义，输入缺失时不能静默换成不相关种子。

偏好按 `task > project > global` 解析，保留本次显式覆盖、历史、撤销和冲突。Instruction 历史不自动成为有效全局偏好；`avoid` 的软排序意义与权限禁止的硬约束不同。偏好只能调整有证据支持的候选，不能绕过资格检查。

## 状态与用户操作

推荐运行保留输入、版本、候选、被拦截原因和最终选择。曝光、反馈、安装和观察到的效果是不同事件；撤销“不适用”等反馈不能删除原始会话事实。查看详情、生成草稿、解析资源和实际安装也分别记录。

支持的资源经过 `resolve → plan → preview → apply`，撤销按已写内容和冲突检查进行，见[安装模块](../install/README.md)。可选 AI 重排、扩展和专家建议由授权与任务机制控制，不能再笼统称整个 App 推荐路径“永不调用模型”。

## 验证

构造案例覆盖召回、资格、范围隔离、偏好、失败降级和安装解析；历史结果见[推荐审计](../../audits/recommendation-validation.md)。未来效用需冻结过去预测，在隔离的后续任务上比较，见[Benchmark 协议](../../../evals/benchmark/README.md)。

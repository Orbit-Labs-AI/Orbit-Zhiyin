# 原始 UI 到分析指标的对应

本页依据可运行的 [Lite 原型](../../../prototypes/lite/orbit-benchmark-demo.html) 与 [Advance 原型](../../../prototypes/advance/orbit-demo.html) 的渲染函数和交互核对，而非仅依据架构表。下列行号对应 2026-10-02 本次核对版本；后续修改优先按函数名定位。

## 基础统计与单位

| UI 与来源 | 展示字段及单位 | 计算约束 |
| --- | --- | --- |
| Lite `PAGES.overview`，HTML 601；Advance `PAGES.overview`，`src/js/40-a1-overview.js:15` | 会话（个）、发出消息（条）、纠偏率（%）、累计协作跨度（h） | 会话与消息按筛选后的可靠身份计数；率汇总分子分母，缺来源不记零。 |
| Advance `TIPS.def`，`src/js/35-visuals.js:43`；Lite HTML 601 | 从首条消息到最后 Agent 输出的会话跨度之和，含并行重叠 | 与真实人工工时分开。仅首末观测事件可用时，明确标为“观测跨度”；不能声称已扣除空闲、等待。 |
| Lite `sessionDetail`，HTML 614；Advance `PAGES.sessions`，`src/js/42-a3-sessions.js:153` | 开始/结束/最后活跃时间、时长（m）、轮次、消息、工具、错误、纠偏、Tokens | 消息不等同于轮次；保留每项来源与未知量。列表按最后聊天时间降序，未知时间置后。 |
| Lite `PAGES.projects`，HTML 621；Advance `PAGES.projects`，`src/js/44-a5-projects.js:28`、31、33、39 | 项目数、各项目会话/轮次/消息、累计跨度（h）、平均会话跨度（m）、Agent 占比（%）、日均会话 | 项目按 canonical identity 归并；未知项目不伪造名称。日均需声明活跃日或所选日历日作分母；原 Advance 使用活跃日。 |
| Lite `dailyChart`，HTML 599；Advance `series`，`src/js/15-derive.js:61` | 按日消息（条）、会话（个）、Agent 堆叠、Tokens（M） | 桶使用显示时区；累计 Token 快照不可平均摊入各日。 |
| Lite `hourChart`，HTML 600 | 星期 × 小时，分钟 | 按会话覆盖时段跨小时切分、累加，含并行重叠；不是发出消息条数。 |
| Advance `heat`，`src/js/15-derive.js:67`，概览热力图 | 星期 × 小时，消息（条）与纠偏（次） | 与 Lite 分钟热力图保留为不同度量；真实记录按消息实际时间入桶。 |
| Lite `taskTimeline`，HTML 612 | 关键任务、最后活跃时间、关联会话 | 原 UI 按任务最后活跃排序；必须保留任务边界和证据，不用固定时间比例重建关键节点。 |
| Advance `filterRow`，`src/js/25-nav.js:49`、59、61；Lite HTML 575–590 | 7/30/90 天、全部、Agent、项目 | 导出同一筛选范围和时区；声明滚动时段或本地日历日，不混用。补数据最早/最晚时间、覆盖日数、活跃日数便于解释样本。 |
| Lite `download-csv`，HTML 678 | session_id、title、project、agent、last_chat、duration_minutes、messages、tool_calls、errors、corrections、tokens | 本地明细与汇总使用同一口径；时间与缺失值可追溯。 |

## 领域细分

原 UI 的七项 `TOPICS` 位于 Advance `src/js/05-data.js:12` 与 Lite HTML 304，其中 Git/PR、产品设计/部署、论文/LaTeX、数据管线混合了领域和任务方式。原型兴趣画像按涉及会话数呈现（Lite `PAGES.sentiment`，HTML 624；Advance `PAGES.sentiment`，`src/js/45-a6-sentiment.js:25`），不是关键词命中次数。

分类应分别提供 `domain`、`subdomain`、`task_type`：例如软件工程下的前端 UI、后端 API、数据库/数据管道、测试与质量、部署运维；研究下的文献检索、论文写作、实验与评估；产品设计下的需求/交互/视觉；同时以独立任务类型表达实现、调试、审查、写作、配置等动作。子类必须有直接文本证据和版本化语料，未命中、冲突或只提及的对象保留未知/候选。

每项展示任务数、涉及会话数与项目数，保留多标签和未知覆盖。任务等权聚合，不因同一任务反复提到某词而增加兴趣权重。领域点击应能筛回对应任务与会话；项目分布只使用该项目自己的证据。

## 原型中的示例值不可复制为真实结果

- Advance `src/js/15-derive.js:23` 和 Lite HTML 494 将工具数乘 `1.54` 模拟 Agent 步数；真实统计应使用工具调用和回复事件。
- Advance `src/js/44-a5-projects.js:25` 将目录占比写成 `72%/28%`，第 40 行固定工作流支持度 `61%`；不能据此生成真实目录或工作流统计。
- Lite HTML 621 的项目完成度是 `(完成会话 + 0.5 × 部分完成会话) / 会话数` 示例代理，页面已明确其不代表项目进度。缺完整验收集合时继续未知。
- Lite HTML 601 的语言排行单位为文件操作次数；人类消息中的扩展名提及必须使用另一个名称，不能冒充文件操作量。
- 两版人格值、情绪均值、预估节省收益、配置快照均依赖模拟或额外来源。缺证据时输出未知，不能把截图上的数值或公式当成已验证规则。

## 工具调用顺序合同

canonical 调用的 `call_event_uid` 必须连接到所选事件中的同会话 `tool.call`，使用该事件唯一有效的原生 `seq`。缺失、被筛除、重放、重复事件身份/序号、来源冲突均保留 `seq=null` 和原因。列表位置、时间戳、工具名、调用 ID 都不能补造邻接顺序。有未知位置的会话不推断连续失败或重试邻接；工具次数和显式失败证据仍可独立统计。

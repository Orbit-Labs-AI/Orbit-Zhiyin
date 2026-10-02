# Instruction 指令／控制方式

本族位于「非语义 · 用户画像」象限，记录用户本次怎样要求 agent 工作。当前实现使用可复现的词面规则，不把工具审批次数、执行行为或模型回复当成用户授权，不生成控制欲、人格或任务成功评分。关联 [Issue #4](https://github.com/ActionMesh-AI/Hackathon/issues/4)。

2026-10-02：由 `MistyHuang03` 发起、Codex 实现和技术验证；特征口径与 MVP 范围仍待团队确认。代码和测试的完成不等于团队已经确认自然语言分类的完整性。

## 目录与兼容

| 文件 | 职责 |
| --- | --- |
| [text.py](text.py) | 真人正文、系统包装、引用与内联标识符处理 |
| [structure.py](structure.py) | 原有 13 个提示词结构字段及输入校验 |
| [extraction.py](extraction.py) | 八个明确指令字段、证据、按消息汇总 |
| [scope.py](scope.py) | 单任务、指定时点的历史、显式替换与冲突 |
| [dictionary.py](dictionary.py) | 本族字段定义，注册到全局特征字典 |
| [单元／功能／质量测试](../../../../tests/analytics/instruction) | 对应行为与边界回归 |

旧的 `analytics.features.structure` 仍导入同一个函数，已有 `prompt_structure`、会话、项目和 CLI 输出继续可用。`constraint_density` 只保留兼容，已标记 deprecated，不扩展为综合评分。其他特征族继续由原模块负责。

`instruction-v1` 是独立规则版本；总分析摘要包含该版本，避免旧缓存混用。全局 `feature_schema_version` 保持兼容；本族版本见 `instruction.schema_version`。

## Feature 完成状态与口径

以下“已实现”仅指规则、接入和技术测试完成。未命中任何受支持句式时返回未知，不能解释成用户没有要求。

| 字段 | 粒度／类型 | 已实现 | 暂未覆盖 |
| --- | --- | --- | --- |
| `requested_autonomy` | 消息／证据项列表 | `ask_first`、`scoped`、`explicit`；保留原文和条件 | 隐含许可、上下文省略、任意复杂否定 |
| `execution_order` | 消息／证据项列表 | `plan_first`、`discuss_first`、`execute_first` | 任意多阶段有序流程 |
| `verification_requirements` | 消息／证据项列表 | 明确要求测试、检查、构建；排除“不要运行测试”等否定 | 自动拆解每个检查的对象、时机、报告格式 |
| `allowed_scope` | 消息／证据项列表 | 明确“只修改／允许修改”等；文件名关联 | 目录继承、项目别名、指代对象的自动解析 |
| `prohibited_actions` | 消息／证据项列表 | 不要／禁止／do not 等明确禁止，保留条件 | 双重否定、例外的逻辑推理 |
| `acceptance_criteria` | 消息／带稳定 ID 的证据项列表 | 明确“验收标准／acceptance criteria”；保留标准全文 | 自动关联实际测试结果并判定通过 |
| `format_requirements` | 消息／证据项列表 | 明确 JSON、Markdown、表格、列表要求 | 隐式格式偏好、跨任务长期偏好 |
| `tool_requirements` | 消息／证据项列表 | 明确使用 pytest、git、bash、ruff、MCP、skill | 任意工具名实体识别、实际调用符合度 |

已有结构函数的改进：先剔除引用和包装，再测量正文；校验 `original_chars` 与上游结构计数；禁止布尔值、负值和未知键覆盖输出。被移除的代码块数量仍未知，截断文本仍标为下界。

## 输入、输出与证据

输入是 `analysis-input-v1` 事件；必需 `event_uid/session_uid/seq/kind`，另读取 `actor/text/ts/attrs`。提取函数只接受调用方明确给出的主会话集合中 `actor=human/user` 且 `attrs.origin=human` 的 `message.user`，并排除 replay/duplicate 关系。不会将来源未知的 user 记录升级为真人。

每条真人消息产生一条 record：

- `features` 含上述八个字段；每个值为证据项列表或 `null`。`constraints` 是同一证据项的扁平列表。
- 每项保存 `constraint_uid/event_uid/session_uid/task_id/seq/ts`、`feature/value/text`、`targets/condition/action`、来源和提取方式。
- `text` 是移除包装／引用并脱敏后的原文子句。`targets` 当前只结构化受支持扩展名的显式文件引用，无法确定对象时为 `null`；其他对象仍保留在原文。
- `condition` 保留条件子句全文，不判定条件已满足。文本不可用、无直接正文、未命中和截断分别记录缺失原因。
- 同一消息中重复的同字段、同值、同子句只记一次；ID 与规则版本和证据绑定，重复分析结果稳定。输出不会修改输入。
- 不输出原始密钥。原始对话和完整派生结果只保存在本地，公开文档只保存合成样例与汇总。

时间均为来源报告的 UTC 毫秒；缺失不猜测。事件顺序采用 `seq`。service 的筛选遵守现有 `Scope`（含会话、项目、时间、模型、scene）；本族只消费筛选后的主会话消息。

## 分析函数

### `instruction_text(text)` 与 `structure(event)`

前者使用现有正文过滤器，再去除中英文引号和句子型内联代码；保留 ASCII 文件／工具标识符。后者返回兼容的结构计数；无文本返回 `None`，零长度分母返回 `None`，上游提供的结构覆盖仅接受已知字段的非负整数。

### `extract_instruction_constraints(messages, *, main_ids)`

按会话与 `seq` 排序、筛选真人来源、规范化文本、切分子句、匹配明确句式并记录证据。文件扩展名中的点不切句；独立逗号指令分别处理否定；历史陈述、引用、解释请求与否定检查有回归用例。属于保守候选提取，尚不是任意自然语言的完整解析器。

### `resolve_instruction_scope(instructions, task, at=None)`

`task` 必须显式包含 `session_uid/task_id`。`at` 是包含该时刻的截止时间（`ts <= at`）；这与 service 的 `until_ts` 右开边界不同。

仅查看同一会话、同一任务的可见记录。时间不明且指定截止时刻、任务不明、条件未求值的要求分别列在 `unresolved`。后出现的句子不会自动覆盖旧要求。只有上游明确提供 `supersedes_instruction_ids`，且旧项更早、字段／目标／条件完全一致时才替换；无效关系另报。输出保留完整 `history`。

先问与无条件授权、先执行与先规划／讨论、同动作且对象重叠的允许／禁止分别报冲突；受限范围与明确授权可以并存。冲突和条件项不进入 `active`。当前无法对目录包含关系、复杂动作或跨字段例外作完整判定；`resolved` 只表示受支持比较中未发现未决项，不代表完整权限政策已验证。

### `summarize_control_patterns(instructions, scope=None, *, source_available=True)`

按真人消息统计：每个字段返回有效样本、未知样本、命中比例和类别分布。同一消息同类别只计一次；不同类别可以同时出现，不能把分布相加当消息总数。分母为已筛选的真人消息；零分母比例为 `null`。有分母但无信号的 0 是“规则命中率为 0”，不证明没有要求。

可选 `scope` 仅进一步筛选时间；会话／项目／模型／scene 必须事先由 engine 选择。源事件不可用时返回 unavailable 和 `null` 总量。汇总描述观察到的请求，不冒充历史解析后的当前有效政策。

## 对外接入

- `GET /v1/analytics/instruction`：共享筛选、覆盖信息、本族版本、records 与 summary；不运行聚类。
- 会话详情 `GET /v1/analytics/sessions/{id}`：`session.instruction`。
- overview 的 `instruction` 和每个 project 的 `instruction`：同一筛选下的消息级汇总。
- `tandem analytics --no-text --output .local/analytics.json`：顶层 `instruction`。
- 缺失源事件返回 `records=null`；有数据但选中零条时为 `records=[]`。跨任务关联只使用上游 `task_id`；旧适配器的任务划分仍是原实现。

## 验收样例

| 输入 | 预期 |
| --- | --- |
| 先给方案，等我确认后再改文件 | ask_first + plan_first；条件保留 |
| 只修改 `src/a.py` | scoped + allowed_scope，文件证据 |
| 不要推送，请运行测试 | 禁止推送 + 核验要求，否定不污染后半句 |
| 验收标准：全部测试通过 | acceptance_criteria；不凭空判定已通过 |
| “不要运行测试”／代码块中的指令 | 无当前指令信号 |
| We run tests every day／请解释先给方案是什么意思 | 不作为本次操作指令 |
| 后续允许修改同一文件但无明确替换关系 | 保留两条版本，冲突待确认 |

完整 48 例及预期标签见 [质量夹具](../../../../tests/fixtures/instruction-quality.json)。五类测试的实测结果、命令和限制见 [验收记录](../../../../docs/backend/instruction-validation.md)。

## 待完成／待测试

- [ ] 团队确认类别、覆盖口径和优先级；技术实现不代替三人确认 MVP。
- [ ] 补充经授权、来源确认且有明确指令正例的真实数据；当前固定快照没有规则命中正例。
- [ ] 独立人工标注、跨项目／跨语言泛化与规则外句式评估。
- [ ] 完整目录／项目／对象范围、复杂条件例外和自然语言撤销／替换。
- [ ] 核验项与 Outcome 客观结果逐项匹配；不把测试请求当测试通过。
- [ ] 更大规模、多进程并发、冷启动与冲突密集输入的容量测试。冲突比较最坏仍可随互相冲突的目标组数平方增长。

# Instruction 指令／控制方式

这部分记录用户**这一次让 agent 怎么做**：要不要先问、先做哪一步、能改哪些文件、哪些操作不能做，以及要怎样检查结果。每条识别结果都保留对应的原话，方便回看依据。

例如，“先给方案，等我确认后再改文件”包含两层要求：现在先给方案，改文件要等确认。长期适用的习惯由 Preference 处理；这里专注本次请求，属于分类文档中的「非语义 · 用户画像」象限。

**本轮代码重构、函数接入和五类测试已完成。** 现有实现采用固定的中英文规则，只能识别部分明确说法。没识别出来时记为未知，不代表用户没有要求。真实数据流程已跑通，但样本中没有指令命中正例，识别质量还需要补充真实样本验证。

2026-10-02，由 `MistyHuang03` 发起，Codex 实现和技术验证。用户已在本次对话确认，三位成员对本次 MVP 范围的确认、`yhyfhgs` 对 PR #16 的合并授权均已满足；独立人工质量评估尚未完成。[PR #16](https://github.com/ActionMesh-AI/Hackathon/pull/16) · [Issue #4](https://github.com/ActionMesh-AI/Hackathon/issues/4) · [五类测试记录](../../../../docs/backend/instruction-validation.md)。

## 能看出什么

| 字段 | 回答的问题 | 当前做到哪一步 |
| --- | --- | --- |
| `requested_autonomy` | 改之前要先问，还是可以自主完成？ | 支持先问、有限范围自主、明确自主授权；隐含许可和复杂否定待补。 |
| `execution_order` | 先给方案、先讨论，还是直接执行？ | 支持常见明确说法；多阶段流程及部分连写句式待补。 |
| `verification_requirements` | 用户要求运行什么检查？ | 支持“请运行测试”等说法；“请检查代码”“请构建项目”仍可能漏识别。 |
| `allowed_scope` | 允许处理哪些文件或对象？ | 能记录明确范围及文件名；目录、项目别名和指代对象待补。 |
| `prohibited_actions` | 哪些操作不能做？ | 能记录明确禁止及条件；复杂例外和部分动作冲突待补。 |
| `acceptance_criteria` | 用户怎样判断任务完成？ | 保留明确写出的验收标准；尚未对照实际结果判断是否达标。 |
| `format_requirements` | 要用什么格式输出？ | 支持 JSON、Markdown、表格、列表等明确要求。 |
| `tool_requirements` | 用户指定了哪些工具？ | 支持 pytest、git、bash、ruff、MCP、skill 等明确要求；任意工具名待补。 |

以上字段都返回带原文的条目列表或 `null`。程序不会根据工具审批次数、agent 的行为或回复倒推用户授权，也不会据此给用户打性格分。

## 分析函数做什么

| 函数 | 输入 → 输出 | 主要用途 |
| --- | --- | --- |
| `instruction_text / structure` | 消息 → 清理后的正文／结构计数 | 延续原来的字符数、文件引用和格式词等统计。 |
| `extract_instruction_constraints` | 真人消息 → 明确要求和原文证据 | 找出这一次说了什么要求。 |
| `resolve_instruction_scope` | 指令历史、任务、时点 → 可用要求、冲突和待确认项 | 回看某个时刻有哪些要求，保留无法判断的部分。 |
| `summarize_control_patterns` | 已筛选的消息记录 → 各类要求的数量和比例 | 看所选消息中出现了多少明确要求。 |

例如，10 条真人消息里有 3 条命中核验要求，命中比例就是 30%；另外 7 条保持未知。同一消息可以同时要求测试和禁止推送，不同类别的比例不能简单相加。

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

原有结构函数也补了输入检查：先清理引用和包装，再测量正文；上游提供的字符数和结构计数只接受已知字段的非负整数。移除后无法还原的代码块数量仍记为未知，截断文本的计数只表示已看到的部分。

下面保留接入所需的参数、时间边界和返回值说明。

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

## 函数参数与处理规则

### `instruction_text(text)` 与 `structure(event)`

前者使用现有正文过滤器，再去除中英文引号和句子型内联代码；保留 ASCII 文件／工具标识符。后者返回兼容的结构计数；无文本返回 `None`，零长度分母返回 `None`，上游提供的结构覆盖仅接受已知字段的非负整数。

### `extract_instruction_constraints(messages, *, main_ids)`

按会话与 `seq` 排序、筛选真人来源、规范化文本、切分子句、匹配明确句式并记录证据。文件扩展名中的点不切句；独立逗号指令分别处理否定；历史陈述、引用、解释请求与否定检查有回归用例。只识别规则明确支持的说法，其他表达可能漏掉。

授权类别为 `ask_first`（先问）、`scoped`（有限范围自主）、`explicit`（明确自主授权）；顺序类别为 `plan_first`、`discuss_first`、`execute_first`，分别表示先规划、先讨论、直接执行。

### `resolve_instruction_scope(instructions, task, at=None)`

`task` 必须显式包含 `session_uid/task_id`。`at` 是包含该时刻的截止时间（`ts <= at`）；这与 service 的 `until_ts` 右开边界不同。

仅查看同一会话、同一任务的可见记录。时间不明且指定截止时刻、任务不明、条件未求值的要求分别列在 `unresolved`。后出现的句子不会自动覆盖旧要求。只有上游明确提供 `supersedes_instruction_ids`，且旧项更早、字段／目标／条件完全一致时才替换；无效关系另报。输出保留完整 `history`。

先问与无条件授权、先执行与先规划／讨论、同动作且对象重叠的允许／禁止分别报冲突；受限范围与明确授权可以并存。冲突和条件项不进入 `active`。目录包含关系、复杂动作和跨字段例外还不能完整判断。`resolved` 只表示当前规则没有发现待确认项，不能直接当作执行操作的授权。

### `summarize_control_patterns(instructions, scope=None, *, source_available=True)`

按真人消息统计：每个字段返回有效样本、未知样本、命中比例和类别分布。同一消息同类别只计一次；不同类别可以同时出现，不能把分布相加当消息总数。分母为已筛选的真人消息；零分母比例为 `null`。有分母但无信号的 0 是“规则命中率为 0”，不证明没有要求。

可选 `scope` 仅进一步筛选时间；会话／项目／模型／scene 必须事先由 engine 选择。源事件不可用时返回 unavailable 和 `null` 总量。这些统计说明用户说过什么；若要查询某一时刻可用的要求，需要另用范围函数。

## 对外接入

- `GET /v1/analytics/instruction`：共享筛选、覆盖信息、本族版本、records 与 summary；不运行聚类。
- 会话详情 `GET /v1/analytics/sessions/{id}`：`session.instruction`。
- overview 的 `instruction` 和每个 project 的 `instruction`：同一筛选下的消息级汇总。
- `tandem analytics --no-text --output .local/analytics.json`：顶层 `instruction`。
- 缺失源事件返回 `records=null`；有数据但选中零条时为 `records=[]`。跨任务关联只使用上游 `task_id`；旧适配器的任务划分仍是原实现。

## 验收样例

| 输入 | 预期 |
| --- | --- |
| 先给方案，等我确认后再改文件 | ask_first + plan_first；后续确认条件不限制前面的计划 |
| 只修改 `src/a.py` | scoped + allowed_scope，文件证据 |
| 不要推送，请运行测试 | 禁止推送 + 核验要求，否定不污染后半句 |
| 验收标准：全部测试通过 | acceptance_criteria；不凭空判定已通过 |
| “不要运行测试”／代码块中的指令 | 无当前指令信号 |
| We run tests every day／请解释先给方案是什么意思 | 不作为本次操作指令 |
| 后续允许修改同一文件但无明确替换关系 | 保留两条版本，冲突待确认 |

完整 48 例及预期标签见 [质量夹具](../../../../tests/fixtures/instruction-quality.json)。五类测试的实测结果、命令和限制见 [验收记录](../../../../docs/backend/instruction-validation.md)。

## 待完成／待测试

- [x] 本次有限规则 MVP 的三位成员范围确认及 `yhyfhgs` 合并授权：用户在本次对话中确认均已满足。后续能力另行评估。
- [ ] 补充经授权、来源确认且有明确指令正例的真实数据；当前固定快照没有规则命中正例。
- [ ] 独立人工标注、跨项目／跨语言泛化与规则外句式评估。
- [ ] 完整目录／项目／对象范围、复杂条件例外和自然语言撤销／替换。
- [ ] 核验项与 Outcome 客观结果逐项匹配；不把测试请求当测试通过。
- [ ] 更大规模、多进程并发、冷启动与冲突密集输入的容量测试。冲突比较最坏仍可随互相冲突的目标组数平方增长。

## 评审中暂缓的三项 P2

按用户“非 P0/P1 可以忽略”的指示，以下问题本轮保留为待办：

- “请检查代码”“请构建项目”可能漏识别为核验要求。[原意见](https://github.com/ActionMesh-AI/Hackathon/pull/16#discussion_r4163524616)
- “无需确认直接执行”“不要询问直接执行”这种没有标点的连写，可能漏掉“直接执行”的顺序要求。[原意见](https://github.com/ActionMesh-AI/Hackathon/pull/16#discussion_r4163547545)
- “Run build”与“Do not run build”可能没有被判成冲突；build、ruff、lint 等动作的对应关系还不完整。[原意见](https://github.com/ActionMesh-AI/Hackathon/pull/16#discussion_r4163547547)

后续需要为这些说法补规则和测试。现有样例通过不表示这些问题已经解决。

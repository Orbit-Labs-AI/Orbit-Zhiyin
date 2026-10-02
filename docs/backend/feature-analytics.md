# Feature Analytics MVP：先测量，再解释

本版在 `feat/plain-language-backend` 的后端上增加独立分析入口，消费 [analysis-input-v1](../plan/analysis-inputs.md)。已有画像、报告、推荐和评价接口保持原行为。新接口只做测量、代理信号和无监督文本表示，不输出人格、任务成功率、项目完成百分比或推荐。

已经跑通：SQLite 历史 → 输入适配与覆盖说明 → 会话/工具/时间/流程特征 → 项目聚合 → 本地 TF-IDF/SVD/DBSCAN → 二维坐标 → API/CLI。代码可运行不代表所有目标输入已经具备；尤其真人来源、逐次模型用量、子代理树仍不完整。

## 先看这次真实数据告诉了我们什么

2026-10-02 使用本机已有 `.local/history.sqlite`，沿用原有固定快照：截至 **2026-10-01 23:43:13，Asia/Shanghai**，继续排除原先的一条评价会话。重新导入采用 parser 26，没有扩大时间范围。共发现 121 份文件：36 份进入台账、83 份非用户会话跳过、1 份评价会话排除、1 份在快照之后。台账有 41,740 个标准化事件。

分析进一步排除 1 个缺复制段边界的 fork。保留 35 个会话、40,664 个事件；其中 33 个有原生主会话来源证明，2 个会话种类仍未知。这里的排除是保守取舍：少计一段可说明的记录，比重复统计复制历史更可复核。

| 实际观测 | 数值 | 可以说明什么 |
| --- | ---: | --- |
| 逻辑工具调用 | 11,657 | 调用和返回已配对，按调用计一次 |
| 有结果 / 未配对 | 11,657 / 0 | 此次台账内的配对完整，不证明原始世界没有遗漏 |
| 明确成功 / 明确失败 | 4,375 / 768 | 仅按已有协议状态，不读 stdout 猜成功 |
| 状态未知 | 6,514（55.88%） | 不能默认计为成功 |
| 已知成功或失败中的失败率 | 768 / 5,143 = 14.93% | 是已知状态子样本的比例，不能外推任务失败率 |
| 工具日志时间差中位数 | 319 ms | 属于 estimated/event_difference，不是原生执行耗时 |
| 可靠起止区间的并集 | 未知 | 旧导入器只有写入时间差；不能据此计算工作投入 |
| 连续失败的相邻调用对 | 141 | 最长连续失败段为 6 次；不等于同参数重试 |
| 同工具、同参数、同状态范围的失败重复 | 0 / 140 对可检查样本 | 另 1 对缺少兼容范围；不能把 141 都称为重试 |
| 明确轮次中断 | 70 | 只说明协议中断，不说明谁打断、是否浪费 |
| 确认真人输入 | 9 条，分布在 5 个会话 | 保守接受原生输入回执、问答答案或明确 origin |
| 其余来源未知的 user 消息 | 918 条 | user 角色本身不足以确认真人，未进入语义分母 |
| 文本聚类 | 5 个样本，1 个簇、3 个噪声点 | 验证算法与前端数据链路；不足以代表完整任务分布 |

工具操作分布在 68 个日期；确认真人输入只覆盖 5 个日期。两者来自不同有效样本，不能把工具活动直接当作人的作息。时间桶明确采用上海时区，这只是显示选择，不是历史时区证据。

### 案例一：工具很多，失败结论仍要限制分母

按调用次数排序的一个匿名会话有 **2,913 次工具调用、955 条保留助手消息、67 次明确工具失败**。其中 367 条 user 角色消息缺少明确真人来源，真人输入数输出 `null`，不写成 0。这个例子可以展示工具密度和流程；它不能支持“用户很少发言”“自主性高”或用户满意的判断。

全局常见工具为 `exec`（5,551 次）、`exec_command`（4,390 次）、`apply_patch`（625 次）、`write_stdin`（482 次）。`exec` 有 4,778 次状态未知：外层脚本返回不代表所有内层操作成功。`apply_patch` 当前 625 次均未取得可确认的成功协议；这也不代表它们失败了。

### 案例二：重复转移不是重复失败

观察到 `TOOL_CALL → TOOL_RESULT` 9,296 次、`TOOL_RESULT → TOOL_CALL` 6,041 次。按会话内“此前出现过的边再次出现”的定义，重复转移率为 **99.09%**。工具往返本来就会反复出现，因此这个值描述流程结构，不能直接命名为卡点或低效。相同参数失败重复另按工具身份、参数摘要和 status_scope 检查，结果见上表。

### 案例三：坐标已能交给前端，语义覆盖还很小

5 个有确认真人输入的主会话得到 `cluster_id / novelty / embedding_x / embedding_y`。簇不命名，噪声的 `cluster_id=-1`，没有文本证据的会话坐标为 `null`。当前字符词项中存在普通英文片段，说明小样本的字面相似性尚不能说明任务主题；文档不把这个簇解释成人格或兴趣。

新颖度只使用严格更早的会话，连 TF-IDF 的 IDF 和 SVD 都只在过去样本上拟合。会话文本要到最后一条参与输入的时间才算可用；同一时间的样本互不作为前序；缺时间或没有严格更早样本时为未知。这个分数只是表示空间的相对距离，不是任务创新程度。

真实会话 ID、项目名称、词项和证据下钻保存在本地 `.local/feature-analytics/`。仓库文档只给匿名案例和必要汇总，完整聊天、路径和私有报告不提交。

## 为什么这样实现

- **边界薄，算法独立。** `analytics/inputs.py` 用一次 SQLite 读取事务适配旧 Store；算法只接收 `AnalysisInputBundle`。未来 L2/L3 接入可以替换适配器，不必改全部算法。
- **旧字段不改名冒充新字段。** `session.model` 不生成 model_call；cwd 分组用 `legacy_project_id`；旧 `parent_id` 实际是 forked_from，不当子代理父关系。
- **统计与上下文分开。** 时间范围为 UTC 毫秒 `[from_ts, until_ts)`。时间未知的关联返回可支持工具状态与顺序，但不进入时间分桶；上界之后的明确返回不能泄漏进快照。
- **不缓存原始历史副本。** 分析可丢弃、可重算。输出带输入内容摘要、parser/adapter/feature/vectorizer 版本与 scope。每次查询重算，不维护另一套原始事件库或 7/30/90 天汇总表。
- **文本先用会话粒度。** 既有 task_contexts 仅复用到场景/同任务反馈关联，未新增任务分段算法。旧输入的任务/血缘边界不够稳定，文本表示选择确认的主会话。
- **依赖保持本地。** 字符 2–4 gram TF-IDF（最多 20,000 特征）→ 至多 32 维 TruncatedSVD（seed=0）→ L2 归一化；DBSCAN 使用 cosine 距离、eps=0.35、min_samples=2，至少 4 个文本样本才聚类。2D 使用 PCA；少量或相同样本可退化为零坐标。

算法参数是固定的 MVP 选择，未通过用户标签调参。DBSCAN 不强行指定簇数；所有点都是噪声也是合法结果。API 的 `feature_dictionary` 保存每项单位、规则、分母、类型及证据位置。算法依据可核对 [TF-IDF 文档](https://scikit-learn.org/1.7/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html)、[TruncatedSVD 文档](https://scikit-learn.org/1.7/modules/generated/sklearn.decomposition.TruncatedSVD.html) 和 [DBSCAN 文档](https://scikit-learn.org/1.7/modules/generated/sklearn.cluster.DBSCAN.html)。

## 怎样复跑与接前端

```sh
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
# 沿用已有导入快照和排除项；不要 reset 样本策略。
.venv/bin/tandem --db .local/history.sqlite import --codex-home "$HOME/.codex"
.venv/bin/tandem --db .local/history.sqlite analytics \
  --display-timezone Asia/Shanghai --output .local/feature-analytics/analytics.json
.venv/bin/tandem --db .local/history.sqlite serve
.venv/bin/pytest -q
.venv/bin/ruff check src tests
```

`analytics --no-text` 可只跑确定性测量。新的范围参数是 `--from-ts / --until-ts`（UTC ms）、可重复的 `--project-id / --legacy-project-id / --model-id / --effort-raw / --root-session-uid / --exclude-session`、`--no-include-children` 和 `--scene`。旧导入 `before` 为包含截止点的毫秒边界，入口明确记录等价 `until_ts = before + 1`，没有只改参数名。

| GET 路径 | 主要内容 |
| --- | --- |
| `/v1/analytics/overview` | 规模、有效分母、用量状态、活动节律、常见工具与语言线索 |
| `/v1/analytics/sessions` | 分页摘要、身份质量、特征、簇、新颖度、坐标；默认 50、最多 200 |
| `/v1/analytics/sessions/{id}` | 完整特征、工作流、调用序列、证据 ID、覆盖 |
| `/v1/analytics/tools` | 各工具状态、未知/未配对、时长分位数、转移矩阵 |
| `/v1/analytics/projects` | 同一特征引擎的项目聚合；当前标为 legacy_path |
| `/v1/analytics/text` | 字符 n-gram 词项、纠偏词、无名称簇、二维坐标 |

全部返回 `scope / coverage / source_coverage / effective_samples / unknown_counts / versions / sample_boundary`。`coverage.rows` 对应当前选择，`source_coverage` 描述台账输入。列表参数用重复 query key；显式空参数如 `project_ids=` 表示选择零个项目。当前旧库传规范 `project_ids` 或请求级 `model_ids/effort_raw` 会收到 **422 和具体原因**，避免用近似字段悄悄筛出错误数据。路径聚合使用 `legacy_project_ids`。

服务默认只监听本机。列表返回紧凑摘要，详情才带调用链。旧 `demo / evaluate / import / report / serve` 保留；新增分析不请求远程 LLM，也不访问用户目录做配置扫描。

一段真实实跑结果的匿名摘录（完整 schema 以 JSON 为准）：

```json
{
  "input_contract": "analysis-input-v1",
  "feature_schema_version": "feature-analytics-v1",
  "scope": {"display_timezone": "Asia/Shanghai", "from_ts": null, "until_ts": null},
  "effective_samples": {"main_sessions": 33, "human_messages": 9, "tools": 11657, "text_sessions": 5},
  "unknown_counts": {"human_origin": 918, "session_kind": 2, "timestamp": 0, "model_calls": null},
  "overview": {"usage": {"request_count": null, "total_tokens": null, "cost_usd": null}},
  "tools": {"totals": {"known_failure_count": 768, "unknown_status_count": 6514, "failure_rate": 0.1493291853}},
  "text": {"clustering": {"status": "available", "cluster_count": 1, "noise_count": 3}}
}
```

## Feature Dictionary

状态按具体数据而变化。`available` 是在已读取范围内可观测；`partial` 表示已知子集，不保证全量；`unavailable` 对应 `null`；`excluded` 是调用方/样本策略排除。实际数值 0 只能描述可观测样本中未出现，不能掩盖未知行。下面将同公式的字段合并列出；机器字典逐项展开。

| feature | level | source | formula/rule | denominator | missing semantics | confidence/type |
| --- | --- | --- | --- | --- | --- | --- |
| user_message_count | session/aggregate | main + message.user + actor/origin | 仅确认真人；子代理注入不计 | 无 | 未知来源单列，只有未知时 null | deterministic derived |
| assistant_message_count / total_event_count | session | 保留消息/事件 | 当前选择内计数，非原始日志条数 | 无 | 数据集不可用为 null | direct observation |
| turn_count | session/project | event.turn_uid | 非空轮次去重，不按消息补造 | 无 | 缺轮次未知；unknown_count 单列 | deterministic derived |
| first/last_observed_ts / observed_session_span_ms | session | 事件时间 | min/max/差；UTC ms | 有时间事件 | 无时间为 null；不是工作时长 | deterministic derived |
| avg/median_user/assistant_message_chars | session | original_chars/正文 | 字符均值/中位数 | 可测消息 | 原长优先，否则截断下界；空样本 null | deterministic derived |
| sessions/human_messages/tool_calls/model_usage_by_day、by_hour、weekday_distribution、active_days | aggregate | 相应实体时间 | 依显示时区分桶；模型桶计请求 | 有时间且在范围内的记录 | 缺时间不进桶并报告数量；模型无输入为 null | deterministic derived |
| call_count / paired_result_count / unpaired_count | tool/session | 配对调用 | 一次调用一行 | 无 | 数据集不支持时 null | direct observation |
| known_success/failure / rejected / interrupted / running / unknown_status_count | tool | 明确协议 | 每次调用状态；外层成功不覆盖内层未知/失败 | 无 | 未知单列 | direct observation |
| success_rate / failure_rate | tool | 明确成功和失败 | 成功或失败数 / 二者总数 | 已知 success + failed | 分母 0 为 null | deterministic derived |
| median/p25/p75/p90_duration_ms | tool | 可用时长 | 线性插值分位数，保留 source/quality | 有可用 duration 的调用 | 无值为 null；不同时间质量不冒充同等精度 | deterministic derived |
| duration_sum_ms / reliable_interval_union_ms | tool/workflow | 时长/可靠端点 | 求和 / 端点区间合并 | 各自可用调用 | 缺结束不补 start+duration；无可靠区间为 null | deterministic derived |
| name_raw / kind / mcp_server / mcp_tool / skill / command_head | call | 明确名称及结构字段 | 名称规则归一；不读安装清单猜使用 | 无 | 未保存字段为 null | direct/derived |
| error / branch / rollback_rewind / compaction / permission_request / subagent_spawn / interruption_count | session/workflow | 标准事件 kind | 只数解析器支持的明确事件 | 无 | 未支持种类为 null，不能报 0 | direct observation |
| transitions / normalized matrix | workflow | 会话内 seq | 相邻状态 N_ij；每行除以出边数 | 同一来源状态的出边 | 不跨会话拼 seq，不按时间重排 | deterministic derived |
| repeated_transition_count/rate / max_repeated_transition_run | workflow | 状态序列 | 已出现过的边再出现 / 总边数；相邻同边最长段 | 总边数 | 无转移的比例 null；不解释为低效 | deterministic derived |
| consecutive_failed_calls | workflow | 工具顺序和状态 | 相邻失败对数；另给最长失败段 | 无 | 不称同操作重试 | deterministic derived |
| confirmed_same_argument_failed_retries | workflow | 名称、字面 digest、status_scope | 三者兼容且相邻失败 | 可比较失败对另列 | 缺摘要/范围为未知；包装层仅说明包装重复 | deterministic derived |
| correction_signal_count/rate | session/aggregate | 确认真人规范正文 | 高精度纠偏词命中的消息数/确认真人消息数 | 确认真人消息 | 无真人样本 null；绝非真实纠偏标签 | proxy |
| prompt_char/line / paragraph / question_mark / bullet / numbered_list / URL / file_reference_count | prompt | 规范正文 | 字符、行、分段与结构规则 | 无 | 截断保留下界；不补原始正文 | deterministic derived |
| code_block_count | prompt | 上游结构测量 | 若输入明确提供则使用 | 无 | 旧导入器已去围栏，当前为 null | direct/derived |
| explicit_format_request / explicit_tool_mention / constraint_marker_count、constraint_density | prompt | 真人规范正文 | 明确词/简单规则；密度除以规范正文字符数 | 字符数（仅 density） | 不是人格控制程度；缺输入 null | proxy |
| language_signals | session/aggregate | 正文明示文件扩展名 | 扩展名映射分布 | 出现次数 | 仅文本文件线索，不猜代码语言；引用/围栏已移除 | proxy |
| request_count / token buckets / total_tokens | session/aggregate | 合规 model_call | call/delta + 边界；输入+缓存读+缓存写+输出 | 合规请求 | 任一必需桶缺失，总量未知；reasoning 不再相加 | direct/derived |
| cumulative_snapshots / legacy_latest_reports | session | model.usage | 同键最后可信快照；旧库只保留末次原生报告 | 同计数周期 | 不加快照、不伪造请求、不分摊到天；同键回退标异常；范围不明无规范总量 | direct observation |
| cost_usd / median_latency_ms / median_ttft_ms | request/aggregate | 请求费用与时延 | 有来源的完整费用求和、可用时延中位数 | 可用请求数分别报告 | 无输入 null；价格估计须保留价格表版本 | direct/derived |
| objective_outcomes | session | 工具返回/command_head | 明确失败、验证命令候选 | 无 | 未知验证范围不写全量验证；task_success=null | direct observation |
| subjective_outcome_candidates | session | 同任务最终交付及后续真人 | 完整短句“可以了/还是不行”等 | 有对应交付和反馈的证据 | 无反馈不满意也不不满意；空候选不是成功 | proxy |
| top_terms / cluster_id / centroid distance / embedding_x/y | main session | 确认真人文本 | TF-IDF/SVD/L2/DBSCAN/PCA | 有文本的主会话 | 少于4份不聚类；无文本 null；噪声 -1 | unsupervised representation |
| novelty | main session | 文本及最后输入时间 | 1−max cosine(严格更早样本)；仅前缀拟合 | 更早有效样本 | 无时间/无前序 null；同时间互不比较 | unsupervised representation |

## Input-contract mapping

| contract entity/field | current source | status | notes |
| --- | --- | --- | --- |
| canonical project_id | Store.project_id（cwd 摘要） | legacy-only | 对外另名 legacy_project_id；规范 ID 为 null |
| session identity | 原生会话 id + Store 唯一行 | partial | 无规范 source 身份拼接，多来源合并待数据层 |
| kind/main | session_meta.source + 原生 thread_source=user | partial | parser 26 新存依据；旧 source_kind=user 不能自动升级 |
| root/parent/spawn | main 的 self root；子代理被原导入器排除 | partial | 不把 forked_from 当 parent；主子工具聚合已用合约夹具验证 |
| fork/import replay | 旧 parent_id 实为 forked_from | partial | 无复制段边界的 fork 整体排除；明确 replayed_from/duplicate_of 可剔除 |
| human origin | 明确 origin、原生 user_message 镜像、question_reply.answer | partial | 普通 role=user 保持 unknown；系统围栏、代码、引用仍过滤 |
| turn identity | 原生 turn_id + 会话生成稳定 uid | partial | 没有完整 L3 turn；保留缺失行数量 |
| event order/time | ordinal → seq；原始 timestamp → UTC ms | partial | seq 可用；时间按写入观察解释，缺源端点语义 |
| tool_call pairing | (session_id, call_id) 配对 | available | 标准调用逐行保留；包装内逻辑工具不另计 |
| argument_digest | 截断前完整参数的稳定摘要 | available | 字面摘要，不声称参数规范化；不保存原参数 |
| status_scope | 明确命令/工具/包装返回解析 | partial | 只保留已确认协议；未知不等于成功 |
| duration + provenance | 配对事件时间差 | partial | event_difference/estimated；不生成可靠原生结束端点 |
| model_call/model_id/effort | 旧 event.model / session.model | unavailable | 不升级为逐次请求；相应过滤返回422；未来输入同一轮混用多个模型时，事件归属不明确的轮次不分配给单一模型 |
| usage_scope/measurement | cumulative_tokens | partial | 知道是累计，不知道可信计数周期/覆盖；无 fake model_call |
| snapshot_key / coverage=self/root_tree | 旧库未保留 | unavailable | 不能合并多快照或父子总量 |
| cost / latency / ttft | 无请求级记录 | unavailable | null，不从回复间隔推断 |
| inventory_item | 未接入 | unavailable | 不扫描额外目录；安装不等于调用 |
| context-window observations | 未持久化占用、容量配对 | unavailable | 不用会话累计 token 推占用率 |
| session_feature/link | 部分工具名/文件文本线索 | partial | 无标准 feature/link 输入；只报告明确线索 |
| source/L1/L0 evidence drill-down | 事件 id、源文件当前路径、原行号 | partial | 可看旧 evidence API；无不可变 raw_record/归档代次链 |
| versions/sample boundary | parser policy、内容摘要、固定 before/exclusions | partial | schema_version 无明确版本为 null；redaction_version 未独立保存 |

## 完成度、效果与验证

工程链路已完成，当前数据支持范围明确受限。P0 的基础统计、工具聚合、活动桶、工作流、覆盖语义、API 和 CLI 已可复跑；P0.5 的结构/语言仅覆盖规范真人正文；P1 主观反馈只有保守候选规则。文本表示、聚类、新颖度与坐标已经产出，但实际有效文本只有 5 个会话，应作为接线验收，而非分析质量达标的证明。

新增测试覆盖契约第8节原样夹具、不可用与零、零分母、seq 优先、未知时间、非真人来源、子代理分母、复制历史、配对与包装状态、摘要重试、时长并集、半开边界、未来返回隔离、缓存桶及 reasoning、累计快照不叠加、root_tree、普通否定误报、无沉默验收、聚类退化/分离/噪声/确定性、前缀拟合无未来泄漏、项目/模型/排除过滤、API 与 CLI。

验证基线原有 351 项测试通过。新增功能完成时全量 **397 项通过**，Ruff 通过；Starlette 测试客户端有一条现有 AnyIO 弃用提示。新增 46 项测试；`demo / evaluate / import / report` 已实际复跑，`serve` 的六个新路由通过 TestClient 验证。evaluate 的三个回归集分别为 8/8、34/34、12/12，pip check 无依赖冲突。固定来源的开发夹具用于防回归，不等同于独立的用户效果评测。

## 下一步先做什么

先补**人类输入来源及复制历史边界**，再重跑同一快照，核对有效文本样本从 5 个增长多少、是否仍受同一项目或长会话主导。随后接入请求级 model_call 和规范项目身份，才能可靠做模型/项目比较。最后对真实纠偏和验收样本做独立人工核验，再决定是否加入更强文本表示或学习型画像。前端可以先消费已有坐标及状态，必须展示未知/部分覆盖，不能用零填平缺口。

# Missing inputs needed for future analysis

以下是检查实际 parser 26/Store 后的缺口，不是把契约可选字段机械复制一遍。P0 指阻挡当前完整测量；P1 支持近期 Persona/Bottleneck；P2 主要支持 Recommendation/高级分析。接入责任中的“连接器/数据层”表示分析公式本身无法补造这些证据。

| needed input | contract field/entity | feature blocked | expected producer/source | current status | current proxy if any | why proxy is insufficient | priority |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 每条输入的真实发送来源 | message.user.actor / attrs.origin | 大部分人类输入统计、纠偏、文本覆盖 | Codex/其他连接器读取原生来源、队列与任务通知协议 | 918 条选中 user 消息未知 | role=user 候选，未进真人分母 | 同角色可承载注入、通知、代理文本 | P0 |
| 复制段/重放去向 | L1 disposition、event replay/duplicate 引用 | fork 新行为保留且不双计 | 连接器合并/去重层 | 1 个 fork 整体排除 | 已知 forked_from | 只知道来源，不知道复制到哪一条 | P0 |
| 完整规范逐次请求与桶 | model_call + usage_scope=call、measurement=delta、稳定请求边界 | 模型/档位筛选、调用量、逐次 token 趋势 | 连接器请求与 usage 标准化 | 全部缺失 | 旧模型设置/累计 token 原报 | 最后设置不是每次模型，快照不是请求 | P0 |
| 规范仓库级项目归属 | project/project_id、key_type、project_override | 跨 worktree/克隆项目合并 | 数据层项目派生 | 缺失 | legacy cwd 摘要分组 | 同仓库不同路径会被拆开，同路径也可切仓库 | P1 |
| 会话种类及主子派生关系 | session.kind/root_uid/parent_uid/spawn_call_uid | 真实根工作流、子代理成本与委派过程 | 连接器保留被旧导入器跳过的子会话并关联 spawn | 2 个 kind 未知，子树不可用 | 主会话 self root | 标题、近邻时间、fork 指针均非子代理证据 | P0 |
| 累计周期、维度、覆盖 | model.usage.snapshot_key / coverage | 可信累计总量及父子去重 | 连接器 usage 归一层 | 累计原报存在，键/覆盖缺失 | 每会话末次原报 | 无法证明重置、模型维度、是否含子代理 | P0 |
| 内层逻辑操作、状态范围与返回完整性 | tool_call、status_scope、known/failed/unknown returns | 包装内工具使用、失败定位 | 工具连接器/编排返回协议 | 外层调用可用，内层部分未知 | exec 包装级状态/摘要 | 包装完成或参数相同不能代表内层全成功/同操作 | P1 |
| 原生工具开始与结束 | tool_call native bounds + attrs.time | 可靠区间并集、并发覆盖 | 工具连接器原生端点 | 全量只有日志差 estimated | 11,657 个配对写入时间差 | 写入排队/批量返回不等于实际运行区间 | P1 |
| 原生请求时延和首字时延 | model_call.latency_ms / ttft_ms | 模型响应等待分析 | 模型连接器请求/流式信号 | 缺失 | 无 | 助手写入间隔不能确定请求边界 | P1 |
| 成本与价目证据 | model_call.cost_usd/cost_source + price-table version | 支持范围内费用估计 | 原生用量账单或有版本的模型价目适配 | 缺失 | 无 | token 未规范化，订阅费用亦不能直接反推 | P1 |
| 审批等待与明确过程事件 | permission.request/decision、branch、compaction、error、subagent.spawn | 等待、撤回、压缩及过程计数 | 上游连接器映射并保留标准事件 | 旧 parser 未保存这些种类 | turn.interrupted 有70条 | 中断不是审批/rollback；缺记录不能计零 | P1 |
| 截断前结构统计与完整语言线索 | attrs.prompt_structure / session_feature / tool files | 代码围栏、程序语言与长提示结构 | 导入器在去引用/截断前保存安全结构，不保存私有代码正文 | 规范正文可用，围栏/结构缺失 | 真人正文文件扩展名 | 不能恢复被过滤掉的原始代码与工具文件 | P1 |
| 验证对象、范围与明确验收关系 | 结构化命令结果、file.change、同任务反馈关联 | 完整验证判断、主观结果质量 | 工具连接器 + 后续独立人工标注 | 仅返回状态/少量短句候选 | 验证命令候选、词面反馈 | 命令名不证明覆盖全部测试，短句不构成稳定偏好标签 | P1 |
| 同时刻上下文用量与容量 | context observation event_uid/used_tokens/context_window_tokens | 上下文压力、压缩影响 | 连接器保留运行时窗口观测 | 未持久化 | 无 | 累计 token 不是当前窗口占用 | P1 |
| 历史安装/启用/注入/调用状态 | inventory_item 与 attribution | 配置覆盖、资源推荐 | 配置采集器的历史快照与调用归因 | 未接入 | 明确工具名只能证明调用 | 当前安装不能证明历史启用或使用效果 | P2 |
| 不可变证据代次、来源与版本 | source/source_file/raw_record/L0、redaction_version | 跨来源去重、全文审计、稳定重放 | 数据层归档和版本管理 | 当前路径+行号可回看，非完整归档链 | 已保存事件 id 和内容摘要 | 原文件可移动、变更或丢失，摘要不能恢复正文 | P1 |

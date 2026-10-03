# Feature 到前端指标：映射、计算与降维规则

这层把已经合入的八个特征族转换为前端可直接使用的指标、坐标和建议，不再读取原始日志或重新做语义提取。设计同时核对了原始 Lite / Advance UI 的实际渲染代码，逐项来源见[原始 UI 对照](original-ui-mapping.md)；四轴名称沿用《agent轨迹数据处理方向与分析工具.md》。本次不扩大暂缓特征的范围。

入口为 `build_presentation(analysis)`，输入是同一筛选范围的 `analyze_bundle`／`analyze_store` 输出。结果版本为 `presentation-v2`；诊断规则为 `presentation-diagnostics-v1`；画像规则为 `collaboration-profile-v1`。纯代码计算，不调用模型或外部 API，也不修改输入。v2 将 `overview.collaboration_duration` 从不可用改为 UI 定义的累计会话观测跨度；人工工时始终在独立的 `human_work_duration` 中保持未知，消费者需按版本升级标签与说明。

## 1. 分层与页面合同

```text
筛选后的标准数据
  → 已有八族 Feature（含证据、未知数、来源覆盖）
  → 计数 / 条件比例 / 任务等权归并 / 固定坐标 / 规则排序
  → 概览、画像、会话轨迹、工具、项目、语义、建议、资源匹配信号
```

画像回答“观察到了哪些协作选择”；瓶颈回答“哪些已记录问题值得回看”。工作量和证据记录由两者共用。错误率、纠偏率、Token 消耗不混入人格总分；任务题材、工具多样性也不自动成为瓶颈。

下表左列是 Feature 输出中的相对路径，右列是 presentation 输出中的路径。

| 特征族 | 已有字段与处理特点 | 前端映射 | 边界 |
| --- | --- | --- | --- |
| Task 任务 | `tasks.records[*]` 的 `task_id`、`domain`、`task_type`、`human_evidence_ids`、`task_boundaries`、目标与产物；领域／类型为词面候选、多标签 | `timeline`；`profile.task_distribution`；`semantics.interest_domains`；画像按任务去重的统计单位 | 候选任务边界保留，不用同目录自动合并任务；兴趣候选不是人格事实 |
| Instruction 指令 | `instruction.records[*].constraints`、`features`、`unknown_reasons`、`supersedes_instruction_ids`；明确真人指令、条件与冲突分开 | `profile.axes`、`monthly_trend`、`scatter` | 记录“明确提出了什么”，未命中不证明相反偏好；不计算暂缓的 prompt 具体程度综合分 |
| Interaction 交互 | `bottleneck_features.interaction.message_intents`、`friction_types`、`repeated_requirement_count`；确认标签与关键词候选分开 | `overview.correction_rate`；会话纠偏；`diagnostics`；`semantics.friction` | 新要求、正常澄清不自动当纠偏；未审消息不进入确认分母 |
| Preference 主观偏好 | `preferences.records[*]` 的类型、值、极性、作用范围、生效时间与版本关系 | `profile.preferences`；`semantics.explicit_preferences`；`resources.matching_signals` | 展示明确表达的历史，不把重复次数当强度，不生成隐式偏好向量 |
| Respond 回应与执行 | `bottleneck_features.respond.tool_sequence`、重试、父子关系、失败原因；调用已配对、去重 | `tools`、会话工具指标、转移矩阵、失败原因、诊断证据 | 调用成功不等于任务成功；子代理实际出现次数不是配置数量 |
| Cost / Time 用量与时间 | `overview.usage`、各会话／项目 `usage`；`bottleneck_features.cost_time.durations`；`overview.activity_rhythm` | Token、可靠工具耗时、日／小时活动量、项目执行时间 | 已知小计与完整总量分开；日志跨度和执行时间不当人工工时 |
| Outcome 主观结果 | `overview.subjective_outcomes.counts`；`sessions[*].subjective_outcomes.feedback`；明确反馈及关联状态 | 接受／拒收／返工计数；`diagnostics.outcomes.subjective`；返工建议 | 分母是关联反馈消息，不是任务；沉默保持未知，不输出满意率 |
| Outcome 客观结果 | `bottleneck_features.outcome.validation_runs`、`acceptance_results`、`task_results`；版本／范围匹配 | 检查失败率、已声明验收项通过率、项目内声明的验收集合 | 局部检查不代表全项目验收；没有完整项目任务清单不输出项目完成度 |

页面消费方式：

| 前端模块 | presentation 路径与用途 |
| --- | --- |
| 概览 | `overview`：主会话、真人消息、纠偏率、Token、活动、工具／语言排行、画像摘要、主要问题与前三条建议 |
| 协作画像 | `profile`：四轴观测及缺口、稳定散点、月度变化、任务分布、明确偏好 |
| 会话轨迹 | `sessions` 按所选范围内最后事件时间降序，未知时间最后；`timeline` 按任务边界时间升序，缺时间保留原顺序信息 |
| 工具调用 | `tools`：次数、结果分母、耗时、子代理、重试、转移矩阵、失败原因 |
| 项目分析 | `projects`：同范围计数、Agent 构成、画像、诊断、执行时间、声明验收集合；项目完成度与配置覆盖显式不可用 |
| 情绪语义 | `semantics`：题材候选、明确偏好、反馈词面线索、确认摩擦各自展示；不从词频生成情绪结论 |
| 优化建议 | `recommendations` 与 `diagnostics.findings`：证据驱动的回看建议；类别列表保留前端分类 |
| 资源库 | `resources.for_you` 复用同范围的资源推荐结果，`resources.matching_signals` 保留匹配输入；同人格使用和热门仍需群体使用数据 |
| 生成工坊 | `capabilities.studio="deferred"`，本次不实现 |

同步、分享、导出与安装是应用操作，不是统计指标。此层可作为导出 JSON 的来源，不会执行配置安装。

## 2. 筛选、时间与缺失值

### 同范围先算再呈现

所有计数、比例、任务与证据来自同一个 `scope`。支持原有 `project_ids`、`legacy_project_ids`、`model_ids`、`effort_raw`、`root_session_uids`、排除会话、`include_children`、`scene` 等筛选，以及 `agent_ids`。Agent 是会话来源身份，模型是逐请求身份，两者分别筛选。

时间成员边界统一为 UTC 毫秒的 `[from_ts, until_ts)`。`display_timezone` 只决定日、小时、月的日历分桶，不修改事件时间。后补标签和返回结果的可见性仍由 Feature 层控制，展示层不另行补入范围外历史。

`window=7d/30d/90d` 为滚动 `N × 24` 小时：

```text
until = 显式 until_ts，否则当前 UTC 毫秒
from  = until - N × 86_400_000
```

因此 `7d` 不等于本地自然周。`window` 与显式 `from_ts` 同时出现会报错；可以用 `until_ts` 回看历史窗口。`window=all` 不与 `from_ts/until_ts` 混用。需要“本周建议”时应明确给出本周边界；默认建议只对当前选择范围负责。

### 零与未知分别编码

- `0`：该口径已可观测，所选数据中的计数确实为零。
- `null`：来源不可用、零有效分母、缺证据或不支持该结论。前端显示“暂无可用数据”等缺失状态，不能画为零值。
- `partial`：有可展示的观察子集，但存在未知、估算或来源覆盖不完整；展示分母和覆盖信息。
- `insufficient_data`：诊断比例或平均值没有合格分母；不是失败率为零。
- 来源主动排除时不恢复数据；Feature 的 `coverage`、`selection` 随结果保留。

基础量值通常带 `value/unit/status/basis/unknown_n/reason/evidence_refs`；诊断比例还带 `numerator/denominator/known_n/rule_version`。画像轴使用任务与会话粒度的 `effective_task_n/observable_task_n/unknown_task_n/session_n`。不同粒度不混用一个总覆盖率。

任何总体比例都从同范围分子和分母重新计算：

```text
pooled_rate = Σ numerator_session / Σ denominator_session
```

例如两会话纠偏分别是 `1/2` 与 `1/8`，合计为 `2/10=20%`，不能平均为 `31.25%`。项目和会话视图复用各自已筛选的 Feature 聚合，不相加父会话与重复包含的子代理 Token。

## 3. 基础统计、活动与排行

### 工作量及轨迹

- `overview.sessions`：确认的主会话 ID 数，不把子代理算作新增真人协作会话。
- `overview.messages`：确认真人来源消息数；来源不明另列。
- 会话 `turns`：明确 `(session_uid, turn_uid)` 去重，不能用消息数除以二推算。
- `timeline`：每个任务在每个会话内的边界段保留 `start_ts/end_ts`、顺序、`boundary_status`、结束原因和证据。缺结束时间保留开放任务，不把助手最后回复当作结束。
- `observed_session_span_ms` 是所选会话自身的 `last_event-first_event`，只表示日志跨度。`overview.collaboration_duration` 是这些跨度之和，包含空闲与并行重叠；`human_work_duration` 保持不可用。
- `statistics.counts` 提供项目、主会话、子代理、未知类型、轮次、真人消息、助手消息、事件与工具数。项目优先 canonical ID，再用无歧义的 legacy 别名；未分配项目单列，不算一个项目。
- `statistics.time` 提供首末事件、观测范围、跨度总和／均值／中位数／区间并集、时间已知／未知会话数。只出现一个事件时跨度为零；缺事件边界为未知。未展开的子代理只有个数，不借父会话时间填充。
- `statistics.activity.active_dates` 是实际有事件的本地日期集合大小，不能用首末日期差替代。会话、项目均保留局部明细，按 Agent／项目／日期筛选后重算。
- `timeline_recent` 按任务中已观察到的最后真人消息降序，用于原始 Lite 的近期任务；不把任务消息时间解释成完成时间。

```text
span_i = max(selected_own_event_ts_i) - min(selected_own_event_ts_i)
span_sum = Σ span_i
span_union = length(union([first_i, last_i]))
active_dates = size(union(local_date(selected_own_event_ts)))
```

### 日／小时活动量

`overview.activity.series` 分别保留 `human_messages`、`tool_calls`、`model_requests`，不把三类不同单位相加成为“工作强度”。对某一类事件：

```text
day_share(d) = count(d) / Σ count(d)
hour_share(h) = count(h) / Σ count(d)
intensity(d) = log(1 + count(d)) / log(1 + max_selected_day_count)
```

当当前选择没有已知活动时，分布比例为 `null`，已知空桶热度为 `0`。时间未知的事件不摊入日期。范围有明确起止且覆盖不超过 366 个本地日期时返回完整日期网格，否则只返回观察到的日期；小时桶固定为 `0…23`。

三个系列分别继承各自的事件／调用／请求覆盖状态。真人来源全部未知或来源部分覆盖且没有已知活动时，桶次数和热度保留 `null`，不能显示成确定的零工作量。

`statistics.activity.message_weekday_hour` 直接计算每条真人消息的 `(ISO星期, 本地小时)` 联合分布，对应 Advance 热力图，不能用两个边缘分布相乘制造。`observed_span_by_hour` 将会话区间按本地整点和时区偏移变化切分，单位为分钟，对应 Lite 小时图；并行跨度分别计入。`overview.agent_activity` 提供按 Agent 的每日会话起点和真人消息；每日 Token 必须另按有效请求口径计算，不摊分未知总量。

例：三天已知消息数为 `0、3、15`，热度分别是 `0、0.5、1`，比例分别是 `0、1/6、5/6`。热度最大值来自当前筛选，切换窗口后颜色可能变化；跨窗口比较应看原始次数、分母及覆盖，不能把颜色当效率改善。

### 工具、语言和任务标签排行

普通次数排行按次数降序、同次按名称稳定排序，份额为 `count/Σcount`。工具次数来自去重后的实际调用。语言排行的来源是 `overview.top_languages`，口径为真人正文中提及的文件扩展名；前端应显示“提及的语言／文件类型”，不能写成真实代码行数或使用时长。

任务的领域／类型是多标签发生率：

```text
domain_rate(k) = 带标签 k 的不同任务数 / 至少有一个领域标签的不同任务数
```

同任务跨会话只计一次；未知标签任务不进入已知分母，单独列 `unknown_n`。一个任务同时涉及 software 与 writing，两类可以各为 100%，不要求加总等于 100%。它与普通排行的份额不同。

v2 的 `semantics.domain_details` 在六个父类下提供 27 个细分领域，见[领域规则与语料](task-taxonomy.md)。每项包含不同任务／会话／项目数及可下钻 ID，按事件证据投影到项目和会话；`task_type` 独立保留“创建／修改／测试／解释”等动作。120 条构造语料用于回归验证，不能视为真实用户准确率。词面命中只作为可解释的任务题材候选，不宣称已经完成向量语义分类。

## 4. 诊断指标与工具转移

| 输出 | 精确分子／分母 | 排除或单列 |
| --- | --- | --- |
| `correction_rate` | 确认含 correction 的消息数／来源和意图均已确认的真人消息数 | 同消息多标签计一次；关键词候选与未审意图、未知真人来源不进入确认分母 |
| `tools.success_rate` | success 调用数／`success+failed` 调用数 | rejected、interrupted、running、unknown 分别展示 |
| `tools.error_rate` | failed 调用数／同一已知结果分母 | 不是工具调用总数；不把缺返回判失败 |
| `average_execution_duration_ms` | 可靠执行耗时之和／可靠耗时样本数 | 日志间隔估算另列 `estimated_n/estimated_log_gap_mean_ms`，不混入平均执行耗时 |
| `subjective.rework_feedback_rate` | 已关联返工反馈消息数／全部已关联反馈消息数 | 无法关联及未收到反馈的交付不默认为好评；不是满意率或任务失败率 |
| `objective.validation_failure_rate` | failed 检查执行数／`passed+failed` 检查执行数 | 中断与未知单列；只计实际执行、有直接证据的检查 |
| `objective.declared_criterion_pass_rate` | passed 声明验收项数／`passed+failed` 声明验收项数 | 未验证项仍未知；该条件比例不代表完整验收或项目完成度 |

示例：工具记录有 8 成功、2 失败、1 中断、1 结果未知，则成功率 `8/10=80%`、错误率 `2/10=20%`；总调用数仍为 12。其中仅 3 条有可靠耗时 `100、200、600 ms`，平均值是 `900/3=300 ms`。另有一个 `900 ms` 日志间隔估算也不能加入分母，前端同时展示 `known_n=3` 和估算／缺失数量。

`failure_reasons` 按原协议明确原因聚合，并列出原因未知数。它可以包括失败、拒绝和中断的原因；不能将它的总数直接当成错误率分子，也不能从 stdout 的负面词推断根因。

`subagent_count` 按明确父子／spawn 证据的 `child_session_uid` 去重；fork 单列，角色名称不证明父子关系。`confirmed_retry_count` 与 `candidate_retry_count` 分开，重复调用本身不证明重试或浪费。

### 转移矩阵

节点键为 `(name_raw, kind)`。在每个会话内按可靠且不重复的 `seq` 排序，对相邻调用记数；不连接不同会话。某会话存在缺失或重复顺序时，整个会话的调用不参与邻接统计，并返回 `excluded_order_call_count`。

```text
C[i,j] = 会话内工具 i 后紧接工具 j 的观察次数
N[i] = Σj C[i,j]
P[i,j] = C[i,j]/N[i]；N[i]=0 时该行概率为 null
```

若 A→B 有 3 次，A→C 有 1 次，则 A 行为 B `0.75`、C `0.25`。B 没有任何已知后继时，B 行不能填为全零概率。矩阵描述调用记录顺序；并行调用也可能相邻，因此它不是依赖图、关键路径或因果调用链。

为限制展示矩阵的维度，工具身份超过 20 类时，保留调用最多的 19 类（次数相同按身份稳定排序），其余合并为“其他工具”；先合并计数，再按行归一化，保留总转移次数与逐边证据。`reduction` 给出原节点数量、20 节点上限及归并成员，`by_tool` 仍保留完整工具明细。低频工具重新归并可能随筛选变化，跨范围比较须同时查看归并信息。

## 5. Token 与时间的计量边界

展示直接复用 Cost / Time 的规范结果，不再次解析日志或按页面猜测用量：

```text
T = 未缓存输入 + 缓存读取 + 缓存写入 + 输出
```

`reasoning_tokens` 已在输出中，不重复相加。若上游明确声明输入含缓存，先按既有规则扣除缓存读写；未知包含关系保留未知。可靠逐请求身份去重，身份冲突隔离；完整总量与 `known_subtotal` 分开。

例：四个桶是 `100、20、10、40`，总量为 `170`；输出包含的 15 个思考 Token 不再增加总量。两条请求只有第一条四桶完整，则可展示其已知小计，不能把小计写成两条请求的完整总量。

累计快照按同周期末次有效值处理，不累加连续快照，也不与覆盖相同调用的逐请求数据相加。root-tree 快照不得再加子代理请求；有时间／模型等细分时，不把全会话累计值平均摊入所选范围。

可靠执行区间可用并集避免重复：`[0,10)` 与 `[5,15)` 的耗时总和是 20 秒，区间并集是 15 秒。两者都不是人工投入时长。页面需保留原 `duration_source`、质量和覆盖，不能使用会话跨度补上缺失耗时。

## 6. 四轴降维与稳定坐标

### 按任务归并，不按消息堆票

Instruction 的 `task_id` 可能是原生或旧 ID，Task 的 `task_id` 是派生 ID，两者不能直接相等连接。代码通过 Task 的 `human_evidence_ids` 和包含性的边界证据关联消息；多候选或无法关联时增加 `unmapped_instruction_n`。一个原生任务跨会话仍只获得一次总览投票。

同任务、同会话先调用既有 `resolve_instruction_scope`，处理明确替换、条件、冲突；截断正文和没有直接正文的记录不用于得分。如果不完整记录明确声明替换旧约束，对应轴记为 unresolved，既不猜替换内容，也不因跳过新记录而恢复旧值；输出 `unresolved_task_n/unresolved_evidence`。条件未求值时不当作无条件要求。不同会话的同任务仍会检查互斥授权、规划顺序和核验禁止冲突；冲突任务在对应轴弃权，不平均成中性。

每个有效任务对每轴最多贡献一个 `x_task ∈ [0,1]`，聚合为：

```text
observed_axis = Σ x_task / 有效任务数
```

当前等任务权重，无时间衰减、模型学习或跨用户标准化。一个任务重复提出十次授权也不比另一个只提出一次的任务权重更大。任务未知轴不补 `0` 或 `0.5`。

### 实际可支持的轴

| 轴 | 当前字段映射 | `score` 与类型输出 |
| --- | --- | --- |
| 控制 C／委托 D | `requested_autonomy.ask_first→0`，`scoped→0.5`，`explicit→1`；scoped 与明确端点共现采用端点，ask_first 与 explicit 冲突则弃权 | 可以输出观察子集上的连续 `score`；满足展示门槛才给暂定 C/D |
| 探索 E／规划 P | 仅 `execution_order.plan_first` 记规划支持；discuss_first 不自动当规划，execute_first 不自动当探索 | `observed_score` 可描述命中的支持侧；`score=null`、`direction=null`，原因 `single_pole_extractor` |
| 加速 A／验证 V | 仅 `verification_requirements.requested` 记核验支持 | 与 P 相同；没要求测试不表示偏好加速 |
| 专精 S／编排 O | 当前没有明确用户编排选择的规范字段 | 分数和方向均为空；工具多、领域熵高、子代理多不代替该证据 |

`signal_rate` 另外提供“明确规则命中任务数／有可读指令且该轴不冲突的任务数”。这个分母允许未命中任务，因此零值表示没有规则命中；它不表示相反人格。O 没有提取规则，连规则命中率也保持为空。

D 方向的实际展示门槛：

1. 至少 5 个本轴有效任务，证据来自至少 2 个会话；只计算本轴证据的会话，不借无关跟进消息凑数。
2. 有效任务不能含候选任务边界；仅有候选边界时可以展示观察数值，但暂不给类型方向。
3. 分数严格 `<0.4` 才给 C，严格 `>0.6` 才给 D；中间和边界均不选方向。

这是版本化的产品启发规则，不是心理学阈值或校准置信度。只有四轴方向齐备才拼 `code`；按当前提取能力完整四字码通常为 `null`，不填造 MBTI。`headline` 由这些已知事实生成确定性短句，不声称是模型推断的心理结论。

算例：任务甲十次明确委托、任务乙一次先询问，两个任务的 D 观察均值是 `(1+0)/2=0.5`，不是 `10/11`。只有两个任务也不满足方向显示门槛。

### 月度趋势

月度视图最多显示当前范围中最近 12 个本地日历月，保留 `max_months` 和被省略的更早观测月份数，避免长历史或异常日期范围产生无界网格。总体画像仍使用整个已选范围，月度窗口不会改变总体统计。

`monthly_trend.rows` 以 `display_timezone` 和每条指令原始时间分月，逐月执行相同任务归并规则。没有证据的月份保留空分数；缺时间指令列在 `unknown_time_instruction_n`，不猜月份。跨月任务在每个月只按当月证据归并一次，整体窗口仍按任务去重。

月趋势不是“当时所有有效配置的重建”：每月只消费当月指令观察；显式替换若指向该月之外且没有上下文的旧约束，会保守保留未知，而不会偷偷补入范围外历史。较晚月份的替换不会覆盖较早月份的分数。`scope_clipped` 标明被总时间范围截断的月份。

### 散点图

散点使用固定、可解释的两个观测指标，不按筛选结果拟合 PCA、UMAP 或重新定向：

```text
x = 会话内的 D 授权方式观察分数
y = 会话内明确规划要求命中任务数 / 可读且规划轴不冲突的任务数
```

Y 轴名称为“明确规划要求命中率”，不是完整 E/P 轴。`coordinate_basis` 明确为 `observable_request_metrics_not_personality_embedding`。缺任一坐标的会话不画，列入 `missing_session_ids`；点内保留任务数和轴证据。

例如同一会话有两个可读任务，都明确委托，只有一个提出先规划，则点为 `(1,0.5)`。另一个没有规划命中的会话可为 `(1,0)`，这不能解释为探索人格。切换其他会话筛选不会旋转该坐标；任务构成、分母或可见证据变化仍可能改变数值。

### 明确偏好单独展示

`profile.preferences` 对 `preference_id` 去重，保留类型、规范值、prefer/avoid、范围、时间、operation、版本关系与证据 ID。它是表达历史，不是“当前全局有效设置”或强度排行；需要执行偏好时继续使用既有范围解析器。

当前 `collaboration.act_directly` 可以表示执行顺序，不足以单独证明自主授权；因此不进入 D 或 E 轴。项目偏好也不会复制到所有任务、制造多份投票。当前任务明确指令仍优先于历史建议。

## 7. 问题与建议的排序规则

当前只生成四类有直接证据的回看项：确认纠偏、工具失败、实际检查失败、已关联返工。存在正分子、有效比例和证据才能产生 finding；没有发现这些问题不等于整体协作无瓶颈。

设 `r` 是该问题的观察比例、`n` 是该比例的已知分母、`u` 是对应未知数量：

```text
support = min(n/5, 1)
coverage = n/(n+u)
priority = 100 × r × support × coverage
```

`u` 不可得时 `priority_score=null`，不伪造覆盖；已知优先分数用于降序排列，同分按规则 ID 稳定排序。它只决定回看顺序，不是严重性、异常概率、因果根因或预期收益。

例如已审 10 条消息中 2 条确认纠偏，另有 5 条未知消息，优先分数为 `100×0.2×1×10/15≈13.3333`。已审 2 条中 1 条纠偏且没有未知，优先分数为 `100×0.5×0.4×1=20`。这种排序是首版可解释约定，应通过后续人工验收调整，不能标为统计显著性。

推荐分类保留 `prompt/skill/hooks/plugin_mcp/subagent/model/workflow`。本次只对可证问题生成 prompt、workflow，以及至少两次检查失败时的 hooks 回看建议；不会为了填满栏目强造 skill、模型或 MCP 推荐。

每条建议携带 `rule_id/rule_version/evidence_refs/priority_score`。`expected_effect=null`、`installable=false`；配置名称、适配 Agent、代码预览和安装动作需要后续可信资源条目与能力清单，不由排序公式补造。

具体资源卡片复用同范围的 `bottleneck_recommendations`，输出在 `resource_recommendations` 与 `resources.for_you`。其规则／BM25／效果方向／环境召回、RRF 融合、兼容性过滤、加权排序和 MMR 去重由已有[推荐引擎](../recommendation/engine.md)负责；本展示层不重新评分。上面的诊断 `priority_score` 仅排列回看建议，与资源卡片的试用优先级分别解释。

## 8. 明确保留不可用的展示与所需输入

| 展示 | 当前处理 | 后续需要的规范输入 |
| --- | --- | --- |
| 项目完成度 vs Token | Token 可独立展示；`projects[*].completion` 不可用，保留声明的验收集合 | 完整项目任务／交付清单、版本、完成标准与可比权重；所有未完成和未知项的范围 |
| AGENTS.md、hooks、skills、MCP、配置子代理覆盖 | `configuration_coverage` 不可用 | 带项目／Agent／版本／采集时间的配置盘点；明确已检查不存在与未采集的区别 |
| 真人协作工时 | `collaboration_duration` 不可用 | 经用户认可的人工投入测量、暂停／并行／离开口径；不能用会话跨度代替 |
| 完整十六类型 | 四轴缺口可见，`code` 为空 | 明确探索／加速／专精／编排选择的独立字段及语义验收；不从缺信号倒推 |
| 为你推荐资源 | `resources.for_you` 和 `resource_recommendations` 原样保留同范围推荐引擎结果；另保留 `matching_signals` | 继续补齐七类可信资源及环境清单；缺资源／证据时保留引擎的空结果，不伪造推荐 |
| 同人格正在用、热门 | `same_persona/popular` 不可用 | 有授权的群体使用数据、时间窗、去重身份、足够覆盖与适用范围 |
| 预计节省时间／Token／费用、ROI | `expected_effect=null`；不新增费用估算 | 同类任务、相同验收约束的实际干预前后或对照数据，包含额外配置开销 |
| 高频语义词、真实兴趣词频 | `semantic_terms` 不可用；已有领域候选和偏好仍可展示 | 有明确文本来源、分词、词义归并、语言与文档频率口径的语义计数；现有 n-gram 权重不是词频 |
| 情绪、满意度总分 | 不生成；仅展示已确认摩擦、反馈类别和词面线索 | 独立验证的标签及任务／交付关联；不能把负面词、沉默当真实情绪或满意度 |
| 生成工坊 | deferred | 团队另行确认目标与范围 |

## 9. API、CLI 与代码入口

获取前端快照：

```text
GET /v1/analytics/presentation?window=7d&agent_ids=codex&display_timezone=Asia/Shanghai
```

列表筛选沿用重复 query 参数方式，例如 `agent_ids=codex&agent_ids=claude_code`；值须匹配来源中的真实 Agent ID。支持共享筛选及上面的 `window` 规则。历史时间参数使用 UTC 毫秒，非法时区或冲突时间条件返回校验错误。

`agent_ids` 筛选历史数据来源，`target_agent` 指资源适配目标（generic / codex / claude_code），两者独立；可用 `family` 选择推荐资源族。CLI 对应 `--recommendation-agent`、`--recommendation-family`、`--recommendation-catalog`；显式空目录仍为空，不回退种子。展示摘要还包含推荐目录、目标和策略的结果，资源条件改变会更新 `presentation_digest`。

导出：

```bash
orbit analytics --presentation --window 7d --agent-id codex \
  --display-timezone Asia/Shanghai --output .local/presentation.json
```

直接调用可先用 `window_scope` 构造实际范围，再运行已有分析：

```python
from orbit_backend.analytics.inputs import Scope
from orbit_backend.analytics.presentation import build_presentation
from orbit_backend.analytics.presentation.metrics import window_scope
from orbit_backend.analytics.service import analyze_bundle

scope = window_scope(Scope(display_timezone="Asia/Shanghai", agent_ids=["codex"]), "7d")
analysis = analyze_bundle(bundle, scope, with_text=False)
presentation = build_presentation(analysis)
```

实现文件：

- [metrics.py](../../../packages/backend/src/orbit_backend/analytics/presentation/metrics.py)：滚动窗口、基础量值、排行、活动热度。
- [profile.py](../../../packages/backend/src/orbit_backend/analytics/presentation/profile.py)：任务等权四轴、缺口、月份、固定散点与偏好历史。
- [diagnostics.py](../../../packages/backend/src/orbit_backend/analytics/presentation/diagnostics.py)：确认比例、工具状态与耗时、转移矩阵、结果与建议排序。
- [service.py](../../../packages/backend/src/orbit_backend/analytics/presentation/service.py)：八族结果装配为同一前端快照、会话／项目子视图及不可用能力。

快照保留源特征版本、各族版本、源分析摘要与展示版本，便于追溯口径变化。前端不要自己换分母、重新拟合坐标或从空字段补造结论；变更公式、阈值和字段语义时同时更新规则版本与合成验收样例。

项目子视图按证据所属会话重新投影任务标签、边界和偏好候选，避免跨项目共享任务携带其他项目的题材。累计 Token 总量引用快照事件证据；逐请求桶保留独立 `bucket_basis`，不得强求其和等于不同范围的累计总量。

## 10. 验证范围

数学验证使用虚构事件和既有真实提取器，不读取个人 Agent 历史。覆盖：不同分母汇总、零／未知、状态排除、可靠与估算耗时分离、Token 原口径、转移矩阵与顺序缺口、建议证据、同任务重复与跨会话、指令冲突和替换、单侧提取抑制、时间分桶、固定散点、Agent／项目范围，以及 API／CLI 一致性。

这些测试验证规则和对接，不证明规则提取在真实语言上的准确率，也不证明建议已经改善效率。真实语义质量和产品阈值仍需团队人工验收；不以合成测试通过率对外宣称人格准确率。

2026-10-02（Asia/Shanghai）在 Python 3.13.12 / Linux 上验证：合入 main 的推荐模块后，后端 1,129 项通过、1 项 staging 桥接测试因未构建 Node 连接器而跳过；数据层 101 项通过。锁定依赖同步、规定目录 Ruff 检查及数据层格式检查、两包构建、`orbit demo`、`orbit evaluate`、`git diff --check` 通过；评价的 readability / pipeline / probe 分别为 8/8、34/34、12/12。构造的 canonical demo 数据成功导出 `presentation-v1` JSON，验证显式空资源目录和目标 Agent 不被展示层覆盖；未读取或导入个人会话。远端 CI 状态单独查看 PR。

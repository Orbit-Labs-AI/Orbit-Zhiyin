# Orbit 分析与 AI harness 可靠性审计

日期：2026-10-03。范围：`analytics/`、`ai/`、`uiview/a4a6_sentiment.py` 与特征范围归一化。只使用构造会话、FakeEngine 和模拟 CLI；未读取或发送真实私密会话，未执行真实付费模型调用。

## 现有实现与输入—计算—输出

已有八族分析与本地 Agent 执行器是真实实现。本次沿现有数据契约补强，不另建平行分析框架。语义信号和可直接观测的统计分别保留；用户输入与 Agent 行为/反馈分别追溯。该 2×2 是组织视角，不是把文本代理指标升级为客观事实。

| 区域/模块 | 输入 | 计算 | 实际输出与界限 |
|---|---|---|---|
| 语义输入：Instruction | 已确认 human 的直接原话、任务边界 | 约束提取、目标/条件/格式/工具要求、可选有引文的语义观察 | `instruction.records`；明确要求不自动授予执行权限 |
| 语义输入：Task | 用户目标、显式任务与会话关系 | 任务分类、目标历史、预期产物、主题表示 | `tasks.records`；没有证据的目标/领域保留空值 |
| 语义输入：Preference | 有作用域的明确要求与重复证据 | 区分任务局部指令、候选偏好和支持/反例 | `preferences.records`；不把单次要求当永久偏好 |
| 语义反馈：OutcomeSubjective | 用户反馈与先前交付/任务身份 | 分开计算接受、完成确认、返工并关联目标 | `overview.subjective_outcomes`；沉默不是接受 |
| 情绪与反馈表达 | 直接用户文本；剥离引文与非断言；截断文本不推断 | 显式正/负/混合/中性词面信号、时间桶、反馈短语 | `products.feedback`、A6 series/friction/phrases/terms；仅表达趋势，不是心理诊断或任务成功率 |
| 观测输入：Interaction | 有序用户/助手事件与任务关系 | 消息长度、轮次、纠偏候选与已确认关联、重复要求 | `bottleneck_features.interaction`；候选与确认率分开 |
| 观测输出：Respond | 工具调用、协议结果、父子会话关系 | 成败率、转移序列、明确重试关系与工具分组 | `bottleneck_features.respond`、`products.tools`；仅 success/failed 等明确结果进入分母 |
| 观测输出：CostTime | 完整 token 桶、费用来源、可靠时间点 | 兼容用量合计、区间并集、延迟统计 | `bottleneck_features.cost_time`、`presentation.statistics`；缺费用不等于免费，会话跨度不等于工作时长 |
| 观测输出：Outcome | 验证结果、交付记录 | 已执行检查的结果与交付观察 | `bottleneck_features.outcome`；工具成功/Agent 声称完成不等于用户认可 |
| 传统文本与描述统计 | 选定范围已脱敏文本、事件/调用数值 | 中文分词/英文词、TF-IDF/主题表示、分位数、区间与按时间分组 | `lexical`、`statistics`、`presentation`；样本不足/不可比较保持 unknown |
| 展示适配 | 上述已选范围结果 | 统一单位、分母、缺失状态、可追溯证据 | `uiview/` 和 `analytics/presentation/`；不在读取页面时调用模型 |

内置 `feature_dictionary` 补充 emotion、expression_balance、feedback_signal 与 emotion_explicit_n 的计算口径。完整分析结果元数据新增 `ui_analysis_map`（分区响应不重复携带该静态字典，兼容旧缓存并保持响应精简），包含各族的输入、计算、输出路径及 unknown 含义，可供 UI 帮助说明与集成核对使用。`expression_balance` 为 `(正面数 - 负面数) / 已识别显式表达数`，混合与明确中性计入分母；未识别文本不当成中性。

## 已修复的可靠性问题

1. **选定范围丢失。** AI pack 过去忽略 source/exclusion，显式 session/event/call ID 路径可绕过项目和时间筛选；问答转发还丢弃 `source_ids=[]`，特征归一化把空列表变为无筛选。现在显式空选择保持无记录；ID 是追加条件；搜索在 SQL limit 前按范围过滤；持久化排除和调用方排除合并。
2. **语义查询范围扩大。** 模型规划的查询可指定与用户不一致的范围。现在 `ask.question` 的查询必须使用已选 pack scope，选中会话同时限定指标、摘要、摩擦与证据。AI scope 的 start/end/project/session 别名映射到特征服务对应字段。
3. **缓存绕过验证。** RunContext 缓存命中过去直接返回。现在命中后重新执行 JSON Schema 与当前证据验证；失败缓存重新生成，且取消仍生效。
4. **候选证据错配。** 同一会话内合法 signal_id 可错误搭配另一合法 event_uid。现在检验精确 signal→event 映射。
5. **长会话尾部丢失。** 原先先取前 200 条再取尾部，无法看到真实最终交付与反馈。现在用户消息取最初 4 条+真实最后 8 条，助手取真实最后 12 条；保留 role/seq/ts、总量/留存量和 chunked。工具错误合计对完整会话计算，序列样本独立标记覆盖。
6. **工具成败分母。** AI 指标原先将“非 unknown”都视为已知结果，running/interrupted/rejected 会稀释失败率。现在只有明确 success/failed 系列状态进入分母，其余保留未知占比。
7. **epoch 窗口。** A6 与 AI window 不再用 truthy 默认值覆盖合法的时间戳 0。
8. **旧 narrative 串范围。** `AIService.narrative` 原先在 key 为空时返回任何范围的最近历史叙述。现在先比较规范化的项目/来源/时间/会话/排除范围，再用当前数据重建原请求并比对保存的输入指纹（旧作业使用原 preview digest）；不一致就返回当前范围的 L0 模板。相对时间窗口生成的 key/window 标签只归一化同一 UTC 日内的毫秒漂移，所有实际指标、证据、文本与任务版本仍进入指纹；显式时间边界精确保留。每次最多重建一个匹配历史请求及一个当前回退 pack，避免扫描 50 个作业导致重复计算。历史 job 仍可单独查看，但不再冒充当前分析。

## 专业分析与推荐任务协议

新增任务沿用既有 `AIService → pack → RunContext → 本地 CLI/FakeEngine → 校验 → ai_job`，具备现有授权、脱敏、预算、队列、取消、重试、缓存、usage 和失败回退。没有另建网络模型接口，也没有新增未经验证的 CLI thinking 参数；cheap slot 可通过既有引擎模型设置配置。

| task_id | 专业角度 | 输入 |
|---|---|---|
| `analyze.collaboration` | 指令、响应、纠偏与显式反馈 | goal / metrics / sessions / friction / evidence |
| `analyze.quality` | 验证、交付与接受 | 同上 |
| `analyze.workflow` | 工具序列、重复失败与最小流程实验 | 同上 |
| `analyze.cost` | 费用、用量、时间与覆盖 | 同上 |
| `recommend.expert` | 工具配置、提示要求、验证流程建议草稿 | problems / profile / candidates，调用方显式 slots |

专业分析返回 `summary`、`findings[{kind: observation|hypothesis,text,evidence_ids,metrics:[{path,value}]}]`、`next_steps`、`limitations`。引用必须来自输入；指标路径与数值必须精确匹配。每个结果附 `analysis_session`，含 task/prompt/schema 版本、输入摘要、证据 ID 和验证状态；产物明确为草稿，不安装、不执行建议。问题可经 goal 或 `params.question` 提供；`params.session_uid` 限定当前会话。

推荐专家最多产生 3 条 suggestions 和 3 条 queries，建议必须引用自身输入 problem_id，额外引用只允许输入 candidate_id；标题、解释与步骤非空。失败回退为空建议/查询，交由现有确定性推荐保持可用。专业分析失败返回说明原因的模板和空 findings，不伪造模型结论。

## 验证与边界

固定历史会话的 facet_quality 评测显式提交与 fixture 一致的固定时间范围，避免依赖运行日期；未放宽 schema、外来证据与缓存复用断言。

定向回归覆盖项目/来源/排除范围、空来源、显式 ID、模型试图扩大范围、专业分析单会话范围、缓存坏数据、长会话真实尾部、signal/event 关联、工具结果分母、专业模板与推荐引用/结构校验。分析 AI 套件与 runner 已通过 133 项测试；最终追加的 scope/模板回归及仓库统一检查以本次集成验证结果为准。

真实模型质量、真实服务商计价、所有本机 CLI 版本的兼容性未在此次测试中验证。词面情绪与纠偏仍是未校准代理信号。生成式文字的语义正确性不能仅由 JSON 与引用校验证明，故观察/假设、局限和草稿标签必须保留。样本截取后的分类只解释留存材料，不代表完整会话中的全部语义。当前不对每个工具配置或所有示例 UI 占位值声称已得到真实数据支撑；完整页面验收由 UI 与服务集成测试核对。

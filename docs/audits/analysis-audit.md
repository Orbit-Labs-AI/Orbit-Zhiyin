# 本地分析模块审计：功能覆盖、持久化与性能

> 审计基线：`feat/yhyfhgs-dev` @ `747b0da`（已含 main 的 PR #32 `analytics/products/`、PR #34、PR #35）。
> 进行中的分支：PR #27 `feat/feature-display-metrics`（`presentation/`、四轴画像，genius-FXC）、PR #37 `feat/preference-v2`、PR #39 `fix/analysis-coverage-status`、PR #33 `feat/data-app-integration`。本文不重复它们的工作，任务包也尽量避开它们修改的文件。
> 性能数据全部来自构造数据（脚本见本文 §4.1），没有读取本机真实会话。

## 0. 结论

1. **功能覆盖**：AN 共 25 项（含 .1/.2 拆分）。按 main 现状计：已完成 3 项（AN-08.1、AN-17、AN-18），部分完成 15 项，缺失 7 项。缺口集中在一条链路上：**信号 → 问题 → 关键时刻 → 会话结果合成**（AN-05 的适配器、AN-06、AN-09、AN-19 的合成器）和 **AN-01 的指标引擎**（`metrics` 端点、`group_by`、带区间的统一指标对象）。A1–A7 中有 74 个 UI 条目依赖 AN，其中约 30 个卡在这两处。
2. **类别族**：八族的职责划分是完整的，不需要新增业务族。但缺少一个横向的**「信号」层**（`analytics/signals/`），用来把八族的事实转成可聚合、可下钻、可推荐的 `signal / problem`。族内还缺：Respond 的 `would_prompt / risky_command / runaway_loop / edit_churn`，Interaction 的 `frustration`，Outcome 的 `missing_verification` 与会话结果合成，Cost-Time 的 `resident_tokens` 与空闲折叠，以及 Interaction 的 `autonomy_steps` 会话字段。
3. **持久化**：`analysis.sqlite` 每次请求都会**写入**完整快照，但从不**读取**它来跳过计算。每个 `/v1/analytics/*` GET 都会全量重算全部八族、词频、统计、文本表示和推荐，再把整份结果（1000 会话时约 145 MB JSON）压缩写盘。`/v1/analytics/sessions/{id}` 只取一行，也要重算一次全量结果。分页接口 `runs/{id}/records` 每取 50 行，都要解压整份快照（0.92 s）。现在没有输入指纹，没有会话级缓存，没有失效机制，也没有清理策略。
4. **性能**：在 10 万事件、2,500 会话的构造数据上，`analyze_bundle(with_text=False)` 需要 **40.9 s**；文档 §5.3 的预算是 10 s。耗时随规模超线性增长（500→1000→2500 会话：3.1→7.5→40.9 s）。`with_text=True` 时，1,000 会话就要 **74 s**，因为 `temporal_novelty` 对每个会话都重新拟合一次 TF-IDF+SVD，复杂度 O(N²)。只改三处纯函数热点（缓存 `main_ids`、为 `direct_user_text` 加记忆化、把 `summarize_durations` 改成按会话分组）就能降到 **9.1 s**（4.5×）；产品层 1,000 会话从 17.5 s 降到 4.9 s。再去掉 `deepcopy`，并把项目行改为 O(E) 分组，预计 10 万事件能稳定在 5 s 以内。

---

## 1. AN feature 逐项核对

状态口径：**已完成**指 main 上有实现，也有对外入口；**部分**指核心计算已有，但缺字段、端点或口径；**缺失**指 main 上没有对应实现，雏形另行注明。路径相对 `packages/backend/src/tandem_backend/`。

| ID | 名称 | 判定 | 证据（文件:行） | 缺什么 |
| --- | --- | --- | --- | --- |
| AN-01 | 指标引擎 | 部分 | `analytics/service.py:196 analyze_bundle`、`:209 analyze_context`；八族 `dictionary.py`；`analytics/features.py:46 session_features` | `GET /v1/analytics/metrics`、`group_by`（agent/project/model/effort/day/week）、`{value,n,lo,hi,basis}` 统一指标对象、分母说明 |
| AN-01.1 | 组合层 | 部分 | `analytics/products/service.py:26 build_products`（PR #32 已合入）；PR #27 `presentation/` 未合入 | 与 PR #27 收敛为一套组合层（由 PR #27 rebase，本审计不碰） |
| AN-01.2 | 工具调用明细下钻 | 缺失 | `api/routes.py` 只有 `sessions/{id}/events` 和聚合端点 | 按工具 / `command_head` + Scope 取最近 N 条（脱敏摘要、`exit_code`、`duration`、`session_uid/event_uid`） |
| AN-02 | 会话事实 | 部分 | `analytics/features.py:46`；`service.py:23 _session_rows`（`bottleneck_features`、`subjective_outcomes`） | 会话行缺 `outcome`、`verify_*`、`autonomy_steps`（雏形 `products/journey.py:246 interaction_habits` 按轮次）、`signals_summary` |
| AN-03 | 分段 | 部分 | `analytics/task/features.py:64 segment_tasks`；`products/journey.py:117 session_journey`（`phase` 为规则候选） | 工作段（空闲折叠、work_block） |
| AN-04 | 过程挖掘 | 部分 | `respond/sequence.py:9 workflow`（DFG 转移）、`respond/relations.py:39`（子代理关系）、`products/tools.py:38 transition_matrix`、`:163 workflow_patterns`（三步链，按会话计支持度） | 子代理并行度分布、`wait_side`、变体（v1） |
| AN-05.1 | 语义检测 | 部分 | `interaction/rules.py:20 correction_terms`、`interaction/features.py:9 classify_message_intents`、`profiling/bottlenecks.py:58 diagnose`、`outcome_subjective/extraction.py:20` | 没有统一的 `signal` 行；缺 `frustration`（v1）；`explanation_revision / long_response / unexplained_terms` 只在旧链路 |
| AN-05.2 | 非语义检测 | 部分 | `respond/sequence.py:65 analyze_execution_sequence`（`retry_links`）、`outcome/validation.py:18`、`permission_request_count`；`recommendations/rules.py:13 RULE_IDS` 有 7 条规则信号 | `retry_loop` 适配器、`missing_verification`、`would_prompt`、`permission_denied`、`risky_command`、`interruption` 信号；`runaway_loop / edit_churn / mid_task_compaction`（v1） |
| AN-06 | 问题升级 | 缺失 | 雏形：`recommendations/diagnosis.py`、`recommendations/rules.py:35 evaluate_features`（`signal_id`，但无 problem 聚合与 Wilson 门槛） | `problem_id = stable_id(type,key,scope,scope_id)`、`min_sessions`、`wilson_lo ≥ 0.05`、按机会分母、`label` 状态只读 |
| AN-07 | 情绪弱标注 | 部分 | `products/feedback.py:45 classify_emotion`、`:68 expression_summary`、`:88 analyze_feedback`（按日 / 周） | −1~+1 分值、置信度门槛、低点与纠偏同轴（v1，Advance 独有） |
| AN-08.1 | 明确要求与偏好 | 已完成 | `profiling/portrait.py:13 profile`、`analytics/preference/`、`analytics/instruction/` | —（PR #37 在扩展） |
| AN-08.2 | 四轴与逐月画像 | 部分 | `products/journey.py:246 interaction_habits`（`type_code=None`、uncalibrated）、`products/summaries.py:58 profile_history`；四轴算法在 PR #27 | 等待 PR #27；本审计不重做 |
| AN-09 | 关键时刻 | 部分 | `products/journey.py:160-185` 按事件打标签（`tool_failure / verification / user_feedback / permission.request / context.compaction / turn.interrupted / confirmed_intervention`） | 5 类规则时刻（首个目标、纠偏、连续失败、验证通过、结束）的编号、去重、说明文字；依赖 signal |
| AN-10 | 小样本统计库 | 部分 | `profiling/analysis.py:16 wilson_interval`、`products/statistics.py:85 wilson`、`:249 bootstrap_difference`、`common.quantile` | 两份 Wilson 实现需合一；缺 `insufficient` 门槛常量和统一的 `{value,n,lo,hi,basis}` |
| AN-11 | 已装未用、常驻开销 | 缺失 | `products/service.py` 只把 `bundle.inventory` 原样透传（`configuration.items`） | `installed_unused`（清单项 × 调用名匹配）、`resident_tokens_median`、`rule_coverage` |
| AN-12 | 趋势与对比 | 部分 | `products/trends.py:51 activity_series(bucket)`、`:105 comparison`、`:16 resource_groups`（模型 × 档位）；`cost_time/activity.py:11` | 通用 `group_by`、`change_flags`、带区间的差值 |
| AN-13 | 实时状态 | 部分 | `products/journey.py:85 observed_state`（最后观测状态） | 菜单栏 / HUD 端点（v1） |
| AN-13.1 | 实时关注事件队列 | 缺失 | — | v1 |
| AN-14 | 快照与报告 | 部分 | `application/reports.py:9 build_report`、`products/render.py:313 export_report`（JSON/CSV/HTML） | `report_snapshot` 表（v1）；按章节导出 |
| AN-15 | 质量下降诊断 | 缺失 | — | v1，依赖 AN-12 `change_flags` |
| AN-16 | 输入适配与范围 | 部分 | `analytics/inputs.py:33 Scope`（已有 `source_ids`）、`:251 select`、`:387 select_canonical`；`data_access/store.py:118 analysis_bundle` | Scope 缺 `cluster_ids / signal_types / weekday / hour`；覆盖契约见 PR #39 |
| AN-16.1 | 会话排除持久化 | 缺失 | 只有查询参数 `excluded_session_uids`（`api/routes.py:64`） | 持久化排除名单、`POST /v1/sessions/{id}/exclude`、`GET .../source_files` |
| AN-17 | 任务上下文与明确要求 | 已完成 | `profiling/feedback.py`、`analytics/instruction/extraction.py`、`task/taxonomy.py` | — |
| AN-18 | 无监督文本表示 | 已完成（性能不达标） | `task/representation.py:54 representation`、`:33 temporal_novelty` | 新颖度 O(N²) 重拟合，见 §4 |
| AN-19 | 会话结果判定 | 部分 | `outcome/analyzer.py:13`、`outcome/acceptance.py:33/66`、`outcome_subjective/__init__.py:7`、`products/summaries.py:14 outcome_card`（只并列三类事实） | 合成器：`completed / partial / failed / abandoned / unknown` + `basis` + 证据 |

### 1.1 依赖 AN 的 UI 条目（A1–A7，共 74 条）

| 页 | 合计 | 可用（后端已足够） | 卡在 AN-01 metrics / group_by / 区间 | 卡在 signal / problem / 时刻 / 结果合成（AN-05/06/09/19） | 卡在 PR #27 四轴 | 其他（AI、v1、前端） |
| --- | --- | --- | --- | --- | --- | --- |
| A1 概览 | 21 | A1-01、A1-14、A1-24（Top 工具） | A1-12、A1-13、A1-16、A1-17、A1-18、A1-22、A1-23 | A1-09、A1-10、A1-11、A1-25 | A1-21 | A1-02（同步状态）、A1-03（导出）、A1-04、A1-06、A1-07 |
| A2 协作人格 | 14 | — | A2-16 | A2-15 | A2-01、A2-02、A2-05、A2-06、A2-07、A2-10、A2-13、A2-14 | A2-04、A2-08、A2-09、A2-11 |
| A3 会话与轨迹 | 15 | A3-07、A3-13（`/v1/evidence`） | A3-11（`autonomy_steps`） | A3-06（结果列、纠偏列）、A3-08、A3-12、A3-17、A3-18 | — | A3-01、A3-02、A3-04、A3-05（FTS）、A3-10（排除持久化）、A3-19、A3-20 |
| A4 工具调用 | 15 | A4-04、A4-05、A4-11、A4-12 | A4-01（by_mcp_server）、A4-06（区间、by_kind）、A4-09（按工具日序列） | A4-03、A4-07、A4-13（`would_prompt / permission_denied`） | — | A4-02、A4-08、A4-10（AN-01.2 下钻）、A4-14（AN-11）、A4-15 |
| A5 项目习惯 | 11 | A5-01 | A5-06、A5-09、A5-10 | A5-03、A5-11 | A5-05、A5-08 | A5-04、A5-07、A5-12（AN-11） |
| A6 情绪与语义 | 9 | A6-10 | A6-07 | A6-03、A6-08（`friction_type` 分布） | — | A6-01、A6-02、A6-06、A6-09（`cluster_ids`）、A6-11（AN-07，v1） |
| A7 优化建议 | 6 | — | A7-15 | A7-08、A7-09（显式 session 集合）、A7-12 | — | A7-02（重算 / 状态）、A7-03 |

**结论**：补齐 signal 层和 metrics 引擎（任务包 a）后，约 30 个条目可以从「部分 / 计划」推进到可接线。A2 的大部分条目等待 PR #27，不在本次范围内。

---

## 2. 类别族是否完整

### 2.1 现有八族与 feature（按 `analytics/dictionary.py` 合并字典）

| 族 | 目录 | 已有 feature（摘要） |
| --- | --- | --- |
| Task | `task/` | `domain / task_type / task_title / task_goal / task_goal_history / expected_artifacts / task_boundaries / related_session_ids`；`segment_tasks`；文本表示 `cluster_id / embedding_x,y / novelty / top_terms` |
| Instruction | `instruction/` | 8 字段约束（`requested_autonomy / execution_order / verification_requirements / allowed_scope / prohibited_actions / acceptance_criteria / format_requirements / tool_requirements`）+ 13 项结构计量（`prompt_char_count … constraint_density`） |
| Preference | `preference/` | `preference_statement / type / scope / evidence / effective_at / history / polarity` |
| Interaction | `interaction/` | `message_intents / friction_types / confirmed_correction_count,rate / repeated_requirement_count / intervention_points`；词表 `correction_signal_count,rate` |
| Respond | `respond/` | 调用计数与状态（`call_count … unpaired_count / success_rate`）、耗时分位、`error_count / branch_count / rollback_rewind_count / compaction_count / permission_request_count / subagent_spawn_count / interruption_count`、重复转移、`consecutive_failed_calls / confirmed_same_argument_failed_retries`、`failure_reasons`、`retry_links`、DFG |
| Cost-Time | `cost_time/` | `request_count / total_tokens / cost_usd / median_latency,ttft`、节律（按日、按小时、星期）、执行时长与区间并集、日志间隔估算 |
| Outcome | `outcome/` | `validation_runs / acceptance_results / task_success`（`task_success` 恒为 None） |
| Subjective Outcome | `outcome_subjective/` | `user_acceptance / user_confirmed_completion / rework_feedback / feedback_target / *_count` |

### 2.2 判断

- **不新增业务族**。同意 `analysis-review.md` §「八族与二维分类」的结论：画像、趋势、轨迹、实时状态都是跨族组合。
- **要新增一个横向的派生层 `analytics/signals/`**。它不是第九个族，而是「八族事实 → `signal` → `problem` / `key_moment` / `session_outcome`」的唯一出口。目前同类逻辑分散在三处：`profiling/bottlenecks.diagnose`（旧链路）、`recommendations/rules.evaluate_features`（7 条规则信号）、`products/journey`（时刻标签）。三处的口径各不相同，UI 的摩擦分布、关键时刻、建议依据因此对不上（BUG-27 一类问题的根源）。
- **族内应补的 feature（只列 UI 需要的）**：

| 族 | 补充 | 服务的 UI | 理由 |
| --- | --- | --- | --- |
| Respond | `would_prompt`（只读 shell 在 default 权限下仍需审批）、`permission_denied`、`risky_command`（DT-13 破坏性命令族，词表命中即可） | A4-07、A4-13、A7 scope-guard | 推荐的 `permission_rule / hook` 需要这三个事实 |
| Respond | 子代理最大并行数、平均时长（复用 `relations.execution_intervals`） | A4-08、A4-15 | Demo 写死 |
| Respond（v1） | `runaway_loop`、`edit_churn` | A3-12、POP-09 | 规则简单，复用 `tool_sequence` |
| Interaction | `autonomy_steps`（会话行：每个含真人消息的轮次的步数中位数） | A1-15、A3-11、A2-07 | `interaction_habits` 已按轮次计算，但没有落到会话行 |
| Interaction（v1） | `frustration` 词表 | A6-06、A6-11 | 与情绪曲线配套 |
| Outcome | `missing_verification`（最后一次 `file.edit` 之后没有验证） | A3-18、A7 验证阶梯 | 直接消费 `validation_runs` |
| Outcome | 会话结果合成器 `session_outcome ∈ completed/partial/failed/abandoned/unknown` + `basis` | A1-09、A3-06、A3-08、A2-16、A5-10 | `task_success` 恒为 None；UI 的「结果」列没有来源 |
| Cost-Time | 空闲折叠后的协作时长（间隔 > 30 min 截断）、`resident_tokens_median`（首个请求 `input_tokens` 中位数） | A1-13、A4-14、AN-11 | Demo 用会话时长之和，口径错误 |
| 共享 | `stats.py`：统一的 Wilson / `insufficient`（n < 门槛）/ 指标对象 | 所有 KPI 卡 | 现有两份 Wilson（`profiling/analysis.py:16`、`products/statistics.py:85`） |

---

## 3. 计算结果的持久化

### 3.1 现状

| 项 | 现状 | 证据 |
| --- | --- | --- |
| 结果表 | `analysis.sqlite`：`analysis_run`（每次执行）+ `analysis_snapshot`（按 sha256 去重的 zlib 压缩 JSON） | `packages/data/src/tandem_data/migrations/analysis/001.sql`、`analysis_history.py:73 complete` |
| 版本号 | 结果中带 `FEATURE_VERSION`、`RULE_VERSIONS`、`INSTRUCTION_VERSION`；`analysis_digest = stable_id(content_digest, scope, versions, with_text)` | `analytics/service.py:302-311, 371` |
| 输入指纹 | 只有 `bundle.versions.content_digest`（canonical 为 projection run），没有会话粒度的指纹 | — |
| 读路径 | **没有**。`recorded()` 先 `start` 再计算，然后 `complete`，从不查找已有的相同 digest | `analytics/history.py:25-54` |
| 失效 / 增量 | 没有 | — |
| 清理 | 没有。每个请求追加一行 run，快照只按内容去重 | — |

### 3.2 重复计算与浪费（实测，1,000 会话 / 4.1 万事件）

1. **每个端点都全量计算**：`/overview`、`/tools`、`/projects`、`/statistics`、`/lexical`、`/bottleneck`、`/sessions`、`/sessions/{id}` 各自调用 `analyze_store`（`routes.py:84-93`），而且都会附带计算 `lexical`、`statistics`、`recommend_resources`。打开一个 A1 页面要发 5–6 个请求，同样的计算就做 5–6 遍。
2. **`/sessions`、`/text`、`/projects` 强制 `with_text=True`**（`routes.py:93`），会触发 O(N²) 的 `temporal_novelty`：1,000 会话时单次请求约 74 s。
3. **`/sessions/{id}` 为了返回一行，要算完整结果**（`routes.py:219-225`）。
4. **每次请求写入完整快照**：1,000 会话时 145 MB JSON，写入 1.7 s；`records` 分页取 50 行要解压全量（0.92 s）。
5. **`compare_previous=true` 把上期完整 product 嵌入结果**（`products/service.py:173`），快照体积翻倍。
6. **同一次请求内的重复工作**：八族先按每个根会话算一遍，再按每个项目算一遍，最后按全体算一遍。项目层还要逐个项目扫描全部事件（`service.py:146-147`，O(P·E)）。

### 3.3 设计：按需 + 增量 + 结果缓存

**原则**：只在派生库 `analysis.sqlite` 落盘，不写 canonical 库；默认范围预热，其余按需惰性计算；输入或版本变化即失效，没有 TTL 意义上的「过期仍可用」。

```
请求(scope, section) ──► request_key = H(scope 规范化, section 参数, ALGO_VERSION)
                       ├─► input_fp = H(projection_run_id, 选中会话树指纹集合)  ← 1 条 GROUP BY SQL
                       ├─► 进程内 LRU[request_key, input_fp] 命中 → 直接返回（≤ 50 ms）
                       ├─► analysis_section 表命中 → 解压该 section 返回（不解压整份快照）
                       └─► 未命中 → 惰性计算该 section 所需的最小依赖：
                                session_rows（会话级缓存复用 + 只算变更的根会话，可并行）
                                → 聚合（O(E) 一次分组）→ 写 section 与 session 行缓存
```

**新增表**（`migrations/analysis/002.sql`，`user_version=2`）：

| 表 | 主键 | 列 | 用途 |
| --- | --- | --- | --- |
| `session_result` | `(root_session_uid, scope_class, algo_version)` | `tree_fp, payload(zlib JSON), computed_at` | 会话级家族结果与会话行（不含跨会话字段 `task_ids / preference_ids / 文本坐标`） |
| `analysis_section` | `(request_key, input_fp, section)` | `payload, json_bytes, sha256, created_at, last_hit_at, hits` | 每个端点的 section 单独存储，读时只解压一段 |
| `analysis_row` | `(request_key, input_fp, section, idx)` | `payload` | 大数组（sessions、records）逐行存储，分页时直接 `LIMIT/OFFSET` |
| `session_exclusion` | `session_uid` | `reason, created_at` | AN-16.1 |

- **`tree_fp`**：对根会话树的 `count(event)`、`max(event.rowid)`、`count(tool_call)`、`count(model_call)`、`max(seq)` 做哈希。用一条 `GROUP BY root_uid` 的 SQL 一次取全部，走已有索引 `event_by_call(session_uid, …)`、`projection_fk_tool_session`、`projection_fk_model_session`。指纹放在 `tandem_data/analysis_fingerprint.py`。
- **`scope_class`**：表示会话树在当前 Scope 下是否被完整选中。会话树落在时间窗内、且没有模型 / 档位过滤时记为 `full`，可以跨窗口复用；跨越窗口边界的会话树记为对过滤条件的哈希，只在相同过滤下复用。
- **`algo_version`**：`H(FEATURE_VERSION, RULE_VERSIONS, INSTRUCTION_VERSION, VECTOR_VERSION)`。规则一变，旧行自动失配。
- **增量**：导入完成后只重算 `tree_fp` 变化的根会话行；聚合（全体、项目）用缓存的会话行加原始列表做一次 O(E) 分组。跨会话的 Task、Preference、文本表示、词频、统计只在请求对应 section 时惰性计算，并按 `input_fp` 缓存。
- **预热**：导入完成后在后台计算默认 Scope（全部时间、`with_text=False`）的 `overview / sessions / tools / projects`，让 App 首屏命中缓存。
- **清理**：`analysis_section` 每个 `request_key` 只保留最近 3 个 `input_fp`；整库超过 512 MB 时，按 `last_hit_at` 淘汰。`analysis_run` 中的失败记录保留 30 天。`session_result` 对每个根会话只保留当前 `algo_version`。
- **与文档的冲突**：`analysis-module.md` §5.1 和 §5.3 写的是「查询现算，不建 `session_row` 缓存；MVP 不做增量缓存」。实测 10 万事件冷算 40.9 s，超出预算 4 倍，不满足这一前提。该段改为「会话行物化 + section 缓存」，由任务包 b 同步更新 analysis-module.md。

---

## 4. 计算与分析速度

### 4.1 方法

- 构造数据生成器：`scratchpad/audit/synth.py`（12 个项目、3 个来源，每会话 4 个提示 × 4 次工具调用，带模型调用和子代理；文本为 10 条虚构短句随机组合）。
- 快速修复的效果用进程内 monkeypatch 测量：`scratchpad/audit/patched.py`，不修改仓库文件。
- 环境：macOS arm64，CPython 3.13.15，单进程。

### 4.2 实测

| 场景 | 会话 | 事件 | 工具调用 | 现状 | 三处快速修复后 |
| --- | --- | --- | --- | --- | --- |
| `analyze_bundle(with_text=False)` | 500 | 20,432 | 8,000 | 3.1 s | — |
| 同上 | 1,000 | 40,858 | 16,000 | 7.5 s | **3.4 s** |
| 同上 | 2,500 | 102,148 | 40,000 | **40.9 s** | **9.1 s** |
| `build_products(with_text=False)` | 1,000 | 40,858 | 16,000 | 17.5 s | **4.9 s** |
| `analyze_bundle(with_text=True)` | 1,000 | 40,858 | 16,000 | **73.8 s** | 69.8 s（新颖度未修） |
| 结果 JSON 体积 | 1,000 / 2,500 | | | 145 MB / 365 MB | — |
| 历史写入 / 全量读取 / 分页 50 行 | 1,000 | | | 1.7 s / 0.93 s / 0.92 s | — |

### 4.3 热点（cProfile，按 cumtime）

| # | 热点 | 占比（1,000 会话，现状 21 s profile） | 原因 | 修法 |
| --- | --- | --- | --- | --- |
| 1 | `AnalysisContext.main_ids`（`context.py:56`） | 6.2 s（30%），41,874 次调用 | `@property` 每次都重建集合，又在逐事件循环里调用（`products/statistics.py:143`、`trends.py:67`、`summaries.py:66`、`journey.py:250,254`），复杂度 O(E·S) | 改成只算一次的缓存属性（frozenset） |
| 2 | `temporal_novelty`（`task/representation.py:33`） | with_text 时约 66 s | 每个会话都对全部「更早会话」重新拟合 TF-IDF+SVD，复杂度 O(N²) 次拟合 | 改用无需拟合的 `HashingVectorizer`（char 2–4，l2），按时间排序后分块计算稀疏矩阵乘积的下三角最大值；不会泄漏未来数据。`VECTOR_VERSION` 升级 |
| 3 | 八族重复计算（`context.families` 被调用 1,013 次：每会话、每项目、全体各一次） | 8.3 s | 项目与全体层把所有事件再完整算一遍 | 结构问题，由任务包 (b) 用会话行复用加一次分组解决 |
| 4 | `normalize_tool_calls` 的 `deepcopy`（`respond/calls.py:79`） | 2.3–5.9 s | 每次调用对每行做深拷贝，而且会对同一批调用重复执行（会话、项目、全体） | 改为浅拷贝 `dict(original)`，只对 `files` 等列表做 `list()` 拷贝 |
| 5 | `direct_user_text`（`privacy.py:43`，markdown-it 解析） | 3.2 s，4 万次调用对应 4,000 条真人消息 | 四个模块对同一文本重复解析 | 纯函数，加 `functools.lru_cache(maxsize=65536)` |
| 6 | `summarize_durations` 中的 `session_spans`（`cost_time/durations.py:34-36`） | 1.7 s | 每个会话都扫描一遍全部事件，复杂度 O(S·E) | 一次 `group_sessions` 分组 |
| 7 | `_project_rows`（`service.py:146-147`） | 2.3–5.0 s | 每个项目扫描全部事件和调用 | 复用 `context.event_groups / call_groups` |
| 8 | `correction_terms` 每次调用都执行 `re.escape` 和临时 `re.sub` | 1.4 s | 正则没有预编译 | 预编译为模块常量 |
| 9 | sklearn 导入（`representation.py` 顶层导入） | 冷启动约 1.7–6 s | `analytics.service` 导入链的顶层就会加载 sklearn、scipy | 在 `representation()` 内延迟导入；API 首请求和 CLI 都受益 |
| 10 | 输入读取（`tandem_data/analysis_input.py`，静态分析） | 未测（需要 canonical 库） | `SELECT * FROM v_analysis_tool_call / v_analysis_model_call / session` 全表扫描后在 Python 里过滤（:216、:251、:267）；`until_ts` 时每个调用单独查一次审批（:225，N+1）；`next(e for e in events …)` 在循环内线性查找（约 :259，O(T·E)）；`json.loads` 解码全部 `attrs` | 用 `IN (SELECT event_uid FROM members)` 下推；用一条带窗口函数的 SQL 批量取最后审批；用 `event_lookup` 字典查找 |

**并行**：会话级家族计算是纯函数，可以按根会话分块，用 `ProcessPoolExecutor` 并行（macOS 下 spawn，块大小约 200 个根会话，只把会话树的原始行传给子进程）。缓存命中后需要计算的会话通常很少，所以并行只在冷算时启用（未命中的根会话 ≥ 300 个时）。

**目标**（在 10 万事件构造数据上验收）：冷算 `with_text=False` ≤ 5 s，`with_text=True` ≤ 8 s；热请求（缓存命中）`overview` ≤ 200 ms，`sessions?limit=50` ≤ 100 ms；导入 1 个新会话后的增量重算 ≤ 1 s。

---

## 5. 任务包

文件集合互不重叠；`api/routes.py` 和 `analytics/service.py` 只归 (b)。(a) 通过新文件 `api/insights.py` 提供 `APIRouter`，在 (a) 合入后由 (b) 加一行 `include_router`；如果 (b) 先合入，则由 (a) 在 rebase 时补这一行（这是本方案唯一的一处跨包衔接）。

| 包 | 内容 | effort |
| --- | --- | --- |
| (a) | signal 层与缺失 AN feature：stats、signals（检测器适配、problem 升级、关键时刻、会话结果合成、会话事实补字段）、metrics + group_by、工具调用下钻、AN-11 已装未用 | high |
| (b) | 结果持久化与执行框架：会话树指纹、`analysis.sqlite` v2（session_result、section、row、exclusion）、读穿缓存、惰性 section、增量重算、按会话并行、预热、清理、AN-16.1 端点 | high |
| (c) | 算法热点：main_ids、deepcopy、direct_user_text、spans、正则、新颖度、sklearn 延迟导入、`analysis_input.py` SQL 下推 | medium |
| (d) | 构造数据基准与等价性回归：可复现的生成器、全链路基准、核心 section 的金标摘要（保证 (b)、(c) 不改变结果） | medium |

---

## 6. 优化后实测

合入全部导入与分析优化（含分析单进程路径提速 `wip/yhyfhgs-analysis-serial` 与首导写者 `wip/yhyfhgs-writer2`）后的最终验收复测（2026-10-03 04:36–04:50，`wip/yhyfhgs-int` 的 `a29da8b`；同一提交 `pnpm check` 全部通过）。

- **对照**：审计基线 `747b0da`。两边用各自的 `.venv`（CPython 3.13.15），读取同一份共用构造输入包（`bundle-2500` / `bundle-1000`），`Scope(display_timezone="Asia/Shanghai")`，`with_text=False`。
- **方式**：每次运行都是新进程，在机器级基准锁里串行执行；基线与新代码紧挨着成对运行。`workers=1` 用环境变量 `TANDEM_ANALYSIS_WORKERS=1`（基线为单进程，不受影响），默认 workers 不设该变量。每种组合成对 2 次；`workers=1` 在 load 降到 4 左右时又补测 1 对。
- **负载**：机器为 14 核 Apple M4 Pro，测量期间有其他 agent 占用 CPU；表中为每次运行开始时的 1 分钟 load average。

| 场景 | workers | 对 | 负载（基线 / 新，开始） | 基线 | 新值 | 加速比 | 目标 | 达标 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `analyze_bundle` 2,500 会话 | 1 | 1 | 14.6 / 9.3 | 51.1 s | 9.11 s | 5.61× | ≥6.8× | 否 |
| | 1 | 2 | 14.8 / 13.8 | 54.5 s | 9.16 s | 5.95× | ≥6.8× | 否 |
| | 1 | 3（低负载补测） | 4.3 / 3.9 | 45.9 s | 8.86 s | 5.19× | ≥6.8× | 否 |
| | 默认 | 1 | 6.9 / 5.1 | 46.1 s | 6.12 s | 7.53× | ≥6.8× | 是 |
| | 默认 | 2 | 12.0 / 8.1 | 46.6 s | 6.41 s | 7.27× | ≥6.8× | 是 |
| `build_products` 1,000 会话 | 1 | 1 | 8.4 / 7.4 | 15.9 s | 4.14 s | 3.84× | ≥4.4× | 否 |
| | 1 | 2 | 12.9 / 12.7 | 17.0 s | 4.43 s | 3.84× | ≥4.4× | 否 |
| | 1 | 3（低负载补测） | 3.7 / 3.4 | 16.0 s | 4.29 s | 3.74× | ≥4.4× | 否 |
| | 默认 | 1 | 5.6 / 12.0（新结束 14.8） | 23.7 s | 10.15 s | 2.33× | ≥4.4× | 否 |
| | 默认 | 2 | 7.8 / 6.8 | 16.3 s | 3.22 s | 5.07× | ≥4.4× | 是 |

**说明**

- **默认 workers 的 `analyze_bundle`**：两对 7.53× / 7.27×，达标，且比上一轮（load 5–7 时 6.77× / 6.96×）更高，单进程路径的提速也惠及并行路径。
- **`workers=1` 未达标**：`analyze_bundle` 为 5.2–6.0×，`build_products` 为 3.7–3.8×。load 4 左右的补测对并不更好（5.19× / 3.74×），说明差距不是负载造成的，而是单进程路径本身的耗时（`analyze_bundle` 约 8.9–9.2 s、`build_products` 约 4.1–4.4 s）仍高于目标所需的 6.8 s 与 3.6 s；`wip/yhyfhgs-analysis-serial` 的提速尚不足以单独达标。
- **默认 workers 的 `build_products`**：低负载对 5.07× 达标；另一对新代码开始时 load 12.0、结束时 14.8（其他 agent 突发占用），新值 10.15 s 是低负载时 3.22 s 的 3 倍，并行部分抢不到核心，记为未达标对。

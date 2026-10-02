# 分析模块设计：跨 Agent、跨项目、跨模型的会话分析体系

> 状态：方案（不等同当前能力） · 维护者 `yhyfhgs` · 核对版本 main `0c96334` · 适用：Advance / Lite（另注明处除外）

> 版本：2026-10-02 第 2 版（按评审意见修订）。依据：**origin/main `6f31203`**（PR #28 结构迁移之后；后端算法与 PR #19 合入时相同，只是目录搬到 `packages/backend/src/tandem_backend/`）。已合入 main：PR #9 / #14（`packages/data`，tandem-session-v1，`migrations/001–004.sql`，`user_version = 4`，`contract.KINDS` 26 种）、PR #11（`packages/connectors`，Codex TypeScript connector，事件 Schema 25 种、缺 `permission.request`，35 项构造回归）、PR #12 / #15（Lite Demo 与 Lite / Advance 命名）、PR #13 / #16 / #17（`MistyHuang03`，`analytics/{task,preference,instruction,outcome_subjective}`）、PR #19 / #24（`genius-FXC`，`analytics/{respond,interaction,cost_time,outcome}`，`bottleneck-features-v1`）、PR #26 / #29（推荐与 catalog）、PR #30（`docs/plans/analysis-review.md`，八族职责与两版 UI 缺口）。未合入：PR #27 `feat/feature-display-metrics`（`genius-FXC`，`analytics/presentation/`，`presentation-v1`）、PR #31 `feat/local-inventory`（`yhyfhgs`，DT-09 七个 Agent 的安装清单扫描）、PR #32 `feat/analytics-products`（`yhyfhgs`，`analytics/products/`，`analysis-products-v1`）、PR #33 `feat/data-app-integration`。模块契约 [`contract.md`](module-contract.md) 第 2 版 + 本轮评审统一结论（并入第 3 版的条目见 §11）。
>
> 路径对照（PR #28 之后）：`src/tandem_backend/` → `packages/backend/src/tandem_backend/`；旧链路 `feedback / bottlenecks / portrait / analysis / trajectory / content.py` → `profiling/*.py`（根级同名文件只剩兼容导出）；`api.py` → `api/routes.py`；`evaluation / pipeline_eval / reader_eval.py` → `evaluation/{readability,pipeline,reader}.py`；`docs/contracts/analysis-inputs.md` → `docs/contracts/analysis-inputs.md`；`docs/backend/*` → `docs/modules/analytics/*`、`docs/architecture/*`；Advance Demo `prototypes/advance/src` → `prototypes/advance/src`；Lite Demo → `prototypes/lite/tandem-benchmark-demo.html`（页面表 `docs/design/lite-review.md`）。配套文档 `recommendation.md`、`ai.md`、`evaluation.md` 若仍引用 `c97c818` / `f4a2cde` 与旧路径，按本表换算。
>
> 本文回答「各种 session 要分析什么」，并把每一项落到数据契约的真实列名、现有代码与 Demo 面板上。不实现算法；写清输入 → 处理 → 输出、MVP 与迭代、复杂度。标「待验证」的是需要真实数据或实测才能定的技术假设（只引契约 §7 编号，见 §12）；标「实验性」的是界面上必须如此标注的产物。成员一律用 GitHub 账号指代；版本名统一为 Lite / Advance。三张端到端功能卡（只读放行、重复失败熔断、高频纠偏 → 规则）与合并后的前端升级表在 `docs/plans/feature-map.md`，本文只写各卡的第 2 段「触发与证据」（§8）。

## 0. 结论先行

1. **分析对象分八层**：事件 → 轮次 → 会话 → 任务 / 工作段 → 项目 → Agent / 模型 × 思考档位 → 用户整体 → 时间演变。每层有自己的身份键、单位与分母，指标只在定义它的那一层计算，再向上聚合；向上聚合按会话去重，不让长会话多投票（§1）。二级筛选（主题 / 结果 / 摩擦 / 时段）先解析成会话集合，其他端点用 `root_session_uids` 复用，不扩 `Scope`（§1.2）。
2. **指标分 13 组约 100 项，全部确定性，每张表带「阶段」列**（§2）。main 八族已实现约 60 项；**MVP = feature-analytics 现有测量 + Lite 8 页用到的约 20 项 + §2.13 安装追踪注册表，比例只带 Wilson**；其余 v1。本文新增且必须新写的只有：`signal → problem` 映射与升级（AN-05 / AN-06）、会话结果合成器（AN-19，约 60 行，复用 `outcome` 与 `outcome_subjective`）、带区间的 `metrics` 端点（AN-01）、四轴 Wilson 版（AN-08）、规则关键时刻（AN-09）、追踪注册表（§2.13）。
3. **`problem.type` 不等于 `friction_type`**（§2.4）。`friction_type` 只留在 `signal` 上供 A6-08 分布与 AI-04.1 细分；`problem.type` 取推荐决策表的 12 类（`repeated_instruction / communication_gap / repeated_workflow / missing_verification / tool_env_failure / permission_friction / context_loss / parallel_conflict / quota_interrupt / process_overhead / unsafe_operation / misunderstood_request`），`key` 一律写全称 `<signal.kind>:<子键>`（如 `would_prompt:readonly_shell`、`retry_loop:wrangler`、`correction:verification`），推荐侧按全称比对。`installed_unused / resident_cost` 是事实，不进 `problem` 表。
4. **真人分母、未知保持未知、分母 < 5 不出数**（§4）。沿用 main 的保守口径：真人消息 = `v_human_message`；状态未知不当成功；缺事件不等于没发生；时间未知不进有界统计；fork / replay 副本不计数。MVP 的区间只有 Wilson（`profiling/analysis.wilson_interval` 已有）；Newcombe、Beta-Binomial、bootstrap 与响应里的 `method` 字段全部 v1。
5. **会话结果只有一套对外口径**：AN-19 `outcome ∈ {completed, partially_completed, abandoned, unknown}`；AI-03 facet 五态经 §2.3 映射表进入，`outcome_basis` 增 `facet`；`completed_rate` 分母 = `outcome ≠ unknown`，另报 `unknown_n`。验证证据只认 `outcome.extract_validation_runs()` 的 `executed = true` 记录，只命中 `command_head` 的是 `verify_candidate`（proxy），不作 `completed` 的证据。
6. **摩擦 → 问题 → 推荐是单向链**：检测器产 `signal`（每会话每类型最多参与一次会话级计数），AN-06 按 `(problem_type, key, scope)` 聚合，`min_sessions` 按类型（`repeated_instruction` = 2，其余 3）∧ Wilson 下界 ≥ 阈值（契约 V1）升级为 `problem`；推荐只吃 `problem`、`profile` 与 AN-11 的清单事实（§2.4、§8）。
7. **第一件事是 AN-16**：把 PR #14 已合入的 `tandem_data.analysis_input.read_analysis()` 适配成 `AnalysisInputBundle`（`analytics/inputs.py` 的 canonical 适配器尚未闭环），用真实 `tandem.db` 重跑现有 analytics，核对 `human_origin` 覆盖（契约 V11，阻塞 MVP）。
8. **计算管线 = 会话行物化 + section 缓存**（§5，负责人已决定，替代原「查询现算、不建缓存」）：会话行按根会话树指纹物化到 `analysis.sqlite` 的 `session_result`，各端点 section 按 `(request_key, input_fp)` 缓存，只重算变化的会话树；`signal / problem` 用确定性 ID（`stable_id(session_uid, kind, event_uid)`、`stable_id(type, key, scope, scope_id)`），`problem` 的 `resolved / dismissed` 写 `label`，section 先查进程内 LRU、再查 `analysis_section`；`analysis.db` 在 MVP 只存用户状态（`candidate / label / install_ledger / tracking`）。性能预算：100k 事件冷算 ≤ 10 s（首次导入后带 `analysis_run` 进度）、热查询 ≤ 1 s（契约 V4，阻塞 MVP）；审计实测 10 万事件冷算 40.9 s，不满足原「查询现算」的前提，因此会话行物化与 section 缓存提前到 MVP（[审计](analysis-audit.md) §3.3）。
9. **目录不再搬**：八族（`task / instruction / preference / interaction / respond / cost_time / outcome / outcome_subjective`）已全部在 main；MVP 只新增 `analytics/signals.py`（检测器适配、映射表、AN-06 升级、规则时刻）与 `analytics/stats.py`（Wilson、`insufficient`），四轴写在 `profiling/portrait.py` 旁；组合层以 PR #27 `analytics/presentation/` 与 PR #32 `analytics/products/` 中先合入者为底，另一个 rebase 并入，本文 §2 的口径是两者的验收标准（§5.2）。
10. **MVP 判定规则**（契约 §2.1 第 3 版）：MVP = Lite 8 页需要的数据 + Advance 三张安装闭环卡；只服务 Advance 独有界面（A9 工坊、ASK、菜单栏 / HUD / 小组件、首次启动、SET-21 周报、A1-06 上期对比、A3 阶段带与情绪泳道）的 feature 一律 v1。据此 AN-07 情绪、AN-13 实时状态、AN-14 `report_snapshot` 表、AN-12 的周序列与 `compare_previous`、AN-03 阶段打标、AN-10 的 EB / bootstrap 全部 v1（§6）。
11. **Demo 的差距集中在三处**（§9、§10）：两版 Demo 自算的指标（`15-derive.js::stats / persona`、Lite `stats() / persona()`）全部换成后端 `metrics / profile`；A3 时间线沿用本地 `ui/vizkit` 的密度泳道 / 关键时刻簇 / minimap / 回放组件，只换数据源（本机工作文件 第 3 条）；A4 / A6 的静态表改为按 `Scope` 实时计算并按 `n / lo / hi / basis` 渲染。

## 1. 分析对象层级

### 1.1 八层

每层写：单位与身份键（tandem-session-v1 列名）、这一层独有的指标、向上聚合规则、现状。所有层共用 `Scope`（`display_timezone / project_ids / model_ids / effort_raw / from_ts / until_ts / root_session_uids / excluded_session_uids / include_children / scene`，补充 `source_ids`；PR #27 另有 `agent_ids`、PR #32 有 `source_ids`，合并时统一为 `source_ids`）。

| 层 | 单位与身份 | 这一层独有的指标 | 向上聚合 | 现状 |
| --- | --- | --- | --- | --- |
| L-E 事件 | `event(event_uid, session_uid, seq, kind, actor, ts, attrs)`；工具调用配对后为 `tool_call(call_uid)`；模型请求为 `model_call(call_uid)` | 单条事实：`kind`、`actor`、`attrs.origin`、`text_truncated`、`attrs.time.quality`；`tool_call.status / status_scope / error_class / duration_*`；`model_call` 五个 token 桶与 `cost_source` | 不聚合；作为证据回链（`GET /v1/evidence/{event_id}`）与信号定位（`signal.event_uid / call_uid`） | main `legacy_bundle()` 适配 8 种 kind；`packages/data` `contract.KINDS` 26 种；`packages/connectors` Schema 25 种（缺 `permission.request`，契约 V12） |
| L-T 轮次 | `turn(turn_uid, session_uid, idx, trigger, status, started_at, ended_at)`；legacy 由 `stable_id(session_id, turn_id)` 生成 | 轮内 Agent 步数（`autonomy_steps` = 工具调用 + 非进度回复）、轮内失败串、轮次状态（`completed / interrupted / failed / unknown`）、轮内 token、是否由真人触发（`trigger = human`） | 轮次是「D 轴」与「摩擦比例」的计数单位：同轮多个事件只算一次 | `turn_count`、`turns` 已有；`autonomy_steps` 雏形 = `profiling/portrait.interaction.recorded_steps_per_request`（按任务）、PR #32 `products/journey`（按真实轮次统计 Agent 步骤） |
| L-S 会话 | `session(session_uid, kind, root_uid, parent_uid, project_id, started_at, ended_at, status)`；主会话 = `kind = main`；子代理归根会话（`include_children`） | AN-02 会话事实行：消息 / 轮次 / 工具 / 用量 / 时长 / 纠偏 / 结果 / 验证 / 压缩 / 簇与坐标 / 信号摘要；`session_feature(feature, value, n)` | 会话是比例类指标的分母单位（有 ≥ 1 条确认真人消息的主会话）；`review / automation / import / auxiliary` 默认排除 | main `session_features()` + 行级 `usage / tools / workflow / subjective_outcomes / bottleneck_features`；缺 `outcome / verify_* / autonomy_steps` |
| L-K 任务 / 工作段 | `segment(session_uid, level ∈ task/phase, idx, label, first_event_uid, last_event_uid)`；任务身份 `task_id`（main `task/features.segment_tasks` 的 `task_id_source ∈ native/human_confirmed/legacy_inferred`；`profiling/feedback.task_contexts` 为旧链路）；`work_block(block_id, session_uids, interleaved, agent_sequence)` | 任务：场景、读者、交付语言、8 维度要求、目标版本、产物、`domain / task_type`（task-taxonomy-v1）、结果；阶段（v1）：`explore / plan / implement / verify / debug / deliver / converse`；工作段：跨会话 30 分钟空闲切分、是否交错、Agent 序列 | 任务数按 `(session_uid, task_id)` 去重；场景会话数不可相加；同任务重复要求只加消息数不加会话数 | 任务级：main `analytics/task/`；工作段：PR #32 `products/journey`（部分）；阶段：v1（AN-03） |
| L-P 项目 | `project(project_id, key_type ∈ git_remote/git_root/path/bucket, paths)`；legacy 只有 `legacy_project_id` | 项目聚合（现有 `projects[]`）+ 工作流模式（AN-04）+ 规则与配置覆盖（DT-09 `inventory_item`，PR #31）+ 项目内画像（AN-08 `scope = project`）+ 项目内问题（`problem.scope = project`）+ `tags` | 项目是推荐作用域（`candidate.scope`）与「跨项目候选」判断（`_preferences.scope = cross_project_candidate`）的依据 | main `projects[]`（canonical `project_id` 随 AN-16 接入） |
| L-A Agent / 模型 × 档位 | Agent = `source.agent`（只作来源筛选 `source_ids`，不作画像维度，DA §4.5）；模型 = `model_call.model_id`、档位 = `(provider, effort_raw, effort_rank)`；会话级近似 = 该会话 `model_call` 的众数 | 分层描述：同一指标按 `(model_id, effort_rank)`、`source.agent`、`task_type` 分组的 `n / value / lo / hi`；`model_resolution = unmapped` 单列为「未归一」 | 只做分层描述，不排名；混杂提示（强模型常被分配难任务）随卡片固定展示 | main `usage().models`；PR #32 `model_effort` 段（按请求实际记录的模型与档位汇总，不按会话近似分摊）；`group_by` 端点计划（AN-12） |
| L-U 用户整体 | 一个本机用户 = 全部 `source`；多根目录不是多个人 | 画像（AN-08）、问题清单（AN-06）、已装未用与常驻开销（AN-11）、总用量与额度（DT-08 / DT-17）、概览 KPI（AN-01） | 全局与项目 / 模型分层共用同一引擎，只换 `Scope` | main `overview` 段；画像雏形 `profiling/portrait.profile()`；PR #27 `presentation/profile.py`（`collaboration-profile-v1`） |
| L-H 时间演变 | 按 `display_timezone` 分桶：日 / 周（ISO 周一起）/ 月；上期 = 同长度紧邻窗口 | 日序列（MVP）；周序列、上期对比、逐月画像（按月窗口现算）、变化检测（v1）；跨 Agent 切换（v1，§3.1） | 周桶末尾不完整周标注「进行中」；时间未知记录单列 | main `activity()` 有 `by_day / by_hour / weekday`；PR #32 `bucket=day∣week∣month` 与 `compare_previous`、PR #27 `monthly_trend`（最近 12 个月） |

层间关系的硬规则：

- 子代理 / workflow_agent 的工具与用量归根会话（`include_children = true`），其注入文本不进真人分母；`v_analysis_*` 视图默认只含 `main` 与已解析的子树。
- fork 新增行为可分析，复制段按 L1 `record_event.relation ∈ replayed/duplicate` 剔除（main `select()` 已按 `attrs.replayed_from / duplicate_of` 剔除；legacy 下无复制边界的 fork 整体排除）。
- 任务、阶段、场景、读者、交付语言、`task_type` 是分析派生标签，不是 L3 列；筛选 `scene` 不改写用户原话。
- 上下文材料与统计成员分开：窗口前的原始要求可作上下文，不进窗口内计数；窗口后的返回不泄漏进早期快照（main `select()` 的「未来返回隔离」；PR #14 `read_analysis()` 把截止时间之后的 `session.ended_at / status` 置为 `unknown`）。

### 1.2 二级筛选解析与各页生效范围

Demo 的主题 / 结果 / 摩擦 / 时段芯片（FB-04…FB-06）、A1-23 星期 × 小时下钻、A6 → A3 下钻都是「会话集合」筛选，不扩 `Scope`：

| 步骤 | 做法 | 现状 |
| --- | --- | --- |
| 解析 | `GET /v1/analytics/sessions?Scope&cluster_id&outcome&friction_type&weekday&hour&signal_kind&problem_id` 返回会话 ID 集合（≤ 200 行分页；超过时返回服务端 `selection_id`，24 小时有效，避免长 URL） | 现有路由 + 新增参数（契约 §3.1 已把 `signal_kind / friction_type / hour / weekday` 限定在 `sessions / signals` 端点） |
| 复用 | 其他端点带 `root_session_uids`（或 `selection_id`）即可按同一口径重算 | main `Scope.root_session_uids` 已有 |
| 回显 | 响应 `meta.scope` 回显解析后的筛选与会话数，界面据此标注口径 | 计划 |

| 页面 | 生效的筛选 | 说明 |
| --- | --- | --- |
| A1 概览、A3–A6、Lite 概览 / 会话 / 工具 / 项目 / 情绪 | `Scope` 全部 + 二级筛选 | A1 KPI 与 A5 带「结果 = 完成」时按同一会话集合重算 |
| A2 协作画像、Lite 协作画像 | 只认窗口（A2-01 自有周期）+ `source_ids` + `project_ids` | 画像不随主题 / 结果筛选变化；Lite 逐月画像用完整历史并在页面标明 |
| A7–A9、Lite 优化建议 / 资源库 | 不受二级筛选影响 | 推荐批次按 `Scope` 重算（RC-05） |
| 侧栏用户卡 SB-09、REV-01 揭晓、EXP-04 分享卡、WG-02 小组件 | 固定口径：近 30 天、全部已启用来源 | v1（Advance 外壳）；由 AN-14 `report_snapshot(kind = persona_fixed)` 提供 |

## 2. 指标体系

表列约定：**字段**写 tandem-session-v1 / analysis-input-v1 的真实列名；**分母 · 置信度**写分母单位与区间方法（MVP 只有 `wilson` 比例与 `—` 计数；`eb / bootstrap` 标注的行一律 v1）；**Demo** 写 [`feature-map.md`](feature-map.md) §5 条目 ID，Lite 页名写「Lite·页」；**阶段** 按 §0.10 的判定规则；**现状** 写代码名称（`main:` 省略，只写模块）或 `PR#27 / PR#32 / 计划`。所有比例在分母 < 5 时输出 `insufficient`，5–30 必须带区间（契约 §1）。`basis` 取值：`measured`、`estimated`（含 `duration_quality = estimated` 或价目表折算）、`proxy`（词面或结构代理）、`unknown`。

### 2.1 使用概况与节律（AN-01 / AN-12）

| 指标 | 定义 / 公式 | 字段 | 分母 · 置信度 | Demo | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- | --- |
| `sessions`、`main_sessions` | 窗口内会话数；主会话数只作规模，不作分母 | `session.kind`、`started_at` | — | A1-12、SB；Lite·概览 | MVP | `counts` |
| `active_days` | 有 ≥ 1 条确认真人消息的日历日数（按 `display_timezone`） | `v_human_message.ts` | — | A1-22、WG-03 | MVP | `cost_time/activity.active_days` |
| `human_messages`、`human_messages_by_day/hour`、`weekday_distribution`、`by_hour × weekday` | 确认真人消息按日 / 小时 / 星期分桶；时间未知单列 `time_unknown_n`；热力强度 `log(1 + n) / log(1 + max)`（PR #27） | `event.kind = message.user`、`attrs.origin = human`、`ts` | 计数；桶内 n 展示 | A1-14、A1-22、A2-11 中环；Lite·概览 按日强度 / 热力图 | MVP | `activity()`；PR#27 `overview.activity.series`、PR#32 星期 × 小时联合热力 |
| `tool_calls_by_day`、`model_requests_by_day` | 工具调用按 `started_at`、模型请求按 `model_call.ts` 分桶；三类不同单位不相加 | `tool_call.started_at`、`model_call.ts` | — | A1-17（度量切换） | MVP | `activity()` |
| `sessions_by_source`、`sessions_by_project`、`sessions_by_model_effort` | 按 `source.agent`、`project_id`、`(model_id, effort_rank)` 的会话数与占比 | `session.source_id`、`project_id`、`model_call.model_id / effort_rank` | 计数 | A1-17、A1-20、A5-05、A5-10；Lite·项目 Agent 构成 | MVP | 按 `project_id`；模型分组随 AN-16 |
| `observed_span_minutes` | `last_observed_ts − first_observed_ts`，**不是**工作时长 | `event.ts` | — | A1-13、A3-11；Lite·概览「时长」 | MVP | `observed_session_span_ms` |
| `active_minutes` | 会话内可靠工具区间并集 + 真人消息到下一事件 ≤ 10 分钟的间隙（折叠空闲） | `tool_call.started_at / ended_at`（`interval_reliable`）、`event.ts` | `basis = estimated` | A1-13、A3-14 | v1 | 并集 `reliable_interval_union_ms` 已有；空闲折叠计划 |
| `work_blocks_per_day`、`work_block_minutes_median` | 工作段（§3.1）每日个数与时长中位数 | `work_block` | — | A1-13 替代口径 | MVP（随 `work_block`） | 计划（AN-03） |
| `hour_peak`、`night_share` | 真人消息最多的 (星期, 小时) 格；0–5 时消息占比 | 同上 | — | A1-22 结论句 | v1 | 计划（展示层口径） |
| `correction_rate:h<0-23>` | 各小时纠偏率，Beta-Binomial 收缩到全局率 | AN-05 `correction` 信号、小时桶 | `eb`，m = 10 | A1-22「深夜纠偏率」 | v1 | 计划 |
| `agent_switches_after{quota_hit, abandoned, failure_streak}` | 同项目内切换 Agent 前 30 分钟出现过触发信号的切换次数（供 RC-14 与 `quota_interrupt`） | `work_block.agent_sequence`、AN-05 信号 | — | — | v1 | 计划（§3.1） |

节律只描述记录时间，不是连续工作；`activity()` 已标 `time_basis = "reported log timestamps; not continuous work"`，界面沿用。

### 2.2 效率与产出（AN-01 / AN-02）

| 指标 | 定义 / 公式 | 字段 | 分母 · 置信度 | Demo | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- | --- |
| `turns_per_session`、`human_messages_per_session` | 中位数与 p90；轮次只数 `turn_uid` 非空，不用消息数除以二推算 | `turn`、`v_human_message` | 主会话 | A3-11；Lite·会话「轮数」 | MVP | `turn_count / user_message_count` |
| `human_chars_per_turn` | `attrs.original_chars` 均值 / 中位数；截断时下界（与契约 §3.2、`ai.md` 同名） | `event.text`、`attrs.original_chars`、`text_truncated` | 可测消息 | A1-14 | MVP | `text_lengths()`（`avg_user_message_chars`） |
| `autonomy_steps_median / p90` | 每个真人触发的轮次内 `tool_call` 数 + 非进度 `message.assistant` 数（`attrs.phase ∉ commentary/analysis`）；替代 Demo 的「工具 × 1.54 ÷ 消息」 | `turn.trigger = human`、`tool_call.turn_uid`、`message.assistant.attrs.phase` | 轮次 n；`basis = measured` | A1-15、A3-11 | MVP | 雏形 `profiling/portrait.interaction.recorded_steps_per_request`；PR#32 `journey` 按轮次 |
| `human_response_s_median` | 助手最终回复到下一条真人消息的间隔中位数 | `message.assistant(phase = final).ts`、下一条 `v_human_message.ts` | 配对数；`basis = estimated` | A3-12 | v1 | 计划 |
| `agent_turn_s_median` | 真人消息到该轮最终回复的时长 | `turn.started_at / ended_at` | `basis` 随 `boundary_source` | A3-12、HUD-07 | v1 | 计划 |
| `parallel_overlaps` | 同一时刻 ≥ 2 个主会话有可靠活动区间的分钟数 | 会话级活动区间 | `basis = estimated` | A4-15、A2 M 轴 | MVP（供 M 轴） | `respond.parallel_intervals()`；会话级并集计划 |
| `subagent_spawn_count[:<name>]`、`subagent_token_share` | 子代理派发次数（按明确 spawn 证据的 `child_session_uid` 去重）；子会话 token ÷ 根树 token | `tool_call.kind = subagent`、`session.spawn_call_uid`、`model_call.coverage` | 根会话 | A4-08、A4-15；Lite·工具 | MVP | `subagent_spawn_count` 已有；份额随 `model_call` |
| `files_touched_per_session` | `tool_call.files` 去重后的文件数 | `tool_call.files` | — | A3-11 | v1 | 计划 |
| `commits_per_active_hour`、`links_per_session` | `link.kind ∈ commit/pr` 数 ÷ 活跃小时 | `link(kind, ref, ts)` | 无 `link` 为 null | A5-11 | v1 | 计划（`link` 表 connector 尚未填充） |
| `delivery_count` | `message.assistant(phase = final)` 数 | `attrs.phase` | — | A3-12 | MVP | `outcome_subjective.collect_deliveries()` |

效率指标不合成总分、不换算成「节省分钟」；推荐侧的「每周节省」只取 `problem.weekly_count` 这类可机械计数的量（契约 §0.5）。

### 2.3 质量与结果（AN-19；AN-02 行字段 `outcome / verify_*`）

结果判定只用可观察证据，按优先级取最强的一层；取不到就是 `unknown`，界面显示「未知」而不是失败。AN-19 是一个约 60 行的合成器：显式反馈 = `outcome_subjective`，验证 = `outcome`，facet = AI-03，结构规则只补 `interrupted` 与「最后一条是纠偏」。

| 产物 | 规则 | 字段 | 分母 · 置信度 | Demo | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- | --- |
| `outcome ∈ {completed, partially_completed, abandoned, unknown}` + `outcome_basis ∈ {explicit_feedback, verify_pass, facet, structural, unknown}` | 优先级 `explicit_feedback > verify_pass > facet（该字段 κ ≥ 0.6，EV-04.1）> structural`。① **显式反馈**：最后一次交付之后 `classify_feedback()` 给出 `user_acceptance = accepted` 或 `user_confirmed_completion = true` → `completed`；`rejected` 或 `rework_feedback = true` → `partially_completed`；`mixed` 不判，交给下一层。② **验证通过**：`outcome.extract_validation_runs()` 中最后一次 `file.edit / file.change` 之后存在 `validation_result = passed` 且其后无 `failed`、无纠偏 → `completed`。③ **facet**：按下表映射。④ **结构**：最后一个轮次 `status = interrupted` 或最后一条真人消息是纠偏 / 挫败且其后无交付 → `abandoned`；有交付但最后一次验证 `failed` 或其后有纠偏 → `partially_completed`。其余 `unknown` | `outcome_subjective.feedback`、`outcome.validation_runs`、`session_facet.outcome`、`turn.status`、AN-05 信号 | 会话；`completed_rate / abandoned_rate` 分母 = `outcome ≠ unknown` 的主会话，另报 `unknown_n`；`wilson` | A3-08、A3-11、A5-05、A1-09；Lite·会话状态、Lite·项目完成度 | MVP（①②④）；随 AI-03（③） | 计划（合成器）；①②已在 `outcome_subjective / outcome` |
| `verify_requested` | `profiling/feedback.RULES.verification` 或 `instruction.verification_requirements.requested` 命中 | 真人文本 | 任务 | A2 V 轴、A2-13 | MVP | `feedback.signals()`、`instruction/extraction` |
| `verify_ran`、`verify_pass`、`verify_candidate` | 来自 `extract_validation_runs()` 的已执行验证（`executed = true`：有来源元数据或完整直接检查命令加命令级返回；仅 `command_head`、不完整命令、复合命令、列表模式、被拒绝执行都不算）；`verify_pass` = 最后一次为 `passed`；只命中 `command_head` 的记 `verify_candidate`（`basis = proxy`，= main `validation_command_candidates`） | `tool_call.command_head / status / status_scope`、`attrs.validation` | 有 shell 调用的会话 | A3-11、A5-05；Lite·会话 | MVP | `outcome/validation.py`（PR #19 / #24） |
| `edit_without_verify` | 最后一次 `file.edit` 之后到会话结束没有任何已执行验证（`validation_runs` 为空） | `tool_call.kind = file.edit`、`validation_runs`、`seq` | 有编辑的会话；`wilson` | A3-18、A7 验证阶梯 | MVP | 计划（= AN-05 `missing_verification` 的会话级汇总） |
| `rework_rate` | 同任务内 `rework_feedback` 或交付后再编辑同一文件集合的任务占比 | `outcome_subjective.rework_feedback`、`tool_call.files` | 任务；`wilson` | A1-10、A5-09 | MVP（反馈部分） | `outcome_subjective.summarize_subjective_outcomes()`（`rework_feedback_count`） |
| `first_turn_success_rate` | 单轮次会话且 `outcome = completed` 的占比 | 上述 | `outcome ≠ unknown`；`wilson` | A5-09 | v1 | 计划 |
| `user_acceptance / rejection counts` | 交付后显式接受 / 拒绝 / 混合 / 完成确认 / 返工请求的消息数（不推断沉默） | 真人短句 + 交付关联 | 关联反馈消息 | A6-10；Lite·会话 | MVP | `summarize_subjective_outcomes()`（`accepted_feedback_count` 等） |
| `acceptance_results`、`task_success` | 已确认验收项的逐项状态；只有完整验收集合才给 `task_success` | `attrs.acceptance`、`validation_runs` | 验收项 | Lite·会话结果卡 | MVP（已实现，数据待 Instruction 产出确认集合） | `outcome/acceptance.py` |

**facet → AN-19 映射**（AI-03 `session_facet.outcome` 五态只经此表进入；EV-02 标注 AN-19 四态，facet 五类作附加字段）：

| facet | AN-19 | 条件 |
| --- | --- | --- |
| `fully_achieved`、`mostly_achieved` | `completed` | — |
| `partially_achieved` | `partially_completed` | — |
| `not_achieved` | `partially_completed` / `abandoned` / `unknown` | 有交付 → `partially_completed`；无交付且有结构证据（`interrupted` 或最后一条是纠偏）→ `abandoned`；否则 `unknown` |
| `unclear` | 不覆盖 | 交给结构层 |

「Agent 声称完成」「文件已写入」「commit 存在」「包装层成功」都不进 `completed` 的证据（`outcome/README.md` 与 `profiling/trajectory.audit_revisions` 的边界沿用）。Demo 的 `out ∈ {ok, part, fail}` 与「项目完成度 = (完成 + 0.5 × 部分) / 会话数」改为 `outcome` 四态分布 + `unknown_n`；完成度合成分只在 `unknown` 占比 < 50% 时显示（契约 V-A10）。

### 2.4 摩擦与瓶颈（AN-05 检测器闭集 → AN-06 问题升级）

设计原则：每个检测器是一个纯函数 `detect(session_events, tool_calls, ctx) → signal[]`，输入是一个根会话树的 L2 / L3 行，输出 `signal` 行（契约 §3.2b）；每会话每类型只参与一次会话级计数（`signal.value` 保留次数）；`unit ∈ message/turn/task/session`；`friction_type` 只是信号的展示属性（A6-08 分布、AI-04.1 细分），**不作聚合键**；`problem_type` 是推荐匹配键（见下表与映射表）；`rules_version` 随词表与阈值变化。MVP 的 `signal` 不带 `severity`，也不做上游去重（随 `runaway_loop` 进 v1 时再加）。移植自 agentsview 的阈值按字符重标（中文 15–200 字节 ≈ 5–66 字），词表双语。AN-05 拆为 **AN-05.1 语义检测**（`correction / frustration / requirement / subjective_feedback / explanation_revision / long_response / unexplained_terms`）与 **AN-05.2 非语义检测**（其余）。

| `signal.kind` | 规则（MVP 阈值，契约 V3） | 字段 | `friction_type`（展示） | `problem_type` | 分母 | Demo | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `correction` | 两条助手回复之间 5–200 字的真人消息命中纠偏词表（`不对 / 不是我说的 / 还是不行 / 我说的是 / 你理解错了 / 重新 / 改成 / wrong / not what I meant / try again / instead`）；引用、围栏、问答回执先剥离；`dimension` 由 `feedback.signals` 给出 | `v_human_message.text`、`attrs.original_chars` | `misunderstood_request`（AI-04.1 可细分为 `wrong_approach / excessive_changes / buggy_output`） | 有 `dimension` → `repeated_instruction`；无 → `misunderstood_request` | 真人消息 → 会话；`wilson`；`basis = proxy` | A1-16、A6-07、A6-08；Lite·概览纠偏率 | MVP | `interaction/rules.correction_terms()`（词表 proxy）；`interaction.classify_message_intents`（消费确认标注 `attrs.interaction`） |
| `requirement` | 8 维度明确要求（`clarity … scope`）+ `convention`；不是摩擦，与纠偏同表存储供画像与问题关联；`target = communication` 的归 `communication_gap` | `feedback.signals()`、`instruction.extract_instruction_constraints()` | — | 同 `dimension` 跨会话重复 → `repeated_instruction`；`target = communication` → `communication_gap` | 会话 / 任务 | A2-05、A2-13 | MVP | `profiling/feedback.RULES`；`instruction/`（8 字段） |
| `explanation_revision` | 同任务交付后要求调整说明（`category ∈ correction/refinement ∧ target = communication`），且不是回答澄清问题 | `feedback.signals()`、`task_contexts()` | `misunderstood_request` | `communication_gap` | 任务 | A6-08 | MVP | `profiling/bottlenecks.diagnose()`（`observed_revision`） |
| `long_response` / `unexplained_terms` | 超出明确篇幅上限（无上限按摘要 450 / 其他 2500 字核对）；要求易懂时前 500 字 ≥ 4 个未解释术语 | `attrs.writing_measurements`、`output_contracts` | `process_overhead` | `communication_gap` | 任务 | A6-08 | MVP | `profiling/bottlenecks.diagnose()`（`rule_candidate`） |
| `frustration` | 命中挫败词表（`算了 / 别弄了 / 怎么又 / 又错了 / 第几次 / 烦 / seriously / again?! / ugh`）或连续 ≥ 2 条 ≤ 40 字纠偏 | 真人文本 | `misunderstood_request` | `misunderstood_request` | 会话；`basis = proxy` | A6-06、A6-11 | v1 | 计划（词表 EV-02 标定） |
| `subjective_feedback` | 交付后真人短句 `accepted / rejected / mixed` 与 `rework_feedback`（§2.3） | `outcome_subjective.feedback` | `other`（`rejected / rework` 为 `buggy_output` 候选） | 不升级（进 AN-19） | 关联反馈 | A6-10 | MVP | `outcome_subjective/extraction.classify_feedback()` |
| `retry_loop` | **适配器**：把 `respond.analyze_execution_sequence().retry_links` 中同轮次、同 `status_scope`、`same_arguments = true` 的确认重试串（≥ 2 条链接，即 ≥ 3 次失败）转成一条 `signal`；预期失败测试（`_expected_failure`）排除；`key` 子键 = `command_head` | `retry_links`、`tool_call.argument_digest / status_scope / turn_uid` | `tool_env_failure` | `tool_env_failure` | 有工具调用的会话；`wilson` | A3-17、A4-12、POP-09；Lite·工具失败 | MVP | `respond/sequence.py`（PR #19）；main `confirmed_same_argument_failed_retries` 与 `profiling/bottlenecks.repeated_tool_failure` 只作旧链路兼容输出，不再产生 signal |
| `runaway_loop` | 12 次调用窗口内失败 ≥ 6，或失败 ≥ 3 且同 `command_head` ≥ 10 | `tool_call.status`、`command_head`、`seq` | `tool_env_failure` | `tool_env_failure` | 会话 | A3-17、POP-09 | v1 | 计划 |
| `edit_churn` | 同一文件在 10 个 `seq` 内被 `file.edit` ≥ 3 次 | `tool_call.kind = file.edit`、`files`、`seq` | `excessive_changes` | `misunderstood_request` | 有编辑的会话 | A3-12 | v1 | 计划 |
| `mid_task_compaction` | `context.compaction` 前 10 次与后 5 次工具调用共享 ≥ 2 种 `name_raw` | `event.kind = context.compaction`、`tool_call.seq` | `context_loss` | `context_loss` | 有压缩事件的会话；legacy null | A3-12、POP-10 | v1 | `compaction_count` 已有 |
| `context_pressure` | 上下文观测 `used_tokens / context_window_tokens > 0.9` | 补充约定的上下文观测（契约 C9） | `context_loss` | `context_loss` | 有观测的会话 | HUD-08、POP-10 | v2 | 计划（契约 V-A9） |
| `interruption` | `turn.status = interrupted`（legacy `turn.interrupted`）；谁打断不推断 | `turn.status` | `process_overhead` | 不升级（进 AN-19 结构层） | 轮次 | A3-17、A4-15 | MVP | `interruption_count` |
| `duplicate_prompt` | 同会话或 7 天内不同会话出现 `message_digest` 相同或 Jaccard(字符 3-gram) ≥ 0.9 的真人开场消息 | `attrs.message_digest`、真人文本 | `process_overhead` | 单句 → `repeated_instruction`；多步（含 ≥ 2 个动作分句）→ `repeated_workflow` | 会话 | A5-11、A7 skill 候选 | v1 | 计划（契约 V-A11） |
| `workflow_pattern` | AN-04 轮次变体 `support_sessions ≥ 3` 时产一条会话级信号 | `workflow_pattern` | `process_overhead` | `repeated_workflow` | 会话 | A5-11 | v1 | 计划 |
| `missing_verification` | 最后一次 `file.edit` 之后 `validation_runs` 为空即出现最终交付或会话结束 | `tool_call.kind / seq`、`outcome.validation_runs`、`message.assistant(phase = final)` | `buggy_output` | `missing_verification` | 有编辑的会话；`wilson` | A3-18、A7 验证阶梯 | MVP | 计划（消费 `outcome/validation.py`） |
| `would_prompt` | `kind = shell ∧ is_wrapper = 0 ∧ command_head ∈ command.readonly` 且会话权限模式为 default、未被已安装 allow 规则覆盖（契约 §4.2） | `tool_call.command_head`、`session.meta.attrs.permission_mode`（契约 V12）、`inventory_item`（PR #31） | `permission_friction` | `permission_friction` | 有 shell 调用的会话 | A4-07、A4-13 | MVP | 计划；`/insights bash_would_prompt_count` 作对照（DT-18） |
| `permission_denied` | `permission.decision.attrs.decision = deny` 或 `tool_call.approval = declined`；`approval_wait_ms` 只在有端点时统计 | `event.kind ∈ permission.*`、`tool_call.approval` | `permission_friction` | `permission_friction` | 有审批事件的会话 | A4-07、A4-13 | MVP | `permission_request_count` 已有 |
| `risky_command` | 任一成立：shell `command_head` 或参数命中 DT-13 破坏性命令族（`rm -rf`、`git push --force`、`git reset --hard`、`DROP`…）；`tool_call.files` 落在 `project.paths` 之外的写操作；会话 `permission_mode ∈ bypass/auto`（契约 V12） | `tool_call.command_head / files`、`project.paths`、`session.meta.attrs.permission_mode` | `other` | `unsafe_operation`（`min_sessions = 1`） | 有 shell / 编辑的会话 | A7 scope-guard hook（`ai.md` AI-06）、EV §7 破坏性拦截卡 | MVP（词表命中）；v1（根目录外写入、权限模式） | 计划 |
| `quota_hit` | `error.attrs.error_class ∈ rate_limit/quota` 或 `rate_limits` 快照剩余为 0 后出现中断 | `event.kind = error`、`attrs.rate_limits` | `quota_interrupt` | `quota_interrupt` | 会话 | A6-08 | v1 | 计划（DT-17） |
| `parallel_conflict` | 两个主会话活动区间重叠且 `tool_call.files` 交集非空，随后其一出现失败或 `branch(action = rollback)` | `respond.parallel_intervals`、`files`、`branch` | `parallel_conflict` | `parallel_conflict` | 重叠会话对 | A6-08 | v1 | 区间已有；冲突判定计划 |

闭集 20 类（AN-07 的 `sentiment` 另算）。契约 §3.2b 计划列表中的 `repeated_tool_failure` 并入 `retry_loop`；`error` 只作 `by_error_class` 指标，不作 signal；`workaround` 不做（§11）。

**`signal.kind → problem.type / key` 映射（唯一来源；`recommendation.md` §3.1、`ai.md` §9.2 与契约 §3.2b 引用此表）**。`key` 语法 `<signal.kind>:<子键>`，推荐侧按全称比对（`remedy_rule.problem.key` 写全称，如 `would_prompt:readonly_shell`）：

| `problem.type` | 来源 `signal.kind` | `key` | `min_sessions` | 默认解法（RC §3.1） |
| --- | --- | --- | --- | --- |
| `repeated_instruction` | 同 `dimension` 的 `correction` 或 `requirement` 跨会话重复；单句 `duplicate_prompt` | `correction:<dimension>[:<entity>]` / `requirement:<dimension>` / `duplicate_prompt:<message_digest 前 8 位>` | 2（与 RC-06 #1 对齐） | `rule` > `hook` > `prompt` |
| `communication_gap` | `explanation_revision`、`long_response`、`unexplained_terms`、`requirement(target = communication)` | `explanation_revision:<dimension>` / `long_response:<scene>` / `unexplained_terms:<scene>` / `requirement:<dimension>` | 3 | `skill`（humanizer-zh）> `rule` > output style |
| `repeated_workflow` | 多步 `duplicate_prompt`、`workflow_pattern` | `duplicate_prompt:<digest>` / `workflow_pattern:<variant_hash>` | 3 | `skill` > `plugin` > `subagent` |
| `missing_verification` | `missing_verification` | `missing_verification:<file_ext 众数 ∣ project>` | 3 | `rule` > `hook` > `subagent`（验证阶梯） |
| `tool_env_failure` | `retry_loop`、`runaway_loop` | `retry_loop:<command_head>` / `runaway_loop:<command_head>`（`error_class` 只进 `evidence.numbers`） | 3 | `hook`（熔断）> `skill` > `rule` |
| `permission_friction` | `would_prompt`、`permission_denied` | `would_prompt:readonly_shell` / `permission_denied:<命令族>` | 3 | `permission_rule` > `builtin` > `hook` |
| `context_loss` | `mid_task_compaction`、`context_pressure` | `mid_task_compaction:project` / `context_pressure:project` | 3 | `rule` > `skill` > `workflow` |
| `parallel_conflict` | `parallel_conflict` | `parallel_conflict:<project_id>` | 2 | `workflow`（worktree） |
| `quota_interrupt` | `quota_hit` | `quota_hit:<source.agent>` | 3 | `model` > `workflow` |
| `process_overhead` | 长 `search → read+` 链（AN-04 三步链 `support ≥ 3`）、`subagent_token_share` 过高 | `three_step_chain:<chain_hash>` | 3 | `subagent` > `plugin` > `rule` |
| `unsafe_operation` | `risky_command` | `risky_command:<命令族>` | 1 | `hook`（scope-guard）> `permission_rule`（deny） |
| `misunderstood_request` | 无 `dimension` 的 `correction`、`frustration`、`edit_churn`；AI-04.1 细分后分别记 `wrong_approach / excessive_changes / buggy_output` 子类 | `correction:none` / `frustration:session` | 3 | `prompt`（完成契约）> `workflow`；默认不装东西 |

`installed_unused`、`resident_cost`、`quality_drop`（AN-15，v1）不经 AN-06：前两者是 AN-11 的事实，由 RC-07 直接生成候选（`match_basis = inventory_fact`）；`quality_drop` 由 AN-15 单独写入。

**问题升级（AN-06）**：按 `(problem_type, key, scope ∈ all/project/source, scope_id)` 聚合窗口内信号；`problem_id = stable_id(type, key, scope, scope_id)`，跨重算稳定。升级条件：`sessions ≥ min_sessions（上表）∧ wilson_lo(sessions, denom) ≥ 0.05`（契约 V1），`denom` = 该类型「有机会发生」的会话数（`retry_loop` 用有工具调用的会话，`would_prompt` 用有 shell 调用的会话，`missing_verification` 用有编辑的会话，其余用有确认真人消息的主会话）。`weekly_count` = 近 4 周信号次数均值；`weekly_cost_minutes` 只在有可靠区间时估算并标 `estimated`，否则不填。`status` 不存在 `problem` 表里：RC-10 / IN-04 写 `label(target_kind = problem, label ∈ resolved/dismissed)`，AN-06 重算时只读 `label`、不覆盖；RC-03 闸门 14 的 `active` = 无此类 `label` 且 `last_seen` 在窗口内。

### 2.5 工具与调用链（AN-01 / AN-04 / AN-11）

| 指标 | 定义 / 公式 | 字段 | 分母 · 置信度 | Demo | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- | --- |
| `by_tool[]`（`call_count / known_success / known_failure / rejected / interrupted / running / unknown_status / unpaired`） | 一次逻辑调用一行；状态只认协议；包装层成功不抹掉内层未知 | `tool_call.name_raw / kind / status / status_scope / pairing_quality` | — | A4-05、A4-09、A1-24；Lite·工具明细 | MVP | `respond/calls.tool_summary()`、`result_status()` |
| `failure_rate` | `known_failure ÷ (known_success + known_failure)`；未知另列（实测 55.88% 未知） | 同上 | 已知状态调用；`wilson` | A4-06；Lite·工具成功率 | MVP | 裸值已有；区间计划 |
| `by_kind`、`by_command_head`、`by_mcp_server`、`by_skill` | 按 L3 `kind`、命令头、MCP 服务、技能聚合 | `tool_call.kind / command_head / mcp_server / skill`、`session_feature` | — | A4-09、A4-14、A1-24 | MVP | `name_raw` 拆分已有；按 `kind / command_head` 聚合计划 |
| `by_file_language[]` | 由 `session_feature(feature = file_extension)` 或 `tool_call.files` 扩展名按 DT-13 词表归到语言，按文件类工具调用计数，`basis = measured`；main `overview.top_languages`（`basis = file_extension_in_human_text`，「提及的语言」）作降级并分开展示；RC-09 的 `session_feature(file_type)` 来自同一聚合 | `session_feature`、`tool_call.files` | 文件类调用 | Lite·概览「工具 / 程序语言排行」、A5-07 标签 | MVP | PR#32「文件语言使用」（需文件证据）；`top_languages` 已有 |
| `by_error_class` | 失败按 `error_class` 分组；命名细分交 AI-04.2 `cluster.failure_names`（v1） | `tool_call.error_class / exit_code` | 失败调用 | A4-12；Lite·工具失败原因 | MVP | PR#27 `failure_reasons`；legacy 无 `error_class` |
| `median / p25 / p75 / p90_duration_ms`、`duration_sum_ms`、`reliable_interval_union_ms` | 线性插值分位；`duration_source / quality` 随行；并集只用可靠端点 | `tool_call.duration_ms / duration_source / duration_quality` | 有时长调用；`basis` 随 `duration_quality` | A4-09 | MVP | `cost_time/durations` |
| `transitions[]`（DFG） | 会话内相邻状态对计数与 `P(next ∣ current)`；MVP 以 `(name_raw, kind)` 为节点（PR #27：> 20 类时保留前 19 类 + 其他），缺序或重复 `seq` 的会话整体不参与 | `event.seq / kind`、`tool_call.kind` | 同一起点的出边；`n` 随边展示 | A4-11；Lite·工具转移矩阵 | MVP | `respond/sequence.workflow().transitions`（事件状态级）；PR#27 / PR#32 调用级矩阵 |
| `three_step_chains[]` | 频次前 10 的三步链（按 `kind` 族），带支持会话数；`process_overhead` 的输入 | 同上 | 支持会话 ≥ 3 才展示 | A4-11 结论句、A5-11 | MVP | PR#32「常见执行流程」（三步工具类型组合，按会话去重） |
| `repeated_transition_rate`、`max_repeated_transition_run` | 描述结构，不解释为低效（实测 99.09%） | 同上 | 总边数 | — | MVP | `workflow()` |
| `workflow_pattern[]`（轮次级变体） | 轮次内活动序列游程折叠后哈希，统计 `support_turns / sessions / share / correction_rate / failure_rate` | `tool_call.kind / command_head`、`turn_uid` | 变体 `support_sessions ≥ 3` | A5-11 | v1 | 计划 |
| `wait_side`、`declare_check[]` | DFG 边中位间隔归「等 Agent / 等人」；约束满足 / 违反计数（`edit ⇒ eventually verify` 等） | `event.ts`、`tool_call` 序列 | — | A3-12、A5-11 | v1 | 计划 |
| `subagent_relations`、`parallel_degree` | 子代理派发批次、同时运行数、中止数（只认 `spawn_call_uid` / 明确 spawn-join） | `session.spawn_call_uid / parent_uid`、`subagent.spawn / result` | 批次 | A4-08、A4-15 | MVP（关系）；v1（并行度） | `respond/relations.build_execution_relations()` |
| `would_prompt_count:<族>`、`denied_count`、`approval_count` | §2.4 审批类信号计数；等待时长只在有 `approval_wait_ms` 时给中位数 | 同 §2.4 | 有 shell / 审批的会话 | A4-07、A4-13 | MVP | 计划 |
| `installed_unused[]` | 逐项 `{item, type, last_used_at, days_since_last_use, sessions_since_last_use}`（`inventory_item` × `tool_call.mcp_server / skill`、`hook.run`）；**AN 侧不设门槛**，RC-07 自定「14 天且 10 会话」；只能说「本次记录未观察到使用」 | `inventory_item(type, name, enabled, seen_at)`（PR #31） | 已装项 | A4-14、A5-12、A7 减法 | MVP（随 PR #31 合入） | 计划（AN-11） |

### 2.6 上下文与 token 经济（AN-01 / AN-02 / AN-11）

| 指标 | 定义 / 公式 | 字段 | 分母 · 置信度 | Demo | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_count`、`token_buckets{input, cache_read, cache_write, output, reasoning}`、`total_tokens` | 只收 `usage_scope = call ∧ measurement = delta` 且边界可靠的 `model_call`；`total = input + cache_read + cache_write + output`（reasoning 已含在 output）；任一桶缺失总量为 null，另给 `known_subtotal` | `model_call.*_tokens`、`coverage` | 合规请求；`basis = measured` | A1-18、A3-11、FE-22；Lite·概览 / 会话 Tokens | MVP | `cost_time/tokens.usage()` |
| `cumulative_snapshots` | 同 `snapshot_key` 同 `counter_cycle` 取最后可信快照；不与逐次值相加 | `usage_snapshot`、`v_latest_usage_snapshot` | — | A1-18（降级口径） | MVP | 已有；canonical 适配透传 `usage_snapshots`（AN-16） |
| `cost_usd`、`cost_sources`、`price_table_versions` | 有来源的完整费用求和；价目表折算带版本；订阅不等于账单 | `model_call.cost_usd / cost_source`、`model_info.price`（DT-14） | 合规请求 | FE-22、A5-05 | MVP（原生）；v1（价目表） | 原生已有 |
| `cache_hit_rate`、`reasoning_share` | `cache_read ÷ (input + cache_read + cache_write)`；`reasoning ÷ output` | 同上 | 输入总量 > 0 | FE-22 | v1 | 计划（公式在 `docs/contracts/analysis-inputs.md` §3.5） |
| `resident_tokens_median` | 每会话第一条 `model_call` 的 `input + cache_read + cache_write`（常驻上下文：规则、技能清单、MCP 描述） | 会话内 `model_call` 首条 | 有逐次用量的会话 | A4-14（「常驻 ≈ 2.1k tokens」）、A7 常驻 ≥ 2000 token 标黄 | MVP | 计划（AN-11） |
| `cache_rebill_tokens` | 相邻两次请求前一次 `cache_read > 0`、本次 `cache_read ≈ 0 ∧ cache_write ≥ 前次 × 0.8`，且间隔 > TTL 或 `model_id` 变化 → 计重复计费 | `model_call.ts / model_id / cache_*` | 相邻请求对；`basis = estimated` | A7「长停顿前先压缩」 | v1 | 计划（契约 V-A12） |
| `rework_tax_tokens`、`retry_cost_ms` | 第一次 `correction` 之后的 token 总量；确认重试链的可靠执行耗时 | `model_call.ts` × `signal(correction).ts`；`retry_links` | 有纠偏 / 重试的会话 | A6-11、A7 | MVP（重试耗时）；v1（返工税） | PR#32「重试耗时」 |
| `compaction_count`、`compactions_mid_task` | `context.compaction` 事件数；§2.4 `mid_task_compaction` | `event.kind` | legacy null | A3-12、POP-10 | MVP / v1 | `compaction_count` 已有 |
| `context_peak_ratio`、`context_used_series` | 上下文观测 `used ÷ window` 的峰值与序列 | 补充约定的上下文观测（契约 C9） | 有观测的会话 | A3-11、HUD-08 | v2 | 计划（契约 V-A9） |
| `median_latency_ms`、`median_ttft_ms` | 请求级延迟中位数 | `model_call.latency_ms / ttft_ms` | 有值请求 | A3-12、FE-22 | MVP | 已有 |
| `tokens_per_session_by_model_effort` | 每会话 token 中位数按 `(model_id, effort_rank)` 分组 | `model_call.model_id / effort_rank` | 分组 n | A5-05、RC-08 输入 | MVP | PR#32 `model_effort` 段 |

### 2.7 用量与额度（DT-08 / DT-17 → AN-01 `quota_*`，v1）

| 指标 | 定义 / 公式 | 字段 | 分母 · 置信度 | Demo | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- | --- |
| `quota_window[]` | 从 `rate_limits / quotaLimits` 快照重建每个 `(source, window_minutes)` 的用量曲线与重置时刻 | `attrs.rate_limits`（PR #11）；Claude `cachedUsageUtilization`（待验证 AV7） | 快照数 | FE-22 | v1 | 计划（DT-17） |
| `quota_hit_count`、`quota_hit_sessions` | §2.4 `quota_hit` 信号 | 同上 | 会话 | A6-08 | v1 | 计划 |
| `burn_rate_expected_vs_actual` | 窗口内线性期望用量 vs 实际 | `quota_window` | `basis = estimated` | FE-22 | v1 | 计划 |
| `cost_by_project / by_model_effort / by_day` | `cost_usd` 分组序列；无价目表为 null | `model_call.cost_usd / project_id / model_id` | 合规请求 | FE-22、A5-05 | v1 | 计划（DT-14） |

额度与成本是分析的分母而不是产出；界面金额一律标「API 等价估算，非账单」。

### 2.8 协作风格与人格（AN-08，实验性）

两层产物：**明确要求覆盖**（`profile.observations[]`，已实现、可靠）与**四轴代码**（`profile.axes / code`，实验性）。推荐只用前者与连续分数，不用四字母（契约 RC-04 / 内部资料 X3）。PR #27 `presentation/profile.py`（`collaboration-profile-v1`：按任务等权归并、D 轴门槛 ≥ 5 任务 ∧ ≥ 2 会话、分数 < 0.4 / > 0.6 才给方向）是四轴的实现起点；本文在它之上统一单位与区间规则。

| 产物 | 定义 / 公式 | 字段 | 分母 · 置信度 | Demo | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- | --- |
| `observations[]`（8 维度 + `convention`） | 每维度 `sessions / tasks / messages / categories / examples`，`k / n` 带 Wilson；`scope ∈ observed_request / cross_project_candidate` | `feedback.signals()`、`instruction` 8 字段 | 有真人消息的主会话；`wilson` | A2-13、A2-15、A5-08；Lite·画像「计算信号」 | MVP | `profiling/portrait.profile()` + `profiling/analysis._preferences()` |
| `preferences.effective[]` | 显式偏好（语言 / 详略 / 格式 / 工具 / 协作方式）按 `scope` 与时点解析，含 `supersedes / revokes / reaffirms`；窗口前仍有效的偏好作背景不计入本月 | `preference/features.py` | 不同 `preference_id` | A2-13、A6-10 | MVP | `analytics/preference/`（`/v1/analytics/preferences`） |
| `opening_structured_rate` | 任务首条真人消息满足「`bullet_count + numbered_list_count ≥ 2` 或 `constraint_marker_count ≥ 2` 或 `file_reference_count ≥ 1`」的任务占比 | `prompt_structure.*` | 任务；`wilson`；`basis = proxy` | A2-13 P 轴证据 | MVP | `instruction/structure()` 已有；汇总计划 |
| `planning_rate`、`verify_requested_rate` | 任务含 `planning` 维度要求或 `instruction.execution_order = plan_first` 或首个动作为 `plan.update` 的占比；§2.3 `verify_requested` 的任务占比 | `feedback.RULES`、`instruction.execution_order / verification_requirements`、`event.kind = plan.update` | 任务；`wilson` | A2-13、Lite·画像 | MVP | 要求部分已有；汇总 = PR#27 `signal_rate` |
| `interaction_pattern_mix` | `directive / feedback_loop / task_iteration / validation / learning` 的会话占比；MVP 用规则（单轮 = directive；≥ 2 次纠偏 = feedback_loop；同任务 ≥ 3 轮 = task_iteration；验证占比高 = validation；`explain / learn` 类任务 = learning） | AN-02 行 + `task.task_type` | 会话 | A2-15 | v1 | 计划 |
| 四轴 `axes{D, P, M, V}` | 每轴 = 满足条件的单位占比 `{value, lo, hi, n_units, unit, letter}`：**D/S** = `autonomy_steps ≥ 5` 的真人触发轮次占比（unit = turn），`instruction.requested_autonomy = explicit` 作加分证据；**P/I** = `opening_structured ∨ planning` 的任务占比（unit = task）；**M/F** = 当天存在交错工作段（`work_block.interleaved = 1`）或 ≥ 2 个主会话重叠的活跃天占比（unit = day）；**V/T** = `verify_requested` 的任务占比（unit = task；Agent 自己跑验证单独显示为 `verify_ran_rate`，不进 V 轴）。字母：**按单位计数的 Wilson 95% 区间整体在 50% 一侧才给字母**，否则 `?`；任一轴 `?` 时 `code` 带 `?`、`experimental = 1`。门槛：每轴 `n_units ≥ 30 ∧ 活跃天 ≥ 10`（契约 V2），否则「数据不足」 | 上述指标 + `work_block` | `wilson`（按单位） | A1-21、A2-06…A2-08、A2-13、WG-02、POP-08；Lite·画像人格码 | MVP（Wilson 版） | PR#27 `presentation/profile.py`（任务等权、D 轴门槛）；Demo `15-derive.js::persona` 与 Lite `persona()` 为示例算法，全部替换 |
| 逐月画像 | 每自然月一份 `axes / code`，按月窗口现算（同一 `rules_version`），最近 12 个月；不建 `profile_history` 表 | `profile` 查询 | 月 `n_units ≥ 30` | A2-10；Lite·画像「6–9 月变化」 | MVP（现算）；v1（物化） | PR#27 `monthly_trend`、PR#32 `profile_history` |
| `type_name`、特质标签 | 16 型名称与标签只是展示映射（Demo `TYPES` 表）；带 `?` 的代码显示「尚未定型」；「中英混用」标签来自 §2.9 `human_language_mix` | — | — | A2-07、A2-08 | MVP | Demo 已有表；后端只回传 `code` |

信号权重：MVP 四轴内各信号等权，不拟合权重；v1 在 EV-02 标注集上检验各信号与「不像我」反馈（`label.not_me`）的一致性后再调。小样本规则：`n_units < 30` 不出字母；30–100 置信度「中」；≥ 100「高」（以区间宽度 ≤ 20 个百分点为准，契约 V2）。按天分块 bootstrap 区间、Beta-Binomial 收缩与 `profile_history` 表全部 v1。

### 2.9 语义（AN-17 / AN-18 / AN-07；哪些需要 AI 见 `ai.md`）

| 产物 | 规则（本模块，确定性） | 字段 | 分母 · 置信度 | Demo | 阶段 | 现状 | 需要 AI 的部分 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 场景 `scene`（5 类）、读者、交付语言 | `feedback.scene_of()`、`reader_constraints()`、`language_constraints()`；同任务继承 | 真人文本 | 任务 | A2-05、A6-09 | MVP | `profiling/feedback.task_contexts()` | 无 |
| 任务领域 / 类型 `domain / task_type`（多标签，`type_source ∈ rule/facet`） | **唯一枚举 = `task-taxonomy-v1`**：`task_type ∈ research / create / modify / debug / test / explain / translate / summarize / grade / publish`（+ `other`），`domain ∈ software / mathematics / data_analysis / writing / design / education`；双语词表、禁止动作排除、`semantic_status = candidate`；主标签 = 首个动作标签，每会话只计一次；来源优先级 `facet（κ ≥ 0.6）> rule` | `task/taxonomy.py`、`task/features.py` | 有标签任务；`unknown_n` 单列 | A6-09、A5-05；Lite·情绪「语义兴趣」 | MVP | `analytics/task/`（`/v1/analytics/tasks`） | AI-03 facet `task_type` 用同一枚举校正 |
| `task_type → benchmark_task_class` 固定映射（供 EV-08 / RC-08 先验） | `debug → bugfix`、`create → feature`、`modify → refactor`、`test / grade → review`、`explain / summarize / translate → docs`、`research → research`、`publish → ops_deploy`、`domain = data_analysis → data`、其余 → `other`；准确率在 EV-02 标注集上待验证 | 同上 | — | A7「thinking medium」 | v1（随 EV-08） | 计划 | 无 |
| 任务目标与版本、产物、边界 | 首个可识别动作分句；「目标改为」才换版本；产物只认产出动词后的对象 | 同上 | 任务 | A3-08、A3-17 | MVP | `analytics/task/` | 无 |
| 主题簇 `cluster_id / embedding_x,y / top_terms / novelty` | 字符 2–4 gram TF-IDF → SVD(≤ 32) → cosine DBSCAN；≥ 4 样本才聚类；簇不命名 | 真人文本（会话粒度） | 有文本的主会话 | A6-09、A2-11；Lite·画像散点（文本相似度坐标，不是人格坐标） | MVP | `analytics/text.py`、`task/representation.py` | 簇命名 = AI-04.3 `cluster.topic_names`（v1）；MVP 显示「簇 #k · n 个会话」加前 5 个 `top_terms`（与 `ai.md` §3.4 一致） |
| `similar_sessions(session_uid, k = 5)` | 用 AN-18 的 SVD 向量做余弦近邻，同项目、同 `task_type` 优先；返回相似度与共同 `top_terms`（A3-02 对比模式选 B 的依据） | `embedding` | — | A3-02、A3-19 | v1 | 计划（纯 L0） | 无 |
| 高频反馈语 `phrases_top[]` | 交付后 ≤ 40 字的真人消息规范化（去标点、全角 / 半角、繁简）后分组；输出 `{text_redacted, sessions, messages, category ∈ 偏好/纠偏/规划/验收/其他, evidence event_uids(≤ 3)}` | 真人文本、`attrs.message_digest` | 会话（去重）；只展示 `sessions ≥ 2` | A6-10；Lite·情绪「高频反馈语」 | MVP | PR#32「高频反馈语」（附消息 ID） | AI-04.1 可把「其他」细分（v1） |
| `human_language_mix{zh, en, mixed, n}` | 确认真人消息按 CJK 字符占比判定（阈值待验证，契约 V-A13） | 真人文本 | 真人消息 | A6-01、A2-08「中英混用」 | MVP | 计划 | 无 |
| 纠偏类型 `friction_type_mix` | §2.4 信号的 `friction_type` 分布；规则直接产出 9 类（`misunderstood_request / tool_env_failure / permission_friction / context_loss / process_overhead / quota_interrupt / parallel_conflict`，加 `excessive_changes` 来自 `edit_churn`、`buggy_output` 来自 `missing_verification`）；纠偏词类信号里 `wrong_approach / excessive_changes / buggy_output` 的细分交给 AI-04.1；PR #19 `interaction.FRICTIONS`（`understanding / scope / execution / verification`）是粗类，映射见 `evaluation.md` §13.3 | `signal.friction_type` | 有信号的会话 | A6-08、A1-10；Lite·情绪「纠偏 / 摩擦类型」 | MVP | 计划 | AI-04.1 `classify.feedback` 细分（`type_source = facet`，v1） |
| 情绪 `sentiment`（实验性） | 弱标注投票：① 纠偏词表 → −1 ② 挫败词表 → −1 ③ 接受 / 感谢词表 → +1 ④ 连续重复消息 → −0.5 ⑤ 感叹 / 全大写 / 「？？」→ −0.5 ⑥ 中性结构 → 0；加权和 ÷ 命中函数数，abs(score) < 0.3 或只命中 1 个函数 → 不计；等权 | 真人文本 | 真人消息 → 日 / 周 | A6-06、A6-11、A3-12 情绪泳道 | v1（Advance 独有；Lite 页面写明「纠偏不等同于负面情绪」） | 雏形 `outcome_subjective.classify_feedback().signal ∈ positive/negative/mixed`；PR#32「情绪表达趋势」 | AI-04 消解歧义短句 |
| 情绪的前因 `mood_drivers[]` | 对 4 个二元特征（会话 > 90 分钟、`retry_loop`、首条消息无结构、`mid_task_compaction`）给情绪均值差与区间；固定文案「相关不等于因果」 | `sentiment` × AN-02 行 | 每特征两组会话 n ≥ 10 | A6-11 | v1 | PR#32「反馈关联」（每会话一票） | 无 |
| 意图 `intents`（request / clarification / correction / feedback / other） | 规则候选 = `feedback.category` 映射；确认标注来自 `label(target_kind = signal)`（契约 C8；`attrs.interaction` 只作连接器可选输入） | 真人文本 | 确认意图的消息 | A6-07 | MVP | `interaction.classify_message_intents()` | AI-04.1 产出确认标注（v1） |
| 会话一句话摘要、复盘、人格自述、概览解读 | 不在本模块；只提供 AN-02 行 + `tool_sequence` + 信号摘要作输入 | — | — | A1-07、A3-04、A2-04 | — | `narrative.explain()` 模板降级 | AI-05 |

语义分母规则：所有语义指标只用 `semantic_messages()`（`analytics/common.py`：主会话、`origin = human`、非重放、剥引用与围栏）；来源未知的 user 消息进 `unknown_counts.human_origin`，不进分母；文本截断只给下界。

### 2.10 项目习惯与规则覆盖（AN-04 / AN-11 项目视角）

| 产物 | 定义 | 字段 | 分母 · 置信度 | Demo | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- | --- |
| `projects[]` 聚合行 | 现有 `session_count / main_session_count / human_message_count / turn_count / correction_signal_count / tools / usage / cluster_distribution` + 新增 `outcome_mix`、`verify_ran_rate`、`problems_top[]`、`tags`（`by_file_language` 前 2 + `domain` 众数）、`axes`（项目内画像，门槛同 §2.8） | `project_id`、AN-02 行 | 项目内主会话；每项带 `n / lo / hi` | A5-05、A5-07、A5-08、A5-09；Lite·项目 | MVP | `projects[]`；新增列计划 |
| `project.identity_quality` | `canonical`（`key_type ∈ git_remote/git_root`）/ `path` / `legacy_path`；界面标注「按路径分组」 | `project.key_type` | — | A5-04 | MVP | 已有 |
| `workflow_patterns[]` | §2.5 轮次变体中该项目支持度最高的 3 条 | `workflow_pattern` | `support_sessions ≥ 3` | A5-11 | v1 | 计划 |
| `rule_coverage[]` | 该项目与用户层配置里观察到的 `AGENTS.md / CLAUDE.md / .codex rules / hooks / skills / MCP / 子代理` 的存在、大小、行数、最近修改、是否被 `context.inject` 注入过；区分「已配置」「日志中用过」「未扫描」 | `inventory_item`（PR #31）、`event.kind = context.inject` | — | A5-12、A8-02；Lite·项目「配置覆盖」 | MVP（随 PR #31） | 计划；无清单显示「未扫描」 |
| `rule_file_stats` | 规则文件行数（Claude Code > 200 行提示）、拼接字节（Codex > 32 KiB）、常驻 token 估算 | `inventory_item.config`、§2.6 | — | A5-12、A7 减法 | MVP（随 PR #31） | 计划（AN-11） |
| `installed_unused[]` | §2.5 同名指标按项目 | 同上 | — | A5-12、A4-14 | MVP（随 PR #31） | 计划 |
| `project_compare` | 两个项目或项目 vs 整体的同口径指标并列（`metrics` 端点传两个 `Scope`） | `metrics` | 各自 n | A5-02、A5-09 | v1 | 计划 |
| 跨项目散点 | 只画散点（x = `autonomy_steps_median`，y = `correction_signal_rate`）与各点 n；不画回归线（内部资料 X18） | `metrics` by project | 项目 `n ≥ 5` | A5-06 | MVP | Demo `regress()` 删除；后端只出点 |

### 2.11 跨 Agent / 模型 × 档位 / 任务类型对比（AN-12 分层描述）

| 产物 | 定义 | 字段 | 分母 · 置信度 | Demo | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- | --- |
| `metrics?group_by=<keys>`，`keys ⊆ {project, model_effort, source, task_type}`，允许多键（如 `group_by=model_effort,task_type`） | 任何 `metrics` 项按组给 `n / value / lo / hi`：`completed_rate`、`correction_signal_rate`、`tool_failure_rate`、`tokens_per_session`、`cost_per_completed_session`、`median_latency_ms`、`autonomy_steps_median`；`model_effort` 会话归属 = 该会话 `model_call` 众数，混用标 `mixed`；`task_type` 主标签每会话计一次；每格 `n < 5` → `insufficient`；`model_resolution = unmapped` 单列 | `model_call.model_id / effort_rank / provider`、`session.source_id`、`task.task_type` | 分组 n；比例 `wilson`（EB 收缩 v1） | A7「thinking medium」、A5-05、RC-08 / RC-14 / EV-08 输入；Lite·优化建议「模型」 | MVP | PR#32 `model_effort` 段；`group_by` 端点计划 |
| 混杂提示 | 固定文案：强模型常被分配难任务；任务类型分布按组并列展示 | `task.task_type` | — | 卡片脚注 | MVP | 计划 |
| `benchmark_result` 对照 | 公开成绩只作 RC-08 / EV-08 的先验，不进本模块指标；任务类映射见 §2.9 | DT-14 | — | A7 | v1 | `evaluation.md` |

不做：跨用户对比、Agent 排名、「契合度」合成分（Demo `fitOf()` 删除）。

### 2.12 趋势与变化检测（AN-12 / AN-15）

| 产物 | 定义 | 字段 | 分母 · 置信度 | Demo | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- | --- |
| `metrics?bucket=day` | 任一指标的日序列 `[{bucket, value, n, lo, hi, basis}]` | 对应字段 | 桶内 n；比例 `wilson` | A1-17；Lite·概览按日强度 | MVP | `activity().by_day`；PR#32 `bucket=day` |
| `metrics?bucket=week∣month` | 周 = `display_timezone` 下的 ISO 周；末桶不完整标 `partial_bucket = true` | 同上 | 同上 | A1-19、A6-06、A6-07、POP-06、WG-04 | v1 | PR#32 `bucket=week∣month` |
| `compare_previous` | 同长度紧邻上一窗口、同 `Scope`，输出 `current / previous / delta / delta_lo / delta_hi`；比例差用 Newcombe 区间；`previous.n < 5` 显示「无可比上期」；基期为零不生成百分比 | 同上 | 两窗口各自 n | A1-06、A5-09 | v1（Lite 无上期对比） | PR#32 `compare_previous=true`（计数差，无区间） |
| `change_flags[]` | 最近 2 周 vs 之前 4 周基线：`correction_signal_rate / tool_failure_rate / abandoned_rate / rework_rate` 上升且差值区间不含 0 → `rising` | 周序列 | 两段各 ≥ 10 会话 | A1-10、SET-21 | v1 | 计划 |
| `quality_drop` 诊断（AN-15） | `change_flags` 触发后依次查 `model_id / effort_rank` 众数、`session.harness_version`、`compaction_count`、`inventory_item` 变化；输出 `problem(type = quality_drop)` | 上述 | — | A1-10 | v1 | 计划 |
| `novelty` 序列 | 会话相对更早样本的文本新颖度按周均值 | `text.novelty` | 有文本会话 | A6-09 | v1 | `temporal_novelty()` 已有 |

趋势只报可数事件与带区间的变化，不写「提速 X%」；安装后的效果判断是 EV-07，本模块只提供同口径的前后序列。

### 2.13 安装追踪指标注册表（AN-01 / AN-11，供 RC-13 `tracking.metrics`、EV-07 `rec_outcome` 使用）

`tracking.metrics[].metric` 与 `rec_outcome.metric` 只能取本表的名字（EV-07 只读 AN-01 指标，`ai.md` §4.5 要求 `verify.metric` 在本表内）；每项都按 `Scope`（`tracking.scope_filter`）与前后窗分别计算，返回 `{value, n, lo, hi, basis}`。

| metric | 定义 | 字段 | 分母 | `basis` | 阶段 |
| --- | --- | --- | --- | --- | --- |
| `allow_rule_matches:<rule_id>` | 装后 `tool_call(kind = shell)` 的 `command_head` 命中该放行规则前缀的次数 | `install_plan.targets[].content`、`tool_call.command_head` | 计数 | measured | MVP |
| `would_prompt_count:<key>`、`denied_count` | §2.4 对应信号次数 | `signal` | 计数 / 有 shell 的会话 | measured | MVP |
| `destructive_allowed_count` | §2.4 `risky_command`（命令族命中）且该调用 `approval ≠ declined`、未被 hook 拦截的次数；护栏必须为 0 | `signal(risky_command)`、`tool_call.approval`、`hook.run` | 计数 | measured | MVP |
| `hook_runs:<hook_id>` | `event.kind = hook.run ∧ attrs.hook_id` 的次数（Orbit 写入的 hook 带固定 id） | `event.kind = hook.run` | 计数 | measured | MVP |
| `false_block_count:<hook_id>` | hook 以退出码 2 拦截后，同轮或下一轮用户 / Agent 手动执行同一 `command_head` 且成功的次数 | `hook.run.attrs.exit_code`、后续 `tool_call` | 计数 | measured | MVP |
| `retry_loop_count[:<command_head>]` | AN-05 `retry_loop` 信号数（基于 `respond.retry_links`）；替代 RC 的 `retry_runs`、`ai.md` 的 `confirmed_same_argument_failed_retries`、EV 的 `consecutive_failed_calls`（后两者只作 main 别名） | `signal(retry_loop)` | 有工具调用的会话 | measured | MVP |
| `skill_invocations:<skill>`（= `by_skill`） | `tool_call.kind = skill ∧ skill = <name>` 次数 | `tool_call.skill` | 计数 | measured | MVP |
| `subagent_spawn_count:<name>`、`subagent_token_share` | §2.2；RC §3.8 子代理主指标在上下文观测可用前用 `subagent_token_share` 替代 `context_peak_ratio` | `session.spawn_call_uid`、`model_call` | 根会话 | measured | MVP |
| `correction_signal_rate[:<dimension>]` | 消息级：`correction` 信号消息数 ÷ 确认真人消息数（沿用 main） | `signal(correction)`、`v_human_message` | 确认真人消息 | proxy | MVP |
| `correction_session_rate[:<dimension>]` | 会话级：有 `correction` 信号的主会话 ÷ 有确认真人消息的主会话（供 AN-06 与 EV-07 DiD） | 同上 | 主会话 | proxy | MVP |
| `instructions_per_workflow_run` | 每次命中同一 `workflow_pattern` 变体的真人消息条数中位数 | `workflow_pattern`、`v_human_message` | 变体命中次数 | measured | v1 |
| `repeat_explanation_count` | `context.compaction` 后 N 轮内与压缩前要求的 `message_digest` 或字符 3-gram Jaccard ≥ 0.9 重复的真人消息数 | `attrs.message_digest`、`event.kind = context.compaction` | 有压缩的会话 | proxy | v1 |
| `human_chars_per_turn`、`tokens_per_session`、`tool_failure_rate`、`interruption_count`、`completed_rate`、`rework_rate`、`verify_ran_rate / verify_pass_rate`、`resident_tokens_median`、`parallel_conflict_count` | §2.2 / §2.3 / §2.5 / §2.6 同名指标 | — | 各自分母 | 各自 | MVP（`parallel_conflict_count` v1） |

不在本表的名字（如 RC §3.8 的 `wasted_minutes_per_session`）不能登记进 `tracking`；需要时先在本表定义。

## 3. 会话分段、阶段识别与关键时刻（AN-03 / AN-09）

### 3.1 三层切分

| 层 | 规则 | 迭代 | 输出 | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- |
| 工作段 `work_block` | 把窗口内全部主会话的确认真人消息按 `ts` 排序，相邻间隔 > 30 分钟切段；段内若有 ≥ 2 个主会话交错出现记 `interleaved = 1`；记录 `agent_sequence`（按首条消息时间排列的 `source.agent`）与 `agent_switch_count`；时间未知的消息不参与 | 阈值按用户节律自适应（中位间隔 × 3，待验证）；`agent_switches_after{…}`（§2.1） | `work_block(block_id, started_at, ended_at, session_uids, human_message_count, interleaved, agent_sequence, agent_switch_count)` | MVP（供 M 轴）；v1（Agent 切换） | 计划；PR#32 `journey` 有部分 |
| 任务 `segment(level = task)` | 直接用 `task/features.segment_tasks()`（首条可用请求、「新任务」切换、可信 `task_id`、「目标改为」只换版本）；旧链路 `profiling/feedback.task_contexts()` 只对 legacy 库生效，标 `task_id_source = legacy_inferred` | v1 加相似度骤降（相邻真人消息字符 3-gram cosine < 0.2）∧ 文件集合变化（`tool_call.files` Jaccard < 0.2）作第三种边界候选，只产候选不自动切；任务边界修正（`label`）随 EV-10 | `segment(level = task, label = scene, confidence)` | MVP | main `analytics/task/`（已实现） |
| 阶段 `segment(level = phase)` | 任务内按工具调用序列逐步打标：`explore`（只读族占优）、`plan`（`plan.update` 或无工具的结构化助手消息）、`implement`（`file.edit / file.change`）、`verify`（`validation_runs`）、`debug`（失败返回后紧接编辑）、`deliver`（最终回复且其后无工具）、`converse`（任务内无工具）、`unknown`；游程 < 3 步并入前一阶段 | 手设参数的粘性 HMM（对角 0.8）平滑；不训练 | `segment(level = phase, label, first/last_event_uid, confidence)` | v1（阶段带是 Advance 独有；Lite 只有任务节点） | 计划 |

阶段标签是规则候选，只用于 Advance 时间线阶段带与 RC-16 工作流模板（`explore` > 50% 且无 `implement` = 无限探索）；不进画像。

### 3.2 关键时刻（AN-09）

规则生成的时刻画实心，AI 推断（`origin = ai`）画空心并附引用。每会话最多展示 8 个，按时间取；MVP 不带 `severity`。

| `key_moment.kind` | 触发 | 来源 | 展示 | 阶段 |
| --- | --- | --- | --- | --- |
| `delivery` | 首条真人目标（任务开始）与每次最终交付 | `segment(task)`、`message.assistant(phase = final)` | 中性标记 | MVP |
| `correction` | AN-05 `correction / explanation_revision`（`frustration` v1） | `signal` | 琥珀 | MVP |
| `failure_streak` | `retry_loop`（`runaway_loop` v1）信号首次成立的位置 | `signal` | 红 | MVP |
| `verify_pass` | 最后一次编辑之后首个 `validation_result = passed` 的已执行验证 | `outcome.validation_runs` | 绿 | MVP |
| `compaction` | `context.compaction`；`mid_task_compaction` 时标注「任务中压缩」 | `event` | 中性 / 琥珀 | MVP |
| `permission_denied` | `permission.decision = deny` 或 `approval = declined` | `event / tool_call` | 琥珀 | v1 |
| `quota_hit` | §2.4 | `signal` | 红 | v1 |
| `deviation`（AI） | AI-03 facet `key_moments[]` 判定 Agent 偏离用户目标的回复（随 AI-03 的 MVP，`ai.md` §14 第 4 条） | `session_facet.key_moments` | 空心紫，带 `event_uid` 引用 | 随 AI-03 |

### 3.3 会话时间线要画什么（给 FE-05 的数据面）

A3 时间线**沿用本地 `ui/vizkit` 分支（`07ee181` 密度泳道 / 关键时刻簇 / now 标记 / minimap、`a4bd9f5` 回放工具栏）的组件**，保留 8 秒回放、拖动播放头、⌘ / Ctrl 滚轮缩放与按步数排布（本机工作文件 第 3 条），只把数据源换成后端；不收缩泳道、不重做。阶段带与情绪泳道 v1。

| 区域 | 数据 | 端点 |
| --- | --- | --- |
| 密度泳道（你 / Agent / 信号） | 真人消息 `ts`；每像素桶内 `tool_call` 数与失败数；`signals[]` 位置 | `GET /v1/analytics/sessions/{id}`（`tool_sequence`、`signals`） |
| 关键时刻簇 | `key_moments[]`（`kind / origin / ts / event_uid / label`） | 同上 |
| 轮次账本 | 每轮：触发者、`autonomy_steps`、工具按 `kind` 聚合计数、失败数、token（有 `model_call` 时）、耗时与 `basis` | 同上 + `GET /v1/sessions/{id}/events?from_seq&to_seq` |
| 阶段带（v1） | `segment(level = phase)` 的区间与标签 | 同上 `segments[]` |
| 上下文线（v2） | `context_used_series`（有观测时）；否则不画，不用累计 token 冒充 | 同上 |
| 时间投影 | 默认活跃时间投影：折叠 > 10 分钟空闲并标注折叠长度；可切换为 `seq`（步数）投影 | 前端按 `ts / seq` 计算（vizkit 已有） |
| 检查器 | 点击任一标记 → `GET /v1/evidence/{event_id}`（脱敏文本；原文需 `…/raw` 并确认） | 现有 |
| 对比模式 B 的选取 | `similar_sessions`（v1）；MVP 仍按同项目最近 | `GET /v1/analytics/products/compare`（PR #32） |

## 4. 统计严谨性

| 规则 | 做法 | 阶段 | 现状 |
| --- | --- | --- | --- |
| 样本量门槛 | 分母 < 5：`value = null, status = insufficient`；5–30：必须带区间并在界面显示 n；人格四轴每轴 `n_units ≥ 30 ∧ 活跃天 ≥ 10`；分组对比每组 ≥ 5（展示）/ ≥ 10（对比结论）；问题升级按 §2.4 `min_sessions` | MVP | main 无门槛（裸值）；PR#27 `insufficient_data`；契约补充约定 |
| 比例区间 | Wilson（z = 1.96）；排序用下界 | MVP | `profiling/analysis.wilson_interval()`；新链路 `analytics/stats.py` 计划 |
| 两比例差 | Newcombe 混合法（随 `compare_previous`） | v1 | 计划 |
| 分组收缩 | 小时 / 项目 / 模型 × 档位的比率做 Beta-Binomial：`(k + m·p₀) / (n + m)`，m = 10；展示收缩前后两值 | v1 | 计划 |
| 均值与人格区间 | 按天分块 bootstrap（B = 1000）；MVP 四轴只用按单位计数的 Wilson | v1 | 计划 |
| 会话相关性 | 同任务、fork、同一天的会话不独立：区间只作参考，不做显著性检验结论；文案固定「参考区间」 | MVP | `docs/modules/analytics/modeling.md` 已声明 |
| 相关不等于因果 | `mood_drivers`、跨项目散点、前后对比一律附固定文案；因果判断只在 EV-07 DiD | MVP | Demo A6-11 已有文案 |
| 去重 | 事件：`attrs.replayed_from / duplicate_of` 与 L1 `record_event.relation`；用量：`call_uid` 去重、`cumulative` 与 `delta` 不相加、`root_tree` 覆盖不再加子代理；消息：同轮同角色同内容镜像只计一次（`message_digest`）；会话：fork 复制段不计、`import` 默认排除 | MVP | main `select()`、`usage()`；`packages/data` `record_event` |
| 分母表 | 真人消息类 = 确认真人消息；会话比例 = 有 ≥ 1 条确认真人消息的主会话；工具类 = 已知成功 + 失败；任务类 = `(session_uid, task_id)` 去重；用量类 = 合规 `model_call`；「有机会发生」类按 §2.4；合并比例一律 `Σ分子 / Σ分母`，不平均会话比例（PR #27 `pooled_rate`） | MVP | `feature_dictionary.denominator` 逐项声明 |
| 未知语义 | 来源未知的 user 消息、状态未知的调用、时间未知的事件、`kind = unknown` 的会话全部单列 `unknown_counts`，不进分母也不当 0；`coverage.status ≠ available` 的项界面显示「部分 / 不可用」；`0` 只表示有覆盖且确实为零 | MVP | main 已实现（918 条未知来源） |
| 时间 | UTC 毫秒；`[from_ts, until_ts)`；顺序只用 `seq`；`attrs.time.quality = estimated` 的时长标 `estimated`；`window=7d/30d/90d` 为滚动 `N × 24` 小时 | MVP | main / `packages/data`；PR#27 |
| 版本 | 每个产物带 `rules_version`（检测与阈值）、`feature_schema_version`、`analysis_digest`；每次分析记录所有参与族的版本；阈值只在合成夹具与 EV-02 标注集上调 | MVP | `analysis_digest`、`FEATURE_VERSION = feature-analytics-v2.2-bottleneck`；`rules_version` 计划 |

## 5. 计算管线

### 5.1 现有链路与目标链路

```mermaid
flowchart LR
  DB[(tandem.db 只读<br/>tandem_data.analysis_input.read_analysis)] --> AD[AN-16 canonical_bundle<br/>AnalysisInputBundle]
  LEG[(legacy .local/*.sqlite)] -. DT-20 过渡 .-> AD
  AD --> SEL[inputs.select<br/>排除原因 · 重放剔除 · 未来返回隔离]
  SEL --> FAM[八族<br/>task · instruction · preference · interaction<br/>respond · cost_time · outcome · outcome_subjective]
  FAM --> SIG[analytics/signals.py<br/>AN-05 适配 → signal → AN-06 problem · AN-09 key_moment]
  FAM --> ROW[AN-02 会话行 · AN-19 合成器]
  ROW --> AGG[组合层 presentation / products<br/>overview · metrics · tools · projects · text · profile<br/>AN-01 / AN-08 / AN-12]
  SIG --> AGG
  AGG --> API[/v1/analytics/*]
  LBL[(analysis.db<br/>candidate · label · install_ledger · tracking)] --> AGG
  CACHE[(analysis.sqlite<br/>session_result · analysis_section · analysis_row)] -. 按树指纹复用会话行 .-> ROW
  AGG -. section 读穿缓存 LRU → analysis_section .-> API
```

| 环节 | 现状（main） | 目标（MVP） | 触发 |
| --- | --- | --- | --- |
| 输入适配 | `analytics/inputs.py::legacy_bundle()` 一次读事务；`data_access/store.py` 已能打开 canonical 库 | 新增 `canonical_bundle(home, scope)`：调用已合入的 `read_analysis()`（PR #14 版本，含截止后状态置 `unknown` 与事件 kind 过滤），透传 `usage_snapshots / statistical_members / diagnostics / coverage`，把 `projection_run` 写进 `versions`；`scene / task_id` 由 AN-17 补到 `attrs`；`max_events = 100000` 超限时按 `root_session_uids` 分批（契约 V4） | 每次查询 |
| 选择 | `select()` 七种排除原因、重放剔除、模型歧义轮次、未来返回隔离 | 保留；接 canonical 后以 `statistical_members` 为准；PR #32 `analytics/context.py` 的「同一次请求只选择一次、为会话建索引」作统一入口 | 每次查询 |
| 会话行 | `analyze_bundle()` 每次全量重算所有会话 | **会话行物化**：只依赖本会话树的行写入 `session_result`（键 `root_session_uid, scope_class, algo_version`，值带 `tree_fp`），只重算树指纹变化或缺失的根会话，未命中 ≥ 300 个时按根会话分块并行；任务 / 偏好 ID、文本坐标与全局覆盖在装配时附加；`signal_id = stable_id(session_uid, kind, event_uid ∣ call_uid)`、`problem_id = stable_id(type, key, scope, scope_id)` 保证跨重算稳定 | 导入后预热 / 按需 |
| 信号与问题 | `profiling/bottlenecks.diagnose()`、`bottleneck_features` 查询现算 | `analytics/signals.py`：检测器适配 → `signal[]` → §2.4 映射 → `problem[]`；`problem` 的 `resolved / dismissed` 读 `label`；`problems_top[]` 进 `overview` | 随查询 |
| 聚合与区间 | `overview / projects / tools / text` 无区间；PR #27 `presentation-v1`、PR #32 `analysis-products-v1` 各有一套组合层 | `metrics(scope, metric[], bucket, group_by)` 端点：从会话行聚合，比例带 Wilson；两套组合层以先合入者为底，另一套 rebase 并入，本文 §2 为验收口径 | 按需；**section 缓存**：每个端点只算所需 section，按 `request_key = H(Scope, with_text, algo_version)` 与 `input_fp = H(projection_run, 选中会话树指纹)` 存入 `analysis_section` / `analysis_row`，读时先查进程内 LRU；输入或版本一变即失配，不提供过期结果 |
| 画像 | `profiling/portrait.profile()` 查询现算；PR #27 `presentation/profile.py` | `observations` 原样；四轴 Wilson 版与逐月画像按窗口现算；不建 `profile / profile_history` 表 | 每次查询 |
| 作业状态 | 无；`ImportService` 只管导入，`ai_job` 只管 AI | `analysis_run(run_id, trigger ∈ import/rules_version/manual, stage ∈ select/rows/signals/problems/profile, status, progress{done,total}, started_at, finished_at, error)`（内存 + `analysis.db`）与 `GET /v1/analytics/status`（SSE）；`meta.freshness` 带 `analysis_run_id`；MVP 只用于首次冷算进度与 Lite「同步」状态；阶段事件供 NT-04 / OB-05（v1），AI 语义阶段由 `ai_job` 接续 | 导入后 / 手动 |
| 快照与导出 | `cli report`、`cli analytics --output`、`application/reports.py`；PR #32 同源导出（JSON / CSV / HTML） | MVP 复用 CLI 与同源导出；`report_snapshot(kind ∈ weekly/share_card/menubar/persona_fixed)` 表 v1 | 周报定时（v1） |

派生结果缓存（`session_result / analysis_section / analysis_row / session_exclusion`）放在 `analysis.sqlite`，可随时删除重算，清理策略见[统计分析与完整分析记录](../modules/analytics/statistics-history.md)；`analysis.db` 在 MVP 只存用户状态与推荐 / 安装侧表（`candidate / rec_exposure / label / install_ledger / install_state / tracking / rec_outcome / eval_run / ai_usage / session_facet`）；`signal / problem / profile / segment / key_moment / workflow_pattern / dfg_edge / declare_check / report_snapshot` 的 DDL（契约 §3.2b）保留为 v1 物化目标，MVP 只作响应形状。

### 5.2 八族 ↔ AN ID 映射与代码落点

四条特征族分支都已在 main，`analytics/common.py` 只有一份，`FEATURE_VERSION` 已按合并顺序递增（PR #13 `v2` → PR #17 `v2.1-subjective` → PR #19 `v2.2-bottleneck`）；后续分支在 rebase 时继续递增（PR #27 `presentation-v1`、PR #32 `analysis-products-v1` 是组合层自己的版本，不改 `FEATURE_VERSION`）。MVP 期间不迁移任何旧模块。

| 目录（`packages/backend/src/tandem_backend/`） | 作者 | 承载的 AN ID | 说明 |
| --- | --- | --- | --- |
| `analytics/common.py`、`inputs.py`、`service.py`、`bottleneck.py` | main | AN-16、AN-01 调度 | `service.analyze_bundle` 保留；PR #32 `context.py / semantic.py` 把「选择一次、建索引、八族、组合」拆成有名称的步骤（`docs/plans/analysis-review.md` 建议） |
| `analytics/respond/` | genius-FXC | AN-04（DFG、三步链、子代理关系）、AN-05.2 `retry_loop`（经 `retry_links`）、AN-02 工具字段 | `calls / sequence / relations / features` |
| `analytics/interaction/` | genius-FXC | AN-05.1 `correction` 词表与确认标注消费、§2.9 意图、AN-09 `correction` 时刻 | `classify_message_intents / locate_interventions / summarize_interactions` |
| `analytics/cost_time/` | genius-FXC | AN-01 节律与用量、AN-11 `resident_tokens`、§2.6 | `activity / tokens / durations` |
| `analytics/outcome/` | genius-FXC | AN-19 客观验证层（`extract_validation_runs / match_acceptance_criteria / summarize_objective_outcomes`）、AN-05.2 `missing_verification` 的输入 | **客观验证与验收匹配已实现**（PR #19 / #24） |
| `analytics/outcome_subjective/` | MistyHuang03 | AN-19 显式反馈层（`classify_feedback`）、AN-05.1 `subjective_feedback`、AN-07 雏形 | 已实现 |
| `analytics/instruction/` | MistyHuang03 | AN-17（8 字段约束、`resolve_instruction_scope`）、AN-08 `requested_autonomy / plan_first / verification` 证据、`structure()` | 已实现；`/v1/analytics/instruction` |
| `analytics/preference/`、`analytics/task/` | MistyHuang03 | AN-08 `preferences.effective`；AN-03 任务级、AN-18（`representation.py`）、§2.9 `domain / task_type` | 已实现；`/v1/analytics/tasks`、`/preferences` |
| `analytics/text.py` | main | AN-18 | 保留 |
| `profiling/{feedback,bottlenecks,portrait,analysis,trajectory,content}.py` | main 旧链路 | AN-17 任务上下文、AN-05.1 `explanation_revision / long_response / unexplained_terms`、AN-08 `observations`、AN-10 `wilson_interval` | 保留，不重写；`profiling/analysis.py` 的 `schema 1.8` 报告留给 CLI 兼容 |
| `analytics/presentation/`（PR #27）/ `analytics/products/`（PR #32） | genius-FXC / yhyfhgs | AN-01 组合层、AN-08 四轴（`presentation/profile.py`）、AN-12 `model_effort / bucket / compare_previous`（`products/trends.py`）、AN-04 调用级转移矩阵、AN-03 `journey`、§2.9 `phrases_top` | 两者功能重叠（概览、工具矩阵、月度画像、会话检索）；以先合入者为底，另一个 rebase 只保留差集；端点统一为 `metrics / profile / sessions` 形状 |
| `analytics/signals.py`（新） | 本文 | AN-05 检测器适配与闭集、§2.4 映射表、AN-06 升级、AN-09 规则时刻、`risky_command` 词表 | MVP 唯一新增的分析文件（约 400 行） |
| `analytics/stats.py`（新） | 本文 | AN-10 Wilson、`insufficient`、`{value, n, lo, hi, basis}` 对象 | MVP（约 60 行）；Newcombe / EB / bootstrap v1 |
| `analytics/segment/`、`analytics/profile/`、`analytics/problems.py` | — | 阶段打标、物化画像、AN-15 | v1；MVP 不新建目录 |

**端点合并**（契约 §5.3 第 3 版）：保留 `tasks / preferences / instruction` 作为特征族明细端点；`bottleneck` 作为四族原始输出过渡期保留，其中字段按 AN ID 分别并入 `tools`（respond）、`sessions`（interaction、outcome、outcome_subjective）、`metrics`（cost_time），接齐后退役；PR #32 的 `products / products/sessions / products/compare` 与计划中的 `metrics / profile / signals / problems` 合并为一套：`products` → `overview + metrics`，`products/sessions` → `sessions?query&offset&limit`，`products/compare` → `sessions/{id}` 两次调用或保留为 `sessions/compare`；`/v1/analytics/recommendations`（PR #26）归 RC。

### 5.3 性能预算（10 万事件级，契约 V4，阻塞 MVP）

| 项 | 预算 | 依据 |
| --- | --- | --- |
| 冷算：90 天窗口 ≤ 100k 事件、≤ 30k 工具调用、≤ 5k 真人消息 | 全部会话行 + 信号 + 问题 + 画像 ≤ 10 s（首次导入后带 `analysis_run` 进度）；`with_text` 再 +2 s | PR #13 实测 1 万条真人消息 3.3 s；main 真实快照 40,664 事件 3.11 s → 100k 线性外推约 7.6 s，未计新增检测器 |
| 热查询（section 缓存命中） | `overview / metrics / projects / tools` ≤ 200 ms；`sessions?limit=50` ≤ 100 ms；`sessions/{id}` 按键读一行，不触发全量计算 | 进程内 LRU + `analysis_section` / `analysis_row`；1,000 会话构造数据有回归测试 |
| 文本表示 | TF-IDF ≤ 20k 特征、SVD ≤ 32 维、DBSCAN O(n²) 在会话数 ≤ 5k 可接受；> 5k 按项目分块 | `text.py` 参数 |
| 内存 | 事件行一次驻留 ≤ 500 MB；超过改为按根会话分批 | `max_events = 100000` 守卫 |
| 复杂度禁区 | 不做跨会话 O(N²) 相似度（`duplicate_prompt` 用 `message_digest` 精确匹配 + 7 天内 3-gram 近似，v1）；不做实时 HMM | — |
| 增量 | 导入 1 个新会话后只重算该根会话的行（`session_result` 命中其余），聚合用缓存行做一次 O(E) 分组 | 树指纹：一条 `GROUP BY root_uid` SQL |

## 6. MVP 与迭代

### 6.1 先做的部分（按 §0.10 判定规则收口）

| 顺序 | 内容 | 复用 | 新写 | 复杂度 |
| --- | --- | --- | --- | --- |
| 1 | AN-16 `canonical_bundle` + 真实 `tandem.db` 重跑 analytics，核对 `human_origin` 覆盖（契约 V11）；`analysis_run` 进度 | `read_analysis()`、`AnalysisInputBundle.from_dict`、PR #32 `context.py` | 适配器约 150 行 | S |
| 2 | AN-01 `metrics` 端点 + AN-10 `stats.py`（只 Wilson + `insufficient`）+ 响应 `n / lo / hi / basis / status`；AN-01 的 MVP 指标清单 = 现有测量 + Lite 用到的约 20 项：`sessions`、`active_minutes / observed_span`、`human_messages_by_day`、`by_hour × weekday`、`correction_signal_rate`、`turns_per_session`、`by_tool`、`failure_rate`、`transitions`、`by_error_class`、`subagent_spawn_count`、`token_buckets`、`completed_rate / outcome_mix`、`by_file_language`、`clusters / embedding`、`phrases_top`、`friction_type_mix`、`sessions_by_source`、四轴 + §2.13 注册表 | `feature_dictionary`、`wilson_interval()`、PR #27 / #32 组合层 | 端点 + 聚合约 250 行 | M |
| 3 | AN-19 合成器（显式反馈 = `classify_feedback`，验证 = `extract_validation_runs`，facet 映射，结构补 `interrupted` 与「最后一条是纠偏」）；AN-02 补 `outcome / verify_* / edit_without_verify / autonomy_steps` | `outcome/`、`outcome_subjective/`、`portrait.interaction` | 约 60 行 | S |
| 4 | AN-05 四个检测器：`correction`（现有 proxy 改写成 `signal` 行）、`retry_loop`（`retry_links` 适配器约 40 行）、`would_prompt`、`missing_verification`；`risky_command` 词表版；现有 `explanation_revision / long_response / unexplained_terms / requirement / subjective_feedback / interruption` 转 `signal` 行；`rules_version` | `correction_terms`、`retry_links`、`validation_runs`、DT-13 只读 / 破坏性命令词表 | 约 250 行 | M |
| 5 | AN-06 升级 + §2.4 映射表 + `problems_top[]`（供 A1-10、A7、Lite 建议依据）；`label(resolved/dismissed)` 读取 | `_preferences.cross_project_candidate` 阈值思路 | 约 120 行 | S |
| 6 | AN-03 任务级（直接用 `segment_tasks()`）+ `work_block`；AN-04 三步链（按 `kind` 族，支持会话 ≥ 3；PR #32 已有）；AN-09 五类规则时刻（`delivery / correction / failure_streak / verify_pass / compaction`） | `segment_tasks()`、`signal`、PR #32 `journey` | 约 150 行 | M |
| 7 | AN-12 `group_by ∈ {project, model_effort, source, task_type}` 与多键；`bucket = day` | `activity()`、PR #32 `model_effort` | 约 80 行 | S |
| 8 | AN-08 `observations` 原样 + 四轴 Wilson 版（等权、`?` 规则、`experimental`）+ 逐月现算 | `portrait.profile()`、`_preferences()`、PR #27 `profile.py` | 约 150 行 | M |
| 9 | AN-11 `resident_tokens_median`；PR #31 合入后接 `installed_unused / rule_coverage / rule_file_stats` | `model_call` 首条、`inventory_item` | 约 80 行 | S |
| 10 | AN-14 MVP = 复用 `cli report / analytics --output` 与 PR #32 同源导出，口径对齐 `metrics` | `application/reports.py` | 约 40 行 | S |

MVP 完成标准：Lite 8 页与 Advance A1–A6 的每个数字都能回到 `overview / metrics / sessions / profile / signals / problems` 端点，且每个比例带 n 与 Wilson 区间（EV-01.2 做成检查项）；三张安装闭环卡的第 2 段（§8）可用；在三位成员本机 `tandem.db` 上冷算 ≤ 10 s、热查询 ≤ 1 s。

### 6.2 v1 / v2 与「过于复杂先不做」

| 阶段 | 内容 |
| --- | --- |
| v1（有标注与几周数据后） | 阶段打标与粘性 HMM；轮次变体、`wait_side`、Declare（AN-04）；`frustration / runaway_loop / edit_churn / mid_task_compaction / duplicate_prompt / parallel_conflict / quota_hit / workflow_pattern` 检测器与 `severity` / 上游去重；AN-07 情绪与 `mood_drivers`；AN-13 实时状态（`running / idle / failing / stalled / just_finished`，`failing` 对运行中会话尾部增量跑 `retry_loop` 规则，`stalled` = 轮次未闭合且 ≥ N 分钟无新事件，MB-13 优先级 `failing > 等待审批 > 上下文超阈值 > 运行中 > 刚完成`，SSE 事件带 `session_uid`）；AN-14 `report_snapshot` 表（含 `persona_fixed`）；AN-12 `bucket = week`、`compare_previous`（Newcombe）、`change_flags`；AN-10 EB、bootstrap、`method` 字段；AN-15；`cache_rebill / rework_tax`；`similar_sessions`；`agent_switches_after`；`task_type → benchmark_task_class`；`signal / problem / profile` 等派生表物化；信号权重按 `label.not_me` 校准；`analytics/segment/`、`analytics/profile/` 目录 |
| v2（多 Agent / 多用户后） | `context_peak_ratio / context_pressure`（需上下文观测，契约 C9）；DSH 审批等待时长；跨 Agent 落点差异的分层；PELT / BOCPD 变点；AI 推断时刻的回放评测 |
| 先不做 | 训练型 HMM / HSMM、DTW、GNN、HDBSCAN / UMAP；p / q 分布损失、Bradley–Terry、反馈似然更新、分层贝叶斯；健康分 / 契合度合成分；跨用户常模；关键路径；PM4Py（AGPL）；向量语义匹配；bandit |

## 7. 功能清单

ID 沿用契约 §2.3；AN-19 为本文新增；AN-05 拆为 05.1 / 05.2，AN-08 拆为 08.1 / 08.2，AN-01 增 01.1。负责人按分支 / PR 作者直接写定（契约 §6 第 3 版同步）：四族非语义实现（`respond / interaction / cost_time / outcome`，PR #19 / #24）与 presentation 组合层（PR #27）作者为 `genius-FXC`，语义四族（PR #13 / #16 / #17）作者为 `MistyHuang03`，数据层与 products 组合层（PR #14 / #31 / #32）作者为 `yhyfhgs`。现状取值：`main:<模块>`、`PR#27 / #31 / #32`、`计划`。

| ID | 名称 | 说明 | 输入 | 输出 | 依赖 | 阶段 | 现状 | 负责人 | reviewer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AN-01 | 指标引擎 | MVP = feature-analytics 现有测量 + Lite 8 页约 20 项（§6.1 第 2 步）+ §2.13 追踪注册表，比例带 Wilson；新增 `GET /v1/analytics/metrics?metric[]&bucket&group_by`；其余 §2 指标 v1 | `AnalysisInputBundle`、AN-02 行 | `overview`、`metrics[{metric, bucket, group, value, n, lo, hi, basis, status}]`、`tracking_registry`、`feature_dictionary` | AN-16、AN-10 | MVP | main:`analytics/features.py`、`service.py`、八族 `dictionary.py`（无区间、无 `group_by`） | MistyHuang03 | yhyfhgs |
| AN-01.1 | 组合层（presentation / products） | 八族 → 页面字段的组合、固定坐标、排行、月度网格；以先合入者为底 | 八族输出 | `presentation-v1` / `analysis-products-v1` 段 | AN-01 | MVP | PR#27 `analytics/presentation/`（genius-FXC）；PR#32 `analytics/products/`（yhyfhgs） | genius-FXC | yhyfhgs |
| AN-02 | 会话事实 | 每主会话一行：消息 / 轮次 / 工具 / 用量 / 时长 / 纠偏 / 结构 / 语言 / 结果 / 验证 / 自主步数 / 压缩 / 簇坐标 / 信号摘要；查询现算 | `select()` 结果 | `sessions[]` 行（§2.2、§2.3、§2.6 字段） | AN-16、AN-19、AN-05 | MVP | main:`session_features()` + `bottleneck_features / subjective_outcomes`；缺 `outcome / verify_* / autonomy_steps / signals_summary` | MistyHuang03 | yhyfhgs |
| AN-03 | 分段 | 工作段（30 分钟空闲，`agent_sequence`）、任务（`segment_tasks()`）；阶段打标 v1 | 真人消息 `ts`、`tool_call` 序列 | `segment(level = task)`、`work_block`；`segment(level = phase)`（v1） | AN-16、AN-17 | MVP（任务 + 工作段）；v1（阶段、HMM、相似度边界） | main:`analytics/task/features.segment_tasks()`；PR#32 `products/journey`；工作段计划 | MistyHuang03 | genius-FXC |
| AN-04 | 过程挖掘 | 按 `(name_raw, kind)` 的 DFG 与 `P(next ∣ current)`、三步链、子代理关系；轮次变体、`wait_side`、Declare、并行度 v1 | `event.seq / kind`、`tool_call`、`turn` | `tools.transitions / three_step_chains / by_kind`、`subagent_relations`；`workflow_pattern / dfg_edge / declare_check`（v1） | AN-16 | MVP（DFG、三步链、关系）；v1（变体、wait_side、Declare） | main:`respond/sequence.workflow()`、`respond/relations`；PR#27 / PR#32 调用级矩阵与三步链 | genius-FXC | MistyHuang03 |
| AN-05.1 | 语义检测 | `correction`（含 `dimension`）、`requirement`、`explanation_revision`、`long_response`、`unexplained_terms`、`subjective_feedback`；`frustration` v1；词表双语、阈值按字符 | 真人文本、`feedback.signals`、`instruction`、`outcome_subjective` | `signal` 行（`friction_type`、`problem_type`、`unit`） | AN-16、AN-17 | MVP（6 类）；v1（`frustration`） | main:`interaction/rules.correction_terms`、`profiling/feedback`、`profiling/bottlenecks.diagnose()`、`outcome_subjective` | MistyHuang03 | yhyfhgs |
| AN-05.2 | 非语义检测 | `retry_loop`（`retry_links` 适配器）、`would_prompt`、`permission_denied`、`missing_verification`、`interruption`、`risky_command`（词表）；`runaway_loop / edit_churn / mid_task_compaction / context_pressure / duplicate_prompt / workflow_pattern / quota_hit / parallel_conflict` v1 | L3 行、`outcome.validation_runs`、DT-13 词表、`inventory_item` | `signal` 行 | AN-16、DT-13、DT-09（PR #31，`would_prompt` 扣除） | MVP（6 类）；v1（其余） | main:`respond/sequence.retry_links`、`outcome/validation.py`、`permission_request_count`；适配器计划 | genius-FXC | MistyHuang03 |
| AN-06 | 问题升级 | §2.4 映射表（`signal.kind → problem.type / key`，全称 key）；`(problem_type, key, scope)` 聚合；`min_sessions` 按类型 ∧ `wilson_lo ≥ 0.05`；`problem_id` 稳定；`status` 读 `label`；`problems_top[]` | `signal`、分母表、`label` | `problem[]`、`GET /v1/analytics/problems`、`overview.problems_top[]` | AN-05、AN-10 | MVP | 计划（`analytics/signals.py`）；雏形 main:`profiling/analysis._preferences()` 的 `cross_project_candidate`、PR#27 `diagnostics.findings` | MistyHuang03 | yhyfhgs |
| AN-07 | 情绪弱标注 | 6 个打标函数等权投票，abs(score) < 0.3 不计；按日 / 周加权；`mood_drivers`；标「实验性」；AI-04 消解歧义 | 真人文本、AN-05 词表 | `signal(kind = sentiment)`、`text.mood_series`、`mood_drivers[]` | AN-05、AN-17 | v1（Advance 独有） | 雏形 main:`outcome_subjective.classify_feedback().signal`；PR#32 情绪表达趋势 | MistyHuang03 | genius-FXC |
| AN-08.1 | 明确要求覆盖与偏好 | `observations[]`（8 维度 + convention，Wilson）、`preferences.effective`、`opening_structured / planning / verify_requested` 率；`interaction_pattern_mix` v1 | `feedback.signals`、`instruction`、`preference` | `profile.observations / requirements / preferences` | AN-17 | MVP | main:`profiling/portrait.profile()`、`profiling/analysis._preferences()`、`analytics/preference/`、`analytics/instruction/` | MistyHuang03 | genius-FXC |
| AN-08.2 | 四轴与逐月画像（实验性） | 四轴按单位计数 + Wilson 区间整体偏一侧才给字母，否则 `?`；`n_units ≥ 30 ∧ 活跃天 ≥ 10`；逐月按窗口现算；bootstrap、权重校准、`profile_history` 表 v1 | AN-02 行、AN-03 `work_block`、`instruction` | `profile.axes / code / experimental`、`GET /v1/analytics/profile(?month)` | AN-02、AN-03、AN-10、AN-08.1 | MVP（Wilson 版） | PR#27 `presentation/profile.py`（`collaboration-profile-v1`，任务等权、D 轴门槛）；Demo `15-derive.js::persona` 为示例算法 | genius-FXC | MistyHuang03 |
| AN-09 | 关键时刻 | 规则时刻 5 类实心（§3.2），每会话 ≤ 8；AI `deviation` 空心随 AI-03；`permission_denied / quota_hit` v1 | `signal`、`segment`、`outcome.validation_runs`、`event`、`session_facet.key_moments` | `sessions/{id}.key_moments[]` | AN-03、AN-05、AN-19 | MVP（规则 5 类 + 随 AI-03 的 AI 时刻）；v1（其余规则时刻） | 计划（`analytics/signals.py`）；Demo A3-17 为合成 | MistyHuang03 | genius-FXC |
| AN-10 | 小样本统计库 | Wilson、门槛与 `insufficient` 规则、`{value, n, lo, hi, basis}` 对象；Newcombe、Beta-Binomial EB、按天 bootstrap、`method` 字段 v1 | 计数 | `analytics/stats.py` | — | MVP（Wilson）；v1（其余） | main:`profiling/analysis.wilson_interval()`、`union_duration()`、`features.quantile()` | MistyHuang03 | yhyfhgs |
| AN-11 | 已装未用、常驻开销与缓存浪费 | `resident_tokens_median`；`installed_unused[]`（逐项事实，AN 侧不设门槛）、`rule_file_stats`、`rule_coverage[]`（随 PR #31）；`cache_rebill / rework_tax` v1 | `model_call`、`inventory_item`、`tool_call.mcp_server / skill`、`hook.run`、`context.inject` | `metrics(resident_tokens_median)`、`installed_unused[]`、`projects[].rule_coverage` | DT-09（PR #31）、DT-08、AN-16 | MVP（`resident_tokens`；清单项随 PR #31 合入）；v1（缓存重复计费、返工税） | 计划；PR#31 `inventory_item` 扫描（七个 Agent） | MistyHuang03 | yhyfhgs |
| AN-12 | 趋势与对比 | `group_by ∈ {project, model_effort, source, task_type}` 与多键；`bucket = day`；周 / 月序列、`compare_previous`（Newcombe）、`change_flags`、跨项目散点（无回归线）v1 | `metrics` | `metrics[group / bucket]`、`compare_previous`、`change_flags[]` | AN-01、AN-10 | MVP（`group_by`、日序列）；v1（周序列、上期对比、`change_flags`） | main:`cost_time/activity()`；PR#32 `model_effort / bucket / compare_previous`（计数差） | MistyHuang03 | genius-FXC |
| AN-13 | 实时状态 | 运行中 / 空闲 / `failing` / `stalled` / 刚完成、当前工具、`context_used_ratio`（有观测时）；SSE 带 `session_uid`；MB-13 优先级 | `watch` 事件、`session.status`、`source_file.watermark`、尾部增量 `retry_loop` | `GET /v1/analytics/realtime`（SSE） | DT-02（PR #11 `watch.ts`） | v1（只服务菜单栏 / HUD） | PR#32「最后观测状态」（明确生命周期事件）；`watch.ts` 只采集 | yhyfhgs | MistyHuang03 |
| AN-14 | 固定口径快照与报告 | MVP 复用 `cli report / analytics --output` 与 PR #32 同源导出；`report_snapshot(kind ∈ weekly/share_card/menubar/persona_fixed)` 表 v1 | `metrics`、`problems_top`、`profile` | `export/*`；`report_snapshot`（v1） | AN-01、AN-06、AN-08 | MVP（导出）；v1（快照表） | main:`application/reports.py`、`cli report`；PR#32 同源导出 | MistyHuang03 | genius-FXC |
| AN-15 | 质量下降诊断 | `change_flags` 触发后依次查模型 / 档位、harness 版本、压缩、上下文、skill 移除 | AN-12、`model_call`、`session.harness_version`、`inventory_item` | `problem(type = quality_drop)` + 检查表 | AN-12、AN-06、DT-09 | v1 | 计划 | MistyHuang03 | yhyfhgs |
| AN-16 | 分析输入适配与范围 | `canonical_bundle()` 读合入后的 `read_analysis()`（透传 `usage_snapshots / statistical_members / diagnostics`）；`Scope` 补 `source_ids`；legacy 适配器保留到退役；`human_origin` 覆盖核对；`analysis_run` 进度与 `GET /v1/analytics/status` | `tandem.db`（只读）、legacy 库 | `AnalysisInputBundle`、`meta{coverage, selection, versions, freshness}` | DT-19、DT-20 | MVP（第一件事） | main:`analytics/inputs.py`（`Scope`、`legacy_bundle`、`select`）、`data_access/store.py`；PR#32 `context.py`；canonical 适配闭环计划 | MistyHuang03 | yhyfhgs |
| AN-17 | 任务上下文与明确要求 | 任务 `task_id`、场景、读者、交付语言、8 维度要求与篇幅契约；指令 8 字段约束与时点解析；`domain / task_type`（task-taxonomy-v1，`type_source ∈ rule/facet`）；要求—交付—反馈关联 | 真人文本、交付、`turn` | `attrs.scene / task_id`、`signal(kind = requirement)`、`instruction` 记录、`task.domain / task_type` | AN-16 | MVP（已实现） | main:`profiling/feedback.py`、`analytics/instruction/`、`analytics/task/taxonomy.py` | MistyHuang03 | yhyfhgs |
| AN-18 | 无监督文本表示 | 字符 n-gram TF-IDF → SVD → DBSCAN 簇、PCA 坐标、前缀拟合新颖度；簇不命名；MVP 显示「簇 #k」+ 前 5 个 `top_terms`；`similar_sessions` v1 | 真人文本（会话粒度） | `text{clusters, coordinates, top_terms, novelty}` | AN-16 | MVP（已实现） | main:`analytics/text.py`、`task/representation.py` | MistyHuang03 | genius-FXC |
| AN-19 | 会话结果判定 | 约 60 行合成器：`outcome` 四态 + `outcome_basis`（`explicit_feedback > verify_pass > facet > structural`）、facet 映射表、`verify_requested / verify_ran / verify_pass / verify_candidate / edit_without_verify`、`rework_rate`；不把「声称完成」当完成 | `outcome_subjective.classify_feedback`、`outcome.extract_validation_runs`、`session_facet.outcome`、`turn.status`、AN-05 信号 | AN-02 行字段、`metrics(completed_rate, abandoned_rate, verify_ran_rate, verify_pass_rate, edit_without_verify_rate, rework_rate)` | AN-16、AN-05 | MVP（合成器） | main:`analytics/outcome/`（客观验证与验收匹配已实现）、`analytics/outcome_subjective/`（显式反馈已实现）；合成器计划 | genius-FXC | MistyHuang03 |

## 8. 串联：本模块在三张功能卡里负责什么

三张端到端功能卡（契约 §4.1 九段模板）只写一份在 `docs/plans/feature-map.md`；本节只给每张卡的第 2 段「触发与证据（AN）」，并列出其他 AN feature 的消费者。

| 功能卡 | 第 2 段：信号 → 问题（AN） | 分母与升级 | 追踪指标（§2.13） | 降级 |
| --- | --- | --- | --- | --- |
| 只读命令自动放行 | AN-05.2 `would_prompt`（`kind = shell ∧ is_wrapper = 0 ∧ command_head ∈ command.readonly`，权限模式 default，未被已装 allow 覆盖）→ AN-06 `problem(type = permission_friction, key = would_prompt:readonly_shell)` | 分母 = 有 shell 调用的主会话；`sessions ≥ 3 ∧ wilson_lo ≥ 0.05` | `allow_rule_matches:<rule_id>`（触发）、`would_prompt_count:readonly_shell` ↓（机械）、`denied_count` 不升、`destructive_allowed_count = 0`（护栏） | 无清单时按全部只读命令计并标「未扣除已放行规则」；`permission_mode` 不可得时标 proxy（契约 V12） |
| 重复失败熔断 | AN-05.2 `retry_loop`（`respond.retry_links` 同轮、同 `status_scope`、同参数 ≥ 2 链接）→ AN-06 `problem(type = tool_env_failure, key = retry_loop:<command_head>)` | 分母 = 有工具调用的主会话；≥ 3 会话 | `hook_runs:<hook_id>`（触发）、`retry_loop_count:<command_head>` ↓（机械）、`false_block_count:<hook_id> = 0`、`interruption_count` 不升（护栏） | 无 `argument_digest` 时按 `command_head + status_scope` 退化为候选并标 proxy |
| 高频纠偏 → 规则 | AN-05.1 `correction`（带 `dimension`）/ `requirement` 跨会话重复 → AN-06 `problem(type = repeated_instruction, key = correction:<dimension>)` | 分母 = 有确认真人消息的主会话；`min_sessions = 2` | 规则文件 `context.inject`（触发，可观测时）、`correction_signal_rate:<dimension>` ↓（机械）、`human_chars_per_turn`、`tokens_per_session` 不升 > 20%（护栏） | `human_origin` 覆盖不足时整卡显示「数据不足」（契约 V11） |

其他消费者（简表；详细串联见 `feature-map.md`）：

| AN | 推荐 RC | AI | 评测 EV | 前端 FE / Demo |
| --- | --- | --- | --- | --- |
| AN-01 / AN-12 | RC-04 `weekly_saving / applicability`、RC-07 减法、RC-08 / RC-14 分层描述、RC-13 注册表（§2.13） | AI-05 叙述只吃汇总统计 | EV-01.2 金标、EV-07 前后窗、EV-08 分层 | FE-03 A1、FE-07 A5、FE-22；Lite 概览 / 项目 |
| AN-02 / AN-19 | RC-02 证据会话集、RC-08 `completed_rate`、RC-16 验证阶梯 | AI-03 facet 输入与 `outcome` 校正、AI-05 复盘 | EV-02 抽样框与结果标注（四态）、EV-05 回放标签、EV-07 行为层 | FE-05 A3、FE-07 A5 完成度、A1-09；Lite 会话 / 项目 |
| AN-03 / AN-04 | RC-16 工作流模板、RC-06「流程第 3 次」、`process_overhead` | AI-10 诊断输入、AI-08 按任务截取 | EV-03 合成注入（重复链、并行冲突） | FE-05 A3 账本、FE-06 A4-11、FE-07 A5-11；Lite 任务时间轴 / 转移矩阵 |
| AN-05 / AN-06 | RC-02 唯一输入（经 §2.4 映射）、RC-04 分子、RC-11「再积累 N 个会话」 | AI-04.1 候选判定、AI-03 `candidates[]` | EV-02 检测器精度、EV-03 注入用例、EV-07 机械层 | FE-03 A1-10 / A1-16、FE-08 A6-07 / A6-08、FE-06 A4-12 / A4-13；Lite 纠偏率 / 摩擦类型 / 建议依据 |
| AN-07 | 不进推荐触发 | AI-04 歧义消解 | EV-02 情绪标注（v1） | FE-08 A6-06 / A6-11（v1） |
| AN-08 | RC-03 `profile_evidence`、RC-09 匹配特征（不用四字母）、RC-17 交互形式 | AI-05 `narrate.persona`、AI-06 「已有要求」槽位 | EV-10 「不像我」标签率、EV-02 分半信度（v1） | FE-03 A1-21、FE-04 A2、FE-07 A5-08；Lite 协作画像 |
| AN-09 | RC-15 「这次怎么试」证据定位 | AI-03 `deviation`、AI-05 复盘引用 | EV-02 时刻精确率 | FE-05 A3-17 / A3-18；Lite 任务节点 |
| AN-10 | RC-04 `wilson_lo × coverage` | — | EV-01.2 统计函数对照 | FE-20 全站 `n / lo / hi` |
| AN-11 | RC-07 减法（`inventory_fact`）、RC-04 `cost.context_tokens` | AI-06 常驻 token 估算 | EV-07 护栏（`resident_tokens_median` 不升） | FE-06 A4-14、FE-07 A5-12、FE-10 A8-02；Lite 配置覆盖 |
| AN-13 / AN-14 | RC-05 Top N 快照 | AI-05 周报输入 | EV-09 可读性输入 | FE-17 / FE-18 / FE-19（v1）；Lite 导出 |
| AN-16 / AN-17 / AN-18 | 全部 RC 间接依赖；RC-03 `scene_ok / language_ok`；RC-09 簇特征 | AI-08 上下文包、AI-03 `scene`、AI-04.3 簇命名（v1） | EV-01 契约夹具对照、EV-03 `expected.dimensions`、EV-02 主题标注 | FE-20 `coverage / freshness`、FE-04 A2-13、FE-08 A6-09 / A6-10 |

## 9. 与 Demo 的对应

### 9.1 Advance Demo（main `prototypes/advance/src`）由本模块驱动的面板

| 页面 | 条目 | 由哪个 AN 驱动 | Demo 示例逻辑 | 真实实现的差距 |
| --- | --- | --- | --- | --- |
| 全局 | FB-01…FB-06 二级筛选、A1-23 下钻 | §1.2 | 全集重算 | `sessions` 解析成会话集合 → `root_session_uids / selection_id`；`meta.scope` 回显 |
| A1 概览 | A1-12…A1-16 KPI | AN-01、AN-19、AN-05 | `stats()`：时长 = Σdur、自主比 = 工具 × 1.54 ÷ 消息、摩擦率 = 纠偏 ÷ 消息、完成率按 `out` | 自主比 → `autonomy_steps_median`；摩擦率 → `correction_signal_rate`（proxy，带区间）；时长 → `observed_span`（`active_minutes` v1）；完成率 → `completed_rate` + `unknown_n` |
| A1 | A1-06 对比上期 | AN-12 | `prevWin()` 百分比 | v1：`compare_previous` 带差值区间；上期 n < 5「无可比上期」 |
| A1 | A1-09 / A1-10 / A1-11 | AN-06、AN-19 | `countBy(fric)` 取首；文案写死 | `problems_top[]`（证据 = `evidence_session_uids`，跳 A3 用 ID 集合，修 BUG-11 / BUG-27） |
| A1 | A1-17…A1-20 趋势 | AN-12 | `series()` 按 Agent 堆叠 | `metrics?bucket=day&group_by=source`（周桶 v1）；分组以项目 / 模型 × 档位为主 |
| A1 | A1-21 人格卡 | AN-08.2 | `persona()` 常数公式 | `profile.axes / code / experimental`；带 `?` 显示「尚未定型」 |
| A1 | A1-22 / A1-23 热力图 | AN-01 | 会话开始时刻 × 整段消息数 | `human_messages_by_hour × weekday`（消息时刻，`log` 强度）；`correction_rate:h` v1；下钻保留星期（BUG-10） |
| A1 | A1-24 工具 Top 6 | AN-01 | 静态比例 | `tools.by_kind / by_tool` 按 `Scope` |
| A2 协作人格 | A2-01 周期、A2-05…A2-16 | AN-08、AN-18 | 常数公式、45–55 缓冲带、项目参数充当 I / V 轴证据、`fitOf()` | 四轴占比 + Wilson 区间 + `?`；证据行 = 单位计数；删除 A2-14 全体用户与 A2-16 契合度；A2-11 指纹外环用 `sessions[].embedding_x,y`；A2-08「中英混用」= `human_language_mix` |
| A3 会话与轨迹 | A3-02 对比模式 B、A3-06 / A3-08 / A3-11 | AN-02、AN-19、§2.9 `similar_sessions`（v1） | 步数 = 工具 × 1.54；上下文峰值 = 模拟曲线；B 按同项目最近 | `sessions[]` 行；`context_peak_ratio` 无观测不显示（v2）；`outcome` 徽章带 `basis`；B 的相似推荐 v1 |
| A3 | A3-12…A3-18 时间线 | AN-03、AN-09、AN-05 | 精选会话手写，其余随机合成 11 泳道 | 沿用 `ui/vizkit` 组件换数据源（§3.3）；关键时刻 = `key_moments[]`；阶段带与情绪泳道 v1 |
| A3 | A3-19 对比、A3-20 运行中 | AN-02、AN-13 | 固定 1 个运行中 | 对比 = 两个 `sessions/{id}` 并列（PR #32 `compare`）；`realtime` v1 |
| A4 工具调用 | A4-05…A4-10 | AN-01、AN-04 | 比例缩放静态表 | `tools.by_tool / by_kind / by_command_head`，含 `unknown_status_count` 列 |
| A4 | A4-07 / A4-13 审批 | AN-05.2 `would_prompt / permission_denied` | 等待 38 s、212 次写死 | 次数口径（`would_prompt_count:readonly_shell`、`denied_count`）；等待时长只在有 `approval_wait_ms` 时显示 |
| A4 | A4-11 转移矩阵 | AN-04 | `TRANS` 静态 6 × 6 | `transitions` 按 `(name_raw, kind)`，每格带 n，> 20 类归并「其他」；三步链结论句来自 `three_step_chains[0]` |
| A4 | A4-12 失败原因 | AN-04 `by_error_class` | `FAILS` 静态 | 规则按 `error_class`；命名由 AI-04.2（v1） |
| A4 | A4-14 MCP、A4-15 子代理 | AN-11、AN-04 | 静态（figma「常驻 ≈ 2.1k tokens」） | `installed_unused[]`（随 PR #31）、`resident_tokens_median`、`subagent_relations` |
| A5 项目习惯 | A5-05…A5-12 | AN-01、AN-04、AN-08、AN-11、AN-19 | 项目参数手填；回归线；支持度 61% 写死 | `projects[]` 新增列与 `tags`（A5-07）；散点无回归；`workflow_patterns[]` v1；`rule_coverage[]` 随 PR #31（无清单显示「未扫描」） |
| A6 情绪与语义 | A6-01 语言占比 | §2.9 `human_language_mix` | 写死 | 按确认真人消息的 CJK 占比 |
| A6 | A6-06 / A6-07 / A6-11 | AN-07、AN-05 | `mood` 合成；`DRIVERS` 写死 | `mood_series`、`mood_drivers[]` v1（实验性，可关）；A6-07 意图分布 MVP |
| A6 | A6-08 摩擦分类 | AN-05 | 7 类每会话 1 类 | `friction_type_mix`（规则 9 类 + AI 细分，`other` 与 `type_source`） |
| A6 | A6-09 主题 | AN-18 | `TOPICS` 固定 7 类 | 簇 + 「簇 #k · n 个会话」+ 前 5 个 `top_terms`；命名 = AI-04.3 `cluster.topic_names`（v1） |
| A6 | A6-10 高频反馈语 | §2.9 `phrases_top` | 短语写死、出处与短语无关 | `phrases_top[]` 带 `evidence` 出处 |
| A6 | A6-04 仅统计降级 | — | 整页隐藏 | 仅统计模式仍显示 A6-07 / A6-08 / A6-10（规则产物），只隐藏情绪与 AI 细分 |
| A7 / A8 / A9 | A7-08 依据、A8-06 匹配度构成、A9-06 上下文包 | AN-06、AN-08、AN-02 | — | 由 `recommendation.md` / `ai.md` 消费本模块产物 |
| 外壳 | MB-13、POP-03 / POP-09、HUD-02…HUD-05、SIM-01 / SIM-03、A3-20 | AN-13 | `70-sim.js` 模拟 | v1：`realtime` SSE（`failing / stalled / just_finished`，带 `session_uid`） |
| 外壳 | GL-06、NT-04、OB-05 | AN-16 `analysis_run` | `.stale` 类 0.9–1.2 s；固定延时通知 | `GET /v1/analytics/status`（MVP 只有进度；阶段事件 v1） |
| 外壳 | SB-09、REV-01、EXP-04、WG-02、POP-06 / WG-03 / WG-04 / SET-21 | AN-14、AN-12 | 文本模拟 | v1：`report_snapshot(persona_fixed / weekly / share_card / menubar)`、`metrics?bucket=week` |
| 外壳 | SET-20 不计入分析 | AN-16 | 会话从列表消失（BUG-19） | `Scope.excluded_session_uids` + 可恢复列表 |

### 9.2 Lite Demo（main `prototypes/lite/tandem-benchmark-demo.html`，8 页）对应

| Lite 页 | 由哪个 AN 驱动 | Lite 示例逻辑 | 真实替换 |
| --- | --- | --- | --- |
| 概览 | AN-01、AN-08、AN-12、AN-06、§2.5 `by_file_language` | `stats()` 同 Advance；协作时长 = 会话时长之和；本周建议固定三条；语言排行示例 | `overview + metrics(bucket=day) + profile_card + problems_top`；时长 → `observed_span`；工具 / 程序语言排行 → `by_tool / by_file_language`（降级 `top_languages` 标「提及的语言」） |
| 协作画像 | AN-08、AN-18 | `persona()` 常数公式；月度用完整历史 | `profile`（四轴 Wilson 区间）+ `profile?month`（现算）；散点 = `sessions[].embedding_x,y`（文本相似度坐标，不是人格坐标） |
| 会话与轨迹 | AN-02、AN-03、AN-09、AN-19 | 任务时间轴取 `verify` 或 `corr > 1` 的 6 个；详情事件按时长比例合成 | `sessions[]` + `segments(task) / key_moments`；详情轮次账本；结果卡 = `outcome` + `acceptance_results` + 交付反馈 |
| 工具调用 | AN-01、AN-04 | 固定样例矩阵、失败原因；成功率 = 总调用 − 错误 | `tools.by_tool / transitions / by_error_class`；成功率只在已知成功 + 失败中算 |
| 项目分析 | AN-01、AN-19、AN-11 | 完成度 = (完成 + 0.5 部分) / 会话；配置覆盖示例快照 | `projects[]` 的 `outcome_mix`、`rule_coverage`（随 PR #31）；完成度只在 `unknown` 占比低时显示 |
| 情绪与语义 | AN-05、AN-17、AN-18 | 反馈词频、语义兴趣、纠偏类型按会话字段 | `phrases_top`、`text.clusters`（簇 #k + top_terms）、`friction_type_mix`；页面写明「纠偏不等同于负面情绪」；情绪 v1 |
| 优化建议、资源库 | AN-06、AN-08（间接） | 固定建议 + `evidence(r)` 按会话字段计数 | `recommendations` 端点（RC），依据 = `problem.evidence_session_uids` |

### 9.3 示例逻辑与真实实现的共同差距

1. Demo 的会话记录是生成器输出的汇总字段（`msgs / tools / errors / corr / out / verify / mood / topic / fric`），没有事件层；真实实现所有会话级数字来自 L2 / L3 聚合，且带 `coverage / unknown_counts`。
2. Demo 没有「未知」态；真实数据里 `outcome = unknown` 与 `human_origin` 未知会是多数（main 实测 918 / 927 条用户消息来源未知），界面必须按 FE-20 渲染。
3. Demo 的筛选是全集重算；真实实现是 `Scope` + 会话集合 → 端点，上期对比与分组都要同 `Scope`。
4. Demo 的人格、契合度、回归结论、收益百分比都来自常数；真实实现只给占比 + 区间或删除（§2.8、§2.10、§2.11）。`docs/plans/analysis-review.md`「应优先修正的演示口径」与本节一致。

## 10. Demo 还缺什么（本模块侧条目；合并后的前端升级表在 `docs/plans/feature-map.md`）

四份文档的「Demo 还缺什么」合并为 `feature-map.md` 的一张表，按 Lite 页面分组、去重后 P0 ≤ 8 项；本节只保留 AN 侧条目，ID 改为 `UG-AN-xx`，与 RC / EV / AI 重复的条目注明归并目标。「不适用」原因枚举以 `recommendation.md` §3.9 为准。

| ID | 页面 | 改什么 | 为什么 | 依赖后端 | 优先级 | 复杂度 |
| --- | --- | --- | --- | --- | --- | --- |
| UG-AN-01 | 全站（Lite 8 页、A1–A6、侧栏） | 每个数字按 `{value, n, lo, hi, basis, status}` 渲染：n 与区间小字、`insufficient` 显示「数据不足（n）」、`estimated / proxy` 角标；页面顶部一条 `coverage / freshness` 横幅（真人来源未知数、`model_calls` 不可用、`projection_run` 新鲜度、`analysis_run` 进度） | Demo 没有未知态与区间，真实数据多数比例分母很小；没有横幅用户会把 `null` 当 0 | AN-01 `metrics` 响应形状、AN-16 `meta`、AN-10 | P0 | S |
| UG-AN-02 | A1 / Lite 概览 | 「卡在哪」与「本周建议依据」改为 `problems_top[]` 卡：`problem.type`、`sessions / denom` 与下界、`weekly_count`、证据按钮跳 A3 并携带 `session_uid` 集合；「做得好」改为 `verify_pass / completed` 等可数事件 | 文案与证据数来自不同口径（BUG-11、BUG-27）；推荐卡的依据必须与这里同源（= UG-RC-03 的 AN 侧） | AN-06、AN-19 | P0 | S |
| UG-AN-03 | A3 会话与轨迹 | 沿用 `ui/vizkit` 的密度泳道 / 关键时刻簇 / minimap / 回放播放头组件，后端只提供 `GET /v1/analytics/sessions/{id}` 的 `signals / key_moments / tool_sequence`，前端换数据源；保留 8 秒回放、拖动播放头、⌘ / Ctrl 缩放；点击标记打开证据检查器 | 关键时刻与信号是本模块核心产物，Demo 现在是随机合成；用户要求 A3 只做增量修改（USER-OVERRIDES 第 3 条） | AN-05、AN-09、`GET /v1/evidence` | P0 | S |
| UG-AN-04 | A3 / Lite 会话指标条与结果卡 | 「Agent 步数」改为 `autonomy_steps`（按轮次）；「上下文峰值」无观测时不显示；新增 `outcome` 徽章（四态 + `basis`）与验证状态（要求 / 跑了 / 通过 / 候选）；结果卡同时显示用户接受与客观验收，不合成一个成功结论 | 常数 1.54 与模拟曲线不能接真实数据；结果与验证是 A3、A5、A7 共享的事实 | AN-02、AN-19 | P0 | S |
| UG-AN-05 | A4 / Lite 工具调用 | 明细表加「未知状态」列并按 `kind / command_head / mcp_server` 切换；转移矩阵按 `(name_raw, kind)` 从后端取且每格显示 n（> 20 类归并）；审批卡改为次数口径，等待时长只在有端点时显示；失败原因按 `error_class` 分组并可跳转会话；成功率只在已知成功 + 失败中算 | 实测 55.88% 调用状态未知；静态矩阵、38 s、212 次都接不了真实数据 | AN-01、AN-04、AN-05.2 | P0 | M |
| UG-AN-06 | Lite 概览 / A6-01 | 「工具 / 程序语言排行」读 `by_file_language`（文件操作）并与 `top_languages`（提示语提及）分开标注；A6-01 语言占比读 `human_language_mix` | Lite 页面承诺「按涉及语言的文件操作次数排名」，现无对应指标 | §2.5 `by_file_language`、§2.9 `human_language_mix` | P1 | S |
| UG-AN-07 | A2 / Lite 协作画像 | 四轴改为占比条 + Wilson 区间 + 字母 / `?`；证据行显示单位计数（「31 / 84 个轮次 Agent 连续 ≥ 5 步」）与活跃天数；逐月画像读 `profile?month`；删除「全体用户」对照与契合度；「不像我」写 `label`；整页标「实验性」 | 常数公式与 45–55 缓冲带无法解释；区间判定与单位是本模块口径 | AN-08、AN-10、EV-10 `POST /v1/labels` | P1 | M |
| UG-AN-08 | A6 / Lite 情绪与语义 | 摩擦分类改为 `friction_type_mix`（含 `other` 与 `type_source`）；高频反馈语附真实出处（≤ 3 条 `event_uid`）；主题卡显示「簇 #k · n 个会话」+ top_terms；情绪曲线与前因标「实验性」并 v1；仅统计模式下保留摩擦分类与反馈语；页面写明「纠偏不等同于负面情绪」 | 现在的出处与短语无关、每会话一类摩擦、仅统计模式把规则产物也藏掉（= UG-AI-03 的 AN 侧） | AN-05、§2.9 `phrases_top`、AN-18 | P1 | M |
| UG-AN-09 | A5 / Lite 项目 | 项目表加 `identity_quality` 与 `outcome_mix`、`tags`；散点只画点与 n、去掉回归线与结论句；工作流卡 v1 前显示「样本不足」；配置覆盖显示 `inventory_item` 来源与扫描时间，无清单显示「未扫描」；完成度合成分只在 `unknown` 占比 < 50% 显示 | 回归结论在 9 个点上不成立（内部资料 X18）；支持度写死；覆盖手填 | AN-01、AN-11（PR #31）、AN-19 | P1 | M |
| UG-AN-10 | A1 趋势 / 新卡 | 趋势图分组切换：项目 / 模型 × 档位 / Agent（`group_by`）；新增「用量与 token」卡（五个 token 桶、`known_subtotal`、常驻 token 中位数，金额标「API 等价估算」，无价目表显示未知） | 设计 README 已把分组改为项目与模型 × 档位；用量是分析的分母，Demo 没有 | AN-12 `group_by`、AN-01 `token_buckets`、AN-11 `resident_tokens` | P1 | M |
| UG-AN-11 | A1 / A5 对比上期 | 显示上期绝对值、差值与差值区间；上期 n < 5 显示「无可比上期」 | 只显示百分比会放大小样本波动 | AN-12 `compare_previous`（v1） | P2 | S |
| UG-AN-12 | 设置 · 分析 / 侧栏 | 显示 `rules_version / feature_schema_version / projection_run` 与最近 `analysis_run`；「不计入分析」改为可恢复列表（`excluded_session_uids`）；人格阈值说明改为单位与门槛 | 结果可解释与可复现需要版本可见；BUG-19 排除后无法恢复 | AN-16 `meta.versions / freshness`、AN-08 | P2 | S |

## 11. 并入契约第 3 版的条目（[`contract.md`](module-contract.md)）

本节只列本文落实后契约需要同步的改动；四份文档的「对契约的修改建议」统一并入第 3 版，各文档只引编号。

| # | 位置 | 改动 |
| --- | --- | --- |
| C-AN-1 | 页首、§0.1、§2.2 DT 现状、§3.7 | 依据改为 origin/main `6f31203` 与 §0 的路径对照；DT-05 改为「`packages/data` 26 种、`packages/connectors` 25 种（缺 `permission.request`）」；`user_version = 4`（`migrations/004.sql`）；EV-01 改为「`packages/connectors` 35 项」；PR #9 / #11 / #13 / #14 / #16 / #17 / #19 / #24 / #26 / #29 / #30 已合入，现状列的 `分支:` 改为 `main:`；新增 PR #27 / #31 / #32 / #33 为「分支」 |
| C-AN-2 | §2.3 引言 | 八族目录以 main 为准（§5.2 表）；去掉「目录命名以 `MistyHuang03` 的分支为准」与「`common.py` 合成由 … 决定」的措辞；新增 AN-01.1、AN-05.1 / 05.2、AN-08.1 / 08.2、AN-19 |
| C-AN-3 | §3.2b `signal` / `problem` | `signal` 增 `unit ∈ message/turn/task/session`、`problem_type`、`available_at`，MVP 去掉 `severity`、`upstream_signal_id`（v1 再加）；`kind` 闭集按 §2.4（`repeated_tool_failure` 并入 `retry_loop`，删除 `error / workaround`）；`problem.type` 注释「同 friction_type」改为 §2.4 映射表的 12 类，`key` 写全称 `<signal.kind>:<子键>`；`problem` 表去掉 `status` 列，状态改读 `label(target_kind = problem)`；`installed_unused / resident_cost` 不进 `problem`；增 `min_sessions` 按类型 |
| C-AN-4 | §3.4 YAML 示例、`remedy_rule.problem.key` | `key: readonly_shell` 改为 `key: would_prompt:readonly_shell`；`track.*` 的指标名只能取 §2.13 注册表 |
| C-AN-5 | §3.3 `session_facet` | `outcome` 五态经 §2.3 映射表进入 AN-19，`outcome_basis` 增 `facet`；`task_type` 枚举改为 `task-taxonomy-v1` 的 10 类 + `other`，增 `domain`；增 `key_moments[]`（`deviation` 来源） |
| C-AN-6 | §3.2a `metrics` 枚举 | `human_chars_per_turn` 统一命名；`verify_rate` 拆为 `verify_ran_rate / verify_pass_rate`；`consecutive_failed_calls / confirmed_same_argument_failed_retries` 标为 main 别名，正式名 `retry_loop_count`；增 §2.13 全部追踪指标、`by_file_language`、`human_language_mix`、`correction_session_rate`；`group_by ⊆ {project, model_effort, source, task_type}` 多键 |
| C-AN-7 | §3.1 `Scope` | 增 `selection_id`（二级筛选解析结果，§1.2）；`source_ids` 统一（PR #27 `agent_ids` 合并时改名） |
| C-AN-8 | §3.2b `segment / work_block` | 阶段 `label` 加 `unknown`；`work_block` 加 `human_message_count`、`agent_sequence`、`agent_switch_count`；`profile_history` 表移到 v1 |
| C-AN-9 | §5.3 端点 | 「现有」加 `instruction`、`bottleneck`、`tasks`、`preferences`、`recommendations`（PR #26）；按 §5.2「端点合并」写明保留 / 并入 / 退役；新增 `GET /v1/analytics/status`（SSE）、`sessions?query&offset&limit`、`profile?month` |
| C-AN-10 | §2.1 状态列 | 写入 §0.10 的 MVP 判定规则，并据此重标四份文档 |
| C-AN-11 | §6 owner 表 | 按 §7：AN-04、AN-05.2、AN-19、AN-08.2、AN-01.1（presentation）→ `genius-FXC` / `MistyHuang03`；AN-13 → `yhyfhgs` / `MistyHuang03`；其余 AN 留 `MistyHuang03`；删除所有「由用户确认 / 需用户确认」措辞 |
| C-AN-12 | §3.0、§1 时间规则 | canonical 以 `turn.status` 为准，`features.STATES` 的 `turn.interrupted` 映射只对 legacy 生效；`read_analysis()` 截止后状态置 `unknown` 的语义写进 analysis-input-v1 |
| C-AN-13 | §2.2 DT-05 / DA §4.6 | 上下文观测补充约定（`model.usage.attrs.context{used_tokens, window_tokens, source}`），先核对可得性（V-A9） |
| C-AN-14 | §2.2 DT-09 / DT-13 | DT-09 现状改为 PR #31；DT-13 词表增破坏性命令族（`risky_command` 与 `destructive_allowed_count` 共用） |
| C-AN-15 | §7 | 并入 §12 的 V-A 编号与「阻塞 MVP」标记 |

## 12. 待验证（只引契约 §7 编号；V-A 为本文新增，随 C-AN-15 并入）

阻塞 MVP 的三项：**V11**（`human_origin` 覆盖）、**V4**（性能，冷算 ≤ 10 s）、**V12**（`permission_mode` 与 `permission.request`）。

| # | 假设 | 验证方式 | 相关 |
| --- | --- | --- | --- |
| V1 | 问题升级阈值 `min_sessions`（§2.4 按类型）∧ `wilson_lo ≥ 0.05` 在三位成员本机数据上既不漏也不吵 | AN-06 跑真实 `tandem.db`，人工看前 20 条 | AN-06 |
| V2 | 四轴单位门槛 `n_units ≥ 30 ∧ 活跃天 ≥ 10` 下 Wilson 区间宽度多数 ≤ 20 个百分点；D 轴阈值 `autonomy_steps ≥ 5` 不是全 0 或全 1；M 轴判定线 50% | 本机数据跑 `profile` | AN-08.2 |
| V3 | 中文纠偏 / 挫败词表精度 ≥ 0.5；agentsview 阈值改按字符后召回可接受 | 每人 30 条命中标注（EV-02 MVP 口径） | AN-05.1 |
| V4 | 10 万事件 / 90 天窗口查询现算冷算 ≤ 10 s、热查询 ≤ 1 s；`read_analysis(max_events = 100000)` 够一个窗口 | 原型计时；会话行物化与 section 缓存已提前启用（审计 §3.3） | AN-16、AN-01 |
| V11 | canonical 接入后 `human_origin` 覆盖从 legacy 的 9 / 927 显著提升（≥ 50%）；否则所有语义指标继续「数据不足」 | AN-16 完成后重跑同一快照 | AN-16 |
| V12 | `session.meta.attrs.permission_mode` 是否进 L2（Claude Code mapper）；Codex 侧没有 `permission.request` 时 `would_prompt` 只能按词表估计 | 读两个 Schema 与 mapper | AN-05.2 |
| V-A2 | 阶段规则在 50 个真实会话上与人工边界一致率 ≥ 70%（v1） | EV-02 标注抽样 | AN-03 |
| V-A7 | `extract_validation_runs()` 在 canonical 数据上的识别率：Codex `exec` 包装下 `status_scope` 与 `command_head` 能否识别内层命令；否则 `verify_ran` 只能标 partial | 对 `packages/connectors` / `packages/data` 真实样本抽查 | AN-19、DT-13 |
| V-A9 | 上下文观测可得性：Claude Code 累计 `usage` 能否换算窗口占用；pi `usage`、Codex `rate_limits` 是否含窗口大小 | 读 `docs/research/agent-sessions/*.md` 并抽样 | AN-02、AN-05.2、AN-13 |
| V-A10 | 显式反馈 + 验证通过 + facet + 结构四层下 `outcome ≠ unknown` 的会话占比；若 < 30%，完成率类指标在 MVP 只在会话详情显示，不进概览 | 真实快照统计 | AN-19 |
| V-A11 | `duplicate_prompt` 用 `message_digest` 精确匹配的召回是否足够；3-gram 近似是否需要（v1） | 本机真人消息抽样 | AN-05.2 |
| V-A12 | `cache_rebill` 的 TTL（5 分钟 / 1 小时）按 `service_tier` 在各 Agent 的 `model_call` 上可判定（v1） | `packages/data` `model_call` 样本 | AN-11 |
| V-A13 | `human_language_mix` 的 CJK 占比阈值；`task_type → benchmark_task_class` 映射在 EV-02 标注集上的准确率 | 本机标注 | §2.9、EV-08 |
| V-A14 | PR #27 与 PR #32 组合层合并后的字段差集可在一周内收敛；`FEATURE_VERSION` 与组合层版本分离不影响 `analysis_digest` 唯一性 | 合并 PR 时核对 | AN-01.1 |

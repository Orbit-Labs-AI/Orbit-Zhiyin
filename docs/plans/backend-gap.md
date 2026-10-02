# 数据与分析模块对照 UI 的后端缺口

2026-10-02。核对基线：main `4ffa506`，并计入本文所在分支的 [PR #35](https://github.com/ActionMesh-AI/Hackathon/pull/35) 索引式数据与原文轨迹实现（含 PR #28 后端结构迁移、PR #29 独立资源目录包、PR #30 分析补全建议），安装清单已随 PR #31 进入 main；UI 依据 Advance 原型（`prototypes/advance/src/js/` 与 `docs/design/visual-cases-v1/` 画板）和 Lite 原型（`prototypes/lite/tandem-benchmark-demo.html`、`docs/design/lite-review.md`）。下文源码路径按 main 的目录布局书写。

本文回答一个问题：**要让两版 UI 的每个页面和按钮接上真实数据与真实动作，数据模块和分析模块还差什么，另外还需要哪些后端程序。** 八个分析族各自的功能缺口已写在 [analysis-review.md](analysis-review.md)，本文不重复逐族展开，只在页面与横切能力里引用；数据获取的目标方案见 [data-acquisition.md](data-acquisition.md)，统计口径见 [analysis-inputs.md](../contracts/analysis-inputs.md)。

缺口编号：`G-D` 数据模块，`G-A` 分析模块，`G-R` 推荐与资源，`G-B` 横切后端程序。状态用语：**已有**（源码已实现，不代表真实日志覆盖充分或已验收）、**可派生**（原始字段已在库里，缺聚合或接口）、**部分**（有基础但口径或形状不符）、**缺失**（未见实现）。

## 0. 结论

1. **数据底座已经能支撑大多数"事实类"数字。** 7 个 Agent（Claude Code、Codex、DSH、pi、Hermes、OpenCode、Kimi）可离线导入 L0–L3，`tool_call` 有耗时、退出码、错误类别、审批等待，`model_call` 有五类 token，会话有子代理层级、压缩事件和按轮归属的真人文本。概览、工具、项目三页的大部分数字属于"可派生"：字段在库里，缺按 UI 形状聚合的接口。
2. **最大的阻塞项是语义标注层（G-A2）。** UI 会话对象里的 `corr`、`fric`、`mood`、`topic`、`title`、`verify`、`out`，以及轨迹里的阶段、关键时刻、情绪泳道，都需要逐条打标。分析模块已经在消费 `attrs.interaction`、`attrs.acceptance`，但数据层和分析层都没有任何代码产出这些标注，真实数据上纠偏、验收基本是 unknown；摩擦率、自主比、人格、情绪页、关键时刻都卡在这里。
3. **原生记录轨迹已具备，但 UI 的语义泳道与"人格"仍缺失。** `profiling/trajectory.py` 是"原回复 → 改写 → 评价"的修改链审计，不是泳道时间轴；`profiling/portrait.py` 统计的是 8 类明确要求，不是四轴 16 型人格。`/v1/sessions/{id}/trajectory` 已提供完整原生记录索引；阶段、关键时刻、泳道聚合与人格仍需实现（G-A4、G-A5），不能把原生轨迹接口等同于 UI 的完整时间轴。
4. **会写入或调用外部的能力几乎为零。** 写回 Agent 配置、备份与撤销、7 天效果追踪、实时监听与推送、LLM 调用（AI 解读、问本地 Agent、生成工坊）、全文搜索接口、CSV 与分享卡导出、用户设置与纠错的持久化，在后端都还没有实现（G-B）。
5. **资源目录有了引擎，缺内容和接线。** `packages/catalog` 已有采集、版本、FTS 和本地向量检索，但默认不联网同步，内置种子只有 10 条 skill；推荐引擎读取的 7 个 family 目录 JSON 全为空；推荐卡片也缺 UI 需要的难度、受众、diff、目标路径、教程和追踪指标（G-R）。
6. **按 Lite 优先补齐的最短路径**是：G-A2 规则版标注 → G-A1 统计接口 → G-A3 会话结果 → G-A4 轨迹接口 → G-A5 人格 → G-R1 资源内容 → G-B8 搜索 → G-B9 导出。Advance 在此之上再补实时、安装闭环、效果追踪、LLM 执行层与生成工坊。

## 1. 现有底座

### 1.1 数据模块（`packages/data`、`packages/connectors`）

| 能力 | 现状 |
| --- | --- |
| 会话导入 | 7 个 connector（`tandem_data/connectors/`）。来源目录只读，`--home` 不能放在来源目录内 |
| 存储 | L0 来源位置 / 版本 / 哈希索引（原生扫描不复制整份 session，旧归档兼容）→ L1 逐行记账（mapped / folded / replayed / duplicate / ignored / unparsed）→ L2 `event`（过 JSON Schema 校验）→ L3 `session / turn / tool_call / model_call / usage_snapshot / link / session_feature`。迁移在 `migrations/`，`user_version = 6` |
| 增量 | Python 端按文件 stat 跳过；文件变了流式更新索引，L1 复用未变的行，L2/L3 按来源重建；归档移动 / 压缩替换按哈希保留记录身份，来源删除时保留已发布事实并标明缺口；`ImportService.watch` 是 2 秒轮询。TS 端只有 Codex，支持真正的 offset/inode 增量和 `fs.watch` 递归监听，经 `import-connector` 桥接进统一库 |
| 安装清单 | `inventory/`（PR #31，已进 main）：skill / mcp / hook / plugin / rule / scheduled_task 六类，10 种目录布局；只存名称、路径、哈希与可空的 enabled，不存命令、env、正文 |
| 脱敏 | `privacy.py`：密钥字段、认证头、私钥、常见 token 前缀、URL 凭据；L2 正文和字段不再按长度截断。原文留在来源，通过位置 / 主键与哈希校验按需读取 |
| 对外接口 | `read_analysis(home, AnalysisScope)` 返回 `analysis-input-v1`；`event_page` 按 seq 游标分页；`trajectory_page` 返回含未知 / 忽略 / 重放记录的完整轨迹，`record_source` 打开原文；`tandem-data export` 导出 11 张表或视图 |

### 1.2 分析模块（`packages/backend`）

| 能力 | 现状 |
| --- | --- |
| 两条链路 | 旧链路 `profiling/analysis.py`（画像、瓶颈、修改链审计、旧推荐）供 `report` / `demo` / `/v1/analysis`；新链路 `analytics/service.py::analyze_bundle`（八族特征 + 多路召回推荐）供 `/v1/analytics/*` |
| 八族特征 | Task、Instruction、Preference、Interaction、Respond、Cost-Time、Outcome、Subjective Outcome，全部是规则或确定性计算，带 coverage 与 unknown 计数，详见 [analysis-review.md](analysis-review.md) |
| 文本表示 | 字符 n-gram TF-IDF → SVD → DBSCAN 聚类 + PCA 二维坐标 + 新颖度 |
| 瓶颈 | 新链路 7 条规则（纠偏密度、重复要求、相同重试、工具失败、验证失败、验收证据缺口、上下文压力）；旧链路 4 类候选加 3 类数据缺口 |
| 推荐 | 规则 / BM25 / 效果向量 / 上下文四路召回 → RRF → 启发式打分 → MMR；卡片带证据与 `effect_status = unmeasured` |
| 接口 | `/v1/analytics/{overview,bottleneck,sessions,sessions/{id},tools,projects,instruction,text,tasks,preferences,recommendations}`，旧接口 `/v1/{projects,sessions,sessions/{id}/events,analysis,catalog,evidence/{id},evaluation}`，以及 `/v1/catalog/*`。全部同步计算、无缓存 |
| LLM | 无任何模型调用；`reporting/narrative.py` 是模板叙述 |

### 1.3 资源目录（`packages/catalog`）

独立的 `catalog.db`：来源同步与 checkpoint、资源版本、能力特征、正文分块、FTS5、本地 multilingual-e5-small 向量、RRF 与 MMR 混合检索；`/v1/catalog/{status,sources,sync,embeddings,jobs,search,items/detail}` 与 `/v1/catalog/match-analysis`；附 Swift 客户端 `packages/catalog-macos`。默认不联网、不下载模型，同步须显式触发。

## 2. UI 对后端的隐含数据契约

原型的示例数据（Advance `prototypes/advance/src/js/05-data.js`、`15-derive.js`，Lite 内联数据）是 UI 对后端的隐含契约。下表逐字段对照当前来源。

### 2.1 会话对象

| UI 字段 | 含义 | 当前来源 | 状态 |
| --- | --- | --- | --- |
| `id`、`d`、`h`、`mi` | 会话标识、日期、开始时刻 | `session.session_uid`、`started_at` | 已有 |
| `dur` | 时长（分钟） | `session` 跨度；Cost-Time 的可靠执行区间并集 | 部分：需在 UI 上区分"跨度"和"执行时长" |
| `a` | Agent | `source.agent` | 已有 |
| `p` | 项目 | `project.project_id`（git remote / git root / path） | 已有；A5 的"按文件夹"合并视图缺失 |
| `msgs` | 用户消息数 | `v_human_message` | 已有 |
| `tools`、`errors` | 工具调用数、失败数 | `tool_call`，`status = failed` | 已有；状态 unknown 需单列 |
| `corr` | 纠偏数 | Interaction 只认已确认标注，词面命中只算候选 | **缺失**：无标注生产者（G-A2） |
| `tok` | tokens | `model_call` 五桶、`usage_snapshot` | 已有；Hermes 只有累计快照 |
| `out` | ok / part / fail / live | `session.status` 只取最后一个 `turn.end`，从不为 active | **缺失**（G-A3） |
| `verify` | 是否要求或运行验证 | Outcome 从 `command_head` 推断验证运行；Instruction 抽取验证要求 | 部分 |
| `mood` | 会话情绪 −1 到 1 | 无；`outcome_subjective` 明确不做情绪 | **缺失**（G-A2、G-A8） |
| `topic` | 主题 | Task 的 domain / task_type 标签、文本聚类 | 部分：簇没有可读名称 |
| `fric` | 主摩擦类型 | 无 | **缺失**（G-A2） |
| `title` | 会话标题 | `session.title`（仅部分 Agent 原生提供，如 Claude `custom-title.json`） | 部分：无原生标题的会话需生成 |
| `live` | 运行中 | 无 | **缺失**（G-D1、G-B7） |
| Lite `toolMetrics[{name,n,errors,seconds}]` | 每会话工具指标 | `tool_call` 聚合 | 可派生 |
| Lite `languages` | 编程语言 | `tool_call.files` 的扩展名 | 可派生；须与提示语里提到的扩展名分开 |
| Lite `phrases` | 8 个反馈语计数 | Subjective Outcome 的短句规则、`profiling/feedback.py` 的信号 | 部分 |
| Lite `end` | 最后聊天时间 | 最后一条 `message.user` 的 `ts` | 可派生 |

### 2.2 轨迹 `traj(s)`

Advance 的轨迹返回 `{T, ev, phases, ctx, moments, users}`，事件分 11 条泳道。

| 泳道或字段 | 当前来源 | 状态 |
| --- | --- | --- |
| `user`、`reply` | `message.user`、`message.assistant`，按 `turn_uid` 归轮 | 已有 |
| `read`、`edit`、`bash`、`web`、`sub` | `tool_call.kind`（Codex 的 CommandExecution / FileChange / WebSearch / MCP；Claude 按工具名）、子代理 `session.parent_uid` | 部分：缺跨 Agent 的工具名 → 泳道映射表（G-D8） |
| `ev[].cmd`、`res`、`err`、`w` | `tool_call.command_head`、`exit_code`、完整结果文本、`error_class`、`duration_*` | 已有 |
| `phase`、`phases` | 无 | **缺失**（G-A4） |
| `moment`、`moments` | 无 | **缺失**（G-A4） |
| `ctx` 上下文占比曲线 | 只有 `context.compaction` 事件；占用与窗口大小未入库 | **缺失**（G-D2） |
| `mood`、`users[].情绪分` | 无 | **缺失**（G-A8） |
| `users[].是否纠偏` | 无 | **缺失**（G-A2） |

### 2.3 工具聚合

| UI 数据 | 当前来源 | 状态 |
| --- | --- | --- |
| `TOOLS`：调用数、错误率、平均耗时、需审批比例、典型命令 | `tool_call`、`approval_wait_ms`、`command_head` | 可派生 |
| `TRANS`：P(下一个工具 \| 当前工具) | Respond 的转移图是事件状态转移，不是工具名转移 | 部分（G-A6） |
| `FAILS`：失败原因聚类 | `error_class`、退出码、完整输出 | 部分：缺按退出码与输出文本的聚类 |
| `WAITS`：审批等待分桶 | `approval_wait_ms`（请求与处理端点齐全时） | 可派生 |
| MCP 调用数与常驻 tokens | 调用数可从 `tool_call.mcp_server` 得出；工具 schema 常驻开销未采集 | 部分（G-D7） |
| 子代理派发数、最大并行、并行 ≥ 4 时被停止比例 | Respond 的并行区间；子代理终止状态 | 部分 |

### 2.4 人格

| UI 数据 | 当前来源 | 状态 |
| --- | --- | --- |
| 四轴 `v{D,I,M,V}`、`code`、16 型名称、`conf` | 无 | **缺失**（G-A5） |
| 判型门槛（30 会话、项目级 8 会话、45–55 显示"?"） | 无 | **缺失** |
| 各轴证据：每会话消息数、单轮自主步数、规划型项目时长占比、日均会话、同日 Agent 数、验证率 | 消息数、日均会话、同日 Agent 数可派生；单轮自主步数有雏形（`portrait.interaction.recorded_steps_per_request`）；规划型项目与验证率依赖 Task / Instruction / Outcome | 部分 |
| 月度演变 | 无 `profile_history` | **缺失** |
| 人群均值 `POP`、Agent 契合度 | 无数据来源 | 按 §8 默认口径不做 |

### 2.5 建议 `RECS` 与资源库 `LIB`

| UI 字段 | 当前来源 | 状态 |
| --- | --- | --- |
| `title`、`why`、`ev`（证据会话数） | 推荐卡片 `explanation`、`evidence` | 已有 |
| `evq` 证据下钻条件（fric / topic / project / tool） | 证据是事件或会话 ID 列表 | 部分：缺"下钻到筛选条件"的映射 |
| `dim`（7 类）、`lvl`（L1–L4）、`aud`（新手 / 进阶 / 专家） | 无 | **缺失**（G-R3） |
| `gain` 预计收益 | 无；`effect_status = unmeasured` | **缺失** |
| `compat`、`primary`、`target` | 资源有兼容 Agent 字段；写入路径与动作无 | 部分（G-B5） |
| `file` diff 行（`+` / `-` / `ai` / 不变） | 无 | **缺失**（G-B5） |
| `steps` 教程、`track[名称, 前, 后, 单位]` | `evaluation_plan` 只描述计划 | **缺失**（G-B6） |
| `LIB.m` 匹配度 = 行为相似 ×0.5 + 痛点覆盖 ×0.3 + 社区效果 ×0.2 | 召回与打分有分项，但不是这三项 | 部分（G-R6） |
| `LIB.src` 来源与许可、`desc` | `catalog_item`、`item_version` 的许可 | 已有（需同步内容） |
| `LIB.users`、`peer` 社区安装量、同型用户占比 | 无 | 按 §8 默认口径不做 |
| 已安装与"Tandem 安装 / 手动安装"区分 | 安装清单只有观测，没有安装台账 | 部分（G-D6、G-B5） |

## 3. 按页面的差距

### 3.1 两版共有页面

| 页面 | UI 需要 | 后端现状 | 缺口 |
| --- | --- | --- | --- |
| **概览** | 指标卡（会话、时长、消息、自主比、摩擦率 / Lite 纠偏率）+ 12 周火花线 + 与上一等长周期的差值；各 Agent 趋势（会话 / 时长 / Tokens 可切换，可切表格）；周 × 小时热力图（Advance 消息与纠偏，Lite 协作分钟数）并下钻；工具 Top 6；AI 解读；本周 3 条建议 | `/v1/analytics/overview`；Cost-Time 只有按日、按小时活动 | G-A1 统计接口（分组、分桶、环比、下钻成员）；G-A2 纠偏标注；自主比口径替换原型的"工具 ×1.54 ÷ 消息"；G-B2 AI 解读（无 LLM 时用 `narrative.py` 模板） |
| **协作人格 / 画像** | Advance：四轴 16 型、月度演变、证据、优势与盲点 → 建议、反馈"不像我"；Lite：每会话散点、6–9 月逐月画像（不受顶部时间筛选截断）、8 个趣味标签 | `portrait.py` 只有 8 类明确要求的计数与 Wilson 区间，`stability = unverified` | G-A5 四轴与历史；G-B10 "不像我"反馈存储；Lite 散点须用行为轴，不能直接套文本聚类坐标 |
| **会话与轨迹** | 列表（搜索、按天分组、最后聊天时间排序、工具密度条码、运行中实时时长）；7 项指标；泳道时间轴（时间 / 步数轴、缩放、回放、关键时刻跳转）；A/B 对比；在 Agent 中继续、在 Finder 中显示、复制 ID；启示与"不准确"反馈；Lite 关键任务时间轴与 4 个抽象任务节点 | `/v1/sessions`、`/v1/sessions/{id}/events`、`/v1/sessions/{id}/trajectory`、`/v1/records/{id}/source`、`/v1/analytics/sessions/{id}` | G-A4 轨迹接口；G-A3 结果判定；G-D2 上下文曲线；G-D4 标题；G-B8 会话搜索；G-B12 resume 命令与日志路径；G-D1 运行中追加事件；日志损坏的缺口标注可用 L1 `unparsed` 与 `ingest_issue` 派生 |
| **工具调用** | 明细（调用、错误率、平均耗时、审批比例、30 天趋势、只看失败、展开最近 20 次调用）；4 张汇总卡；转移矩阵（Lite 按行归一化）；失败原因；审批等待分布与只读命令白名单；闲置 MCP；子代理并行度 | `/v1/analytics/tools` 有工具汇总；原始字段齐全 | G-A6 工具页聚合；G-D7 MCP 常驻开销；白名单生成需要只读命令前缀表 |
| **项目分析** | 项目表（会话、时长、Agent 构成、项目级人格）；跨项目回归（自主比 × 摩擦率，面积 = 时长，输出 b、a、r、n 与残差）；本项目与整体 6 项对比；高频工作流（支持度 40%）；配置覆盖；Lite 完成度 × Tokens 散点 | `/v1/analytics/projects` 按项目聚合 | G-A7 回归、对比、序列挖掘、完成度分布；G-D6 安装清单按项目关联；"按文件夹"合并 |
| **情绪与语义** | Advance：语言占比、逐条情绪曲线（置信度 ≥ 0.6、按消息加权）、摩擦分类（可改判）、主题与平均情绪、高频反馈语（同义归并与出处）、情绪前因；"仅统计"模式下整页关闭。Lite：反馈语计数、主题、摩擦类型占比，没有情绪曲线 | Subjective Outcome 有明确接受 / 拒绝 / 返工；Preference / Instruction 有明确要求抽取 | G-A8 整页；G-A2 摩擦标注；G-B10 改判存储 |
| **优化建议** | 7 维度、L1–L4、受众筛选；说明 / diff 预览（全局或项目范围，可同时转为 Codex）/ 教程 / 效果追踪四个标签；证据下钻；"不适用"降权；撤销；重新计算；深度诊断 | `/v1/analytics/recommendations` 有卡片、证据和评估计划 | G-R1 资源内容；G-R3 卡片字段；G-R5 反馈降权；G-B5 安装；G-B6 追踪；G-B2 深度诊断 |
| **资源库** | 为你推荐 / 同类型用户在用 / 热门 / 本地生成四个标签；类型筛选与搜索；"不感兴趣"；已安装清单（区分 Tandem 安装与手动安装）；第三方资源的文件清单、权限、许可与沙盒试运行；新版本提示 | `/v1/catalog/search`、`items/detail`；安装清单在分支上 | G-R1、G-R2、G-R4、G-R7、G-R8；"本地生成"依赖 G-B4 |

### 3.2 Advance 独有的页面、浮层与流程

| 部分 | UI 需要 | 缺口 |
| --- | --- | --- |
| **A9 生成工坊** | 5 类产物（Skill、Hook、规则、子代理、工作流）；上下文包逐项勾选与 token 估算；选择本机 Agent 与模型；预览要发送的 JSON；六步流程（打包 → 分析 → 流式起草 → 自检 → 3 个历史会话回放测试 → 审阅）；可停止并保留草稿；自检（结构、与已装内容重名、危险命令、回放）；安装、在编辑器中打开、存入资源库；历史产物与流程模板 | 全部缺失：G-B4，依赖 G-B2、G-D6、G-B5 |
| **安装闭环** | 预览 diff（逐行取消）→ 确认写入（自动备份，可选同时写 `~/.codex/config.toml`）→ 10 秒撤销 → 从备份恢复；可移除配置项（如删除某个 MCP）；目标路径包括 `settings.json`、`agents/*.md`、`mcp.json`、`plugins/*/plugin.json`、`skills/*/SKILL.md`、`AGENTS.md` | 全部缺失：G-B5 |
| **7 天效果追踪** | 同批项目安装前后各 7 天对比；会话数相差超过 30% 标"样本不足"；第 7 天通知"保留 / 撤销"；无效时询问原因并回流资源匹配度 | 全部缺失：G-B6 |
| **菜单栏面板** | 暂停 / 需要关注 / 空闲（昨日摘要）/ 运行中 / 等你确认五种状态；近 7 天柱；最值得做的一条建议 | G-B7 实时；G-A1 日序列 |
| **悬浮组件 HUD** | 5 种收起态；本地规则触发的教练提示；暂停提醒 30 分钟 | G-B7；提示规则需要实时信号 |
| **桌面小组件** | 人格、今日、本周（环比、摩擦率）、首条建议；"只显示数字" | G-A1、G-A5、G-R；小组件读的是缓存快照（G-B1） |
| **实时事件** | 会话完成（超过 10 分钟的）；等你确认（识别审批命令，等待超过 5 分钟才升级通知，Tandem 不代批）；同一命令连续失败并推断原因（如 401 居多提示 token 过期）；上下文 60% / 80%；每周报告生成；发现新数据源；额度中断；同一会话 10 分钟内多条事件合并 | G-D1、G-D2、G-D3、G-D16、G-B7 |
| **运行中会话面板** | 当前工具、近 20 分钟"你 / 工具 / 错误"三条泳道、上下文百分比、工具 / 错误 / 消息数 | G-D1、G-D2、G-B7 |
| **命令面板** | 全局搜索页面、项目、会话（标题和项目名）、建议、操作 | G-B8 |
| **问本地 Agent** | 按 5 种上下文给预置问题；把当前筛选与统计打包；流式回答；引用会话可跳转；可转交生成工坊 | G-B3，依赖 G-B2 |
| **导出与分享** | Markdown 报告（5 个可选章节）；工具 CSV（tool, calls, error_rate, failures, avg_duration, approval_rate）；1080×1350 分享卡（深 / 浅色、隐藏数字、二维码、分享文案）；导出全部 JSON | G-B9 |
| **首次启动** | 自动检测各来源与会话数；首次只索引最近 90 天（目标约 40 秒）；统计 → 轨迹 → 语义 → 人格渐进出结果；关窗后台继续并通知；人格揭晓 | G-B11 |
| **设置六分区** | 见 §6 G-B10 | G-B10、G-D11、G-D12、G-D13 |

### 3.3 Lite 的差异

Lite 去掉了生成工坊、桌面小组件、悬浮组件、首次启动、人格揭晓、会话回放与对比、通知模拟；保留全局搜索、浅深色、筛选、同步入口、导出与分享。因此 Lite 不需要 G-B3、G-B4、G-B6、G-B7、G-B11，也不需要 G-D1 的实时部分。Lite 额外需要：

| Lite 需要 | 缺口 |
| --- | --- |
| 协作分钟数热力图：按会话覆盖时段逐分钟累加 | G-A1 需要支持"时段覆盖"型分桶，不只是事件计数 |
| 完成度 =（完成 + 0.5 × 部分完成）÷ 会话数 | 依赖 G-A3；按 analysis-review 的建议改为展示验收与反馈的状态分布 |
| 建议证据 reason：friction、errors、git、design、verify、tokens（单会话超过 1M）、parallel（时间重叠）、duration（超过 60 分钟） | errors、git、tokens、parallel、duration 可派生；friction、design、verify 依赖 G-A2 |
| 会话 CSV（11 列）与 SVG 分享卡 | G-B9 |
| 筛选状态写入 URL | 前端自理；后端只需 Scope 可序列化（G-B1） |
| 安装 / 撤销按目标 Agent 记录，以 `rec:target` 为键 | 按 §8 默认口径，Lite 不写配置，只提供复制内容与打开目标文件 |

## 4. 数据模块缺口（G-D）

| 编号 | 缺口 | 现状与依据 | 服务的 UI | 做法 |
| --- | --- | --- | --- | --- |
| G-D1 | 实时增量与运行状态 | Python 端只有 2 秒轮询、整文件重新归档；`session.status` 从不为 active；data-acquisition §3.3 规划的 `sessions/<pid>.json`、`thread-writer-locks`、`session.lock` 读取未实现。只有 TS Codex 有真正的增量与文件监听 | Advance 运行中会话、菜单栏、HUD、通知；会话列表实时时长 | 把 TS 端的 offset / generation 增量和 FSEvents 监听推广到 Python connector（至少 Claude Code、Codex）；新增运行状态判定（进程 / 锁文件 / 最近事件时间）；对外提供"自某水位以来的新事件"接口 |
| G-D2 | 上下文观测 | 只有 `context.compaction` 事件；上下文占用与窗口大小未入库（analysis-inputs §4.6 要求的观测表缺失）；`model_context_window` 只有 TS 端读取 | 轨迹 ctx 曲线、上下文峰值指标、60% / 80% 提醒、Cost-Time 的上下文状态 | 每次 `model_call` 记录输入 token 与模型窗口（来自原生字段或模型规格表），派生占比；无来源时为 null |
| G-D3 | 审批请求的完整事件 | 契约有 `permission.*`，各 connector 产出程度不一；`approval_wait_ms` 只在请求与处理端点齐全时有值 | 等你确认、审批等待分布、只读命令白名单 | 逐 Agent 核对审批请求能否从日志实时读出，读不出的标注为不支持，而不是 0 |
| G-D4 | 会话标题 | `session.title` 只在部分 Agent 原生提供 | 会话列表、搜索、命令面板 | 原生标题优先，其次取首条真人消息摘要，LLM 生成标题作为可选增强（G-A2） |
| G-D5 | 来源覆盖 | 无 Gemini CLI、Cursor、Antigravity、Copilot connector；Claude 桌面版会话索引 `claude-code-sessions/local_*.json`、workflow journal、`tool-results/` 未读；Codex 的 `state_5.sqlite` 只能走 TS staging | 设置·数据源、资源库已安装扫描（UI 写了 `~/.gemini`）、"发现新数据源"通知 | 先补 UI 已出现的 Gemini 与 Cursor；其余按 data-acquisition §8.1 的顺序 |
| G-D6 | 安装清单进 main 并补类型 | 安装清单仍在 `feat/local-inventory`；不扫 Claude `agents/`、`commands/`、`known_marketplaces.json`、`permissions`；没有 agent / command 类型；没有"由 Tandem 安装"的标记 | 资源库已安装清单、项目配置覆盖、推荐已装过滤、生成工坊重名自检 | 合入 main；补 agent、command 类型；与 G-B5 的安装台账关联，区分 Tandem 安装与手动安装；按项目路径关联到 `project` |
| G-D7 | MCP 常驻开销 | MCP 调用可统计，但工具 schema 的常驻 token 未采集 | 工具页"闲置 MCP"、已装未用 | 从会话初始化记录或配置读取 MCP 工具清单与描述长度，估算常驻 token，并标注为估算 |
| G-D8 | 名称归一 | `model_alias` 表一直为空；没有跨 Agent 的工具名映射 | 设置·工具名映射表、轨迹泳道分类、工具页跨 Agent 合并 | 内置工具名 → 类别（read / edit / bash / web / sub / mcp）映射，用户覆盖存入 G-D10；模型别名同理 |
| G-D9 | 全文搜索接口 | `event_fts`（FTS5）与触发器已建，但没有任何 MATCH 查询，CLI 与服务也没有搜索入口 | 命令面板、会话搜索、反馈语出处 | 在 `query.py` 增加按 Scope 过滤的 FTS 查询与高亮片段，供 G-B8 使用 |
| G-D10 | 用户状态存储 | canonical 库是只读派生；排除的会话、停用的来源、标签改判、"不像我 / 不准确 / 不适用 / 不感兴趣"反馈、名称映射覆盖都无处存放 | 全局排除与恢复、设置、所有纠错入口 | 新建独立可写的应用状态库（与 `tandem.db` 分开，重建不丢）；分析读取时合并 |
| G-D11 | 自定义来源 | 只有 7 个固定 connector | 设置·自定义来源（JSONL、SQLite、Markdown，沙盒下用安全书签授权） | 通用导入器：字段映射配置 → L2 事件；先做 JSONL |
| G-D12 | 可配置脱敏 | `privacy.py` 规则固定；原生采集只保存索引，表内脱敏，显式原文访问不脱敏；旧归档仍兼容 | 设置·隐私（6 类规则开关、自定义正则、样例测试命中） | 规则可配置并版本化，变更后触发 L2 重建；UI 区分"分析表已脱敏"与"显式打开未脱敏来源"；保持新原生采集不复制整份 session |
| G-D13 | 数据管理 | 有表级导出；没有存储占用统计、清除全部数据、导出全部 JSON | 设置·隐私 | 在服务层提供占用统计、带确认词的清除、全量 JSON 导出 |
| G-D14 | 首次索引优先级 | 导入不区分时间，只有进度回调 | 首次启动"先索引最近 90 天，约 40 秒" | 导入支持按文件修改时间倒序与时间窗口，先近后远；进度按阶段上报 |
| G-D15 | 逐次成本 | Claude Code、Codex 的逐次请求没有成本；只有原生上报的 cost | 设计本身不显示金额 | 不建价目表（§8）；保留原生 cost 作附加信息 |
| G-D16 | 额度窗口 | Codex `rate_limits` 在导入时被丢弃 | 菜单栏"额度中断"提醒 | 保留 `rate_limits` 快照到 `usage_snapshot` 或单独观测；其他 Agent 无来源时不显示 |

## 5. 分析模块缺口（G-A）

逐族的细项见 [analysis-review.md](analysis-review.md)；这里按 UI 需要的交付物归并。

| 编号 | 缺口 | 现状 | 服务的 UI | 做法要点 |
| --- | --- | --- | --- | --- |
| G-A1 | 统计接口 | `overview` 只有总量；Cost-Time 只有按日、按小时 | 概览指标卡与火花线、趋势、热力图、菜单栏 7 天柱、小组件、Lite 协作分钟数 | 一个接口支持 `metric × group_by(agent / project / model) × bucket(day / week / month / weekday×hour)`，返回 `n / value / 区间 / 上期值`；每个格子可回查成员会话；分母与单位随结果返回 |
| G-A2 | 语义标注层 | Interaction、Outcome 等待 `attrs.interaction`、`attrs.acceptance`，无生产者；纠偏只有词面候选 | 纠偏、摩擦、情绪、主题名、标题、verify、关键时刻、启示 | 先做规则版：纠偏、摩擦类型、验证要求、反馈语都以"规则候选"产出并带证据；LLM 版作为可选增强（逐会话 facet：目标、任务类型、结果、摩擦类型、摘要），结果带来源标签 `rule / model / user`，用户改判优先；标注写入分析侧存储，不改 canonical 库 |
| G-A3 | 会话结果判定 | 无 `out`；`task_success` 恒为 null | 会话结果、Lite 完成度、Agent 对比、建议证据 | 结合轮次状态、验证结果、用户接受 / 拒绝 / 放弃信号，输出 ok / part / fail / unknown / live，并附判定依据 |
| G-A4 | 语义轨迹接口 | 原生 `trajectory_page` 和原文索引已实现；`profiling/trajectory.py` 仍是修改链审计，未做语义泳道 | 两版会话页时间轴、Lite 任务节点、A/B 对比、关键时刻跳转、回放 | 新接口返回：按泳道分组的事件（时间轴与步数轴两种坐标）、阶段带（调研 / 规划 / 实现 / 验证 / 调试 / 交付）、关键时刻（目标、偏离、纠偏、连续失败、验证通过、放弃）、上下文曲线、用户消息与标注；Lite 的 4 个任务节点由阶段聚合得到；对比用同一坐标规则 |
| G-A5 | 四轴人格与历史 | `portrait.py` 只有要求计数 | Advance A2、Lite 画像、小组件、首次启动揭晓、分享卡 | 四轴各自由行为事实计算并带区间（按天 bootstrap），不满足门槛时该位显示"?"；全局与项目级共用；按月快照，每个月只用当时可见的数据；输出优势、盲点及对应建议 ID |
| G-A6 | 工具页聚合 | 有工具汇总与事件状态转移 | 工具明细、转移矩阵、失败原因、审批等待、白名单、闲置 MCP、子代理并行 | 工具名转移矩阵（含样本数，Lite 行归一化）；按退出码与输出文本的失败聚类；审批等待分桶；从只读命令前缀生成白名单候选；已装未用（G-D6 × 调用记录）；并行度分布与被停止比例 |
| G-A7 | 项目分析 | 只有按项目聚合与 `cross_project_candidate` 标记 | 跨项目回归、6 项对比、工作流、配置覆盖、Lite 完成度散点 | 最小二乘回归（b、a、r、n、残差）；项目 vs 整体同口径对比；高频动作序列挖掘（支持度阈值可调，列出支持会话）；配置覆盖读 G-D6；验收与反馈状态分布 |
| G-A8 | 情绪与语义 | 无情绪；主题无名称 | Advance A6 整页、轨迹情绪泳道、Lite 主题与反馈语 | 自然语言占比（中 / 英 / 混合）；逐条情绪分与置信度（实验性，置信度低于 0.6 不计入）；主题命名与平均情绪；反馈语同义归并与出处；情绪前因只给关联强度与样本量，不写成因果 |
| G-A9 | 链路合并、缓存与性能 | 新旧两条链路并存；每个页面请求都重跑完整分析 | 所有页面；筛选一改全部重算 | 旧报告改为消费新链路结果；按页面只计算所需族；结果按"数据版本 + 全部规则版本 + 完整 Scope"缓存，物化会话级结果 |
| G-A10 | 叙述与启示 | `narrative.py` 是模板叙述 | 概览 AI 解读、会话启示、建议说明 | 模板版作为默认与降级；LLM 版经 G-B2，界面标注生成时间与来源 |
| G-A11 | 周报与快照 | 只有 CLI 写 Markdown / JSON | 每周报告（周一 09:00）、报告导出 | 报告快照入库，带数据版本；定时生成由 G-B11 的后台调度触发 |

## 6. 推荐与资源缺口（G-R）

| 编号 | 缺口 | 现状 | 做法 |
| --- | --- | --- | --- |
| G-R1 | 资源内容 | 推荐读取的 7 个 family 目录 JSON 全为空；实际候选只有 7 条旧种子；`catalog` 内置种子 10 条 skill，同步须显式触发 | 选定首批公开来源并完成一次同步，入库可追溯的说明、许可与适用条件；为 7 条瓶颈规则各准备至少一组可用候选 |
| G-R2 | 推荐与资源目录接通 | 推荐引擎读 family JSON；`/v1/catalog/match-analysis` 已能用分析结果查 `catalog.db`，但两者分开 | 推荐的召回改为从 `catalog.db` 取候选，family JSON 只保留人工审核的补充 |
| G-R3 | 卡片字段 | 无 UI 的 7 个维度、L1–L4、受众、预计收益、教程、目标路径 | 维度与难度由资源元数据和问题类型映射；收益在追踪前只给定性描述；教程来自资源正文或模板 |
| G-R4 | 已装过滤与已装未用 | `installed_resources` 由请求方传入 | 直接读 G-D6；已装未用结合调用记录 |
| G-R5 | 曝光与反馈 | 无"不适用 / 不感兴趣"记录与降权 | 曝光与反馈存 G-D10，同类候选降权，可在设置中恢复 |
| G-R6 | 匹配度构成 | 打分有分项，与 UI 的三项不对应 | 按 §8 默认口径：行为相似与痛点覆盖两项，权重 0.6 / 0.4；分项随卡片返回 |
| G-R7 | 新版本提示 | `catalog` 有资源版本，但无已装版本对比 | 安装台账记录装入版本，对比最新版本 |
| G-R8 | 第三方资源安全 | `catalog` 有许可判断；无文件清单、权限摘要与试运行 | 安装前展示文件清单、涉及的命令与权限、许可；脚本类资源的沙盒试运行放到 Advance 后续 |

## 7. 横切后端程序缺口（G-B）

| 编号 | 程序 | 现状 | 需要做什么 | 版本 |
| --- | --- | --- | --- | --- |
| G-B1 | 面向 App 的服务层 | `tandem serve` 启动 127.0.0.1:8765；端点按模块分散，旧新接口并存；无缓存；Scope 缺来源 / Agent 多选、主题、结果、摩擦、开始小时筛选 | 统一版本化接口与错误格式；Scope 补齐 UI 的全部筛选维度与手动排除；页面形状的聚合端点；快照接口供小组件和菜单栏读取；桌面 App 负责服务启停（module-map 中的未来 `apps/desktop`） | 两版 |
| G-B2 | LLM 执行层 | 无 | 引擎三档：仅统计 / 本机 Agent headless / Ollama；固定输入与闭集输出、缓存键、预算封顶、`FakeEngine` 测试替身；所有 AI 文案可降级为模板 | Advance；Lite 可只用"仅统计" |
| G-B3 | 问本地 Agent | 无 | 按当前 Scope 打包统计与证据 → 流式回答 → 回答中的会话引用可跳转 → 转交生成工坊 | Advance |
| G-B4 | 生成工坊 | 无 | 产物模板（Skill / Hook / 规则 / 子代理 / 工作流），模型只填有类型的槽位；上下文包与 token 估算；流式起草、可停止并保留草稿；自检（结构、与已装重名、危险命令扫描、用 3 个历史会话回放）；产物历史与"存入资源库" | Advance |
| G-B5 | 安装、备份与撤销 | 数据模块按只读设计，无写回 | 安装计划（每个 Agent 的目标路径与格式）；diff 预览与逐行取消；写入前备份、原子写入；10 秒撤销与从备份恢复；移除配置项；跨 Agent 转换（如同时写入 Codex）；安装台账（时间、版本、目标、追踪天数） | Advance 真实写入；Lite 只复制内容与打开目标文件 |
| G-B6 | 效果追踪 | 无 | 安装前后各 7 天、同批项目对比 `track` 指标；会话数相差超过 30% 标"样本不足"；第 7 天通知"保留 / 撤销"；无效原因回流推荐 | Advance |
| G-B7 | 实时检测与推送 | 无推送通道 | 检测器：会话完成、等待确认（超过 5 分钟升级）、连续失败与原因推断、上下文 60% / 80%、周报生成、新数据源、额度中断；同一会话 10 分钟内合并；SSE 推送给菜单栏、HUD、小组件；通知矩阵（5 类事件 × 横幅 / 悬浮组件 / 菜单栏角标）、暂停全部、测试通知 | Advance |
| G-B8 | 全局搜索 | 无 | 基于 G-D9 搜索会话、项目、建议、操作，结果带类型与跳转目标 | 两版 |
| G-B9 | 导出 | 只有 CLI 写 Markdown / JSON | Markdown 报告（可选章节）、工具 CSV、会话 CSV、分享卡（Advance PNG 1080×1350，Lite SVG）、导出全部 JSON；导出数字与页面同源（同一 Scope 与数据版本） | 两版 |
| G-B10 | 设置与持久化 | 无 | 六分区：通用（外观、悬浮组件、小组件、登录启动、默认时间范围）；数据源（检测到的 Agent、版本、状态、最后同步、启用开关、自定义来源、工具名映射、索引方式、暂停采集、立即重新索引）；隐私（脱敏规则、存储位置与占用、导出、清除）；分析（引擎与执行者、人格规则说明、已排除会话、每周报告）；通知（投递矩阵）；关于。全部存 G-D10 | 两版（Lite 取子集） |
| G-B11 | 首次启动与后台调度 | 无 | 来源检测与会话计数；90 天优先索引；统计 → 轨迹 → 语义 → 人格分阶段完成并上报进度；关窗后台继续、完成后通知；索引方式（FSEvents 实时 / 每小时 / 手动，低电量降级）；周报定时 | Advance（Lite 只需同步入口与进度） |
| G-B12 | 系统动作所需数据 | `record_source` 已提供经校验的原文路径 / 主键 / 字节范围；没有 resume 命令接口 | 基于已有原文索引补充会话入口与项目路径、各 Agent 的 resume 与非交互调用命令模板；打开终端、Finder、编辑器由 App 执行 | 两版 |

## 8. 本文采用的默认口径

1. **人格**：采用 UI 的四轴 16 型，每轴由行为事实计算并给区间；门槛不足时显示"?"而不是猜测。不做"与全体用户对比"和 Agent 契合度评分，改为按 Agent 并排展示行为事实。四轴字母以 UI 的 D / I / M / V 为准，规划文档中的旧字母随之统一。
2. **语义标注**：规则优先，LLM 增强。默认"仅统计"也能出纠偏、摩擦、反馈语的规则候选；情绪曲线与主题命名需要开启 LLM，未开启时 A6 情绪部分关闭并说明原因。所有标注带来源标签，用户改判优先。
3. **社区与人群数据**：本轮不做。资源匹配度去掉"社区效果"项，按行为相似 0.6、痛点覆盖 0.4 计算；资源库隐藏"同类型用户在用"，"热门"改为按公开来源的星标或下载量排序；默认不上传任何数据。
4. **成本**：界面只显示 token。有原生 cost 的 Agent 可附带显示，但不建价目表、不估算金额。
5. **Lite 的安装**：Lite 不写 Agent 配置，提供"复制内容"与"打开目标文件"；真实写入、备份、撤销与 7 天追踪只在 Advance 实现。
6. **情绪与情绪前因**：标为实验性；前因只展示关联强度和样本量，不写成因果结论。

## 9. 补齐顺序

依赖关系：G-D10 应用状态库是一切纠错与设置的前提；G-A2 标注是纠偏、摩擦、结果、人格、情绪、关键时刻的前提；G-D6 安装清单是推荐已装过滤、生成工坊自检、安装闭环的前提；G-B2 LLM 执行层是 AI 解读、问 Agent、生成工坊、情绪的前提。

| 阶段 | 内容 | 让哪些页面可用 |
| --- | --- | --- |
| **P0：Lite 主链** | G-A9 链路合并与缓存；G-B1 Scope 补齐；G-A1 统计接口；G-A2 规则版标注；G-A3 结果判定；G-A4 轨迹接口（不含上下文曲线）；G-A5 四轴人格与月度历史；G-D4 标题；G-D10 应用状态库 | Lite 概览、画像、会话、工具（基础）、项目（基础）；Advance A1–A3 的事实部分 |
| **P1：Lite 补全** | G-A6 工具页聚合；G-A7 项目分析；G-D6 安装清单进 main；G-R1–G-R6 资源与推荐；G-D9 + G-B8 搜索；G-B9 导出；G-B10 设置子集；G-B12 系统动作数据；G-D8 名称映射 | Lite 全部八页；Advance A4、A5、A7、A8 的只读部分 |
| **P2：Advance 实时与闭环** | G-D1 实时增量与运行状态；G-D2 上下文观测；G-D3 审批事件；G-D16 额度；G-B7 实时检测与推送；G-B5 安装与撤销；G-B6 效果追踪；G-B11 首次启动与后台调度 | 菜单栏、HUD、小组件、通知、安装闭环、首次启动、轨迹上下文曲线 |
| **P3：Advance AI** | G-B2 LLM 执行层；G-A2 LLM 版标注；G-A8 情绪与主题命名；G-A10 AI 叙述；G-B3 问本地 Agent；G-B4 生成工坊；G-R8 沙盒试运行；G-D5、G-D11、G-D12 来源与隐私扩展 | A6 情绪、A9 生成工坊、问 Agent、AI 解读与深度诊断 |

## 10. 原型中需要替换的写死数字

接真实数据时，这些值不能沿用，必须由后端给出口径并计算，没有数据时显示未知或空状态：

| 位置 | 写死的值 | 后端来源 |
| --- | --- | --- |
| Advance `15-derive.js` | 自主比 = 工具 × 1.54 ÷ 消息 | G-A5 的单轮自主步数 |
| Advance `05-data.js` 项目 | `q`、`h`、`A`、`fr`、`err` 与人格先验 `I`、`V` | G-A1、G-A5、G-A7 |
| Advance `05-data.js` 工具 | `TOOLS` 的平均耗时与需审批比例、`TRANS`、`FAILS`、`WAITS` | G-A6 |
| Advance `43-a4-tools.js` | 审批平均等待 38 秒、212 次只读命令、并行 ≥ 4 时 40% 被停止、"命令占 77%" | G-A6 |
| Advance `41-a2-persona.js` | 人群均值 `POP` | 按 §8 去掉 |
| Advance `47-a8-library.js` | 1,240 位同型匿名用户、`users`、`peer` | 按 §8 去掉 |
| Advance `05-data.js` 建议 | `track` 前后数值、`gain` | G-B6；追踪前只给定性描述 |
| Advance `05-data.js` 语义 | `PHRASES`、`DRIVERS`、`QUOTES` | G-A8 |
| Lite | 语言排行为模拟特征；工具成功率用"总调用减错误"推算；对话轮数用消息数代替；完成度部分完成固定计 0.5 | G-A6、G-A3；轮数取 `turn` |

## 11. 核对依据

- 数据模块：`packages/data/src/tandem_data/`（`connectors/`、`store.py`、`pipeline.py`、`reduce.py`、`analysis_input.py`、`service.py`、`query.py`、`privacy.py`、`migrations/`）、`packages/connectors/src/`（`ingest.ts`、`watch.ts`、`normalize.ts`）；安装清单 `inventory/` 以 `feat/local-inventory` 为准。
- 分析模块：`packages/backend/src/tandem_backend/`（`analytics/`、`profiling/`、`recommend/`、`reporting/`、`api/routes.py`、`data_access/store.py`）；资源目录 `packages/catalog/src/tandem_catalog/`。
- UI：Advance `prototypes/advance/src/js/05-data.js`、`15-derive.js`、`40`–`48` 各页、`50`–`57` 浮层与流程、`60`–`62` 菜单栏 / HUD / 小组件、`70-sim.js`，以及 v1 画板标注；Lite `prototypes/lite/tandem-benchmark-demo.html` 与 `docs/design/lite-review.md`。
- 关键结论的复核：全仓库没有模型调用；`event_fts` 只有建表与触发器，没有查询；数据包中没有 `attrs.interaction` 与 `attrs.acceptance` 的生产者；推荐的 7 个 family 目录 JSON 条目数均为 0；`tandem demo` 能跑通导入 → 画像 → 瓶颈 → 推荐。

本文只做静态核对与差距梳理，没有修改代码或原型，也没有运行完整测试套件。

# Orbit 竞品分析

> 状态：调研 · 维护者 `yhyfhgs` · 核对版本 main `0c96334` · 适用：Advance / Lite（另注明处除外）

> 日期：2026-10-02｜读者：`yhyfhgs`、`MistyHuang03`、`genius-FXC` 与路演评审｜范围：以 Advanced 为主，Lite 的边界见 §5.3
>
> **依据与核实**：2026-10-02 完成的竞品调研，覆盖 7 类、约 60 个产品与开源项目。外部事实就地附链接，**核实日期均为 2026-10-02**（另注者除外）；GitHub stars、最近推送与发版时间是当日 `gh api` 读数。只有二手来源的事实标「未核实」；需要真实数据或实测才能定的技术假设标「待验证」。
>
> **与其他文档的分工**：主流 Agent 的内置功能与扩展点、开源项目的源码级研读见 [research.md](landscape.md) §2、§4，本文只引结论；Orbit 各模块的做法见 [analysis.md](../plans/analysis-module.md)、[recommendation.md](../plans/recommendation-module.md)、[ai.md](../plans/ai-module.md)、[evaluation.md](../plans/evaluation-module.md)，功能与分工映射见 [feature-map.md](../plans/feature-map.md)。
>
> **Orbit「现状」的口径**（2026-10-02 各分支）：
> - main `c97c818`：后端 v0.13.6 + Feature Analytics（`src/tandem_backend/`），只读 Codex，没有 LLM 调用和安装器；
> - PR #9 `feat/session-data-contract`：`packages/data`，`tandem-session-v1` 契约，6 个 connector（Claude Code、Codex、dsh、Hermes、OpenCode、pi），L0–L3；
> - PR #11 `feat/codex-connector`：`packages/connectors`，Codex 增量 connector、L0 zstd 归档、watch；
> - Advanced Demo：`prototypes/advance/`（main，示例数据）；Lite Demo：`prototypes/advance/tandem-benchmark-demo.html`（`genius-FXC` 的分支 `feat/genius-FXC-dev`，8 页，示例数据，尚未开 PR）。

## 0. 结论先行

### 0.1 定位

**一句话：Orbit 是开发者自己的、在本机运行的跨 Agent 协作教练——用你已有的会话证据指出卡在哪里、该装什么，可撤销地装好，7 天后告诉你有没有用。**

- 路演短句：「官方报告告诉你哪里不顺；Orbit 跨 Agent 找到证据、一键改好，再用数据回看有没有用。」
- English：*Orbit is your local, cross-agent coach: evidence from your own sessions, reversible fixes, and a 7-day check on whether they helped.*

**没有竞品覆盖整条链。** 在「跨 Agent × 零配置读本机历史 × 确定性诊断 → 多类别优化项 → 预览 / 撤销安装 → 装后对照」这条链上，各家只占一两段（矩阵见 §3）：Claude Code 官方和 Devin 只看自家；SpecStory Lore 能把跨 Agent 历史炼成 skill 并装好，但不诊断、不追踪；agentsview 能在本机长期归档并分析 60+ 种 Agent，但不安装；Faros 做浪费分类与回放验证，卖给企业。报告、浏览、记录、记忆、skill 生成、市场排行这些单点能力都已免费或开源，**Orbit 的价值只能来自闭环，以及「装了有没有用」的证据。**

### 0.2 三个差异化

单看第 1 条，agentsview 已经很接近；护城河在三条连成一条链，尤其是第 3 条积累下来的效果证据。

| # | 差异化 | 竞品做不到的证据 | Orbit 怎么做到 | 现状 |
| --- | --- | --- | --- | --- |
| 1 | **同一个人、跨 Agent 的诊断**：打开即分析本机已有的几个月历史，用同一把尺子比较你在 Claude Code、Codex、dsh、pi 等里的协作，每个结论都能点回原事件 | 官方洞察只看自家 Agent，Claude Code 默认 30 天清理会话与 `/insights` 报告；可观测平台与 Entire 从装 hook 或启用那刻起才采集；agentsview 能跨 Agent 浏览并长期归档，但诊断止于规则文本，不连到安装与效果 | connector + L0 原始归档 + 确定性指标 + 证据回链 | main 只读 Codex，已有 `/v1/evidence/{id}`；PR #9 六个 connector 与 L0–L3；PR #11 Codex 增量归档；跨 Agent 对比为计划 |
| 2 | **从证据到可撤销改动的全类别闭环**：7 类优化项（规则与 Prompt、Skills、Hooks、插件与 MCP、子代理、模型与思考强度、工作流），预览 diff → 确认 → 按 Agent 渲染写入 → 单条撤销 | `/doctor` 只改 Claude Code 配置，未见统一撤销；Codex Memories 自动生效；Lore 只产 skill，批准后写入，没有一键撤销；skills.sh 只管装卸，没有 diff 预览，也不看用户数据 | 问题驱动的机制决策表 + 模板渲染 + 安装 ledger | main 的推荐只覆盖 4 个 skill（`status=trial`、`effect_status=unmeasured`）；安装器为计划；两个 Demo 都是模拟安装 |
| 3 | **装后效果对照**：装上的东西有没有被触发、目标摩擦有没有减少，带样本数、区间与混杂说明 | 没有竞品对个人做「装前 vs 装后」：`claude plugin eval` 是面向插件作者的装前对照；Devin Coach 只统计采纳率；Faros 与 Copilot 影响看板是组织级 ROI；Lore 的 outcome lift 比的是主题与个人基线 | 推荐时预登记目标与护栏指标；三层效果（触发 / 机械 / 行为），主指标是目标摩擦的复现率 | 计划；Demo 的 7 天对照卡是示例数据 |

### 0.3 必须达到的门槛

任何一条做不到，评审会直接拿现成产品比下去。

| 门槛 | 谁已做到 | 验收标准 | 现状 |
| --- | --- | --- | --- |
| 解析正确 | agentsview 支持表 66 项；ccusage 的去重与计价规则；Lore 以 fixture 为规格 | 每个 Agent 有 fixture 测试；同一份数据上 token 汇总与 ccusage 对齐（容差待验证）；不认识的格式标「预览」，不静默丢弃 | PR #9 有契约、边界与流水线测试；PR #11 有 legacy 与分页 fixture；main 有构造数据的链路回归 |
| 首次结果快 | `/insights` 一条命令；agentsview 本机 SQLite 增量同步 | 首次打开先出概览并显示解析进度，之后按水位增量 | PR #11 有增量 ingest 与 watch；首屏时长待验证 |
| 不靠 LLM 也有结论 | agentsview 规则检测；Lore 确定性计数；Hermes `/insights` 纯 SQL 聚合 | 指标、摩擦、画像全部确定性计算；AI 只做命名、短候选判定与叙述，可以关闭 | main 已满足：规则 + Wilson 区间 + TF-IDF / SVD / DBSCAN，没有 LLM 调用 |
| 隐私看得见 | Raycast Wrapped 数据只在本机；Cursor 设备端分类；Arize 的记录开关；Lore 机械脱敏 | 默认不出机；交给本机 Agent 的内容先预览、先脱敏，并如实写明它会经该 Agent 发往其服务商；分享卡不含路径、项目名与原文 | main 只读导入、`redact()` 脱敏、数据放 `.local/`，只有 `catalog-refresh` 联网；Lite 分享卡只含汇总 |
| 建议有证据、不重复官方 | Devin 问题时间线；Lore 证据档案；Claude 插件提示频控 | 每条建议附会话链接、次数与原话；标注并去重 `/insights`、`/doctor` 已给过的建议；频控与「不再提示」 | main 的推荐要求画像与瓶颈证据同时成立，带证据 ID；去重与频控为计划 |
| 安装安全可逆 | skills.sh 审计、Anthropic verified、Glama TDQS；Hermes ledger 单条回滚 | 只装有来源的条目；预览 diff 与权限；一键撤销恢复原文件；保留用户已有内容 | 计划（两个 Demo 为模拟） |
| 效果口径可信 | Faros、Copilot 影响看板、Raindrop 实验、`claude plugin eval` | 至少一个结果指标 + 同类任务前后对比 + 混杂说明；样本不足写「数据不足」；不写提速百分比 | 计划；后端已统一标 `effect_status=unmeasured` |
| 原生 Mac 质感 | agent-sessions、Raycast | 按 [research.md](landscape.md) §3.5 的 HIG 数值落地 | Demo 为 HTML 原型 |

### 0.4 最大威胁与对策

| 威胁 | 证据（核实 2026-10-02，出处见 §2） | 可能性 / 影响 | 对策 | 落点 | 代价（复杂度 / token） |
| --- | --- | --- | --- | --- | --- |
| **T1 官方下沉** | Claude Code：`/insights` 报告摩擦与建议，`/doctor` 先报告后改配置，`/usage` 按扩展归因，按会话信号推荐插件，`plugin eval` 做有 / 无对照。Codex：Memories 合并阶段可写 `SKILL.md`，Computer History 建议生成 skill，`tool_suggest` 中途推荐插件，`/import` 导入 Claude Code 配置与近 30 天会话。Devin：Session Insights + Coach。Hermes 内置复盘、curator 与 ledger | 高 / 高 | ① 不做单 Agent 叙述报告，也不叫「Insights」；② 官方产物当输入：只读 `~/.claude/usage-data/` 的 session-meta 结构，作派生指标的对照与冷启动；③ 官方功能当一等零安装推荐项（auto mode、`/fewer-permission-prompts`、`/doctor`、Codex memories），推荐前探测版本；④ 与官方已给的建议去重；⑤ 跨 Agent 写入做双向、键级 diff、可回滚，与官方单向 `/import` 区分；⑥ 路演第一分钟正面对比 | 推荐知识库与去重（MVP）；读取 usage-data（v1，待验证）；路演 | 低：只读结构字段与版本探测，0 token；去重靠规则表 |
| **T2 SpecStory Lore** | 开源（Apache-2.0）；读 7 种 Agent 的历史；beat + 用户回复当结果标签；确定性计数 + 对抗验证者；批准后写 `~/.agents/skills` 并软链到各 Agent | 高 / 中 | ① 不以「会生成 skill」为卖点；② 覆盖 skill 以外的 6 类；③ 先诊断，给可视化证据；④ 装后对照；⑤ 照搬它的四个工程决定（§2.5） | 推荐决策表、AI 生成的四道自检、装后效果（MVP） | 中：决策表 + 模板 + 四道自检；生成调用的 token 预算见 [ai.md](../plans/ai-module.md) |
| **T3 开源浏览器追平** | agentsview：60+ 种 Agent、本机长期归档、friction 检测、健康分、Quality 卡，2026-09 连发 v0.42–v0.44 | 高 / 中 | 不在「能看会话」上竞争；把它的检测器（MIT）移植为规则 v0 并中文化；差异放在闭环 | 分析的摩擦检测（MVP） | 中：移植检测器并补中文词表、重标阈值，0 token |
| **T4 记忆产品内置化** | claude-mem 95.2k★；Codex Memories；Hermes 复盘写记忆与 skill | 中 / 中 | 不做记忆；把记忆类插件记为效果追踪的混杂因素；读它们的产物作补充数据源（经授权、只读，待验证） | 效果追踪的混杂记录（MVP）；补充数据源（v1） | 低：记录同期安装清单，0 token |
| **T5 供应链安全** | 31,132 个 skill 中 26.1% 至少有一处漏洞，带脚本的是纯指令型的 2.12 倍；Snyk 扫描 3,984 个，13.4% 严重、76 个恶意（二手转述，未逐字核实） | 中 / 高 | 只装有来源的条目；装前展示 diff 与权限；静态扫描；一键撤销；不自动运行 skill 自带的脚本 | 安装的风险闸门（MVP） | 中：静态扫描 + diff 预览 + ledger，0 token |
| **T6 评审第一反应「官方已经有了」** | `/insights` 所有套餐可用、不另收费（消耗用户自己的额度） | 高 / 高 | 开场 30 秒脚本 + 三个只有 Orbit 能演示的时刻（§5.1） | 路演 | 低：脚本与标注清楚的演示数据 |

## 1. 竞品分类全景

### 1.1 七类竞品

| 类别 | 代表产品（2026-10 状态） | 它回答的问题 · 买方 | 与 Orbit 的关系 | 威胁 | Orbit 的处理 |
| --- | --- | --- | --- | --- | --- |
| **Agent 自带洞察** | Claude Code `/insights`、`/usage`、`/doctor`、插件推荐与 `plugin eval`；Codex Memories、Computer History、`tool_suggest`、Usage Insights；Devin Session Insights + Coach；Hermes `/insights` + curator；Cursor、GitHub Copilot 团队分析；Gemini CLI `/stats`（未核实） | 「你在我这个 Agent 里用得怎么样」· 个人与管理员，随订阅 | 最直接的对手，也是输入与推荐项 | 高 | 不做单 Agent 报告；做跨 Agent、可撤销、装后对照 |
| **开发者效能分析** | DX（Atlassian，2026 Gartner DPIP 魔力象限 Leader）、Jellyfish、LinearB、Faros AI（Token Intelligence）、Swarmia、WakaTime、Weave | 「AI 工具值不值得买，团队产出变了没有」· VP Eng、平台与财务 | 买方不同；借结果口径与价格锚 | 低 | 只服务个人，不给经理排名 |
| **LLM / Agent 可观测性** | Langfuse（2026-01 并入 ClickHouse）、LangSmith（Insights）、Braintrust（Loop）、Arize Phoenix / AX（Alyx）、W&B Weave、Raindrop；Helicone 并入 Mintlify 后进入维护模式 | 「我做的 AI 应用在生产里表现如何」· 做 Agent 的团队 | 兼容，不竞争：它们靠 hook，从安装那刻起采集 | 低 | v1 提供 OTel / OpenInference 导出；借「逐条摘要 → 聚类」与「沮丧 / 卡在循环」信号 |
| **会话记录与知识管理** | SpecStory + Lore、Entire（种子轮 6000 万美元）、claude-mem（95.2k★）、Pieces、git-ai / Agent Trace、vibe-log（2026-04 后无推送） | 「把历史存下来、搜得到、炼成资产」· 个人与团队 | Lore 是最接近的对手；其余是数据源或混杂因素 | Lore 高，其余中低 | 见 §0.4 T2、T4 |
| **生态市场与推荐** | 官方 MCP Registry（不排序，排序交给下游）、Smithery（2026-08 并入 Arcade.dev）、Glama（TDQS 质量分）、PulseMCP（暂停新提交）、Claude 插件目录、Cursor Marketplace、Codex 插件目录、skills.sh、SkillsMP、claude-code-templates、awesome 列表 | 「有什么可以装，什么最流行」· 所有 Agent 用户 | 通道与先验，不是对手 | 低（skills.sh 的跨 Agent 安装与审计是相邻能力） | 用它们的 ID、审计结果与安装通道；按个人问题重新排序；不自建市场 |
| **开源用量 / 会话工具** | agentsview（66 项支持表）、claude-code-history-viewer、cass、agent-sessions、ccusage（18.8k★）、tokscale（58 个客户端）、CodexBar、cc-switch（139k★）；sniffly、opcode 已停更或放缓 | 「看会话、算 token 与成本、管配置」· 个人开发者 | 参照与对账基准；agentsview、cc-switch 是相邻产品 | 中 | 移植检测器（MIT）；ccusage 作成本对账；用量只做分析的分母，不做额度监控与切号 |
| **人格化报告** | Spotify Wrapped（2022 年 16 型、2024 年 AI 内容翻车、2025 年回归数据）、Your Year with ChatGPT、Cursor Year in Code（使用量百分位）、WakaTime / Raycast Wrapped、社区的 Claude Code Wrapped、16Personalities | 「我是什么类型，值不值得晒」· 个人，靠传播 | 传播样板 | 低 | 维度可解释、数字上卡、设样本门槛、不编百分位；独有的「装后前后对照卡」 |

来源（核实 2026-10-02；已有卡片的产品见 §2）：[Hermes curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator)、[Hermes `/insights`（源码，纯 SQL 聚合）](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/agent/insights.py#L85)、[Gemini Code Assist 监控](https://docs.cloud.google.com/gemini/docs/monitor-gemini)（`/stats` 子命令只见于[第三方教程](https://wpreset.com/how-to-check-gemini-cli-and-api-usage/)，未核实）；[Jellyfish Claude Code 看板](https://jellyfish.co/platform/claude-code-dashboard/)、[LinearB 定价](https://linearb.io/pricing)、[Swarmia 定价](https://www.swarmia.com/pricing/)、Weave（[A 轮报道](https://runtimewire.com/article/weave-raises-13-5-million-measure-ai-coding-roi)，未核实）；[Braintrust 定价](https://www.braintrust.dev/pricing)、[Phoenix × Claude Code](https://arize.com/docs/phoenix/integrations/coding-agents/claude-code)、[Weave × Claude Code](https://docs.wandb.ai/weave/guides/integrations/claude_code)、[Mintlify 收购 Helicone](https://mintlify.com/blog/mintlify-acquires-helicone)；[Pieces 定价](https://pieces.app/pricing)、[git-ai](https://github.com/git-ai-project/git-ai)、[Agent Trace](https://agent-trace.dev/)、[vibe-log](https://github.com/vibe-log/vibe-log-cli)；[MCP Registry](https://github.com/modelcontextprotocol/registry)（[排序交给下游 registry 的设计](https://github.com/modelcontextprotocol/registry/blob/main/docs/design/ecosystem-vision.md)）、[Smithery joins Arcade](https://arcade.dev/blog/smithery-joins-arcade)、[Glama TDQS](https://github.com/glama-ai/tool-definition-quality-score)、[PulseMCP](https://www.pulsemcp.com/servers)、[Claude 插件目录](https://claude.com/plugins)、[Cursor 2.5](https://cursor.com/changelog/2-5)、[Codex 插件](https://learn.chatgpt.com/docs/plugins)、[SkillsMP](https://skillsmp.com/about)；[claude-code-history-viewer](https://github.com/jhlee0409/claude-code-history-viewer)、[cass](https://github.com/Dicklesworthstone/coding_agent_session_search)、[agent-sessions](https://github.com/jazzyalex/agent-sessions)、[ccusage](https://github.com/ccusage/ccusage)、[tokscale](https://github.com/junhoyeo/tokscale)、[CodexBar](https://github.com/steipete/CodexBar)、[sniffly](https://github.com/chiphuyen/sniffly)（最近推送 2025-08-08）、[opcode](https://github.com/winfunc/opcode)（2025-10 之后只有一次 README 修改）；[WakaTime 2025 Wrapped](https://wakatime.com/blog/70-wakatime-2025-wrapped)、[16Personalities](https://www.16personalities.com/)。各开源项目的源码级比较见 [research.md](landscape.md) §4。

### 1.2 位置图

按「覆盖几个 Agent」和「能走到哪一步」两个维度定性归纳（依据 §3 矩阵）：

| 能走到哪一步 | 单 Agent | 跨 Agent |
| --- | --- | --- |
| **改配置并验证效果** | 空位（Hermes 的学习闭环带 ledger 与回滚，但只在 Hermes 内部、只管它自建的 skill） | **Orbit 的目标位置** |
| **会改或会装，但不验证** | Claude Code `/doctor`、插件推荐；Codex Memories、`tool_suggest`；Devin Coach | SpecStory Lore（只产 skill）；skills.sh、cc-switch（只装卸或切换） |
| **只看、只统计** | `/insights`、`/usage`、Devin Session Insights、Cursor 与 Copilot 团队分析 | agentsview、ccusage / tokscale、Entire、Langfuse / LangSmith |

组织级效能平台不放进这张图：Faros 能经网关策略执行并回放验证，但对象是团队预算与模型路由，不是个人配置。

## 2. 重点竞品卡片

挑选标准：威胁最高（2.1–2.3、2.5、2.8），或在某一维度是标杆（其余）。所有卡片核实于 2026-10-02。

### 2.1 Claude Code 官方能力

| 项 | 内容 |
| --- | --- |
| 定位 | Claude Code 内置的用量、洞察与配置体检，加上按会话信号的插件推荐；团队侧另有管理员分析 |
| 用户 | 个人开发者；Team / Enterprise 管理员 |
| 数据来源 | 本机会话历史（不含其他设备与 claude.ai） |
| 核心功能 | **`/insights`**：HTML 报告，含常做的项目、使用方式、摩擦（误解请求、有 bug 的代码等）与建议，单次最多分析 200 个新会话、跳过极短会话，可估算 auto mode 能代处理多少次审批。**`/usage`**：按 skill、子代理、插件、单个 MCP server 归因用量，标出占 ≥10% 的行为（长上下文、cache miss），可切 24 小时 / 7 天。**`/doctor`**：找出未用的 skills、MCP、插件并对比上下文成本，标出慢 hook，去重、裁剪 `CLAUDE.md` 并迁移到 skill，提议默认开 auto mode、预批准常被拒的只读命令；`prompt-audit` 审计过时或冲突的指令。另有 `/skill-doctor`、`/fewer-permission-prompts`、`/team-onboarding`、插件 relevance 推荐与 `claude plugin eval` |
| 分析维度 | 项目领域、交互方式、摩擦类别、满意度（模型估计）、按扩展的成本归因、上下文成本 |
| 可执行建议 / 一键安装 | 建议文本与可复制提示；`/doctor` 先报告，经确认才改；插件提示给出 `/plugin install` 命令，从不自动安装，同一插件最多每 3 个会话提示一次；未见统一撤销 |
| 隐私 | 本机读取；`/insights` 的分析走用户自己的模型账号，内容发往模型供应商；报告与会话按 `cleanupPeriodDays`（默认 30 天）删除，桌面版与 Cowork 自 2.1.248 起例外 |
| 价格 | 随订阅，所有套餐可用；`/insights` 消耗用户自己的额度 |
| 优点 | 零安装，官方字段最全，随版本快速演进；`/doctor` 已覆盖 Orbit「规则精简」「权限」两类推荐的一部分 |
| 缺点（相对 Orbit） | 只看 Claude Code；一次性快照，没有固定口径的趋势与装后对照；`/insights` 的开放标签会漂移（`yhyfhgs` 本机 49 个 facet 文件里，`goal_categories` 出现 181 种键，见 [research.md](landscape.md) §1 第 4 条）；插件推荐只看当前会话，且只对管理员加入 `pluginSuggestionMarketplaces` 的市场生效 |
| 对 Orbit | **威胁最高。** 借：session-meta 的 31 个字段作派生指标的对照答案；relevance 信号词表（工作目录、命令名、host、读过的文件、依赖清单）作资源库匹配字段；提示频控；`plugin eval` 的有 / 无对照。避：不做单 Agent 叙述报告，不重做 `/doctor` |
| 来源 | [costs：`/usage` 与 Analyze your usage patterns](https://code.claude.com/docs/en/costs)、[commands](https://code.claude.com/docs/en/commands)、[plugins/relevance](https://code.claude.com/docs/en/plugins/relevance)、[plugin-evals](https://code.claude.com/docs/en/plugin-evals)、[analytics](https://code.claude.com/docs/en/analytics)、[claude-directory（清理规则）](https://code.claude.com/docs/en/claude-directory) |

### 2.2 Codex 官方能力

| 项 | 内容 |
| --- | --- |
| 定位 | 个人额度查看 + 自动记忆与 skill 沉淀；管理员侧有用量洞察 |
| 用户 | 个人（CLI / App）；Business / Enterprise 管理员 |
| 数据来源 | 本机 `~/.codex/sessions`；ChatGPT 账号用量；可选的 Computer History |
| 核心功能 | `/status`、`/usage`（日 / 周 / 累计）。**Memories**：本地默认关闭；会话闲置后抽取记忆，存 `~/.codex/memories/`；合并阶段可在记忆目录写 `skills/<name>/SKILL.md`；剩余额度低于阈值时跳过。**Computer History** 发现重复工作时建议生成 skill 或 automation；**Record & Replay** 看用户演示一次后起草 skill；`tool_suggest` 让模型在任务中途建议安装插件；`/import` 导入 Claude Code 的配置、项目记忆与近 30 天会话。管理员 **Usage Insights** 按用例与任务分类，给出 credits 占比、模型与推理强度分布、插件与 skill 调用次数 |
| 分析维度 | 个人侧只有用量计数；管理员侧是任务分类 × 模型 × 推理强度 × skill 调用 |
| 可执行建议 / 一键安装 | Memories 自动生效；插件建议需用户确认后安装；生成的 skill 由用户修改后再用 |
| 隐私 | 记忆存本机；管理员数据在 OpenAI |
| 价格 | 随 ChatGPT 套餐；Computer History 限 Pro / Business / Enterprise |
| 优点 | 「从历史沉淀 skill」「任务中途推荐插件」都已内置 |
| 缺点（相对 Orbit） | 没有个人分析报告与摩擦诊断；只看 Codex；没有装后效果 |
| 对 Orbit | **威胁高**（skill 生成与插件推荐）。借 Memories 的节流：闲置 ≥ 6 小时才处理、每次启动最多 2 个、剩余额度 < 25% 跳过、租约防重复、密钥脱敏；rollout 每次响应都带 `rate_limits`，可离线重建额度曲线。避：不再造「会话 → 记忆 → 自动 skill」 |
| 来源 | [Memories](https://learn.chatgpt.com/docs/customization/memories.md)、[合并模板的 skills 段（源码）](https://github.com/openai/codex/blob/b707714ae4200db0a0385da24b3981d99139fa62/codex-rs/memories/write/templates/memories/consolidation.md#L687-L724)、[默认阈值（源码）](https://github.com/openai/codex/blob/b707714ae4200db0a0385da24b3981d99139fa62/codex-rs/config/src/types.rs#L55-L60)、[Computer History](https://learn.chatgpt.com/docs/customization/computer-history.md)、[Record & Replay](https://learn.chatgpt.com/docs/extend/record-and-replay.md)、[`tool_suggest`（源码）](https://github.com/openai/codex/blob/b707714ae4200db0a0385da24b3981d99139fa62/codex-rs/tools/src/request_plugin_install.rs#L16)、[Import](https://learn.chatgpt.com/docs/import.md)、[Usage Insights](https://learn.chatgpt.com/docs/enterprise/usage-insights)、[Codex Pricing](https://developers.openai.com/codex/pricing) |

### 2.3 Devin：Session Insights 与 Devin Coach

| 项 | 内容 |
| --- | --- |
| 定位 | 云端 Agent（含由 Windsurf 改名的 Devin Desktop）的会话复盘与发送前纠偏 |
| 用户 | Devin 用户与管理员 |
| 数据来源 | Devin 云端会话 |
| 核心功能 | **Session Insights**：所有完成的会话自动做轻量分类；L / XL 会话结束时自动生成完整分析，其余手动触发；问题时间线带影响分级，给出改进后的 prompt 与配置行动项，指出哪些 Knowledge 有用、哪些碍事，附 ACU 用量与任务类别。**Devin Coach**：发送前标出 5 类低效用法（模糊的大型请求、非工作任务、模型选得过大、无关追问、可拆分的任务），建议可一键采纳（如「Create plan」「Split into child sessions」）；管理员看 30 天的展示、采纳与拒绝次数和按类型统计，并按「一次修复能解开多少阻塞」对运行时 blocker 分组 |
| 分析维度 | 问题时间线与影响、Knowledge 效用、任务类别、ACU |
| 可执行建议 / 一键安装 | Session Insights 只给建议，不自动修改 prompt、配置与 Knowledge；Coach 一键采纳 |
| 隐私 | 云端 |
| 价格 | Session Insights 免费；Devin 按 ACU / 套餐计费 |
| 优点 | 「复盘 → 改进 prompt → 沉淀 playbook」最完整；发送前提醒的时机好 |
| 缺点（相对 Orbit） | 只覆盖 Devin 自己的会话；云端 |
| 对 Orbit | **威胁高**（叙事最接近）。借：问题时间线 + 影响分级（会话页的关键时刻）；「Knowledge 有用 / 过时」对应 Orbit 的减法推荐；发送前提醒可做成 `UserPromptSubmit` hook 类推荐（v1） |
| 来源 | [Session Insights](https://docs.devin.ai/product-guides/session-insights)、[Devin Coach](https://docs.devin.ai/enterprise/features/devin-coach.md)、[Windsurf is now Devin Desktop](https://devin.ai/blog/windsurf-is-now-devin-desktop) |

### 2.4 Cursor 与 GitHub Copilot 的团队分析

| 项 | 内容 |
| --- | --- |
| 定位 | IDE 与平台厂商给团队的采用度与 AI 产出分析 |
| 用户 | 管理员；成员可看自己的数据 |
| 数据来源 | Cursor：客户端遥测 + git 提交；Copilot：GitHub 遥测 + PR |
| 核心功能 | **Cursor**：AI Share of Committed Code（把 AI 生成行的签名与后续提交比对）、Agent 编辑、Tab 补全、按模式与模型的消息数；**Conversation Insights** 把会话分成 12 类工作、3 种工作类型（KTLO / Bug / 新功能），并衡量任务复杂度与**提示具体度**。**Copilot**：2026-02-27 GA 的用量与代码生成看板；2026-05-29 起按 28 天滚动窗口把用户分为 AI 采用阶段（代码优先 → agent 优先 → 多 agent）；2026-07-22 上线影响看板 |
| 分析维度 | 采用度、AI 代码占比、工作类别、复杂度、提示具体度、采用阶段 |
| 可执行建议 / 一键安装 | 无个人建议；Copilot 给管理员「加深采用」的下一步 |
| 隐私 | Cursor 的分类全部在设备端运行，输出不在预期值内就丢弃；Copilot 是聚合遥测 |
| 价格 | 随 Cursor Teams / Enterprise（Conversation Insights 自 2026-01-01 起按推理计费，Enterprise 默认可用）；随 Copilot Business / Enterprise |
| 优点 | 「设备端分类 + 只传聚合」是隐私样板；「提示具体度」「采用阶段」可直接借作画像维度与成熟度阶梯 |
| 缺点（相对 Orbit） | 管理视角，不回答「我该怎么改」 |
| 对 Orbit | 威胁低；借维度与隐私做法。Cursor Year in Code 的「使用量百分位」是最强的晒图动机，但需要跨用户数据，Orbit 不做 |
| 来源 | [Cursor Usage Analytics](https://cursor.com/docs/account/teams/analytics)、[Year in Code 2025（论坛）](https://forum.cursor.com/t/view-your-year-2025-in-cursor/146960)、[Copilot metrics GA](https://github.blog/changelog/2026-02-27-copilot-metrics-is-now-generally-available)、[采用阶段](https://github.blog/changelog/2026-05-29-copilot-usage-metrics-api-adds-cohorts-for-ai-adoption/)、[影响看板](https://github.blog/changelog/2026-07-22-new-copilot-usage-metrics-impact-dashboard/) |

### 2.5 SpecStory 与 Lore

| 项 | 内容 |
| --- | --- |
| 定位 | 「Intent is the new source code」：把 AI 编程对话自动存成本地 Markdown，可搜索、可分享；Lore 是把历史炼成 skill 的 Agent Skill |
| 用户 | 个人与团队 |
| 数据来源 | Cursor、Copilot 扩展 + CLI 包装 12 种终端 Agent（`specstory run <agent>` 启动，或 `specstory sync` 补写已有会话），写入项目内 `.specstory/history/`；Lore 读取 Claude Code、Codex、Cursor、Gemini、Factory Droid、DeepSeek、Antigravity 的历史（新旧格式） |
| 核心功能 | Cloud：跨项目、跨机器搜索，和历史对话，公开链接分享。**Lore**：分析单位是 beat，即一次提示 + 到下一次提示前 Agent 实际执行的命令、文件与退出码 + 用户回复（认可 ✓ / 纠正 ✗ 当结果标签）；零依赖解析器 + SQLite 做计数，Agent 只负责命名与判断；每个候选簇配一个挖掘者和一个对抗验证者；主题挖掘报告相对个人基线的 outcome lift |
| 分析维度 | 重复工作流、纠正与认可、隐性经验主题（怎么评审、怎么诊断、怎么指挥模型） |
| 可执行建议 / 一键安装 | **生成 skill 并装进每个 Agent**：写到 `~/.agents/skills/<name>`，再软链到各 Agent 目录；先出锻造计划，自带的 `PreToolUse` hook 拒绝任何没有内嵌完整证据的计划；registry 记住已锻造和已拒绝的候选 |
| 隐私 | 本地优先，Cloud 可选；交给模型前机械脱敏凭据 |
| 价格 | 扩展与 CLI 免费；Lore 开源（Apache-2.0），模型调用用用户自己的额度；Cloud 的 analytics 与 skills 属付费功能（价格未核实） |
| 优点 | 与 Orbit「推荐 + 生成 + 安装」重叠最多；「证据 + 反驳 + 看过证据才能批准」值得照搬 |
| 缺点（相对 Orbit） | 只产 skill，不涉及规则精简、hooks、权限、MCP、模型与思考强度、工作流；没有可视化与装后对照；要先用 SpecStory 采集 |
| 对 Orbit | **威胁第二高**，对策见 §0.4 T2。照搬四个工程决定：beat 作分析单位；下一句用户回复当结果标签；确定性计数 + 对抗验证；安装计划内嵌证据才可批准 |
| 来源 | [SpecStory README](https://github.com/specstoryai/getspecstory)（1.3k★）、[Lore README](https://github.com/specstoryai/getspecstory/tree/main/lore)、[Lore CHANGELOG（v3.9.0，2026-06-11）](https://github.com/specstoryai/getspecstory/blob/main/lore/CHANGELOG.md)、[Cloud 概览](https://docs.specstory.com/cloud/overview) |

### 2.6 Entire

| 项 | 内容 |
| --- | --- |
| 定位 | 前 GitHub CEO Thomas Dohmke 创办；让 Agent 写的代码可审计、可复现，可从检查点恢复 |
| 用户 | 工程团队 |
| 数据来源 | Agent hooks（Claude Code、Codex、Cursor、Antigravity、Pi 等约 10 种）+ git hooks |
| 核心功能 | 提交时生成 checkpoint（逐会话 transcript、prompt、改动文件、token、工具调用），存为仓库自己的 git ref `refs/entire/checkpoints/<shard>/<id>`，提交带 `Entire-Checkpoint` trailer；`entire search`（语义 + 关键词）、`recap`、`dispatch`；提交时自动摘要**意图、结果、经验、摩擦点、未决事项**，默认由 Claude 生成，可换成 Codex、Pi 等 |
| 分析维度 | 每次提交对应的会话、意图与摩擦摘要 |
| 可执行建议 / 一键安装 | 不给配置建议 |
| 隐私 | transcript 进仓库自己的 git 对象，推送后在远端；写入前脱敏 secrets，可选 PII 脱敏 |
| 价格 | CLI 开源（MIT，5.1k★）；托管平台定价未公开（未核实）；2026-02-12 发布，种子轮 6000 万美元 |
| 优点 | 会话与提交一一对应，天然带「结果」 |
| 缺点（相对 Orbit） | 从启用那刻起才采集；偏审计与团队协作，不分析个人行为 |
| 对 Orbit | 威胁低。借摘要字段；用户已装 Entire 时，只读 `Entire-Checkpoint` trailer，把会话连到提交与结果 |
| 来源 | [Entire CLI README](https://github.com/entireio/cli)、[官网](https://entire.io/)、[发布报道（RCPmag，2026-02-12）](https://rcpmag.com/articles/2026/02/12/ex-github-ceo-thomas-dohmke-unveils-entire.aspx) |

### 2.7 claude-mem

| 项 | 内容 |
| --- | --- |
| 定位 | 跨会话的持久记忆 |
| 用户 | 个人为主 |
| 数据来源 | hooks 观察工具调用（Claude Code、Codex、Gemini、Cursor、OpenCode、Hermes、Copilot 等） |
| 核心功能 | 把决策、修复、走过的死路压缩成结构化 observation，按渐进披露注入后续会话并显示 token 成本；本地 Web viewer；`mem-search` skill |
| 分析维度 | 无 |
| 可执行建议 / 一键安装 | 自动注入记忆；不分析，不推荐 |
| 隐私 | 本地 SQLite + 本地向量检索；`<private>` 标签可排除内容；可选 CMEM Cloud |
| 价格 | 开源（Apache-2.0，95.2k★）；CMEM Cloud $20 / 月，Team $333 / 席 / 月 |
| 优点 | 星数说明「让 Agent 记住我」是强需求 |
| 缺点（相对 Orbit） | 不分析、不推荐；注入的记忆本身占上下文 |
| 对 Orbit | 不竞争。装了记忆插件会改变会话形态，效果追踪要把它记为混杂因素；其 observation 可作补充数据源（经用户授权、只读，待验证） |
| 来源 | [README](https://github.com/thedotmack/claude-mem)、[CMEM](https://cmem.ai/) |

### 2.8 agentsview

| 项 | 内容 |
| --- | --- |
| 定位 | 本机优先的会话搜索、分析、洞察与 token 统计 |
| 用户 | 个人开发者；可镜像到 PostgreSQL 给团队用 |
| 数据来源 | 自动发现本机各 Agent 的会话目录，同步进本机 SQLite；README 支持表 66 项（含已弃用的 Amp）；源文件被 Agent 清理后，已归档的会话仍保留 |
| 核心功能 | 浏览与搜索、每日成本；friction 检测器（纠偏、重复调用、失控循环、反复编辑、压缩后重做、上下文压力，同一工具的错误出现在 ≥ 3 个会话即升级）；扣分制健康分与 outcome；Quality 模式卡（模式 → 证据 → 动作，受影响会话 ≥ 18% 为 warning、≥ 35% 为 critical）；带 provenance 的 LLM 建议 |
| 分析维度 | 会话形态、摩擦、工具健康、成本、活动节律 |
| 可执行建议 / 一键安装 | 规则动作文本；不安装、不追踪效果 |
| 隐私 | 本机；服务只绑定 loopback 并校验 Host 头 |
| 价格 | 免费开源（MIT，6.0k★） |
| 优点 | 最接近的开源参照，迭代快（2026-09 连发 v0.42、v0.43、v0.44） |
| 缺点（相对 Orbit） | 不安装、不做装后对照；检测器以英文正则为主，长度按字节计，中文会失真 |
| 对 Orbit | **威胁中。** 不在「能看会话」上竞争；把检测器移植为规则 v0 并中文化（MIT，保留声明） |
| 来源 | [README](https://github.com/kenn-io/agentsview)、[Releases](https://github.com/kenn-io/agentsview/releases)、[归档与重建说明](https://agentsview.io/docs/configuration/)、[friction 源码](https://github.com/kenn-io/agentsview/tree/d37642206051dababc436635024676c17dddac45/internal/friction) |

### 2.9 skills.sh 与 claude-code-templates

| 项 | 内容 |
| --- | --- |
| 定位 | skills.sh：Vercel 的开放 Agent Skills 生态与安装量排行（2026-01-20 发布）。claude-code-templates：社区组件库 + 一键批量安装 |
| 用户 | 所有 Agent 用户 |
| 数据来源 | skills.sh 由 `npx skills add` 的匿名遥测自动收录，不需要单独发布 |
| 核心功能 | skills.sh：All Time / Trending（24 小时）/ Hot 排行，单个 skill 的每周安装数与按 Agent 分布；`npx skills add / remove`，默认把各 Agent 的 skills 目录软链到一份规范副本，README 列出 79 个 Agent。claude-code-templates：1,000+ 组件（agents、commands、settings、hooks、MCP、skills、plugins），用 Stack Builder 组合后批量安装 |
| 分析维度 | 安装量与按 Agent 分布；不看用户自己的数据 |
| 可执行建议 / 一键安装 | 一条命令装与卸；按流行度排序。2026-02-17 起与 Gen、Socket、Snyk 自动审计，恶意项从榜单与搜索中隐藏；`skills@1.4.0` 起装前显示风险等级；没有 diff 预览 |
| 隐私 | 遥测默认开启，可用 `DISABLE_TELEMETRY` / `DO_NOT_TRACK` 关闭 |
| 价格 | 免费 |
| 优点 | 跨 Agent 装卸 skill 的现成通道 + 审计数据 |
| 缺点（相对 Orbit） | 「流行」不等于「对你有用」；没有效果追踪 |
| 对 Orbit | 通道与先验，不是对手：安装量与审计结果作推荐的先验与门槛；可直接调用 `npx skills add / remove`，或复用同样的「规范副本 + 软链」，撤销就是删软链 |
| 来源 | [Vercel 发布 skills](https://vercel.com/changelog/introducing-skills-the-open-agent-skills-ecosystem)、[skills.sh](https://skills.sh/)、[安全审计（2026-02-17）](https://vercel.com/changelog/automated-security-audits-now-available-for-skills-sh)、[vercel-labs/skills](https://github.com/vercel-labs/skills)（33.0k★）、[claude-code-templates](https://github.com/davila7/claude-code-templates)（32.3k★） |

### 2.10 cc-switch

| 项 | 内容 |
| --- | --- |
| 定位 | 多 Agent 的供应商切换，以及 MCP、Skills、Prompts 的统一管理（桌面 App） |
| 用户 | 个人开发者 |
| 数据来源 | 各 Agent 的配置文件与用量 |
| 核心功能 | 一键切换 Claude Code、Codex、Gemini CLI 等的供应商；统一管理 MCP、Skills、Prompts；用量面板 |
| 分析维度 | 只有用量 |
| 可执行建议 / 一键安装 | 一键切换与写入配置；不做行为分析、推荐与效果追踪 |
| 隐私 | 本机；其 OAuth 认证中心自述可能违反服务条款（见 [research.md](landscape.md) §4.2） |
| 价格 | 开源（MIT，139k★） |
| 优点 | 「一次写入多个 Agent」的直接相邻产品，用户基数大 |
| 缺点（相对 Orbit） | 管配置与连接，不回答「为什么改、改什么、改了有没有用」 |
| 对 Orbit | 路演要讲清区别。借存储设计（增量水位 + 尾部指纹、`request_model` 与 `pricing_model` 双列）；不碰凭据与代理 |
| 来源 | [README](https://github.com/farion1231/cc-switch) |

### 2.11 效能平台：Faros AI、DX、WakaTime

| 项 | Faros AI | DX（Atlassian） | WakaTime |
| --- | --- | --- | --- |
| 定位 | 2026 年转为「token 工程平台」 | 「研究者设计的工程智能平台」；2026-05 Gartner DPIP 魔力象限 Leader | 个人编码时间追踪，向 AI 洞察延伸 |
| 用户 | 平台与 FinOps 团队 | VP Eng、平台团队 | 个人与团队 |
| 数据来源 | 60+ 工程数据源：coding agent、网关与模型路由、Git、Jira、CI/CD、事故系统 | Git、工单等系统数据 + AI 代码统计 + 开发者问卷 | 编辑器与 Claude Code 插件的活动心跳 |
| 核心功能与维度 | Token Intelligence（2026-06-17）：把花费归因到会话、PR、团队与结果；会话分为高效 / 低效 / 浪费；找出被放弃的探索路径、返工与成本尖峰；Time Machine 回放历史工作，验证模型路由与流程修正 | DX Core 4；AI Measurement Framework 三维：利用率、影响、成本 | 编码时间、AI 生成与手写代码占比、按模型的用量与估算花费、年度 Wrapped |
| 可执行建议 / 一键安装 | 给出工具「保留 / 收窄 / 砍掉」与模型路由建议，经网关策略执行 | 组织级改进建议与基准 | 无 |
| 隐私 | 称不需在开发者机器上装软件，数据留在客户边界 | 企业 SaaS | 心跳发往 WakaTime 云 |
| 价格 | 按用量，未公开 | 询价 | Free、Basic $9、**Premium $14（含 AI 洞察）**、Team $21、Business $24 / 开发者 / 月 |
| 优点 | 把浪费分类做到会话级，并用回放验证修正 | 方法论与问卷体系最成熟，有 Atlassian 渠道 | 面向个人且有 AI 维度的付费产品 |
| 缺点（相对 Orbit） | 企业级、重集成，个人与小团队用不上 | 看不到会话里发生了什么 | 只有计时与行数，没有会话语义、摩擦与建议 |
| 对 Orbit | 「浪费分类 + 回放验证」是 Advanced 的企业级镜像，个人版做轻量回放 | 买方不同，借结果口径 | 个人愿意为「了解自己」付费的价格锚 |
| 来源 | [官网](https://www.faros.ai/)、[Token Intelligence](https://www.faros.ai/blog/token-intelligence-for-ai-engineering) | [官网](https://getdx.com/)、[AI Measurement Framework](https://getdx.com/ai-measurement-framework/)、[魔力象限公告](https://getdx.com/report/dx-named-a-leader-gartner-magic-quadrant-developer-productivity/)（12 家入围名单只见于第三方，未核实） | [定价](https://wakatime.com/pricing)、[Claude Code 插件](https://wakatime.com/claude-code-time-tracking) |

同类团队平台的公开价：LinearB $29–59、Swarmia $45–55 / 开发者 / 月（Swarmia 不足 10 人免费），均卖给管理层。对 Orbit 的共同启示：它们都把 AI 用量连到 PR 吞吐、cycle time、返工；Orbit 只有会话日志，「结果」信号要从本机取：会话所在仓库的提交、提交是否被回滚、测试命令的退出码。

### 2.12 可观测平台：Langfuse、LangSmith、Raindrop

| 项 | Langfuse（ClickHouse） | LangSmith（LangChain） | Raindrop |
| --- | --- | --- | --- |
| 定位 | 开源 LLM 工程平台 | Agent 工程平台 | 生产环境 AI agent 的「Sentry」 |
| 用户 | 做 AI 应用的团队 | 同左 | 同左 |
| 数据来源 | SDK / OpenTelemetry；Claude Code hook 与 Codex 集成从会话日志重建轮次与工具调用 | SDK；Claude Code 追踪插件 | SDK 事件 |
| 核心功能与维度 | Trace / Session、评测、数据集与实验、Prompt 管理、自定义看板 | Tracing、评测；**Insights**：先逐条 LLM 摘要，再聚成两级类别，输出使用模式与失败根因，可定时运行 | 用小模型识别「用户沮丧」「Agent 卡在循环」等隐性信号；Experiments 验证修复效果 |
| 可执行建议 / 一键安装 | 无个人建议 | 给出问题类别，不改配置 | 发现问题 → 实验验证 |
| 隐私 | 核心 MIT，可完全自部署 | Cloud；自托管只在 Enterprise | Cloud |
| 价格 | Hobby 免费、Core $29、Pro $199、Enterprise $2,499 / 月 | Developer 免费、Plus $39 / 席 / 月；Insights 每千条线程约 $1–4 | Starter $65、Pro $350 / 月起（第三方汇总，未核实） |
| 优点 | 开源、可自托管，生态最大（35.3k★） | 「逐条摘要 → 聚类」的分层归类方法现成 | 「隐性信号 + 改后对照」与 Orbit 的摩擦与 7 天追踪最像 |
| 缺点（相对 Orbit） | 要先装 hook，接入前的历史拿不到；面向应用开发而非个人习惯 | 闭源 SaaS，同样要先埋点 | 面向 AI 产品的终端用户，不是开发者本人 |
| 对 Orbit | 兼容不竞争：它们从装 hook 起才采集；v1 提供 OTel 导出 | 借「逐条摘要 → 聚类」做 AI 辅助分析 | 借「沮丧 / 卡在循环」信号与改后对照 |
| 来源 | [ClickHouse 收购（2026-01-16）](https://clickhouse.com/blog/clickhouse-acquires-langfuse-open-source-llm-observability)、[定价](https://langfuse.com/pricing)、[Claude Code 集成](https://langfuse.com/integrations/developer-tools/claude-code) | [定价](https://www.langchain.com/pricing)、[Insights](https://docs.langchain.com/langsmith/insights) | [官网](https://raindrop.ai/) |

### 2.13 人格化报告：Spotify、Raycast、ChatGPT、Cursor

| 项 | Spotify Wrapped | Raycast Wrapped 2025 | Your Year with ChatGPT | Cursor Year in Code 2025 |
| --- | --- | --- | --- | --- |
| 形式 | 年度故事卡 | macOS App 内（v1.104.0，2025-12-16） | 年度回顾（2025-12-22），网页与 App | 年度网页 `cursor.com/2025` |
| 用户与价格 | 全体用户，免费 | Raycast 用户，免费 | 个人套餐用户（Team / Enterprise / Edu 不提供），免费 | Cursor 用户，免费 |
| 数据来源 | 账号收听数据 | 本机使用数据 | 记忆与聊天记录 | 账号用量 |
| 人格 / 标签 | 2022 年「Listening Personality」16 型：4 个二分维度 → 四字母代码 + 名称 | — | 奖项、诗、像素画 | — |
| 社会比较 | 2025 年 Fan Leaderboard、Wrapped Party | — | — | 使用量百分位（如 Top 2%）、连续天数 |
| 隐私 | — | 大部分数据只存本机；使用不足 14 天不显示；每节可「Copy as Image」 | 需开启记忆与聊天记录引用，并达到最低活跃度 | 账号侧数据 |
| 效果 | 2024 年用泛化的 AI 内容替换数据，CARMA 测得正面情绪 50.5% → 41.5%；2025 年回归数据与互动，24 小时 2 亿用户、首日 5 亿次分享 | — | 评价不一 | 论坛自发晒图 |
| 可执行建议 | 无 | 无 | 无 | 无 |
| 优点 | 身份标签 + 社会比较，传播力最强 | 隐私形态与 Orbit 相同 | 证明 AI 助手的使用回顾能做 | 百分位是最强的晒图动机 |
| 缺点（相对 Orbit） | 一年一次，只有计数与标签 | 只有计数 | 被批尴尬，AI 文案风险 | 只有量化数字，没有行为洞察 |
| 对 Orbit | 维度可解释、数字上卡，AI 文案不替代数据 | 同平台、同隐私形态，最值得照搬 | 「先开启才生成」的门槛 | 百分位需要跨用户数据，Orbit 不做 |
| 来源 | [2022（Engadget）](https://www.engadget.com/spotify-wrapped-2022-130037719.html)、[2022 维度（SAYS）](https://says.com/my/entertainment/spotify-wrapped-2022-16-personalities)、[2024（Marketing-Interactive 引 CARMA）](https://www.marketing-interactive.com/Spotify-brand-sentiments-dip-after-Wrapped-2024's-use-of-AI)、[2025（Spotify Newsroom）](https://newsroom.spotify.com/2025-12-03/2025-wrapped-user-experience/)、[2025 首日数据（TechCrunch）](https://techcrunch.com/2025/12/04/spotify-says-wrapped-2025-is-its-biggest-yet-with-200m-users-in-its-first-day) | [changelog](https://www.raycast.com/changelog/macos-v1/1-104-0) | [Storyboard18](https://storyboard18.com/digital/chatgpt-rolls-out-year-end-review-feature-inspired-by-spotify-wrapped-86382.htm)、[TechRadar](https://www.techradar.com/ai-platforms-assistants/chatgpt/chatgpts-attempt-at-spotify-wrapped-is-more-embarrassing-than-any-song-list)（只据标题） | [论坛帖](https://forum.cursor.com/t/view-your-year-2025-in-cursor/146960) |

开发者圈另有：社区的 Claude Code Wrapped 按时段与计数贴称号（夜猫子、连续打卡者等）；tokscale 有公开 token 排行榜，比的是「烧了多少」；16Personalities 免费给完整类型、付费卖深度报告。**MBTI 是 Myers & Briggs Foundation 的注册商标**（[商标说明](https://themyersbriggs.com/en-US/Support/Trademarks)），产品文案应使用自有名称。

## 3. 功能对比矩阵

### 3.1 矩阵

图例：● 有且较完整｜◐ 部分或有限制｜○ 没有｜— 不适用。Orbit 的「Advanced / Lite」两列是目标能力；「现状」列：`main` 已合入，`PR #9` / `PR #11` 在未合入的 PR 中，`Demo-A` / `Demo-L` 只在 Advanced / Lite Demo 中用示例数据演示，「计划」只有设计。

| 能力 | Advanced | Lite | Orbit 现状 | Claude Code | Codex | Devin | SpecStory + Lore | agentsview | Entire | 效能平台 | 可观测 | 市场 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 覆盖 Agent | 9+ | 同 Advanced | main：Codex；PR #9：6 个；PR #11：Codex | 1 | 1 | 1 | 采集 12 / 分析 7 | 66 项 | 约 10 | 多（管理 API） | 多（逐个装 hook） | 安装 79 |
| 零配置读接入前的历史 | ● | ● | main ◐ 手动导入；PR #11 发现 + 增量 | ◐ 默认留 30 天 | ○ | ● 云端 | ◐ 需 `sync` | ● | ○ 从启用起 | ◐ | ○ 从装 hook 起 | — |
| 长期原始归档 | ● | ● | PR #9 整文件快照；PR #11 增量分块 | ○ | — | ● 云端 | ◐ Markdown | ● | ● git | ● | ◐ 按套餐 | — |
| 数据只在本机 | ● | ● | main ● | ● | ◐ | ○ | ● | ● | ◐ | ○ | ◐ | — |
| 核心结论不靠 LLM | ● | ● | main ● | ◐ | ◐ 只有计数 | ○ | ◐ | ● | ◐ | ◐ | ◐ | — |
| 会话轨迹可视化 | ● | ◐ | Demo-A、Demo-L；API 可分页取事件 | ○ | ○ | ◐ | ○ | ● | ◐ | ○ | ● | — |
| 结论回到原事件 | ● | ◐ | main ● `/v1/evidence/{id}` | ◐ | ○ | ● | ● | ● | ◐ | ◐ | ● | — |
| 协作画像 / 人格 | ● | ● | main ◐ 要求画像；四轴人格只在 Demo | ◐ | ○ | ○ | ◐ | ◐ | ○ | ○ | ○ | — |
| 摩擦 / 瓶颈诊断 | ● | ◐ | main ◐ 4 类瓶颈 + 工具失败测量 | ● | ○ | ● | ◐ | ● | ◐ | ◐ | ◐ | — |
| 同一个人跨 Agent / 模型对比 | ● | ◐ | 计划（PR #9 数据层已支持多 Agent） | ○ | ○ | ○ | ○ | ◐ | ○ | ◐ 团队按工具 | ○ | — |
| 用量与成本 | ◐ 分析分母 | ◐ 一张卡 | main ◐ 会话累计 token；PR #9 `model_call` | ● | ◐ | ◐ | ○ | ● | ◐ | ● | ● | — |
| 可执行建议 | ● | ● | main ◐ 4 个 skill | ● | ◐ | ● | ● | ◐ | ○ | ◐ | ◐ | ◐ 流行度 |
| 生成优化项 | ● 7 类 | ○ | 计划；Demo-A 模拟 | ◐ | ◐ | ◐ | ◐ 仅 skill | ○ | ○ | ○ | ◐ | — |
| 预览 → 确认 → 撤销 | ● | ◐ 低风险项 | 计划；Demo 模拟 | ◐ | ◐ | ◐ | ◐ 无一键撤销 | ○ | ○ | ○ | ○ | ◐ 无 diff |
| 一次写入多个 Agent | ● | ○ | 计划 | ○ | ○ | ○ | ● | ○ | ○ | ○ | ○ | ● |
| 装后效果对照（个人） | ● | ◐ | 计划；后端标 `unmeasured` | ○ | ○ | ◐ 采纳率 | ◐ outcome lift | ○ | ○ | ◐ 组织级 | ◐ 应用级 | ○ |
| 装前评测 / benchmark | ● | ○ | main ◐「说人话」评测 | ◐ `plugin eval` | ○ | ○ | ◐ 对抗验证 | ○ | ○ | ◐ 回放 | ● | ◐ 审计 / TDQS |
| 团队 / 管理视角 | ○ 不做 | ○ 不做 | — | ◐ | ● | ● | ◐ | ◐ | ● | ● | ● | — |
| 可分享报告 | ● | ● | Demo-A、Demo-L；main 生成 Markdown 报告 | ◐ | ○ | ○ | ◐ | ○ | ○ | ○ | ○ | — |
| 价格 | 未定 | 未定 | — | 随订阅 | 随套餐 | Insights 免费 | 开源 + Cloud 付费 | 开源 | CLI 开源 | $29–59 / 人 / 月或询价 | 免费至 $2,499 / 月 | 免费 |

**读法**：每一行都有人做得不错，但「零配置读历史 → 诊断 → 生成 → 预览 / 撤销 → 多 Agent 写入 → 装后对照」这一段上，没有任何一列连续是 ●。Orbit 要占的是这条链，而不是其中任何一格。

**现状脚注**（2026-10-02）：
- main 的分析：`feedback.py`（rules-v13）识别 8 个要求维度，`portrait.py` 汇成画像；`bottlenecks.py` 输出 4 类瓶颈（说明修改、回复过长、术语未解释、工具重复失败）与 3 类材料缺口；Feature Analytics（`/v1/analytics/*`）给出工具、流程、节律特征与本地文本聚类。真实 Codex 快照上的测量与「状态未知」的处理见 [docs/backend/feature-analytics.md](../modules/analytics/feature-analytics.md)。
- main 的推荐：内置 10 个固定版本的来源，只对 4 个 skill 生效（`humanizer-zh`、`humanizer`、`doc-coauthoring`、`systematic-debugging`），要求画像与瓶颈证据同时成立，不按热门；全部标 `trial` / `unmeasured`。
- main 的评测：可读性检查（`readability-v2`）、整条链路的构造对照、盲评读者材料，用于「说人话」，不是安装效果评测。
- Advanced Demo 的安装闭环（预览 → 确认 → 10 秒撤销 → 7 天追踪）与 Lite Demo 的模拟安装都只在页面内保存状态，不写配置。

### 3.2 推荐排序信号对照

市场回答「什么流行」，Orbit 回答「什么能解决你的问题」。

| 信号 | 谁在用 | 缺陷 | Orbit 的用法 |
| --- | --- | --- | --- |
| 安装量 / 使用次数 | skills.sh、Smithery、claude-code-templates | 马太效应、可刷，与「对我有没有用」无关 | 只作先验与冷启动，不作主排序 |
| GitHub stars | Glama、Gemini CLI 扩展库、SkillsMP | 与质量弱相关，老项目占优 | 只作门槛 |
| 质量分 | Glama TDQS（工具定义质量 70% + 工具集一致性 30%，A–F） | 只评描述文字，不评实际效果 | 推荐 MCP 时的质量特征 |
| 安全审计与认证 | skills.sh（Gen / Socket / Snyk）、Anthropic verified、Smithery Verified | 静态审计看不到运行时行为 | 未审计或被标记的条目不进一键安装 |
| 人工精选 | 官方目录、Cursor Marketplace、awesome 列表 | 慢、覆盖窄 | 白名单来源 |
| 当前会话信号 | Claude 插件 relevance、Codex `tool_suggest` | 只看当前会话，不看历史问题 | 借时机与频控 |
| **历史问题 → 解法** | **无人在做** | — | 主排序：每周节省 × 适用度 × P(有效) ÷ 成本 − 风险，见 [recommendation.md](../plans/recommendation-module.md) |

## 4. 借鉴与避坑（按模块）

| 模块 | 照搬 | 出处 | 避开 |
| --- | --- | --- | --- |
| 数据 DT | fixture 即规格；支持表作发现清单；会话 → 提交的现成锚点（用户已装时只读） | Lore；agentsview；Entire 的 `Entire-Checkpoint` trailer、git-ai 的 git notes | 从装 hook 起才采集；读凭据调未公开的额度端点 |
| 分析 AN | friction 检测器、健康分、「模式 → 证据 → 动作」卡；问题时间线 + 影响分级；工作类别、复杂度、提示具体度；采用阶段作成熟度阶梯；「高效 / 低效 / 浪费」与被放弃的探索路径；「沮丧」「卡在循环」信号 | agentsview；Devin；Cursor；Copilot；Faros；Raindrop | 开放标签（`/insights` 漂移出 181 种键）；按字节计长度 |
| 推荐 RC | 信号词表与频控（每 3 个会话最多一次）；安装量、审计、TDQS、verified 作先验与门槛；「Knowledge 有用 / 过时」→ 减法推荐；把官方功能列为零安装推荐项 | Claude relevance；skills.sh、Glama、Claude 插件目录；Devin；`/insights` 的「值得尝试的功能」 | 按流行度排序；「同类型用户在用」（没有跨用户数据） |
| AI | 确定性计数 + 模型只命名与判断 + 对抗验证；逐条摘要 → 两级聚类；摘要字段（意图、结果、经验、摩擦点、未决事项），用本机已登录的 Agent 生成、可换 provider；设备端分类，输出不在枚举内即丢弃 | Lore；LangSmith Insights；Entire；Cursor Conversation Insights | 把整段日志交给 Agent 自由问答（理由见 §5.4 第 3 问） |
| 评测 EV | 有 / 无对照每臂多次；回放历史工作验证修正；改后对照实验 | `claude plugin eval`；Faros Time Machine；Raindrop Experiments | 把采纳率当效果（Devin Coach 只报采纳） |
| 安装 IN | 「一份规范副本 + 软链到各 Agent」，撤销即删软链；安装计划内嵌证据才可批准；一键采纳的交互 | Lore、`npx skills`；Lore 的 `PreToolUse` hook；Devin Coach | 无一键撤销（Lore）；无 diff（市场）；自动生效（Codex Memories） |
| 前端 FE | 数据只在本机、每节「Copy as Image」、样本不足不显示；可解释的四维人格；「先开启才生成」 | Raycast Wrapped；Spotify 2022；ChatGPT 年度回顾 | 泛化的 AI 文案（Spotify 2024）；「烧了多少」排行（tokscale）；个人排名式评分（Weave）；只看不改（sniffly、vibe-log 已停更） |

Agent 侧（Hermes 的 ledger 与 curator、Kimi 的 Issues 闭集、pi 的缓存重复计费等）的借鉴见 [research.md](landscape.md) §2.5。

## 5. 对产品与路演的启示

### 5.1 主打展示什么

**一条主线：证据 → 改动 → 验证。** 每一段都要有「只有 Orbit 能做」的画面。

| 时刻 | 画面 | 为什么只有 Orbit 能做 | 数据来源与标注 |
| --- | --- | --- | --- |
| 1. 跨 Agent 的同一个人 | 同一类任务在 Claude Code 与 Codex 里的纠偏率、重复失败、每个完成任务的 token，带样本数与区间 | 官方各看各的；agentsview 只能分别浏览 | 真实数据需要 PR #9 的 Claude Code 与 Codex connector；合入前用示例数据并标「示例」 |
| 2. 一条建议的全过程 | 摩擦证据（次数、原话、会话链接）→ 为什么是 hook 而不是规则（机制决策表）→ 预览将写入的文件与 diff → 确认 → 一键撤销 | `/doctor` 只改 Claude Code；Lore 只产 skill，没有一键撤销；市场没有 diff | 安装器未实现，演示标「模拟安装」 |
| 3. 装后 7 天对照卡 | 目标摩擦的复现率前后对比 + 是否被触发 + 样本数 + 「相关不等于因果」 | 没有竞品对个人做装后对照 | 示例数据，必须标明 |

**现在就能用真实数据展示的**：main 后端在真实 Codex 快照上的「说人话」报告与 Feature Analytics 测量（35 个会话、11,657 次工具调用，其中 55.88% 状态未知并如实显示，见 [docs/backend/feature-analytics.md](../modules/analytics/feature-analytics.md)）。「不知道就写不知道」本身就是区别于 AI 生成式报告的信任点。

**开场 30 秒**（给 `genius-FXC` 的路演脚本草稿）：
1. 「你同时在用 Claude Code 和 Codex。Claude 的 `/insights` 会告诉你 Claude 里哪里卡；同样的问题出在 Codex 里，没人告诉你。」
2. 「Orbit 读你本机已有的全部会话，不用装 hook，打开就有过去几个月；用同一把尺子找出反复出现的卡点，每个结论都能点回原话。」
3. 「然后它把修复装进每个 Agent：先给你看 diff，可以一键撤销；7 天后告诉你那个卡点还出不出现。」

**不要说**：
- 「提速 X%」「每周省 N 小时」——METR 的随机对照里，开发者用 AI 实际慢了 19%，却自认快了 20%（§5.5）；
- 「同类用户」「超过 Y% 的用户」——没有跨用户数据；
- 「AI 自动生成 skill」作为卖点——Lore 与 Codex Memories 已有；
- 「0 字节上传」与「AI 分析」放在同一页却不加说明——交给本机 Agent 的内容会经它发往服务商；
- Demo 里的示例收益数字。

### 5.2 避免与官方正面竞争

一句话回应：**官方是 Orbit 的输入和推荐项，不是对手。** 我们把 `/insights` 已提示过的问题去重，把 `/doctor`、auto mode 这类官方功能推荐给真正需要的人。

| 官方或开源已经做好的 | Orbit 不做 | Orbit 改做 |
| --- | --- | --- |
| 单 Agent 叙述报告（`/insights`、Devin Session Insights） | 不做「又一个 Insights」，也不用这个名字 | 跨 Agent 对比 + 证据回链；Lite 叫「个人协作 Benchmark」，只和过去的自己比 |
| 配置体检与瘦身（`/doctor`、`/skill-doctor`、`/fewer-permission-prompts`） | 不重做 | 列为一等零安装推荐项，用跨会话证据说明「为什么现在该跑」；推荐前用 `claude --version` 探测是否支持 |
| 自动记忆与自动 skill（Codex Memories、claude-mem、Hermes） | 不再造学习闭环 | 记「改了什么、有没有用」的账本；把记忆插件记为混杂因素 |
| 插件市场与排行（官方目录、skills.sh、Smithery） | 不自建市场 | 用它们的 ID、审计结果与安装通道；按个人问题重新排序 |
| 当下推荐插件（Claude relevance、Codex `tool_suggest`） | 不抢「任务进行中」的时机 | 用历史证据推荐；借它们的频控 |
| 单向迁移配置（Claude 与 Codex 的 `/import`） | 不做一次性导入 | 双向、键级 diff、可单条回滚的跨 Agent 写入 |
| trace 存储与观测（Langfuse、LangSmith、Phoenix） | 不做 trace 后端 | v1 提供 OTel / OpenInference 导出 |
| 额度监控与账号切换（CodexBar、cc-switch） | 不读凭据调未公开端点，不切号 | 用量只做分析的分母 |
| 团队看板（各家管理员分析、DX、Faros） | 不做团队排行 | 只服务个人 |

### 5.3 Lite 与 Advanced 的边界

**Lite Demo 现状**（`genius-FXC`，分支 `feat/genius-FXC-dev`，2026-10-02）：8 页——概览、协作画像、会话与轨迹、工具调用、项目分析、情绪与语义、优化建议、资源库；470 个确定性示例会话；预览 → 模拟安装 → 撤销（只在浏览器存标记）；1080×1080 SVG 分享卡与 Markdown / CSV 导出；不调用模型、不读本机日志；生成工坊未做；悬浮组件、小组件、通知、首次启动、人格揭晓、回放、双会话比较、匿名贡献都已移除。范围与自查见该分支的 `prototypes/advance/benchmark-review.md`。

**两个版本各自对标谁**：

| 版本 | 主要对标 | 胜负手 |
| --- | --- | --- |
| Lite：个人协作 Benchmark | `/insights`（单 Agent 报告）、Wrapped 类（传播）、vibe-log（分析 + 教练 + 分享，已停更） | 跨 Agent；只和过去的自己比；低风险的一键修复；带数字证据的分享卡 |
| Advanced：专业、全面 | SpecStory Lore、agentsview、Devin Session Insights、Faros（个人版） | 7 类生成 + 安装 ledger + 三层装后效果 + 装前评测 |

**功能边界**（两者共用同一后端与数据层，Lite 是 Advanced 的子集；阶段以 [feature-map.md](../plans/feature-map.md) 为准）：

| 功能面 | Lite | Advanced | 阶段 | 依据 |
| --- | --- | --- | --- | --- |
| 数据接入 | 自动发现本机 Agent，默认看近 30 / 90 天；共用 L0 归档 | 全部来源与账号、手动加目录、全量归档与重建 | MVP | 零配置是对可观测平台、Entire 的优势 |
| 概览 | 会话、时长、消息、纠偏率、星期 × 小时；一句话解读用确定性模板生成 | 加每个数字的来源与新鲜度、上期对比与区间 | MVP | Lite 的一句话不调模型，守住「不靠 LLM 也有结论」 |
| 协作画像 | 四字母 + 一句话 + 样本门槛，标「实验性」 | 加各维度的证据、按 Agent / 项目拆分、月度演变 | MVP | Spotify 2022 的可解释维度；判定规则以 [analysis.md](../plans/analysis-module.md) 为准 |
| 会话与轨迹 | 关键任务时间轴 + 会话列表 | 三段式时间线、事件账本、检查器、规则与 AI 两类关键时刻 | MVP | 「能看会话」已被 agentsview、dsh 做成熟，Lite 不在这里竞争 |
| 工具与项目 | 工具排行、成功率、失败原因；项目卡与配置覆盖 | 转移矩阵与流程挖掘、审批负担、MCP 与子代理、已装未用、跨项目对比 | MVP | 补上 `/usage` 没有的「已装未用」 |
| 情绪与语义 | 高频反馈语与纠偏类型（词表，确定性） | AI facet、主题聚类命名、情绪（实验性） | MVP；Advanced 的 AI 部分可关 | LangSmith Insights、Cursor Conversation Insights 的做法 |
| 用量与额度 | 一张卡 | 一页：燃尽曲线、缓存效率、额度中断 | v1 | 不做额度监控器（CodexBar 已有） |
| 推荐 | 每周 Top 3，只含低风险类：官方功能开关、规则片段、已审计的现成 skill | 7 类全量、排序分解、减法推荐、模型与思考档位 | MVP；模型档位 v1 | 市场按流行度，Orbit 按个人问题 |
| 生成 | 不生成，只给可编辑模板 | 生成工坊：规则、权限白名单、Hook，之后是 SKILL.md、子代理；四道自检 | MVP（规则、白名单、Hook）；v1（skill、子代理） | 生成不是卖点（Lore、Codex Memories 已有），自检与评测才是 |
| 安装 | 预览 → 确认 → 撤销，单 Agent、低风险 | 跨 Agent 渲染、批量、ledger、风险闸门、Codex hook 的信任引导 | MVP | Lore 没有一键撤销，市场没有 diff |
| 效果 | 一句话：是否被触发 + 目标事件前后次数 + 样本数 | 三层效果 + 区间 + 混杂说明；可选的装前有 / 无对照 | MVP；装前对照 v1 | 没有竞品对个人做装后对照 |
| Benchmark 的含义 | 只和过去的自己比：上月的我、各 Agent 里的我 | 加模型 × 档位的公开基准先验，与个人结果收缩合并 | MVP；模型档位 v1 | 不编跨用户百分位（没有数据通路） |
| AI | 默认关，0 token | 可选开启，走本机 Agent：发送前预览、设预算、只处理新会话、5–10 个会话打包一次调用（固定开销实测见 [research.md](landscape.md) §2.4） | MVP（可关） | `/insights` 逐会话调用模型、单次上限 200 个会话；Orbit 打包调用，目标是同样会话数下更少 token（待验证） |
| 分享与导出 | 分享卡（汇总 + 画像）、Markdown / CSV | 加装后前后对照卡、周报 | MVP | Raycast 的「Copy as Image」；前后对照卡是独有的分享理由 |
| 常驻形态 | 无 | 菜单栏、悬浮组件、小组件、通知 | MVP（运行中 / 空闲）；之后加审批、压缩前提醒 | agent-sessions、CodexBar 的同平台形态 |
| 资源库 | 「为你推荐」（问题驱动）+ 外部信号（官方、verified、审计、安装量，注明来源与日期） | 全量检索、许可与风险、TDQS、来源管理 | MVP | 「同人格正在用」没有数据通路 |

**Lite Demo 与已定口径的 7 处差异**（下一版修改建议；Lite 的增删以本表为准，新增功能先在团队里对齐）：

| # | Lite Demo 现在 | 建议 | 依据 |
| --- | --- | --- | --- |
| 1 | 资源库有「同人格正在用」「社区使用次数」与按「同人格使用比例」排序 | 删除「同人格」；「社区使用」改为标明来源与日期的外部信号（如 skills.sh 安装量） | [docs/design/boards.md](../design/boards.md)「v1 之后的决定」已删除跨用户对比 |
| 2 | 建议卡写「预计效果 约 30% / 约 45% / 约 20%」 | 改为可数的受影响事件（如「近 30 天 14 次纠偏」，示例）+「效果未测」 | [research.md](landscape.md) §1 第 7、11 条 |
| 3 | 叫「协作 MBTI」 | 产品文案改用自有名称；路演可以口头类比；保留「非心理测评」「实验性」 | MBTI 是注册商标（§2.13） |
| 4 | 少于 30 个会话或维度落在 45–55 时不定型 | 30 个会话保留为最低样本；字母改按区间判定（按天 bootstrap 的 95% 区间整体在 50% 一侧才给字母，否则「?」） | [research.md](landscape.md) §5.1、[analysis.md](../plans/analysis-module.md) |
| 5 | 概览有「AI 一句话」 | 用确定性模板生成（后端 `narrative.py` 已有规则叙述），AI 只作可选润色 | 门槛「不靠 LLM 也有结论」 |
| 6 | 项目「完成度」=（完成 + 0.5 × 部分完成）/ 会话数 | 改为 outcome（完成 / 放弃 / 出错 / 未知，带置信度），不给项目进度百分比 | 日志里没有独立验收，后端不判成败；outcome 口径见 [research.md](landscape.md) §6.2 |
| 7 | 所有建议都可模拟安装 | 产品化时 Lite 只对低风险条目开放真实安装，并展示将写入的文件与 diff；hook、权限、MCP 放 Advanced | T5 供应链安全；§0.3「安装安全可逆」 |

### 5.4 路演问答

| 质疑 | 回答要点 | 依据 |
| --- | --- | --- |
| 官方 `/insights` 已经有了，为什么还要 Orbit？ | `/insights` 只看 Claude Code、是一次性快照、报告 30 天后删除，建议停在复制粘贴。Orbit 跨 Agent、长期、能装能撤、装后对照；还会把 `/insights` 已提示过的问题去重，把官方功能当推荐项 | §2.1、§3 |
| SpecStory Lore 已经开源了「历史 → skill → 安装」？ | Lore 只产 skill，不诊断、不可视化、不追踪效果；Orbit 覆盖 7 类，skill 只是其中之一；Lore 的证据设计我们直接照搬 | §2.5 |
| 为什么不直接把日志交给 Claude 问？ | 贵且不稳：默认配置的 `claude -p` 每次调用约 2.7 万输入 token 的固定开销，`/insights` 单次上限 200 个会话；LLM 在长轨迹里定位错误的准确率很低；开放标签会漂移。Orbit 先用代码算，模型只判定已定位的短候选，用最小配置、多会话打包、结构化输出，可关闭 | §5.5；[research.md](landscape.md) §2.4；[ai.md](../plans/ai-module.md) |
| 数据安全吗？ | 默认不出机，只读日志；AI 可关；开启时走用户本机已登录的 Agent，发送前预览并脱敏，并如实说明内容会经该 Agent 发往其服务商；分享卡不含路径与原文 | §0.3 |
| 怎么证明有效？ | 不报提速百分比；报可数事件（目标摩擦的复现率）+ 区间 + 混杂；样本不足就写「数据不足」；装前可选有 / 无对照 | §5.5；[evaluation.md](../plans/evaluation-module.md) |
| 和 cc-switch、skills.sh、插件市场有什么不同？ | 它们管「装什么、怎么装」，按流行度排序；Orbit 管「为什么装、装哪一个、装了有没有用」，并用它们做通道与先验 | §2.9、§2.10 |
| agentsview 也能跨 Agent、本机、长期归档？ | 能看会话不是差异点；它止于规则文本，Orbit 把诊断连到安装和效果；我们移植了它的检测器（MIT） | §2.8 |
| 会不会变成监控工具？ | 只做个人工具，不出团队排行、不做跨用户比较；人格命名中性、标「实验性」 | §5.2 |
| 怎么赚钱？ | 商业假设（待验证）：Lite 免费、Advanced 付费，参照 16Personalities 的「免费给类型、付费卖深度」；个人价格锚是 WakaTime Premium $14 / 月，团队平台 $29–59 / 人 / 月 | §2.11、§2.13 |

### 5.5 可直接引用的外部论据

| 论点 | 数字 | 用在哪 | 来源 |
| --- | --- | --- | --- |
| 感觉不可靠，必须测 | METR 随机对照：16 位资深开发者用 AI 实际慢 19%，事后自认快 20% | 为什么不写提速百分比、为什么要装后对照 | [arXiv 2507.09089](https://arxiv.org/abs/2507.09089) |
| 通用最佳实践互相矛盾 | ETH：LLM 生成的上下文文件让成功率 −0.5% / −2%（不显著），成本 +20% / +23%；另一研究：有 AGENTS.md 时运行时间中位数 −28.64%、输出 token −16.58% | 为什么要对每个人就地测量 | [arXiv 2602.11988](https://arxiv.org/abs/2602.11988)、[arXiv 2601.20404](https://arxiv.org/abs/2601.20404) |
| 生成 skill 不一定有用 | SkillsBench：策展 skill 平均 +16.6pp，但 87 个任务中 13 个变差；模型自写 skill 比不用低 8.1–11.5pp；1 个 skill +18.0pp，2–3 个 +19.0pp，≥ 4 个 +10.1pp | 为什么生成不是卖点、为什么一次只推 2–3 个 | [arXiv 2602.12670](https://arxiv.org/abs/2602.12670) |
| 装第三方的东西有风险 | 31,132 个 skill 中 26.1% 至少有一处漏洞，带脚本的是纯指令型的 2.12 倍；Snyk 扫描 3,984 个，13.4% 严重、76 个恶意 | 为什么要预览、来源白名单与撤销 | [arXiv 2601.10338](https://arxiv.org/abs/2601.10338)；[Snyk ToxicSkills](https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub)（原页因证书错误未能打开，数字来自二手转述，未逐字核实） |
| 让 LLM 通读整段日志找问题不可靠 | TRAIL：最好的模型定位错误准确率 11%；Who&When：步级归因 14.2% | 为什么 AI 只判短候选 | [arXiv 2505.08638](https://arxiv.org/abs/2505.08638)、[arXiv 2505.00212](https://arxiv.org/abs/2505.00212) |
| 人格报告要数据先于文案 | Spotify 2024 用泛化 AI 内容，正面情绪 50.5% → 41.5%；2025 回归数据，首日 5 亿次分享 | 为什么人格卡上放数字证据 | §2.13 |

## 6. 待验证

本文涉及、需要真实数据或实测才能定的技术假设：

| # | 假设 | 怎么验证 | 影响 |
| --- | --- | --- | --- |
| V1 | 同一类任务能在不同 Agent 的日志上一致识别，跨 Agent 对比才有意义 | 用 PR #9 的 Claude Code 与 Codex 数据，抽样人工核对任务分类 | 时刻 1（§5.1）与差异化 1 |
| V2 | 个人每周的同类任务够多，7 天对照能给出有意义的区间 | 在真实历史上回放：前后各 ≥ 5 个会话的覆盖率 | 差异化 3；Lite 的效果一句话 |
| V3 | 几个月历史的首屏时间可接受 | PR #11 增量导入在真实数据上计时 | 门槛「首次结果快」 |
| V4 | 读取 `~/.claude/usage-data/` 的 session-meta 结构作对照与冷启动是稳定的 | 跨 Claude Code 版本比对字段 | T1 对策② |
| V5 | 能识别 `/insights`、`/doctor` 已给过的建议并去重 | 用 `yhyfhgs` 本机报告做对照 | 门槛「不重复官方」 |
| V6 | 读取 SpecStory、Entire、claude-mem 的产物作补充数据源可行，且授权方式清楚 | 各取一个样本做只读解析 | T4 对策 |
| V7 | token 汇总与 ccusage 的对账容差 | CI 中对同一份日志跑 ccusage 对账 | 门槛「解析正确」 |

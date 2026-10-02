# Orbit 调研总结：主流 Agent、设计哲学、开源项目与算法选型

> 状态：调研 · 维护者 `yhyfhgs` · 核对版本 main `0c96334` · 适用：Advance / Lite（另注明处除外）

> 日期：2026-10-02。面向 Advanced 版（Lite 是其子集），服务分析、推荐、AI、评测四类后端，以及一键安装（模块 8）与前端（模块 4、9）。
>
> 本文整合四组调研：主流编程 Agent 的内置功能与设计；官方文档、工程博客与 2026 年实证论文中的设计哲学；用量与额度、账号、多 Agent 管理、会话可视化四类开源项目；分析 / 推荐 / AI / 评测的算法选型。会话落盘格式见 [docs/research/agent-sessions/](../research/agent-sessions/README.md)，数据获取、标准化与生态索引见 [data-acquisition.md](../plans/data-acquisition.md)，本文不重复。各模块的具体设计见 [analysis.md](../plans/analysis-module.md)、[recommendation.md](../plans/recommendation-module.md)（含安装与效果追踪）、[ai.md](../plans/ai-module.md)、[evaluation.md](../plans/evaluation-module.md)。
>
> 标注：外部事实就地附链接，源码链接固定到调研时的 commit；「本机实测」指 2026-10-02 在 `yhyfhgs` 本机的只读测量（只看结构与计数，不读内容）；「未核实」指只有二手来源；「待验证」指需要用真实数据验证的技术假设。
>
> Demo 页面编号：A1 概览、A2 协作人格、A3 会话与轨迹、A4 工具调用、A5 项目习惯、A6 情绪与语义、A7 优化建议、A8 资源库、A9 生成工坊（源码在 [prototypes/advance/src/js/](../../prototypes/advance/src/js/) 的 `40`–`48` 号文件），另有安装浮层、「问本地 Agent」、菜单栏面板与 HUD。

## 1. 结论先行：15 条设计决定

| # | 决定 | 调研依据 | 落点 |
| --- | --- | --- | --- |
| 1 | **定位在「跨 Agent 证据 + 可撤销安装 + 装后验证」，不以单 Agent 报告或「会生成 skill」为卖点。** 差异只放在官方做不到的五件事：同一个人跨 Agent 对比、长期本地归档、每条结论能回到证据、一次安装写入多个 Agent 且可撤销、装后效果对照。 | 单 Agent 的同类能力都已内置或开源：Claude Code 有 [`/insights`、`/doctor`、`/skill-doctor`](https://code.claude.com/docs/en/commands)；Codex [Memories](https://learn.chatgpt.com/docs/customization/memories.md) 的合并代理会[自动写 skill](https://github.com/openai/codex/blob/b707714ae4200db0a0385da24b3981d99139fa62/codex-rs/memories/write/templates/memories/consolidation.md#L687-L724)；Hermes 有[学习闭环与 curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator)；[SpecStory Lore](https://github.com/specstoryai/getspecstory/tree/main/lore) 已开源「跨 Agent 历史 → skill → 安装」。Claude Code 默认只保留 30 天会话（桌面版与 Cowork 自 2.1.248 起例外，见 [claude-directory](https://code.claude.com/docs/en/claude-directory)） | 全部模块；路演开场直接对比 `/insights`；A1 |
| 2 | **后端主链路是预定义代码路径的 workflow，不是把日志交给一个 Agent。** 导入 → 指标 → 逐会话 facet → 聚合 → 匹配 → 生成 → 校验，每个 LLM 步骤后接代码 gate（schema、枚举、引用的会话与原话真实存在），不通过就重试一次再降级为确定性结果。Agent 只用于用户主动发起的只读深度诊断，有预算上限。 | Anthropic 区分 workflow 与 agent，要求从最简单的方案起步（[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)）；OpenAI 指南认为规则能解决就不必用 agent（[A practical guide to building agents](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)）；LLM 在长轨迹里定位错误的准确率很低（[TRAIL](https://arxiv.org/abs/2505.08638) 最好模型 11%，[Who&When](https://arxiv.org/abs/2505.00212) 步级归因 14.2%） | [ai.md](../plans/ai-module.md) |
| 3 | **分析层不开 AI 也要让 Demo 每页接上真实数据。** 约 40 个确定性指标分七类；摩擦检测移植 agentsview（MIT），长度阈值从字节改为字符、补中文词表；直接借用 Hermes 验证证据账本、pi 缓存重复计费、dsh 与 Kimi 的 3 / 5 / 8 次重复调用阈值、Kimi Issues 闭集。 | `/insights` 的 session-meta 是纯代码统计（[costs](https://code.claude.com/docs/en/costs)）；[agentsview friction](https://github.com/kenn-io/agentsview/tree/d37642206051dababc436635024676c17dddac45/internal/friction)；[verification_evidence.py](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/agent/verification_evidence.py)；[cache-stats.ts](https://github.com/earendil-works/pi/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/src/core/cache-stats.ts#L56)；[toolDedupeService.ts](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/packages/agent-core-v2/src/agent/toolDedupe/toolDedupeService.ts#L34)；[issues.ts](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/apps/vis/web/src/lib/issues.ts) | [analysis.md](../plans/analysis-module.md)；A1、A3、A4、A6 |
| 4 | **LLM 产出的标签一律是闭集枚举 + `other` + JSON Schema，缓存键带版本。** 缓存键 = 会话内容哈希 + `prompt_version` + `schema_version` + `model_id`。 | 本机实测：49 个 `/insights` facet 文件里，开放字段 `goal_categories` 漂移出 181 种键，`friction_counts` 出现 21 种（含 `api_error` 与 `api_errors` 这类同义重复），写成枚举的字段则稳定；`/insights` 的 facet 缓存不带提示词版本 | [ai.md](../plans/ai-module.md)、[analysis.md](../plans/analysis-module.md) |
| 5 | **调用本机 Agent 用最小配置、隔离、打包。** Claude 用 `--safe-mode --tools "" --system-prompt-file … --no-session-persistence --json-schema`，Codex 用 `exec --ephemeral --ignore-user-config --ignore-rules --output-schema`；一次调用放 5–10 个会话的摘要；Orbit 自己的调用不落成用户会话，导入时再按标记与 cwd 过滤；分析调用不给联网与写入能力。 | 本机实测固定开销：Claude 默认约 2.7 万输入 token，最小配置约 0.55–0.73K，加结构化输出后 2 轮合计约 1.3–1.5K；Codex 默认约 2.09 万，最小约 0.92–1.46 万（§2.4）。会话日志同时含私有数据与不可信内容，再给对外通信能力就凑齐了 [lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) | [ai.md](../plans/ai-module.md) |
| 6 | **推荐是问题驱动的，机制由代码决策表选，不让模型自由选。** 同一约定被纠正 ≥ 2 次 → 规则；同一流程第 3 次出现 → skill；必须每次发生或规则写入后仍被违反 → hook；习惯问题 → 只给建议、不装东西；规则过长或扩展闲置 → 做减法。知识库种子取官方触发条件表、五种失败模式与官方内置功能清单。 | Claude Code 官方的「何时加什么」与常见失败模式（[features-overview](https://code.claude.com/docs/en/features-overview)、[best-practices](https://code.claude.com/docs/en/best-practices)）；[Steering Claude Code](https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more) 的反模式；OpenAI 把反复违反的规则升级为 lint（[Harness engineering](https://openai.com/index/harness-engineering/)） | [recommendation.md](../plans/recommendation-module.md)；A7 |
| 7 | **排序逐项可解释，推荐要克制。** priority = 每周节省 × 适用度 × P(有效) ÷ 成本 − 风险，再用 MMR 去重；卡片显示常驻与触发 token 成本；一次最多推荐 2–3 个 skill；带频控与「不再提示」；不按热门排序。 | 与 [RICE](https://www.intercom.com/blog/rice-simple-prioritization-for-product-managers/) 同构；[MMR](https://doi.org/10.1145/290941.291025)；[SkillsBench](https://arxiv.org/abs/2602.12670)：1 个 skill +18.0pp、2–3 个 +19.0pp、≥ 4 个只有 +10.1pp；Claude 插件提示每 3 个会话最多一次（[relevance](https://code.claude.com/docs/en/plugins/relevance)）；插件成本拆成常驻与调用时两部分（[measure](https://code.claude.com/docs/en/plugins/measure)）；后端 MVP 已定「推荐由画像与瓶颈共同支持、不按热门」（[Issue #4](https://github.com/ActionMesh-AI/Hackathon/issues/4)） | [recommendation.md](../plans/recommendation-module.md)；A7、A8 |
| 8 | **生成的定位是「策展 + 验证」。** 能匹配到审查过的现成条目就推荐现成的；生成物用模板 + 填槽 + 四道自检（规范校验、静态安全扫描、历史回放 dry-run、judge），内容只取用户已验证成功的轨迹与纠偏证据，写教训不写事故经过。 | LLM 生成的 AGENTS.md 让成功率 −0.5% / −2%（不显著）而成本 +20% / +23%（[ETH](https://arxiv.org/abs/2602.11988)）；模型自写 skill 比不用低 8.1–11.5pp，策展 skill 平均 +16.6pp 但 87 个任务中 13 个变差（[SkillsBench](https://arxiv.org/abs/2602.12670)）；Hermes 的[复盘提示词](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/agent/background_review.py#L385)与 [skill_linter](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/tools/skill_linter.py) | [ai.md](../plans/ai-module.md)、[recommendation.md](../plans/recommendation-module.md)；A9 |
| 9 | **安装用「公共格式 + 各 Agent 适配器」。** 规则以项目 `AGENTS.md` 为单一来源（Claude 侧放只含 `@AGENTS.md` 的 CLAUDE.md），skill 写 `.agents/skills/`，hook 与权限规则按各家语义分别渲染；无法映射的项在预览里列出。 | 格式在收敛、语义仍分裂：Claude 有 CLAUDE.md 时默认不读 AGENTS.md（[memory](https://code.claude.com/docs/en/memory)）；Codex 的非托管 hook 要按哈希信任后才运行（[Codex hooks](https://learn.chatgpt.com/docs/hooks.md)）；权限冲突裁决三家不同（§2.3） | [recommendation.md](../plans/recommendation-module.md)（安装）；安装浮层 |
| 10 | **每次写入都能单条撤销，所有权只声明不推断。** 预览内容哈希绑定确认；写入用可识别的标记块；ledger 记录 actor、action、证据与前后 sha256，支持单条与整批回滚，回滚前再快照；用户改过的条目转为只读；只归档不删除；默认写用户层或 local 层。 | Claude [`/import`](https://code.claude.com/docs/en/commands) 的 `--dry-run` → `--yes=<digest>`；Hermes [curator ledger 与单条回滚](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/website/docs/user-guide/features/curator.md)；Kimi 导入器的[来源标记块](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/packages/agent-core-v2/src/agent/profile/context.ts#L79) | [recommendation.md](../plans/recommendation-module.md)（安装）；A7、安装浮层 |
| 11 | **装后效果分三层报告，主指标是目标摩擦的复现率。** ① 是否触发；② 机械效果（被替代的事件直接计数）；③ 行为效果（前 14–28 天对后 7 天，覆盖组对未覆盖组做双重差分，按天 bootstrap 给区间）。推荐生成时预先登记目标与护栏指标；样本不足显示「数据不足」；指标恶化即建议撤销；不宣称「提速 X%」。 | Cursor Bugbot 以 resolution rate 衡量，从 52% 提到 70% 以上（[Building Bugbot](https://cursor.com/blog/building-bugbot)）；METR 随机对照中开发者用 AI 实际慢 19% 却自认快 20%（[arXiv 2507.09089](https://arxiv.org/abs/2507.09089)）；[双重差分](https://mixtape.scunning.com/09-difference_in_differences)；[回归均值](https://doi.org/10.1093/ije/dyh299) | [evaluation.md](../plans/evaluation-module.md)、[recommendation.md](../plans/recommendation-module.md)；A7 |
| 12 | **评测以历史回放为主轴，多层叠加。** 检测器 κ ≥ 0.6 才上线；judge 交换顺序并用金标校正；装前有 / 无对照每臂 3 次（用户同意后才跑）；公开 benchmark 只作先验，与用户自己「模型 × 档位」的结果收缩合并。 | [Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) 的瑞士奶酪模型；[claude plugin eval](https://code.claude.com/docs/en/plugin-evals)；pi 的[配对评测协议](https://github.com/earendil-works/pi/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/evals/README.md)；公开结论互相矛盾（ETH 称上下文文件成本 +20%，[Lulla 等](https://arxiv.org/abs/2601.20404)称运行时间中位数 −28.64%），只能就地测量 | [evaluation.md](../plans/evaluation-module.md) |
| 13 | **用量与额度是分析的分母，不做又一个额度监控器。** Codex 用 rollout 里的 `rate_limits` 离线重建燃尽曲线，Claude 走 statusline 与 Hooks；不读凭据调未公开端点；定价以 LiteLLM 为主、models.dev 兜底，未定价不显示 $0；ccusage 作成本对账基准。Advanced 加一页（或 A1 的标签页），Lite 只放一张卡。 | 研读的用量、额度、账号类开源项目全部停在「量」上（§4）；Anthropic 不允许第三方收集或中转 Claude.ai 凭据（[legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)）；本机实测 Claude Code 输入侧 token 98.2% 是缓存读取，缓存写入分 5 分钟 ×1.25 与 1 小时 ×2（[prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)） | [analysis.md](../plans/analysis-module.md)、[data-acquisition.md](../plans/data-acquisition.md)；A1、新增「用量与额度」视图 |
| 14 | **A3 时间线重做为「脊柱 overview + 语义泳道 + 按轮次的事件账本 + 检查器」。** 默认「活跃时间」投影、空闲折叠、永不横向滚动；色相只表示事件类别，红色只给失败；规则检测的关键时刻画实心，AI 推断画空心并附引用。 | Demo 实测：mac-14 下可见绘图区仅 332px，而 SVG 宽 686px，必须横向滚动；dsh [ui-trajectory](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/client/ui-trajectory/README.zh.md)、Langfuse [响应式时间线](https://langfuse.com/changelog/2026-08-28-responsive-timeline)、[Perfetto UI](https://perfetto.dev/docs/visualization/perfetto-ui)、Instruments（[WWDC19-411](https://developer.apple.com/videos/play/wwdc2019/411/)） | A3；[analysis.md](../plans/analysis-module.md)（关键时刻） |
| 15 | **界面先给结论、数字说明来源、样本不够不下结论。** 每张图标题写结论句；每个数字带来源与新鲜度标签（官方 / 官方缓存 / 估算 / 过期 / 无数据）；人格与健康分标「实验性」并按区间判定；删掉需要社区数据的 Demo 文案。 | Apple 建议图表标题写结论（[WWDC22-110342](https://developer.apple.com/videos/play/wwdc2022/110342/)）；Fitness 趋势要累计 180 天数据才显示（[Apple 支持](https://support.apple.com/108359)）；tokentelemetry 的[能力状态](https://github.com/VasiHemanth/tokentelemetry/blob/main/docs/design/native-quota-limits.md)；Demo A8「同为 DIMV 的用户安装后冲突减少 72%」与 A2「与全体用户比较」没有任何数据通路 | 全部页面；A2、A8 |

## 2. 主流 Agent 对比

### 2.0 结论

1. **官方已经做了 Orbit 叙事的一半，但只在各自的 Agent 里。** 共同缺口：都是单 Agent；都是一次性快照，没有固定口径的纵向趋势；建议停在复制粘贴，没有预览 → 安装 → 撤销 → 效果追踪的闭环；除 Claude 面向插件作者的 `claude plugin eval` 外，没有对推荐项做装前装后评测。
2. **扩展格式在收敛，语义仍然分裂。** AGENTS.md、[Agent Skills 规范](https://agentskills.io/specification)、Claude Code 式 command hook（stdin JSON、退出码 2 阻断）被多数 Agent 采用；但规则加载顺序、权限冲突裁决、hook 的信任与失败语义各不相同，安装层必须按 Agent 适配。
3. **记忆与自我改进**：Hermes 是唯一内置学习闭环（复盘写记忆与 skill + curator 生命周期）的；Codex 有 Memories 且能自动写 skill；Claude Code 有 auto memory；Kimi、pi、dsh、OpenCode 没有记忆，也不自动生成 skill。
4. **「能看会话」不是差异点**：dsh、Kimi、pi 自带轨迹视图，[HF Agent Trace Viewer](https://huggingface.co/docs/hub/agent-traces) 原生读取 Claude Code、Codex、pi 的会话文件。
5. **headless 调用必须用最小配置**：默认配置每次 1.5–3.7 万 token 的固定开销，且会写入用户的会话历史。

### 2.1 内置分析、记忆与自我改进

| Agent（依据版本） | 内置分析 / 洞察 | 记忆与自我改进 | 会话存储 |
| --- | --- | --- | --- |
| Claude Code（本机 2.1.285） | `/insights`：逐会话确定性统计（session-meta）+ LLM facet + 7 个并列分节 + At a Glance，单次最多 200 个新会话，报告随 `cleanupPeriodDays` 清理（[costs](https://code.claude.com/docs/en/costs)）；`/usage` 按 skill、子代理、插件、MCP 归因额度，并给 prompt cache miss 原因；`/context`；`/doctor`（未用扩展对比上下文成本、CLAUDE.md 瘦身、`prompt-audit` 审计过时与冲突指令，先报告后修改）；`/skill-doctor`；`/fewer-permission-prompts`（从会话生成只读命令 allowlist）（[commands](https://code.claude.com/docs/en/commands)）；status line 与 OTel（[statusline](https://code.claude.com/docs/en/statusline)、[monitoring-usage](https://code.claude.com/docs/en/monitoring-usage)） | CLAUDE.md（人写）+ auto memory（Claude 自写 user / feedback / project / reference 四类，`MEMORY.md` 每次加载前 200 行或 25KB）（[memory](https://code.claude.com/docs/en/memory)）；不自动生成 skill，生成靠 skill-creator 插件 | [claude-code.md](../research/agent-sessions/claude-code.md) |
| Codex（CLI 0.159.2） | `/status`、`/usage`（日 / 周 / 累计）；`codex debug prompt-input` 不调模型渲染模型可见输入；组织级 Usage Insights（[slash commands](https://learn.chatgpt.com/docs/developer-commands.md?surface=cli)、[Usage Insights](https://learn.chatgpt.com/docs/enterprise/usage-insights.md)） | Memories 两阶段（本地默认关闭）：逐线程抽取（会话空闲 ≥ 6 小时、每次启动最多 2 个、租约防重复、密钥脱敏）→ 全局合并代理更新记忆并可写 `skills/<name>/SKILL.md`，剩余额度 < 25% 时跳过（[Memories](https://learn.chatgpt.com/docs/customization/memories.md)、[源码 README](https://github.com/openai/codex/blob/b707714ae4200db0a0385da24b3981d99139fa62/codex-rs/memories/README.md)、[默认值](https://github.com/openai/codex/blob/b707714ae4200db0a0385da24b3981d99139fa62/codex-rs/config/src/types.rs#L55-L60)）；Computer History 发现重复工作时建议 skill 或 automation（[文档](https://learn.chatgpt.com/docs/customization/computer-history.md)）；Record & Replay 看一次演示起草 skill；`tool_suggest` 让模型中途建议装插件（[源码](https://github.com/openai/codex/blob/b707714ae4200db0a0385da24b3981d99139fa62/codex-rs/tools/src/request_plugin_install.rs#L16)）；`/import` 能导入 Claude Code 的配置、项目记忆与近 30 天会话（[Import](https://learn.chatgpt.com/docs/import.md)） | [codex.md](../research/agent-sessions/codex.md) |
| Kimi Code（2.1.1，源码 `21406fb`） | `/usage`、`/status`；`kimi vis` 本地可视化（Wire / Context / Timeline / Subagents / Tasks / Logs）+ Issues 闭集抽屉（[kimi-command.md](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/docs/zh/reference/kimi-command.md)、[analysis.ts](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/apps/vis/web/src/lib/analysis.ts)）；匿名遥测约 80 个事件，默认开启、可关（[events.ts](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/packages/agent-core-v2/src/app/telemetry/events.ts#L599)） | 无记忆；`/sub-skill` 整理 skill 库：只读评审 → 用户确认 → 带时间戳备份后执行（[review/SKILL.md](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/packages/agent-core-v2/src/features/skill/catalog/builtin/sub-skill/review/SKILL.md)）；目标模式把目标写成完成契约（[write-goal.md](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/packages/agent-core-v2/src/features/skill/catalog/builtin/write-goal.md)） | agent-sessions 未覆盖，见 RS-05 |
| pi（v1.0.0，源码 `7fbbd5f`） | 页脚实时成本；`/session` 拆出缓存命中率、按实际解析模型的成本、缓存重复计费（Cache Re-billed）；缓存保温（空闲到 TTL 的 90% 时刷新，预期节省 ≥ $0.05 才发）（[cache-stats.ts](https://github.com/earendil-works/pi/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/src/core/cache-stats.ts#L56)、[cache-warmer.ts](https://github.com/earendil-works/pi/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/src/core/cache-warmer.ts#L16)）；HTML 导出带会话树侧栏（[template.js](https://github.com/earendil-works/pi/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/src/core/export-html/template.js#L371)） | 无；由用户或 agent 显式写 AGENTS.md、skill、extension（[作者博客](https://mariozechner.at/posts/2025-11-30-pi-coding-agent/)） | [pi.md](../research/agent-sessions/pi.md) |
| Hermes Agent（v0.21.5，源码 `be5e9f7`） | `hermes insights` / `/insights` 是纯 SQL 聚合：有无定价的模型分列、估算与实际成本、模型 / 平台 / 工具 / skill 排行、星期 × 小时、最长连续活跃天、Top 会话（[insights.py](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/agent/insights.py#L85)）；验证证据账本 + 结束守卫（改了代码没验证就想结束会被追问）；`/journey` 学习历程图 | 学习闭环：`MEMORY.md`（2,200 字符）+ `USER.md`（1,375 字符）以冻结快照注入；每 10 个用户轮次 / 10 次工具迭代后台 fork 复盘，写记忆与 skill；curator 按 14 天未用 → stale、30 天 → 归档管理 agent 自建 skill，可选 LLM 合并，ledger + 单条回滚；`write_approval` 开启后写入先进暂存区（[memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)、[skills](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/website/docs/user-guide/features/skills.md)、[curator.py](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/agent/curator.py#L209)） | [hermes-agent.md](../research/agent-sessions/hermes-agent.md) |
| OpenCode（1.18.x，源码 `a79ecfe`） | `opencode stats`（按模型的 token 与成本、工具调用计数）；`export --sanitize`；`/share` 生成公开链接（配置 `share: auto` 会自动公开每个会话）（[cli.mdx](https://github.com/anomalyco/opencode/blob/a79ecfe109294909a239c98fb89f02979d5aa10b/packages/web/src/content/docs/cli.mdx)、[share.mdx](https://github.com/anomalyco/opencode/blob/a79ecfe109294909a239c98fb89f02979d5aa10b/packages/web/src/content/docs/share.mdx)）；官方公开站 [OpenCode Data](https://opencode.ai/data) 给出全量模型使用排行 | 无 | [opencode.md](../research/agent-sessions/opencode.md) |
| DeepSeek Harness（0.2.0-rc.2，本机 0.1.1-rc.2） | `sessionStats` 投影：turns、steps、LLM 与工具耗时、TTFT、解码（[types.ts](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/session/session-stats/src/types.ts#L22)）；消息级赞 / 踩 + 7 类固定反馈写入会话日志（[command-feedback](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/feedback/command-feedback/src/index.ts#L30)）；重复调用提醒；`ui-trajectory` 轨迹视图 | 无；官方只给 3 个默认关闭的第三方记忆 MCP 参考配置（[mcp-memory.md](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/docs/user/guide/mcp-memory.md)） | [dsh.md](../research/agent-sessions/dsh.md) |
| Gemini CLI / Antigravity | Gemini CLI 有 `/stats` 计数与 OTel（来自[第三方教程](https://wpreset.com/how-to-check-gemini-cli-and-api-usage/)，未核实）；Code Assist 的企业指标在 Cloud Monitoring（[文档](https://docs.cloud.google.com/gemini/docs/monitor-gemini)）；Antigravity 是否有同类功能未核实 | 未核实 | [data-acquisition.md](../plans/data-acquisition.md) §3.2 |
| Copilot CLI | 只有组织级指标：用量与代码生成看板（[GA](https://github.blog/changelog/2026-02-27-copilot-metrics-is-now-generally-available)）、AI 采用阶段（[cohorts](https://github.blog/changelog/2026-05-29-copilot-usage-metrics-api-adds-cohorts-for-ai-adoption/)）、影响看板（[impact](https://github.blog/changelog/2026-07-22-new-copilot-usage-metrics-impact-dashboard/)）；没有个人会话洞察 | 未核实 | [data-acquisition.md](../plans/data-acquisition.md) §3.2 |

### 2.2 扩展点（安装层的直接输入）

| Agent | 规则 | Skills | Hooks | 插件 | MCP | 子代理 |
| --- | --- | --- | --- | --- | --- | --- |
| Claude Code | CLAUDE.md 从 cwd 向上逐级拼接 + `.claude/rules/*.md`（`paths` 条件加载）；有 CLAUDE.md 时默认不读 AGENTS.md（≥ 2.1.277）；建议每个文件 < 200 行（[memory](https://code.claude.com/docs/en/memory)） | `.claude/skills`（不读 `.agents/skills`）；列表预算占上下文 1%，每条 ≤ 1,536 字符（[skills](https://code.claude.com/docs/en/skills)） | 30 余个事件，处理器 command / http / mcp_tool / prompt / agent；只有退出码 2 或 JSON 决策才阻断，退出码 1 不拦截（[hooks](https://code.claude.com/docs/en/hooks)） | `.claude-plugin/plugin.json` + marketplace；`plugin validate / details / eval` | local / project / user 作用域；工具定义默认延迟加载（[mcp](https://code.claude.com/docs/en/mcp)） | `.claude/agents/*.md`，内置 Explore / Plan（[sub-agents](https://code.claude.com/docs/en/sub-agents)） |
| Codex | AGENTS.md / AGENTS.override.md，项目根到 cwd 每层最多一个，拼接上限 32 KiB（[AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md.md)） | `.agents/skills`、`~/.agents/skills`；列表 ≤ 上下文 2% 或 8,000 字符；Codex 专有字段写 `agents/openai.yaml`（[build skills](https://learn.chatgpt.com/docs/build-skills.md)） | `hooks.json` 或 `config.toml` 的 `[hooks]`，12 个事件；非托管 hook 按定义哈希信任后才运行（[hooks](https://learn.chatgpt.com/docs/hooks.md)） | `.codex-plugin/plugin.json`，与 ChatGPT 共用目录（[plugins](https://learn.chatgpt.com/docs/plugins.md)） | `config.toml` 的 `[mcp_servers]` | `.codex/agents/*.toml` |
| Kimi Code | AGENTS.md 链 + `~/.agents/AGENTS.md`；不读 CLAUDE.md；合计 > 32KB 告警 | `.kimi-code/skills`、`.agents/skills`；支持父子 skill（[skills.md](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/docs/zh/customization/skills.md)） | `config.toml` 的 `[[hooks]]` 只允许 4 个字段；退出码 2 阻断、其他错误放行；只有 PreToolUse / Stop / UserPromptSubmit 可阻断（[hooks.md](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/docs/zh/customization/hooks.md)） | `kimi.plugin.json`，GitHub 安装可钉 commit（[plugins.md](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/docs/zh/customization/plugins.md)） | `mcp.json`，另读项目根 `.mcp.json`；实验性 deferred | Markdown agent 文件，可直接加载 Claude Code 风格文件 |
| pi | 每个目录只取一个：`AGENTS.override.md` > `AGENTS.md` > `CLAUDE.md`；另有 `SYSTEM.md` / `APPEND_SYSTEM.md`（[resource-loader.ts](https://github.com/earendil-works/pi/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/src/core/resource-loader.ts#L185)） | Agent Skills 规范；`.pi/skills`、`.agents/skills`（[skills.md](https://github.com/earendil-works/pi/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/docs/skills.md)） | 无配置格式；写 TS extension，`pi.on("tool_call")` 可改参数或阻断 | pi package（npm / git，可钉版本）；`pi -e` 单次试用（[packages.md](https://github.com/earendil-works/pi/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/docs/packages.md)） | `mcp.json` + `exposure`（默认 codemode，不进上下文）（[mcp.md](https://github.com/earendil-works/pi/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/docs/mcp.md)） | 理念上不做会话内子代理 |
| Hermes | 每个会话只加载一种：`.hermes.md` > `AGENTS.override.md` > `AGENTS.md` > `CLAUDE.md` > `.cursorrules`（[context-files](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/website/docs/user-guide/features/context-files.md)） | `~/.hermes/skills`；项目 `.agents/skills` 需先信任项目；用户级 `~/.agents/skills` 要写进 `skills.external_dirs` | 4 套：shell hooks（兼容 Claude Code，首次使用征求同意）、Python 插件 hooks、网关 hooks、只观察的出站 webhook | `plugin.yaml` + Python；安装时静态扫描分 safe / caution / dangerous（[plugins.md](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/website/docs/user-guide/features/plugins.md)） | `config.yaml` 的 `mcp_servers` | 插件 hook 有 `subagent_start / stop`，配置方式未细读 |
| OpenCode | AGENTS.md（首个命中，否则回退 CLAUDE.md）+ `instructions` 数组（glob、URL）（[rules.mdx](https://github.com/anomalyco/opencode/blob/a79ecfe109294909a239c98fb89f02979d5aa10b/packages/web/src/content/docs/rules.mdx)） | `.opencode/skills`、`.claude/skills`、`.agents/skills` 都读（[skills.mdx](https://github.com/anomalyco/opencode/blob/a79ecfe109294909a239c98fb89f02979d5aa10b/packages/web/src/content/docs/skills.mdx)） | 无声明式 hook；JS / TS 插件钩子（`tool.execute.before` 中抛异常即阻断），还能改模型参数与系统提示（[plugins.mdx](https://github.com/anomalyco/opencode/blob/a79ecfe109294909a239c98fb89f02979d5aa10b/packages/web/src/content/docs/plugins.mdx)） | npm 包或 `.opencode/plugins/*.ts`；无官方市场 | `opencode.json` 的 `mcp` | `.opencode/agents/*.md`，`mode: primary / subagent`（[agents.mdx](https://github.com/anomalyco/opencode/blob/a79ecfe109294909a239c98fb89f02979d5aa10b/packages/web/src/content/docs/agents.mdx)） |
| DeepSeek Harness | `AGENTS.md` + `CLAUDE.md`（含 `.local.md`），内容相同只渲染一次，64KB 预算（[agent-instructions](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/context/agent-instructions/README.md)） | `.dsh/skills`、`.agents/skills`（[skill-filesystem](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/skill/skill-filesystem/README.md)） | hooks 桥直接读 Claude Code / Codex 的 `hooks.json`，只跑 command hook；HEAD 才有，本机 0.1.1 没有 | npm bundle + `cordis.patch.yml`；`--patch` 临时叠加 | YAML 插件行 | 子代理是插件，可把 Claude Code、Codex 当外部子代理 |
| Gemini CLI | `GEMINI.md` | 全局目录 `~/.gemini/skills`（据 [vercel-labs/skills](https://github.com/vercel-labs/skills)） | BeforeTool / AfterTool 等事件，配置位置未核实 | `gemini-extension.json`；扩展库 2,066 个，按 stars 排序（[extensions.json](https://geminicli.com/extensions.json)） | 扩展可带 MCP | 未核实 |
| Copilot CLI | `.github/copilot-instructions.md` | [awesome-copilot](https://github.com/github/awesome-copilot) 收录 444 个 | 插件 `hooks.json`：sessionStart、preToolUse 等 | `.github/plugin/` | — | `.agent.md` |

### 2.3 跨 Agent 安装：公共落点与适配差异

| 资源 | 公共落点 | 各家差异（适配器要处理的） | 来源 |
| --- | --- | --- | --- |
| 规则 | 项目 `AGENTS.md`；Claude 侧放一个只含 `@AGENTS.md` 的 CLAUDE.md | Claude 有 CLAUDE.md 时默认不读 AGENTS.md；Codex 拼接上限 32 KiB，`AGENTS.override.md` 会遮蔽新规则；Kimi 不读 CLAUDE.md；pi 与 Hermes 有 AGENTS.md 时不读 CLAUDE.md；dsh 两者都读。避免同一内容经 SessionStart hook、软链或导入被重复注入；写入用标记块，撤销只删自己的块 | [memory](https://code.claude.com/docs/en/memory)、[Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md.md)、[Kimi context.ts](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/packages/agent-core-v2/src/agent/profile/context.ts#L79) |
| Skill | 正文放 `.agents/skills/<name>/`（Codex、OpenCode、Kimi、pi、dsh 读），Claude 侧再放到 `.claude/skills/<name>`（软链是否被跟随待验证） | frontmatter 只用规范字段；手动触发在 Claude 写 `disable-model-invocation: true`，在 Codex 写 `allow_implicit_invocation: false`；触发词放 description 最前（两家列表预算都会截断描述）；Hermes 用户级目录要写进 `external_dirs` | [Agent Skills 规范](https://agentskills.io/specification)、[skills](https://code.claude.com/docs/en/skills)、[build skills](https://learn.chatgpt.com/docs/build-skills.md) |
| Hook | Claude Code 式 command hook：stdin JSON、退出码 2 阻断、stderr 写怎么改 | Codex 需用户在 `/hooks` 里按哈希信任，安装状态要有「已安装、未信任」；Kimi 只允许 4 个字段且出错放行；Hermes 首次使用征求同意；dsh 只有新版本有桥；pi 生成 TS extension；OpenCode 生成 JS 插件；同一事件的多个 hook 并行执行，不要让两个 hook 改写同一工具输入 | [hooks](https://code.claude.com/docs/en/hooks)、[Codex hooks](https://learn.chatgpt.com/docs/hooks.md)、[Kimi hooks](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/docs/zh/customization/hooks.md) |
| MCP | `{"mcpServers": {…}}` JSON；工具名统一为 `mcp__<server>__<tool>` | pi 加 `exposure`；Kimi 可设 deferred；Hermes 写 YAML；dsh 写插件行；推荐时附常驻 token 成本 | §2.2 |
| 权限 | 不共用规则文本 | 冲突裁决：Claude 按 deny → ask → allow 取首个命中；Codex 取最严格（forbidden > prompt > allow），复合命令拆开逐条判定；OpenCode 以最后一条命中为准 → 按 Agent 分别渲染并做冲突模拟 | [permissions](https://code.claude.com/docs/en/permissions)、[Codex rules](https://learn.chatgpt.com/docs/agent-configuration/rules.md)、[OpenCode permissions](https://github.com/anomalyco/opencode/blob/a79ecfe109294909a239c98fb89f02979d5aa10b/packages/web/src/content/docs/permissions.mdx) |
| 写入位置 | 用户层或 local 层（如 `.claude/settings.local.json`） | 不写托管层与团队共享层；写入前读托管配置，提示「会被组织策略覆盖」；settings / `config.toml` 这类共享文件做键级 diff 与备份 | [settings](https://code.claude.com/docs/en/settings)、[Codex config reference](https://learn.chatgpt.com/docs/config-file/config-reference.md) |

### 2.4 headless 调用与固定开销

| Agent | 最小配置调用 | 不落盘与隔离 | 固定开销 | 陷阱 |
| --- | --- | --- | --- | --- |
| Claude Code | 在 Orbit 自己的空目录、净环境（`env -i`）里运行：`claude -p --safe-mode --tools "" --system-prompt-file <固定提示> --no-session-persistence --output-format json --json-schema <schema> --max-turns 3 --effort low --max-budget-usd <上限> < /dev/null`（[headless](https://code.claude.com/docs/en/headless)、[cli-reference](https://code.claude.com/docs/en/cli-reference)） | `--no-session-persistence`（仍会建一个空的 `projects/<cwd>/memory/` 目录，导入时忽略）；`--safe-mode` 关闭 CLAUDE.md、skills、插件、hooks、MCP，订阅登录照常可用；`--bare` 只接受 API key | 本机实测（Haiku 4.5）：默认约 2.7 万（净环境）/ 3.7 万（继承 Claude Desktop 环境）；最小配置约 0.55–0.73K；加 `--json-schema` 至少 2 轮，合计约 1.3–1.5K | 不加 `--safe-mode` 时会在未信任目录执行项目 hooks 与 MCP；子进程继承 `CLAUDE_CODE_ENTRYPOINT`；stdin 不关闭会等 3 秒；`--max-turns 1` 与 `--json-schema` 冲突；用户开了 `alwaysThinkingEnabled` 时要显式关 |
| Codex | `codex exec --ephemeral --json --skip-git-repo-check -s read-only --ignore-user-config --ignore-rules --disable apps --disable plugins --disable memories -c agents.enabled=false --output-schema schema.json -o out.json < /dev/null`（[Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode.md)） | `--ephemeral`（实测不写 rollout、不写 threads 行，也不触发 memories） | 本机实测（CLI 0.159.2）：默认约 2.09 万；去掉用户配置约 1.46 万；再替换基础指令并关闭工具约 0.92 万；`--output-schema` 原生单轮，只多约 20 token | `--ignore-user-config` 时已信任的 hooks 是否仍运行待验证 |
| pi | `pi -p --no-session --no-tools --no-extensions --no-skills --no-context-files --mode json --system-prompt <固定提示>`（[cli.md](https://github.com/earendil-works/pi/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/docs/cli.md)） | `--no-session` | 未实测（系统提示本身很短） | — |
| Hermes | `hermes chat -q … --oneshot --format stream-json --source tool --ignore-user-config --ignore-rules --safe-mode`，或 `hermes -z`（[cli-commands](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/website/docs/reference/cli-commands.md)） | `--source tool`：第三方会话不出现在用户会话列表 | 未实测 | — |
| OpenCode | CLI 没有 schema 参数；用 `opencode serve` + SDK 的 `session.prompt({format: {type: "json_schema"}})`（[sdk.mdx](https://github.com/anomalyco/opencode/blob/a79ecfe109294909a239c98fb89f02979d5aa10b/packages/web/src/content/docs/sdk.mdx)） | 总是写库：用独立的 `OPENCODE_DB` + inline 配置关闭分享（能否压过用户的 `share: auto` 待验证） | 按源码估算约 6–10K（未实测） | 用户设了 `share: auto` 时 headless 会话也会被公开 |
| Kimi Code | `kimi -p … --output-format stream-json` | 文档未见不落盘开关 → 导入时排除 Orbit 自己的会话 | 未实测 | 固定 auto 权限 |
| DeepSeek Harness | `dsh --profile headless --json`（[headless README](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/bundle/headless/README.md)） | 无不落盘开关 → 导入时排除 | 未实测 | 轮内失败仍以 `final` 结束，要看退出码 |
| Copilot / Gemini | 参照 agentsview 的调用：Copilot `-p … --silent --no-custom-instructions --no-ask-user --disable-builtin-mcps`，Gemini 必须显式配置沙箱（[generate.go](https://github.com/kenn-io/agentsview/blob/d37642206051dababc436635024676c17dddac45/internal/insight/generate.go)） | 未核实 | 未实测 | 本机未装 |

调用前可以不花模型调用估算成本：`claude -p "/context"` 给出分类 token 数（本机默认约 2.84 万）；`codex debug prompt-input` 渲染模型可见输入（不含基础指令与工具 schema，只能当下限）。

### 2.5 Orbit 借鉴什么、避免重复什么

| Agent | 借鉴 | 避免重复 / 注意 |
| --- | --- | --- |
| Claude Code | `/insights` 的分层流水线（逐会话 facet 按 `sessionId` 与 `transcript_mtime` 缓存；超过 3 万字符先按 2.5 万字符切块摘要；再把统计量 + 50 条摘要 + 20 条摩擦细节 + 15 条「用户反复说的话」交给并列分节，最后单独写总结；见[社区逆向](https://web.archive.org/web/20260324085553/https://www.zolkos.com/2026/02/04/deep-dive-how-claude-codes-insights-command-works.html)）；session-meta 的 31 个字段作派生指标的对照答案与冷启动数据；`plugin details` 的常驻 / 调用成本拆分；插件 relevance 的信号词表（cwd、cli 命令名、hosts、filesRead glob、manifestDeps）作匹配字段；`plugin eval` 的有 / 无对照；`/import` 的哈希绑定确认；statusline 的 `rate_limits` | 不做单 Agent 叙述报告；不重做 `/doctor` 瘦身与 `/fewer-permission-prompts`，把它们和 auto mode 等官方功能列为一等推荐项（零安装，推荐前用 `claude --version` 探测）；transcript 是内部格式，只读不写；按版本做能力探测（本机 9 月一个月的会话跨 38 个版本） |
| Codex | Memories 的节流与安全（空闲阈值、每次少量、额度阈值、租约、失败退避、密钥脱敏、生成物目录做 git 基线 diff）；rollout 每次响应都带 `rate_limits`，可离线重建额度燃尽曲线 | 不做又一个「会话 → 记忆 → 自动 skill」；生成 skill 的差异放在跨 Agent 证据、装前装后评测、多格式输出与版本 diff；hook 安装要处理「需信任」 |
| Kimi Code | Issues 闭集（孤立调用、工具错误、输出截断、provider 过滤、max_tokens、未完成 step 或压缩、审批被拒）；Timeline 会话指标（上下文占用折线与峰值、≥ 3 秒的空闲间隙、活跃 / 墙钟时长、工具统计表）；重复调用 3 / 5 / 8 / 12 分级提示（第 12 次强制结束本轮并只允许文字交接）可改写成防死循环 hook；完成契约五要素（终态、证明、边界、循环、停止规则）；导入标记块 | 本机没有样本，连接器要先实测；遥测默认开启是反例，Orbit 不加默认开启的遥测 |
| pi | 缓存重复计费：`min(上轮 prompt, 本轮 prompt) − cacheRead`，≤ 1,024 视为噪声，原因只报可观察事实（空闲超 TTL、换模型；压缩后重置基线）；按实际解析出的模型拆成本；会话树可视化；evals 配对协议 | 尊重其「最小内核」哲学：不推荐 MCP、子代理、计划模式，改给 CLI + README、PLAN.md、tmux 等价做法 |
| Hermes | 复盘提示的四段结构（触发信号 → 动作优先级 → 教训写法 → 禁止项）；skill_linter 规则；curator 状态机（pin 与被定时任务引用的豁免，`use=0` 不作裁剪依据，只归档不删除）；ledger + 单条回滚；所有权只声明不推断；验证证据账本；安装扫描三档；区分人类输入与注入上下文的包装标签正则（[foreign_sessions.py](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/hermes_cli/foreign_sessions.py#L20)）；异模型复盘只送 digest（文档称成本降 3–5 倍、捕获一致） | 不再造学习闭环；对 Hermes 用户读它的 `.usage.json` 与 `.curator_ledger.jsonl` 来评估它自建的 skill |
| OpenCode | `export --sanitize` 的占位脱敏；OpenCode Data 作模型推荐的群体参照 | headless 总是写库、`share: auto` 会公开 → 必须隔离 |
| DeepSeek Harness | ui-trajectory 三件套作 A3 底座；7 类反馈（task-result、instruction-following、product-interaction、service-stability、resource-cost、security-privacy-permission、other）作摩擦闭集种子，日志里的反馈事件就是用户亲手打的标签；缺数据写「未记录」；把系统提示与工具目录变化做成一类事件并给 diff（[TrajectoryTable.tsx](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/client/ui-trajectory/src/client/TrajectoryTable.tsx#L1440)），作为安装前后的证据；patch 文件式安装（先 `--patch` 试用再合并） | 「能看会话」不是差异点 |

### 2.6 官方能力与 Orbit 模块的重叠度

| Orbit 模块 | 官方最接近的能力 | 重叠 | Orbit 的做法 |
| --- | --- | --- | --- |
| 协作人格 | `/insights` 的 interaction style | 高（仅 Claude） | 跨 Agent；由可复算指标驱动，叙述只作解释；看趋势 |
| 会话轨迹 | 各 App 自带会话查看 | 低 | 统一时间线、跨 Agent 对照、子代理与压缩可视化 |
| 摩擦 / 瓶颈 | `/insights` friction（建议词表会漂移） | 高（仅 Claude） | 闭集 + 跨 Agent 对比同类摩擦 + 直连推荐 |
| 规则 / Prompt | `/insights` 的 CLAUDE.md 建议、`/doctor`、Codex Memories | 高 | 跨 Agent 渲染、冲突与重复检测、体积校验、安装闭环 |
| Skills | Codex 合并代理自动写 skill、Computer History、skill-creator、SpecStory Lore | 高 | 证据门槛 + 装前装后评测 + 多格式输出 + 版本 diff |
| Hooks | 没有官方生成器 | 低 | 空白点：按摩擦生成 hook，分 Agent 渲染，历史回放 dry-run |
| 插件 / MCP | Claude relevance 信号（只对管理员白名单的市场生效，官方市场 315 个插件都没声明）、Codex `tool_suggest` | 中 | 基于历史证据匹配全量目录 + 常驻成本 + 安装闭环 |
| 子代理 | 无 | 低 | 识别反复探索 / 评审的模式 |
| 模型与思考强度 | `/usage` 行为标记、Codex 组织级按模型与推理强度拆分 | 低–中 | 个人层面的「花费 × 结果」建议 |
| 工作流 | `/insights` usage patterns、Codex 定时任务 | 中 | 序列挖掘 + 可安装的工作流模板 |
| 安装 → 撤销 → 7 天追踪 | `/import` 预览 + 摘要确认；`/doctor` 先报告后修改 | 低 | 核心差异 |
| 评测 | `claude plugin eval`、skill-creator evals | 中（仅 Claude 插件） | 跨 Agent 评测 harness，复用 §2.4 的调用配方 |

## 3. 设计哲学

按模块归类；原则一栏是转述，来源附链接。

### 3.1 分析

| # | 原则 | Orbit 的做法 | 来源 |
| --- | --- | --- | --- |
| A1 | 能用代码确定计算的不交给模型 | 指标、去重、聚合、检测器全部确定性；LLM 只做语义判断，可整体关闭 | [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)；[Skill best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) |
| A2 | 失败分类要从读真实轨迹的错误分析中长出来 | 摩擦闭集以官方五种失败模式、dsh 7 类反馈、`/insights` 摩擦键为种子；开放编码约 30 条 → 轴向编码 → 约 100 条不再出现新类别为止；每个任务段只记第一个上游失败 | [Hamel Evals FAQ](https://hamel.dev/blog/posts/evals-faq/)；[best-practices](https://code.claude.com/docs/en/best-practices) |
| A3 | 活动量不等于产出 | 信号分四级：S1 确定性结果（测试退出码、代码保留、问题是否复现）、S2 用户行为（纠正、不满意追问、中断、撤销）、S3 结构指标、S4 LLM 判断；推荐触发至少要 S1 或 S2；消息数、token、调用次数只算成本 | [Usage Insights](https://learn.chatgpt.com/docs/enterprise/usage-insights.md)；[Cursor semsearch](https://cursor.com/blog/semsearch) |
| A4 | Agent 没说、没做的事往往更重要 | 检测「缺席」：宣布完成前最后一次编辑之后没跑测试、构建或 lint | [Writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)；[verification_evidence.py](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/agent/verification_evidence.py) |
| A5 | 上下文是最需要管理的资源，越长越难回忆 | 上下文压力、压缩次数、峰值占用、会话中途换模型或改工具造成的缓存失效都是一级维度 | [Context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)；[Unrolling the Codex agent loop](https://openai.com/index/unrolling-the-codex-agent-loop/) |
| A6 | 小样本要诚实，按条件分层 | Wilson 下界排序、Beta-Binomial 经验贝叶斯收缩、按天 bootstrap；按 Agent 版本、模型与档位、项目规模分层（语义检索的收益在 1,000 个文件以上的仓库才明显） | [Evan Miller](https://www.evanmiller.org/how-not-to-sort-by-average-rating.html)；[Cursor semsearch](https://cursor.com/blog/semsearch) |
| A7 | 质量下降先查外因 | 纠正率或返工率上升时依次查：模型或档位变了、Agent 升级、上下文常逼近上限、压缩次数、常用 skill 被移除 | [Hermes troubleshooting](https://hermes-agent.nousresearch.com/docs/guides/troubleshooting-agent-quality) |
| A8 | 不夸大 AI 带来的收益 | 只报可数事件与带区间的变化；人格与健康分标「实验性」 | [METR](https://arxiv.org/abs/2507.09089) |

### 3.2 推荐（含安装）

| # | 原则 | Orbit 的做法 | 来源 |
| --- | --- | --- | --- |
| R1 | 规则只写从代码推不出、与默认不同的内容；仓库概览没有帮助 | 规则生成有白名单（猜不到的命令、风格差异、测试方法、仓库礼仪、环境怪癖、常见坑）与黑名单（可从代码推出的内容、通用惯例、空话）；每条至少 2 次纠正证据 | [best-practices](https://code.claude.com/docs/en/best-practices)；[ETH](https://arxiv.org/abs/2602.11988) |
| R2 | 必须每次成立的约束交给 hook，不靠文字 | 规则里出现「必须 / 每次 / 禁止」→ 提示改用 hook；写入后仍被违反 ≥ 2 次 → 升级为 hook 或 lint，错误信息写修复方法 | [features-overview](https://code.claude.com/docs/en/features-overview)；[Harness engineering](https://openai.com/index/harness-engineering/)；[Steering Claude Code](https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more) |
| R3 | skill 要精简、有适用边界与后备，数量要少 | 生成的 skill 写明何时不用；正文 < 500 行；一次推荐 ≤ 2–3 个 | [SkillsBench](https://arxiv.org/abs/2602.12670)；[Skill best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) |
| R4 | 写教训，不写日志 | 坑写成可推广的规则 + 一句原因，挂在对应步骤上；不写会话 ID、日期、PR 号与原话；没找到可行方法的失败尝试不能包装成流程 | [Hermes background_review](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/agent/background_review.py#L385) |
| R5 | AGENTS.md 是目录不是百科；小步做配置垃圾回收 | 规则文件过长时推荐拆分，而不是再加一条；定期只提一两个一分钟内能决定的改动 | [Harness engineering](https://openai.com/index/harness-engineering/) |
| R6 | 做减法和加法同样重要 | 14 天且 10 个会话未用的扩展建议停用（可恢复）；常驻 ≥ 2,000 token 的条目标黄；功能重叠的合并；已由 hook 强制的规则删除；缩短 description 后重跑触发评测 | [plugins/measure](https://code.claude.com/docs/en/plugins/measure) |
| R7 | 尊重目标 Agent 的设计哲学 | 每个条目标注适用 Agent 与在其他 Agent 上的等价做法；对 pi 不推 MCP、子代理、计划模式 | [pi 作者博客](https://mariozechner.at/posts/2025-11-30-pi-coding-agent/) |
| R8 | 按「缺什么」组织推荐，推荐要克制 | 每个摩擦先回答缺的是知识（规则 / skill）、能力（工具 / MCP / CLI）、反馈（测试 / 检查）还是约束（hook / lint）；有成熟 CLI 时优先 CLI；频控与「不再提示」 | [Harness engineering](https://openai.com/index/harness-engineering/)；[best-practices](https://code.claude.com/docs/en/best-practices)；[plugins/relevance](https://code.claude.com/docs/en/plugins/relevance) |
| R9 | 工作流建议用带验证回路的成熟模板 | 验证阶梯（提示模板 → `/goal` → Stop hook → 审查子代理）；长任务用进度文件 + 特性清单 + 一次一个特性；计划模式只推荐给多文件且返工多的任务；目标写成完成契约 | [best-practices](https://code.claude.com/docs/en/best-practices)；[long-running harness](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)；[write-goal.md](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/packages/agent-core-v2/src/features/skill/catalog/builtin/write-goal.md) |
| R10 | 预览与执行之间内容一变就要重新确认；所有权只能声明 | 预览绑定内容哈希；Orbit 安装的条目记录 owner 与内容哈希，用户改过即只读，只给建议 | [commands（/import）](https://code.claude.com/docs/en/commands)；[Hermes curator](https://github.com/NousResearch/hermes-agent/blob/be5e9f72c6681af9dfb75bf480f08844f1499949/website/docs/user-guide/features/curator.md) |
| R11 | 第三方 skill 不能直接转推 | 入库前静态扫描（脚本、联网、凭据路径、隐藏指令），带脚本的默认提高风险等级；预览展示所有会被模型读到的文本；MCP 与插件标注 lethal trifecta 三项能力 | [Agent Skills in the Wild](https://arxiv.org/abs/2601.10338)；[Malicious agent skills](https://arxiv.org/abs/2602.06547)；[lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) |

### 3.3 AI

| # | 原则 | Orbit 的做法 | 来源 |
| --- | --- | --- | --- |
| I1 | 代码骨架 + 少量 LLM 节点；agent 只用于开放问题，且只读 | 主链路是 workflow；L4 本机 Agent 只服务用户主动发起的「深度诊断」，只给只读查询工具与预算上限；凡是写用户配置的动作都走预览 → 确认 → 可撤销 | [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)；[A practical guide](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf) |
| I2 | 每个 LLM 步骤后插程序化检查 | gate 校验 schema、枚举、引用的会话 ID 与原话真实存在；失败重试一次，再失败降级为「无 AI 结论」并在 UI 说明 | 同上（prompt chaining） |
| I3 | 先用最强模型建评测基线，再逐级换小模型 | 节点注册表记录模板版本、档位与降级评测结果，评测分不降才换；会触发推荐的高影响标签三票两胜 | [A practical guide](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)；[Building Bugbot](https://cursor.com/blog/building-bugbot) |
| I4 | 省 token 按「不送 → 少送 → 送对 → 复用 → 封顶」 | 只分析新会话、跳过短会话；先用代码把旧工具输出换成占位（最轻的压缩）；每个 judge 只看相关片段；按任务设预算，超出退避后降级 | [Context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)；[Hermes compression](https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching) |
| I5 | 缓存只对完全相同的前缀生效 | 模板静态部分（指令、枚举 schema、示例）在前，证据在后；同批不换模型；结果缓存用精确键，不用语义缓存；Haiku 4.5 前缀 ≥ 4,096 token 才能缓存，Sonnet 5.5 / Opus 5.5 为 512 | [Unrolling the Codex agent loop](https://openai.com/index/unrolling-the-codex-agent-loop/)；[prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) |
| I6 | 开放字典一定漂移 | 闭集枚举 + `other` + JSON Schema（本机 `/insights` 实测见 §1 第 4 条） | [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) |
| I7 | 私有数据、不可信内容、对外通信不能同时具备 | 分析调用关工具、无网络；只发统计与摘要，发送前逐项预览与脱敏；推荐的 MCP 凑齐三项时明确警告 | [lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) |
| I8 | 旁路任务用可配置的便宜模型，换模型时改送摘要 | facet、标签、去重判断默认便宜档；跨模型复盘只送 digest（近期原文 + 早期摘要） | [Hermes memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory) |
| I9 | 后台任务不抢用户额度 | 会话空闲足够久才处理、每次只处理少量、额度低于阈值跳过、租约防重复、失败退避 | [Codex memories 默认值](https://github.com/openai/codex/blob/b707714ae4200db0a0385da24b3981d99139fa62/codex-rs/config/src/types.rs#L55-L60) |
| I10 | 模型不擅长在长轨迹里找问题 | 规则先定位候选片段，模型只对短片段做二元或闭集判断 | [TRAIL](https://arxiv.org/abs/2505.08638)；[Who&When](https://arxiv.org/abs/2505.00212) |

### 3.4 评测

| # | 原则 | Orbit 的做法 | 来源 |
| --- | --- | --- | --- |
| E1 | 多层叠加，任何单层结论都不对外宣称有效 | 数据回归 → 检测器 → 生成物质量 → 装前对照 → 装后追踪 → 推荐整体 → 人工抽查 | [Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) |
| E2 | 20–50 个真实失败就能起步；先验证 grader 再信分数 | 第一版评测集取三人真实会话里的失败片段；某条推荐全员零效果时先查指标与检测器定义（CORE-Bench 修好评分错误后从 42% 升到 95%） | 同上 |
| E3 | 二元判定，分别报告 TPR 与 TNR | 每个失败模式一个二元 judge；标注 200 个以上（失败 50–100）；κ ≥ 0.6 上线、≥ 0.7 视为可靠；成对比较交换顺序；judge 与生成器用不同模型 | [Eugene Yan product evals](https://eugeneyan.com/writing/product-evals/)；[LLM-as-judge](https://arxiv.org/abs/2306.05685) |
| E4 | 用 judge 估比例要校正 | Rogan–Gladen：p = (p_judge + Sp − 1) / (Se + Sp − 1)；金标积累后用 PPI 给有效区间 | [Rogan–Gladen](https://doi.org/10.1093/oxfordjournals.aje.a112510)；[PPI](https://arxiv.org/abs/2301.09633) |
| E5 | 有 / 无对照要配对、重复、先登记 | 每臂 3 次；「skill 是否被调用」只作生效指示，不计入 Δ；执行前登记全部队列；任一对缺臂就不报总体通过率；缺失遥测记为不可用而不是 0；一次重复不能证明稳定 | [plugin evals](https://code.claude.com/docs/en/plugin-evals)；[pi evals](https://github.com/earendil-works/pi/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/evals/README.md) |
| E6 | 触发评测要用近似反例 | 8–10 条应触发 + 8–10 条共享关键词的近似反例（尽量取自用户自己的提示），每条跑 3 次，60 / 40 划分，最多迭代 5 轮，按留出集选 description | [skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator) |
| E7 | 线上指标看「问题是否不再出现」 | 主指标是目标摩擦的复现率；同时看每周推荐条数（召回）与被采纳且有效的比例（精度），只追一边都会失衡 | [Building Bugbot](https://cursor.com/blog/building-bugbot)；[Bugbot learning](https://cursor.com/blog/bugbot-learning) |
| E8 | 推荐是干预，历史日志的评估有偏 | 第一天起记录候选集、分数、位次、展示概率与用户动作；末位留小比例随机探索位 | [Counterfactual evaluation](https://eugeneyan.com/writing/counterfactual-evaluation/)；[Open Bandit Pipeline](https://github.com/st-tech/zr-obp) |
| E9 | 稳定性看 pass^k | 同类任务「连续 3 次都做对」的比例比单次成功率更能说明配置是否可靠 | [Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) |

### 3.5 UI

| # | 原则 | Orbit 的做法 | 来源 |
| --- | --- | --- | --- |
| U1 | 标题写结论，图只做证据；小图静态、大图交互 | 每张图一句可独立阅读的结论；KPI 迷你线不画坐标与网格，点开进详情图；详情图约 4 条水平网格线 | [WWDC22-110340](https://developer.apple.com/videos/play/wwdc2022/110340/)、[WWDC22-110342](https://developer.apple.com/videos/play/wwdc2022/110342/) |
| U2 | 先概览，再缩放过滤，最后看细节 | A3 的 overview 选区就是下方明细的过滤器，与 Instruments 的 inspection range 一致 | [Shneiderman 1996](https://www.cs.umd.edu/~ben/papers/Shneiderman1996eyes.pdf)；[WWDC19-411](https://developer.apple.com/videos/play/wwdc2019/411/) |
| U3 | 一个颜色通道只表达一个维度 | 色相只表示事件类别（≤ 7 类）；红色只给失败并配 × 形状；审批、拒绝、中断、超时用图标；成本热力是可切换的替代着色；Agent 身份色不进时间线；构成图只给前 3 类上色 | [Few 颜色规则](https://www.perceptualedge.com/articles/visual_business_intelligence/rules_for_using_color.pdf)；Langfuse 移除热力叠加的说明见 [TimelineRowMetrics.tsx](https://github.com/langfuse/langfuse/blob/9a29212e855c60ffb86d1989b62918b3781d9652/web/src/features/traces/components/TraceTimelineDense/TimelineRowMetrics.tsx)；[Screen Time](https://support.apple.com/en-ie/guide/mac-help/mchlf2c0c770/mac) |
| U4 | 记录的事实与推断的结论分层 | 日志事实实心；阶段、情绪、关键时刻用紫色虚线 + 置信度放独立注释层，可一键隐藏；AI 结论带精确到事件的可点击引用 | [Tufte 分层与分离](https://meiert.com/en/blog/1-1-3-explaining-busyness-and-background-noise-on-websites/)；[DevTools annotations](https://developer.chrome.com/docs/devtools/performance/annotations)；[Docent citation.py](https://github.com/TransluceAI/docent/blob/8ab199c332180100f3882fc3e7323bd22ad50434/docent/docent/data_models/citation.py) |
| U5 | 诚实呈现 | 进行中的记录不虚构时长；缺字段写「未记录」；未定价不显示 $0；每个数字带来源与新鲜度；每个 Agent × 账号有能力状态 | [dsh ui-trajectory](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/client/ui-trajectory/README.zh.md)；[tokentelemetry](https://github.com/VasiHemanth/tokentelemetry/blob/main/docs/design/native-quota-limits.md) |
| U6 | 放大是长出细节，不是切换模式；永不横向滚动 | 三档密度（直方 / 图元 / 带标签）；每像素最多一个带计数的代表标记；空闲压缩只是坐标重映射，刻度与 tooltip 还原真实时刻 | [Langfuse 响应式时间线](https://langfuse.com/changelog/2026-08-28-responsive-timeline)；[Perfetto UI](https://perfetto.dev/docs/visualization/perfetto-ui) |
| U7 | 数据不够不下结论 | 人格与趋势设最少样本、固定比较窗口；不足时显示「再积累 N 个会话」 | [Apple Fitness](https://support.apple.com/108359) |
| U8 | 玻璃只给功能层 | 工具栏、侧栏、菜单、popover 用 Liquid Glass；卡片、图表、表格用实色 | [HIG Materials](https://developer.apple.com/design/human-interface-guidelines/materials) |
| U9 | 按系统实测度量还原原生感 | 本机 macOS 27.2 实测：统一工具栏高 52、交通灯直径 14、控件高 20 / 24 / 28 / 36、窗口圆角 16、页面标题 15 Semibold、侧栏默认 220（最小 144）、检查器 270；网页字体栈以 `system-ui` 开头（写 `-apple-system` 会让中文落到宋体），发丝线用 box-shadow | [HIG Typography](https://developer.apple.com/design/human-interface-guidelines/typography)；[WWDC25-356](https://developer.apple.com/videos/play/wwdc2025/356/) |
| U10 | 成本与证据可见 | 推荐卡显示常驻 / 触发成本（≥ 2,000 token 标黄）、证据回链、with / without / Δ；同时显示 Orbit 自己花了多少 token | [LLM patterns](https://eugeneyan.com/writing/llm-patterns/)；[plugins/measure](https://code.claude.com/docs/en/plugins/measure) |

## 4. 开源项目对比

### 4.0 结论

1. **用量、额度、账号类项目分五类，全部停在「量」上**：用量报表、额度监控、配置与路由、账号切换、账号池。没有一个把 token、成本、额度与会话行为、摩擦、优化措施及其效果连起来，这就是 Orbit 的空白。
2. **会话可视化已经成熟**：agentsview 覆盖 40+ Agent，dsh、Kimi、pi 自带轨迹视图。Orbit 的差异放在跨 Agent 的时间线、结论能跳回证据、建议能安装并追踪效果。
3. **多 Agent 编排容易被官方吸收**：vibe-kanban 已停止商业运营，Crystal 已废弃。Orbit 不做编排，只借状态检测。
4. **许可证**：MIT / Apache-2.0 可参考实现（保留声明）；AGPL、ELv2、CC BY-NC-SA、无许可证的只借设计。stars 与许可为 2026-10-02 读取，许可证已对照仓库 LICENSE 文件。

### 4.1 用量与额度

| 项目 | ★ · 许可 | 做法 | 可复用部分 | 注意 |
| --- | --- | --- | --- | --- |
| [ccusage](https://github.com/ccusage/ccusage) | 18.8k · MIT | 本地日志 → 日 / 周 / 月 / 会话的 token 与成本；18 个适配器 | 去重与计价规则（`message.id + requestId`、侧链重放、Codex 累计与增量、子代理重放）直接当连接器规格（[claude 适配器](https://github.com/ccusage/ccusage/blob/2cdd67e9aa46f3c4b3f8ac5e11385bf21cead5c5/rust/adapters/claude/src/README.md)）；在 CI 里跑 `--json --offline` 做对账 | 作基准，不作运行时依赖 |
| [tokscale](https://github.com/junhoyeo/tokscale) | 5.6k · MIT | 58 个客户端；价格查找链（自定义 → 精确 → 别名 → 去档位后缀 → 模糊）；任务归因与排行榜 | 路径表作连接器发现清单；成本记录带匹配级别；排除 LiteLLM 里 `github_copilot/` 这类 $0 订阅条目 | 额度功能会调各家未公开端点 |
| [splitrail](https://github.com/Piebald-AI/splitrail) | 222 · MIT | 文件监听的实时统计，另有 MCP 服务 | 证明「把洞察做成本地 MCP」可行（它只暴露用量计数） | — |
| [Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) | 8.7k · MIT | 实时 TUI、额度预测；官方读数 600 秒后降级为估算 | 新鲜度降级规则 | 手写价目表把 Fable 5.1 的缓存读取高估 4 倍（本机核对）→ 价目表不手写 |
| [CodexBar](https://github.com/steipete/CodexBar) | 22.1k · MIT | 菜单栏额度中心，86 个 provider；节奏显示「期望 vs 实际」与 ETA；明确不做历史分析 | 检测到已安装且用户开启时读 `codexbar usage --format json`（[cli.md](https://github.com/steipete/CodexBar/blob/b5435c75a285f5571664f39c741c9c203e745160/docs/cli.md)）；节奏算法（[UsagePace.swift](https://github.com/steipete/CodexBar/blob/b5435c75a285f5571664f39c741c9c203e745160/Sources/CodexBarCore/UsagePace.swift)） | 额度来自读凭据的接口，Orbit 不照做 |
| [OpenUsage](https://github.com/robinebers/openusage) | 4.3k · MIT | 菜单栏 + 本地 HTTP；无数据显示「No data」而非 $0；账号归属规则 | 「未归属」桶与无数据语义（[providers/claude.md](https://github.com/robinebers/openusage/blob/ab3e87bbb7c3e91205d64ef5be4baadc20d09c67/docs/providers/claude.md)） | 每日匿名 ping 不可关闭（[privacy.md](https://github.com/robinebers/openusage/blob/ab3e87bbb7c3e91205d64ef5be4baadc20d09c67/docs/privacy.md)），是反例 |
| [tokentelemetry](https://github.com/VasiHemanth/tokentelemetry) | 374 · MIT | 每个 Agent 的能力状态（未登录 / 会话过期 / 无套餐额度 / 不支持 / 读取失败），缺数据直接省略、不记 0 | UI 的能力状态 | — |
| [LiteLLM 价目表](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) / [models.dev](https://models.dev/api.json) | MIT / MIT | 4,453 条按 token 计价（含 1 小时缓存写入、priority / flex、长上下文档位）/ 225 个 provider 与模型元数据 | 主价目表 / 兜底价与模型能力字段，快照进 `catalog.db` | LiteLLM 的 `enterprise/` 目录不是 MIT |

### 4.2 账号、供应商与路由

| 项目 | ★ · 许可 | 做法 | 可复用部分 | 注意 |
| --- | --- | --- | --- | --- |
| [cc-switch](https://github.com/farion1231/cc-switch) | 139k · MIT | 一键切换 Claude Code、Codex、Gemini CLI 等的供应商，统一管理 MCP、Skills、Prompts，带用量面板 | 存储设计：增量水位 + 尾部指纹识别整体重写、行级 `input_token_semantics`、`request_model` 与 `pricing_model` 双列（[sql_helpers.rs](https://github.com/farion1231/cc-switch/blob/d0b57827e453fcab5620a89a4c452648ae371d42/src-tauri/src/services/sql_helpers.rs#L23)） | 最近的相邻产品：管配置与连接，不做行为分析与效果追踪，路演要讲清区别；其 OAuth 认证中心自述可能违反条款 |
| [claude-code-router](https://github.com/musistudio/claude-code-router) | 37.5k · MIT | 本地模型网关与路由 | 计费头与响应体分别归一 token 口径 | 代理形态不借鉴 |
| [ccs](https://github.com/kaitranntt/ccs) | 2.9k · MIT | 每个账号一个 `CLAUDE_CONFIG_DIR` / `CODEX_HOME` | 数据发现：会话散落在 `~/.ccs/instances/*`、`~/.ccs/codex-instances/*` | — |
| [claude-swap](https://github.com/realiti4/claude-swap) | 3.0k · MIT | 切换型（换登录）+ 隔离型（每账号一个目录）；按额度自动切号 | 软链共享会让同一文件出现在多个根下 → 先按 realpath、再按记录 ID 去重 | 自动切号、「先用快到期额度」不做；usage 端点约每小时 28–30 次 / 身份且被多个工具共享（[社区实测](https://github.com/realiti4/claude-swap/blob/3a4e5c14873eb5b32f182d55c68da98ac8c0db45/src/claude_swap/poll_policy.py)，未核实） |
| [codex-auth](https://github.com/Loongphy/codex-auth) | 2.8k · MIT | 替换 `auth.json` 切号；`--skip-api` 只读最新 rollout 的 `rate_limits` | 证明 rollout 可作额度来源；部分版本会写 `rate_limits: null`（[openai/codex#14880](https://github.com/openai/codex/issues/14880)） | API 方式自述可能违反条款 |
| 账号池 / 代理：[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)（53.7k · MIT）、[better-ccflare](https://github.com/tombii/better-ccflare)（271 · MIT）、[codex-lb](https://github.com/Soju06/codex-lb)（3.3k · MIT）、[sub2api](https://github.com/Wei-Shaw/sub2api)（43.2k · LGPL-3.0）、[Antigravity-Manager](https://github.com/lbjlaq/Antigravity-Manager)（31.9k · CC BY-NC-SA 4.0） | 见左 | 把订阅 OAuth 包成兼容 API、多账号负载均衡、按剩余额度调度 | 无 | 红线：不做账号池、代理转发、订阅共享；Antigravity-Manager 为非商用许可 |

多账号的直接影响是数据发现：切换型把多个账号的会话写进同一个目录，且普通终端会话不记录账号；隔离型每个账号一个数据根。Orbit 以「根目录 → 账号」归属，归属不了的进「未归属」桶，不承诺精确的按账号统计（[OpenUsage 的做法](https://github.com/robinebers/openusage/blob/ab3e87bbb7c3e91205d64ef5be4baadc20d09c67/docs/providers/claude.md)）。

### 4.3 多 Agent 管理

| 项目 | ★ · 许可 | 做法 | 可复用部分 | 注意 |
| --- | --- | --- | --- | --- |
| [claude-squad](https://github.com/smtg-ai/claude-squad) | 8.6k · AGPL-3.0 | tmux + git worktree 并行跑 Claude Code、Codex、Gemini、Aider | 无（只看思路） | AGPL，不复制代码 |
| [ccmanager](https://github.com/kbwo/ccmanager) | 1.3k · MIT | 不依赖 tmux 的多会话管理；按 CLI 配置的状态检测（busy / waiting / idle） | 菜单栏与 HUD 的「运行中 / 等你确认」检测策略 | — |
| [vibe-kanban](https://github.com/BloopAI/vibe-kanban) | 28.2k · Apache-2.0 | 看板 → 每个 workspace 一个分支 + 终端；10+ Agent 的输出归一为 `NormalizedEntry` | shell 命令按语义重分类（cat → 读取、rg → 搜索、sed -i → 编辑、curl → 网络），避免 Codex 这类靠 shell 的 Agent 全挤进「命令」泳道；连续同类事件聚合；工具状态加 denied / pending_approval / timed_out（[shell_command_parsing.rs](https://github.com/BloopAI/vibe-kanban/blob/d5cbb5380fa0b32e98ef9b8d987f63decce4be3a/crates/executors/src/logs/utils/shell_command_parsing.rs)） | 2026-04-10 宣布停止商业运营 |
| [Crystal](https://github.com/stravu/crystal) → [Nimbalyst](https://github.com/nimbalyst/nimbalyst) | 3.1k · MIT | 并行 worktree 会话比较 | 低 | 2026-02 废弃 |
| [omnigent](https://github.com/omnigent-ai/omnigent) | 10.4k · Apache-2.0 | 元 harness：统一编排 Claude Code、Codex、OpenCode、Hermes、pi，带花费上限与危险操作暂停策略 | 低（执行层控制，Orbit 不做） | — |
| [disler 多 Agent 观测](https://github.com/disler/claude-code-hooks-multi-agent-observability) | 无许可证 | Hook 实时事件流 + 每 Agent 泳道 + 实时脉冲柱 | 只借设计：菜单栏「最近 5 分钟活动」 | 不能复制代码 |
| [agent-sessions](https://github.com/jazzyalex/agent-sessions) | 889 · MIT | 原生 macOS 会话浏览 + Cockpit HUD + 额度表 | 同平台参照；会话头的模型 / effort 变更史与 token 构成三段条（cached / fresh / output） | — |

「同一任务交给不同 Agent」这种用法产生的对照数据，可以作为跨 Agent 对比与 benchmark 的素材。

### 4.4 会话可视化

| 项目 | ★ · 许可 | 做法 | 可复用部分 | 注意 |
| --- | --- | --- | --- | --- |
| [agentsview](https://github.com/kenn-io/agentsview) | 6.0k · MIT | 40+ Agent 的本地浏览、搜索、分析；friction 检测器、扣分制健康分与 outcome（[score.go](https://github.com/kenn-io/agentsview/blob/d37642206051dababc436635024676c17dddac45/internal/signals/score.go)）；Quality 模式卡（受影响会话占比 ≥ 18% 为 warning、≥ 35% 为 critical）；canned 建议带 `template_id@version` 与聚合指纹（[canned.go](https://github.com/kenn-io/agentsview/blob/d37642206051dababc436635024676c17dddac45/internal/insight/canned.go)） | 检测器作规则 v0；「模式 → 证据 → 动作」卡与 provenance 格式；调用条按范围内最长调用归一、最慢 10% 标注；并行度柱、会话形态三联直方 | 时间线只是右栏小泳道；检测器以英文正则为主 |
| [dsh ui-trajectory](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/client/ui-trajectory/README.zh.md) | MIT | Chrome Network 式三泳道（输入 / 模型 / 工具）overview + 按轮次的事件账本 + 检查器；四种横轴投影；助手条拆「等首 token / 解码」 | A3 底座（[timeline.ts](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/client/ui-trajectory/src/client/timeline.ts)） | — |
| [Langfuse](https://github.com/langfuse/langfuse) TimelineDense | MIT（`ee/` 除外） | 地图式缩放平移、语义缩放、空闲压缩（移植自 Sentry）、永不横向滚动；设计决定写在源码注释里 | 交互与布局原则；空闲压缩算法（[timeCompression.ts](https://github.com/langfuse/langfuse/blob/9a29212e855c60ffb86d1989b62918b3781d9652/web/src/features/traces/fns/timeline/timeCompression.ts)） | — |
| [claude-code-history-viewer](https://github.com/jhlee0409/claude-code-history-viewer) | 2.2k · MIT | Session Board：多会话纵向泳道、PIXEL / SKIM / READ 三档语义缩放、跨会话属性刷选 + 匹配比例 | 多会话对比与列表缩略（[BRUSHING_SPEC.md](https://github.com/jhlee0409/claude-code-history-viewer/blob/090737b593d81b84b3d2b2a602f85a5c8cb9edc8/docs/BRUSHING_SPEC.md)） | — |
| [Laminar](https://github.com/lmnr-ai/lmnr) | Apache-2.0 | condensed timeline 上画出列表当前可见范围（视口窗口），拖选过滤 transcript；成本热力开关；Signals 语义事件聚类 | 时间线与列表双向联动 | — |
| [Docent](https://github.com/TransluceAI/docent) | Apache-2.0 | 用 LLM rubric 检索并聚类大量 transcript，回答带精确到块的引用 | AI 推断的引用格式；A6「自定义 rubric 搜索」 | — |
| [sniffly](https://github.com/chiphuyen/sniffly) | 1.3k · MIT | 以「用户指令」为单位的 Claude Code 仪表盘；错误原因正则表 | 打断率、steps / 指令、0 工具指令占比；失败原因排序条 + 例句 | 2025-08 后停更 |
| [claude-code-log](https://github.com/daaain/claude-code-log) | 1.2k · MIT | 静态 HTML 报告 + vis-timeline + DAG 分支 | 分支表达 | — |
| [agent-prism](https://github.com/evilmartians/agent-prism) | MIT | 可直接拷贝的 React trace 组件（树 + 行内时间条） | 组件参考 | — |
| Kimi `kimi vis` / pi HTML 导出 | MIT / MIT | turn → step → tool 分析 + Issues 闭集 / 会话树侧栏 + 过滤模式 | Issues 抽屉；遇到 fork / rewind 时画成树而不是硬拉成一条线 | — |
| [HF Agent Trace Viewer](https://huggingface.co/docs/hub/agent-traces) | 托管服务 | 原生读 Claude Code、Codex、pi 的原始 JSONL；其他 harness 写 STS-Format | 导出与分享的目标格式（[STS-Format](https://huggingface.co/docs/hub/session-traces-format)） | — |
| 只借设计：[Arize Phoenix](https://github.com/Arize-ai/phoenix)（ELv2）、[AgentOps](https://github.com/AgentOps-AI/agentops) 仪表盘（`app/` 为 ELv2）、[opcode](https://github.com/winfunc/opcode)（AGPL-3.0）、[claude-trace](https://github.com/badlogic/lemmy)（无许可证）、[OpenHands trajectory-visualizer](https://github.com/OpenHands/trajectory-visualizer)（无许可证） | 见左 | 树 + 行内瀑布、错误沿树传播；甘特瀑布；检查点分叉树；请求级视图 | 交互范式 | 不复制代码 |
| 跨领域范式：[Perfetto](https://perfetto.dev/docs/visualization/perfetto-ui)（Apache-2.0）、[Chrome DevTools](https://developer.chrome.com/docs/devtools/performance/reference)、Instruments | — | 每像素一个代表标记（mipmap）；缩放面包屑；条目与区间注释；拖选区间聚合 | 时间线细节层级与键位（W / S 缩放、A / D 平移、F 适应、Esc 清除） | — |

### 4.5 相邻项目：历史 → skill、记忆与归因

| 项目 | 许可 | 做法 | 可复用部分 | 与 Orbit 的边界 |
| --- | --- | --- | --- | --- |
| [SpecStory Lore](https://github.com/specstoryai/getspecstory/tree/main/lore) | Apache-2.0 | 分析单位是 beat（一次提示 + 到下一次提示前 Agent 实际执行的命令、文件与退出码 + 用户回复），用户回复当结果标签；SQLite 做确定性计数，Agent 只负责命名与判断；每个候选配一个反驳子代理；安装计划内嵌完整证据，写到 `~/.agents/skills` 再软链到各 Agent | 四个工程决定照搬：beat 单位、下一句回复当标签、确定性计数 + 反驳、没有证据不能批准 | 只产 skill；没有可视化与装后对照；要先装 SpecStory 采集 |
| [Entire CLI](https://github.com/entireio/cli) | MIT | 提交时生成 checkpoint，由本机 Agent 摘要「意图、结果、经验、摩擦点、未决事项」 | 会话摘要 schema；`Entire-Checkpoint` trailer 作会话与提交的锚点 | 从启用起才采集；偏审计 |
| [claude-mem](https://github.com/thedotmack/claude-mem) | Apache-2.0 | hooks 观察工具调用，压缩成记忆并自动注入后续会话 | 无 | 装了记忆插件会改变会话形态，效果追踪要记为混杂因素 |
| [git-ai](https://github.com/git-ai-project/git-ai) | Apache-2.0 | 用 git notes 把每行 AI 代码关联到 Agent、模型与提示 | 「代码保留」类结果指标的现成口径 | 只有归因，没有分析 |

## 5. 算法选型与公开实证

### 5.1 选型总表

阶段：MVP = 第一版做；后续 = 数据或标注到位后再做；不做 = 本产品形态下不划算。方法细节见各模块文档。

| 模块 | 方法 | 阶段 | 理由 | 依据 |
| --- | --- | --- | --- | --- |
| 分析 | 七类约 40 个确定性指标（效率、质量、摩擦、token 经济、工具、协作、节律），不合成总分 | MVP | `/insights` 的 session-meta 证明这一层不需要模型 | [costs](https://code.claude.com/docs/en/costs) |
| 分析 | 自研频次 DFG、P(下一步∣当前)、三步链、游程折叠后的轮次变体、区分「等 Agent / 等人」的性能瓶颈、Declare 约束（如「改了要测」），约 150–200 行、O(N) | MVP | PM4Py 是 AGPL-3.0，只作离线对照 | [PM4Py](https://github.com/process-intelligence-solutions/pm4py)；[van der Aalst](https://www.vdaalst.com/publications/p314.pdf) |
| 分析 | 会话三层切分：人类消息间隔 > 30 分钟切工作段；相似度骤降 + 文件集合变化切任务；规则标阶段（探索、规划、实现、验证、调试、交付）+ 手设参数的粘性 HMM 平滑 | MVP | 无需训练；阶段与官方 Explore → Plan → Implement → Commit 对齐，可识别「什么都塞进一个会话」 | [TextTiling](https://aclanthology.org/J97-1003/)；[best-practices](https://code.claude.com/docs/en/best-practices) |
| 分析 | agentsview 检测器移植 + 中文词表；同类问题出现在 ≥ 3 个会话才升级 | MVP | 现成、MIT、阈值有出处；中文 15–200 字节只相当于 5–66 个字，必须改按字符计 | [agentsview](https://github.com/kenn-io/agentsview/tree/d37642206051dababc436635024676c17dddac45/internal/friction) |
| 分析 | 情绪：打标函数加权投票（弱监督） | MVP | 无标注即可起步；标签模型放后续 | — |
| 分析 | 小样本：Wilson 下界、Beta-Binomial 经验贝叶斯、按天 bootstrap；人格四轴按「95% 区间是否整体在 50% 一侧」给字母，否则记「?」 | MVP | 替代 Demo 固定的 45–55 缓冲带；后端基线已实现 Wilson | [Evan Miller](https://www.evanmiller.org/how-not-to-sort-by-average-rating.html)；[Efron 1979](https://doi.org/10.1214/aos/1176347265) |
| 分析 | PELT / BOCPD 变点、可训练 HMM、PrefixSpan 反模式 | 后续 | 需要更多数据与标注 | — |
| 推荐 | 问题 → 解法知识库（YAML，30–50 条） | MVP | 透明、可审、可测试，官方文档就是现成规则源 | [features-overview](https://code.claude.com/docs/en/features-overview) |
| 推荐 | priority = 每周节省分钟 × 适用度（Wilson 下界 × 覆盖率）× P(有效)（Beta 先验，7 天结果回写）÷ (1 + 安装分钟 / 30 + 常驻 token / 2000) − 风险；MMR λ = 0.7 | MVP | 逐项可解释，单位统一为每周分钟或美元 | [RICE](https://www.intercom.com/blog/rice-simple-prioritization-for-product-managers/)；[MMR](https://doi.org/10.1145/290941.291025) |
| 推荐 | IDF 加权的共享能力词表重合 + 摩擦标签 + SQLite FTS5 BM25 | MVP | 复用 data-acquisition §6.3 的共享能力词表 | [data-acquisition.md](../plans/data-acquisition.md) |
| 推荐 | 向量语义匹配 | 后续 | 数据方案已列为暂不做 | — |
| 推荐 | 曝光日志（含展示概率） | MVP | 不记就永远无法做离线评估 | [Li 等 2011](https://arxiv.org/abs/1103.4601) |
| 推荐 | LinUCB / Thompson / IPS / DR | 不做 | 单用户反馈少，奖励延迟 7 天 | [LinUCB](https://arxiv.org/abs/1003.5956) |
| 推荐 | 7 天三层评估（触发 / 机械 / 双重差分简版） | MVP | 机械层不需要因果假设，行为层带对照与区间 | [双重差分](https://mixtape.scunning.com/09-difference_in_differences) |
| 推荐 | CUPED、中断时间序列、switchback / N-of-1 | 后续 | 需要更长数据或用户同意 | [CUPED](https://exp-platform.com/cuped/) |
| AI | 分级调用 + 可关闭的 facet（闭集、版本化缓存、多会话打包） | MVP | 省 token、可复现、不污染画像 | §2.4 |
| AI | 只发统计与摘要 + 逐项预览 | MVP | 隐私与成本双重约束 | — |
| AI | 生成物模板 + 四道自检（规范、安全、历史回放 dry-run、judge） | MVP | 生成物必须在历史数据上不误伤 | [hooks](https://code.claude.com/docs/en/hooks)；[Skill best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) |
| AI | `claude plugin eval` 有 / 无对照 | 后续 | 耗额度，用户同意后才跑 | [plugin-evals](https://code.claude.com/docs/en/plugin-evals) |
| AI | 自带 API Key 的 Batch + 显式缓存 | 后续 | 只对 API Key 用户有意义；Batch 全部 token 5 折，可与缓存折扣叠加 | [prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) |
| 评测 | 合成注入回归集 + 200 个会话的人工标注集 | MVP | 检测器与 facet 的精度底线；合成注入复用后端基线的 `pipeline_eval.py` 框架 | — |
| 评测 | judge 校准（交换顺序、Rogan–Gladen） | MVP | 简单、可解释 | [Rogan–Gladen](https://doi.org/10.1093/oxfordjournals.aje.a112510) |
| 评测 | PPI 区间 | 后续 | 金标积累后再上 | [PPI](https://arxiv.org/abs/2301.09633) |
| 评测 | 时间切分回放、Hook dry-run、规则反事实 judge | MVP | 不需要额外数据 | — |
| 评测 | 公开 benchmark 先验 + 用户数据经验贝叶斯收缩（先验强度 m ≈ 10，P(更好) ≥ 0.8 才建议；思考档位只在同厂商内比） | MVP | 公开成绩只作先验，结论落在用户自己的任务上 | §5.3 |

### 5.2 公开实证

| 研究 | 结果 | 对 Orbit |
| --- | --- | --- |
| [ETH：Evaluating AGENTS.md](https://arxiv.org/abs/2602.11988) | LLM 生成的上下文文件让成功率 −0.5%（SWE-bench）/ −2%（CTXbench），不显著；步数增加，成本 +20% / +23%；开发者写的 +2.4%（不显著）；仓库概览没有帮助 | 不生成项目概览式规则；只写推不出来、有纠正证据的条目；显示每条规则的常驻成本 |
| [Lulla 等：AGENTS.md 与效率](https://arxiv.org/abs/2601.20404) | 10 个仓库、124 个 PR：有 AGENTS.md 时运行时间中位数 −28.64%、输出 token −16.58% | 与上一条看似矛盾，说明效果依赖具体文件与场景，必须就地测量（路演论据） |
| [SkillsBench v4](https://arxiv.org/abs/2602.12670) | 策展 skill 平均通过率 33.9% → 50.5%（+16.6pp），87 个任务中 13 个变差；模型自写 skill 低于无 skill 基线 8.1 / 11.3 / 11.5pp；1 个 skill +18.0pp、2–3 个 +19.0pp、≥ 4 个 +10.1pp；「全面文档」只有 +0.7pp | 精简、有边界、一次 ≤ 2–3 个；生成只取用户验证过的轨迹；跨 Agent 安装后分别验证 |
| [EvoClawBench](https://arxiv.org/abs/2607.09711) | 「先写 skill 再做题」在部分模型上灾难性下降（DeepSeek-V4-Pro 77.77% → 4.80%） | 装后指标恶化要立即建议撤销 |
| [Agent Skills in the Wild](https://arxiv.org/abs/2601.10338) | 31,132 个 skill 中 26.1% 至少有一个漏洞，含可执行脚本的是纯指令型的 2.12 倍 | 第三方条目入库扫描，带脚本的默认提高风险等级 |
| [Malicious agent skills](https://arxiv.org/abs/2602.06547) | 近 10 万个扩展中发现 157 个恶意 skill，常把欺骗性指令藏在文档里 | 预览展示所有会被模型读到的文本，检测隐藏指令 |
| [METR 随机对照](https://arxiv.org/abs/2507.09089) | 16 位资深开发者用 AI 实际慢 19%，事后自认快 20% | 不宣称提速百分比，只报可数事件 |
| [TRAIL](https://arxiv.org/abs/2505.08638) / [Who&When](https://arxiv.org/abs/2505.00212) | 长轨迹错误定位：最好模型 11%；步级归因 14.2% | 模型只判定规则已定位的短候选 |
| [Cursor Bugbot](https://cursor.com/blog/building-bugbot) / [Bugbot learning](https://cursor.com/blog/bugbot-learning) | resolution rate 从 52% 提到 70% 以上，加入从反馈学规则后近 80%；规则走候选 → 激活 → 停用 | 主指标用复现率；推荐生命周期照此设计 |
| [Cursor semsearch](https://cursor.com/blog/semsearch) | 线上 A/B：代码保留率整体 +0.3%，1,000 个文件以上的仓库 +2.6%；去掉语义检索后不满意追问 +2.2% | 「代码保留率」「不满意追问率」可作结果指标；效果按项目规模分层 |

### 5.3 模型与思考强度的 benchmark 数据源（2026-10-02 核对）

| 来源 | 现状 | 用法 · 条款 |
| --- | --- | --- |
| [SWE-bench Verified 排行数据](https://github.com/SWE-bench/swe-bench.github.io/blob/master/data/leaderboards.json) | 180 条，最新条目 2026-02-26；同 harness（mini-swe-agent）47 条，有 `reasoning_effort` 的 18 条，40 条带逐实例结果 | 修 bug、实现功能类任务的先验，优先用同 harness 条目 · 许可未声明，只存元数据与链接 |
| [Terminal-Bench](https://www.tbench.ai/leaderboard) | 排行榜已到 4.0；2.0 为 89 个终端任务（[arXiv 2601.11868](https://arxiv.org/abs/2601.11868)） | 终端运维类先验 · 条款未核实 |
| [Aider polyglot](https://github.com/Aider-AI/aider/blob/main/aider/website/_data/polyglot_leaderboard.yml) | 69 条，2025-10-03 后未更新 | 只作历史参照 · Apache-2.0 |
| [LMArena 数据集](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset) | 更新到 2026-09-30，含 Text、WebDev、Agent 竞技场，带置信区间 | 对话、前端类偏好先验 · CC-BY-4.0 |
| [Artificial Analysis](https://artificialanalysis.ai/data-api/docs) | 免费档每天 100 次请求 | 速度与价格补充，不进 MVP · 须署名 |
| [Epoch AI](https://epoch.ai/benchmarks/use-this-data) | CSV 打包下载 | 聚合先验的备选 · CC BY 4.0 |
| [models.dev](https://models.dev/api.json) | 225 个 provider，含上下文上限、推理与思考档位选项 | 成本与可选档位的默认来源 · MIT |
| [OpenCode Data](https://opencode.ai/data) | OpenCode 遥测的全量模型使用排行（token 份额、缓存命中比例、平均会话成本） | 群体参照，不作效果证据 |

使用规则：不同 harness 的成绩不混排；公开成绩一律标「公开基准，非你的任务」；超过 6 个月的成绩降权；强模型常被用在难任务上，观察性对比要写明这一混杂。

## 6. 行动项

ID 用 `RS-` 前缀，表示来自本调研；各模块文档在自己的功能表里引用或改写。负责人按 [AGENTS.md](../../AGENTS.md) 的角色给出建议，以各模块文档的功能表为准。token 一栏是首次估算，按 Haiku 4.5 的 API 价折算（订阅用户实际消耗的是额度），都待验证。

### 6.1 数据层（需求写入 data-acquisition.md）

| ID | 行动 | 输入 → 输出 | MVP / 后续 | 复杂度 · token | 建议负责人 |
| --- | --- | --- | --- | --- | --- |
| RS-01 | 成本证据列与价格表 | 原始 usage → `model_call` 拆 `cache_write_5m` / `cache_write_1h`，加 `service_tier`、`pricing_model`、`price_match`（exact / alias / fuzzy / unpriced）、`price_ref`；`catalog.db` 加带生效日期的 `model_price` | MVP：LiteLLM 快照为主、models.dev 兜底，未定价单列；后续：价格变更后回填重算，支持组织下发的 `modelPricing`（[settings-reference](https://code.claude.com/docs/en/settings-reference)） | S · 0 | yhyfhgs |
| RS-02 | 额度事件 | Codex rollout 的 `token_count.rate_limits`、日志里的撞限错误 → L2 `quota.observed`、`limit.hit`，L3 `quota_window`；窗口按 `window_minutes` 与 `limit_id` 判定（Pro 套餐只有周窗口，见 [Codex 定价](https://learn.chatgpt.com/docs/pricing)） | MVP：Codex 燃尽曲线 + 两家的撞限识别；后续：Claude statusline 采集（RS-32）、可选读 CodexBar JSON | M · 0 | yhyfhgs |
| RS-03 | 账号与多根目录 | 多账号工具的数据根（claude-swap、ccs、自定义 `CODEX_HOME`、第二账号目录、Claude Desktop 本地 Agent 模式目录）→ `source.account_key` / `account_label`，realpath 去重，「未归属」桶 | MVP：根目录 → 账号；后续：目录绑定作辅助信号 | S · 0 | yhyfhgs |
| RS-04 | 人类输入识别与自身会话过滤 | user 消息 + Orbit 调用的标记与 cwd → `message.user.origin`（真人 / 注入上下文 / 命令输出）；排除 Orbit 自己发起的会话 | MVP：借 Hermes 包装标签正则（`<system-reminder>`、`<environment_context>`、`<command-name>` 等）+ 固定 cwd 与提示标记 | S · 0 | yhyfhgs |
| RS-05 | Kimi Code 连接器 | `~/.kimi-code/session_index.jsonl` + `sessions/wd_<slug>_<sha12>/<id>/agents/*/wire.jsonl`（协议 1.5，64 种记录）→ L1 / L2；与旧版 `~/.kimi/` 迁移副本（带 `[imported]` 标记）去重（[wire-manifest](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/packages/agent-core-v2/docs/wire-manifest.d.ts)、[data-locations](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/docs/zh/configuration/data-locations.md)） | 后续：本机无样本，格式待验证 | M · 0 | yhyfhgs |

### 6.2 分析（[analysis.md](../plans/analysis-module.md)）

| ID | 行动 | 输入 → 输出 | MVP / 后续 | 复杂度 · token | 建议负责人 |
| --- | --- | --- | --- | --- | --- |
| RS-06 | 摩擦检测 v0 | L3 事件 → `signal`：纠偏（两条助手消息之间的短人类消息）、retry（同工具同参数连续 ≥ 3 次）、runaway（12 次窗口内失败 ≥ 6，或失败 ≥ 3 且同类命令 ≥ 10）、edit churn（同一文件在 10 条消息内改 ≥ 3 次）、压缩后重做、上下文压力 > 0.9、P0 告警（同一工具在 ≥ 3 个会话报错），带 `rules_version`；dsh 与 Kimi 的 3 / 5 / 8 阈值并列对照 | MVP：移植阈值，长度改按字符，补中文纠偏与挫败词表；后续：用 RS-24 的标注集重标阈值 | M · 0 | MistyHuang03 |
| RS-07 | 验证与缺席检测 | shell 命令 + 编辑事件 → test / lint / typecheck / build（targeted / full）分类，「改完代码没验证就结束」信号 | MVP：Hermes 账本规则；后续：喂给人格「求证 vs 信任」轴 | S · 0 | MistyHuang03 |
| RS-08 | 成本与缓存诊断 | `model_call` → 缓存命中率、缓存重复计费（只报空闲超 TTL、换模型这类可观察原因）、返工税（第一次纠偏之后消耗的 token） | MVP：pi 公式；后续：接推荐「长停顿前先压缩」「会话开始就选定模型」 | S · 0 | MistyHuang03 |
| RS-09 | 会话级指标与问题抽屉 | L3 → 上下文占用折线与峰值、空闲间隙（区分轮间 / 轮内）、活跃 / 墙钟时长、工具统计表；Kimi Issues 闭集；指令粒度指标（打断率、steps / 指令、0 工具指令占比） | MVP（全部确定性） | S · 0 | MistyHuang03 |
| RS-10 | 概览基线与交叉校验 | 会话与 `model_call` → Hermes `/insights` 的维度（有 / 无定价分列、星期 × 小时、连续活跃天、Top 会话）；与 Claude 的 session-meta / facets 交叉校验，作冷启动对照答案 | MVP | S · 0 | MistyHuang03 |
| RS-11 | 健康分、结果与人格的区间判定 | 指标 → 扣分制健康分（数据不足不评分）、outcome（completed / abandoned / errored / unknown）+ 置信度；人格 DIMV 四轴改为「满足条件的单位占比」，按天 bootstrap 1000 次给区间 | MVP；后续：常模与跨时间稳定性 | M · 0 | MistyHuang03 |

### 6.3 推荐（[recommendation.md](../plans/recommendation-module.md)）

| ID | 行动 | 输入 → 输出 | MVP / 后续 | 复杂度 · token | 建议负责人 |
| --- | --- | --- | --- | --- | --- |
| RS-12 | 问题 → 解法知识库 | 问题类型 + 适用 Agent → YAML 条目（触发条件、证据门槛、机制、各 Agent 的落点与等价做法、常驻成本、风险） | MVP：30–50 条，种子取官方触发条件表、五种失败模式、`/insights` 功能清单与 Demo 的 13 条示例；官方内置功能（auto mode、`/fewer-permission-prompts`、Codex memories、skill 列表预算、`opusplan` 等）按版本探测后作为一等推荐项；后续：Bugbot 式候选 → 激活 → 停用 | M · 0 | genius-FXC（条目内容）、MistyHuang03（结构） |
| RS-13 | 机制决策表与减法 | 摩擦与习惯信号 → 规则 / skill / hook / 子代理 / CLI / 只给建议；闲置 14 天且 10 个会话未用 → 停用建议；常驻 ≥ 2,000 token 标黄 | MVP | S · 0 | MistyHuang03 |
| RS-14 | 排序与曝光日志 | 候选 + 证据 → priority 分解、MMR、每次 ≤ 2–3 个 skill、频控；`rec_exposure`（候选集、分数、位次、展示概率、用户动作） | MVP；不做 bandit，末位留小比例探索位 | M · 0 | MistyHuang03 |
| RS-15 | 目录匹配字段 | Claude 插件 relevance 的信号词表（cwd、cli 命令名、hosts、filesRead glob、manifestDeps）→ 共享能力词表的匹配字段；第三方条目的风险等级（来自 RS-31）进入排序的风险项 | MVP | S · 0 | yhyfhgs |
| RS-16 | 工作流类推荐模板 | 阶段分布、纠偏螺旋、长任务、并行冲突 → 验证阶梯、长任务进度文件 + 特性清单、完成契约五要素、计划模式只给多文件且返工多的任务、同一问题纠正两次后建议开新会话 | MVP：教程类推荐（只给步骤与可复制命令）；后续：生成对应的 skill 或 hook | S–M · 每条一次 L3 叙述，约 $0.05–0.2 | MistyHuang03 |
| RS-17 | 跨 Agent 额度组合建议 | A2 的 Agent 契合度 + 各订阅剩余额度与重置时间 → 「这类任务本周交给 X」 | 后续：只建议，不切号 | M · 0 | MistyHuang03 |

### 6.4 AI（[ai.md](../plans/ai-module.md)）

| ID | 行动 | 输入 → 输出 | MVP / 后续 | 复杂度 · token | 建议负责人 |
| --- | --- | --- | --- | --- | --- |
| RS-18 | 分级调用与节点注册表 | 任务 → L0 代码 / L1 本地嵌入（可选）/ L2 小模型单次 / L3 大模型单次 / L4 本机 Agent；每个节点记录模板版本、档位与评测基线；LLM 步骤后接代码 gate | MVP：L0 + L2 facet + L3 叙述与生成；L4 只留「深度诊断」入口 | M · — | yhyfhgs |
| RS-19 | facet 抽取 | 结构化事件摘要（人类消息与 Agent 回复截断、工具类别与命令头、错误类别；不送工具输出、文件内容与思考）→ 闭集 facet JSON | MVP：5–10 个会话打包一次调用；后台空闲时运行，剩余额度低于阈值跳过 | M · 每会话约 $0.006–0.016，1,000 个会话首次回填约 $6–16，每周增量约 $0.3–0.8 | yhyfhgs |
| RS-20 | headless 执行器 | 任务 + schema → 各 Agent 的最小配置调用（§2.4）；调用前估算并在 UI 显示「预计 N 次、约 X token」；`--max-budget-usd` 封顶；失败退避；并发 ≤ 3 | MVP：Claude、Codex；后续：pi、Hermes、OpenCode | M · 每次固定约 0.55–1.5K（Claude）/ 0.92–1.46 万（Codex） | yhyfhgs |
| RS-21 | 生成式推荐 | 问题证据（≤ 5 条脱敏片段）+ 用户已有规则的相关段落 + 模板 → SKILL.md / hook / 规则段落 / 子代理 / 权限白名单；能匹配到现成条目时只生成粘合部分（规则或 hook） | MVP：模板 + 填槽 + 四道自检；提示词按 Hermes 四段结构；lint 参照 skill_linter 与规则 lint（具体到可验证、不与已有规则冲突、Claude 每文件 < 200 行、Codex 拼接 ≤ 32 KiB）；后续：触发评测（RS-26） | L · 每条约 $0.05–0.5（含 judge） | yhyfhgs |
| RS-22 | AI 标注的结构化输出 | 规则已定位的短候选片段 → `{label, explanation, confidence, citations}`，引用精确到事件 | MVP：关键时刻与纠偏类型细分；后续：A6「自定义 rubric 搜索」与聚类 | M · 每个候选一次 L2 判定（高影响三票两胜） | yhyfhgs |

### 6.5 评测（[evaluation.md](../plans/evaluation-module.md)）

| ID | 行动 | 输入 → 输出 | MVP / 后续 | 复杂度 · token | 建议负责人 |
| --- | --- | --- | --- | --- | --- |
| RS-23 | 数据层回归 | 各 Agent fixture + 本机样本 → 全记账测试、ccusage 按日 × 模型的对账、Agent × 分析能力的数据可得性矩阵（pass / fail / 未测，参照 [Session-Bench](https://github.com/jazzyalex/agent-sessions)） | MVP | S · 0 | MistyHuang03 |
| RS-24 | 检测器标注集 | 三人真实会话中的失败片段 → 开放编码 → 轴向编码 → 闭集；200 个会话标注（失败 50–100）；每个失败模式一个二元 judge，报 TPR / TNR，κ ≥ 0.6 上线 | MVP：先用 20–50 个真实失败起步 | M · judge 校准每轮数百次 L2 调用 | MistyHuang03 |
| RS-25 | 回放评测 | 历史 `tool_call` → 还原成 hook 的 stdin JSON 喂给生成的 hook，统计触发召回与误拦（被拒或破坏性命令被放行必须为 0）；按时间切分检验推荐是否命中后来发生的问题 | MVP | S–M · 0 | MistyHuang03 |
| RS-26 | 装前对照 | 摩擦点之前的转录作 `history_file`、用户当时的下一句作提示 → 有 / 无两臂各 3 次（`claude plugin eval` 需显式加 `--ablation with-without`）；先用零成本 grader 再用 judge；description 触发评测 | 后续：耗额度，用户同意后才跑 | L · 单条推荐数十次 Agent 调用 | MistyHuang03 |
| RS-27 | 模型与档位建议 | 公开榜单（按任务类型映射）作先验 + 用户「模型 × 档位」的完成率、纠偏率、每完成任务成本 → 收缩后的 P(更好) | MVP：SWE-bench 同 harness、Terminal-Bench、LMArena、models.dev 快照；后续：用户同意的 N-of-1 档位交替试验 | M · 0 | MistyHuang03 |
| RS-28 | 「说人话」可读性 | 报告与卡片文案 → 后端基线已有的规则检查与读者评审材料 | MVP：补真实读者评分 | S · 0 | genius-FXC（读者评审） |

### 6.6 安装（模块 8，见 [recommendation.md](../plans/recommendation-module.md) 的安装部分）

| ID | 行动 | 输入 → 输出 | MVP / 后续 | 复杂度 · token | 建议负责人 |
| --- | --- | --- | --- | --- | --- |
| RS-29 | 跨 Agent 适配器 | 安装计划 → 各 Agent 的文件与配置改动（§2.3）+ 无法映射清单；Codex hook 显示「已安装、未信任」；pi 生成 TS extension，OpenCode 生成 JS 插件；权限规则按三家冲突语义渲染并模拟 | MVP：Claude Code 与 Codex 的规则、skill、hook、权限；后续：Kimi、pi、Hermes、OpenCode、dsh | L · 0 | yhyfhgs |
| RS-30 | 预览、ledger 与撤销 | 安装计划 → 键级 diff 预览（绑定内容哈希）→ 写入（标记块形如 `<!-- tandem:rule id=… -->`）→ ledger（actor、action、证据、前后 sha256，内容按哈希存）→ 单条或整批回滚，回滚前快照；用户改过的文件不自动撤销 | MVP | M · 0 | yhyfhgs |
| RS-31 | 风险闸门 | 第三方条目 → 静态扫描（脚本、联网、凭据路径、隐藏指令、过宽的 `allowed-tools`）→ safe / caution / dangerous，dangerous 不进一键安装；MCP 与插件标注 lethal trifecta 三项能力 | MVP：规则扫描；后续：沙箱试跑（[sandbox-runtime](https://github.com/anthropics/sandbox-runtime)） | M · 0 | yhyfhgs |
| RS-32 | 采集类优化项 | 用户同意 → 调大 `cleanupPeriodDays`；安装 statusLine 包装（原样调用用户已有命令，同时记录 `rate_limits`；statusLine 只能配一个命令，不能替换）；安装只读的 `StopFailure` / `Notification` Hooks | 后续 | S · 0 | yhyfhgs |

### 6.7 前端（Demo）

| ID | 行动 | 输入 → 输出 | MVP / 后续 | 复杂度 · token | 建议负责人 |
| --- | --- | --- | --- | --- | --- |
| RS-33 | A3 时间线重做 | L3 事件 + 关键时刻 → 脊柱 overview（三泳道 + 视口窗口 + 拖选）+ 按轮次的事件账本（同类聚合、行内迷你条）+ 检查器（diff、命令输出）；活跃时间投影；规则型关键时刻 6 类（纠偏、打断、失败串、重试循环、压缩后重做、突破） | MVP：只用确定性数据的部分；后续：语义泳道、语义缩放、跨会话刷选、AI 推断时刻 | L · 0 | genius-FXC |
| RS-34 | 编码纪律 | 全站图表 → 色相只表示类别、红色只给失败、AI 推断用紫色虚线 + 置信度；单系列条形用浅灰；图表按容器宽度重新布局，不按 viewBox 等比缩放 | MVP | M · 0 | genius-FXC |
| RS-35 | 来源、新鲜度与样本门槛 | 每个数字 → 来源标签（官方 / 官方缓存 / 估算 / 过期 / 无数据）、Agent × 账号能力状态、「数据不足」「实验性」；金额标「API 等价估算，非账单」 | MVP | S · 0 | genius-FXC |
| RS-36 | 「用量与额度」视图 | `quota_window` + `model_call` → 额度卡（节奏：期望 vs 实际）、燃尽曲线叠会话条带、成本与 token 互斥分桶、缓存效率、撞限时间线、建议入口 | MVP：Advanced 一页或 A1 标签页；Lite 一张卡 | M · 0 | genius-FXC |
| RS-37 | 推荐卡结构 | 推荐 → 模式 → 证据 → 动作；常驻 / 触发成本；with / without / Δ；「草案」标记与依据（模板 ID@版本、聚合指纹、置信度）；有用 / 没用 + 一句原因；不再提示 | MVP | S–M · 0 | genius-FXC |
| RS-38 | 文案与原生度量 | Demo → 删除或改写需要社区数据的对比（A8、A2）；预填的量化收益改为可计数口径；按 §3.5 U9 的实测度量落地，并写成 Playwright 断言（标题栏高与三灯位置、字体命中、字号只取 8 档、卡片无 backdrop-filter、时间线每像素最多 1 个标记） | MVP | M · 0 | genius-FXC |

## 7. 明确不做

| 不做 | 原因 | 依据 |
| --- | --- | --- |
| 读 OAuth 凭据、钥匙串或浏览器 cookie 调未公开额度端点 | Anthropic 不允许第三方收集或中转 Claude.ai 凭据；端点配额被用户的其他工具共享 | [legal and compliance](https://code.claude.com/docs/en/legal-and-compliance) |
| 账号池、自动切号、提前开窗、代理转发、订阅共享 | 条款风险；与「本地分析」定位无关 | §4.2 |
| 又一个记忆系统或学习闭环 | Claude auto memory、Codex Memories、Hermes 已覆盖；Orbit 做记忆的审查与跨 Agent 同步 | §2.1 |
| 多 Agent 编排 | 易被官方吸收，明星项目已停更或废弃 | §4.3 |
| 自己的实时额度菜单栏 | 已高度同质；检测到 CodexBar / OpenUsage 时可选读取它们的 JSON | §4.1 |
| 上下文 bandit、训练模型、MVP 中的向量检索 | 单用户反馈少、奖励延迟；先做确定性排序与曝光日志 | §5.1 |
| 在用户仓库里用默认配置跑 headless | 会执行项目 hooks 与 MCP、写会话 | §2.4 |
| 写托管层或团队共享层配置 | 会被组织策略覆盖或被提交进团队仓库 | §2.3 |
| 让 Agent 自主改用户配置 | 所有写入走预览 → 确认 → 可撤销 | §3.3 I1 |
| 引入 PM4Py，复制 AGPL、ELv2、CC BY-NC-SA 或无许可证项目的代码 | 许可证 | §4 |
| 宣称提速百分比；MVP 中展示需要社区数据的对比 | 没有数据通路；METR 的反例 | §5.2 |

## 8. 待验证

| 假设 | 怎么验证 | 影响 |
| --- | --- | --- |
| agentsview 阈值改按字符后，中文纠偏与挫败检测的召回与误报可接受 | RS-24 标注集上报 TPR / TNR | 摩擦检测与推荐触发 |
| 5–10 个会话打包后 facet 准确率不低于单会话调用 | 同一批会话分别跑打包与单会话，对比字段准确率 | AI 成本估算 |
| `--safe-mode` 在订阅登录下稳定，CLI 内部的缓存断点能命中 | 连续批量调用，读 usage 里的缓存读写 | RS-20 的固定开销 |
| Claude 中文 token 比例（成本估算按约 1 字 1 token） | 用 CLI 返回的 usage 实测 | RS-19 的预算 |
| Claude 是否跟随软链加载 `.claude/skills/<name>` | 本机实测 | RS-29 的 skill 落点 |
| Codex `--ignore-user-config` 时已信任的 hooks 是否仍运行 | 配一个写文件的测试 hook | RS-20 的隔离 |
| `OPENCODE_CONFIG_CONTENT` 能否压过用户的 `share: auto` | 安装 OpenCode 后实测 | OpenCode 调用的隐私 |
| dsh 能否用 `--patch` 摘掉持久化插件；Kimi 是否有隐藏的不落盘参数 | 读 headless profile 与源码 | 自身会话过滤 |
| Kimi wire 格式与旧版去重规则 | 安装后生成样本 | RS-05 |
| Claude Desktop / Cowork 会话不受 30 天清理（2.1.248 起）在本机成立 | 对照桌面版会话目录的最早时间 | 原始归档的回填范围 |
| `~/.claude.json` 的 `cachedUsageUtilization` 字段在版本间稳定；只读这一子树即可 | 跨版本对照字段结构 | Claude 额度快照 |
| 7 天双重差分在「前后各 ≥ 5 个会话」时区间足够窄 | 用历史数据做时间切分模拟 | 效果追踪是否显示「数据不足」 |
| 装前对照（每臂 3 次）的额度消耗用户能接受 | 在三人的真实推荐上试跑并记录花费 | RS-26 是否进入默认流程 |

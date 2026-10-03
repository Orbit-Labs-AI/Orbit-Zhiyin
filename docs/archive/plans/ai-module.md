# Orbit AI 接入设计：分析侧与推荐侧如何用模型

> 文档状态：历史记录。正文保留原基线、日期与证据；其中的状态和数字不代表当前版本。现行入口见[文档导航](../../README.md)。


> 状态：方案（不等同当前能力） · 维护者 `yhyfhgs` · 核对版本 main `0c96334` · 适用：Advance / Lite（另注明处除外）

> 定位：回答「分析（AN）与推荐（RC）两个模块分别如何接入 AI」。AI 是可关闭的横切层：不接一个 agent 自由问答，而是把模型嵌进确定性的 workflow 节点里，每个节点有固定输入、闭集输出、缓存键、预算与降级。不开 AI 时，所有页面照常出数（main `orbit_backend` 已是这样）。
>
> 依据（2026-10-02，按评审统一结论修订）：模块契约 [`contract.md`](module-contract.md) 第 2 版 + 本轮评审结论（并入契约第 3 版的条目见 §14）；main `f4a2cde`（`src/orbit_backend/` 0.13.6 + PR #16 `analytics/instruction/`：`narrative.py`、`reader_eval.py`、`evaluation.py`、`analytics/{features,text,service}.py`、`feedback.py`、`bottlenecks.py`、`recommend.py`、`pipeline_eval.py`、`privacy.py`、`store.py`）；已合入 main 的 PR #11（`packages/connectors`，35 项回归）、PR #12 Lite Demo（`prototypes/advance/benchmark-review.md`）、PR #15（版本名统一为 Lite / Advance）；未合入：PR #9 / #14 `origin/feat/agent-connectors`（`packages/data`：`analysis_input.read_analysis()`、`ImportService`、`user_version = 4`）、PR #13 / #17（`MistyHuang03` 语义特征族）、PR #19 `origin/refactor/genius-FXC-bottleneck`（`analytics/{respond,interaction,cost_time,outcome}`）；调研 `docs/research/landscape.md`（§2.4 headless 实测、§3.3 AI 原则）与 [research.md](../../research/landscape.md) 所汇总的调研笔记；Demo 盘点 [`feature-map.md`](feature-map.md) §5；用户覆盖要求 本机工作文件。
>
> 写法：每个 AI 任务写「触发 → 输入（只发哪些字段、预算）→ 档位 → 输出 schema → 缓存键与失效 → 失败降级 → 评测」。标「待验证」的是需要真实数据或实测才能定的假设。成员一律用 GitHub 账号指代。配套文档：`docs/archive/plans/analysis-module.md`（AN）、`docs/archive/plans/recommendation-module.md`（RC）、`docs/archive/plans/evaluation-module.md`（EV）、`docs/archive/plans/feature-map.md`（三张端到端功能卡与合并后的前端升级表；本文只写各卡的第 4 段「AI 介入点」，见 §9）。

## 0. 结论先行

1. **两种接入形态，没有第三种。** 分析侧 AI 只做「代码定位好的短片段 → 闭集标签」（逐会话 facet；反馈分类与簇命名 v1）和「汇总统计 → 先给结论的叙述」；推荐侧 AI 只做「模板填槽生成」（规则、hook、SKILL.md、与专家 skill 的粘合规则）、「单次 workflow 诊断」和「候选适配解释（v1）」。所有「找问题」「算数」「排序」「安全判定」「证据选择」留在 L0 代码。
2. **逐会话 facet 是分析侧唯一的大头调用，一次抽取、多处复用。** MVP schema 只有七项：`goal、task_type、outcome、friction_types、candidates[]、repeated_instructions、summary`；AN-05 信号、AN-06 问题、AI-05 叙述、AI-06 生成的证据、A6 页面全部读它的缓存，不再各自调模型。`scene`（main `feedback.scene_of()`）与 `interaction_pattern`（AN-08 规则）由 L0 算好作输入；满意度 / 情绪、AI 推断时刻、违反规则随 AN-07 / AN-09 / RC-06 #2 在 v1 加入。
3. **通道用用户自己的本机 Agent headless，最小开销配方已实测**（`docs/research/landscape.md` §2.4）：Claude Code `--safe-mode --tools "" --system-prompt-file … --no-session-persistence --json-schema` 固定开销约 0.55–0.73K token（结构化输出两轮合计 1.3–1.5K；默认配置 2.7–3.7 万）；Codex `exec --ephemeral … --output-schema` 约 0.92–1.46 万。因此 **5–10 个会话打包成一次调用**，Codex 通道只给 L3 任务。MVP 引擎只有 Claude Code、Codex 与测试用 `FakeEngine`；API Key（Anthropic Messages API）v1，Ollama v2。
4. **MVP 的执行方式是用户触发、串行**：facet 由用户在设置 / 首次启动点一次「开始语义分析（预计 N 次 · X token）」，首次回填只覆盖分析窗口（默认 90 天）内最近的 ≤ 200 个合格会话（≈ 25 次调用、≈ 0.8M 输入 token、≈ $1.1 cheap，§5.4），之后只处理新会话；叙述与生成按需、单次 ≤ 12K。省 token 靠四项机制：精确缓存键、只处理新会话、L0 候选定位、每次 `--max-budget-usd` 封顶。后台空闲 / 电量 / 额度判定、租约、退避、并发全部 v1。
5. **生成物只允许模型填有类型的槽位**：规则句、hook 的 matcher / 阈值 / 提示语 / 命令头、SKILL.md 的 description / steps、子代理的 system prompt 段落（v1）、slash command 正文（v1）；脚本体、文件骨架、权限前缀、落点全部来自仓库模板（内容哈希固定）。MVP 三道自检（lint → 静态安全扫描 → 历史回放 dry-run）任一失败即退回模板默认或不展示，然后才进 IN-02 预览；judge 复核 v1。
6. **与现有代码的关系**：AI 叙述沿用 `narrative.explain()` 的 JSON 形状并以它为降级；所有 AI 文案进界面前过 `evaluation.evaluate_text()`（EV-09），`error` 级问题即退回模板；模板版与 AI 版的优劣用 `reader_eval.make_pack()` 做盲评（EV-10）；簇命名（v1）建立在 `analytics/text.representation()`（AN-18）之上；facet 候选的输入是 `features.correction_terms` / `subjective_outcome_candidates` / `feedback.signals` / `bottlenecks.diagnose`；自身会话过滤的现有机制是 `store.import_codex --exclude-session` + `sample_policies`。
7. **MVP** = AI-01 通道（Claude Code、Codex、`FakeEngine`）+ AI-02 注册表（Python 常量字典 + gate）+ AI-03 facet（用户触发，七项 schema）+ AI-05.1 概览叙述 + AI-06.1 / 06.3 / 06.4 / 06.7（规则、hook、SKILL.md、粘合规则）+ AI-07 ①②③ + AI-08 上下文包（含「入口 → 证据包」表）+ AI-10 单次调用版 + AI-11（估算、封顶、只处理新会话）+ EV-11 账本；**v1** = AI-03.1 分块摘要、AI-04（反馈分类、簇命名）、AI-05.2 / 05.3 / 05.4、AI-06.5 / 06.6 / 06.8、AI-07.4 judge、AI-09 问本地 Agent（计划 → 执行 → 回答）、AI-10 → RC-06 映射、AI-12、后台调度、pi / Hermes / API Key 通道；**v2** = 装前有 / 无对照评测（唯一的 L4 任务）、Ollama、更多引擎、L1 端侧小模型。
8. 不做：自由对话式 agent 分析、让本机 Agent 多轮自主查询数据（原 L4 `ask.query`）、让模型改用户配置、语义缓存、向量检索、在用户仓库里用默认配置跑 headless、把模型自报置信度当概率、0–100 满意度分。

## 1. 原则与边界

### 1.1 五级调用（沿用契约 §5.1）

| 层 | 本文落到的任务 | 只能在这一层做的事 | token |
| --- | --- | --- | --- |
| L0 代码 | 候选定位、证据选择、打包、脱敏、schema 校验、引用校验、缓存、排序、lint、安全扫描、回放 dry-run、模板渲染、预算与封顶、预置问题生成 | 一切安全相关判定与一切数字 | 0 |
| L1 端侧小模型（可选，v2） | 「这条短消息是纠偏还是继续」的二元判定 | 不出本机；不可用即跳过 | 0 |
| L2 便宜模型（单次、枚举输出） | `facet.session`（MVP）；`classify.feedback`、`cluster.failure_names`、`cluster.topic_names`、`judge.*`、`rerank.fit`、`ask.plan`（v1） | 读懂原话但不负责找问题 | 每次 ≤ 50K |
| L3 强模型（单次、结构化） | `narrate.overview`、`generate.rule / hook / skill`、`diagnose.workflow`（MVP）；`narrate.persona / session_review / weekly`、`generate.subagent / command / workflow_tutorial / revise`、`ask.answer`（v1） | 低频按需；输出结构化并校验引用 | 每次 ≤ 20K |
| L4 本机 Agent（多轮、只读工具） | 只剩 `eval.plugin_eval`（v2，装前有 / 无对照）；「问本地 Agent」不走 L4（§4.6） | 用户主动发起；预算封顶即停 | 每次 ≤ 50K |

每个 LLM 节点先用 main 档建评测基线，再换 cheap 档，评测分不降才采用；注册表记录模板版本、当前档位与上次降级评测结果（契约 §5.1）。

### 1.2 硬规则（对应 `docs/research/landscape.md` §3.3 I1–I10）

| # | 规则 | 实现位置 |
| --- | --- | --- |
| R1 | 主链路是预定义 workflow：导入 → 指标 → 候选定位 → facet → 聚合 → 匹配 → 生成 → 校验；没有「自由提示」入口，问答也是「计划 → 代码执行 → 回答」三步 | AI-02 路由表只认注册的 `task_id`；§4.6 |
| R2 | 每个 LLM 步骤后接代码 gate：JSON Schema、枚举、引用的 `event_uid / session_uid / problem_id` 必须真实存在、数字必须来自输入白名单；失败重试一次，再失败降级并在界面说明 | AI-02 `validate()`；§5.3 |
| R3 | 静态前缀在前、证据在后；同批不换模型、不换引擎；结果缓存只用精确键（内容哈希 + `prompt_version` + `schema_version`），`model_id` 只记录与展示，换模型不作废旧结果 | AI-02、§3.2、§5.2 |
| R4 | 省 token 的顺序：不送（只分析新会话、跳过过滤阈值以下的会话、首次回填只做窗口内 ≤ 200 个）→ 少送（截断、占位替换工具输出）→ 送对（只送候选片段）→ 复用（facet 缓存）→ 封顶（每次调用预算） | AI-08、AI-11 |
| R5 | 开放字典一定漂移：所有标签字段闭集 + `other`；开放文本只允许在限长的 `summary / label / text_redacted` | §3、§4 的 schema |
| R6 | 私有数据、不可信内容、对外通信三者不同时具备：分析调用关工具、无网络、不加载用户的 CLAUDE.md / Skills / Hooks / MCP；推荐 MCP / 插件时标注三项能力 | AI-01 参数；IN-05 |
| R7 | 旁路任务默认 cheap 档；换模型时同时换输入形态（送摘要而非原文） | AI-02 模型槽位 |
| R8 | 不抢用户额度：MVP 所有调用由用户触发、串行执行、先看估算；v1 的后台任务才引入空闲判定、额度阈值、租约与退避 | AI-11 |
| R9 | 模型不擅长在长轨迹里找问题：规则先定位候选，模型只对短片段做闭集判断；回填先抽有 L0 候选或是活跃 `problem` 证据的会话 | AI-03 输入 = L0 定位的片段；§5.2 |
| R10 | 不污染被分析的数据：固定 marker + 专用 cwd + 不落会话；连接器导入时再过滤一遍 | AI-01；DT 侧补充约定（§14） |

### 1.3 隐私边界（沿用契约 §5.2，本文只列 AI 相关项）

| 可以发给本机 Agent（经它发往其服务商；发送前逐项预览） | 永不发送 |
| --- | --- |
| L2 已脱敏的真人消息截断（≤ 500 字）、答复截断（≤ 300 字）、工具 `kind + command_head + status + error_class`、错误输出首 200 字、汇总统计、每类问题 ≤ 3 条证据片段、已有规则文件的相关段落、Catalog 条目的 description | L0 原文、`reasoning`（`encrypted / redacted`）、工具参数全文、工具输出全文、文件内容、路径中的用户名（脱敏规则替换）、凭据、`ext` 原生字段 |

用户在 A9-06 / ASK 预览里取消勾选的项不发送；开启「原始对话片段」需逐条确认（Demo A9-06 的交互保留）。脱敏按契约 §3.8：以 DT-10（`yhyfhgs`，`packages/data` `privacy.py`）写入时脱敏为准，AI-08 与分析侧只调用 main `privacy.direct_user_text()` 剥平台块与引用；EV-01 的脱敏夹具放在 `packages/data`。Orbit 自身没有服务端，不上传任何数据；只有 Ollama 通道可称「完全离线」。

## 2. 执行通道（AI-01、AI-02、AI-08、AI-11、EV-11）

### 2.1 通道矩阵（AI-01）

| 引擎 | 最小开销配方（来源：`docs/research/landscape.md` §2.4，本机实测 2026-10-02） | 不落盘 / 隔离 | 固定开销（输入 token） | 结构化输出 | 阶段 |
| --- | --- | --- | --- | --- | --- |
| Claude Code | 在 Orbit 专用空目录、净环境运行：`claude -p --safe-mode --tools "" --system-prompt-file <任务静态提示> --no-session-persistence --output-format json --json-schema <schema> --max-turns 3 --effort low --settings '{"alwaysThinkingEnabled":false}' --max-budget-usd <上限> --model <槽位> < /dev/null`（[headless](https://code.claude.com/docs/en/headless)、[cli-reference](https://code.claude.com/docs/en/cli-reference)） | `--no-session-persistence`（仍会建空的 `projects/<cwd>/memory/`，连接器忽略）；`--safe-mode` 关 CLAUDE.md / skills / 插件 / hooks / MCP；订阅登录照常可用；`--bare` 只接受 API Key，不用 | 约 0.55–0.73K；加 `--json-schema` 至少两轮，合计 1.3–1.5K；默认配置 2.7 万（净环境）/ 3.7 万（继承桌面环境） | `--json-schema`（两轮） | MVP：L2 + L3 |
| Codex | `codex exec --ephemeral --json --skip-git-repo-check -s read-only --ignore-user-config --ignore-rules --disable apps --disable plugins --disable memories -c agents.enabled=false --output-schema schema.json -o out.json < /dev/null`（[Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode.md)） | `--ephemeral` 不写 rollout、不写 threads、不触发 memories | 默认 2.09 万；去用户配置 1.46 万；换基础指令并关工具 0.92 万；`--output-schema` 原生单轮，多约 20 token | `--output-schema`（单轮） | MVP：只给 L3 任务（固定开销太大，不做 facet 打包） |
| `FakeEngine` | 从 fixture 读取固定 JSON 响应，不调模型；与真实引擎走同一条 `run_task → gate → 缓存 → 降级` 链路 | 无 | 0 | 原生 | MVP（测试与 EV-03 回归） |
| pi | `pi -p --no-session --no-tools --no-extensions --no-skills --no-context-files --mode json --system-prompt <提示>` | `--no-session` | 未实测（系统提示很短） | `--mode json`（schema 由提示约束 + 代码校验） | v1 |
| Hermes | `hermes chat -q … --oneshot --format stream-json --source tool --ignore-user-config --ignore-rules --safe-mode` | `--source tool`：不出现在用户会话列表 | 未实测 | 提示约束 | v1 |
| API Key（可选） | Anthropic Messages API：`output_config.format` 结构化输出、静态前缀 `cache_control`、后台任务可走 Batch（5 折）（[structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)、[prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)、[batch](https://platform.claude.com/docs/en/build-with-claude/batch-processing)） | 无会话；密钥存 Keychain，只在 Orbit 进程内使用 | 无 CLI 开销；静态前缀可缓存（最小可缓存前缀：Sonnet 5.5 / Opus 5.5 为 512 token，Haiku 4.5 为 4,096，见 prompt caching 文档） | 原生 | v1 |
| OpenCode / Kimi Code / DSH | OpenCode 走 `opencode serve` + SDK `format: json_schema`；Kimi `-p --output-format stream-json`；DSH `--profile headless --json` | 三者都会写会话 → 只能靠 marker + cwd 过滤（R10）；OpenCode `share: auto` 会公开会话，必须用独立 `OPENCODE_DB` 与 inline 配置关闭分享（待验证） | 未实测 | 部分 | v2 |
| Ollama（可选） | 本机 OpenAI 兼容端点；`format: json` | 完全离线 | 0 | 弱（代码校验 + 重试） | v2（只做 L2 任务） |

共同约束：子进程用 `env -i` 加最小环境（`PATH`、`HOME`、各 CLI 的登录目录），避免继承 `CLAUDE_CODE_ENTRYPOINT` 等变量；stdin 立即关闭（否则 Claude 等 3 秒）；`--max-turns 1` 与 `--json-schema` 冲突，用 3；用户开了 `alwaysThinkingEnabled` 要显式关；超时 120 s 杀进程并记 `failed`。

**能力探测**（`GET /v1/ai/capabilities`，SET-18、A9-08）：按引擎执行 `claude --version`、`codex --version`，解析版本并对照支持矩阵（`--safe-mode`、`--json-schema`、`--max-budget-usd` 的最低版本待验证 AV6）；登录状态用一次最便宜的探测调用（`--max-budget-usd 0.01`，提示「reply ok」）确认，结果缓存 24 h；额度 MVP 只显示不判定：Codex 从最近 rollout 的 `rate_limits`（PR #11 已写入 attrs），Claude 从 `~/.claude.json` 的 `cachedUsageUtilization` 只读（DT-17 v1，字段稳定性待验证 AV7），都没有则显示「未知」；「额度不足跳过」是 v1 后台任务的规则。

**自身会话过滤**（R10）：每次调用的提示第一行是固定 marker `[orbit-analysis v1 task=<task_id>]`；cwd 固定为 `~/Library/Application Support/Orbit/agent-cwd/`；连接器把 cwd 命中该目录或首条真人消息以 marker 开头的会话标为 `session.kind = auxiliary`、`attrs.origin = orbit`，默认不进 `v_analysis_*` 视图（DT 侧补充约定，见 §14）。过渡期 main 旧链路用 `import_codex --exclude-session` 与 `sample_policies` 排除。

### 2.2 模型槽位（AI-02 的一部分）

| 槽位 | 用途 | Claude Code 通道默认 | Codex 通道 | API Key 通道（v1） | 说明 |
| --- | --- | --- | --- | --- | --- |
| `cheap` | L2：facet、分类、簇命名、judge | `--model haiku`（Haiku 4.5） | 不用 | `claude-haiku-4-5` | 价目参考 [pricing](https://platform.claude.com/docs/en/about-claude/pricing)：Haiku 4.5 $1 / $5 每 MTok；Sonnet 5.5 $2 / $10；Opus 5.5 $4 / $20 |
| `main` | L3：叙述、生成、诊断 | 用户当前默认模型（订阅通常为 Sonnet 5.5 / Opus 5.5） | 用户默认模型 | `claude-sonnet-5-5` | `--effort low`；叙述与生成不需要深思考 |
| `judge`（v1） | judge.*（必须 ≠ 生成所用模型） | 若 `main` 生成则 `cheap` 评审；或换另一引擎（Codex）评审 | 同左 | 同左 | 交换顺序成对评审（EV-04） |

槽位 → 具体模型名由能力探测写入 `ai_engine` 配置（用户可改，SET-18）；注册表只记录槽位，不写死模型名。

### 2.3 任务注册表（AI-02）

契约 §3.6 的表是基线，本文把它补成下表（变更项见 §14）。所有任务共享请求 / 响应信封（契约 §3.6）与 `ai_usage` 账本（EV-11）。

| task_id | 层 | 触发 | 打包 | 输入上限 | 输出 schema | 缓存键 | 降级 | 阶段 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `facet.session` | L2 | 用户在设置 / 首次启动点「开始语义分析」；之后导入后对新完成的主会话（开关「仅新会话自动分析」，默认关） | 5–10 会话 / 次 | ≤ 50K | `session_facet` v1.1 MVP 七项（§3.2） | `(session_uid, content_hash, prompt_version, schema_version)`，记录 `model_id` | `status=failed`，只显示 L0 结果 | MVP |
| `facet.chunk_summary` | L2 | `facet.session` 之前，会话脱敏文本 > 30,000 字符 | 单会话按 25,000 字符切块：首尾块原文 + 中段每块 6 项摘要 | ≤ 30K | `{goal, progress, blockers, decisions, files, next}`（每项 ≤ 60 字） | `(session_uid, chunk_idx, chunk_hash, prompt_version)` | §5.2 的 L0 压缩 | v1 |
| `classify.feedback` | L2（v2 可 L1） | 关闭 facet 的用户的歧义候选；用户在 A6-10 点「不准确」后的复判 | 20 条 / 次 | ≤ 12K | `{is_correction, feedback_kind, friction_type, sentiment, confidence}` | `(signal_id, content_hash, prompt_version)` | 保留 L0 结果，`type_source=rule` | v1 |
| `cluster.failure_names` | L2 | A4 失败簇展示前，按 `error_class` 分组后 | 每簇 ≤ 30 条首 200 字 | ≤ 10K | `{clusters:[{error_class, name, member_ids}]}` | `(scope, members_hash, prompt_version)` | 只按 `error_class` 分组 | v1 |
| `cluster.topic_names` | L2 | AN-18 聚类完成且簇 ≥ 2 | 全部簇 / 次 | ≤ 8K | `{clusters:[{cluster_id, name, kind, confidence}]}` | `(scope, members_hash, vectorizer_version, prompt_version)` | 显示「簇 #k」+ top terms | v1 |
| `narrate.overview` | L3 | 概览打开且 `metrics_hash` 变化；用户点「重新生成」 | 1 | ≤ 8K | 契约 §3.3 叙述形状 | `(scope_hash, metrics_hash, prompt_version)` | `narrative.explain()` | MVP |
| `narrate.persona` | L3 | 画像 `axes` 或 `observations` 变化；用户点「自述」 | 1 | ≤ 6K | §3.6 人格文案 schema | `(profile_hash, prompt_version)` | 类型文案库（模板） | v1 |
| `narrate.session_review` | L3 | 用户在 A3 点「让 Agent 复盘」 | 1 | ≤ 10K | 叙述形状 + `lessons[]` | `(session_uid, facet_hash, prompt_version)` | 规则复盘（AN-02 行 + 信号列表的模板句） | v1 |
| `narrate.weekly` | L3 | 每周一 09:00（SET-21）或导出时 | 1 | ≤ 10K | 叙述形状 + `sections[]` | `(window, snapshot_hash, prompt_version)` | `analysis_reports.*_markdown` | v1 |
| `rerank.fit` | L2 | 推荐批次重算后 | ≤ 10 候选 / 次 | ≤ 10K | §4.2 schema | `(batch_id, candidate_id, profile_hash, prompt_version)` | RC-04 顺序 + RC-15 模板解释 | v1 |
| `generate.rule`（含粘合变体 `glue`，AI-06.7）/ `generate.hook` / `generate.skill` | L3 | 用户在 A7 / A9 / Lite「Agent 定制草稿」点「生成」 | 1 | ≤ 12K | 各模板的槽位 schema（§4.3） | `(candidate_id 或 goal_hash, evidence_hash, template_id@version, prompt_version)` | 模板默认值并标「未个性化」，或不生成 | MVP |
| `generate.subagent` / `generate.command` / `generate.workflow_tutorial` | L3 | 同上 | 1 | ≤ 12K | §4.3 | 同上 | 同上 | v1 |
| `generate.revise` | L3 | 用户在 A7「修改已有」候选或 RC-07 精简候选上点「生成」 | 1 | ≤ 12K | 编辑操作列表（§4.3 AI-06.8） | `(target_hash, evidence_hash, template_id@version, prompt_version)` | 确定性拆分（按二级标题）或不改 | v1 |
| `judge.rule_counterfactual` | L2（judge 槽位） | 规则生成后、预览前 | ≤ 10 对 / 次 | ≤ 8K | `{items:[{event_uid, avoidable, reason}]}` | `(rule_hash, event_uid, prompt_version)` | 不给 judge 结论，只显示 lint 与 dry-run | v1 |
| `judge.artifact_review` | L2（judge 槽位） | 生成物通过前三道自检后 | 1 | ≤ 8K | `{issues:[{kind, ref, note}]}` | `(artifact_hash, prompt_version)` | `evaluate_text()` 规则检查 | v1 |
| `diagnose.workflow` | L3 | 用户在 A7 点「深度诊断」 | 1 | MVP ≤ 12K；v1 ≤ 20K | §4.5 schema | 不做结果缓存；24 小时内同一输入哈希直接复用上次 `job_id` 的结果 | 按钮灰显并说明需要开启 AI | MVP（单次调用、只展示）；v1（映射为候选） |
| `ask.plan` + `ask.answer` | L2 + L3 | 用户在 ASK 浮层提问 | 1 + 1 | ≤ 2K + ≤ 12K | `{queries[] ≤ 3}` + `{answer, refs[], next}`（§4.6） | 不缓存 | 预置问题的模板回答（Demo `askAnswer` 逻辑即 L0 版） | v1 |
| `eval.plugin_eval` | L4 | 用户同意装前对照 | 每臂 3 次 | 按 case | 评测 JSON | `(artifact_hash, cases_hash)` | 卡片标「未测」 | v2 |

注册表 MVP 用 Python 常量字典（`TASKS = {task_id: {tier, slot, input_budget, schema, prompt_version, fallback}}`），与引擎、`run_task()`、gate 同放 `src/orbit_backend/ai.py`；schema、提示与模板放 `src/orbit_backend/data/ai/{schemas,prompts,templates}/`。YAML 注册表与 `max_items_per_call / idle_only / requires_user_trigger / eval_suite / baseline_score` 列随 v1 的后台调度一起加。

### 2.4 预算、封顶与不污染数据（AI-11）

| 规则 | MVP（用户触发、串行） | v1（后台任务） |
| --- | --- | --- |
| 调用前估算 | 用注册表的 `input_budget` × 条数 + 固定开销估「本次 N 次、约 X token」，界面先显示再执行（A1-08、A9-11、OB-05）；Claude 可用 `claude -p "/context"` 校准固定开销 | 同左 |
| 触发 | facet：用户点「开始语义分析」做首次回填（分析窗口内 ≤ 200 个合格会话，不受任何日总额限制）；之后「仅新会话自动分析」开关（默认关）在每次导入后只处理新会话。叙述 / 生成 / 诊断：用户点击 | 空闲判定（无运行中会话 ≥ 10 分钟且接电源或电量 > 30%）；每轮 ≤ 50 个新会话、≤ 10 次调用；已知剩余额度 < 25% 跳过（依赖 DT-17、AV7）；每日后台总额默认 2M token 或 $2 |
| 执行 | 一次一个子进程，串行；进度 n / N 可见、可取消（已完成的批次保留） | 并发 ≤ 3，同批同模型 |
| 预算封顶 | 每次调用 `--max-budget-usd`（cheap 0.1、main 0.5） | 同左 + L4 1.0 |
| 失败 | 单项重试 1 次（把校验错误附回提示）→ `failed`；整批失败 → 停止、在设置页提示，不自动重试 | 1 / 5 / 30 分钟退避；连续 3 批失败当天停用；`ai_job.lease_until` 防 App 重启重复提交 |
| 只处理新会话 | facet 只对 `status ∈ completed/interrupted/failed` 或 ≥ 30 分钟无新事件的主会话；运行中的不抽 | 同左 |
| 不污染 | marker + 专用 cwd + 不落会话（§2.1） | 同左 |

### 2.5 上下文包构建与预览（AI-08）

上下文包是所有任务的唯一输入形态；由代码从 `analysis.db` 与 `orbit.db`（只读）组装，再过第二遍脱敏（main `privacy.direct_user_text()`，规则表以 DT-10 写入时脱敏为准），逐项计 token（中文按 1 字 ≈ 1 token 估，待验证 AV4）。

| 包项 | 来源（真实列名） | 默认 | 用于 |
| --- | --- | --- | --- |
| `session_rows[]` | main `session_features()` 行：`features`、`workflow.transitions` 前 10、`correction_signals`、`prompt_structure`、`objective_outcomes`、`subjective_outcome_candidates`、`language_signals`；L0 补 `scene`（`feedback.scene_of()`）与 `interaction_pattern`（AN-08 规则） | 开 | facet、复盘、诊断 |
| `tool_sequence[]` | `v_analysis_tool_call`：`kind`、`command_head`、`status`、`error_class`、`duration_ms`（只保留 ≤ 60 条；连续同类合并为 `×n`） | 开 | facet、复盘、hook 生成 |
| `human_messages[]` | `v_human_message.text`（已脱敏）截 500 字，含 `event_uid` | 开 | facet、分类、生成 |
| `assistant_replies[]` | `event(kind=message.assistant).text` 截 300 字；工具输出只留首 200 字的 `error` 文本 | 开 | facet、复盘 |
| `candidates[]` | AN-05 定位的候选信号：`signal_id`、`event_uid`、`kind`、`detector`、`snippet_redacted` | 开 | facet、分类 |
| `metrics` | `analytics/overview` 段的 `counts / usage / activity_rhythm` + `metrics` 端点的带区间指标 | 开 | 叙述、诊断 |
| `problems[]` | `problem` 表：`type / key / sessions / denom / wilson_lo / weekly_count`，每条 ≤ 3 个证据片段 | 开 | 叙述、适配、生成、诊断 |
| `profile` | `profile.axes / observations / interaction`（只数值与标签） | 开 | 人格文案（v1）、适配（v1） |
| `inventory[]` | `inventory_item`（DT-09）名称与类型；缺时标 `unavailable` | 开 | 适配、生成、诊断 |
| `existing_rules[]` | 目标文件（`AGENTS.md / CLAUDE.md / settings.json`）中与候选问题关键词命中的段落 ≤ 3 段 × 400 字，每段带 `anchor_hash` | 开 | 生成（避免重复与冲突；AI-06.8 的编辑目标） |
| `catalog_items[]` | `catalog_item.summary / trial / limitations`（RC-02 / RC-09 匹配到的 ≤ 3 条） | 开 | 生成（粘合规则，AI-06.7） |
| `raw_snippets[]` | `Store.read_raw(record_uid)` 原文片段 | **关** | 用户逐条确认后才附（A9-06） |

**入口 → 证据包（L0，生成类任务）**：证据不由模型自己找，由入口决定。0 命中时只用模板默认值并标「未个性化」，不扩大到全量历史；`ai_job.goal_source` 记录入口，A9-06 的包项随入口变化（修 A9-06「上下文包不随目标或项目变化」与 A5-03「目标只有摩擦名」）。

| 入口 | `goal_source` | 证据包 |
| --- | --- | --- |
| A7 候选「生成 / 交给 Agent 定制」（A7-11、A7-16） | `candidate` | `problem.evidence_session_uids` 前 5 个会话各取 1 条片段（`top_signal_ids` 对应的 `snippet_redacted`） |
| A6-03「把高频纠偏写成规则」 | `phrases` | `phrases_top[]` 前 4 条的 `evidence`（每条 ≤ 3 个 `event_uid`）+ 对应 `problem_id` |
| A5-03「为此项目起草规则」 | `project` | 该项目 `problems_top[]` ≤ 3 条 × 每条 ≤ 2 片段 + 项目的 `existing_rules` |
| A5-11「封装为 Skill」 | `workflow` | `workflow_pattern.example_turn_uids` 的 `tool_sequence`（≤ 3 轮）+ 该变体的 `activities` |
| ASK-07「交给生成工坊」 | `ask` | `answer.refs[]` 解析到的 ≤ 5 条片段 |
| A9-05 手输目标 / Lite「Agent 定制草稿」 | `manual` | `Scope` 内 `event_fts` BM25 前 5 条真人消息（脱敏）+ 与 `problem.key` 的关键词匹配得到的 ≤ 2 条 `problem` |

`POST /v1/ai/preview {task_id, scope, selection, goal_source}` 返回包内容、每项 token、合计与预估费用、脱敏命中数、`preview_digest`；生成类任务提交 `POST /v1/ai/jobs` 时必须回传 `preview_digest`，包内容变化即拒绝。facet 等分析类任务没有逐项预览，只显示一次合计估算后执行。

## 3. 分析侧 AI 任务

### 3.1 总表

| 任务 | ID | 触发 | 输入（只发这些） | 档位 | 输出 | 复用方 | 阶段 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 逐会话语义 facet | AI-03 | 用户点「开始语义分析」（首次回填）；之后开关「仅新会话自动分析」；重算触发：`prompt_version / schema_version` 升版 | §2.5 的 `session_rows`（含 L0 算好的 `scene / interaction_pattern`）`+ tool_sequence + human_messages + assistant_replies + candidates`，5–10 会话打包 | L2 cheap | `session_facet` v1.1 MVP 七项：`goal、task_type、outcome、friction_types、candidates[]、repeated_instructions、summary` | AN-05 / AN-06 / AN-08 / AI-05 / AI-06 / FE-05 / FE-08 | MVP（可关闭） |
| 长会话分块摘要 | AI-03.1 | 单会话脱敏文本 > 30,000 字符 | 首尾两块原文 + 中段 6 项摘要 | L2 cheap | `{goal, progress, blockers, decisions, files, next}` | AI-03 | v1（MVP 用 §5.2 的 L0 压缩） |
| facet v1 扩展字段 | AI-03（v1） | 随 facet | 同 facet + §2.5 `existing_rules` 的 L0 预筛段落 | L2 cheap | `satisfaction_signal`、`candidates[].sentiment`、`key_moments[]`（只 `deviation \| other`）、`violated_rules[]` | AN-07 / AN-09（AI 时刻）/ RC-06 #2 | v1 |
| 反馈语 / 情绪分类 | AI-04.1 | 关闭 facet 的用户的歧义候选；A6-10「不准确」复判 | 单条候选 + 前一条助手摘要 + 任务上下文，20 条打包 | L2 cheap（v2：L1） | `feedback_kind / is_correction / friction_type / sentiment / confidence` | AN-05 `signal(type_source=facet)`、AN-07 | v1 |
| 失败簇命名 | AI-04.2 | A4 失败原因面板 | 按 `error_class` 分组的失败输出首 200 字 × ≤ 30 | L2 cheap | `{error_class, name, member_ids}` | A4 失败原因、`problem.key` 可读名 | v1 |
| 主题簇命名 | AI-04.3 | AN-18 聚类完成且簇 ≥ 2 | 每簇 top terms 20 + 3 条代表会话 facet `summary` | L2 cheap | `{cluster_id, name ≤ 12 字, kind, confidence}` | A6-09、A2-11 | v1 |
| 概览叙述 | AI-05.1 | `metrics_hash` 变化；用户点「重新生成」 | 汇总统计 + `problems_top` ≤ 5（每条 ≤ 3 条摘要）+ 上期对比 + Top 3 候选 | L3 main | 契约 §3.3 叙述形状，scene `status_update` | A1-07…A1-11、Lite「AI 一句话解读」 | MVP |
| 单会话复盘 | AI-05.2 | 用户在 A3 点「让 Agent 复盘」 | 该会话 facet + AN-02 行 + 信号 + 关键时刻 | L3 main | 叙述形状 + `lessons[]` | A3-04、A3-18 | v1 |
| 周报叙述 | AI-05.3 | 每周一 09:00（SET-21）或导出时 | AN-14 `report_snapshot(weekly)` | L3 main | 叙述形状 + `sections[]`，scene `weekly_report` | SET-21、EXP-02 | v1 |
| 人格解读文案 | AI-05.4 | `profile` 变化或用户点「自述」 | `axes`、`observations[]` 前 5、`interaction`、前 3 类摩擦、`compare_previous` | L3 main | §3.6 schema，scene `profile` | A2-07 / A2-08 / A2-15 | v1（MVP 用类型文案库） |

### 3.2 逐会话 facet（AI-03）

**触发与过滤**：主会话（`session.kind = main`）、确认真人消息 ≥ 2 条、`observed_span ≥ 60 s`（与 `/insights` 的阈值一致，便于 DT-18 对照）、状态非运行中。超出单会话 6K token 上限时按 §5.2 的 L0 压缩（保首末各 3 条真人消息全文、全部候选片段、中段每条首 80 字、工具序列同类合并），记 `chunked: true`；v1 才走 `facet.chunk_summary`（首尾块原文 + 中段 6 项摘要）。不满足过滤的会话不抽 facet，界面显示「未做语义分析（会话太短）」而不是空值。

**输入预算（每会话）**：AN-02 行压缩成 ≤ 150 token 的键值（含 L0 算好的 `scene`（main `feedback.scene_of()`）与 `interaction_pattern`（AN-08 规则），两者是输入不是输出）；`tool_sequence` ≤ 60 条 × ≈ 8 token；真人消息 ≤ 12 条 × ≤ 500 字；答复 ≤ 12 条 × ≤ 300 字；候选 ≤ 10 条 × ≈ 40 token；单会话上限 6K，超出先裁答复再裁早期消息。典型 3–4K；8 会话打包 ≈ 28–32K + 静态前缀 ≈ 2.5K（指令、枚举表、schema、2 个示例）+ 固定开销 ≈ 0.7K。

**输出 schema `session_facet` v1.1 MVP 七项**（在契约 §3.3 v1 上：新增 `goal / friction_types / chunked` 与 `candidates[].confidence`；`scene / interaction_pattern` 改为输入；进契约第 3 版，§14 第 1 条）：

```json
{
  "session_uid": "…",
  "goal": "≤ 40 字；只写用户明确提出的请求，不写 Agent 自发的探索",
  "task_type": "feature|bugfix|refactor|review|docs|research|ops_deploy|data|config|chat|other",
  "outcome": "fully_achieved|mostly_achieved|partially_achieved|not_achieved|unclear",
  "friction_types": ["wrong_approach|misunderstood_request|excessive_changes|buggy_output|tool_env_failure|permission_friction|process_overhead|context_loss|parallel_conflict|quota_interrupt|other"],
  "candidates": [{"signal_id": "…", "event_uid": "…", "is_correction": true,
                  "feedback_kind": "accept|correct|refine|requirement_change|new_task|clarify|other",
                  "friction_type": "<同上>|none", "confidence": "high|medium|low"}],
  "repeated_instructions": [{"text_redacted": "≤ 80 字", "dimension": "clarity|brevity|grounding|actionability|autonomy|planning|verification|scope|convention|other"}],
  "summary": "≤ 40 字",
  "chunked": false
}
```

**v1 扩展字段**（随 AN-07、AN-09（AI）、RC-06 #2 加入，每加一个字段 EV-04.1 多一组标注）：`satisfaction_signal: explicit_positive|implicit_continue|explicit_negative|abandoned|unclear`（只依据显式信号与是否继续，与 `/insights` 的 `likely_satisfied` 口径一致）；`candidates[].sentiment: positive|neutral|negative|frustrated`；`key_moments: [{event_uid, kind: "deviation|other", label ≤ 30 字}]`——规则类时刻（correction、failure_streak、verify_pass …）只由 AN-09 产出，AI 只补「偏离用户目标」一类，写 `key_moment(origin=ai)` 空心标记；`violated_rules: [{rule_anchor_hash, event_uid, confidence}]`——输入只送 L0 预筛结果（AN 先把纠偏 / 要求消息与 §2.5 `existing_rules` 段落做字符 n-gram 重合，每会话 ≤ 3 对），gate 要求 `rule_anchor_hash` 必须在输入里；MVP 的「规则写入后仍被违反」（RC-06 #2 / #12）只限 Orbit 已装规则，由 EV-07 机械层判定。

规则：`candidates[].signal_id / event_uid` 必须出现在输入里，否则该项丢弃；`friction_types` 只能来自 `candidates` 里出现过的类型或工具失败证据，不许凭空添加；极短会话归 `chat`；`confidence` 是闭集不是概率。

**缓存与失效**（R3、R4）：键 `(session_uid, content_hash, prompt_version, schema_version)`，`content_hash` 是实际发送的包的哈希；`model_id` 只记录与展示，不进键。
- 换模型或引擎：旧 facet 继续有效并显示其 `model_id`，只对新会话用新模型；全量重抽需用户确认并先显示估算（修 SET-18「切换引擎后已有结果怎么处理」）。
- 脱敏规则变化：只重抽「脱敏命中集合有变化」的会话（按会话记录 `redaction_hits_hash`）。
- `prompt_version` 升版：只对分析窗口（默认 90 天）内的会话懒重算，更早的保留旧版并标「旧版 facet」。
- 会话内容变化（追加事件）：标 `stale`，下一次「仅新会话」处理时重算。
- 首次回填：只覆盖分析窗口内最近的 ≤ 200 个合格会话，更早区间在用户查看时按需补；回填顺序 = 先抽有 L0 候选或是活跃 `problem` 证据的会话，其余按分层抽样补足 `task_type` 分布所需样本（R9；质量与 AV1 / AV8 一并验证）。
- `session_facet` 表可整表重建，不进 `orbit.db`。

**打包与解析**：请求 `items[]` 每项带 `ref_id = session_uid`；响应按 `ref_id` 对齐，缺项记 `skipped`，schema 不合法的单项重试一次（把校验错误附在重试提示里），仍失败记 `failed`，整批其余项照常入库；同批不换模型；一批失败超过一半则停止并提示（§2.4）。

**失败降级**：A6 / A3 只显示 L0 的 `correction_terms`、`bottlenecks.diagnose` 候选与规则关键时刻；摩擦分类面板显示「语义分析未完成 n / N」；`signal(type_source=facet)` 不存在时 AN-06 只用规则信号。

**评测**（门槛口径只写在 `evaluation.md` §2.3）：EV-04.1 字段 κ ≥ 0.6 才默认展示并参与 AN-06 计数；打包一致性（同一批会话分别单会话调用与 8 会话打包，逐字段一致率 ≥ 0.9，契约 V5 = AV1）；DT-18 对照 `~/.claude/usage-data/facets` 的 `outcome` 只作参考；漂移监测：`other` 占比 > 15% 或某枚举值 30 天内零出现 → 提示检查 schema；EV-10 `inaccurate` 标签回流为评测用例。

### 3.3 反馈语 / 情绪分类（AI-04.1，v1）

**定位**：facet 的 `candidates[]` 已经对同一批 L0 候选做了同样的判定；本任务只服务两种情形——用户关闭 facet 但想要摩擦细分，或在 A6-10 点「不准确」后复判一条短语。两条路径共用 schema 与 gate，避免重复实现。

**L0 先定位**：候选来自 main `features.correction_terms()`（`CORRECTION` 词表，proxy）、`subjective_outcome_candidates`、`feedback.signals()`（`category ∈ request/refinement/correction`）、`bottlenecks.diagnose()` 的 `explanation_revision`。词表强命中且与前一条助手消息同任务的直接判定，不送模型；送模型的只有：多词表冲突、短消息（≤ 20 字）无词表命中但紧跟工具失败、`polarity = unclear`、用户点「不准确」的短语。

**输入**：每条 ≤ 4K（候选原文 ≤ 500 字 + 前一条助手摘要 ≤ 300 字 + `scene / task_id` + 前后各一条真人消息首 100 字），20 条打包。**输出**：`{signal_id, is_correction, feedback_kind, friction_type, sentiment, confidence}`（枚举同 §3.2）。`feedback_kind` 是主字段（内部资料 [TOOLS] §8 的「满意度先分类」原则）；`sentiment` 只作 AN-07 的一个打标函数，界面标「实验性」；没有人工标注前不给 0–100 满意度分。「三票两胜」随本任务一并后置到 v1，MVP 不做多次调用。

**缓存**：`(signal_id, content_hash, prompt_version)`。**降级**：保留 L0 结果，`type_source = rule`，`sentiment = null`。**评测**：EV-04 二元 judge TPR / TNR（κ ≥ 0.6 且 TPR、TNR ≥ 0.8 才写 `type_source = facet`）；Rogan–Gladen 校正估计比例；中文纠偏词表精度 ≥ 0.5 的假设见契约 V3。

### 3.4 簇命名（AI-04.2 / AI-04.3，v1，建立在 AN-18 之上）

AN-18（main `analytics/text.representation()`：字符 2–4 gram TF-IDF → SVD ≤ 32 维 → cosine DBSCAN eps 0.35 / min 2，≥ 4 样本才聚类）产出 `clusters[{cluster_id, size, top_terms, entity_ids}]` 与噪声点；它刻意「不命名、不带人格含义」。命名是纯展示层：

| 项 | 规则 |
| --- | --- |
| 触发 | `clustering.status = available` 且簇数 ≥ 2；`members_hash` 不变不重算 |
| 输入 | 每簇：`top_terms` 20 个 + 3 条代表会话的 facet `summary`（没有 facet 的簇用 3 条最靠近质心的真人消息首 120 字）；全部簇一次送，≤ 8K |
| 输出 | `{cluster_id, name ≤ 12 字, kind: "project_work\|research\|writing\|ops\|data\|config\|chat\|other", confidence: "high\|medium\|low"}`；名称不得含项目路径、人名、文件名（lint：命中脱敏占位符即拒绝） |
| 缓存 | `(scope, members_hash, vectorizer_version, prompt_version)` |
| 降级 | 显示「簇 #k · n 个会话」+ 前 5 个 top terms；噪声点显示「未归类」 |
| 评测 | EV-04.2：lint 通过率 100%；两簇同名率 0；EV-10 `inaccurate` < 10% |

失败簇命名（AI-04.2）同一套做法，输入换成按 `error_class` 分组的失败输出首 200 字（脱敏后）；A4 失败原因面板与 `problem.key`（如 `retry_loop:wrangler`）的可读名用它。MVP 只按 `error_class` 分组。

### 3.5 会话与周期叙述（AI-05.1 / 05.2 / 05.3）

**原则**：先给结论，所有数字来自输入，所有引用是真实 ID；输出沿用 main `narrative.explain()` 的 JSON 形状（`summary / sample_summary / findings[{title,text,scene,evidence_ids,example}] / bottlenecks / next_step / caveats / audience / main_evidence_ids`），额外带 `prompt_version / model_id`，前端不区分模板版与 AI 版的渲染路径。每个任务固定一个 `evaluate_text()` 的 scene（main `SCENE_BUDGETS` 遇到未知 scene 抛 `ValueError`，所以不能临时造名）：

| 任务 | scene（EV-09） | 输入（≤ 8–10K） | map-reduce | 结论句的硬约束 | 阶段 |
| --- | --- | --- | --- | --- | --- |
| `narrate.overview` | `status_update`（450 字） | `overview.counts / usage / activity_rhythm`、`metrics`（带 `n / lo / hi / basis`）、`problems_top` ≤ 5（每条 `type / key / sessions / denom / weekly_count` + ≤ 3 条 facet `summary`）、`compare_previous`、Top 3 候选的 `title / problem_id`、`profile.code` | map：代码按问题挑 ≤ 3 条 facet 摘要（不调模型）；reduce：一次调用写三段「做得好 / 卡在哪 / 立刻可做」（A1-09…A1-11） | 每段 ≤ 60 字；`做得好` 只能引用 `basis = measured` 的指标；`卡在哪` 必须引用 `problem_id`；`立刻可做` 只能引用输入里的 `candidate_id`；分母 < 5 的指标不许出现 | MVP |
| `narrate.persona` | `profile`（900 字） | §3.6 | 单次 | §3.6 gate | v1 |
| `narrate.session_review` | `bottleneck`（1,200 字） | 该会话 facet 全文 + AN-02 行 + `signals[]` + `key_moments[]` + 同项目近 5 个会话的 facet `summary` | 单次 | `lessons[] ≤ 3`，每条 `{text ≤ 60 字, mechanism: "rule\|hook\|skill\|subagent\|workflow\|none", evidence_ids[]}`；A3-18 的「生成规则 / 加 Hook」按钮直接拿 `mechanism` 作 AI-06 的入口 | v1 |
| `narrate.weekly` | `weekly_report`（新增 scene，随 `evaluation.md` 的契约建议进 `SCENE_BUDGETS`，同批还有 `share_card / menubar`） | AN-14 固定窗口快照 `report_snapshot(kind=weekly)`（周序列、上期对比、问题变化、已装建议的 `rec_outcome`） | map：每节一次（概览 / 问题 / 建议效果），reduce：At a Glance 一次 | 每节 ≤ 200 字；效果一节只能用 `rec_outcome.status = ok` 的项，其余写「未测」 | v1 |

**代码 gate（R2）**：① JSON Schema；② `evidence_ids / main_evidence_ids` 逐个查 `event` 表，不存在即整段降级；③ 数字白名单：文本中的每个数字（含百分比）必须在输入的数值集合（含四舍五入到 1 位）里，否则该 finding 丢弃；④ `evaluate_text(text, scene)`，出现 `error`（`empty_information / missing_fact / unsupported_claim / unverified_certainty`）即整段退回模板，`warning` 保留但记录；⑤ 禁用词：「保证」「一定」「证明有效」（`_CERTAINTY` 已覆盖）。

**缓存**：`(scope_hash, metrics_hash, prompt_version)`；数字没变就不重算，A1-08「重新生成」是显式失效。**降级**：`narrative.explain()`；周报降级 `analysis_reports.{profile,bottlenecks,process}_markdown`。**评测**：EV-09 规则检查通过率；EV-10 用 `reader_eval.make_pack()` 把同一事实下的模板版与 AI 版作为 `variants` 盲评（A/B 顺序交换、`purpose = evaluation_only`），`preference_counts` 与 4 维评分决定 AI 版是否默认展示（v1）；EV-04 judge 不用于叙述。

### 3.6 人格解读文案（AI-05.4，v1）

MVP 用 Advance Demo `TYPES` 式的类型文案库 + 模板量化旁白（A2-07 现有做法）；四轴本身是实验性（AN-08），先不为它花 token。v1 的 AI 版：

**输入**（≤ 6K）：`profile.axes`（四轴 `value / lo / hi / n_units / letter`，区间跨 50% 的轴字母为 `?`）、`code / type_name / experimental`、`observations[]` 前 5（`dimension / label / sessions / denominator`）、`interaction`、AN-08 `opening_structured_rate / planning_rate / verify_requested_rate`、前 3 类 `friction_types` 的会话数、`compare_previous` 的轴变化、用户的 `label(not_me)` 原因枚举（有则附）。

**输出**：`{headline ≤ 30 字（含类型名；任一轴为 ? 时必须说明「暂定」）, traits[{text ≤ 8 字, metric, value_ref}], tradeoffs[{axis: D|P|M|V, text ≤ 50 字}], blind_spots[{problem_id, text ≤ 50 字}], caveats[≤ 40 字]}`。gate：`traits ≤ 5` 且每条 `metric` 必须在输入里、`value_ref` 必须等于输入值；`blind_spots` 的 `problem_id` 必须存在；文本不得出现「性格」「人格测试」字样（lint）；通过 `evaluate_text(scene=profile)`。**缓存**：`(profile_hash, prompt_version)`。**评测**：EV-10「不像我」标签率不高于模板版；读者盲评（模板 vs AI）不劣于模板版才默认展示。

### 3.7 facet 一次抽取、多处复用

| 消费方 | 读哪个字段 | 怎么用 | 口径标记 | 阶段 |
| --- | --- | --- | --- | --- |
| AN-05 信号 | `candidates[]`（`is_correction / feedback_kind / friction_type / confidence`） | 写 `signal(type_source=facet, detector=facet.session@<prompt_version>)`；与规则信号同会话同类型只计一次；`confidence = low` 的不写 | `basis = proxy` | MVP |
| AN-06 问题升级 | 同上 + `friction_types` | 参与会话计数（字段 κ ≥ 0.6 之后）；多数证据来自 facet 时 `problem.evidence_basis = facet`，卡片标「AI 判定」 | — | MVP |
| AN-08 画像 | `repeated_instructions[]` | `observations` 的补充证据与 AI-06.1 的规则候选（RC-06 #1 `repeated_instruction`） | — | MVP |
| AI-05 叙述 | `summary`、`goal` | 每类问题 ≤ 3 条摘要 | — | MVP |
| AI-06 生成 | `repeated_instructions[]`、`candidates[].event_uid` | 证据包的片段来源（§2.5「入口 → 证据包」） | — | MVP |
| RC-08 模型建议 | `outcome × task_type × model_id` | 分层描述（MVP 只展示） | — | MVP |
| FE-05 / FE-08 | `goal / summary / friction_types` | A3 列表摘要、A6 摩擦分类、筛选 `friction_type` | — | MVP |
| EV-01.1 对照 | `outcome` | 与 `/insights` facets 的 `outcome` 对照 | 只作参考 | MVP |
| AN-07 情绪 | `candidates[].sentiment`、`satisfaction_signal` | 作为一个打标函数参与等权投票，`confidence = low` 的不计 | 实验性 | v1 |
| AN-09 关键时刻 | `key_moments[]`（`deviation \| other`） | 写 `key_moment(origin=ai)` 空心标记；用户确认后 `origin=user` | 紫色虚线 + 置信度 | v1 |
| RC-06 #2 / #12 | `violated_rules[]` | AN-05 `signal(kind = rule_violation, type_source = facet)`，以 `rule_anchor` 为 key 升级 | — | v1 |
| AI-12 适配 | `task_type` 分布、`outcome` 按 `task_type` | 判断候选是否对应用户常做的任务类型 | — | v1 |

## 4. 推荐侧 AI 任务

### 4.1 总表

| 任务 | ID | 触发 | 输入（只发这些） | 档位 | 输出 | 消费方 | 阶段 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 生成式推荐：模板填槽 | AI-06.1 / 06.3 / 06.4 | 用户在 A7「生成 / 交给 Agent 定制」、A9、Lite「Agent 定制草稿」点「生成」；或候选 `remedy.template` 有必填槽位（RC-02 ④ `generate_request`） | §2.5「入口 → 证据包」（≤ 5 条片段）+ `existing_rules` + 模板 + 槽位说明 + 匹配到的 Catalog 条目 | L3 main | 槽位 JSON；文件由 RC-12 渲染器拼出 | RC-12 `install_plan`、A9-14、A7-13 | MVP：规则、hook、SKILL.md |
| 与专家 skills / plugins 组合 | AI-06.7 | RC-02 ② / RC-09 已匹配种子条目且候选需要「粘合」 | `generate.rule` 的 `glue` 变体：输入多给已匹配的种子 skill 的 `summary / trial / limitations` | L3 main（同一次 `generate.rule` 调用） | 只产「遇到 X 时使用 `<skill>`」规则段，`uses_catalog_items[]` | IN-08 安装条目 + 粘合规则 | MVP（最小形态）；v1：粘合 hook |
| 子代理 / slash command / 工作流教程 | AI-06.5 / 06.6 | 同上 | 同上 | L3 main | §4.3 | RC-12 | v1 |
| 修改已有文件 | AI-06.8 | A7「修改已有」候选（RC-06 #4、闸门 7 失败转修改）、RC-07「精简 / 拆分」候选 | 目标文件相关段落（≤ 3 段 × 400 字，带 `anchor_hash`）+ 证据 + 约束 | L3 main | 编辑操作列表（§4.3） | RC-12 渲染 diff；IN `replace_block / move_block` | v1（MVP 只做确定性拆分） |
| 三道自检 + judge | AI-07.1–07.4 | 每次生成后、预览前 | 生成物 + 历史 `tool_call` / 消息 | L0（①②③）+ L2 judge（④） | 通过 / 失败 + 问题清单 | A9-15、IN-02 预览 | MVP：①②③；v1：④ |
| 高层次 workflow 诊断 | AI-10 | 用户在 A7 点「深度诊断」 | `problems[]` + main `workflow().transitions` 前 15 + AN-04 变体前 5（有则给）+ 任务数 / 验证率 + 已装清单，≤ 12K | L3 main | `findings[]`（§4.5） | A7-03 展示（MVP）；RC-06 映射为候选（v1） | MVP（单次调用、只展示） |
| 候选适配判断与个性化解释 | AI-12 | RC 批次重算后 | 画像摘要、问题列表、已装清单、≤ 10 条候选 | L2 cheap | 每候选 `fit / reasons[] / explain ≤ 60 字 / pair_with[]` | A7-08 / A7-12 文案、`unfit` 降序 | v1（MVP 用 RC-15 模板句） |
| 问本地 Agent | AI-09 | 用户在 ASK 浮层提问 | 计划 → 代码执行只读查询 → 回答（§4.6） | L2 + L3 | `{answer, refs[], next}` | ASK-01…07、A1-04、A2-04、A3-04 | v1（MVP 只有预置问题的 L0 模板回答） |
| 可自动化操作清单 | —（L0，无 task_id） | 用户在 A4 点「找出可自动化的操作」 | AN-04 `three_step_chains`、AN-05 `would_prompt / retry_loop`、AN-11 `installed_unused` | L0 | 对应 RC 候选的确定性清单（§4.7） | A4-03、ASK `tool_worst / approvals / mcp_unused` 意图 | MVP（不调模型） |

### 4.2 候选适配判断与个性化解释（AI-12，v1）

RC-04 的 `priority` 是确定性的，AI 不改分数；它只回答两个人读得懂的问题：「这条对我合不合适」「为什么是我」。MVP 的卡片文案全部用 RC-15 模板句（`recommend.trial_method()` / `narrative.explain()` 已实现），本任务 v1 再加。

**输入**（≤ 10K，一批 ≤ 10 条候选）：`profile`（`code`、`observations` 前 5、facet `task_type` 分布）、`problems[]`（`problem_id / type / key / sessions / denom / weekly_count`）、`inventory[]`（名称、类型、最近 30 天调用数）、候选：`candidate_id / title / remedy.kind / target_agents / benefit.unit / risk.flags / explain.reason（模板句）/ remedy_rule 一句话 / evidence.counts`。

**输出**：`{items: [{candidate_id, fit: "fits|partial|unfit|unknown", reasons: ["already_covered_by_installed|conflicts_with_existing_rule|agent_unsupported|workflow_mismatch|task_type_mismatch|evidence_weak|duplicate_of_candidate|good_fit_evidence|other"], explain: "≤ 60 字；必须引用一个 problem_id 或 observation 的 dimension；不写收益数字", pair_with: ["<candidate_id>"]}]}`。

**用法**：`fit = unfit` 的候选不删除，降到同批末尾并显示「AI 认为可能不适合：<reason>」（用户可反馈）；其余保持 RC-04 顺序；`pair_with` 供 A7「可以一起装」提示。`explain` 替换 `candidate.explain.reason` 时写 `explain.source = ai`，模板句保留在 `explain.template_reason` 供降级与对照。收益数字仍由 L0 从 `score.weekly_saving` 渲染并标 `measured / estimated / 未测`。

**缓存**：`(batch_id, candidate_id, profile_hash, prompt_version)`。**降级**：RC-04 顺序 + RC-15 模板句。**评测**：EV-05 曝光 `not_applicable` 率按 `fit` 分层（`unfit` 显著高于 `fits`，否则关掉降序只留解释）；回放 HitRate@3（有 / 无重排）。

### 4.3 生成式推荐：模板与槽位（AI-06）

**原则**：生成物 = 仓库模板（`template_id@version`，内容哈希固定）+ 模型填的有类型槽位 + 代码填的证据与落点。模型不写脚本体、不写 JSON 骨架、不决定文件路径、不决定权限前缀。渲染器（RC-12）输出 `install_plan.targets[]`，每行标注来源：模板行 `+`、AI 槽位行 `✦`、删除行 `−`（Demo A7-13 / A9-14 的标记语义照用）。权限白名单（`permissions/readonly-allowlist@1`）**不是生成任务**：前缀清单来自 DT-13 `command.readonly` 词表，说明句用模板句（「这些命令只读、不改文件」），原 AI-06.2 删除。

| 产物 | template_id | 模型填的槽位（类型、上限） | 代码填的部分 | 落点（IN-01，与 `recommendation.md` §8.2 一致） | lint 要点 | 阶段 |
| --- | --- | --- | --- | --- | --- | --- |
| 规则片段 AI-06.1 | `rules/paragraph@2` | `rules[] ≤ 5`，每条 ≤ 60 字的祈使句，必须「可验证」（含动作 + 条件或对象）；`title ≤ 12 字` | 标记块 `<!-- orbit:rule id=… evidence=… -->`、证据回链、`dimension` | Claude Code `~/.claude/CLAUDE.md`（用户层）或项目 `AGENTS.md` 块（并确保 `CLAUDE.md` 含 `@AGENTS.md`）；子目录 `.claude/rules/<id>.md`（`paths`）；Codex `~/.codex/AGENTS.md` | 与已有规则相似度 ≥ 0.8 判重复；与 `permissions.deny` / 已有「不要…」冲突判冲突；Claude 单文件 < 200 行、Codex 拼接 ≤ 32 KiB（`docs/research/landscape.md` RS-21）；不含路径用户名、密钥占位符 | MVP |
| 粘合规则 AI-06.7（`generate.rule` 的 `glue` 变体） | `rules/paragraph@2`（`variant = glue`） | 同上，但每条规则必须出现 `uses_catalog_items[]` 里的一个条目名（「遇到 X 时使用 `<skill>`」） | `uses_catalog_items[] = 输入给的条目 ID`（gate 校验相等） | 同上 | 同上 + `uses_catalog_items` 越界即丢弃 | MVP |
| Hook AI-06.3 | `hooks/retry-breaker@2`（← `tool_env_failure`）、`hooks/verify-before-commit@2`（← `missing_verification`，PreToolUse `git commit`）、`hooks/post-edit-check@2`（← `missing_verification` 格式 / 编译类、RC-06 #3；PostToolUse，matcher `Edit\|Write`）、`hooks/stop-verify@2`（← `missing_verification`，验证阶梯第二级；Stop 时自上次成功验证后有编辑就运行或提示验证命令）、`hooks/compaction-reminder@2`（← `context_loss`）、`hooks/scope-guard@2`（← `unsafe_operation`，见 `recommendation.md` 高风险操作一项） | `matcher`（闭集：`Bash\|Edit\|Write\|Task\|*`）、`threshold`（整数区间，如重复失败 2–5）、`message ≤ 120 字`、`command_heads[] ≤ 10`（只能从证据里出现过的 `command_head` 中选）；`post-edit-check` 的 `file_glob` 只能从证据扩展名中选，`command` 只能从该项目历史成功过的验证族 / formatter `command_head` 中选 | hook 事件名、`settings.json` 结构、脚本体（仓库自带，内容哈希固定）、退出码语义 | Claude Code `settings.json /hooks/<Event>` `merge_json` + 脚本 `~/Library/Application Support/Orbit/hooks/<template_id>@<version>.sh`；Codex `~/.codex/hooks.json` + 同一脚本（按哈希信任，标「已安装、未信任」）；pi 需 TS extension（v2） | JSON 合法；脚本哈希与模板一致（文件名带版本便于校验）；`message` 不含 shell 元字符；[hooks 文档](https://code.claude.com/docs/en/hooks) | MVP |
| SKILL.md AI-06.4 | `skills/procedure@1` | `name`（kebab，≤ 64）、`description ≤ 1024 字符`（含触发短语，取自用户原话）、`steps[] ≤ 8` 每条 ≤ 80 字、`dont[] ≤ 5`、`verify ≤ 80 字`、`allowed_tools[]`（闭集） | frontmatter、目录结构、`license`、来源与证据注释 | `~/.claude/skills/<name>/SKILL.md`；Codex `~/.agents/skills/<name>/`（Agent Skills 规范，[specification](https://agentskills.io/specification)） | 规范字段长度；`name` 不与已装清单冲突（A9-15）；只过自检 ①②，description 触发评测 v1（EV-06）；RC 侧仍「检索优先」（`recommendation.md` §5），只在无匹配种子条目时露出 | MVP（用户在 Lite「Agent 定制草稿」或 A9 选定目标与证据会话后触发） |
| 子代理 AI-06.5 | `agents/reviewer@1` | `name`、`description ≤ 200 字`、`tools[]`（闭集，只读为默认）、`body` 四段（职责 / 输入 / 输出格式 / 禁止项，各 ≤ 120 字） | frontmatter、`model` 槽位、落点 | `~/.claude/agents/<name>.md`；其他 Agent 不可映射则列出 | 只读工具集；`body` 不含路径与密钥 | v1 |
| slash command AI-06.6 | `commands/checklist@1` | `name`、`description ≤ 100 字`、`body ≤ 300 字`（可含 `$ARGUMENTS`）、`argument_hint ≤ 40 字` | frontmatter、落点 | `~/.claude/commands/<name>.md`；Codex / pi 作为 prompt 文件（落点待验证 AV12） | 与内置命令同名则拒绝 | v1 |
| 工作流教程 AI-06.6' | `workflow/tutorial@1` | `steps[] ≤ 6` 每条 `{title ≤ 20 字, text ≤ 120 字, command?}`，`command` 只能从模板给的命令清单里选 | 不写文件（A7-14 教程 Tab） | 无 | 命令必须在白名单 | v1 |
| 修改已有 AI-06.8（`generate.revise`） | `revise/edit-ops@1` | 只允许编辑操作 `ops[] ≤ 12`，每项 `{op: "keep\|replace\|move\|delete", anchor_hash, new_text ≤ 60 字, target?: ".claude/rules/<topic>.md"}` | 由 L0 渲染器按 `anchor_hash` 应用并生成 diff；拆分目标按主题落 `.claude/rules/<topic>.md` 并带 `paths` | IN 动作 `replace_block / move_block`（写前备份、可撤销；`recommendation.md` §2.1 / §8.2 新增） | `anchor_hash` 必须在输入里；`delete` 项必须附「重复 / 已由 hook 强制 / 长期未触发」证据之一；去重后行数 ≤ 目标；用户手写段落只允许 `move`，不允许 `replace` | v1（MVP：RC-12 对 > 200 行的规则文件按二级标题做确定性拆分，不调模型） |

**生成提示的结构**（四段，参照 Hermes 复盘提示：触发信号 → 动作优先级 → 教训写法 → 禁止项，`docs/research/landscape.md` §2.5）：① 用户在 N 个会话里反复出现的模式（≤ 5 条脱敏片段 + 计数，来源见 §2.5「入口 → 证据包」）；② 已有规则的相关段落（避免重复、避免冲突）；③ 槽位说明与示例；④ 禁止项（不写数字收益、不写路径、不写脚本、不改变模板结构）。静态部分（①以外）在前，证据在后。

**与专家 skills / plugins 组合（AI-06.7）**：RC-02 ② / RC-09 匹配到种子条目时，候选分两部分——条目本身走 IN-08（下载、校验哈希与许可，不生成），生成器只产粘合规则（v1 再加粘合 hook）。lethal trifecta 检查（R6）：条目若同时具备读私有数据、读不可信内容、对外通信三项能力，预览顶部明确警告（IN-05）。

**缓存**：`(candidate_id 或 goal_hash, evidence_hash, template_id@version, prompt_version)`；同一证据不重复生成。**降级**：槽位取模板默认值（如 hook `threshold = 2`、规则句为模板示例）并标「未个性化」，或不生成只给教程。

### 4.4 三道自检（AI-07）与预览确认

| 道 | 做什么 | 实现 | 不通过时 | 阶段 |
| --- | --- | --- | --- | --- |
| ① 规范校验 AI-07.1 | 槽位 JSON Schema；渲染后的文件按类型 lint（frontmatter、长度、JSON 合法、名称冲突、与已有规则重复 / 冲突） | L0；复用 `evaluate_text()` 的 `inflated_language / unverified_certainty` 检查文案槽位 | 重试一次（把 lint 错误附回提示）；再失败用模板默认值 | MVP |
| ② 静态安全扫描 AI-07.2 | 非脚本槽位里的 shell 元字符、URL / 主机名、凭据路径（`~/.ssh`、`.env`、`auth.json`）、`rm -rf`、`--force`、`curl … \| sh`、权限扩大标记；脚本体哈希必须等于模板哈希 | L0；规则表随 IN-05 维护 | 直接不展示该生成物，记 `risk_scan.blocked` | MVP |
| ③ 历史回放 dry-run AI-07.3 | Hook（全部六个模板）：把历史 `tool_call` 行还原成 hook 的 stdin JSON，逐条跑生成的 hook（沙箱、无副作用），统计证据会话上的触发召回与「正常会话」上的误拦（`false_block` 必须 = 0）；`stop-verify` 用会话末尾的编辑 / 验证序列回放；白名单：历史命令过前缀，交集破坏性清单 = 0；规则：只做 lint；SKILL.md：description 触发评测（v1，EV-06） | L0 | 误拦 > 0 不展示；召回 = 0 标「未在历史上触发」 | MVP |
| ④ judge AI-07.4 | `judge.artifact_review`：`{issues:[{kind: "vague\|unverifiable\|conflicts_existing\|too_long\|unsafe\|off_evidence\|other", ref, note ≤ 60 字}]}`；`judge.rule_counterfactual`：对 ≤ 5 条正例片段 + 5 条共享关键词的近似反例判 `avoidable`，正例命中 ≥ 3 且反例命中 ≤ 1 才算通过 | L2 judge 槽位（≠ 生成模型），成对交换顺序 | `unsafe` 阻断；其余作为预览里的警告 | v1（EV-04 校准前 `ai_task.calibrated = false`） |

通过后进入 IN-02 预览：键级 diff、每行来源标记（`+ / ✦ / −`）、每个 `✦` 槽位悬停显示它依据的证据片段与 `event_uid`、常驻 / 触发成本、风险标注、自检结果（A9-15 改成真实结果：lint 问题数、安全命中数、回放「会话名 · 通过 / 失败 · 原因」三行；judge issues 行 v1）。确认写入绑定 `preview_digest`（IN-03）；写入后登记 `tracking`（RC-13）。生成物进 `install_plan.ai_filled_slots` 与 `risk_scan`（契约 §3.4 已预留列）。

### 4.5 高层次 workflow 改造（AI-10）

**MVP 单次调用版**（用户点「深度诊断」触发，输入 ≤ 12K，代码先压缩）：`problems[]` 全部（`problem_id / type / key / sessions / weekly_count / weekly_cost_minutes`）、main `workflow().transitions` 前 15 条边（`from / to / count / probability`；`analytics/respond/sequence.py`）、AN-04 轮次级变体前 5（有则给，`activities / support_sessions / correction_rate`）、任务数 / 验证率 / `autonomy_steps` 中位、`inventory[]`、已装建议的 `rec_outcome`。v1 扩到 ≤ 20K：加 DFG 的 `median_dt_ms / wait_side`、`declare_check` 违反项、facet 聚合（`task_type × outcome`）。

**输出**：

```json
{"findings": [{"step": "<AN-04 活动词表里的活动名>",
  "why": "≤ 80 字；必须引用 problem_id 或指标名",
  "change": "≤ 80 字",
  "mechanism": "rule|prompt|skill|hook|permission_rule|mcp|plugin|subagent|model|workflow|removal|builtin",
  "verify": {"metric": "<analysis.md §2.13 追踪指标注册表里的名字>", "direction": "down|up", "window_days": 7},
  "evidence_session_uids": ["…"]}],
 "caveats": ["≤ 40 字"]}
```

gate：`step` 必须在活动词表；`metric` 必须在追踪指标注册表；`evidence_session_uids` 必须存在；`findings ≤ 5`；`why` 里的数字过白名单。**MVP** 只在 A7-03 展示 findings 列表（改哪一步 / 为什么 / 怎么改 / 怎么验证），每条带「交给生成工坊」（`mechanism ∈ rule/hook/skill` 时以 finding 为 `goal_source = ask` 进 AI-06）。**v1**：每条 finding 写成 `candidate(kind = finding.mechanism 经 RC-06 校正后的 kind, match_basis = ai_diagnosis, generic = 0)`，仍过 RC-03 全部闸门，卡片标「AI 诊断 · 未测」；只有 `mechanism = workflow` 才落到 RC-16 教程。`match_basis = ai_diagnosis` 与 RC 的 `inventory_fact` 一起进契约第 3 版（§14）。

不做结果缓存；`job_id` 与输入哈希入 `ai_usage`，24 小时内同一输入哈希直接复用上次 `job_id` 的结果（与 `recommendation.md` §6.3 统一）。**降级**：无（按钮灰显并说明需要开启 AI）。**评测**：EV-05 时间切分回放（v1）——`verify.metric` 在后窗是否按 `direction` 变化；EV-10 标签。

### 4.6 问本地 Agent（AI-09，v1）

「问本地 Agent」不是接一个 agent 自由问答：问题先被分类成结构化查询，由代码执行只读 API，再由模型写一次回答；没有多轮自主调用，没有 MCP 工具暴露给本机 Agent（原 L4 `ask.query` 删除，L4 只留给 v2 的 `eval.plugin_eval`）。

| 步 | 做法 | 预算 |
| --- | --- | --- |
| 1 `ask.plan`（L2） | 问题 + 当前页面上下文 → `{intents: [≤ 2 个，枚举: compare_previous \| top_action \| explain_metric \| persona_why \| persona_tradeoff \| blind_spot \| rank_recs \| pair_recs \| session_stuck \| session_opening \| write_rule \| tool_worst \| approvals \| mcp_unused \| project_habits \| phrases \| catalog_fit \| other], queries: [≤ 3 个，每个 {api: "metrics\|sessions\|problems\|candidates\|evidence\|search\|projects\|text\|catalog", params: {…按 schema…}}]}`；`params` 有 JSON Schema（`Scope`、`metric[]`、`session_uid`、`q ≤ 80 字`），越界即丢弃该查询 | ≤ 2K |
| 2 代码执行（L0） | 逐个执行只读查询（只读 `analysis.db` / `orbit.db`），按 §2.5 组包 ≤ 12K；`views` 覆盖 `metrics / problems / profile / candidates / session_detail / tools / inventory / projects / text（phrases_top / clusters / friction_type_mix）/ catalog`，补齐 ASK-01 指出的 A5、A6、A8 无专属上下文；`tool_worst / approvals / mcp_unused` 意图直接以 §4.7 的可自动化操作清单作 view，`refs = candidate_id` | 0 |
| 3 `ask.answer`（L3） | 输出 `{answer ≤ 300 字, refs: [{kind: "session\|event\|problem\|candidate\|metric", id}], next: "studio\|recs\|sessions\|tools\|none"}`；`refs` 逐个校验存在；`next = studio` 时 ASK-07「交给生成工坊」把 `answer` 作为 AI-06 的 goal（`goal_source = ask`，证据 = `refs` 解析到的片段） | ≤ 12K |
| 超出范围 | `intents = [other]` 或查询全部越界：回答固定句「这个问题现在还不能处理」并给可跳转的页面（按关键词映射到 A1–A9） | 0 |

**预置问题与开场建议（L0，MVP 就有）**：ASK-02 的预置问题由代码从 `change_flags`（AN-12）、`problems_top`、`installed_unused` 生成（如「为什么本周纠偏率上升？」只在 `change_flags` 含该项时出现），不调模型；POP-11 空闲态「开场建议」= 最近项目 top-1 活跃 `problem` 对应候选的 RC-15 `trial` 句。MVP 的 ASK 浮层只提供预置问题的模板回答（Demo `askAnswer` 的套模板逻辑即 L0 版，保留为 v1 的降级），自由提问灰显并注明 v1。回答进界面前过 `evaluate_text(scene=status_update)`；引用可点击跳到 A3（Docent 式精确到事件的引用，[docent](https://github.com/TransluceAI/docent)）。

### 4.7 可自动化操作清单（A4-03，L0，MVP）

A4-03「找出可自动化的操作」是分析到推荐最直接的入口，MVP 不调模型：

| 来源（AN） | 条目 | 对应 RC 候选 | 展示 |
| --- | --- | --- | --- |
| AN-04 `three_step_chains`（support ≥ 3 会话） | 重复命令序列 | RC-06 #4 `skill`（第 3 次）或 #9 `plugin`；无种子条目时露出「交给生成工坊」（AI-06.4） | 序列 + 会话数 + 候选卡入口 |
| AN-05 `would_prompt` | 反复弹审批的只读命令族 | RC-06 #13 `permission_rule` / `builtin` | 命令族 + 次数 / 周 |
| AN-05 `retry_loop` | 同参数重试段 | RC-06 #2 `hook`（`hooks/retry-breaker@2`） | 命令头 + 段数 |
| AN-11 `installed_unused` | 闲置 MCP / skill / 子代理 | RC-07 `removal` | 条目 + 天数 + 常驻 token |

接口：`GET /v1/recommendations?surface=tools&kind=hook,skill,permission_rule,removal,builtin`（`recommendation.md` §9 新增 `surface / kind` 参数），返回的是已过 RC-03 闸门的候选，`refs = candidate_id`；AI 只在 v1 以 AI-12 `explain` 加一句说明。

## 5. 内置 workflow：分级漏斗、缓存、打包与预算

### 5.1 分级漏斗

```mermaid
flowchart LR
  IMP[导入完成] --> L0A[L0 指标 · 分段 · 候选信号 · 问题升级<br/>analytics + feedback + bottlenecks]
  L0A --> SEL{用户开启语义分析?}
  SEL -- 开始语义分析 / 仅新会话 --> PACK[L0 打包: 截断 · 脱敏 · 占位 · 5–10 会话/次<br/>先抽有候选或问题证据的会话]
  PACK --> FAC[L2 facet.session 串行]
  FAC --> GATE1[gate: schema · 枚举 · event_uid 存在]
  GATE1 -- ok --> DB[(session_facet · signal type_source=facet)]
  GATE1 -- fail --> RETRY[重试 1 次 → failed, 只用 L0]
  DB --> AGG[L0 聚合: problems_top · 每类 ≤3 条摘要 · metrics_hash]
  AGG -- metrics_hash 变化 --> NAR[L3 narrate.overview]
  NAR --> GATE2[gate: 引用 · 数字白名单 · evaluate_text]
  GATE2 -- ok --> UI[A1 / A3 / A6]
  GATE2 -- fail --> TPL[narrative.explain 模板]
  DB --> RC[RC-02…05 候选与排序 L0]
  RC -- 用户点生成 --> EVD[L0 入口 → 证据包 §2.5]
  EVD --> GEN[L3 generate.rule / hook / skill 填槽]
  GEN --> CHK[三道自检: lint · 安全扫描 · 回放]
  CHK -- 全过 --> PREV[IN-02 预览 → 确认 → ledger]
  CHK -- 失败 --> DEF[模板默认值 / 不展示]
  RC -- 用户点深度诊断 --> DIAG[L3 diagnose.workflow 单次] --> SHOW[A7-03 findings 只展示]
```

每一层只能用上一层的产物，不回头读原文；只有 `raw_snippets` 例外且需逐条确认。无 AI 时漏斗在 `SEL` 处直接走 `TPL / RC` 分支，页面全部可用。v1 的虚线分支（AI-04.1、AI-12、AI-09、后台调度）不画进 MVP 图。

### 5.2 增量、缓存、打包与稳定前缀

| 机制 | 规则（MVP） | v1 | 为什么 |
| --- | --- | --- | --- |
| 用户触发、串行 | facet 首次回填：用户点「开始语义分析（预计 N 次 · X token）」后串行跑完分析窗口（默认 90 天）内最近 ≤ 200 个合格会话；之后开关「仅新会话自动分析」（默认关）在导入后只处理新会话，一次一个子进程 | 空闲判定、每轮 ≤ 50 个、额度 < 25% 跳过、租约与退避、并发 ≤ 3（§2.4） | R8 不抢额度；MVP 只有 4–5 个任务，不需要调度器 |
| 只处理新会话 | 工作集 = `session_facet` 中无记录或 `stale` 的合格会话；运行中的不抽 | 同左 | R4「不送」 |
| 回填顺序 | 先抽有 L0 候选（AN-05）或是活跃 `problem` 证据的会话，其余按分层抽样补足 `task_type` 分布所需样本；更早区间在用户查看该会话时按需补 | 同左 | R9；A6 的摩擦细分先有数据 |
| 精确缓存键 | 内容哈希 + `prompt_version` + `schema_version`（§2.3）；`model_id` 只记录；不做语义缓存 | 同左 | 命中可复现；换模型不作废旧结果 |
| 失效范围 | 换模型 / 引擎：旧结果有效，只对新会话用新模型，全量重抽需确认并先看估算；改脱敏规则：只重抽脱敏命中集合有变化的会话；`prompt_version` 升版：只重算窗口内 | 同左 | 避免整库重抽（§5.4 有数） |
| 多会话打包 | facet 5–10 会话 / 次（默认 8，按 token 上限 50K 动态缩减）；每项带 `ref_id`，响应按 `ref_id` 对齐 | 分类 20 条 / 次；适配 ≤ 10 条 / 次 | Claude headless 固定开销 0.7–1.5K / 次，打包把它摊到 < 5% |
| 长会话压缩 | L0 压缩：保首 3 条与末 3 条真人消息全文（≤ 500 字）、所有候选片段、中段每条真人消息只留首 80 字、工具序列同类合并；单会话硬上限 6K，超出记 `chunked: true` | `facet.chunk_summary`（> 30,000 字符按 25,000 字符分块，首尾块原文 + 中段 6 项摘要） | 先零成本压缩，再花钱摘要（Hermes 压缩顺序，`docs/research/landscape.md` §3.3 I4） |
| map-reduce | 叙述：map 由代码完成（按问题挑摘要），只有 reduce 调模型 | 周报三节各一次 + At a Glance 一次 | `/insights` 的分层结构，但 map 不花 token |
| 稳定前缀 | 每个任务一个静态提示文件（角色、枚举表、schema、2 个示例）放最前；会话数据在后；同批同模型同引擎 | API Key 通道在静态前缀末尾放 `cache_control`；Haiku 4.5 最小可缓存前缀 4,096 token，facet 静态前缀约 2.5K 不够，按需补示例到 ≥ 4.1K 或接受不缓存（前缀只占一次调用的 8%）；headless 内部缓存断点能否命中待验证 AV3 | [prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)；R3 |
| 结构化输出 | Claude `--json-schema`、Codex `--output-schema`；所有 schema 的标签字段 `enum + other`，开放文本带 `maxLength` | API `output_config.format`、pi `--mode json` | R5 |
| 预算封顶 | 每次调用 `--max-budget-usd`（cheap 0.1、main 0.5）；用户触发任务只受单次上限 | 每日后台总额 2M token 或 $2；L4 1.0 | AI-11 |
| 失败处理 | 单项重试 1 次 → `failed`；整批失败 → 停止、提示、不自动重试 | 1 / 5 / 30 分钟退避；连续 3 批失败当天停用 | AI-11 |
| 账本 | 每次调用写 `ai_usage(job_id, task_id, model_id, engine, usage{input, cache_read, cache_write, output}, cost_usd, ts)`（EV-11）；设置页按任务 / 按天汇总；订阅通道 `cost_usd = null`，只显示 token | 同左 | 用户能看到 AI 花了多少 |

### 5.3 结构化输出与代码 gate（R2 的实现清单）

| gate | 适用 | 失败处理 |
| --- | --- | --- |
| JSON 可解析（CLI 返回的 `structured_output` 字段或 `-o` 文件） | 全部 | 重试 1 次 |
| JSON Schema（`additionalProperties: false`，枚举闭集，`maxLength`） | 全部 | 重试 1 次，把校验错误附回提示 |
| 引用存在：`event_uid / session_uid / signal_id / problem_id / candidate_id / catalog_item_id / rule_anchor_hash` 逐个查表或查输入 | facet、分类、叙述、适配、生成、诊断、问答 | 丢弃该项（叙述整段丢弃） |
| 数字白名单：文本中的数字 ⊆ 输入数值集合（含 1 位四舍五入与百分比形式） | 叙述、人格文案、适配解释、诊断 `why`、生成的文案槽位 | 丢弃该 finding / 槽位取默认 |
| 来源约束：`friction_types ⊆ candidates 出现过的类型`、`command_heads / file_glob / command ⊆ 证据里出现过的值`、`uses_catalog_items = 输入条目`、`revise.ops[].anchor_hash ∈ 输入段落` | facet、hook 生成、粘合生成、修改已有 | 丢弃越界值 |
| 查询 schema：`ask.plan` 的 `queries[].api` 在只读 API 闭集内、`params` 过 schema | 问答 | 丢弃该查询；全部越界则走「不能处理」 |
| 脱敏占位符不得被改写或还原；输出中出现 `<redacted:` 以外的密钥模式即丢弃 | 全部 | 丢弃该项并记 `privacy_violation` |
| `evaluate_text(text, scene)` 无 `error` | 所有进界面的文本 | 退回模板 |
| lint / 安全扫描 / 回放（§4.4） | 生成物 | 模板默认值或不展示 |

### 5.4 token 预算估算表

假设：中文 1 字 ≈ 1 token（待验证 AV4）；facet 每会话输入平均 3.5K（2–6K）、输出 0.25K；8 会话打包，静态前缀 2.5K，Claude headless 固定开销 1.5K（含 `--json-schema` 第二轮）；**合格会话占原始会话约 45%**（`≥ 2` 真人消息且 `≥ 60 s`，`/insights` 本机数据 53 / 119，[research.md](../../research/landscape.md) 所汇总的调研笔记 §3.1），即 1,000 个合格会话 ≈ 2,200 个原始会话。价目取 [pricing](https://platform.claude.com/docs/en/about-claude/pricing)（2026-09 快照）：Haiku 4.5 $1 / $5，Sonnet 5.5 $2 / $10，Opus 5.5 $4 / $20 每 MTok；订阅通道没有美元成本，token 计入 5 小时 / 周额度。

**首次回填（用户触发，不受任何日总额限制）**

| 项 | 调用数 | 输入 token | 输出 token | cheap（Haiku 4.5） | main（Sonnet 5.5） | 耗时（串行，待验证 AV13） |
| --- | --- | --- | --- | --- | --- | --- |
| **MVP 默认：facet，分析窗口内 ≤ 200 个合格会话（≈ 440 个原始会话）** | 25 | ≈ 0.8M | ≈ 0.05M | **≈ $1.1** | ≈ $2.1 | 4–8 分钟 |
| facet，1,000 个合格会话（≈ 2,200 原始；用户显式扩大窗口时） | 125 | 4.0M | 0.25M | ≈ $5.3 | ≈ $10.5 | 20–40 分钟 |
| narrate.overview（首次） | 1 | 8K | 0.6K | — | ≈ $0.02 | — |
| **MVP 合计（200 会话）** | ≈ 26 | **≈ 0.8M** | ≈ 0.05M | **≈ $1.1** | ≈ $2.1 | ≈ 5–10 分钟 |
| v1 加 `facet.chunk_summary`（约 3–5% 长会话 × 2 块 × 25K） | +12–20（200 会话） | +0.3–0.5M | +0.02M | +$0.3–0.5 | +$0.6–1 | AV8 验证后再定是否默认开 |
| v1 加 classify.feedback（约 200 条歧义候选）、cluster.*names、rerank.fit | ≈ 13 | ≈ 0.15M | ≈ 0.015M | ≈ $0.2 | ≈ $0.35 | — |

与 `docs/research/landscape.md` RS-19 的估算（每会话 $0.006–0.016）同量级；Codex 通道做 facet 每次固定开销 0.9–1.5 万，200 会话仅固定开销就 ≥ 0.23M，所以 Codex 只做 L3。

**特殊情形**

| 情形 | token | 说明 |
| --- | --- | --- |
| 换模型 / 换引擎 | 0 | 旧 facet 继续有效并显示其 `model_id`；只有用户确认「全量重抽」才按上表重算 |
| 改一条脱敏规则 | ≤ 10% 的会话重抽（200 会话 ≈ 3 次调用、≈ 0.08M；1,000 会话 ≈ 13 次、≈ 0.4M） | 只重抽脱敏命中集合有变化的会话；按 `redaction_hits_hash` 判定 |
| `prompt_version` 升版 | 窗口内会话全量（= 首次回填一行） | 懒重算；更早的标「旧版 facet」 |

**每周增量（MVP：「仅新会话」开关打开时）**

| 项 | 频次 / 周 | 输入 token / 周 | 说明 |
| --- | --- | --- | --- |
| facet（每天 10–20 个新合格会话） | 10–20 次 | 0.45–0.7M | 占大头；重度用户（50 个 / 天）≈ 1.4M |
| narrate.overview（数字变化时） | ≤ 7 次 | ≤ 60K | 缓存命中则 0 |
| generate.* / diagnose.workflow（按需） | 按点击 | 见下表 | — |
| **合计** | ≈ 15–30 次 | **≈ 0.5–0.8M 输入 + ≈ 0.05M 输出** | **≈ $0.7–1.4（cheap，含输出）**；main 做 facet 时 ≈ $1.5–3 |

**按需（用户触发）**

| 项 | 每次 token | 每次成本（main = Sonnet 5.5；judge = Haiku 4.5，v1） | 备注 |
| --- | --- | --- | --- |
| generate.rule / hook / skill（MVP） | 12K 入 + 1.5K 出 | ≈ $0.04（main 为 Opus 5.5 时 ≈ $0.08） | v1 加 judge 两次 2 × 8K ≈ +$0.02；RS-21 估 $0.05–0.5 |
| generate.revise（v1） | 12K + 1K | ≈ $0.035 | — |
| diagnose.workflow（MVP 单次） | 12K + 1.5K | ≈ $0.04 | v1 ≤ 20K ≈ $0.06 |
| narrate.session_review（v1） | 10K + 1K | ≈ $0.03 | — |
| narrate.weekly（v1） | 4 次共 30K + 3K | ≈ $0.1 | 每周一次 |
| ask.plan + ask.answer（v1） | 2K + 12K + 0.5K | ≈ $0.03 | 不再有 L4 追加 |
| eval.plugin_eval（v2） | 每臂 3 次 × 完整 Agent 调用 | 单条推荐数十次调用 | 用户同意后才跑（RS-26） |

界面显示规则：每次任务执行前显示「预计 N 次调用、约 X K token」（A1-08、A9-11、SET-18）；设置页显示今日 / 本周累计（EV-11）；订阅通道显示 token 与「额度未知 / 剩余 n%」。

## 6. 与现有代码的关系

| main 模块 / 产物 | 在本文中的角色 | 改动 |
| --- | --- | --- |
| `narrative.py::explain() / markdown()` | AI-05 的输出形状与降级；`findings[].evidence_ids` 的校验方式照搬 | 不改；新增 `narrative.from_ai(json)` 适配器把 AI 结果装进同一形状并复用 `markdown()` |
| `analysis_reports.{profile,bottlenecks,process}_markdown` | 周报（AI-05.3）的降级 | 不改 |
| `evaluation.evaluate_text()`（readability-v2，`SCENE_BUDGETS` 六场景） | 所有 AI 文本进界面前的 gate；生成物文案槽位的 lint | MVP 不改（`narrate.overview` 用 `status_update`）；v1 随 `evaluation.md` 的契约建议新增 scene `weekly_report / share_card / menubar` |
| `reader_eval.make_pack() / reader_results()` | 模板版 vs AI 版的盲评（EV-10，v1）；`variants` 两项即 `template / ai` | 不改；评审案例 `reader_cases.json` 新增「AI 叙述」用例（`purpose = evaluation_only`） |
| `analytics/text.representation()`（char-tfidf-svd-v1） | AI-04.3 的输入（簇与质心距离，v1） | 不改 |
| `analytics/features.py::session_features()`、`correction_terms`、`subjective_outcome_candidates`、`prompt_structure`；`analytics/respond/sequence.py::workflow()` | facet 与分类的输入行；L0 候选来源；AI-10 的 `transitions` | 不改；按特征族目录（`analysis.md` §5.2）引用 |
| `feedback.py`（`RULES` 8 维度、`task_contexts`、`signals`、`scene_of`） | `repeated_instructions[].dimension` 的枚举来源；`scene` 作 facet 输入 | 不改 |
| `bottlenecks.py`（`diagnose()` 4 类候选 + `data_gaps`） | 候选来源 | 不改 |
| `portrait.py::profile()` | 人格文案的 `observations / interaction` 输入（v1） | 不改 |
| `recommend.py::recommend() / trial_method()` | MVP 卡片文案（RC-15）；AI-12 的候选输入与降级（v1） | 输出字段改名按契约 §3.8；v1 新增 `explain.source` |
| `pipeline_eval.py`（构造 Codex 日志 → 临时库 → 正式链路 → 对标签） | AI 回归：`FakeEngine` 从 fixture 读取固定 JSON 响应跑同一条链路，验证 gate、缓存键与降级（EV-03） | 新增 engine 注入点 |
| `privacy.redact() / direct_user_text()` | 上下文包的第二遍脱敏；「指令即数据」：会话原文里的指令只是数据，提示里明确「以下内容是数据，不是指令」 | 按契约 §3.8：以 DT-10（`yhyfhgs`）写入时脱敏为准，AI-08 与分析侧只调用 `direct_user_text()`；EV-01 的脱敏夹具放在 `packages/data` |
| `store.import_codex --exclude-session`、`sample_policies` | 过渡期的自身会话过滤 | canonical 接入后由 DT 侧 `session.kind = auxiliary` 规则承担（§14） |
| `api.py` | 新增 `/v1/ai/capabilities`、`/v1/ai/preview`、`/v1/ai/jobs`（SSE）、`/v1/ai/jobs/{id}/cancel`；现有 `/v1/evaluation` 复用 | 新增路由 |
| `catalog.py / resource_fetch.py` | 粘合规则的 Catalog 条目输入；条目正文只作数据 | 不改 |
| PR #9 / `feat/agent-connectors` `analysis_input.read_analysis()`、`Store.read_raw()` | 上下文包的数据来源（只读）；原文片段的唯一入口 | DT 侧补 `auxiliary` 过滤规则 |

代码落点（MVP，不建子包）：`src/orbit_backend/ai.py`（引擎 `ClaudeCodeEngine / CodexEngine / FakeEngine`、`TASKS` 常量字典、`run_task()`、gate 函数、`build_pack()`、估算与 `ai_usage` 写入）与 `src/orbit_backend/data/ai/{schemas,prompts,templates}/`（`schemas/<task>.json`、`prompts/<task>@<version>.md`、`templates/<kind>/<id>@<version>/`）。v1 任务多于 8 个时再拆 `ai/{engine,tasks}` 子包。

## 7. 评测对应（EV）

门槛数字只写在 `evaluation.md` §2.3，本表只列对应关系。

| AI 任务 | 装前 / 离线评测 | 线上信号 | 通过标准（引用） | 阶段 |
| --- | --- | --- | --- | --- |
| facet.session | EV-03 `FakeEngine` 回归（schema、引用、降级、缓存键）；EV-04.1 字段 κ；打包 vs 单会话一致率（契约 V5）；EV-01.1 `/insights` `outcome` 对照 | `other` 占比、`failed` 率、EV-10 `inaccurate` | κ ≥ 0.6 的字段才默认展示；`failed` < 5% | MVP（回归、`failed` 率）；v1（κ） |
| classify.feedback | EV-04 二元 judge TPR / TNR；Rogan–Gladen 校正 | 同上 | κ ≥ 0.6 且 TPR、TNR ≥ 0.8 | v1 |
| cluster.*names | lint 通过率；同名率 | EV-10 标签 | lint 100%；同名率 0；`inaccurate` < 10% | v1 |
| narrate.overview | EV-09 规则检查（`status_update`）；数字白名单与引用存在率 | 「不准确」标签、重新生成次数 | EV-09 无 `error`；幻觉率 = 0 | MVP |
| narrate.persona / session_review / weekly | EV-09（`profile / bottleneck / weekly_report`）；EV-10 读者盲评 | 「不像我」标签率 | 盲评 AI 版不劣于模板版才默认展示 | v1 |
| generate.rule / hook / skill | EV-06：lint 通过率、hook 回放 `false_block = 0`、白名单交集 = 0；`evaluate_text` 文案层 | EV-07 装后三层指标；撤销率 | lint ≥ 95%；`false_block = 0` | MVP |
| generate.* judge、description 触发评测 | EV-04 judge 校准（50–100 条金标、交换顺序）；EV-06 触发评测（8–10 条应触发 + 近似反例） | — | judge κ ≥ 0.6 才启用 | v1 |
| generate.revise | EV-06：应用 ops 后文件可解析、行数 ≤ 目标、`delete` 项证据存在率 100% | 撤销率 | 100% | v1 |
| diagnose.workflow | gate 通过率（`step / metric / evidence`）；EV-05 时间切分（`verify.metric` 后窗方向） | 「交给生成工坊」转化 | 至少一项正向且无反对才写「有效」 | MVP（gate）；v1（回放） |
| rerank.fit | EV-05 曝光 `not_applicable` 按 `fit` 分层；回放 HitRate@3 | — | `unfit` 显著高于 `fits` | v1 |
| ask.* | 引用存在率；查询 schema 通过率；`evaluate_text` | 「交给生成工坊」转化、复制率 | 引用存在率 100% | v1 |
| 全部 | EV-11 账本：预算命中率、每任务平均 token 与估算误差 | — | 估算误差 ≤ 30% | MVP |

评测基线流程（v1 起）：每个节点先用 `main` 档在标注集上建基线分 → 换 `cheap` 档 → 分数不降才默认用 cheap；结果写 `eval_run(suite ∈ facet/judge/artifact/readability/reader)` 与注册表的 `baseline_score`。MVP 只跑 `FakeEngine` 回归与 EV-09。

## 8. 功能清单

ID 沿用契约 §2.5（AI-01…AI-11），细化为 `AI-xx.y`；AI-12 为本文新增（v1）；AI-06.2 废弃（白名单说明句用模板，不是生成任务；ID 不复用）。现状列：`计划` 表示未写代码；括号里是现有代码中可直接复用的输入或降级。负责人 / reviewer 按契约 §6 owner 表（AI-12 按 §14 第 3 条）。

| ID | 名称 | 说明 | 输入 | 输出 | 依赖 | 阶段 | 现状 | 负责人 | reviewer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AI-01 | 调用通道与安全参数 | Claude Code / Codex headless 最小开销配方、`FakeEngine`、能力与登录探测、marker + 专用 cwd + 不落会话；pi / Hermes / API Key v1，Ollama v2 | `ai_request` 信封 | `ai_response` 信封 + `ai_usage` | DT-02、DT-10 | MVP | 计划（过渡过滤：main:src/orbit_backend/store.py `--exclude-session` / `sample_policies`） | MistyHuang03 | yhyfhgs |
| AI-02 | 任务注册表与分级路由 | `TASKS` 常量字典（tier、槽位、预算、schema、`prompt_version`、降级）、模型槽位、代码 gate、重试与降级；YAML 与评测基线列 v1 | `task_id` + 上下文包 | 校验后的 JSON 或降级标记 | AI-01 | MVP | 计划 | MistyHuang03 | yhyfhgs |
| AI-03 | 逐会话 facet（`facet.session`） | 用户触发回填（窗口内 ≤ 200）+「仅新会话」；七项 schema；5–10 会话打包；精确缓存（不含 `model_id`）；回填先抽有候选的会话 | §2.5 `session_rows / tool_sequence / human_messages / assistant_replies / candidates` | `session_facet` v1.1；`signal(type_source=facet)` | AN-02、AN-05、AN-16、AI-01、AI-02、AI-08、AI-11 | MVP（可关闭） | 计划（输入行：main:src/orbit_backend/analytics/features.py `session_features()`） | MistyHuang03 | yhyfhgs |
| AI-03.1 | 长会话分块摘要（`facet.chunk_summary`） | > 30,000 字符的会话按 25,000 字符分块，首尾块原文 + 中段 6 项摘要；facet v1 扩展字段（`satisfaction_signal / sentiment / key_moments(deviation) / violated_rules`）随本项一起 | 脱敏文本块；`existing_rules` 预筛段落 | 6 项结构化摘要；facet v1 字段 | AI-03、AN-07、AN-09 | v1 | 计划 | MistyHuang03 | yhyfhgs |
| AI-04.1 | 反馈语 / 情绪分类（`classify.feedback`） | 关闭 facet 的用户的歧义候选、A6-10「不准确」复判；`feedback_kind / is_correction / friction_type / sentiment / confidence`；三票两胜随本项 | 候选 + 前一条助手摘要 + 任务上下文 | `signal` 字段更新；AN-07 投票输入 | AN-05、AN-17 | v1 | 计划（候选来源：main:src/orbit_backend/analytics/features.py `correction_terms`、bottlenecks.py `diagnose`、feedback.py `signals`） | MistyHuang03 | yhyfhgs |
| AI-04.2 | 失败簇命名（`cluster.failure_names`） | 按 `error_class` 分组的失败输出取可读簇名 | 失败输出首 200 字 × ≤ 30 | `{error_class, name, member_ids}` | AN-04、DT-06 | v1 | 计划 | MistyHuang03 | yhyfhgs |
| AI-04.3 | 主题簇命名（`cluster.topic_names`） | 在 AN-18 的 DBSCAN 簇上命名与归类，纯展示层 | top terms + 代表会话摘要 | `{cluster_id, name, kind, confidence}` | AN-18、AI-03 | v1 | 计划（簇来源：main:src/orbit_backend/analytics/text.py） | MistyHuang03 | yhyfhgs |
| AI-05.1 | 概览叙述（`narrate.overview`） | 「做得好 / 卡在哪 / 立刻可做」三段，结论先行，引用 `problem_id / candidate_id`，数字白名单；scene `status_update` | 汇总统计 + `problems_top` ≤ 5 + Top 3 候选 | 契约 §3.3 叙述形状 | AN-01、AN-06、AN-12、RC-05、AI-03 | MVP | 计划（降级：main:src/orbit_backend/narrative.py `explain()`） | genius-FXC | MistyHuang03 |
| AI-05.2 | 单会话复盘（`narrate.session_review`） | 卡点、开场建议、`lessons[]` 绑定机制，直通 AI-06；scene `bottleneck` | facet + AN-02 行 + 信号 + 关键时刻 | 叙述形状 + `lessons[]` | AI-03、AN-09 | v1 | 计划 | genius-FXC | MistyHuang03 |
| AI-05.3 | 周报叙述（`narrate.weekly`） | 固定窗口快照的三节 + At a Glance；scene `weekly_report`（新增） | `report_snapshot(weekly)` | 叙述形状 + `sections[]` | AN-14、EV-07、EV-09 | v1 | 计划（降级：main:src/orbit_backend/analysis_reports.py） | genius-FXC | MistyHuang03 |
| AI-05.4 | 人格解读文案（`narrate.persona`） | headline、traits（绑定指标）、tradeoffs、blind_spots（绑定 problem）、caveats；scene `profile` | `profile.axes / observations / interaction` + 前 3 类摩擦 | §3.6 schema | AN-08、AN-06 | v1 | 计划（MVP 用 Advance Demo `TYPES` 式类型文案库） | genius-FXC | MistyHuang03 |
| AI-06.1 | 规则片段生成（`generate.rule`） | ≤ 5 条可验证祈使句 + 标记块；重复 / 冲突 lint；入口 → 证据包（§2.5） | 证据片段 + 已有规则段落 + 模板 | 槽位 JSON → `install_plan.targets` | RC-01、RC-06、RC-12、AI-08 | MVP | 计划 | genius-FXC | MistyHuang03 |
| AI-06.2（废弃） | 权限白名单说明 | 白名单前缀来自 DT-13 词表，说明句用模板句；不再是 AI 任务 | — | — | — | — | 并入 RC-12 模板 | — | — |
| AI-06.3 | Hook 生成（`generate.hook`） | 六个 hook 模板（`retry-breaker / verify-before-commit / post-edit-check / stop-verify / compaction-reminder / scope-guard`）的 matcher / 阈值 / 提示语 / 命令头 / 文件 glob；脚本体来自仓库模板，落 `~/Library/Application Support/Orbit/hooks/<template_id>@<version>.sh` | 证据 + 模板 | 槽位 JSON → `settings.json` 片段 + 脚本引用 | RC-01、RC-12、AI-07.3 | MVP | 计划（Demo 示意：Advance Demo `05-data.js` `retry-breaker.file`、`latex-hook`） | genius-FXC | MistyHuang03 |
| AI-06.4 | SKILL.md 生成（`generate.skill`） | `skills/procedure@1`：name / description / steps / dont / verify / allowed_tools；用户在 Lite「Agent 定制草稿」或 A9 选定目标与证据会话后触发；只过自检 ①②；RC 侧检索优先，无匹配种子条目时才露出 | 反复出现的流程证据（A5-11 `workflow_pattern` 或手输目标的 BM25 片段）+ 模板 | SKILL.md | RC-06（流程第 3 次 → skill）、RC-02 ④、AI-08 | MVP | 计划 | genius-FXC | MistyHuang03 |
| AI-06.5 | 子代理定义生成（`generate.subagent`） | 只读默认的评审 / 核查类子代理 | 旁支任务证据 + 模板 | agents/*.md | RC-06 | v1 | 计划 | genius-FXC | MistyHuang03 |
| AI-06.6 | slash command 与工作流教程生成（`generate.command` / `generate.workflow_tutorial`） | 命令正文、参数提示；教程步骤只能用白名单命令 | 证据 + 模板 | commands/*.md；教程 Tab | RC-06、RC-16 | v1 | 计划 | genius-FXC | MistyHuang03 |
| AI-06.7 | 与专家 skills / plugins 组合 | `generate.rule` 的 `glue` 变体：输入多给已匹配种子 skill，只产「遇到 X 时使用 `<skill>`」规则段，校验 `uses_catalog_items`；条目本身走 IN-08；lethal trifecta 警告；粘合 hook v1 | Catalog 条目 + 模式证据 | 粘合规则 + `uses_catalog_items[]` | RC-02 ②、RC-09、IN-08、IN-05 | MVP（最小形态） | 计划（条目获取：main:src/orbit_backend/resource_fetch.py） | genius-FXC | MistyHuang03 |
| AI-06.8 | 修改已有文件（`generate.revise`） | 以 `existing_rules` 段落为输入，输出 `keep / replace / move / delete` 编辑操作（带 `anchor_hash`），L0 应用并生成 diff；删除项必须有证据；MVP 由 RC-12 做确定性拆分 | 目标段落 + 证据 + 约束 | 编辑操作列表 → `replace_block / move_block` | RC-06 #4 / #12、RC-07、RC-12、AI-08 | v1 | 计划 | genius-FXC | MistyHuang03 |
| AI-07.1 | 规范校验 lint | 槽位 schema、文件 lint、名称冲突、与已有规则重复 / 冲突 | 生成物 + 已装清单 + 已有规则 | 通过 / 问题清单 | DT-09、AI-06 | MVP | 计划（文案部分：main:src/orbit_backend/evaluation.py） | MistyHuang03 | yhyfhgs |
| AI-07.2 | 静态安全扫描 | 元字符、URL、凭据路径、破坏性命令、脚本哈希、权限扩大 | 生成物 | 通过 / 阻断 | IN-05 | MVP | 计划 | MistyHuang03 | yhyfhgs |
| AI-07.3 | 历史回放 dry-run | 六个 hook 模板的 stdin 回放、白名单回放、`false_block = 0` | 生成物 + 历史 `tool_call` | 召回 / 误拦计数 | DT-06、AI-06.3 | MVP | 计划 | MistyHuang03 | yhyfhgs |
| AI-07.4 | LLM-as-judge（`judge.artifact_review` / `judge.rule_counterfactual`） | 与生成模型不同的 judge、交换顺序、issues 闭集、近似反例 | 生成物 + lint 报告 / 规则 + 片段 | issues / avoidable | EV-04 | v1 | 计划 | MistyHuang03 | yhyfhgs |
| AI-08 | 上下文包构建与预览 | 只读组包、第二遍脱敏（`direct_user_text`）、逐项 token、「入口 → 证据包」表、原文片段逐条确认、`preview_digest`（生成类） | `analysis.db` + `orbit.db`（只读） | 包 + 估算 | DT-10、AN-16 | MVP | 计划（脱敏：main:src/orbit_backend/privacy.py；原文：PR#9 `Store.read_raw`） | genius-FXC | MistyHuang03 |
| AI-09 | 问本地 Agent | `ask.plan`（≤ 3 个结构化只读查询）→ 代码执行 → `ask.answer`；超范围回答不能处理并给跳转；预置问题与 POP-11 开场建议由 L0 生成（MVP） | 问题 + 页面上下文 | `{answer, refs[], next}` | AI-08、AI-02、AN-12 | v1（L0 预置问题 MVP） | 计划（预置问题模板回答：Advance Demo `53-ask.js` 逻辑即 L0 版） | genius-FXC | MistyHuang03 |
| AI-10 | 高层次 workflow 诊断（`diagnose.workflow`） | MVP 单次调用（≤ 12K：problems + `transitions` 前 15 + 变体前 5 + 任务数 / 验证率 + 已装清单）→ findings 只展示；v1 经 RC-06 映射为 `candidate(match_basis = ai_diagnosis)` | AN-04 产物 + `problems` + `inventory` | findings（MVP）→ 候选（v1） | AN-04、AN-06、DT-09、RC-06 | MVP（单次、只展示）；v1（映射候选） | 计划（`transitions`：main:src/orbit_backend/analytics/respond/sequence.py `workflow()`） | genius-FXC | MistyHuang03 |
| AI-11 | 预算、封顶与不污染数据 | 调用前估算、每次 `--max-budget-usd`、只处理新会话、首次回填 ≤ 200、串行与取消、marker + cwd；空闲 / 电量 / 额度阈值、租约、退避、并发 v1 | 注册表 + 会话工作集 | `ai_job` 行、估算 | AI-01、DT-17（v1） | MVP | 计划 | MistyHuang03 | yhyfhgs |
| AI-12 | 候选适配判断与个性化解释（`rerank.fit`） | `fit / reasons / explain / pair_with`；不改 priority，`unfit` 降到末尾 | 画像 + 问题 + 已装清单 + ≤ 10 候选 | `candidate.explain(source=ai)`、排序微调 | RC-02…RC-05、RC-15、AI-03 | v1 | 计划（MVP 文案：main:src/orbit_backend/recommend.py `trial_method`、narrative.py） | MistyHuang03 | genius-FXC |
| EV-11 | 自身 token 账本 | 每次调用的用量、费用、引擎、任务；设置页汇总；估算误差 ≤ 30% | `ai_response.usage` | `ai_usage` 表 | AI-01 | MVP | 计划 | MistyHuang03 | yhyfhgs |

## 9. 功能卡：本模块负责的第 4 段「AI 介入点」

三张端到端功能卡（只读放行、重复失败熔断、高频纠偏 → 规则）按契约 §4.1 九段模板只在 `docs/archive/plans/feature-map.md` 写一份；本文只给每张卡的第 4 段。

| 卡 | AI 介入点（第 4 段） | 无 AI 时 | token |
| --- | --- | --- | --- |
| 只读命令自动放行（契约 §4.2） | 无必需的模型调用：前缀清单来自 DT-13 词表，说明句为模板句；可选 `narrate.overview` 在概览提到它时只能引用 `problem_id` 与计数 | 完全相同 | 0 |
| 重复失败 → 熔断 hook（`hooks/retry-breaker@2`） | `generate.hook`（L3，≤ 10K）只填 `threshold ∈ [2,5]`、`message ≤ 120 字`、`command_heads ⊆ 证据命令头`；脚本体 = 仓库模板（哈希固定），写 `~/Library/Application Support/Orbit/hooks/retry-breaker@2.sh`；AI-07.1 lint → AI-07.2 扫描 → AI-07.3 回放（历史 `tool_call` 还原 stdin JSON，`false_block = 0`）；缓存键 `(candidate_id, evidence_hash, hooks/retry-breaker@2, prompt_version)` | `threshold = 2`、默认提示语，标「未个性化」 | 1 次 L3 ≈ 10K + 1K |
| 高频纠偏 → 规则片段（A6-03、A6-10、A3-18；Lite「优化建议 › 规则」） | 证据包按 §2.5「入口 → 证据包」：`phrases_top[]`（AN-17）前 4 条的 `evidence` + `problem_id`；`generate.rule`（L3，≤ 12K：≤ 5 条原话 + `existing_rules` + 模板）→ AI-07.1 lint（重复 / 冲突 / 长度）→ AI-07.2 扫描；`judge.rule_counterfactual` v1；证据入口跳 A3 时携带 `problem.evidence_session_uids`（作为 `root_session_uids`），不改用户已有筛选 | 模板默认句「我说『<原话>』时，请<维度动作>」 | 1 次 L3 ≈ 12K + 1K |

## 10. MVP 与迭代

| 阶段 | 交付 | 验收 |
| --- | --- | --- |
| MVP（v0） | AI-01（Claude Code + Codex 通道、`FakeEngine`、能力探测、marker / cwd）、AI-02（常量字典注册表 + gate）、AI-03（facet 七项，用户触发、≤ 200 回填、L0 长会话压缩）、AI-05.1、AI-06.1 / 06.3 / 06.4 / 06.7、AI-07.1 / 07.2 / 07.3、AI-08（含入口 → 证据包）、AI-10 单次调用版、AI-11（估算、封顶、只处理新会话）、EV-11；L0 项：ASK-02 预置问题、POP-11 开场建议、A4-03 可自动化清单；界面：Lite「AI 一句话解读」与「Agent 定制草稿 → 用本地 Agent 生成」、A1 AI 解读、A6 摩擦分类（facet）、SET-18 引擎与「开始语义分析」估算 | 三位成员本机：facet `failed` 率 < 5%；打包一致率 ≥ 0.9（契约 V5）；两张功能卡（§9 熔断、规则）从问题到预览全程无模型写文件；EV-09 全部通过；账本误差 ≤ 30%；200 会话回填 ≤ 10 分钟（AV13） |
| v1 | AI-03.1 与 facet 扩展字段、AI-04.1 / 04.2 / 04.3、AI-05.2 / 05.3 / 05.4、AI-06.5 / 06.6 / 06.8、粘合 hook、AI-07.4、AI-09（计划 → 执行 → 回答）、AI-10 → RC-06 映射、AI-12、后台调度（空闲 / 额度 / 租约 / 退避 / 并发）、pi / Hermes 通道、API Key 通道 + Batch、YAML 注册表 | EV-02 标注集 κ ≥ 0.6；EV-04 judge 校准；读者盲评 AI 版不劣于模板版；EV-05 回放 |
| v2 | L1 端侧小模型、Ollama、OpenCode / Kimi / DSH 通道、`eval.plugin_eval`（唯一的 L4 任务）、description 触发评测自动迭代 | 各通道隔离实测；装前对照的额度消耗可接受 |

先最简单可运行的顺序（对齐契约 §6「先最简单、可运行」）：① `FakeEngine` + `TASKS` + facet gate 在 `tests/fixtures/analysis-input-v1.json` 上跑通；② Claude Code 通道实测固定开销与 `--json-schema` 两轮；③ 用三人真实 `orbit.db` 各抽 50 个会话 facet，测打包一致率与 token；④ `narrate.overview` 接 gate 与 `evaluate_text`；⑤ `generate.rule / hook` + 三道自检 + IN-02 预览；⑥ `generate.skill`、`diagnose.workflow` 单次版；⑦ 估算、封顶与设置页。每步交付后再扩。

## 11. 与 Demo 的对应

### 11.1 Advance Demo：由本模块驱动的面板与交互

| Demo 条目（[`feature-map.md`](feature-map.md) §5） | 由哪个 AI feature 驱动 | 真实实现与 Demo 示例逻辑的差距 |
| --- | --- | --- |
| A1-04、A2-04、A3-04、A7-03 四个 AI 按钮 | AI-09（v1）；A3-04 → AI-05.2（v1）；A7-03 → AI-10（MVP 单次版） | Demo 用 `askAnswer` 套模板；MVP 保留模板回答，v1 换 `ask.plan → 执行 → ask.answer`，回答带可点引用 |
| A1-07 一句话画像、A1-08 重新生成 | AI-05.1 + AI-02 作业（`POST /v1/ai/jobs`，SSE 进度，可取消） | Demo 从 3 条预置文案随机选；真实版「重新生成」= 显式失效缓存，显示引擎、`prompt_version`、生成时间、本次 token；`regen` 打字效果保留（前端对返回文本做动画） |
| A1-09 做得好 / A1-10 卡在哪 / A1-11 立刻可做 | AI-05.1 `findings[]` 三段；证据入口携带 `problem.evidence_session_uids`（作为 `root_session_uids` 跳 A3，修 BUG-11 / BUG-27） | Demo 由 `stats.verify / countBy(fric)` 直接算；真实版数字来自 AN，句子来自 AI 或模板，分母 < 5 的指标不入句 |
| A1-16 摩擦率 KPI | AN-05（规则 proxy）+ AI-03 `candidates[]` | Demo「纠偏 ÷ 消息」无置信度；真实版显示 `basis = proxy`、区间与「含 AI 判定 n 条」 |
| A2-07 类型描述、A2-08「AI 撰写」特质、A2-15 盲点 | MVP：类型文案库 + 模板量化旁白；v1：AI-05.4 | Demo 用 ≥ 55 / ≤ 45 阈值与写死文案；v1 每条特质悬停显示指标与数值 |
| A2-09「不像我」 | EV-10 `label(not_me, reason)` → AI-05.4（v1）下次生成时附入 `caveats` | Demo 不存储 |
| A3-13 悬停「情绪分与纠偏」 | AI-03 `candidates[]`（类别 + `confidence`）；情绪 v1 | Demo 每条消息 −1..+1 分；MVP 只有候选消息的类别 |
| A3-17 关键时刻 | AN-09 规则实心标记（MVP）；AI-03 v1 `key_moments(deviation)` 空心标记 | Demo 手写；AI 标记 v1 才出现，紫色虚线 + 置信度，可确认 / 删除 |
| A3-18 这次会话的启示 + 生成规则 / 加 Hook | MVP 启示为规则模板句（AN-02 行 + 信号）；v1 AI-05.2 `lessons[].mechanism` → AI-06.1 / 06.3 | — |
| A4-03 找出可自动化的操作 | §4.7 确定性清单（AN-04 `three_step_chains`、AN-05 `would_prompt / retry_loop`、AN-11 `installed_unused` → RC 候选）；AI 只在 v1 以 AI-12 `explain` 加说明 | Demo 只有一个问答浮层；真实版返回候选列表，`refs = candidate_id` |
| A4 失败原因面板 | AI-04.2（v1） | MVP 只按 `error_class` 分组 |
| A5-03 / A5-11 项目页的定制与工作流入口 | AI-06.1（`goal_source = project`）、AI-06.4（`goal_source = workflow`）；AI-10 v1 映射 | Demo 跳 A9 只预填目标；真实版带证据包（§2.5） |
| A6-03 把高频纠偏写成规则 | AI-06.1（§9 规则卡） | Demo 目标文本写死；真实版目标 = AN-17 `phrases_top[]` 前 4 条 + `problem_id` |
| A6-04「仅统计」降级 | AI-02：引擎 = `none` 时所有 AI 任务返回降级 | Demo 整页只剩提示；真实版 A6 的 L0 部分（簇、坐标、`correction_terms`、短语）照常显示，只有 AI 字段隐藏 |
| A6-05 本地处理声明 | AI-01 / AI-08 | 真实版显示当前引擎与「原文不离开本机，脱敏文本经 <引擎> 发往其服务商」 |
| A6-06 情绪曲线、A6-07 纠偏柱 | AN-07（v1 用 facet `sentiment` 作一个打标函数）、AN-05 | 真实版每日 ≥ 5 条判定才画点，标「实验性」 |
| A6-08 摩擦分类 | AI-03 `friction_types` + 规则信号 | Demo 7 类，契约 10 类 + other；映射表见 `analysis.md` UG-07（本文不再重复） |
| A6-09 语义主题 | AN-18 簇 + AI-04.3 命名（v1） | Demo 固定 7 类；真实簇数不定且有噪声点 |
| A6-10 高频反馈语 | AN-17 `phrases_top[]`（L0）+ AI-03 `candidates[].feedback_kind`；「不准确」→ AI-04.1 复判（v1） | Demo 短语写死、次数按会话算 |
| A7-08 / A7-12 卡片原因与说明 | MVP：RC-15 模板句；v1：AI-12 `explain`（`source = ai`） | Demo 预填收益百分比；真实版收益只用 `score.weekly_saving`，效果写「未测」 |
| A7-11「交给 Agent 生成」、A7-16「交给 Agent 定制」 | AI-06（`goal_source = candidate`） | 同上 |
| A7-13 预览 Tab 的 `+ / ✦ / −` 标记 | RC-12 渲染器 + AI-06 槽位来源 | Demo 标记写死；真实版 `✦` 行悬停显示依据片段 |
| A9-01 本地执行声明、A9-06 / A9-07 上下文包 | AI-01、AI-08（真实 token 计数、脱敏命中数、`preview_digest`、包项随 `goal_source` 变化） | Demo `CTX` 固定 token 数、不随目标变化 |
| A9-03 工作流模板 | AI-02 生成流程配置（快速草稿 = 跳过回放 / 严格模式 = judge 用另一引擎，v1） | Demo 选择无效（BUG-81） |
| A9-04 产物类型 | AI-06.1 / 06.3 / 06.4 / 06.7 可生成；子代理、命令、教程灰显注明 v1 | — |
| A9-05 手输目标 | AI-08 `goal_source = manual`：`event_fts` BM25 前 5 + `problem.key` 关键词匹配；0 命中标「未个性化」 | Demo 任意文本 |
| A9-08 执行者 | AI-01 能力探测 + 槽位 | Demo 列出 Gemini / DeepSeek / Copilot；MVP 只有 Claude Code、Codex，其余显示「暂不支持 headless」 |
| A9-09 / A9-11 / A9-12 开始、状态、六步 | AI-02 作业（`POST /v1/ai/jobs` → SSE `{stage, progress, tokens}`）；六步 = 组包 → 读 facet 缓存 → 填槽 → lint / 扫描 → 回放 → 预览 | Demo 定时器驱动、耗时写死 |
| A9-13 实时日志、A9-14 流式产物 | 后端一次返回产物 JSON；前端对返回内容做逐行出现动画（沿用 `48-a9-studio.js` 的 `studioStep`），无需 stream-json | 效果保留（本机工作文件 第 4 条） |
| A9-15 自检清单 | AI-07.1–07.3 真实结果；judge 行 v1 | Demo 永远通过 |
| A9-16 / A9-18 安装、存入资源库 | IN-02…04；本地 Catalog 条目（`catalog_item(kind=local)`） | — |
| ASK-01…ASK-07 | AI-09（v1）；ASK-02 预置问题由 L0 从 `change_flags / problems_top / installed_unused` 生成（MVP）；ASK-07 → AI-06 的 goal（`goal_source = ask`） | Demo 预置回答；真实版 A5 / A6 / A8 也有专属 `views` |
| POP-11 空闲态开场建议 | L0：最近项目 top-1 活跃 `problem` 对应候选的 RC-15 `trial` 句 | Demo 固定文案 |
| SET-18 分析引擎与执行者 | AI-01 能力探测、AI-02 槽位、AI-11「开始语义分析（预计 N 次 · X token）」、EV-11 账本 | Demo 只有分段选择 |
| SET-21 每周报告 | AI-05.3（v1）；MVP 为 `analysis_reports` 模板 | — |
| NT-03 生成完成通知 | AI-02 作业完成事件 | — |
| OB-05 首次启动「语义」步骤 | AI 默认关闭：显示「语义分析未开启，可在设置开启（预计 N 次调用）」 | Demo 四步都「完成」 |

### 11.2 Lite Demo（`prototypes/advance/benchmark-review.md`，8 页）

| Lite 页面 | AI 相关元素 | 对应 feature | 差距 |
| --- | --- | --- | --- |
| 概览 | 「AI 一句话解读」、协作 MBTI、本周建议 | AI-05.1；AN-08 四轴（类型文案库）；RC-15 模板句 | 一句话需带来源标签与「重新生成」；MBTI 来自 AN-08 真实四轴 |
| 协作画像 | 趣味标签、四维得分与计算信号 | MVP 类型文案库；v1 AI-05.4 `traits` | 标签不再按阈值写死 |
| 会话与轨迹 | 任务节点与建议、启示 | AN-09 规则时刻；AI-05.2（v1） | MVP 启示为模板句 |
| 工具调用 | 失败原因 | AI-04.2（v1） | MVP 按 `error_class` |
| 情绪与语义 | 高频反馈语、语义兴趣、纠偏 / 摩擦类型 | AN-17 `phrases_top`、AN-18（命名 v1）、AI-03 `friction_types` | 同 Advance |
| 优化建议 | 适配 Agent 与预期效果、Agent 定制草稿、模拟安装 | RC-15 模板句（v1 AI-12 `fit`）；AI-06.1 / 06.3 / 06.4「用本地 Agent 生成」+ IN-02 预览 | 「预期效果」改「未测」；定制草稿从「复制」升级为真实生成 + 三道自检 |
| 资源库 | 为你推荐 / 同人格 / 热门 | RC-09（v1 加 AI-12 `fit`） | 「同人格正在用」无数据通路，删或标示例 |

Lite 没有生成工坊、问本地 Agent 与引擎设置页：MVP 的 Lite 模式消费 facet / 叙述 / 模板解释，生成走「Agent 定制草稿 → 用本地 Agent 生成 → 预览」，引擎开关与「开始语义分析」放在一个最小设置面板。

## 12. Demo 还缺什么（AI 模块贡献的条目；合并后的前端升级表在 `docs/archive/plans/feature-map.md`）

去重规则：与其他模块重复的条目只保留一处（本文标「= UG-xx」并不再计数）；只服务 Advance 独有界面的条目一律 P2 / v1。

| ID | 页面 | 改什么 | 为什么 | 依赖后端 feature | 优先级 | 复杂度 |
| --- | --- | --- | --- | --- | --- | --- |
| UG-AI-01 | A1 AI 解读卡（A1-07…A1-11）与 Lite 概览「AI 一句话」 | 每段显示来源标签（模板版 / AI 版 · 引擎 · `prompt_version` · 生成时间 · 本次 token）；「证据」按钮携带 `evidence_session_uids` 跳 A3（与 `analysis.md` UG-02 同一实现）；分母不足时整段显示「数据不足」 | 用户要能分辨哪句是模型写的、能回到证据 | AI-05.1、EV-11、AN-06 | P0 | S |
| UG-AI-02 | 设置 › 分析（SET-18）与 Lite 最小设置面板 | 引擎能力探测结果（已安装 / 版本 / 已登录 / 结构化输出）、模型槽位、「开始语义分析（预计 N 次 · X token）」按钮与进度 n / N、可取消、今日 / 本周账本、「AI 默认关闭」说明 | AI 可关闭、可控成本是产品承诺；Demo 只有三选一分段 | AI-01、AI-02、AI-11、EV-11 | P0 | M |
| UG-AI-03 | Lite 优化建议「Agent 定制草稿」 | 加「用本地 Agent 生成」入口：选目标与证据会话 → 生成（规则 / hook / skill）→ 预览（`+ / ✦` 行、三道自检结果三行）→ 安装；无引擎时保留「复制草稿」 | 用户点名的核心：直接生成 hook 和 skills | AI-06.1 / 06.3 / 06.4、AI-07、AI-08、RC-12、IN-02 | P0 | M |
| UG-AI-04 | A6 情绪与语义、A3 轨迹（A6-06…A6-10、A3-13） | AI 判定统一视觉：紫色标记 + `confidence` 芯片 + 「确认 / 不准确」反馈；摩擦分类 10 类 + other 的映射与 `type_source` 标记 = `analysis.md` UG-07（只保留那一条） | 区分事实 / 规则 / AI 推断；反馈回流评测 | AI-03、EV-10 | P1 | M |
| UG-AI-05 | A7-03 深度诊断 | 结果改为结构化 findings 列表（改哪一步 / 为什么 / 怎么改 / 怎么验证）+ 每条「交给生成工坊」；v1 加「转为建议」 | 诊断是推荐的输入，不是聊天记录 | AI-10 | P1 | M |
| UG-AI-06 | A4-03 找出可自动化的操作 | 浮层改为确定性清单（序列 / 命令族 / 重试段 / 闲置条目 → 候选卡入口） | 分析到推荐最直接的入口 | AN-04、AN-05、AN-11、RC-06、RC-07 | P1 | S |
| UG-AI-07 | 首次启动第 3 步（OB-05）与 A6-04 空状态 | 语义步骤如实显示「未开启」并给「开启并预计成本」入口；A6 仅统计模式保留 L0 部分 | AI 默认关闭时页面不能是空的 | AI-01、AI-11 | P1 | S |
| UG-AI-08 | A9 产物与自检（A9-14、A9-15） | = UG-EV-03（只保留那一条）：`✦` 行悬停证据、自检三行真实结果、失败时标「已退回模板默认」；逐行出现动画保留 | 生成物可信度全靠检查可见 | AI-06、AI-07、RC-12 | P2（A9 为 Advance 独有） | M |
| UG-AI-09 | A9 上下文包（A9-06、A9-07） | 包项随 `goal_source` 变化；逐项 token 堆叠条、脱敏命中高亮、原始片段逐条勾选、`preview_digest` | 逐项预览是隐私边界的落点 | AI-08 | P2 | S |
| UG-AI-10 | ASK 浮层 / POP-11 | ASK-02 预置问题按 `change_flags / problems_top / installed_unused` 生成；A5 / A6 / A8 专属问题；POP-11 开场建议取 RC-15 `trial` 句；回答引用可点击跳 A3 | 不接自由对话也能有「问」的入口 | AI-09（v1）、AN-12、RC-15 | P2 | S |
| UG-AI-11 | A2 自述与特质（A2-07、A2-08、A2-15）、A6-09 簇卡 | 特质悬停显示指标名与数值；自述标「AI 撰写 · 数字来自指标」；簇卡标「AI 命名」+ top terms；无 AI 时「簇 #k」 | 数字白名单与 AI 来源可见化 | AI-05.4、AI-04.3（v1） | P2 | S |

A7-10「不适用」原因枚举与 A7 「AI 适配判断」芯片归 `recommendation.md` UG-RC-06（AI-12 v1 后再加芯片）；A7-15 效果追踪归 UG-RC-04。

## 13. 待验证

编号以契约 §7 为准（第 3 版把下表并入 V16 起的条目；并入前沿用 AV 编号）。阻塞 MVP 的三项是契约 V11（`human_origin` 覆盖）、V4（性能）、V12（`permission_mode`），不在本文范围但 facet 与 hook 回放的输入都依赖它们。

| # | 假设 | 验证方式 | 影响 |
| --- | --- | --- | --- |
| AV1（= 契约 V5） | 5–10 会话打包的 facet 逐字段一致率 ≥ 0.9 | 50 个会话分别单会话与打包调用对比 | 打包是否默认开 |
| AV3 | 订阅通道 headless 连续批量调用时 CLI 内部缓存断点能命中（`usage.cache_read` > 0） | 连续 5 次同前缀调用读 usage | 静态前缀是否值得补足到 4.1K |
| AV4 | 中文 1 字 ≈ 1 token 的估算偏差 ≤ 30% | 用 CLI 返回的 usage 对照 | 预算显示与封顶 |
| AV5 | Codex `--ignore-user-config` 下已信任的 hooks 不再运行 | 配一个写文件的测试 hook | Codex 通道隔离 |
| AV6 | `--safe-mode`、`--json-schema`（两轮）、`--max-budget-usd` 在当前 Claude Code 版本行为稳定；最低支持版本 | `claude --version` 矩阵实测 | 能力探测表 |
| AV7 | `~/.claude.json` 的 `cachedUsageUtilization` 跨版本稳定 | 对照字段结构 | v1 额度阈值 |
| AV8 | 超过 30,000 字符的合格会话占比 ≤ 5%，L0 压缩后 facet 质量不明显下降；回填「先抽有候选的会话」不使 `task_type` 分布失真 | 本机数据统计 + 标注集对比 | AI-03.1 是否默认开；回填顺序 |
| AV9 | facet 各字段在 EV-02 标注集上 κ ≥ 0.6 | 200 会话两人标注（v1） | 哪些字段默认展示 |
| AV10 | 「规则可验证」lint（祈使句 + 条件 / 对象）在中文上的误报率 < 20% | 50 条生成规则人工核 | AI-07.1 |
| AV11 | hook stdin JSON 的字段随 Claude Code 版本变化时回放仍成立；`Stop` 事件能拿到自上次验证后的编辑清单 | 对照 hooks 文档与本机版本 | AI-07.3、`stop-verify@2` |
| AV12 | Codex / pi 的 slash command 与 skills 落点语法 | 查源码与文档（契约 V6） | AI-06.4 / 06.6 |
| AV13 | headless 单次调用 5–15 s；200 会话串行回填 ≤ 10 分钟 | 计时 | 首次回填体验 |
| AV14 | `rerank.fit` 重排提升 HitRate@3 | EV-05 回放（v1） | AI-12 是否重排 |
| AV15 | 手输目标的 `event_fts` BM25 前 5 片段与 `problem.key` 关键词匹配能给出相关证据（人工判相关 ≥ 3 / 5） | 三人各 10 个手输目标 | AI-08 `goal_source = manual` |

AV2（`--safe-mode` 与 MCP 共存）随 L4 `ask.query` 删除而撤销。

## 14. 并入契约第 3 版的条目（AI 侧）

本节只列本文对契约的修改，按本轮评审统一结论写定；已被否决或撤回的不再列（原建议 4「AN-09 AI 时刻进 MVP」撤回：AN-09 保持 MVP 规则 / v1 AI，`deviation` 的来源写为 AI-03 facet `key_moments[]`（v1），`analysis.md` §3.2 同步）。

| # | 条目 | 位置 |
| --- | --- | --- |
| 1 | `session_facet.json` 升 v1.1：MVP 七项 `goal / task_type / outcome / friction_types / candidates[{signal_id, event_uid, is_correction, feedback_kind, friction_type, confidence}] / repeated_instructions / summary` + `chunked`；`scene / interaction_pattern` 改为输入；v1 扩展 `satisfaction_signal / candidates[].sentiment / key_moments[{event_uid, kind ∈ deviation \| other, label}] / violated_rules[{rule_anchor_hash, event_uid, confidence}]`；`key_moment(origin=ai)` 的唯一来源是 AI-03（v1） | §3.3 |
| 2 | `ai_task` 注册表：MVP 为 Python 常量字典，YAML 与 `max_items_per_call / idle_only / requires_user_trigger / eval_suite / baseline_score` 列 v1；新增 `facet.chunk_summary`（v1）、`cluster.topic_names`、`rerank.fit`、`generate.command`、`generate.revise`、`ask.plan / ask.answer`；`classify.candidate` 改名 `classify.feedback` 并加 `feedback_kind`；删除 `generate.allowlist`（白名单不是生成任务）与 `ask.query`（L4 只留 `eval.plugin_eval`）；`diagnose.workflow` 的 tier 改 L3、阶段 MVP（单次、只展示）/ v1（映射候选）；缓存键去掉 `model_id`（只记录） | §3.6、§2.5 |
| 3 | 新增 AI-12「候选适配判断与个性化解释」（v1）；RC-15 的「AI 版（AI-05）」改为 AI-12；§6 owner 表加 `AI-12：MistyHuang03 / genius-FXC` | §2.4、§2.5、§6 |
| 4 | `candidate.match_basis` 枚举增加 `inventory_fact`、`ai_diagnosis` | §3.4 |
| 5 | `problem` 表加 `evidence_basis TEXT`（`rule \| facet \| mixed`）；AN-06 写明 facet 信号参与会话计数（κ ≥ 0.6 后）但卡片标「含 AI 判定」 | §3.2 (b) |
| 6 | 新增 `ai_job` 表（MVP 列：`job_id, task_id, status, scope_hash, goal_source, preview_digest, estimated_tokens, actual_tokens, created_at, finished_at, error`；`lease_until` v1）；`ai_usage` 加 `status, items_ok, items_failed, engine_version` | §3.3 |
| 7 | hook 脚本落点统一为 `~/Library/Application Support/Orbit/hooks/<template_id>@<version>.sh`；hook 模板闭集六个（`retry-breaker / verify-before-commit / post-edit-check / stop-verify / compaction-reminder / scope-guard`）各标触发 `problem.type`；`scope-guard` 的触发 `unsafe_operation` 随 `recommendation.md` 新增的高风险操作 `problem.type` 进 §3.2b | §3.4、§3.5 |
| 8 | IN 动作枚举增加 `replace_block / move_block`（写前备份、可撤销），供 AI-06.8 与 RC-07 拆分使用 | §3.5 |
| 9 | DT 侧补充约定：连接器把 cwd 位于 Orbit `agent-cwd/` 或首条真人消息以 `[orbit-analysis` 开头的会话标 `session.kind = auxiliary, attrs.origin = orbit`，默认不进 `v_analysis_*`；落在 `packages/data` 的 mapper 公共层 | §1 隐私、DT-01 / DT-06 |
| 10 | API：`GET /v1/analytics/overview` 增 `narration{…, source, prompt_version, model_id, generated_at}`；`GET /v1/analytics/sessions/{id}` 增 `facet`；`GET /v1/ai/jobs/{id}` SSE 事件形状 `{stage, progress, tokens, message}`；`GET /v1/ai/usage?from&until`；`GET /v1/recommendations` 增 `surface / kind` 参数 | §5.3 |
| 11 | AI-09 改为「计划 → 代码执行只读查询 → 回答」（`ask.plan` L2 + `ask.answer` L3），无 L4；AI-11 的空闲 / 额度 / 并发 / 退避规则改为 v1，MVP 为用户触发、串行；AI-06 行的 MVP 改为「规则、hook、SKILL.md、粘合规则」 | §2.5、§5.1 |
| 12 | `judge.rule_counterfactual` 的反例由「随机片段」改为「共享关键词的近似反例」（研究 E6） | §3.6 |
| 13 | `evaluate_text` 新增 scene `weekly_report / share_card / menubar`（随 `evaluation.md` 的同一条建议）；AI 任务固定 scene 映射见 §3.5 | §3.7、EV-09 |
| 14 | 「依据」补 `origin/feat/agent-connectors`（PR #9 / #14：六家 mapper、`ImportService`、`event_page`、`docs/backend/agent-connectors.md`，`user_version = 4`，四个 migration）；PR #11 回归项数 35 | 页首依据 |
| 15 | 待验证清单并入 AV1、AV3–AV15（AV1 = V5 合并；AV2 撤销） | §7 |

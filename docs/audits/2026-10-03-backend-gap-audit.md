# 后端全面审计（2026-10-03）：两轮修复与遗留

> 范围：`packages/connectors`、`packages/data`、`packages/catalog`、`packages/backend` 以及跨包测试与评测。分 12 个区审计（connectors-ts、data-ingest、data-core、catalog、recommend、persona、analytics-core、analytics-products、ai、uiview-features、platform、tests-cross），另有一份算法说明（画像分类、节省时间预估、推荐流水线）。
> 集成分支：第一轮 `feat/backend-audit-r1`，第二轮 `feat/backend-audit-r2`（包含第一轮）。本文以 PR 合并前的这两条分支为准，已合入内容按 `git log origin/main..origin/feat/backend-audit-r2` 核对。
> 区内审计笔记是本地工作笔记（`.work/audit-notes/`，不入库）；本文只收录结论、修复清单与遗留项。
> 产品规则（main `ebdc750e`，已定）：协作人格 1 个会话即出完整 4 字母、按 50 分界、没有单位的轴按 50 计；只有四轴都无值才阻止揭晓。
> 修复原则：数据缺失返回 unknown 而非伪造；阈值与参数写明出处，无依据的标为「产品默认、未校准」；测试期望值由构造样本手算，不复制实现输出。

## 1. 第一轮（摘要）

第一轮对 12 个区做只读审计后修复了 P0/P1 项，按区归纳如下（提交主题见分支历史）：

| 区 | 第一轮主要修复 |
| --- | --- |
| connectors-ts | 工具分类改为名称表并覆盖真实 Codex 工具名；旧版协议事件映射；`cache_write` 缺省按 0 计；重复 legacy 累计值不再生成 `model_call`；单会话重建失败隔离；`event_fts` 与按会话清除投影的性能；`event.ext`、`attrs.output` 不再重复存储。 |
| data-ingest / data-core | 连接器对字符串或 null 的 source、cost、error 防护；Hermes、opencode 发现范围与工具状态；价格表数据化并按缓存 TTL 计费（迁移 014）；inventory 收录 Claude commands/agents；search 时间窗改为半开区间。 |
| catalog | 词法路改为自算 BM25F 并输出绝对相关度；资源库匹配度改用绝对相关度；特征词表按首词分桶、按位置与频次加权；KB 官方条目名称不带模板占位符；风险估计区分未读正文；MMR 冗余只看名称、仓库与类型。 |
| recommend | 排序改为几何均值并拦截净收益非正的候选；节省时间不再用手拍常数；catalog 核验与 Agent 兼容读真实字段；`TARGETS` 与数据层能力矩阵同源；召回权重可配置并注明出处；`dense` 如实更名 `hashed_lexical`；离线回放重建并加入负例。 |
| persona | 置信度由定型轴数生成，D/V 区间按会话聚类；去掉单语料术语表与课程名；`code` 字段从 presentation 画像删除。 |
| analytics-core / analytics-products | signals 升级闸改为 min_sessions + Wilson 下界>0；`would_prompt` 改用调用级 approval；FRUSTRATION 复用情绪词典；指令抽取与主观反馈词典召回提升；presentation 窗口按本地日界对齐并纳入快照键；出口证据数组封顶 50 条并保留 `*_total`；文件扩展名语言表数据化；`unknown_counts.model_calls` 口径修正。 |
| ai | API 引擎改用结构化输出并按完整模型 ID 计价；ask 自由问答按查询数据类校验授权；生成流水线不再把未实现的评审阶段报 ok；引擎环境放行代理与 CA 变量；纠偏判定统一并加中英回归集。 |
| uiview-features | facts 只对缺表缺列降级并在 `meta.degraded` 报告；活跃时长单一实现；outcome 估计规则统一；会话列表搜索不再截断到 50 条；linked 不足 90 天不判 unused。 |
| platform | 排除会话与额度估算 fail-closed；`app-state.json` 损坏时备份并以默认状态启动；worker 日志有上限；realtime/sync 循环可观测；app.db 有序迁移机制；网关屏蔽 legacy purge。 |
| tests-cross | 新建 `tests/conftest.py` 共享网关夹具；UI stub 与真实网关响应的契约测试；Claude Code 与 Kimi 的 gateway 级端到端；evalrun 全跳过、零检查、恒真检查不再判通过；`check-repository` 只检查已跟踪文件并校验文档导航登记。 |

## 2. 第二轮修复（2026-10-03）

第二轮处理第一轮因文件归属或时间盒留下的跨区项。下列修复均已合入 `feat/backend-audit-r2`；「未做」在第 3 节汇总。

### 2.1 catalog：向量路产品化

- **模型发现与授权下载**：新增 `embedding_model.py`，按 `<home>/models`、`$ORBIT_HOME/models`、`~/Library/Application Support/Orbit/models` 查找 multilingual-e5-small。只有用户授权后才下载（`PUT /v1/catalog/embeddings/model`、`ORBIT_CATALOG_MODEL_DOWNLOAD=1` 或 CLI `model-download --allow`），固定 revision `614241f6`，int8 ONNX 118,346,824 B 加 tokenizer.json 17,082,730 B，共约 135 MB；断点续传（HTTP Range），按大小与 SHA-256 校验，不一致删除半成品并报 `model_checksum_mismatch`。
- **加载失败不重复校验**：`LocalE5Encoder` 按 `manifest.json` 选模型，记录 `precision=int8-dynamic`；加载失败按目录记住，状态为 `unavailable`（`embedding_runtime_missing` 或 `embedding_model_unloadable`），词法检索照常。
- **后台增量嵌入**：首次联网同步完成后，网关刷新器每 5 秒调 `service.vector_tick()`；允许时先下载（失败 30 分钟后重试），否则每次嵌入 512 个分块，可取消并从断点继续；`ORBIT_CATALOG_AUTOEMBED` 默认跟随 `ORBIT_CATALOG_AUTOSYNC`。
- **状态输出**：`/v1/catalog/status` 增加 `vector` 块，新增 `GET /v1/catalog/embeddings/status`；状态值 `not_configured`、`downloading`、`download_failed`、`unavailable`、`not_loaded`、`indexing`、`not_indexed`、`partial`、`ready`，含模型信息、下载进度与授权、覆盖率（embedded / eligible / pending）。
- **索引代次**：`index_embeddings` 每次调用只推进一次 catalog generation（取消或崩溃时在 `finally` 里推进），且只处理活跃条目的分块，避免后台嵌入时每 64 块重建整个检索索引。
- **规模实测**（本机一次测量，不构成承诺）：7.5 万分块 × 384 维 fp16 精确余弦中位 3.1 ms（P95 5.0 ms）；矩阵加载 471 ms，常驻 57.6 MB，加载峰值 182 MB；因此保留 fp16 全量精确检索，不上近似索引。种子库 1,312 条、2,875 分块嵌入 245 s，覆盖率 2,875/2,875；int8 与 fp32 逐块余弦均值 0.9985、最小 0.9928。
- **余弦阈值实测**（6 个查询，种子库）：相关条目余弦中位 0.833（n=128），无关 0.801（n=7,744），AUC 0.857；当前有效阈值约 0.76，无关条目保留 97.4%，等于没有过滤。按查询归一化为 z 分数后 AUC 0.891（z≥1.5 保留 69.5% 相关、10.6% 无关）。代码改动属 `search.py`，列入遗留。数据与 6 个查询的 Top 5 对比见 [资源索引验证](../modules/catalog/validation.md)。
- **测试**：`test_vector_lifecycle.py`（10 项，384 维手写单位向量夹具）覆盖校验失败、Range 续传、服务端忽略 Range、发现顺序、无模型回落词法、下载失败退避、模型不可加载、分片嵌入与覆盖率、取消保留已提交批次、语义排序与手算余弦（1、0.707、0 被排除）；`test_catalog_bootstrap.py` 增 3 项；`test_real_embeddings.py` 与 App 用同一发现逻辑，缺模型时带原因跳过。

### 2.2 catalog：来源、兼容与准入

- **匹配行带真实来源与兼容值**：`verification`、`body_policy`、`language`、`support`、`support_basis`、`agent_support`（只含已知级别）、`admission`；缺失的 verification 为 null，不默认成 verified。
- **Agent 兼容推导**：新增 `compat.py`，按资源格式（SKILL.md、MCP、AGENTS.md/CLAUDE.md、Claude Code hooks.json）推导；仅当 `third_party` 源码显示某 agent 读取该格式才算 native（codex、opencode、hermes、dsh、pi）。Kimi、Cursor、Gemini CLI、Copilot 未收录源码，标 unknown/unverified。Codex 读 Claude hooks 为 `adaptation_required`；发布者声明的级别优先。
- **新来源**：awesome 列表（punkpeye/awesome-mcp-servers，仅元数据，`verification=listed_only`）、GitHub topic 发现（agent-skills、claude-code-skills、mcp-server、cursor-rules 等，每 topic 至多 3 页、star≥20、调用间隔≥2.1 s）、awesome-cursorrules（CC0）；`network.py` 对 GitHub 限流 403 按 Retry-After 或 `x-ratelimit-remaining=0` 重试。
- **种子分层抽样**：每类取各来源最优，再保证每个声明的 agent ≥15 条、每个来源 ≥10 条，其余按排名；1277 条增至 1987 条（17 个来源，1.88 MB）。rule 60→250、command 60→150、skill 400→600、mcp 300→500；无摘要的 rule 排除，rule/command/subagent 缺描述时取正文首段。
- **推荐准入**：新增 `admission.py` 与 `data/admission.v1.json`，在 curated 之外加 `rule_admitted` 层：来源已核验、正文有许可、抽取摩擦权重≥0.45（产品默认，未校准）、风险≤1、类型可安装；`reviewed_reject` 可移出。`purpose=recommendation` 的 mask 与 `eligibility()` SQL 同规则。新种子下 approval_wait 10、long_tool_wait 11、readonly_prompted 2、retry_same_call 9 条被准入。
- **详情**：新增 `support` 与 `install.paths`（只对 native 支持的 agent 给出目录）；KB 正文的会话槽位显示为 〈措辞〉 标记。`docs/modules/catalog/architecture.md` 同步了 BM25F、noisy-OR、阈值依据、兼容推导、准入与新来源。

### 2.3 recommend

- **`remedies.v1.json`**：25 条规则逐条核对，没有一条的 `unit_minutes` 有文献或本机实测依据，因此没有编造分钟数；每条新增 `benefit.unit_minutes_note`（产品默认、未校准、仅用于内部排序，并写明应取的实测口径：审批取 `approval_wait_ms`，失败与返工取 `cost_time` 段时长，常驻 token 未实测）。`remedy.agents` 按 `capabilities.MATRIX` 扩到七种 agent（Kimi 保持 unknown），依据写在 KB 顶层 `agent_support_basis`。
- **catalog 路核验**：`catalog_route.enrich` 对缺字段的条目回查 `catalog_item(verification, metadata)`，只有 VERIFIED 通过 `source_verified` 门，`metadata.agent_support` 作为声明的支持矩阵；读不到库时保持未核验并输出 `catalog.verification` 诊断。
- **问题层**：会话数 k 大于主会话数时截断为主会话数并记 `vars.count_mismatch`，状态保持 insufficient；`installed_unused` 采用 `features.linked.UNUSED_WINDOW_DAYS=90`，窗口不足 90 天不判 unused，置信度随观察窗口 90/135/180 天为 .5/.7/.9（产品默认，未校准）。
- **其他**：`RecommendationContext.agent` 按 `TARGETS` 校验；evalrun 的 recommend 套件纳入 replay 负例通过率（阈值 1.0）与合成集声明；新增 `explain_candidate` 直接单测（10 项）；`docs/modules/recommendation/engine.md` 写明 service 栈与 engine v2 两栈的关系、入口与分工。

### 2.4 data-ingest（原生连接器）

- **请求边界 `request_id`**：dsh 用 `seq:N`、kimi 用 loop uuid 与 `usage.record:<ordinal>`、opencode V1 用 step-finish part id 与 V2 用 assistant session_message id，依据各自上游源码；`boundary_quality` 由 unknown 变为 reported。
- **MCP 归属**：`mcp_server_names` 与 `split_mcp_name`（最长前缀匹配）读取 inventory 已观测的服务器名；opencode 与 Hermes 旧版名称写入 `mcp_server/mcp_tool`；无 inventory 或匹配不上保持未知。
- **失败与退出码**：opencode（shell exit、V2 `{type,message}` 错误、interrupted）、Hermes（`tool_error`、`permission_refused`）、pi（按上游 `appendStatus` 的结尾状态行写 exit_code、interrupted 或 timeout）。
- **审批证据**：kimi `interaction.request` 读 `id/toolCallId`，按 `toolCallId` 关联决策；opencode 与 PermissionV1 拒绝原文一致时写 denied；Hermes 终端结果 blocked/pending_approval/approval 注记。各 agent 的审批证据覆盖写在 `connectors/__init__.py` 模块文档：Claude Code 只记录拒绝、opencode 无逐次记录、pi 无权限系统，三者的 `would_prompt` 不可测。
- **其他**：kimi `task.*` 不再映射为 subagent.spawn/result；kimi 协议版本 1.0–1.5 视为已核对、更高 1.x 记 `untested_native_version`；opencode V1 message 只在 model/provider/variant/cwd 变化时记 `setting.change`。新增 `test_connector_evidence.py`（9 项，手算期望）。

### 2.5 data-core

- **重建**：`MAPPER_VERSION` 1.5.1→1.6.0，已导入的库按新映射规则重投影（测试用旧版本盖章的库验证）。
- **标题优先级**：单一表 `contract.TITLE_PRIORITY`（custom 4 > agent_name 3 > native 2 > ai 1），reduce 与 `analysis_input` 共用；`REDUCER_VERSION` 1.8.0→1.9.0。
- **清单类型**：迁移 015 重建 `inventory_item`，`type` 增加 `command`、`agent`，旧行就地改类型并保留 `inv_id`；`SCHEMA_VERSION` 15，`SCANNER_VERSION` 1.4.0。其他 agent 对这两个类型报 unsupported，清单覆盖显示 `inventory_layout_incomplete`。
- **覆盖披露**：`read_analysis` 的 `coverage.excluded_sessions`（按原因计数及其 model_calls、token、cost，未上报为 None）、`sessions.status_known_*`、`model_call.unmapped_model_*`。
- **搜索排序**：12 条按产品意图手写的成对排序判断加参数网格；48 个网格点满足全部判断，现行常量（3/2/1.5/1、30 天、0.25）在其中，数值不变，衰减保底命名为 `DECAY_FLOOR`，无时间戳的命中直接取保底。
- **文档**：`migrations/README.md` 写明 Store 同事务盖 `schema_version` 与 `user_version`；`local-inventory.md`、`data-services.md` 同步。

### 2.6 analytics-core

- **纠偏判定统一**：所有纠偏判断只走 `analytics.interaction.rules` 的 `correction_verdict`/`correction_kind`/`is_correction`；词典升至 zh-en-lexicon-v3；新增 `result_feedback` 类别（只报告结果的消息不算纠偏，interaction 标 feedback，仍计入挫败连击）；单独的 try again 视为客户端重试。标注集 116 条 precision=1.000、recall=0.981（唯一漏检「你改错文件了」）；回归注入集 `correction_signals` 由 98 变为 144（等于注入数），strict xfail 移除；signals `RULES_VERSION` 升至 signals-v1.2。
- **文件引用正则**：`file_pattern()` 取自 `analytics.features.LANG`（另加 txt、log），extraction 与 semantic_cascade 同步。
- **`cost_time.usage()`**：一行无效不再清空范围 `total_tokens`；无完整数据时按已知行求和并标 `total_basis=call_delta_known_rows`（下限），给出 `total_complete`、`total_unknown`、`total_note`；读取 `cache_write_1h_tokens` 与 `service_tier`；新增 `known_cost_usd`。
- **主观结果质量**：带 split 的用例改为聚合算召回与精确率并打印漏检；新增 13 条先标注后运行的 heldout-r2：recall=0.375、precision=1.0（0.9 与 0.3 只是回归下限，不是质量目标）。
- **死代码与阈值**：删除仅测试调用的 `analyze_signals`、`inventory_facts`、`installed_unused`、inventory 版 `resident_tokens_median` 等；`code_block_count` 接上真实输入（canonical 输入计数，legacy 为 null）；`signals/dictionary.THRESHOLDS` 登记信号层全部数值阈值及出处，只有 `wilson_lo_min` 有方法出处（Wilson 1927），其余标产品默认、未校准；`signals.md` 同步到 v1.2。

### 2.7 analytics-products

- **删除死代码**：`recommendations/ranking.py`（`rank_resources`）与 `catalog.vetted_catalog` 仅测试调用，已删；`diagnostics.py` 与 `products/validation.validate_products` 因评测与脚本在用而保留，`fact-diagnostics.md` 说明了分工。
- **work_graph（`work-graph-v2`）**：结果事件的调用无 task 时保留自带的 task 引用（仅靠本地分段得到的仍丢弃，原因 `paired_call_task_unknown`）；跨多组验收：任一组失败则 task 为 False，True 需全部通过；`*_retries` 只在两个调用节点都存在时计数；节点与边 id 仍用 v1 命名空间不变。
- **性能**：统计分组 O(G·N)→O(N)（300 组 6 万样本 280 ms→5 ms）；诊断时长查找只建一次（4 万调用 1426 ms→83 ms，输出一致）；`sections._recommendations` 与 `_presentation` 每个请求只调一次 `recommend()`（300 会话、自定义 `target_agent=codex` 约 1.0–2.8 s→0.2–0.26 s）。
- **路由**：legacy `/v1/analytics/presentation` 与 `GET /v1/analytics/recommendations` 复用网关参数校验（七种 agent，未知值 422，窗口锚定一致）；`recompute` overview 与 GET 使用同一自动窗口。
- **文档**：`presentation-metrics.md` 写明 `collaboration-profile-v2` 无 code 字段、轴表与 Wilson 区间方向阈值（产品默认，未校准）、16 型归 `uiview.persona`；`analysis-products.md` 同步。

### 2.8 persona-reveal

- **统一读取**：引导揭晓（`shell/reveal.py`）、分享卡与报告人格段都读 `uiview.persona.page`；`sharecard.persona_request` 把分析范围映射到 uiview 事实范围并在 `notes` 列出无法应用的过滤；候选类型来自 `persona.candidates`（含 `match`）；`reveal.ui_axes` 用人格页自己的 Wilson 区间。`tests/shell/test_reveal.py` 重写为在手工构造的 facts 行上跑真实 `persona.page`（D75/I66.7/M50/V25→DIMT，I 轴 Wilson(2,3)=[20.8,93.9]）。
- **未知值**：`persona.page` 与 `fit` 对无已知值的轴显示「验证情况未知」，D 轴步数占比只用 msgs 与 steps 都已知的会话，`fit` 无已知 outcome 时 `ok_est` 为 None。
- **Wilson 单一实现**：`analytics/stats.wilson_p` 接受非整数有效 n；uiview/persona、presentation/profile、profiling/analysis 委托它，数值不变。
- **验证命令判定**：`facts.is_validation_command` 按每段 shell 的命令头判断（去掉 env 赋值与 `uv run`、`npx`、`python -m` 前缀），不再因 `cd build`、`ls test/`、`git diff --check`、`docker build` 计入；每个轮次记录 `[steps, verify, requested, ran]`，V 轴仍任一成立即计，证据分开列出；`structured_opening` 不再因文件名或≥200 字触发；`STEP_THRESHOLD` 标为未校准的产品默认。合成库人格仍为 SIMV。
- **可读性**：`readability.py` 去掉 `_JARGON`，复用通用判据 `profiling.bottlenecks.unexplained_terms`（依据 Federal Plain Language Guidelines 2011 与 Google 开发者文档风格指南），规则版本 readability-v3，基准 8/8。

### 2.9 ai-platform

- **fail-closed**：`ai/queries._excluded` 在 app.db 不可读时抛 `ExclusionsUnavailable`（503，可重试），`ask` 不再把它变成空的「0」答案。
- **自动会话标注**：`JobService.on_import_done` 在导入 completed 或 partial 时触发一次，由网关后台线程调 `ai.auto_facet_new`；设置里的授权开关默认关，关闭时不构建 AI 服务、不提交任务；端到端测试覆盖开关两种状态。
- **路由归位**：`/v1/ai/artifacts/{id}/materialize` 与 `/to_library` 迁入 `routes_ai.py`，路径与状态码不变。
- **测试隔离**：新增 `packages/backend/tests/conftest.py`，每个用例前后重置排除、来源范围与洞察 AI 的进程级 provider。
- **A4/A6 缓存键**：`cache_key` 必须带 `home`，并加入已发布计数作为数据身份（`data_rev` 在全新库会从 1 重新开始）。
- **概览「AI 解读」**：`AIService.submit` 把 `data_rev`、`inventory_rev` 存进 `ai_job.request._data`；`ai/narratives.latest_overview` 取最新的、由模型写成的、天数与项目完全一致且数据版本匹配的 `narrate.overview`；命中时 `insight.with_ai` 替换导语与好/卡/下一步，`basis=ai_narrative` 并带 source 与 caveats，计数与引用仍为 L0；带筛选或刷选窗口的视图保持 L0。
- **其他**：evalrun 套件分类 `kind`（`regression_guard`、`contract`、`agreement`）写入列表、结果与摘要，旧结果读时由注册表补上；`/v1/app/tool_map` 按 agent 列出静态名称并加 `agents` 列表，未分类的归 other；`/v1/features/profile` 总返回 `stale`、`rebuilding`、`current_revs`；`docs/README.md` 登记 `mac-app.md`、`import-performance.md`、`ui-backend-parity.md`。

### 2.10 install

- **dsh、pi、hermes、opencode 获得完整安装支持**：dsh、pi、hermes、opencode 的 landing 表每行都引用 `third_party` 源码路径；pi 与 hermes 的项目级目录只在信任项目时加载，标 `requires_trust`；upstream 没有落点的类型给出明确 `reason_text`（dsh MCP/hooks、pi hooks、hermes MCP/hooks 与用户规则、opencode subagent 与 hooks）。
- **Kimi**：未收录源码，标 `install_support=unverified`（`kimi_unverified_no_source`），不写入。
- **规则文件落点**：按各 agent 实际读取的文件链（Codex `AGENTS.override.md` 遮蔽 `AGENTS.md`，pi、Hermes、opencode 各自的顺序）写入；有效文件属于别的工具时拒绝并报 `context_file_shadowed`。
- **Codex 核对**：用户 skills 写入 `~/.agents/skills`（`$CODEX_HOME/skills` 已弃用），项目 skills 写入 `<proj>/.agents/skills`，项目 rules/hooks/MCP 写入 `<proj>/.codex` 并标 `requires_trust`；`command` 改为 unsupported（上游不再读自定义 prompts）；SSE MCP 对 codex 与 pi 拒绝。
- **环境与冲突**：`env.agent_root` 只读 `Env.environ`；opencode 同名 `/mcp/<name>` 返回 `mcp_exists`。
- **测试**：`tests/install/test_more_agents.py`（19 项，临时 HOME）覆盖安装后卸载字节一致、冲突、预览阻塞、第二个文件写失败回滚、`preview_stale`、卸载保留用户后续编辑、Kimi 不写入、SSE 拒绝与规则文件链。

## 3. 遗留与下一轮

按负责方归类。每项后括号是来源区。

### 3.1 需要 prototypes / apps/desktop 负责方处理

本轮禁止改动这两处，下列问题都出在它们的一侧或需要它们配合。

- **语义模型授权与进度**：设置页或资料库页需要「语义模型」授权开关（`PUT /v1/catalog/embeddings/model {allow_download}`），显示 135 MB 大小、下载进度（`vector.download.done_bytes/total_bytes`）、覆盖率（`vector.coverage.ratio`），以及 `download_failed` 与 `unavailable` 的原因（catalog-vector）。
- **打包**：`onnxruntime` 1.30.0（arm64 约 21.5 MB）与 `tokenizers` 0.23.2 仍只在 `orbit-catalog[embeddings]` 可选依赖里；发布 App 要有语义路，打包的 Python 环境须安装该 extra（约 +25–30 MB，嵌入时 ORT 常驻约 1.1 GB）。模型本身不随包，授权后首次下载（若内置 int8 模型约 +130 MB）（catalog-vector）。
- **安装详情与兼容显示**：详情页可显示 `install.paths` 与支持级别及依据，unknown/unverified 不得显示成兼容；新增的 agent 标签（Hermes/dsh/pi/Kimi）需要图标（catalog-sources）。`plan._default_agents` 现默认勾选所有已安装的完整支持 agent，需确认默认勾选、`requires_trust` 与 `reason_text` 提示的显示，并显示新的 `install_support=unverified`（install）。
- **AI 解读卡**：读取 `insight.basis`、`source`、`caveats`；当前没有任何东西自动提交 `narrate.overview`，界面的「重新生成」没有后端，需要调度或 POST 入口，否则卡片在实际中不会显示 `basis=ai_narrative`（ai-platform）。
- **标签展示**：`features/profile` 的 `stale/rebuilding/current_revs`、evalrun 的 `kind`（`regression_guard` 不得展示成准确率）、`tool_map` 的按 agent 条目（ai-platform）。
- **纠偏数变化**：结果反馈不再计入纠偏，前端显示的纠偏数会变，文案需确认（analytics-core）。
- **揭晓响应**：`LVN.personaOf` 读 `c.match ?? c.sim`，后端现返回 `match`（0–100）；响应新增 `conf/hint/axes[].unit/decided/meta.notes`，gate 字段改为 `card_gate` 的 `min_sessions/sessions/axes[].state` 加 `passed`，需另一会话确认（persona-reveal）。
- **覆盖卡**：展示 `status_known_share`、`unmapped_model_share`，并在总花费旁报告被排除会话的 token 与成本（data-core）。

### 3.2 后端待办

**catalog**
- `search.py`：语义路的 `scores > 0` 与绝对 `SEMANTIC_FLOOR=0.7` 改为按查询的 z 分数门（z≥1.5；分块少于约 200 时回落绝对阈值），强度由 z 映射，升 `RANKING_VERSION`，加金标测试（catalog-vector）。
- 中文查询把语义路拉向中文 KB 条目（「浏览器自动化测试」的语义 Top 5 没有 playwright 或 webapp-testing）：考虑编码前翻译或扩展，或给 KB 单独语义配额（catalog-vector）。
- `search._concept_score`：双概念中文查询中一个强概念压过两个概念同时命中（「设计系统」先出泛设计条目），应按概念覆盖计分，该测试现为 `xfail(strict)`（catalog-sources）。
- `MIN_TEXT_RELEVANCE=0.2` 未在新种子上重新校准（`code review` 得分 0.209，`the best tool` 0.202），需要更大的金标集（catalog-sources）。
- `index.py` 的 `CatalogIndex.matrix` 用 `fetchall` 后拼接，加载峰值约 3 倍（7.5 万分块 182 MB），可改为流式写入预分配数组（catalog-vector）。
- 来源：hook 与 workflow 种子数仍为 40 与 17（来源池只有 57 个 hook、23 个 workflow）；Kimi 与 AGENTS.md 合集没有来源（catalog-sources）。`sources/__init__.py:7` 仍称 `~/.codex/prompts` 是 Codex 自定义 prompts 位置，而上游已不读（install）。

**recommend**
- 把本机实测的审批等待接进来：`recommend/section.py` 的 `readonly_prompts` 加 Claude Code `tool_call.approval_wait_ms` 中位数与 Codex permission request→decision 间隔，经 `problems.vars` 交给 `kb_route`，使 readonly-allowlist 等规则能以「实测：N 次审批中位等待 X 秒」显示分钟数；失败与返工类接 `cost_time` 段时长（recommend）。
- `catalog_route` 仍用 `purpose=library` 再按摩擦过滤，可改 `purpose=recommendation` 以使用准入层；`rule_admitted` 条目没有人工评审的场景/维度，卡片文案与置信度应标注「规则准入、未评审」；还可读 `support_basis[*].basis` 区分格式推导与声明支持，以及 `admission.tier`（catalog-sources）。
- `ranking/gates._agent_supported` 与 `narrate` 仍只看使用最多的 agent，可改为对 `inputs.agents` 逐个判定（第一轮 R-05 后半）；`kb_route.PATHS` 只有 claude_code/codex 的落地路径，opencode、pi、hermes、dsh 可从源码确认后补上（recommend）。
- `search()` 返回行直接带 `verification` 与 `metadata.agent_support` 已完成，`catalog_route.enrich` 的回查仅作兜底（recommend、catalog-sources）。
- Kimi 在 `MATRIX` 全 unknown；收录 Kimi 源码并更新矩阵后重跑 remedies 推导，`tests/recommend/test_kb.py` 一致性测试会提示（recommend）。

**data / connectors**
- 用户侧词表：backend `features/vocab.from_session_feature` 与 `features/sessfeat` 从 `analytics.task` 分类结果、来源 agent 与命令头派生 domain/sw/agent 词表；`session_feature` 的 domain/sw/agent 特征本轮未做，因 data 包不能导入 backend（data-core）。
- **已修（fix/app-feedback-r4，audit-data）**：清单扫描发现新 MCP 服务器名时把 opencode/Hermes 的文件标为待重映射，inventory 任务随即重建发布。原条目：`reduce.tool_metadata` 在派生 L3 时按 inventory 再解析一次 MCP 归属，或在 inventory 扫描后触发 rebuild；现在先导入后扫描的库不会补上 `mcp_server`（data-ingest）。
- `signals/detectors.py` 的 `would_prompt` 应以 `tool_call.approval` 为主证据；kimi、hermes、opencode 已有审批或拒绝事件，可以接上（data-ingest、analytics-core）。
- **已修（audit-data）**：`_failure_kind` 把 declined 记为 `permission_denied`（REDUCER 1.9.1）；kimi 双 decision 未去重，消费者按调用去重不影响计数。原条目：Claude Code 拒绝时 `tool.result.status="declined"`，而 `reduce._failure_kind` 只认 failed/interrupted，这些调用 `failure_kind` 为 NULL；需 reduce 纳入 declined，或连接器改用 failed 加 `approval=denied`（data-ingest）。kimi 的 `interaction.resolved` 与 `permission.record_approval_result` 会产生两条一致的 decision，可在 reduce 去重。
- Claude Code 的 `permissionMode` 写入（`would_prompt` 的生产者）仍在 reduce/analysis_input 汇总，未做；Claude Code 与 Kimi 失败工具结果的 `error_class` 上游没有分类字段，保持 NULL；opencode V2 权限拒绝消息格式无法由源码确定（data-ingest）。
- 清单：Claude 插件目录内的 `commands/`、`agents/` 已扫描为 `<plugin>:<name>`，plugin.json 的 `commands`/`agents` 自定义路径（文件夹或单个 .md）作为补充一并扫描（audit-data，SCANNER 1.4.2）；`walk()` 用调用方的 kinds，写死 skill 的只有 `skill_documents`，无需改；Codex `~/.codex/prompts`、opencode 的 `command/`、`agent/`、pi prompt 模板可扫为 command/agent 以消除 `layout_incomplete`；backend `install/env.py COUNT_KINDS`、`features/linked.py CATALOG_TYPE`、`a4a6_tools` 需处理新类型 `command`、`agent`（Claude 用户的已装 skill 数会因此下降）（data-core）。
- `analytics/coverage.py` 为 `excluded_sessions` 的各原因加中文标签（data-core）。

**analytics**
- `ai/tasks_v1.feedback_rule`：`result_feedback` 现 `is_correction=False`、`friction=none`，应按 `correction_kind` 映射到相应摩擦而不是丢弃（analytics-core）。
- `api/insights.py` 从 app.db 的 `ai_facet` 读 outcome 传给 `build_signal_layer(facets=...)`，使 facet 层在生产生效（analytics-core）。
- `analysis_input` 带入 `tool_call_file`（path/op/quality），供 `cost_time` 与 `missing_verification` 使用（目前经 shell 的编辑不计入 edits）（analytics-core）。
- `analytics/features.py` 的 `session_features` 纠偏仍没有长度闸与「助手回复之后」限制，与 signals 口径略有差异，建议统一到 `rules.correction_kind`（analytics-core）。
- 阈值登记：task/topics 轮廓系数与 DBSCAN、`cost_time/durations` 的 `over_one_hour` 与 `top_k`、`semantic_cascade` Budget 仍只在笔记里，待并入 `THRESHOLDS` 或用随机文本基线校准（analytics-core）。
- 非 canonical 的 legacy `--db` 仍重复计算自定义推荐（需 `analytics/service.analyze_store` 支持 `with_recommendations`）；uiview facts 的 recompute 若也有入口，需同样对齐 `fastpath.choose`；图的节点与边 id 固定在 `GRAPH_ID_NAMESPACE='work-graph-v1'`，有意改变时必须改这个常量；`diagnostics.py` 与 `validate_products` 可移入 `evals/`（analytics-products）。

**persona / uiview**
- V 轴产品决策：V 是否只计用户要求的验证轮次、排除 Claude Code 自己跑的测试？数据已拆分，改动会改变现有用户的字母，需团队决定（persona-reveal）。
- `analytics.outcome.validation` 与 `uiview/moments.py:14` 仍用词匹配的 `VALIDATION_RE`，应改用 `facts.is_validation_command`；`shell/reveal.VERIFY_HEADS` 与它是不同判据，可改为读 `uiview_facts` 的 verify 字段（persona-reveal）。
- 分 agent 的 `STEP_THRESHOLD` 需要在获授权的真实数据上测每轮步数分布；`uiview/persona.py` 与 `docs/modules/analytics/profiling.md` 要与写入 `presentation-metrics.md` 的「50 分界」规则核对（analytics-products、persona-reveal）。
- `profiling/trajectory.py` 的占位字段（`eligible_for_training`、`human_label`、`learned_preference`、`preference_weights`）：与 `tests/regression/test_trajectory_audit.py:30-42` 的断言、`modeling.md:62` 的描述一并删除（persona-reveal）。
- 其余 Wilson 副本（`analytics/products/statistics.py`、`analytics/features.py`、`uiview/a4a6_common.py`、`recommend/outcomes.py`、`recommend/problems.py`、`ai/ask.py`）可以委托 `analytics.stats`（persona-reveal）。

**ai / platform / install**
- `narrate.persona` 与 `narrate.session_review` 仍无 UI 消费，需要 `routes_uiview.py` 与 `persona.py` 接上；overview 的显式 `source_ids` 需传入 `_narrative_scope`（ai-platform）。
- `evalrun/suites/install_roundtrip.py` 的矩阵只覆盖 claude_code/codex，`DIRS` 仍建 `.codex/prompts`，需扩到 dsh/pi/hermes/opencode 并按新落点更新；`install/collect.py:115` 仍写死 claude_code/codex（install）。
- Hermes 与 dsh 的 MCP/hooks（YAML）：需要保留注释的 YAML 块写入或调用官方 CLI；opencode subagent 前置格式需映射表；新 agent 的 `MIN_VERSIONS` 无法确认（install）。

### 3.3 测试稳定性

- `packages/backend/tests/analytics/test_routes_cache.py::test_catalog_match_etag_changes_when_the_catalog_changes` 在基线 `042b41b4` 就失败（返回 200 而不是 304），需 analytics-core 或 catalog 排查。
- 负载下偶发失败：catalog `test_perf_smoke::test_lexical_and_list_latency_smoke`、`tests/services/test_gateway_basics.py::test_status_without_database_is_fast_and_onboarding`、`test_ingest_flow::test_concurrent_reads_during_import_never_fail`、`test_legacy_analysis_offload::test_legacy_analyses_are_queued_paged_and_bounded`；单独重跑通过，建议标 serial 或放宽阈值。
- 共享 scratchpad 的并发：两个 workflow 代理同时用同一个 `ORBIT_HOME` 会互相替换 catalog.db；下次给每个代理单独的暂存子目录。
- `packages/backend/tests/settings_data/test_about_toolmap.py` 可补 per-agent 静态条目的覆盖（现有 `tests/services/test_units.py` 直接单测）。

### 3.4 文档待同步

- `docs/modules/data/agent-connectors.md`：Kimi「1.0–1.5」与各 agent 审批证据、`would_prompt` 不可测的说明（data-ingest）。
- `docs/contracts/analysis-inputs.md`：登记 `coverage.excluded_sessions`、`sessions.status_known_*`、`model_call.unmapped_model_*`；`docs/contracts/data.md` 的 DDL 索引仍指向 006，应提到 015 与迁移 README（data-core）。
- `docs/modules/analytics/feature-analytics.md` 第 133 行仍写 `code_block_count` 当前为 null，现对 canonical 输入计数、仅 legacy 为 null（analytics-core）。
- `docs/plans/*.md` 多处仍引用 readability-v2，现为 v3（历史方案，未改）（persona-reveal）。
- 算法说明（画像分类、节省时间预估、推荐流水线）目前只在本地笔记 `.work/audit-notes/explain.md`，仓库里没有 `docs/modules/analytics/algorithms-explained.md`；该笔记基于第一轮基线，其中关于两套画像并存、`recommend/service.py` 等描述在第二轮后已变化（人格统一读 `uiview.persona`，`recommend` 两栈关系见 `docs/modules/recommendation/engine.md`），入库前须按本文第 2 节重写。

### 3.5 本轮没有做的审计项（时间盒）

- Hook 与 workflow 种子数量未能提升（catalog-sources）；Kimi 无来源（catalog-sources）。
- `remedies.v1.json` 没有任何一条拿到有依据的分钟数（recommend）。
- 全量测试没有在每个区内跑，各区只跑了定向测试；合入由集成脚本把关。

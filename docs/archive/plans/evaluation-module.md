# Orbit Benchmark 与评测设计（EV）

> 文档状态：历史记录。正文保留原基线、日期与证据；其中的状态和数字不代表当前版本。现行入口见[文档导航](../../README.md)。


> 状态：方案（不等同当前能力） · 维护者 `yhyfhgs` · 核对版本 main `0c96334` · 适用：Advance / Lite（另注明处除外）

> 日期：2026-10-02（第 2 版，按评审意见修订）。回答五个问题：**数据算得对不对、分析准不准、推荐对不对、生成好不好、装得对不对且能撤销、装了真的有效没有**，外加本轮验收目标「说人话」；并说明模型 + 思考强度的 benchmark 怎样进入产品。只做规划与分工，不实现算法。
>
> 依据：模块契约 [`contract.md`](module-contract.md)（第 2 版；本文 §13 列出并入第 3 版的条目）；main `f4a2cde`（`orbit_backend` 0.13.6；已合入 PR #10 后端基线、PR #11 `packages/connectors`（TypeScript Codex connector，35 项构造回归、`connectors.yml`）、PR #12 Lite Demo、PR #15 Lite / Advance 命名、PR #16 `analytics/instruction` 与 `tests/fixtures/instruction-quality.json`、`docs/backend/instruction-validation.md`；`src/orbit_backend/{evaluation,pipeline_eval,reader_eval}.py`、`tests/`（约 486 项）、`.github/workflows/{backend,connectors}.yml`、`docs/backend/{acceptance,reader-review}.md`）；未合入分支：PR #9 `origin/feat/session-data-contract`（`packages/data`，`contract.KINDS` 26 种）与其续作 PR #14 `origin/feat/agent-connectors`（`migrations/001–004.sql`，`user_version = 4`；`orbit_data.validation`、`scripts/check-connectors.sh`、Kimi mapper）；`MistyHuang03` 的 PR #13 `origin/feat/analytics-preference-task`、PR #17 `origin/feat/analytics-subjective-outcome`（`tests/fixtures/*-quality*.json`、`docs/backend/analytics/validation.md`「五类验收」）；`genius-FXC` 的 PR #19 `origin/refactor/genius-FXC-bottleneck`（`analytics/{respond,interaction,cost_time,outcome}`、`tests/bottleneck/`、`tests/fixtures/bottleneck-features-v1.json`）；[调研总结](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/03-%E7%A0%94%E7%A9%B6/%E8%B0%83%E7%A0%94%E6%80%BB%E7%BB%93.md) §3.4、§5.3、§6.5 及其汇总的调研笔记 §5；team-hub `Hackathon/后端-处理流程.md` 第 10 步「evaluation：简单测试案例：说人话」。
>
> 本机状态（写作时）：`feat/yhyfhgs-dev` = main + 文档提交；`ui/shell`、`ui/vizkit`、`ui/foundation` 工作树是前端外壳与图表库，不涉及 EV。本文不依赖未提交内容。
>
> 目录说明：main 于 2026-10-02 17:08 合入 PR #28 `refactor/app-structure`（`6f31203`，含 PR #29 `feat/recommendation-catalog` 与 PR #30 `docs/analysis-review`）：`src/orbit_backend/` → `packages/backend/src/orbit_backend/`（`evaluation.py / pipeline_eval.py / reader_eval.py` → `evaluation/{readability,pipeline,reader}.py`，旧入口保留；`cli.py` → `cli/commands.py`；`bottlenecks / feedback / portrait …` → `profiling/`；`narrative / analysis_reports` → `reporting/`）；`docs/design/demo` → `prototypes/{lite,advance}`；`docs/contracts/analysis-inputs.md` → `docs/contracts/`；`docs/backend/*` → `docs/architecture/ + docs/modules/ + docs/releases/backend/`；真实数据评测脚本 → `evals/`（`evals/README.md`）、性能 → `benchmarks/`；pytest 合计 658 项（根 `tests/` 17 + 各包）；CI 入口改为 `pnpm check`（`scripts/check.sh`）。与四份模块文档一致，本文 §0–§2.3 的路径按 `f4a2cde` 写法，§2.4 起的「现状」列写 PR #28 之后的路径；对照表见 main `docs/archive/migrations/structure-migration.md`。
>
> 术语：按契约 §2.1，「benchmark」只指公开模型成绩 `benchmark_result`（DT-14）；Orbit 自己的检验叫「评测 EV」；Lite 的「个人协作 Benchmark」是产品名。版本名统一为 Lite（`prototypes/advance/benchmark-review.md` 8 页）与 Advance（`prototypes/advance/src`）。「待验证」= 需要真实数据或实测才能定的技术假设，只引契约 §7 编号（§12）。
>
> MVP 判定规则（契约 §2.1 状态列，第 3 版条目）：MVP = Lite 8 页需要的数据 + Advance 的三张安装闭环卡（只读放行、重复失败熔断、高频纠偏 → 规则）；只服务 Advance 独有界面（A9 工坊外壳、ASK、菜单栏 / HUD / 小组件、首次启动、SET-21 周报、A1-06 上期对比、A3 阶段带与情绪泳道）的 feature 一律 v1，Advance 设计保留为路线图。本文每个 EV feature 的阶段按此重标（§6、§10）。

## 0. 结论先行

1. **每个问题各有一条独立证据链，任何单层结论都不对外写「有效」**（瑞士奶酪叠加，[Anthropic：Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)）。数据对 = E1 回归 + EV-01.2 指标金标；分析准 = E2 标注（MVP 精度版）；推荐对 = E6 曝光反馈 + 覆盖率；生成好 = E3 三道机械自检 + 文案检查 + 人工采纳；装得对 = E1 安装往返（EV-13）；真的有效 = E5 三层效果 + 护栏；说人话 = E7。界面上只允许四种措辞：「已计数 / 估计 / 未测 / 数据不足」（= 现有 `effect_status = unmeasured`、`human_acceptance = pending`）；所有信号在 MVP 一律称「候选」（main 现有措辞）。
2. **已有三件东西直接升级为正式套件，不重写**：`evaluation.py`（readability-v2，7 个问题码、6 个篇幅预算）→ EV-09；`pipeline_eval.py`（构造 Codex 日志 → 独立临时库 → 正式链路 → 事后对标签；34 + 12 例）→ EV-03，扩成「AN-05 每类 `signal.kind` 一正一反」「每条 `remedy_rule` 一个触发用例」「每个闸门一项消融」；`reader_eval.py`（reader-pack-v1，X / Y 顺序互换，4 维 0–4）→ EV-09.1 / EV-10，补真实读者轮。
3. **数据层回归已分散在四处，EV-01 只做汇总与门槛，不另起框架**：main 约 486 项 pytest（CI `backend.yml`）；main `packages/connectors` 35 项构造回归 + 真实样本原文 SHA 对账（CI `connectors.yml`，PR #11 已合入）；PR #9 / #14 `orbit-data verify` + `tests/data/` + `python -m orbit_data.validation`（幂等断言、`verify()`、`ingest_issue` 分组、1000 条吞吐、离线 HTML 报告）+ CI `data-contract.yml`。MVP 新增的只有一次性的 `/insights session-meta` 只读对照（EV-01.1）；ccusage / `cost-state` 对账 v1（价目表 DT-08 v1 之后）。
4. **标注从「每人 30 条命中」起步，不算 κ**：三人各自在自己数据上，对 MVP 的每个检测器（`correction`、`retry_loop`、`would_prompt`、`missing_verification`）标 30 条命中为 `confirm / inaccurate`，报精度与 n；结构型检测器（`retry_loop`、`would_prompt`、`missing_verification` 与 main 现有 4 类）以 EV-03 构造用例 100% 通过 + 本机抽检 P ≥ 0.7 代替 κ。两人交叉标注、κ、A3 标注模式、结构化 `payload` 全部 v1。标注写 `label` 表（MVP 只存 `{target_kind, target_id, label, reason}`）。
5. **judge 整体 v1**（与契约 AI-07 ④ 一致）：MVP 生成物门槛 = ① 规范校验 ② 静态安全扫描 ③ 历史回放 dry-run（`false_block = 0`）+ `evaluate_text` 文案层；白名单前缀由 DT-13 词表决定、hook 有回放 dry-run，judge 对这两类没有增量。judge 金标、Rogan–Gladen 校正、漂移监测的做法保留在 §2.3，阶段 v1。
6. **推荐质量的 MVP 指标只用曝光反馈**：采纳率 / 不适用率 / 撤销率（按 `remedy_rule_id` 与 `surface` 分组）+ 问题覆盖率；时间切分回放 HitRate@k 与 NDCG@k 都 v1（回放依赖已装清单的历史，契约 V7 只能用当前配置近似）。解释可信度的机械部分（引用存在、场景保留、来源版本化、语言保留、闸门消融）已在 `pipeline_eval.evidence_checks`，保持 100% 硬门槛。
7. **装后效果分三层**：触发 / 机械 / 行为。前窗 = `tracking.baseline_from / baseline_to`（默认安装前 28 天）；可用天数不足 14 天记 `insufficient`；后窗 7 天（滚动到 28 天）。MVP 做触发 + 机械 + 护栏 + 四态结论（有改善 / 暂未看到明显变化 / 变差建议撤销 / 数据不足），由 EV-07 在线计算、`GET /v1/outcomes/{install_id}` 返回；行为层 DiD + 按天分块 bootstrap 与 N-of-1 试验 v1。
8. **安装模块有自己的评测（EV-13，MVP）**：用临时 `HOME` 构造每个 Agent 的配置夹具（空文件、已有同键、用户手改、已有 Orbit 标记块、非法 JSON）× 每种 `action`，断言预览 diff = 实际写入差异、撤销后 sha256 与安装前一致、重复安装无变化、未知键保留、不写托管层、`preview_digest` 不符拒绝写入、用户改过标记块拒绝自动撤销；CI `--suite install` 门槛 100%；本机 `--real` 冒烟确认 `claude` / `codex` 真的读到规则与 allow 前缀。
9. **Benchmark 在 MVP 只是一张读 AN-12 的表**：A7「模型与思考」/ Lite「优化建议 › 模型」读 `GET /v1/analytics/metrics?group_by=model_effort`，按 n / 区间渲染，不下任何结论；公开榜单（SWE-bench Verified、Terminal-Bench、LMArena、models.dev）导入、任务类型 → 基准映射、Beta-Binomial 收缩、面板的公开成绩列与 RC-08 候选一起 v1；因果只能靠 N-of-1 档位交替试验（v1）。
10. **运行方式沿用现有命令，MVP 只补退出码**：`orbit evaluate --fail-under`（现有 readability / pipeline / probe + 新增 injection、install、metrics、privacy）把 JSON 写到 `.local/evaluation/`；`eval_run` 表、`data/eval_baseline.json` 棘轮、`GET /v1/evaluation/runs`、设置页评测状态卡、detector / facet / judge / rec-replay / artifact / outcome 六个 suite 全部 v1。现状缺口：`orbit evaluate` 不设退出码（`cli/commands.py` 直接 `return`），probe 12 例没有测试守着；PR #28 之后 CI 的 `scripts/check.sh` 只跑 pytest、`check-installed.sh` 与 `tests/integration`，不再调用 `orbit evaluate`（旧 `backend.yml` 曾调用），EV-12 第一步就是把它接回 `pnpm check` 并带 `--fail-under`。
11. **Demo 从评测角度缺三样核心件**：A7-15 效果追踪的四态结论与区间（= UG-RC-04，前端只做一次）；统一反馈入口（不适用原因 / 不像我 / 不准确 / 有用没用）写 `label`；卡片主数字的 `已计数 / 估计 / 未测` 标签。A9-15 自检清单可失败（= UG-AI-04）随 A9 工坊 v1。四份文档的前端升级表合并到 `docs/archive/plans/feature-map.md`，本文 §9 只保留 EV 侧条目与去重说明。

## 1. 评测要回答的问题与分层

| 问题 | 层 | EV | 真值来源 | 能对外说什么 | 不能说什么 |
| --- | --- | --- | --- | --- | --- |
| 数据算得对不对 | E1 数据回归 + 指标金标 | EV-01、EV-01.1、EV-01.2 | 构造夹具、全记账恒等式、手算期望、外部对照（`/insights`） | 「已计数」 | 任何语义结论 |
| 分析准不准 | E2 检测器 / 问题 / 时刻 / 结果 / 人格 | EV-02、EV-02.1 | 人工标注（MVP 精度与 n；v1 κ）、合成注入集 | MVP 一律「候选」；v1 κ ≥ 0.6 的类型才称「摩擦」 | 人格是心理测评 |
| AI 读得准不准、贵不贵 | E2（facet）/ E4（judge） | EV-04（v1）、EV-04.1、EV-04.2（v1）、EV-11、EV-14 | 同一批标注、judge 金标（v1）、`ai_usage`、隐私夹具 | 「AI 候选（未校准）」（MVP）；「AI 判定（已校准）」（v1） | 未校准 judge 的任何结论 |
| 推荐对不对 | E6 曝光 + 回放 | EV-05、EV-05.1（v1）、EV-05.2（v1） | `rec_exposure` + `label`；时间切分回放（v1） | 「针对会重复发生的问题」 | 「会提升 X%」 |
| 生成物好不好 | E3 装前 | EV-06、EV-06.1（v1） | lint、静态扫描、dry-run、`evaluate_text`、人工采纳；judge / 触发评测（v1） | 「已通过回放 N / N、误拦 0」 | 「安全」「一定有效」 |
| 装得对不对、能不能撤销 | E1 安装往返 | EV-13 | 临时 `HOME` 夹具 × action 的往返断言；本机 `--real` 冒烟 | 「预览即写入；撤销后逐字节恢复」 | 「不会影响其他配置」（只对 Orbit 写入的键成立） |
| 装了真的有效没有 | E5 装后 | EV-07、EV-07.1（v1） | `tracking` 基线 + 后窗 + 护栏 | 四态结论之一 | 因果（除 N-of-1） |
| 换模型 / 调档位值不值 | E5 + 先验 | EV-08 | AN-12 分层（MVP）；`benchmark_result`（v1） | 「你的数据（估计）」；v1 加「公开成绩」 | 跨厂商比档位、跨 harness 混排 |
| 读者看得懂、信得过吗 | E7 可读性 | EV-09、EV-09.1、EV-10、EV-10.1 | `evaluate_text` + 读者评分 + `label` | 「读者已验收（限所列案例）」 | 「中文自然」「用户满意」 |

**硬规则（全部已有实现或契约约定）**

| 规则 | 内容 | 现状 |
| --- | --- | --- |
| 标签后读 | 预测路径不接收标签与评价标准；`expected` 只在预测完成后比对 | main `pipeline_eval._write_case` 不读 `expected`，`test_case_writer_does_not_receive_or_copy_expected_labels` |
| 评测不改历史 | 评测在独立临时库 / 独立目录运行；`history_updated = False`；评价表不进画像 | main `test_benchmark_cannot_modify_selected_normal_database`、`reader_eval` 不打开历史库 |
| 评测不改用户配置 | EV-13 只在临时 `HOME` 跑；`--real` 冒烟只读现有配置与 Agent 输出，不写入 | 计划（EV-13） |
| 自身会话隔离 | Orbit 发起的 Agent 会话用固定 `marker` + 临时 cwd，导入时经 `excluded_session_uids` 过滤；评测会话也排除 | main `sample_policies(before, exclude)`、`--exclude-session`；AI-01 计划 |
| 固定快照 | 真实数据评测用固定 `until_ts`（legacy `before + 1`），结果写 `dataset_sha256` / `analysis_digest` | main `Scope`、`pipeline_benchmark.dataset_sha256`；`verify_semantic_history.py` 要求固定快照 |
| 只写 `.local` | 真实数据产物只写 `.local/`（被 Git 忽略）；仓库只放构造案例与汇总 | `verify_semantic_history.py` 显式校验输出路径；`docs/backend/analytics/validation.md` |
| 分母为 0 保持未知 | precision / recall 分母为 0 时为 `null`，不写 100% | main `pipeline_eval._metrics` |
| 版本固定 | 每次评测记录 `component_version`（`readability-v2`、`pipeline-contrasts-v1`、`reader-pack-v1`、`rules_version`、`prompt_version + model_id`） | 契约 §3.1 版本列 |
| 门槛有执行点 | 每条上线门槛写明谁读它：检测器校准 → RC-03 闸门 9 子条件（§2.2）；facet / AI-04.1 门槛 → `type_source` 与默认展示开关（§2.3）；生成物门槛 → `install_plan.risk_scan`（§2.5）；装后四态 → `candidate.effect_status`（§2.6） | 本版新增 |

## 2. 分层评测与指标

### 2.1 E1 数据层正确性（EV-01、EV-01.1、EV-01.2）

对象：去重、记账、token 计数、时间质量、脱敏、Schema；对齐 PR #9 / #14 与 main `packages/connectors` 已有回归，不重复写。

| 检查 | 恒等式 / 指标 | 通过标准 | 现状 | 缺口 |
| --- | --- | --- | --- | --- |
| 全记账 | `raw_record` 数 = Σ `disposition`（mapped / folded / replayed / duplicate / ignored / unparsed）；`record_event` 多对多可回链 | 恒等式成立；`unparsed` 占比 < 1% 且逐条有 `ingest_issue` | PR #9 `v_raw_record_ledger` + `tests/data/test_pipeline.py`；main `packages/connectors`（`raw_record + current_record`）；PR #14 `validation._run` 的 `verify()` 与 `ingest_issue` 分组 | 把恒等式写成一条跨包的汇总断言（EV-12 汇总） |
| 幂等 | 重复导入零差异（事件数、哈希、`projection_run` 不变） | `changed = False` 且 `before == after` | PR #14 `validation._run` 已断言「Repeated import changed an unchanged source」；main `test_repeated_import_is_idempotent_and_evaluation_does_not_update_profile`；main connector 重复导入对账 | canonical 接入后对 `analysis_digest` 再加一次幂等断言（AN-16） |
| 去重 | fork / replay / 复制前缀不双计；`forked_from`、`record_event.relation = replayed` | 抽检 50 条人工核对无误（DA M3）；夹具 100% | PR #9 fork 去重测试、`tests/data/test_edges.py`；main `test_explicit_replay_not_counted_twice…` | 50 条真实抽检只在本机做，结果写 `.local/evaluation/` 备注 |
| token 分桶 | 五桶互斥：input 不含缓存、output 含 reasoning；`call/delta` 与 `cumulative_snapshot` 二选一不相加；累计 100 → 150 不相加 | 构造夹具 100% | PR #9 `normalize_usage()` 六方言；main `test_tokens_cache_buckets_reasoning_and_invalid_requests`、`test_cumulative_latest_not_summed…`；PR #19 `tests/bottleneck/test_cost_time.py` | ccusage 同口径对账（v1，EV-01.1） |
| 成本 | `cost_source ∈ native / price_table / unknown`，价目表带版本；无价目表 `cost_usd = NULL` | 与 Claude `cost-state` 累计值误差 < 1%（v1，价目表 DT-08 落地后） | PR #9 `cost_usd` NULL 语义；DA M2 口径 | v1 |
| 时间质量 | UTC 毫秒；半开窗口；`attrs.time.quality`；时间未知单列 | 夹具 100% | main `test_half_open_time_filter_and_calendar_unknowns`；PR #9 `attrs.time` CHECK | — |
| 脱敏 | 已知密钥模式 0 泄漏；`redaction_version` 变更即重洗 | 注入密钥的夹具在 L2 中 0 命中 | main `test_common_secret_patterns_are_redacted`；main connector `privacy.ts`（凭据键变体、重洗旧投影）；PR #9 `privacy.py` | 两份规则表合并后共用一套夹具（契约 §3.8 待定归属）；AI 上下文包的隐私夹具另见 EV-14 |
| Schema | `event-v1.schema.json` / `tables-v1.schema.json` 校验；connector `validateEvent` | 100% | PR #9 `schema_export.py`（`KINDS` 26 种）；main connector `schema/events.schema.json`（25 种，缺 `permission.request`，契约 V12） | — |
| `/insights` 对照（EV-01.1，MVP 一次性） | Claude Code `~/.claude/usage-data/session-meta` 的工具次数、打断次数、`bash_would_prompt_count` 与 Orbit 同会话数值 | 差异可解释（词表范围、分母口径），逐项写明；只做一次，结果进 `.local/evaluation/insights-<ran_at>.json` 与 PR 正文 | 计划（DT-18 只读） | — |
| 性能基线 | 导入吞吐、分析耗时（不是门槛，只记录） | 记录 `records_per_second / analyze_seconds` | PR #14 `validation.benchmark()` 1000 条；PR #13 `scripts/benchmark_semantic_families.py`（3,000 条 / 秒；10,000 条 3.3 s）；真实快照导入 7.27 s、分析 3.11 s | 100–300 MB canonical 库计时（契约 V4，阻塞 MVP） |
| canonical 接入回归 | 同一固定快照，legacy bundle 与 canonical bundle 的 `counts` 差异可解释；`human_origin` 未知从 918 / 927 显著下降 | 差异逐项有原因；`human_origin` 覆盖 ≥ 50%（契约 V11，阻塞 MVP） | 计划（AN-16） | — |

**EV-01.2 指标引擎金标（MVP）**：AN-01 指标引擎、AN-10 统计库、AN-12 周桶 / `compare_previous` / `change_flags`、AN-14 固定窗口快照是 A1 KPI 与 A2 人格区间的来源，现状没有任何正确性门槛（`analytics` 测试只验契约夹具形状）。

| 项 | 做法 | 门槛 | 阶段 |
| --- | --- | --- | --- |
| 金标夹具 | 在 canonical 夹具（`analysis-input-v1.json` 形态）上构造约 30 个会话，覆盖：来源未知的 user 消息、fork 重放、跨午夜与时区（`display_timezone` 两种）、末周不完整、n = 4 / 5 / 30 边界、状态全未知的工具调用、`model_call` 缺桶、`cumulative` 与 `delta` 混用 | 仓库 `tests/fixtures/metrics-gold-v1.json`：每个 `metrics` 项（MVP 先覆盖 Lite 8 页用到的约 20 项 + Wilson）写手算期望 `{value, n, lo, hi, status, basis}`；100% 相等（浮点 1e-9） | MVP（约 20 项）；v1（全部 metrics 项、EB、bootstrap、`change_flags`） |
| 统计函数对照 | `analytics/stats.py` 的 Wilson、Newcombe、EB、按天 bootstrap（固定种子）对照 scipy / statsmodels 参考值 | 误差 < 1e-6（bootstrap 比均值与区间，固定种子下精确复现） | MVP（Wilson）；v1（其余） |
| 字典覆盖 | `feature_dictionary` 每个指标都有 `denominator`、`basis`、`type`；`metrics` 端点返回的每个 metric 都在字典里 | 100% | MVP |
| Demo 数字 → 端点映射 | 把 `analysis.md` §6.1「每个数字都能回到 `metrics / sessions / profile / signals / problems` 端点」做成检查项：Lite 8 页与 Advance A1–A6 用到的字段清单（`docs/archive/plans/feature-map.md` 前端升级表的「后端字段」列）逐项存在且带 `n / lo / hi / basis` | 100%（缺项列出） | MVP |
| 运行 | `orbit evaluate --suite metrics`，纳入 `--fail-under metrics=1.0`，CI 每次 PR | — | MVP |

### 2.2 E2 分析准确性（EV-02、EV-02.1）

**标注对象与指标**。MVP 口径：每人只标自己数据上 MVP 检测器的命中（`confirm / inaccurate`），报精度与 n；界面所有信号继续称「候选」；κ、交叉标注与结构化 `payload` 全部 v1。

| 对象 | 标签（MVP） | 指标 | 上线门槛 | 阶段 | 现状 |
| --- | --- | --- | --- | --- | --- |
| 摩擦 / 纠偏信号 | `label(target_kind = signal, label ∈ confirm / inaccurate)`；MVP 标 `correction`、`retry_loop`、`would_prompt`、`missing_verification` 各 30 条命中 / 人 | 每类精度 P 与 n；结构型检测器（`retry_loop`、`would_prompt`、`missing_verification`、main 现有 `explanation_revision / long_response / unexplained_terms / repeated_tool_failure`）另以 EV-03 构造用例通过率衡量；v1 两人 κ 与召回 | **进入推荐的类型 P ≥ 0.7**（语义型 `correction` 用 30 条标注；结构型用 EV-03 用例 100% + 本机 20 条抽检 P ≥ 0.7）；v1 κ ≥ 0.6 才称「摩擦」（≥ 0.7 视为可靠）；R 只报告不门槛 | MVP（精度）；v1（κ） | 构造集：main `pipeline_cases.json`（4 类瓶颈）、main `tests/fixtures/instruction-quality.json`；PR #13 / #17 `semantic-quality-v1.json`、`subjective-outcome-quality.json`（自述「非盲测、非真实总体准确率」）；PR #19 `tests/bottleneck/`。真实标注：无 |
| `problem`（AN-06） | 每人本机前 20 条人工判定 + 用户「判断错误」写入的 `label(target_kind = problem, label = inaccurate, reason = wrong_diagnosis)` 比率 | 精确率（前 20 条）；`inaccurate` 比率 | **≥ 0.8 才进 A1-10「卡在哪」与 A7 卡片**，否则只在 A3 详情显示「候选问题」 | MVP | 计划（契约 V1 的「人工看前 20 条」变成指标） |
| `key_moment`（AN-09） | 按 `kind` 标 `confirm / inaccurate`（规则时刻各 20 条 / 人） | 按 kind 的精确率 | 规则时刻 ≥ 0.8 才画实心标记；AI `deviation` κ ≥ 0.6（v1，两人）否则不显示空心标记 | MVP（规则）；v1（AI） | 计划 |
| 结果（AN-19） | `label(target_kind = session, label ∈ confirm / inaccurate)` 对 `outcome / user_acceptance` | `user_acceptance` 准确率；`outcome` 四态混淆矩阵（v1） | `user_acceptance` 准确率 ≥ 0.8；`outcome` κ ≥ 0.6（v1） | MVP（`user_acceptance`）；v1（`outcome`） | PR #17 `outcome_subjective`；PR #19 `outcome/`（规则壳）；`task_success = null` |
| 主题簇（AN-18） | 每簇 3 个代表会话「同一主题」人工判定 | 判定比例；噪声点占比 | ≥ 70% 才在 A6-09 显示簇卡，否则只显示「未归类」；噪声占比随卡显示 | v1 | main `analytics/text.py`（簇不命名） |
| `installed_unused`（AN-11） | 对全部被标闲置的条目人工确认（本机） | 误报数 | **误报 = 0 才允许 RC-07 出「停用」卡**，否则只出「检查」卡 | v1（随 AN-11 / RC-07） | 计划（依赖 DT-09） |
| 阶段边界（AN-03） | `segment(level = phase)` 的 `label` 与边界事件 | 逐事件准确率、边界 F1（容差 ±3 个事件） | 边界 F1 ≥ 0.7 | v1（阶段带是 Advance 独有） | 计划；task 级 `feedback.task_contexts()` / PR #13 `segment_tasks()` 已有 |
| 情绪（AN-07） | `sentiment ∈ positive / neutral / negative / frustrated` | 三分类宏 F1、ECE | 宏 F1 ≥ 0.6，否则只显示「实验性」 | v1 | 计划 |
| 人格四轴（AN-08） | 不标「正确答案」；评一致性与认同 | 分半信度（奇偶日拆分，轴值相关 ≥ 0.7）；「?」轴比例；用户「不像我」标签率 | 分半信度 ≥ 0.7；三人「不像我」≤ 20%；「?」轴不恒为 100% | MVP（「不像我」标签率）；v1（分半信度） | Lite / Advance 示例算法；真实实现计划（AN-08） |
| 任务上下文（AN-17） | `scene`、`task_id` 边界、读者、交付语言 | 与标注一致率；`task_id` 边界 F1 | 场景 ≥ 0.8；语言 ≥ 0.9 | MVP（构造集已有） | main `feedback.py` 规则 + 34 例构造集；真实快照只有 9 条可确认真人消息 |

**检测器校准门槛的执行点**（MVP）：`orbit evaluate --suite injection` 与 `orbit label` 的汇总写 `.local/evaluation/detector-summary.json`：`{kind: {precision, n, constructed_pass, passed}}`（v1 迁入 `eval_run(suite = detector)`）。RC-03 闸门 9（`evidence_ok`）读它：问题的主信号类型 `passed = false` 或文件缺失时，候选仍可展示但标「候选（未校准）」，并且不进入 RC-05 的 Top N 快照（A1「本周建议」、菜单栏、小组件）。AN-06 升级不读它（升级只看会话数与 Wilson 下界），所以门槛只影响推荐与首页，不影响 A3 / A6 的候选展示。

**标注集建设（输入 → 处理 → 输出）**

| 步骤 | MVP | v1 |
| --- | --- | --- |
| 抽样 | 每人从自己近 60 天数据里，对每个 MVP 检测器取最近 30 条命中（不足 30 条取全部，报 n）；`problem` 前 20 条；规则时刻各 20 条 | 分层抽样约 200 会话：`source.agent × project × 时长四分位 × 是否命中候选`，候选命中 50% + 随机 50%；加同量随机负例算召回 |
| 工具 | `orbit label --kind <signal.kind> --limit 30`：终端逐条显示 L2 脱敏文本与命中位置，按 `c / i / s` 标 `confirm / inaccurate / skip`；写本机 `analysis.db.label`，不产生仓库文件 | A3 会话详情标注模式（UG-EV-06） |
| 产物 | `label` 行只有 `{target_kind, target_id, label, reason?, labeler, ts}`；汇总 `{kind, n, precision}` 进 `.local/evaluation/detector-summary.json` 与 PR 正文 | `label-set-v1` 冻结（内容哈希）、`payload`（`friction_type / severity / sentiment / intents / target_event_uid / phase_boundary / user_acceptance / outcome / task_type`）、仓库只放 `{label_set_version, kind, n, κ, P, R, F1}` |
| κ 的隐私做法 | 不做 | 每人抽 30 条脱敏片段（L2 `text`，本人逐条预览同意）给另一位成员标，只用这部分算 κ；三人共同标 20 条合成案例作校准练习 |
| 复用 | 同一批 `inaccurate` 标签回流 EV-03 构造用例（去身份化后由本人改写成合成案例） | 同一批标注同时给 facet κ（EV-04.1）、judge 金标（EV-04）、情绪权重标定（AN-07） |

`friction_type` 的两套枚举（契约 10 类细类 vs PR #19 `interaction.FRICTIONS` 4 类粗类）按 §13 的映射表统一；PR #19 `attrs.interaction` 的「确认标注」在契约第 3 版改为一律写 `label(target_kind = signal)`，分析侧读 `label` 生成 `type_source ∈ rule / facet / user`（`analysis.md` §11 C8）。

### 2.3 AI 抽取质量与 judge 校准（EV-04、EV-04.1、EV-04.2、EV-11）

**门槛的唯一口径**（`ai.md` §3.2、§3.3、§7 与 `analysis.md` AN-06 直接引用本节，不另写数字）：

| 对象 | 指标 | 门槛（单一口径） | 达标前的状态 | 数据 | 阶段 | 成本（估计） |
| --- | --- | --- | --- | --- | --- | --- |
| `facet.session` 各枚举字段（AI-03） | 与 EV-02 两人标注的 κ（`task_type`、`outcome`、`interaction_pattern`、`friction_types`、`satisfaction_signal`）；JSON Schema 有效率；同一会话重复抽取一致率；打包 vs 单会话一致率（契约 V5）；每会话 token 与费用；缓存命中率 | **字段 κ ≥ 0.6 才默认展示，也才允许 `type_source = facet` 的信号参与 AN-06 计数**；Schema 有效率 ≥ 98%；重复一致率 ≥ 0.9；`failed` 率 < 5% | facet 字段只在 A3 / A6 详情显示为「AI 候选（未校准）」，不进 AN-06、不进 A1-10 与 A7 | EV-02 两人标注集中 50–100 个会话 | MVP（Schema / 幻觉 / 重复一致率 / `failed` 率，0 标注）；v1（κ 与默认展示开关） | 100 会话 × ≤ 5K ≈ 0.5M token（v1） |
| 幻觉率 | AI 输出引用的 `event_uid / signal_id / problem_id` 不存在、`text_redacted` 与原文不匹配、数字不在输入白名单 | **= 0**（校验失败整段丢弃并降级为模板，契约 §3.3；`ai.md` §5.3） | — | 全量 AI 输出（代码校验，无需标注） | MVP | 0 |
| `classify.feedback`（AI-04.1） | 二元 TPR / TNR（是否纠偏）；`feedback_kind` / `friction_type` κ | **κ ≥ 0.6 且 TPR、TNR 都 ≥ 0.8** 才写 `type_source = facet`；否则保留规则结果 `type_source = rule`、`sentiment = null` | 规则结果 | 同上 | v1（随 EV-02 κ） | 单条 ≤ 4K |
| `cluster.failure_names` / `cluster.topic_names`（AI-04.2 / 04.3，EV-04.2） | 名称 lint 通过率（不含路径、人名、文件名）；两簇同名率；`label(inaccurate)` 率；主题簇与 §2.2 人工判定的一致 | lint 100%；同名率 0；`inaccurate` < 10% | 显示「簇 #k」+ top terms | A4 / A6 展示后的 `label` | v1 | ≤ 10K / 批 |
| `narrate.persona`（AI-05.4） | 数字白名单通过率；「不像我」标签率；读者盲评（模板版 vs AI 版，EV-09.1 的 `variants`） | 白名单 100%；「不像我」标签率不高于模板版；盲评 AI 版不劣于模板版才默认展示 | 模板文案库 | `label(not_me)`、`reader-results` | MVP（白名单、标签率）；v1（盲评） | ≤ 6K / 次 |
| `rerank.fit`（AI-12） | EV-05 曝光：`not_applicable` 率按 `fit` 分层；v1 回放比较有 / 无重排的 HitRate@3 | `unfit` 的不适用率显著高于 `fits`，否则关掉重排只留解释 | RC-04 顺序 + 模板解释 | `rec_exposure` + `label` | MVP（分层统计）；v1（HitRate@3） | ≤ 10K / 批 |
| `diagnose.workflow`（AI-10） | 时间切分：`verify.metric` 在后窗按 `direction` 变化的比例；转为建议后的采纳率 | 至少一项正向且无反对才在界面写「有效」 | 不显示 | EV-05 回放（v1） | v1 | ≤ 20K / 次 |
| `judge.rule_counterfactual`、`judge.artifact_review`（AI-07 ④） | 对金标的混淆矩阵、κ；位置偏差（交换顺序后不一致率）；漂移 | κ ≥ 0.6 才启用；不一致率 ≤ 10% | `ai_task.calibrated = false`：AI-07 只显示 lint 与 dry-run | 每个 judge 任务 50–100 条两人一致金标（正例 = 证据会话，反例 = 共享关键词的近似反例） | v1 | 100 × 2 顺序 × ≤ 3K ≈ 0.6M token / 轮（v1） |
| 模型降级 | 同一评测集上换便宜模型，分数不降才采用（契约 §5.1） | Δκ ≥ −0.05 | 保持当前槽位 | 同上 | v1 | 每次降级一轮 |
| 自身 token 账本（EV-11） | 每次 AI 调用写 `ai_usage(job_id, task_id, model_id, engine, usage, cost_usd, ts)`；按 task_id 日 / 周汇总 | 预估与实际偏差 ≤ 30%（AI-11 的「本次约 X token」） | — | 全量 | MVP | 0 |

**judge 校准流程（v1）**（[LLM-as-judge](https://arxiv.org/abs/2306.05685)、[Rogan–Gladen 1978](https://doi.org/10.1093/oxfordjournals.aje.a112510)、[PPI](https://arxiv.org/abs/2301.09633)、[Eugene Yan：product evals](https://eugeneyan.com/writing/product-evals/)）

1. 固定 judge 配置：`model_id`、`prompt_version`、温度、评分细则都带版本；judge 与生成模型不同（契约 `ai_task` 的 `judge` 槽位）。
2. 金标：每个 judge 任务 50–100 条，两人独立标、取一致部分；报告 judge 对金标的混淆矩阵、κ、TPR（= Se）、TNR（= Sp）。
3. 成对比较交换顺序各判一次，不一致记「平」；细则写明「长度不加分」。
4. 用 judge 估比例时校正：`p = (p_judge + Sp − 1) / (Se + Sp − 1)`；区间用 PPI 把少量金标与全量预测结合。
5. 漂移监测：模型或提示词升级后在同一金标上重跑，κ 下降 > 0.1 回滚到上一版本；结果写 `eval_run(suite = judge)`。
6. 未校准或 κ < 0.6 的 judge：`ai_task` 标 `calibrated = false`，相关功能走降级（AI-07 只显示 lint 与 dry-run；AI-04.1 保留规则结果）。MVP 全程处于这个状态，所以 MVP 的生成物门槛不含 judge（§2.5）。

### 2.4 E6 推荐质量（EV-05、EV-05.1、EV-05.2）

MVP 只用曝光反馈与覆盖率；时间切分回放、消融与个性化对比全部 v1（回放要在历史时刻 t 重跑 RC 链路，而闸门 7 / 13 依赖的已装清单没有历史，契约 V7 只能用当前配置近似）。

| 指标 | 定义（输入 → 处理 → 输出） | 门槛 | 阶段 | 现状 |
| --- | --- | --- | --- | --- |
| 采纳率 / 不适用率 / 撤销率 | `rec_exposure(action = open / preview)` 与 `label(target_kind = candidate)`、`install_ledger(action = install / revert)` 按 `remedy_rule_id × surface` 分组；分母 = 该规则被展示的候选数；n < 10 的组只报 n | 不适用率 ≤ 30%（估计，V16）；撤销率只报告；任一 `remedy_rule` 不适用率 > 50% 且 n ≥ 10 → RC-10 规则级降权并进 RC-01 修订清单 | MVP | 计划（RC-10 写 `rec_exposure / label`） |
| 问题覆盖率 | `problem(status = active)` 中至少有一条过闸候选被展示的比例；未覆盖的 `(type, key)` 列表 | MVP 问题类型（`permission_friction`、`tool_env_failure`、`repeated_instruction`、`missing_verification`、`communication_gap`）≥ 0.8；未覆盖项是 RC-01 新条目的输入 | MVP | 计划（AN-06 + RC-02） |
| 解释可信度（机械项） | main `pipeline_eval.evidence_checks` 8 项：`references_valid`、`original_context_preserved`、`cited_profile_supports_match`、`versioned_source_reference_valid`、`deliverable_language_preserved` + 三项消融 `profile / bottleneck / context_ablation_abstains` | 100% 硬门槛；闸门消融由 3 项扩成 MVP 闸门各一项（§3） | MVP（已有） | main `packages/backend/src/orbit_backend/evaluation/pipeline.py` |
| 「候选（未校准）」占比 | 展示候选中主信号类型 `passed = false` 的比例（§2.2 执行点） | 只报告；MVP 路演前 MVP 四类检测器都应 `passed = true` | MVP | 计划 |
| RC-09 资源库匹配 | 「为你推荐」前 3 条的 `label(useful)` 率与「不感兴趣」率；每条 `catalog_match.parts` 能回链到 `matched_features`（`session_feature` 真实存在） | 不感兴趣率 ≤ 30%；回链 100% | v1（随 RC-09） | 计划（PR #29 `packages/catalog` 已有三路检索与 `evals/recommendation/catalog.py` 构造验收） |
| RC-17 个性化 | 同一批历史曝光，开 / 关「用户水平偏置 + 历史不适用降权」各回放一次，比较同 `remedy_rule` 的重复「不适用」率 | 开启后重复不适用率下降，否则关闭降权只留水平闸门 | v1 | 计划 |
| 时间切分回放（EV-05.1） | 用户 ≥ 60 天历史按周切分：在 t 只用 `[t − 28 d, t)` 的数据生成候选，命中 = 候选针对的 `problem(type, key)` 在 `[t, t + 14 d)` 仍 `active`（且无安装）；HitRate@3、NDCG@3 | HitRate@3 ≥ 0.5（估计）；有 / 无 AI-12 重排各算一次（§2.3） | v1 | 计划（已装清单历史 V7） |
| 消融（EV-05.2） | 在回放上逐项去掉 RC-04 打分项（`wilson_lo`、`prior_p`、`setup_minutes`）与每道闸门，看 HitRate@3 与不适用率变化 | 去掉某项后指标不降 → 该项从 MVP 公式移除 | v1 | 计划 |

### 2.5 E3 生成物装前（EV-06、EV-06.1）

MVP 三道机械自检 + 文案层；结果写 `install_plan.risk_scan`（结构见 §13），任一 `passed = false` 时 IN-02 预览不显示「应用」按钮，只显示「查看教程」或退回模板默认值（AI-07 的降级）。judge（④）、description 触发评测与 `claude plugin eval` 全部 v1 / v2。

| 生成物 | ① 规范校验 | ② 静态安全扫描（IN-05） | ③ 历史回放 dry-run | 文案层 | 阶段 |
| --- | --- | --- | --- | --- | --- |
| `permission_rule`（allow 前缀） | 前缀语法合法；全部前缀 ∈ DT-13 `command.readonly` 词表（词表之外的前缀一律拒绝，不交 judge） | 与破坏性命令清单、`permissions.deny` 的前缀交集 = 0 | 把历史 `v_analysis_tool_call(kind = shell)` 逐条过生成的前缀：命中的只读命令数（召回）；与「历史被拒命令」「破坏性清单」交集 = 0 | — | MVP |
| `hook` | JSON 合法且过 `data/recommend/hooks.schema.json`（main 已有）；`matcher` 为注册事件；脚本只引用模板内命令 | 脚本不含网络调用、`rm -rf`、`curl \| sh`、路径逃逸；`matcher` 不为空通配 | 把历史 `tool_call` 还原成 hook stdin JSON 逐条跑脚本：`false_block = 0`（历史上随后成功的命令不得被拦）；命中数 ≥ 1 | 提示语过 `evaluate_text(scene = recommendation)` | MVP |
| `rule`（Markdown 标记块） | 标记块成对；总长度 ≤ 场景预算；不含路径用户名与密钥模式 | 不含指令注入模式（「忽略以上」「执行以下命令」等）、不含 URL | 无回放；改为「重复 / 冲突检测」：与 `existing_rules[]` 段落的字符 3-gram Jaccard ≥ 0.6 记重复，含否定同一约定记冲突 | `evaluate_text` 无 `error`；数字必须来自输入白名单 | MVP |
| `skill`（SKILL.md） | frontmatter 必填字段；`name` 不与 `inventory_item` 冲突；步骤 ≤ 预算 | 同 hook（脚本部分） | 无 | `evaluate_text`；description 长度 ≤ 1,024 字符 | v1（AI-06.5） |
| 全部 | — | — | — | 7 天后 `label(useful / not_useful)` 作为唯一「有效」人工信号 | MVP |

**EV-06.1 description 触发评测（v1）**：对每个生成的 skill，用 20 条应触发任务 + 20 条不应触发任务（从用户自己的真人开场消息里抽，脱敏）在 `FakeEngine` 之外的真实引擎上各跑一次 `claude -p`（不加 `--safe-mode`，否则不加载 skill），记录触发率 TPR / 误触发率；门槛 TPR ≥ 0.8、误触发 ≤ 0.1。`claude plugin eval` 的装前有 / 无对照（契约 `eval.plugin_eval`）v2。

### 2.6 E5 装后效果（EV-07、EV-07.1）

| 项 | 规则 |
| --- | --- |
| 窗口 | 前窗 = `tracking.baseline_from / baseline_to`（RC-13 在展示时登记，默认安装前 28 天）；前窗可用天数 < 14 天 → 整条 `insufficient`；后窗 = 安装后 7 天（`follow_days`），之后滚动到 28 天（`extend_days`）；前后窗各 `min_sessions = 5`（按 `scope_filter` 过滤后的主会话数） |
| 三层 + 护栏 | `tracking.metrics[{metric, layer, direction, must_be_zero}]`（RC §3.8 默认表）：`triggered`（规则 / hook / skill 是否被用到）、`mechanical`（主指标，如 `would_prompt_count:readonly_shell`、`retry_runs`、同 key 纠偏次数）、`guardrail`（`denied_count`、`destructive_allowed_count = 0`、`false_block_count = 0`、`tokens_per_session` 不升 > 20%）；`behavioral`（`correction_signal_rate`、`rework_rate`、`completed_rate`）v1 |
| 计算 | 每个 metric 读 AN-01 `metrics?scope_filter&bucket=day`，前后窗各得 `{value, n}`；比例差用 AN-10 Newcombe 区间，计数用按天分块 bootstrap（v1，MVP 只给 Wilson 两侧区间）；写 `rec_outcome(install_id, window, metric, layer, before, after, lo, hi, n_before, n_after, status ∈ ok / insufficient, confounders)` |
| 四态结论 | `positive`：主指标按 `direction` 改善且区间不含 0，护栏全部通过；`no_change`：区间含 0（文案「暂未看到明显变化」，不回写先验）；`negative`：主指标反向且区间不含 0，或任一 `must_be_zero` 护栏 > 0（`reason = guardrail`，建议撤销）；`insufficient`：任一窗口 n < 5 或前窗 < 14 天。写回 `candidate.effect_status`（§13 增加 `no_change`）；`GET /v1/outcomes/{install_id}` 返回 `rec_outcome[]` + `conclusion` |
| 混杂 | `confounders_watch = [harness_version, model_id, effort_rank, other_installs, project_mix]`：后窗内任一项变化只列出（「期间模型从 X 换到 Y」），不校正、不改结论 |
| 装了从未触发 | `triggered` 层 14 天为 0 → 系统写 `label(target_kind = candidate, label = not_useful, reason = never_triggered)`（RC §3.9 最后一行；§2.7 枚举） |
| 执行时机 | 导入后增量重算，只算 `install_state.state ∈ installed / observing` 的条目；`O(安装数 × 指标数 × 天数)` |
| EV-07.1（v1） | 行为层 DiD：对照 = 同用户未被 `scope_filter` 覆盖的会话（其他项目 / 来源）；按天分块 bootstrap 区间；模型 / 档位候选用 N-of-1 交替试验（按项目 × 周 ABAB，§4.3）；`rec_outcome.control_delta` 才填值 |

### 2.7 E7 可读性与人工反馈（EV-09、EV-09.1、EV-10、EV-10.1）

| 项 | MVP 做法 | 门槛 | 现状 |
| --- | --- | --- | --- |
| EV-09 可读性检查 | 所有进界面的文案（模板与 AI）先过 `evaluate_text(text, scene)`：7 个问题码、6 个场景预算；`error` 级退回模板 | 模板文案库 100% 无 `error`；`benchmark()` 8 条对照保持 | main `evaluation/readability.py`（`readability-v2`）、`POST /v1/evaluation` |
| EV-09.1 读者轮 | `reader_eval.make_pack()`：X / Y 顺序互换、4 维 0–4；MVP 一轮 = 现有 6 个虚构案例 + 每人本机 3 条真实案例（只在本机评、只汇总分数）；`variants` 比较模板版 vs AI 版（AI-05.1） | `acceptance.decision` 由 `genius-FXC` 组织并记录；界面只写「读者已验收（限所列案例）」 | main `evaluation/reader.py`（`reader-pack-v1`） |
| EV-10 标签入口（后端） | `POST /v1/labels {target_kind, target_id, label, reason?}` 写 `label`；MVP 只存这四列 + `labeler = local`、`ts`；`target_kind ∈ candidate / profile / signal / key_moment / facet / narrative / reader_case / problem / session`（§13） | 校验：`target_id` 必须存在；同 `(target_kind, target_id, labeler)` 后写覆盖 | 计划 |
| 原因枚举 | `not_applicable.reason ∈ already_have / dont_understand / wont_change / wrong_diagnosis / never_triggered（仅系统写入）/ other`；选 `wrong_diagnosis` 时后端同时写 `label(target_kind = problem, label = inaccurate, reason = wrong_diagnosis)`（EV-02 的问题级反例）；`not_me.reason ∈ axis_D / axis_P / axis_M / axis_V / too_few_sessions / other`；`inaccurate` 对 `signal / key_moment / facet / narrative` 无需 reason | — | 计划 |
| EV-10.1 界面入口（前端） | 一个反馈组件复用于 A7-10「不适用」（4 + 1 选 1，含「看不懂」）、A2-09「不像我」、A8-07「不感兴趣」、A6-10 / A3-18「不准确」、A1-08「有用 / 没用」；8 秒撤销 toast 保留（`USER-OVERRIDES` 第 7 条） | 每个入口写且只写一条 `label` | Advance Demo 只隐藏不存储；Lite Demo 无入口 |
| 使用者 | RC-10 降权（`not_applicable / snooze / not_useful`）；EV-02 精度（`confirm / inaccurate`）；AN-08「不像我」率；EV-05 采纳率 | — | — |

### 2.8 E1 安装往返与落点契约（EV-13）

安装直接改用户的真实配置，「预览 → 确认 → 撤销」是产品主路径，所以它有自己的评测，与 IN-01 / IN-03 / IN-04 同 owner（`yhyfhgs`）、reviewer `MistyHuang03`。全部在临时 `HOME`（`ORBIT_HOME`、`HOME`、`CODEX_HOME` 都指向 `tmp`）内运行，不碰真实配置。

| 维度 | 取值 |
| --- | --- |
| 夹具（每个 Agent × 每个落点文件） | ① 空文件 / 不存在；② 已有同键（`permissions.allow` 已含一项、`hooks.PreToolUse` 已有别的 matcher、`AGENTS.md` 已有正文）；③ 用户手改（安装后再改同一数组 / 块）；④ 已有 Orbit 标记块（重复安装）；⑤ 非法 JSON / TOML |
| action（RC §8.2 落点表） | `merge_json`（`/permissions/allow`、`/hooks/<Event>`、`~/.claude.json` 的 `mcpServers` 子树）、`append_block`（`AGENTS.md` 标记块 + `CLAUDE.md` 的 `@AGENTS.md` 引用）、`create_file`（`~/.codex/rules/*.rules`、hook 脚本、skill 目录）、`remove_pointer`（减法）、`set_key`（`model`、`model_reasoning_effort`）、`trim_block` |
| 断言 | 预览 diff（IN-02 键级 / 块级）= 实际写入前后差异；撤销后文件 sha256 与安装前一致（③ 除外）；重复安装无变化（`install_ledger` 不新增写入条目）；JSON / TOML 仍合法且未知键原样保留；不写托管层与团队共享层；`preview_digest` 不符时 `POST /v1/install/apply` 返回 409 且文件未变；③ 时自动撤销被拒绝并提示人工处理；⑤ 时拒绝写入并给出原因；Codex hook 写入后 `install_state` 为「已安装、未信任」（`requires_trust`，V19）；写前备份存在且 `install_ledger.before_hash / after_hash / backup_path` 可回放 |
| 规模 | 2 个 Agent × 5 种夹具 × 6 种 action ≈ 60 用例（无对应落点的组合跳过并记 `n/a`），本机 < 10 s |
| 运行 | `orbit evaluate --suite install`，CI 门槛 100%；`--real` 冒烟见 §5.3，只在本机，路演前与落点表变更后各跑一次 |
| 不能说什么 | 「不会影响其他配置」只对 Orbit 写入的键成立；Agent 是否真的读到规则由 `--real` 冒烟回答，不由往返用例回答 |

## 3. EV-03 合成注入与回归集

现状：main `evaluation/pipeline.py`（`pipeline_benchmark`：`_write_case` 构造 Codex JSONL → 独立临时库 → `import_codex / analyze / recommend / explain` → 事后对 `expected`）；`data/pipeline_cases.json` 34 例、`pipeline_probe_cases.json` 12 例；`precision / recall / exact_cases`，分母 0 保持 `null`；`evidence_checks` 8 项 + `source_unchanged`。保留原样，扩展如下。

| 扩展 | 内容 | 用例数 | 期望 | 阶段 |
| --- | --- | --- | --- | --- |
| 检测器注入集 | AN-05 每类 `signal.kind` 一正一反：正例 = 命中规则的最小会话，反例 = 共享关键词但不满足阈值（如同参数失败 2 次、`rm -rf` 命令、带引用的纠偏词）；以 canonical 形态（`tests/fixtures/analysis-input-v1.json` 的 `events / tool_calls` 行）注入，不再只构造 legacy JSONL | MVP：`correction`、`retry_loop`、`would_prompt`、`missing_verification` + main 4 类 = 16 例；v1：其余 10 类 = 20 例 | 正例产出且只产出该 `kind`；反例不产出；会话级计数每类 ≤ 1；上游去重（`retry_loop → runaway_loop → interruption` 只记最上游） | MVP |
| `remedy_rule` 触发用例 | 每条 `data/remedy_rules.yaml` 条目一个能触发它的会话集（≥ 3 会话，Wilson 下界过阈值）+ 一个只差一个条件的反例 | MVP 约 15 × 2 | 正例产出该 `remedy_rule_id` 的候选且 `gates.passed = true`；反例 `gates.passed = false` 并写原因 | MVP |
| 闸门消融 | 每道闸门一项：构造「只有该闸门不通过」的输入，断言候选不展示且 `gates.checks[<name>] = false` | MVP 8 道判定闸门 + 3 项静态字段 = 11 项；v1 补齐 14 道 | 100% | MVP |
| 三张卡端到端 | 只读放行（12 次 `git status` 的会话 → 升级为 problem；含 `rm -rf` 的会话 → 不进白名单）；重复失败熔断（同轮同参数 3 次失败 → `tool_env_failure`，hook 候选在前、skill 在 `alternatives`）；高频纠偏 → 规则（同 key 纠偏 ≥ 2 次且跨 ≥ 3 会话 → `repeated_instruction`，规则候选） | 3 × 2 | 候选 ID、`install_plan.targets` 的 `path / action` 与 §7 一致 | MVP |
| AI 任务回归 | `FakeEngine` 固定响应：facet Schema 有效 / 无效 / 引用不存在三种；生成填槽超出白名单数字一种 | 6 | 无效项被 gate 丢弃并降级，`ai_usage` 仍记账 | MVP（随 AI-02） |

规则：标签后读（`_write_case` 不读 `expected`）；固定种子；`exact_cases` 必须 100%（构造集没有「差不多」）；新用例从 EV-02 的 `inaccurate` 标签回流（本人去身份化后改写）。运行：`orbit evaluate --suite injection`，用例文件 `packages/backend/src/orbit_backend/data/injection_cases.json`（新增，与 `pipeline_cases.json` 同格式 + `fixture_kind ∈ legacy_jsonl / canonical_rows`）。

## 4. Benchmark：模型 × 思考档位（EV-08）

MVP 只是一张读 AN-12 的表，不下结论；公开榜单、任务类型映射与收缩随 RC-08 候选在 v1。

### 4.1 MVP：用户自己的数据

A7「模型与思考」/ Lite「优化建议 › 模型」读 `GET /v1/analytics/metrics?group_by=model_effort&metric=sessions,completed_rate,correction_signal_rate,tokens_per_session,cost_usd`：每行 `model_id × effort_rank`，每个比例带 `n / lo / hi / basis`；`n < 5` 显示「数据不足」；`effort_rank` 为空（DT-07 现状）时退化为按 `model_id` 分组并标「档位未知」；`cost_usd` 无价目表显示「未知」（DT-08 v1）。跨厂商不比档位、跨 harness 不混排（同一行只在同 `source.agent` 内）。

### 4.2 v1：公开来源与先验

| 来源 | 内容 | 获取 | 用途 | 阶段 |
| --- | --- | --- | --- | --- |
| [SWE-bench Verified](https://www.swebench.com/) | 修 bug 类任务的 resolved 率（按 harness） | 手工快照 JSON（随 DT-14 `benchmark_result`） | `task_type ∈ bugfix / feature` 的先验 | v1 |
| [Terminal-Bench](https://www.tbench.ai/) | 终端运维任务 | 手工快照 | `task_type ∈ ops_deploy / config` | v1 |
| [LMArena](https://lmarena.ai/) | 对话 / 前端偏好 Elo | 手工快照 | `task_type ∈ chat / docs` | v1 |
| [models.dev](https://models.dev/) | 模型清单、上下文窗口、价目 | DT-14 自动刷新 | `cost_usd` 折算（DT-08） | v1（随 DT-14） |

先验合并：任务类型（AI-03 facet `task_type`，MVP 没有 → 全部「未知」）→ 相关基准成绩归一到 0–1 作 Beta 先验（m ≈ 10），与用户自己的 `completed_rate` 做 Beta-Binomial 收缩；超过 6 个月的成绩权重减半；只在同厂商内比档位；卡片写明「强模型常被分配给难任务」这一混杂。`P(更好) ≥ 0.8` 才由 RC-08 出候选。

### 4.3 v1：N-of-1 档位交替试验

因果只能靠试验：用户同意后，按项目 × 周 ABAB 交替档位（`install_plan.set_key` 改项目层 `model` / `model_reasoning_effort`），主指标 `completed_rate` 与 `tokens_per_session`，护栏 `correction_signal_rate` 不升；每臂 ≥ 5 个会话；结论走 EV-07 四态。

### 4.4 参数与归属

`group_by ∈ project / model_effort / source` 是 AN-12 的参数名（`analysis.md` §7 AN-01），EV-08 与 RC-08 都只读它，不另起 `group=model_effort_task`；RC-08 的「MVP 分层描述」以 AN-12 为唯一来源，EV-08 只负责渲染口径与 v1 的先验合并。

## 5. 运行方式与门槛

### 5.1 套件

| suite | 内容 | 门槛 | 阶段 | 现状 |
| --- | --- | --- | --- | --- |
| `readability` | `benchmark()` 8 条对照 | 100% | MVP | 已有 |
| `pipeline` / `probe` | 34 + 12 构造案例（probe 补一个 pytest 守住） | `exact_cases` 100% | MVP | 已有（probe 无测试） |
| `injection` | §3 的检测器注入、`remedy_rule` 触发、闸门消融、三张卡、AI 回归 | 100% | MVP | 计划 |
| `install` | EV-13 夹具 × action 往返（§2.8） | 100% | MVP | 计划 |
| `metrics` | EV-01.2 指标金标与统计函数对照 | 100%（误差 < 1e-6） | MVP | 计划 |
| `privacy` | EV-14 上下文包隐私夹具 | 命中 = 0 | MVP | 计划 |
| `detector` / `facet` / `judge` / `rec_replay` / `artifact` / `outcome` | §2.2 标注汇总、§2.3 κ 与 judge、§2.4 回放、§2.5 生成物批量、§2.6 四态（在线由 EV-07 算，suite 只做回归） | 见各节 | v1 | 计划 |

### 5.2 退出码、产物与 CI（EV-12）

- 命令：`orbit evaluate [--suite <s>] [--fail-under <suite>=<阈值> …]`；任一 suite 低于阈值退出码 1，否则 0；现状 `cli/commands.py` 直接 `return`，没有退出码。
- 产物：每次运行写 `.local/evaluation/<suite>-<ran_at>.json`（含 `component_version`、`dataset_sha256`、`n`、`value`、`passed`）；现有 `.local/evaluation.json` 三段格式保留为汇总；`eval_run` 表、`data/eval_baseline.json` 棘轮、`GET /v1/evaluation/runs` 与设置页评测状态卡全部 v1。
- CI：`scripts/check.sh`（`pnpm check`）加一行 `uv run orbit evaluate --fail-under readability=1 pipeline=1 probe=1 injection=1 install=1 metrics=1 privacy=1`；真实数据 suite 不进 CI。
- 真实数据评测：只在本机，固定 `until_ts`，产物只写 `.local/`，`--real` 参数显式给路径（`evals/README.md` 已是这个约定）。

### 5.3 本机 `--real` 冒烟（EV-13 的一部分）

`orbit evaluate --suite install --real`：在临时 `HOME` 内安装三张卡的产物，然后以非 `--safe-mode` 的 `claude -p` / `codex exec`（临时 `HOME`、临时 cwd、`--max-budget-usd 0.02`）问「读到的规则第一行是什么 / `git status` 是否需要审批」，断言回答含 Orbit 标记块首行、allow 前缀生效（V21）；只读现有配置与 Agent 输出，不写用户配置。每次约 3K token。

### 5.4 路演前清单（MVP）

| # | 检查 | 通过标准 |
| --- | --- | --- |
| 1 | `orbit evaluate --fail-under` 七个 MVP suite | 全绿，退出码 0 |
| 2 | 三人本机 `orbit label` 汇总（EV-02） | MVP 四类检测器各 n ≥ 30（不足取全部）且 P ≥ 0.7；`problem` 前 20 条精确率 ≥ 0.8 |
| 3 | 三张卡端到端（EV-13 + §7） | 每人本机：预览 → 确认 → 撤销后 sha256 一致；`--real` 冒烟通过 |
| 4 | 装后四态（EV-07） | 至少一条真实安装显示 `positive / no_change / negative / insufficient` 之一且区间与 n 正确 |
| 5 | 读者轮（EV-09.1） | 6 + 9 案例有 `acceptance.decision` |
| 6 | AI 账本（EV-11） | facet 回填的预估 vs 实际偏差 ≤ 30%；幻觉率 = 0 |
| 7 | `/insights` 对照（EV-01.1） | 差异逐项有解释，写进 PR 正文 |
| 8 | canonical 接入（V4、V11） | 100–300 MB 库全部指标 ≤ 5 s；`human_origin` 覆盖 ≥ 50% |

去掉的项：judge κ、facet κ、「至少 3 类信号 κ ≥ 0.6」（全部 v1）。

## 6. MVP 与迭代

| 阶段 | 内容 |
| --- | --- |
| MVP | EV-12（`--fail-under` + JSON + 接回 `pnpm check`）；EV-03 扩展（16 例注入、15 × 2 触发、11 项消融、三张卡、AI 回归）；EV-13 安装往返 + `--real` 冒烟；EV-01.2 指标金标（Lite 约 20 项 + Wilson）；EV-01 汇总 + EV-01.1 一次性 `/insights` 对照；EV-02 精度版（每人每检测器 30 条，`orbit label` CLI，只存四列）；EV-04.1 的 Schema / 幻觉 / 重复一致 / `failed` 率（0 标注）；EV-05 曝光统计 + 覆盖率；EV-06 ①②③ + `evaluate_text`；EV-07 触发 + 机械 + 护栏 + 四态；EV-08 读 AN-12 表；EV-09（已有）、EV-09.1 一轮、EV-10 后端 + EV-10.1 组件；EV-11 账本；EV-14 隐私夹具 |
| v1 | κ、交叉标注、A3 标注模式、`label.payload`、`label-set-v1` 冻结；judge 金标与校准（EV-04）；facet / AI-04.1 κ 开关；簇命名评测（EV-04.2）；时间切分回放与消融（EV-05.1 / 05.2）、RC-09 / RC-17 评测；description 触发评测（EV-06.1）、skill 自检；行为层 DiD、bootstrap、N-of-1（EV-07.1）；公开榜单与先验（EV-08 v1）；`eval_run`、棘轮、runs 端点、状态卡；其余 6 个 suite；ccusage / `cost-state` 对账；主题簇与 `installed_unused` 标注 |
| v2 | `claude plugin eval` 装前有 / 无对照；AI 推断时刻回放；跨 Agent 落点差异评测；读者轮扩展到外部读者 |
| 先不做 | 跨用户常模与「与全体用户比」；在线 bandit 评测；用模型自报置信度作概率；0–100 满意度分；把合成注入集的通过率说成「真实准确率」 |

## 7. 三张安装闭环卡的 EV 段（契约 §4.1 第 5 段）

三张卡的九段全文只写一份，放 `docs/archive/plans/feature-map.md`；本节是 EV 负责的第 5 段，其他段分别在 `analysis.md`（第 2 段）、`recommendation.md` §12（第 3 / 6 段）、`ai.md` §9（第 4 段）。

| 卡 | 装前（E3） | 回归用例（E1 / E3） | 装后（E5） | 通过标准 |
| --- | --- | --- | --- | --- |
| 只读命令自动放行（`readonly-allowlist`，`permission_rule`） | ① 前缀 ∈ `command.readonly` 词表；② 与破坏性清单 / `deny` 交集 = 0；③ 历史 shell 调用回放：召回只读命令数，交集 = 0 | `injection`：12 次 `git status` → problem；`rm -rf` 会话 → 不进白名单；`install`：`merge_json` 到 `/permissions/allow` 的往返（空文件 / 已有同前缀 / 用户手改数组）；E1：`would_prompt_count` 与 `/insights bash_would_prompt_count` 对照 | `triggered = allow_rule_matches`；`mechanical = would_prompt_count:readonly_shell ↓`；护栏 `denied_count` 不升、`destructive_allowed_count = 0` | 装前 100%；装后四态之一；护栏触发即 `negative` |
| 重复失败熔断（`retry-breaker`，`hook`；`systematic-debugging` skill 在 `alternatives`） | ① 过 `hooks.schema.json`；② 脚本无网络 / 破坏命令；③ 历史 `tool_call` 还原为 stdin 回放：`false_block = 0`、命中 ≥ 1 | `injection`：同轮同参数 3 次失败 → `tool_env_failure:retry_loop:<command_head>`；候选来源 RC-02 ① `skills.json` 种子（`problem_types = repeated_tool_failure`）；RC-06 #2 首选 `hook`，skill 作 `alternatives`（RC §3.1 `tool_env_failure` 优先序）；`install`：`merge_json` 到 `/hooks/PreToolUse` + 脚本文件；Codex `hooks.json` 写入后状态「已安装、未信任」（V19） | `triggered = hook.run`；`mechanical = retry_runs ↓`；护栏 `false_block_count = 0`、`interruption_count` 不升 | 同上 |
| 高频纠偏 → 规则（`repeated_instruction:<key>`，`rule`） | ① 标记块成对、长度 ≤ 预算；② 无注入模式；重复 / 冲突检测对 `existing_rules`；`evaluate_text` 无 `error` | `injection`：同 key 纠偏 ≥ 2 次 × ≥ 3 会话 → `repeated_instruction` → 规则候选；`install`：`append_block` 到 `AGENTS.md` + `CLAUDE.md` 的 `@AGENTS.md` 引用（RC §8.2）往返（已有 Orbit 块 / 用户改过块 → 拒绝自动撤销） | `triggered = context.inject`（可观测时，否则「未测」）；`mechanical` = 同 key 纠偏次数 ↓；护栏 `tokens_per_session` 不升 > 20% | 同上；`triggered` 不可观测时结论只能是 `no_change / insufficient`，不写 `positive` |

## 8. 与 Demo 的对应

### 8.1 Advance（`prototypes/advance/src`，条目 ID 见 [`feature-map.md`](feature-map.md) §5）

| Demo 条目 | Demo 现状 | 真实实现（EV） | 阶段 |
| --- | --- | --- | --- |
| A7-15 效果追踪 Tab | 7 天后恒「有效」、改善百分比 | EV-07 四态 + 区间 + 护栏行 + 混杂列表（= UG-RC-04，前端只做一次） | MVP |
| A7-10 不适用 + 撤销 | 隐藏不存储、不问原因 | EV-10 / EV-10.1：5 + 1 选 1 原因写 `label`；RC-10 降权 | MVP |
| A2-09 不像我 | 4 原因、不存储 | `label(not_me, reason = axis_*)`；AN-08 「不像我」率 | MVP |
| A8-07 不感兴趣 | 从数组删 | `label(target_kind = candidate, not_useful)`；RC-09 评测输入（v1） | MVP（写入）；v1（评测） |
| A6-10 / A3-18 不准确 | toast | `label(inaccurate)` 对 `signal / key_moment / narrative` → EV-02 精度 | MVP |
| A1-08 重新生成 | 随机 3 条文案，无反馈 | 有用 / 没用 → `label(target_kind = narrative)`；`ai_usage` 记账（EV-11） | MVP |
| A1-09 / A1-10 做得好 / 卡在哪 | `stats` 常数 | `problem` 精确率 ≥ 0.8 才进 A1-10（§2.2） | MVP |
| A6-07 / A6-08 纠偏柱 / 摩擦分类 | 每会话一类、静态 | 一律「候选」+ `type_source` 标记；`passed = false` 的类型标「未校准」 | MVP |
| A4-12 失败原因聚类 | 静态 6 类 | MVP 按 `error_class` 分组；簇命名评测 = AI-04.2 的 lint / 同名率 / `inaccurate` 率（EV-04.2，v1），不是 EV-04 judge | MVP（分组）；v1（命名） |
| A3-17 关键时刻 | 手写精选 | 规则时刻精确率 ≥ 0.8 才实心；AI 时刻 v1 | MVP |
| A9-15 自检清单 | 永远通过 | EV-06 ①②③ 可失败并阻止安装（= UG-AI-04）；judge 项 v1 | v1（随 A9 工坊） |
| A9-16 安装产物 | 不进追踪 | 安装即登记 `tracking`（RC-13）并进 EV-07 | v1（随 A9） |
| INST-06 / INST-07 写入 / 撤销 | localStorage | EV-13 往返断言；撤销 toast 倒计时保留 | MVP |
| A7-01 页头 | 时间写死 | `batch_id` 与重算时间；EV-05 按 `batch_id` 分组 | MVP |
| SET-18 分析引擎 | 下拉无效果 | `GET /v1/ai/capabilities` + EV-11 账本汇总显示 | MVP |
| SET-19 人格规则 | 静态文案 | 单位与门槛（`n_units ≥ 30 ∧ 活跃天 ≥ 10`）从 AN-08 读 | MVP |
| 设置页评测状态卡 | 无 | `GET /v1/evaluation/runs` 摘要 | v1 |

### 8.2 Lite（`prototypes/lite/orbit-benchmark-demo.html`，8 页）

| 页 | Demo 现状 | EV 对应 |
| --- | --- | --- |
| 概览 | 本周建议固定三条 | EV-05 覆盖率；「候选（未校准）」不进本周建议 |
| 协作画像 | 示例算法、无反馈 | A2「不像我」→ `label`（EV-10.1）；整页标「实验性」 |
| 会话与轨迹 | 任务节点手写 | 规则时刻精确率门槛（EV-02） |
| 工具调用 | 失败原因固定样例 | 按 `error_class` 分组；命名 v1 |
| 项目分析 | 完成度示例公式 | AN-19 `user_acceptance` 准确率 ≥ 0.8 才显示完成度（EV-02） |
| 情绪与语义 | 纠偏类型占比示例 | 一律「候选」+ 精度与 n |
| 优化建议 | 模拟安装 / 撤销只改浏览器存储；「预期效果」写死 | EV-13 真实往返；效果列改为「未测」或 EV-07 四态 |
| 资源库 | 匹配度示例 | RC-09 评测（v1）；MVP 只显示「示例匹配」或隐藏匹配度 |

## 9. Demo 还缺什么（EV 侧；合并到 `docs/archive/plans/feature-map.md` 前端升级表时按下表去重）

| ID | 页面 | 改什么 | 为什么 | 依赖后端 | 优先级 | 复杂度 | 去重说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| UG-EV-01 | A7 效果追踪 Tab / Lite 优化建议「预期效果」 | 前窗 28 天 / 后窗 7 天时间轴；每项 `before / after / n / lo / hi`；四态结论句；护栏行；混杂列表；撤销 / 保留按钮按结论启用；未安装显示「未测」 | 恒「有效」与 METR 反例冲突；追踪是产品核心差异 | EV-07、RC-13、`GET /v1/outcomes/{install_id}` | P0 | M | = UG-RC-04，前端只做一次 |
| UG-EV-02 | A7-10、A2-09、A8-07、A6-10、A3-18、A1-08 | 一个反馈组件：不适用（5 + 1 原因）、不像我（轴）、不感兴趣、不准确、有用 / 没用；都写 `POST /v1/labels`；8 秒撤销 toast 保留 | 这是 MVP 唯一的人工标签通道（EV-02 精度、RC-10 降权、AN-08 不像我率都读它） | EV-10、EV-10.1、RC-10 | P1 | S | 合并 UG-RC-06 / UG-AI-07；原因枚举以 §2.7 为准 |
| UG-EV-03 | 全站卡片主数字 | `basis` 角标：已计数 / 估计 / 未测 / 数据不足；`effect_status` 与 `human_acceptance = pending` 的文案映射 | 契约 §0.5 的措辞规则在 Demo 里没有落点 | AN-01 `basis`、RC-04、EV-07 | P0 | S | = UG-01（analysis）/ UG-RC-01 的 `basis` 部分，前端只做一次 |
| UG-EV-04 | A9-15 自检清单 | 五项可失败：规范、冲突、危险命令、回放 `false_block`、`evaluate_text`；失败项展开原因并禁用「安装」；judge 项标「v1」 | 现在永远通过，无法阻止坏产物进入安装 | EV-06、AI-07、IN-05 | P2 | S | = UG-AI-04；随 A9 工坊 v1 |
| UG-EV-05 | 设置 › 分析 | 评测状态卡：最近一次 `orbit evaluate` 各 suite 通过 / 失败、`component_version`、本机标注进度（每检测器 n / 30） | 用户与成员都能看到「这台机器上的分析校准到什么程度」 | EV-12（v1 `eval_run` / runs 端点）、EV-02 | P2 | S | 新增；MVP 用 CLI 输出代替 |
| UG-EV-06 | A3 会话详情 | 标注模式：对当前会话的信号 / 时刻逐条 `confirm / inaccurate / skip`，键盘 `c / i / s` | 比 CLI 直观，可带上下文看证据 | EV-02.1、EV-10 | P2 | M | v1；MVP 只用 `orbit label` CLI |

## 10. 功能清单

| ID | 名称 | 说明 | 输入 | 输出 | 依赖 | 阶段 | 现状 | 负责人 | reviewer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EV-01 | 数据层回归汇总 | 汇总 main / PR #9 / #14 / #11 的回归与全记账恒等式，不另起框架；跨包汇总断言 | 各包测试与 `verify()` 输出 | `--fail-under` 汇总项 | DT-04、DT-19 | MVP | main `packages/backend/tests`、`packages/data/tests`、`packages/connectors` 35 项 + CI | yhyfhgs | MistyHuang03 |
| EV-01.1 | `/insights` 只读对照 | Claude Code `session-meta` 的工具数 / 打断数 / `bash_would_prompt_count` 与 Orbit 同会话数值对照，一次性 | `~/.claude/usage-data/session-meta`（DT-18） | `.local/evaluation/insights-<ran_at>.json` + PR 正文 | DT-18、AN-05 `would_prompt` | MVP（一次性）；v1（ccusage / `cost-state` 对账） | 计划 | yhyfhgs | MistyHuang03 |
| EV-01.2 | 指标引擎金标 | 约 30 个构造会话的 `metrics` 手算期望；统计函数对照 scipy / statsmodels；字典覆盖；Demo 数字 → 端点映射检查 | canonical 夹具、`metrics` 端点、`analytics/stats.py` | `tests/fixtures/metrics-gold-v1.json`、`--suite metrics` | AN-01、AN-10、AN-12、AN-14、AN-16 | MVP（Lite 约 20 项 + Wilson）；v1（全部） | 计划（`analytics` 测试只验夹具形状） | MistyHuang03 | yhyfhgs |
| EV-02 | 分析准确性标注 | §2.2：每人对 MVP 检测器各 30 条命中 `confirm / inaccurate`，`problem` 前 20 条，规则时刻各 20 条；精度与 n；执行点 = 检测器摘要文件 | `signal / problem / key_moment`、`label` | `.local/evaluation/detector-summary.json`、PR 正文汇总 | AN-05、AN-06、AN-09、AN-11、AN-18、AN-19、EV-10、EV-02.1 | MVP（精度）；v1（κ、交叉标注、主题簇、`installed_unused`、阶段、情绪） | 计划；构造集 main `pipeline_cases.json`、`tests/fixtures/*-quality*.json`、`tests/bottleneck/` | MistyHuang03 | yhyfhgs |
| EV-02.1 | `orbit label` CLI | 终端逐条显示 L2 脱敏文本与命中位置，`c / i / s` 写本机 `label` | `analysis.db`、`orbit.db`（只读） | `label` 行 | EV-10 | MVP | 计划 | MistyHuang03 | genius-FXC |
| EV-03 | 合成注入与回归集 | §3：检测器一正一反、`remedy_rule` 触发、闸门消融、三张卡、AI 回归；`exact_cases` 100% | 夹具 + 用例 JSON | `--suite injection / pipeline / probe` | AN-05、AN-06、RC-01、RC-03、AI-02 | MVP | main `evaluation/pipeline.py`（34 + 12 例、`evidence_checks` 8 项） | MistyHuang03 | yhyfhgs |
| EV-04 | judge 校准 | §2.3 流程：金标 50–100 条、成对交换、Rogan–Gladen、漂移 | judge 输出、金标 | `calibrated` 标记、`eval_run(suite = judge)` | AI-07 ④、EV-02 κ | v1 | 计划 | MistyHuang03 | yhyfhgs |
| EV-04.1 | facet 与 AI-04.1 质量 | Schema 有效率、幻觉率 = 0、重复一致率、`failed` 率（MVP）；κ 与默认展示开关（v1） | `session_facet`、`label` | 门槛结果 → `type_source` / 展示开关 | AI-03、AI-04.1、EV-02 | MVP（0 标注项）；v1（κ） | 计划 | MistyHuang03 | yhyfhgs |
| EV-04.2 | 簇命名评测 | AI-04.2 / 04.3 名称 lint、同名率、`inaccurate` 率、与主题簇人工判定一致 | 簇名、`label` | 门槛结果 | AI-04、AN-18 | v1 | 计划 | MistyHuang03 | genius-FXC |
| EV-05 | 曝光评估 | 采纳 / 不适用 / 撤销率按 `remedy_rule × surface`；问题覆盖率；「未校准」占比 | `rec_exposure`、`label`、`install_ledger`、`problem` | 汇总 JSON、RC-01 修订清单 | RC-10、AN-06 | MVP | 计划 | MistyHuang03 | genius-FXC |
| EV-05.1 | 时间切分回放 | HitRate@3 / NDCG@3；有 / 无 AI-12 重排 | ≥ 60 天历史 | `eval_run(suite = rec_replay)` | RC-02…RC-05、AI-12 | v1 | 计划（V7） | MistyHuang03 | yhyfhgs |
| EV-05.2 | 打分与闸门消融、RC-09 / RC-17 评测 | 回放上逐项消融；资源库前 3 有用率；个性化开 / 关对比 | 回放结果、`catalog_match`、`label` | 公式修订输入 | EV-05.1、RC-09、RC-17 | v1 | 计划 | MistyHuang03 | genius-FXC |
| EV-06 | 生成物装前评测 | §2.5 ①②③ + `evaluate_text`；写 `install_plan.risk_scan`；失败即阻止安装 | 生成物、历史 `tool_call`、DT-13 词表、`existing_rules` | `risk_scan`、`--suite artifact`（v1） | AI-06、AI-07、IN-05、DT-13 | MVP（规则 / 白名单 / hook）；v1（skill、judge） | 计划；`hooks.schema.json` 等三份 Schema 已在 main `data/recommend/` | MistyHuang03 | yhyfhgs |
| EV-06.1 | description 触发评测 | 20 正 + 20 反真实引擎触发率 | skill、脱敏开场消息 | TPR / 误触发率 | EV-06、AI-01 | v1；`claude plugin eval` v2 | 计划 | MistyHuang03 | genius-FXC |
| EV-07 | 装后效果 | §2.6：前窗 = `tracking.baseline`（默认 28 天，< 14 天 `insufficient`）、后窗 7 → 28 天；触发 / 机械 / 护栏 + 四态；`never_triggered` 系统标签 | `tracking`、AN-01 `metrics`、`install_state` | `rec_outcome`、`candidate.effect_status`、`GET /v1/outcomes/{install_id}` | RC-13、AN-01、AN-10、AN-12、IN-04 | MVP | 计划（`effect_status = unmeasured` 占位） | MistyHuang03 | yhyfhgs |
| EV-07.1 | 行为层与因果 | DiD（对照 = 未覆盖会话）、按天分块 bootstrap、N-of-1 档位交替 | 同上 + AN-19 | `rec_outcome.control_delta` | EV-07、AN-10、AN-19 | v1 | 计划（V8） | MistyHuang03 | yhyfhgs |
| EV-08 | 模型 × 档位 | MVP：读 AN-12 `group_by=model_effort` 按 n / 区间渲染，不下结论；v1：公开来源快照、任务类型映射、Beta 收缩、N-of-1 | `metrics`、`benchmark_result`（v1）、facet `task_type`（v1） | A7 / Lite 模型表；RC-08 先验（v1） | AN-12、AN-19、DT-07、DT-14（v1）、AI-03（v1） | MVP（表）；v1（先验） | 计划 | MistyHuang03 | genius-FXC |
| EV-09 | 可读性检查 | `readability-v2`：7 问题码、6 预算；所有文案进界面前调用 | 文案、场景 | `evaluate_text()` 结果、`POST /v1/evaluation` | — | MVP（已实现） | main `evaluation/readability.py` | MistyHuang03 | genius-FXC |
| EV-09.1 | 读者轮 | `reader-pack-v1` X / Y；6 虚构 + 每人 3 真实；模板版 vs AI 版 | `reader_cases.json`、本机案例 | `ratings-{X,Y}.json`、`acceptance.decision` | EV-09、AI-05.1 | MVP（一轮） | main `evaluation/reader.py`；真实读者轮计划 | genius-FXC | MistyHuang03 |
| EV-10 | 标签入口（后端） | `POST /v1/labels`；`label` 四列；`target_kind` 含 `problem / session`；原因枚举；`wrong_diagnosis` 联动写 problem 标签 | 前端反馈、系统写入 | `label` 表 | — | MVP | 计划 | MistyHuang03 | yhyfhgs |
| EV-10.1 | 反馈组件（界面） | A7-10 / A2-09 / A8-07 / A6-10 / A3-18 / A1-08 共用一个组件；8 秒撤销 | `POST /v1/labels` | 界面 | EV-10 | MVP | Advance Demo 只隐藏；Lite 无 | genius-FXC | MistyHuang03 |
| EV-11 | 自身 token 账本 | 每次 AI 调用写 `ai_usage`；按 task_id 日 / 周汇总；预估偏差 ≤ 30%（本表是 EV-11 的唯一清单行，`ai.md` §8 引用此处） | `ai_response.usage / cost_usd` | `ai_usage`、SET-18 汇总 | AI-01、AI-02 | MVP | 计划 | MistyHuang03 | yhyfhgs |
| EV-12 | 评测运行方式 | `orbit evaluate --fail-under`、JSON 产物、接回 `pnpm check`；probe 测试 | 各 suite | 退出码、`.local/evaluation/*.json` | — | MVP；v1（`eval_run`、棘轮、runs 端点、状态卡） | main `cli/commands.py evaluate`（无退出码；CI 未调用） | MistyHuang03 | yhyfhgs |
| EV-13 | 安装往返与落点契约 | §2.8：临时 `HOME` 夹具（空 / 同键 / 用户手改 / 已有标记块 / 非法 JSON）× action（`merge_json / append_block / create_file / remove_pointer / set_key / trim_block`）；断言预览 diff = 写入差异、撤销 sha256 一致、幂等、未知键保留、不写托管层、`preview_digest` 不符拒绝、用户改过标记块拒绝自动撤销、Codex hook「已安装、未信任」、`@AGENTS.md` 与 `~/.claude.json` 子树；`--real` 冒烟 | `install_plan`、IN-01 落点表 | `--suite install`、冒烟记录 | IN-01、IN-02、IN-03、IN-04、RC-12 | MVP | 计划 | yhyfhgs | MistyHuang03 |
| EV-14 | AI 上下文包隐私 | 构造含密钥、路径用户名、工具输出全文、`reasoning`、`ext` 的会话；断言 `POST /v1/ai/preview` 包内命中 = 0、取消勾选的项不出现在 `FakeEngine` 收到的请求里、`raw_snippets` 默认关 | 隐私夹具、AI-08 | `--suite privacy` | AI-08、DT-10、AI-01（`FakeEngine`） | MVP | 计划 | MistyHuang03 | yhyfhgs |

## 11. 复杂度与 token 成本

| 项 | 计算复杂度 / 人力 | 运行时机 | token（MVP） | token（v1） |
| --- | --- | --- | --- | --- |
| EV-01 / EV-01.2 / EV-03 / EV-13 / EV-14 | CI 每次 PR 秒级；金标与夹具一次性人力约 2 人日（金标 30 会话 × 20 指标手算是主要工作） | 每次 PR | 0（`FakeEngine`） | 0 |
| EV-02 | 每人每检测器 30 条 × 4 类 ≈ 1 小时 / 人；`problem` 20 条、时刻 20 条再 0.5 小时 | 路演前一次，之后每月 | 0 | κ 交叉标注 30 条 / 人 + 20 条合成校准 |
| EV-04.1 | 复用 facet 回填结果，0 额外调用 | 回填后 | 0 | facet κ：100 会话 × ≤ 5K ≈ 0.5M |
| EV-04 judge | — | — | 0 | 每 judge 任务 100 × 2 顺序 × ≤ 3K ≈ 0.6M / 轮；降级评测每次一轮 |
| EV-05 | `O(曝光数)`，导入后增量 | 导入后 | 0 | 回放：每周切点重跑 RC 链路，`O(周数 × 候选数)`，0 token（AI-12 重排另计 ≤ 10K / 批） |
| EV-06 | allow / hook 回放 `O(历史 shell 调用数)`，本机 ≤ 1 s | 生成后、预览前 | 0 | 触发评测 40 × 2 轮 × ≈ 1.5K ≈ 0.12M / skill |
| EV-07 | `O(安装数 × 指标数 × 天数)` | 导入后增量 | 0 | bootstrap B = 1000，秒级 |
| EV-08 | 一次 `metrics` 查询 | 打开页面 | 0 | 公开快照手工维护 |
| EV-09 / EV-09.1 | `evaluate_text` 微秒级；读者轮每人约 30 分钟 | 文案进界面前；路演前一轮 | 0（模板）；AI 版文案由 AI-05 计 | 同左 |
| EV-11 | 一行写入 / 次 | 每次 AI 调用 | 0 | 0 |
| §5.3 `--real` 冒烟 | 两次 headless 调用 | 路演前、落点表变更后 | ≈ 3K / 次 | 同左 |

MVP 评测总 token ≈ 0 + 冒烟 3K；v1 的大头是 facet κ（0.5M）与 judge 校准（0.6M / 轮）。

## 12. 待验证（只引契约 §7 编号；本文新增的以 V16–V21 作为第 3 版输入，见 §13）

| 契约 # | 本文用处 | 阻塞 MVP |
| --- | --- | --- |
| V1 | `problem` 精确率 ≥ 0.8 的前 20 条抽检（§2.2）就是 V1 的验证方式 | 是（RC 的输入） |
| V3 | `correction` 词表精度 ≥ 0.5 是词表可用线；进入推荐的门槛是 P ≥ 0.7（§2.2），不达标时该类型标「候选（未校准）」而不是停用 | 否 |
| V4 | §5.4 第 8 项：100–300 MB 库全部指标 ≤ 5 s | 是 |
| V7 | EV-05.1 回放只能用当前已装清单近似 → v1 | 否 |
| V8 | EV-07.1 DiD 区间宽度（前后各 ≥ 5 会话） | 否 |
| V11 | `human_origin` 覆盖 ≥ 50%，否则语义类指标全部「数据不足」 | 是 |
| V12 | Codex 侧无 `permission.request` → `would_prompt` 只能按词表估计；EV-01.1 对照只对 Claude Code 成立 | 是（只读放行卡） |
| V16（新） | 不适用率 ≤ 30% 的规则级降权阈值（§2.4） | 否 |
| V17（新） | 前后窗各 5 个会话时 Newcombe 区间多数能分出 `positive / no_change` | 否 |
| V18（新） | canonical 形态注入（`fixture_kind = canonical_rows`）能否复用 `pipeline_benchmark` 的临时库流程，还是要经 `orbit-data` 导入 | 否（先用 legacy JSONL） |
| V19（新） | Codex `hooks.json` 写入后「已安装、未信任」能否只读探测（EV-13 `--real`） | 否 |
| V20（新） | `~/.claude/usage-data/session-meta` 字段在 Claude Code 版本间是否稳定（DT-18） | 否 |
| V21（新） | 非 `--safe-mode` 的 `claude -p` 在临时 `HOME` + 临时 cwd 下是否只读到夹具里的 `CLAUDE.md`（冒烟判定方法） | 否 |

## 13. 并入契约第 3 版的条目（EV 侧）

| # | 位置 | 条目 |
| --- | --- | --- |
| E1 | §2.6 EV 表 | 按本文 §10 重写：EV-02「MVP 精度版（每人每检测器 30 条），κ v1」；EV-04 v1；EV-05「MVP 曝光 + 覆盖率」；EV-06「MVP（①②③ dry-run）、v1（judge、触发评测）、v2（plugin eval）」；EV-07「前窗 = `tracking.baseline`（默认 28 天）」；EV-08「MVP 读 AN-12 表，v1 公开来源」；新增 EV-12、EV-13、EV-14 与子 ID EV-01.1 / 01.2 / 02.1 / 04.1 / 04.2 / 05.1 / 05.2 / 06.1 / 07.1 / 09.1 / 10.1 |
| E2 | §3.4 `label` | `target_kind` 增加 `problem`、`session`；`reason` 枚举：`not_applicable → already_have / dont_understand / wont_change / wrong_diagnosis / never_triggered（系统）/ other`，`not_me → axis_D / axis_P / axis_M / axis_V / too_few_sessions / other`；MVP 必填列只有 `target_kind / target_id / label`（`reason` 可选），`payload` v1 |
| E3 | §3.4 `candidate.effect_status` | 增加 `no_change`（区间含 0）；`rec_outcome` 增加 `conclusion ∈ positive / no_change / negative / insufficient` 与 `reason`（`guardrail`）；不用 `neutral` / `guardrail_hit`（与 RC §3.8 统一） |
| E4 | §3.4 `install_plan.risk_scan` | 结构 `{"lint": {"passed", "issues"}, "scan": {"passed", "flags"}, "dryrun": {"passed", "recall", "false_block", "intersections"}, "text": {"score", "errors"}, "passed"}`；`passed = false` 时 IN-02 不出「应用」 |
| E5 | §3.7 | `eval_run` 表 v1；MVP 产物为 `.local/evaluation/<suite>-<ran_at>.json`；suite 枚举增加 `injection / install / metrics / privacy`；通过标准改为「E1 / E3 / 安装 100%；E2 MVP 精度 P ≥ 0.7（进入推荐）与 `problem` ≥ 0.8；judge v1」 |
| E6 | §3.2b `signal.friction_type` | 与 PR #19 `interaction.FRICTIONS` 的映射：`understanding ← misunderstood_request / wrong_approach`；`scope ← excessive_changes`；`execution ← buggy_output / tool_env_failure / context_loss / parallel_conflict / quota_interrupt`；`verification ← missing_verification`（RC §16 C2 新增 type）；`permission_friction / process_overhead / other` 不映射（4 类里没有）。粗类只作 PR #19 输入，`signal` 表存细类；人工 / AI 确认一律写 `label(target_kind = signal)`（`analysis.md` §11 C8） |
| E7 | §5.3 | `POST /v1/labels` 请求体与校验；`GET /v1/outcomes/{install_id}` 返回 `rec_outcome[] + conclusion`；`GET /v1/evaluation/runs` 标 v1 |
| E8 | §6 owner 表 | EV-01、EV-01.1、EV-13：`yhyfhgs` / `MistyHuang03`；EV-02…EV-08、EV-11、EV-12、EV-14：`MistyHuang03` / `yhyfhgs`（EV-02.1、EV-04.2、EV-05、EV-05.2、EV-06.1、EV-08、EV-09 的 reviewer 为 `genius-FXC`）；EV-09.1、EV-10.1 单独成行：`genius-FXC` / `MistyHuang03`；负责人直接写定，不再保留悬置表述 |
| E9 | §7 | 增加 V16–V21（§12） |
| E10 | §0.1、§0.7、§2.2 DT-05、EV-01、§3.7 | 现状修正：PR #9 `KINDS` 26 种、PR #11 25 种；PR #11 35 项回归；PR #14 `migrations/001–004.sql`、`user_version = 4`（评审稿写 3，按分支 `004.sql` 的 `PRAGMA user_version=4` 为准）；main 测试 658 项（PR #28 后）；目录按 `docs/archive/migrations/structure-migration.md` |
| E11 | §2.1 术语 | MVP 界面所有信号称「候选」；「摩擦」只在 v1 κ ≥ 0.6 后使用；judge 对 allow 前缀（DT-13 词表决定）与 hook（回放 dry-run）无增量，AI-07 ④ 一律 v1 |
| E12 | §4.1 / 功能映射 | 三张卡九段只在 `docs/archive/plans/feature-map.md` 写一份，本文 §7 只保留第 5 段；四份文档的前端升级表合并为该文件一张表，`UG-EV-01 = UG-RC-04`、`UG-EV-03 = UG-01 / UG-RC-01（basis 部分）`、`UG-EV-04 = UG-AI-04`、`UG-EV-02 = UG-RC-06 / UG-AI-07` |

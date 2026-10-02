# Signal 层、指标引擎与下钻

`analytics/signals/` 是八族之上的横向派生层，不是第九个族。它只读取 `AnalysisContext` 与 `analyze_context` 的结果，把八族事实转成 `signal`，再派生 `problem`（AN-06）、关键时刻（AN-09）、会话结果（AN-19）和会话事实补字段（AN-02）。设计依据见 [分析模块设计](../../plans/analysis-module.md) §2.3、§2.4、§3.2、§4，缺口与任务包见 [分析模块审计](../../audits/analysis-audit.md) §1、§2.2、§5。

版本：`rules_version = signals-v1.0`（[dictionary.py](../../../packages/backend/src/tandem_backend/analytics/signals/dictionary.py)）。词表、阈值或映射变化时必须同步提升版本号。

## 模块

| 文件 | AN | 职责 |
| --- | --- | --- |
| [stats.py](../../../packages/backend/src/tandem_backend/analytics/stats.py) | AN-10 | Wilson（z = 1.96）、`INSUFFICIENT_N = 5`、`{value, n, k, lo, hi, basis, status}` 指标对象 |
| [signals/detectors.py](../../../packages/backend/src/tandem_backend/analytics/signals/detectors.py) | AN-05 | 按根会话树构建视图，运行八个检测器 |
| [signals/problems.py](../../../packages/backend/src/tandem_backend/analytics/signals/problems.py) | AN-06 | 按 `(type, key, scope, scope_id)` 聚合并判断是否升级 |
| [signals/moments.py](../../../packages/backend/src/tandem_backend/analytics/signals/moments.py) | AN-09 | 规则关键时刻：编号、去重、每会话最多 8 个 |
| [signals/outcome.py](../../../packages/backend/src/tandem_backend/analytics/signals/outcome.py) | AN-19 | 会话结果合成器 |
| [signals/facts.py](../../../packages/backend/src/tandem_backend/analytics/signals/facts.py) | AN-02 | `outcome / verify_* / autonomy_steps / signals_summary` |
| [signals/inventory.py](../../../packages/backend/src/tandem_backend/analytics/signals/inventory.py) | AN-11 | `installed_unused`、`resident_tokens_median` |
| [metrics.py](../../../packages/backend/src/tandem_backend/analytics/metrics.py) | AN-01 | `metrics(context, metric[], bucket, group_by)` |
| [drilldown.py](../../../packages/backend/src/tandem_backend/analytics/drilldown.py) | AN-01.2 | 按工具取最近 N 条调用 |
| [api/insights.py](../../../packages/backend/src/tandem_backend/api/insights.py) | — | `build_router(get_result)` 提供的独立 `APIRouter` |

所有函数都是纯函数，不修改 `service.py`、`routes.py`、`context.py` 及八族文件。

## 空值约定

- 检测器返回 `None`：证据不可用（数据集缺失、旧账本 `legacy-json-ledger` 无法确认、缺少身份字段），不计为 0，也不进入分母。
- 检测器返回 `[]`：证据可用且未出现。
- `signals_summary[kind]` 沿用同一约定；`metrics` 中的 `unknown_n` 单列这类会话。

## signal.kind（v1.0 已实现）

每会话每个 `(kind, key)` 只产一行；`value` 保留次数，`occurrences` 保留每次出现的位置。`signal_id = stable_id(session_uid, kind, event_uid | call_uid)`，锚点取第一次出现的位置。

| kind | 规则 | unit | friction_type | problem_type | 机会分母 | basis | null 条件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `correction` | 助手回复之后、5–200 字的直接真人消息命中纠偏词表 | message | misunderstood_request | 有 `dimension` → repeated_instruction；无 → misunderstood_request | 有真人消息 | proxy | 事件不可用 |
| `frustration`（v1） | 挫败词表，或连续 2 条 ≤ 40 字纠偏 | session | misunderstood_request | misunderstood_request | 有真人消息 | proxy | 事件不可用 |
| `retry_loop` | 适配 `respond.retry_links`：同轮次（或同任务）、同 `status_scope`、`same_arguments = true` 的链接 ≥ 2 条且失败 ≥ 3 次；预期失败测试排除 | turn | tool_env_failure | tool_env_failure | 有工具调用 | measured | 调用不可用；存在无法确认身份的候选重试且无确认链 |
| `missing_verification` | 最后一次 `file.edit / file.write / file.change` 之后没有已执行验证 | session | buggy_output | missing_verification | 有编辑 | measured | 调用或验证不可用；旧账本；编辑后只有未确认的验证候选 |
| `would_prompt` | `kind = shell`、非包装、只读命令头，会话 `permission_mode = default`，且未被已装 allow 规则覆盖 | session | permission_friction | permission_friction | 有 shell 调用 | inventory 未知时为 proxy | 调用不可用；有只读命令但权限模式未知 |
| `permission_denied` | `permission.decision.decision = deny` 或 `tool_call.approval = declined` | session | permission_friction | permission_friction | 有真人消息 | measured | 不支持 `permission.*` 事件且调用无 `approval` 字段 |
| `risky_command` | DT-13 破坏性命令词表（`rm -rf`、`git push --force`、`git reset --hard`、`git clean -f`、`DROP TABLE`、`mkfs / dd`、`chmod -R 777`） | session | other | unsafe_operation | 有真人消息 | proxy | 调用不可用 |
| `interruption` | `turn.status = interrupted` 或旧账本 `turn.interrupted` | turn | process_overhead | 不升级（进 AN-19） | 有真人消息 | measured | 轮次与事件都不可用 |

未实现（按设计文档阶段）：`runaway_loop`、`edit_churn`、`mid_task_compaction`、`duplicate_prompt`、`workflow_pattern`、`quota_hit`、`parallel_conflict`（v1），`context_pressure`（v2），以及依赖旧链路的 `explanation_revision / long_response / unexplained_terms / requirement`。`risky_command` 的根目录外写入与权限模式判定属于 v1。

## signal → problem 映射（AN-06）

`key` 语法 `<signal.kind>:<子键>`，与推荐侧按全称比对。

| problem.type | 来源 kind | key | min_sessions |
| --- | --- | --- | --- |
| `repeated_instruction` | 带 `dimension` 的 `correction` | `correction:<dimension>` | 2 |
| `misunderstood_request` | 无 `dimension` 的 `correction`、`frustration` | `correction:none`、`frustration:session` | 3 |
| `tool_env_failure` | `retry_loop` | `retry_loop:<command_head>` | 3 |
| `missing_verification` | `missing_verification` | `missing_verification:<扩展名众数 ∣ project>` | 3 |
| `permission_friction` | `would_prompt`、`permission_denied` | `would_prompt:readonly_shell`、`permission_denied:<命令族>` | 3 |
| `unsafe_operation` | `risky_command` | `risky_command:<命令族>` | 1 |

其余问题类型（`communication_gap / repeated_workflow / context_loss / parallel_conflict / quota_interrupt / process_overhead`）的门槛已登记在字典中，来源信号随 v1 接入。

升级条件：`sessions ≥ min_sessions` 且 `wilson_lo(sessions, denom) ≥ 0.05`。`denom` 只统计同一范围内「有机会发生」且该 kind 证据可用的会话。范围为 `all / project / source`；`problem_id = stable_id(type, key, scope, scope_id)`，跨重算稳定。输出带显式的 `session_uids`；未升级的项放入 `candidates`，并给出 `reason ∈ below_min_sessions / below_wilson_lo / no_denominator`。`label(target_kind = problem, label ∈ resolved / dismissed)` 只读入 `status`，从不写回，也不会从结果中删除问题。`weekly_count` 取参考时刻前 4 周的出现次数均值。

## AN-19 会话结果

`outcome ∈ completed / partial / failed / abandoned / unknown`，`basis ∈ explicit_feedback / verify_pass / verify_fail / facet / structural / unknown`，并附 `evidence`（event_uid / call_uid / validation_uid）。

1. 显式反馈：最后一次交付之后的最后一条反馈。`accepted` 或确认完成 → completed；`rejected`、返工或否认完成 → partial；`mixed` 交给下一层。
2. 验证：最后一次编辑之后存在 `passed`，其后既无 `failed` 也无纠偏 → completed；最后一次验证为 `failed` → failed。
3. facet（可选输入 `facets`）：`fully / mostly_achieved` → completed；`partially_achieved` → partial；`not_achieved` 按有无交付和结构证据分流；`unclear` 不覆盖。
4. 结构：最后一个轮次被打断，或最后一条真人消息是纠偏且之后没有交付 → abandoned。其余情况为 unknown；事件不可用时为 unknown，`reason = events_unavailable`。

## AN-09 关键时刻

规则时刻共 6 类：`goal`（首条真人目标）、`correction`、`failure_streak`（retry_loop 首次成立）、`verify_pass`（最后一次编辑之后首个通过的验证）、`compaction`、`end`（会话最后一个事件，标注结果）。`moment_id = stable_id(session_uid, kind, event_uid | call_uid)`；按 `(kind, 锚点)` 去重，每会话最多 8 个，始终保留首尾，`total_n` 给出去重后的总数。说明文字固定，不引用用户原文。

## AN-01 指标

单位为根会话（子代理并入根）。比例按 `Σk / Σn` 合并，不对会话比例求平均；n < 5 时 `status = insufficient`、`value = null`；5–30 时 `show_n = true`。`group_by ∈ agent / source / project / model / effort / day / week`：缺失键归入 `unknown`，因此分组计数之和等于总体。model / effort 取该会话树 `model_call` 的众数；day / week 按 `started_at` 与 `display_timezone` 划分。`bucket ∈ day / week` 给出按日或按周的时间序列。

已登记指标：`sessions`、`human_messages`、`tool_calls`、`tool_failure_rate`、`correction_rate`、`completed_rate`、`verify_pass_rate`、`autonomy_steps_median`、`resident_tokens_median`、`unknown_outcome_sessions`、`<kind>_session_rate`（每个 signal.kind 一个），以及 `edit_without_verify_rate`（= `missing_verification_session_rate`）。

## AN-01.2 下钻与 AN-11

- `tool_calls(context, name, limit ≤ 50, command_head?)`：按 `name_raw / name` 匹配，按 `started_at`、`seq` 倒序返回。参数摘要由命令头和参数文本拼成，经过 `privacy.redact` 脱敏，并截断到 160 字。
- `installed_unused`：已启用的 skill / mcp / plugin 与窗口内调用名的匹配结果；hook / rule / scheduled_task 无法从调用名观测，标为 `not_matchable`，不计为未使用。inventory 不可用时返回 `null`。
- `resident_tokens_median`：每个主会话首个模型请求 `input_tokens` 的中位数，`basis = estimated`。

## 接入

`api/insights.py` 提供 `build_router(get_result, get_labels=None, scope_dependency=None)`，端点为 `/v1/analytics/metrics`、`/signals`、`/problems`、`/sessions/{id}/facts`、`/tools/{name}/calls`。`routes.py` 归任务包 (b)，挂载只需在其中补一行 `include_router`。

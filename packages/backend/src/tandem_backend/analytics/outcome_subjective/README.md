# Outcome 主观结果

本特征族描述用户对具体交付的明确反馈，位于“语义 · 瓶颈分析”象限。实现入口为 `analyze_subjective_outcomes`；会话详情、项目汇总、概览、CLI 共用同一套计算。关联 [Issue #4](https://github.com/ActionMesh-AI/Hackathon/issues/4)，本次实现由 `MistyHuang03` 发起。

本分支按本轮明确开发请求实现分类表中的主观 Outcome，供 PR 审查；尚未合并 main 或发布产品。下文“待团队确认”区分代码验收与产品决策，不声称三位成员已完成业务验收。

这是有证据的规则代理信号，不是通用情感分析。用户沉默、助手声称完成、测试通过和会话结束均不证明用户接受；`task_success` 始终为 `null`。产品字段口径与人工验收仍待团队确认。

## Feature TODO 与实现状态

- [x] 接受／拒收 `user_acceptance`：支持中文、英文明确短句；同一条消息中相互冲突时保留 `mixed`。
- [x] 完成确认 `user_confirmed_completion`：明确完成为 `true`，明确未完成为 `false`，其他为 `null`；接受回复不自动等于任务完成。
- [x] 返工 `rework_feedback`：保留明确重写、重做、重新修改等要求；只提取同一句中的显式原因，其他原因保留 `null`。
- [x] 对象 `feedback_target`：关联会话、任务、交付事件、产物及版本；关联不足时保留候选与原因。
- [x] 证据 `feedback_evidence`：消息 ID、规范化且脱敏的片段、顺序、发生时间、可见时间与时间质量。
- [x] 状态历史：保留同一交付的反馈顺序和最新反馈，保留未获反馈的交付，不将旧版本结果扩展到新版本。
- [x] 原入口兼容：保留 `subjective_outcome_candidates` 的三个字段及 `positive`／`negative` 两种值；混合反馈只出现在新结构中。
- [ ] 独立人工标注真实反馈集，并评估误报、漏报、对象关联及任务边界质量。
- [ ] 接入 Task 的可靠任务 ID 与 Respond 的显式交付、产物版本信息。
- [ ] 团队确认产品口径、词表覆盖与人工验收；长期满意度、外部实际使用仍暂缓。

以上勾选只表示代码与自动验证完成，不代表团队已批准新的产品范围。

## 特征口径

| 字段 | 粒度／类型 | 规则与缺失处理 |
| --- | --- | --- |
| `user_acceptance` | 反馈消息；`accepted/rejected/mixed/null` | 只匹配完整的明确分句；不以情绪、礼貌、沉默推断接受。 |
| `user_confirmed_completion` | 反馈对象；`bool/null` | 独立于接受；相互矛盾的完成陈述输出 `null` 并标记冲突。 |
| `rework_feedback` | 反馈消息；列表 | 每项保留 `request/reason`；新增需求本身不记返工。 |
| `feedback_target` | 对象关系；字典或 `null` | 交付必须在同一会话、反馈之前；显式坏链接（包括空对象）不能回退到其他交付。 |
| `feedback_evidence` | 证据；字典 | 原始日志通过 `event_uid` 回查；输出不复制原始日志，引用片段经过规范化和脱敏。 |
| `link_status` | 反馈；`linked/candidate/unlinked` | 只有 `linked` 计入确认分布；旧适配器的启发式任务 ID 只产生 `candidate`。 |
| `completion_scope` | `task/artifact/delivery/null` | 显式交付引用优先为 delivery，显式产物引用为 artifact，只有任务关联才为 task；不据此推断其他产物或整个项目的完成状态。 |

`accepted_feedback_count` 等计数以“已关联反馈消息”为单位，重复反馈计作不同观测，不是独立任务数量或满意率。`effective_n` 为已关联反馈数；`unknown_n` 为未能关联的候选、来源不确定的消息与不可测正文数量之和。未获反馈的交付另外计入 `deliveries_without_feedback`，分母不能相加混用。

`status=available` 仅表示输入范围可观测；`partial` 表示覆盖不全或存在未解决关联；整个事件源不可用／被排除时，`feedback/deliveries/counts` 为 `null`。已知子集中的 0 不代表未知子集没有反馈。

## 输入、对象关联与时间

输入是经过 `analytics.inputs.select` 筛选的 `analysis-input-v1` 事件。只分析已确认主会话中 `message.user + actor=human/user + attrs.origin=human` 的消息。注入、同伴、自动化、来源未知及子代理输入不进入反馈样本；重放和重复标记按既有契约排除。

交付是一轮（`turn_uid`）内最后一条非空 `message.assistant`；agent 不记录轮次时取相邻两条人类消息之间的最后一条（`common.final_assistant_uids`）。只有 Codex 写 `attrs.phase`；会话内只要有助手消息带 phase 即按标签判定：`final` 或历史日志的 `final_answer` 是交付，commentary 与缺标签的消息不是。这是最终回复的观测记录，不证明产物有效。

关联优先使用 `attrs.feedback_target`，其可选键为非空字符串 `delivery_event_uid/task_id/artifact_id/artifact_version`。否则使用明确共享 `task_id` 的最近一次先前交付。显式产物版本可以定位旧交付；仅在文本中提到“上一版”“旧版”“v1”等且没有对象元数据时，不猜它对应哪个版本。

```json
{
  "kind": "message.user",
  "actor": "human",
  "attrs": {
    "origin": "human",
    "task_id": "task-1",
    "feedback_target": {"delivery_event_uid": "delivery-v1"}
  },
  "text": "请重写结论，因为缺少测试结果"
}
```

交付可提供 `attrs.artifact_id/artifact_version`。任务来源没有声明时按规范输入的显式 ID 处理；`legacy_bundle` 单独标记 `task_id_source=legacy_derived`，其他非显式来源也不升级为确认关联。直接的交付／产物引用仍须通过会话、顺序、任务一致性与版本检查。

事件顺序使用 `seq`；交付时间晚于反馈时间时保留 `timestamp_conflict`，缺时间只保留顺序。`ts/available_at` 均为反馈自身的 UTC 毫秒时间，不用当前时间填补。范围为 `[from_ts, until_ts)`，不从范围外恢复交付，也不使用未来反馈解释过去快照。时间窗口截断了交付时，反馈保留为未关联候选。

## 分析函数与文件

| 函数 | 输入 → 输出 | 方法与对应测试 |
| --- | --- | --- |
| `classify_feedback` | 正文 → 分维度标签或空 | 去除平台块、引用和围栏；先排除含条件、假设、示例、转述及文本分析请求的整条消息，再排除提问；完整分句规则。分类正反例、冲突与因果范围单测。 |
| `collect_deliveries` | 事件、主会话集合 → 交付 | 显式 final／final_answer 与来源边界；阶段、子代理与重放单测。 |
| `extract_subjective_feedback` | 真人消息、交付、主会话集合 → 候选 | 再次检查身份，提取证据并调用关联；来源、actor、截断和证据测试。 |
| `link_feedback_targets` | 候选、交付 → 带状态的对象关系 | 会话＋任务／对象索引、按序二分查找；坏引用、旧版本、重复顺序和未来交付单测。 |
| `summarize_subjective_outcomes` | 候选、交付与覆盖 → 计数和历史 | 只汇总已关联反馈；状态反转、沉默、未知与分母测试。 |
| `analyze_subjective_outcomes` | 已筛选事件 → 完整特征族 | 串联以上步骤；范围、真实来源和缺失数据功能测试。 |
| `aggregate_subjective_outcomes` | 会话特征族 → 项目／概览 | 复用会话证据与分母；跨层一致性与 API/CLI mock 测试。 |

代码分别位于 [extraction.py](extraction.py)、[linking.py](linking.py)、[summary.py](summary.py)、[__init__.py](__init__.py)。主体通过 [features.py](../features.py) 接入，会话／项目／概览聚合在 [service.py](../service.py)。输入契约与其他特征族没有搬移。

## 五类测试与复跑方式

| 类型 | 证据与方法 | 完成边界 |
| --- | --- | --- |
| 单元 | [函数测试](../../../../tests/regression/test_subjective_outcomes.py) | 覆盖上述每个函数，包含失效输入和语义边界。 |
| 功能 mock | 同文件的 `test_mock_store_api_and_cli_share_the_family` | mock 输入适配器，在真实 TestClient 和 CLI 上比较 JSON、会话详情、项目聚合与历史窗口。 |
| 端到端真实数据 | [验证脚本](../../../../../../evals/analytics/subjective_outcomes.py) 的 `real_flow` | 只读备份现有 SQLite，在副本使导入缓存失效，重新解析原始 Codex 日志；保持截止时间与排除名单，核对 CLI/API 和源证据引用。 |
| 性能 | [独立性能脚本](../../../../../../benchmarks/analytics/subjective_outcomes.py) 的 `performance` | 1千／1万／5万事件、同一任务的连续交付与反馈；预热后重复3次，单独测量分配峰值；另测完整 analytics `--no-text` 计算。 |
| 正确性／质量 | [49例质量集](../../../../tests/fixtures/subjective-outcome-quality.json)、[质量测试](../../../../tests/regression/test_subjective_outcome_quality.py) | 独立保存预期标签，逐例比对接受、完成、返工三个维度，覆盖中文、英文、条件、引用、拒收及冲突。 |

质量集是为本规则口径构造的输入，不是独立标注的真实分布；同一组样例通过不能说明长文本、反讽、隐喻和跨任务反馈已经可靠。性能数字也不代表并发服务 SLA。

在仓库根目录运行，先执行 `uv sync --locked --all-packages --dev`：

```sh
uv run python -m pytest -q
uv run ruff check packages/backend/src packages/backend/tests packages/data/src packages/data/tests tests scripts evals benchmarks
uv run python -m tandem_backend demo
uv run python -m tandem_backend evaluate
uv run python -m evals.analytics.subjective_outcomes
# 真实全流程需要本机已授权的历史库和已有固定快照策略：
uv run python -m evals.analytics.subjective_outcomes \
  --real-db /path/to/existing/history.sqlite --codex-home /path/to/codex
```

脚本只向此 checkout 的 `.local/subjective-outcome-validation/` 写入，生成 `validation-summary.json`、副本库和完整 `real-analytics.json`。完整结果包含本地证据，保持忽略，不提交；文档只记录汇总。没有真实库时 `real_e2e=not_requested`，不能写成端到端通过。

## 本轮实测记录（2026-10-02，Asia/Shanghai）

运行环境：Python 3.12.3，macOS 14.6.1 arm64。全仓库 **540 项测试通过**；其中本族新增 93 项函数／功能用例、49 项构造质量用例；另有原 analytics 47 项回归通过。`ruff check src tests scripts`、`tandem demo`、`tandem evaluate` 均通过；evaluate 的 readability/pipeline/probe 分别为 8/8、34/34、12/12。仅有现有 Starlette/AnyIO 弃用提示。

质量集 49/49 完全匹配；该固定集合上的反馈检测 precision/recall 均为 1.0。样例包括无结果、冲突、中文／英文、引用、条件和新增需求；不将该数字外推为真实数据准确率。

| 事件规模 | 特征族耗时中位数（3次） | 特征族吞吐量 | 整体 analytics 无文本表示（单次） |
| ---: | ---: | ---: | ---: |
| 1,000 | 0.038 秒 | 26,566 事件／秒 | 0.083 秒 |
| 10,000 | 0.414 秒 | 24,151 事件／秒 | 0.866 秒 |
| 50,000 | 2.030 秒 | 24,634 事件／秒 | 4.385 秒 |

5万事件对应2.5万次交付与反馈；独立 tracemalloc 测量的特征族分配峰值约 **58.46 MiB**，不含输入数据内存。关联使用索引与二分查询，避免每条反馈重新扫描全部交付。没有执行并发压力、超大正文和长期运行内存测试。

真实端到端沿用本机已有快照：截至 **2026-10-01 23:43:13（Asia/Shanghai）**，排除名单中的1个会话保持不变。在隔离副本上使导入缓存失效后，重新解析36份真实日志，保存41,740个事件；126份已发现文件中的其余90份依现有策略跳过。原数据库文件摘要与样本策略前后相同。

选择后保留35个会话、40,664个事件，其中33个确认主会话；识别并逐条核对 **823 条 final／final_answer 交付引用**。原始解析、SQLite 适配、特征族、CLI JSON 和 API 概览／项目／会话详情全部一致。解析约6.64秒；引擎无文本表示约0.86秒；CLI进程含适配与JSON输出约4.02秒；3个API请求合计约7.66秒。

**真实语义结果仍不足以验收准确率**：仅9条消息有确认真人来源，另918条来源未知；没有命中明确反馈，823个交付结果全部保持未知。因此有效已关联反馈数为0，`status=partial`；这不是满意率0，也不是任务失败。真实反馈引用核对数为0，不能把它写成“真实正例已验证”。真实正负例的独立人工标注和业务验收仍待完成。

完整实测位于本地 `.local/subjective-outcome-validation/validation-summary.json`；原始数据、私有正文、数据库及完整分析结果不入库。验证脚本可按上节复跑。

## 限制与下一步

1. 规则只覆盖明确表达；“好的”“谢谢”“算了”保持未知。旧实现把“算了”当拒收的误判已移除。
2. final／final_answer 只是最终回复边界；缺少产物关系、版本或任务证据时，输出不能代替人工验收。
3. Task 负责可靠任务身份，Respond 负责交付记录；本族不重复实现任务分段或客观测试结果。旧任务推导保持候选，不在本轮扩大其权限。
4. 需要后续建立有授权、可脱敏、由多人标注的真实反馈集，再评估召回率和关联准确率；API 并发压测、超长文本与更大规模内存上限仍待测试。

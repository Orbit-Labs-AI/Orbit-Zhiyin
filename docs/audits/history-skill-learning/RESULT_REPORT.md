# RESULT_REPORT — 冻结后的四题比较

正式 held-out：Ours 4/4、LLM 4/4、Vanilla 3/4。Ours online 为 1,177,452 tokens，相对 LLM 增加 69.71%，相对 vanilla 增加 62.78%。

本轮修复了 history 到 Skill 的链路，并在成功率上优于 vanilla；但与 LLM 成功率持平、成本更高，**未达到 ours 全面优于 LLM / vanilla 的目标**。不再依据这批 test 调整实现或重跑到有利结果。

| arm | 通过 / 全部 | 失败 / 未知 | online tokens | tokens / success |
| --- | --- | --- | --- | --- |
| Vanilla | 3/4 | 1 / 0 | 723,323 | 241,108 |
| Ours | 4/4 | 0 / 0 | 1,177,452 | 294,363 |
| LLM | 4/4 | 0 / 0 | 693,808 | 173,452 |


五份交付：[token](TOKEN_REPORT.md)、[正面案例](POSITIVE_REPORT.md)、[负面案例](NEGATIVE_REPORT.md)、[注入漏斗](INJECTION_REPORT.md)，以及机器可复核的 [evidence.json](evidence.json)。

## 所有正式 test

| task ID | family / split | 任务摘要 | verifier（vanilla / ours / LLM） |
| --- | --- | --- | --- |
| court-form-filling-5 | court-form-filling / test | 双原告、第二次起诉、押金争议；填写必要字段并保留法院/未给出字段为空。 | Vanilla PASS 50/50; Ours PASS 50/50; LLM PASS 50/50 |
| court-form-filling-6 | court-form-filling / test | 单原告、首次起诉、另一押金争议；日期、必答选择与留空约束。 | Vanilla FAIL 44/47; Ours PASS 47/47; LLM PASS 47/47 |
| schedule-planning-4 | schedule-planning / test | 三封会议请求含 GMT 窗口与 90 分钟会议；从 PDF 几何读时间，覆盖蓝色任务并联合排程。 | Vanilla PASS 2/2; Ours PASS 2/2; LLM PASS 2/2 |
| schedule-planning-5 | schedule-planning / test | 三封请求含 Pacific 窗口与两小时会议；不能逐个贪心占用最早空档，须让全部请求容纳。 | Vanilla PASS 2/2; Ours PASS 2/2; LLM PASS 2/2 |


四题的三组 verifier 都运行完成，JUnit 无 skipped；主表使用冻结的官方判分。Court task 6 的两项电话格式断言过严，但 vanilla 还有独立 CourtInfo 错填，因此不改变这题的失败结论。Task 5 上游 CTRF 与 JUnit 参数化计数不同，记录实际 JUnit testcase 数及原 CTRF，不以简化汇总替代。具体局限见负面报告。

| task | Ours vs vanilla | Ours vs LLM | Ours / vanilla tokens | Ours / LLM tokens |
| --- | --- | --- | --- | --- |
| court-form-filling-5 | PASS / PASS | PASS / PASS | 166.43% | 197.64% |
| court-form-filling-6 | PASS / FAIL | PASS / PASS | 224.79% | 285.17% |
| schedule-planning-4 | PASS / PASS | PASS / PASS | 119.59% | 86.74% |
| schedule-planning-5 | PASS / PASS | PASS / PASS | 110.65% | 100.07% |


成功率配对：相对 vanilla，ours 1 胜、0 负，其余同结果；相对 LLM 全部同结果。每题仅一次随机执行，不能做总体显著性结论。

| task | Vanilla 原始目录 | Ours 原始目录 | LLM 原始目录 |
| --- | --- | --- | --- |
| court-form-filling-5 | `test-tokendance-slot-1/court-form-filling-5--vanilla` | `test-tokendance-slot-1/court-form-filling-5--ours` | `test-tokendance-slot-1/court-form-filling-5--llm` |
| court-form-filling-6 | `test-tokendance-slot-3/court-form-filling-6--vanilla` | `test-tokendance-slot-3/court-form-filling-6--ours` | `test-tokendance-slot-3/court-form-filling-6--llm` |
| schedule-planning-4 | `test-tokendance-slot-2/schedule-planning-4--vanilla` | `test-tokendance-slot-2/schedule-planning-4--ours` | `test-tokendance-slot-2/schedule-planning-4--llm` |
| schedule-planning-5 | `test-tokendance-slot-1/schedule-planning-5--vanilla` | `test-tokendance-slot-1/schedule-planning-5--ours` | `test-tokendance-slot-1/schedule-planning-5--llm` |


这些目录均相对于 `/Volumes/Data/OrbitBenchmark/study/run-005`。每目录包含 `result.json`、`provenance.json`、`model.json`、native session、`verifier/junit.xml`、`usage-observation.json`，学习组另有人工工具证据 `usage-review.json`。完整 cohort 为 TokenDance `kimi-k3` / `openai-completions` / max；原生两次中断另存于 `test/schedule-planning-4--llm` 与 `test/schedule-planning-5--llm`。

冻结顺序按任务第一次出现分组、组内顺序不变：schedule-planning-5: llm, ours, vanilla → schedule-planning-4: llm, ours, vanilla → court-form-filling-6: vanilla, llm, ours → court-form-filling-5: ours, vanilla, llm。前两个任务可并行；不会按已看到的结果调整顺序。

冻结时间：2026-10-03 20:04:26 UTC（北京时间 2026-10-04 04:04:26）；原 `freeze.json` SHA-256：`1efa11e457079766a9b0743de7200c9e50c01c5f7283961cccefc4ce972682d3`。完整设置和原始文件哈希在 evidence 中。

## 冻结与数据隔离

运行根目录：`/Volumes/Data/OrbitBenchmark/study/run-005`。正式执行代码为 `2225b37cbcc3bde1608182bdccdcdf55a2bf1de5`；benchmark 来源为 [SkillLearnBench](https://github.com/cxcscmu/SkillLearnBench/tree/726e1f79b96b0cb3d729d0e55a1c847e0b5353ae)，commit `726e1f79b96b0cb3d729d0e55a1c847e0b5353ae`。原 run-003/004 的全部已暴露实例仅用于开发诊断。

最终 freeze 先固定两家族、全部 split、库与 LLM 正文 hash、模型与 provider recovery、检索阈值、bundle 指令和随机运行顺序，再 sparse-download 四道 test。测试 prompt 由已冻结的源 commit 与 task ID 固定，下载后再记录单文件 hash。`freeze.json` 和 `freeze.sha256` 不覆盖；每次正式运行保留 code SHA、clean 状态、模型设置、镜像、prompt、verifier、执行器文件与注入正文 hash。正式运行期间代码树保持冻结；后续提交仅追加报告与其汇总证据。

| family | history / train | validation | held-out test |
| --- | --- | --- | --- |
| court-form-filling | `court-form-filling-1/2/3` | `court-form-filling-4` | `court-form-filling-5/6` |
| schedule-planning | `schedule-planning-1/2` | `schedule-planning-3` | `schedule-planning-4/5` |

五条 history 包含成功与失败，未按结果挑选；court 的初次镜像错误单独保留，基础设施修复后重跑。两组离线学习看相同历史，两组修订看相同 validation 反馈。反馈只含 validation prompt、失败断言、计量与审阅后的方法使用证据，不含 oracle 正文、verifier 源码或 test。Ours 局部修订失败的 court 技能；scheduler 保持正文和 bundle 字节不变。完成两次实质迭代后冻结，不再根据 test 结果选择家族、改阈值、改提示或重新训练。开发阶段各尝试使用不同提交，v1 LLM 的 provenance 还明确标记 working tree dirty；原始目录保留实际 prompt、request 和逐源文件 hash，不用最终 SHA 回填旧实验。正式 12 次运行全部是相同 clean freeze commit。

三组使用 Kimi K3 max、Pi 0.99.2、memory OFF，最多 200 turns、3,600 秒，context 1,048,576；容器 2 CPU / 3,500 MB、执行器 read/write/edit/bash、任务网络关闭。最多两个任务并行，同一任务按冻结顺序依次执行三个 arm。Ours 使用两项分开的证据化 Skill 库与确定性检索；LLM self-personalization 使用相同历史、反馈和 16,000 output-token 上限，生成一份全局合并 Skill；vanilla 无个性化资产。两种学习型 arm 都共享 bundle activation instruction。

原 Kimi Coding 优先；其正式测试初始两次请求遇到五小时额度错误，未返回计量，记为 UNKNOWN，不当作任务失败或零成本。按 freeze 前声明的规则，同一任务三组改在 TokenDance 独立 cohort 完整执行，后续任务使用同一 fallback endpoint；所有原尝试仍保留。预付 key 只控制额度，不能据此假定供应商端点与原生服务完全等价。

## 家族筛选与 oracle headroom

筛选发生在 test 内容访问之前，并先于 ours 效果判断。法院 validation 的空输出失败、参考解 47/47；排程无官方参考解，先从 validation PDF 与请求独立构造参考结果，空输出失败、参考结果 2/2，并审查约束与时区。只在 verifier 正常、实例可靠且有 headroom 时进入正式测试。

| validation 家族 | vanilla | oracle intervention | 决策 |
| --- | --- | --- | --- |
| court-form-filling-4 | FAIL 46/47；815,384 tokens | PASS 47/47；133,032 | 成功率和 token 有 headroom，保留 |
| schedule-planning-3 | PASS；已知 ≥166,635 tokens | PASS；106,364 | token 至少减少 36.17%，保留；oracle 墙钟更慢 |
| dbscan-parameter-tuning-3 | PASS；62,437 | PASS；122,783 | 无 headroom，提前排除 |
| earthquake-plate-calculation-4 | prompt 最近/最远要求矛盾 | 不进行付费对比 | 提前排除 |
| travel-planning-3 | 参考解 11/11，但 verifier 忽略预算/住宿且逐日景点要求与 prompt 不符 | 不进行付费对比 | 提前排除 |
| temperature-simulation-3 | 无参考解，可靠性未完成验证 | 不进行付费对比 | 未纳入 |
| stock-data-visualization-3 | 外部 D3 依赖尚未离线固定 | 不进行付费对比 | 未纳入 |
| dependency-vulnerability-check-3 | 外部漏洞库尚未固定 | 不进行付费对比 | 未纳入 |

这些是选择条件而不是所有家族的效果结论。排程原生 vanilla 的 429 有缺报，保守 token 下限仍足以证明 10% 的预设阈值。证据在 `headroom-summary.json`、`family-screening-development.json` 及 `headroom/`；被排除的任务不因后续 test 结果重新加入。

## 两次开发迭代

第一版从跨会话 trajectory 提炼 activation / procedure / verification / termination，再做相关性、证据、能力、验证与去重筛选；采用 [AWM、ExpeL、Voyager 的机制简化](../../research/history-skill-learning.md)，未实现其完整系统。第二版用共同 validation 反例做局部修订，让检查从“写入值能读回”扩展为“独立预期集合与输出双向比对”。后端没有硬编码 task ID、测试答案或表单字段规则；具体方法由选中历史和 validation 反馈生成，实际正文也原样公开以审查可能的过度泛化。

| 阶段 / provider | court ours | court LLM | schedule ours | schedule LLM |
| --- | --- | --- | --- | --- |
| v1 / native | FAIL 45/47；314,314 | FAIL 46/47；226,642 | PASS；79,096 | PASS；121,932 |
| v2 / native | PASS；≥522,202，总量未知 | PASS；277,144 | 正文未改，复用 v1 验证 | UNKNOWN；≥39,089，额度中断 |
| v2 独立复验 / TokenDance | PASS；187,867 | PASS；223,583 | PASS；99,466 | PASS；122,930 |

TokenDance 同 cohort 的 vanilla court FAIL 44/47、394,418 tokens，schedule PASS、111,907。两题合计：ours 2/2、LLM 2/2、vanilla 1/2；ours 287,333 tokens，比 LLM 346,513 少 17.08%，比 vanilla 506,325 少 43.25%。原生结果已经满足 freeze 条件；在 TokenDance vanilla 复验结束前记录此决定，再保留完整复验结果，不按两种 provider 的最佳单次拼接成绩。

Skill-only 两题均通过且确认使用；court 408,611、schedule 99,237 tokens。bundle 分别为 187,867 / 99,466。单次随机对比不能给出 activation instruction 的独立因果效应，因此仍采用预先设定的 bundle。阈值、top-k、dedup、history support 与能力过滤的离线敏感性见 [INJECTION_REPORT](INJECTION_REPORT.md)。

## 可复现入口与检查

五份报告共享 [evidence.json](evidence.json)：冻结设置、正式逐运行结果、result / provenance / asset / prompt / verifier 哈希、来源路径、配对统计、学习调用和全部成本 ledger。原始本机会话、隐藏推理、认证材料和 SQLite 库不进仓库。精确注入正文见 [INJECTION_REPORT](INJECTION_REPORT.md) 的资产链接。

在匹配依赖与 Docker 环境中，`evals.skill_learning.pipeline` 接收显式 history selection 完成真实 API 链路；`learning` / `interventions` 负责显式学习和导出；`final freeze` 只接受 clean commit 与 validation improvement，`final run` 校验冻结记录；`trace` 保存读正文与后续工具证据；`report` 只离线聚合既定 cohort，不按 pass/fail 选运行。具体参数见[评测入口](../../../evals/skill_learning/README.md)。

冻结提交上的五条新 history E2E 为 PASS / 8.950 秒；当前主线的 12 条旧 history E2E 为 PASS / 9.742 秒。完整 Python 与连接器检查通过；Swift 阶段因本机没有完整 Xcode 未完成，其余原型、文档和 wheel 安装验收单独通过。完整检查限制与失败记录见 [NEGATIVE_REPORT](NEGATIVE_REPORT.md)。

# TOKEN_REPORT — history 处理、online 与研发成本

**Offline 指正式方法对给定 history 的一次处理成本，debug、失败重试和 validation 修订不计入这项比较。** LLM 首次从 history 生成个性化 Skill 的实测为 **98,443 tokens**（90,857 input + 7,586 output），加上正式 online 693,808，按此费用口径合计 **792,251 tokens**。此前 207,305 的数字包含 108,862 validation 修订，属于累计学习调用账本，不能当作一次 history 处理成本。

必须区分两条 ours 路径：原统计分析与推荐算法不调用模型，**offline = 0**；但本轮 4/4 的正式 ours 在此之外使用了 `recommend.learn` 生成 Skill，首次成功调用为 **113,376 tokens**。因此，本轮结果是“LLM 辅助技能学习 + 算法检索”，不能把其 4/4 成绩标为纯算法、0-token 的 history→Skill 路径。纯算法路径在这四道 test 上没有独立运行成绩。

| history 处理路径 / 阶段 | 模型调用 | 一次成功处理 tokens | 适用范围 |
| --- | ---: | ---: | --- |
| Ours：统计分析、推荐与确定性检索 | 0 | **0** | 原算法路径；冻结 E2E 验收本身也为 0 模型调用 |
| 本轮 Ours：额外从 history 生成 Skill | 1 | **113,376** | `adaptation-v1/ours-attempt-2/model/call-02` |
| LLM：从 history 生成个性化 Skill | 1 | **98,443** | `adaptation-v1/llm/model/call-01` |

下表把现有正式 online 费用与一次成功 history 处理费用相加，按用户指定口径排除 debug。Offline 每组只计一次，不对每道题重复添加。

| arm | 正式通过 / 全部 | online tokens | 一次 history 处理 | 口径内合计 | 合计 / success |
| --- | --- | --- | --- | --- | --- |
| Vanilla | 3/4 | 723,323 | 0 | 723,323 | 241,108 |
| 本轮 Ours（LLM 辅助） | 4/4 | 1,177,452 | 113,376 | 1,290,828 | 322,707 |
| LLM | 4/4 | 693,808 | 98,443 | 792,251 | 198,063 |

按此费用归类，本轮 ours 比 LLM 高 62.93%。**版本边界：online 成绩来自 validation 修订后的 v2 资产，history-only 费用来自 v1 首次成功调用。** 此表是排除研发费用后的账面归类，不是“只用 v1 资产即可复现相同成绩”的实测，也不是从零重建冻结 v2 资产的完整费用。不能把未运行的纯算法 ours 与本轮 online 成绩拼接成新的实验组。

共享 history 的生成、headroom、validation、失败重试和修订均在后文研发账本保留，不计入上述比较。所有正式 online cohort usage 完整；不能用 validation 的节省率替代 test 实测。

## 正式逐题 tokens

本节仅列 online 执行成本：Ours 相对 LLM 增加 69.71%，相对 vanilla 增加 62.78%；加入一次 history 处理的费用归类见上表。

| task | Vanilla | Ours | LLM | Ours / vanilla | Ours / LLM |
| --- | --- | --- | --- | --- | --- |
| court-form-filling-5 | 294,012 | 489,324 | 247,587 | 166.43% | 197.64% |
| court-form-filling-6 | 178,600 | 401,473 | 140,783 | 224.79% | 285.17% |
| schedule-planning-4 | 103,332 | 123,574 | 142,469 | 119.59% | 86.74% |
| schedule-planning-5 | 147,379 | 163,081 | 162,969 | 110.65% | 100.07% |


按题平均的 ours / baseline ratio：vanilla 155.37%，LLM 167.40%；按合计 token 的 ratio：vanilla 162.78%，LLM 169.71%。这些只是本次配对观测，不是置信区间。

| arm | input | output | cacheRead | cacheWrite | total |
| --- | --- | --- | --- | --- | --- |
| Vanilla | 149,039 | 40,780 | 533,504 | 0 | 723,323 |
| Ours | 233,131 | 51,393 | 892,928 | 0 | 1,177,452 |
| LLM | 194,668 | 35,268 | 463,872 | 0 | 693,808 |


正式 test 余额实扣 ¥22.449162，本轮 TokenDance 合计实扣 ¥36.737451，三个 key 最终合计余额 ¥203.518577。两次原生正式中断没有 usage，不能当作已知零 token；它们列在研究 ledger 而不混入完整 fallback 配对。

## 口径

本报告计量本轮 Pi/Kimi 任务与离线适应调用，不包含 Codex 编程会话、Docker CPU 或磁盘成本。

每次调用只按 native Pi `message_end` 累计 `input + output + cacheRead + cacheWrite`，不再累计 `agent_end` 的重复消息。cache read 也计入逻辑 token；这与收费金额不是同一指标。正文长度仅作为字符数报告，不用字符数近似实际 token。

有错误请求未报告 usage 时，总量为 UNKNOWN，单独保留 `known_total_tokens` 下限，不能把缺失当作 0。正常任务失败照常计入 token；额度错误、开发拒绝、预检、学习、headroom 和消融均在全尝试 ledger 中保留。正式 online 统计只使用 `cohorts/<task>.json` 按预先规则选定的完整同 provider 三组，绝不按成功与否或 token 高低选运行。

逐任务 ratio 为 ours / baseline；合计 ratio 是两臂总 token 之比；二者平均方式不同，均明确标注。`online tokens/success = 该臂所有正式任务 online token / 通过题数`；费用归类表的 `合计/success = (该臂所有正式任务 online token + 一次成功 history 处理 token) / 通过题数`，均包含该臂失败题的执行成本。通过题数不同的组不宜仅按这个商推断因果效率。

## 学习调用归类：正式 history 处理与 debug 分开

| 阶段 | 本轮 Ours | LLM self-personalization | 是否计入一次 history 处理 |
| --- | ---: | ---: | --- |
| v1：首次成功从 history 生成 | 113,376 | 98,443 | 是；纯统计 ours 另为 0 |
| v1：引用检查误拒的失败调用 | 112,458 | 0 | 否，属于 debug |
| v2：同 validation 反馈修订 | 121,337 | 108,862 | 否，属于开发修订 |
| 被排除的 debug / 修订合计 | **233,795** | **108,862** | 不纳入正式成本比较 |
| 全部学习调用账本 | **347,171** | **207,305** | 仅保留实际支出记录 |

费用边界变化不删除已发生的调用。112,458 的误拒费用从正式方法比较中排除，仍保留在研发账本；validation 修订对两组按同一规则排除。两次投影不可用的尝试在模型调用前失败，不虚构 token。确定性检索本身不调用模型。逐调用 usage 和正文哈希见 `evidence.json` 的 `adaptation_call_integrity`，其中 `adaptation` 汇总仍代表全部学习调用，而非新的正式成本口径。

五条 history 的已知 token 合计为 921,952，其中一次 429 缺少 usage，因此只是下限。这批历史是两种学习 arm 的共享开发输入，未加到某一组的 online 或 adaptation。Oracle、verification、transport 预检、开发验证、Skill-only 对照也作为研究成本单列，不隐藏在最终 online 比较之外。

## 研发账本与实际余额（不纳入上述方法成本比较）

| key slot | 研究初始余额（元） | 正式 test 前（元） | 最终余额（元） | test 实扣（元） | 本轮实扣（元） |
| --- | --- | --- | --- | --- | --- |
| 1 | 79.267159 | 70.173580 | 56.961964 | 13.211616 | 22.305195 |
| 2 | 81.628972 | 76.434262 | 72.718989 | 3.715273 | 8.909983 |
| 3 | 79.359897 | 79.359897 | 73.837624 | 5.522273 | 5.522273 |


三个 key 在本轮第一次余额快照分别为 ¥79.267159、¥81.628972、¥79.359897；以真实快照为准，不使用对余额的口头估计。进入正式 test 前分别为 ¥70.173580、¥76.434262、¥79.359897，已消耗 ¥14.288289。余额 API 以 microyuan 返回，报告按 1,000,000 换算人民币；模型配置中的价格估计不当作实扣。

原生 Kimi Coding 属订阅额度，无法从这次调用记录推算边际人民币费用。TokenDance 是账户区间余额差，不是逐条计费单；供应商后台若有其他同时消费会影响差值。全部 attempt 的已知 tokens 是下限，不能与完整正式 cohort 的总量混写。

| 原始目录组 | 有 trajectory 的尝试数 | 已知 tokens 下限 | usage 缺报次数 |
| --- | --- | --- | --- |
| `adaptation-v1/` | 3 | 324,277 | 0 |
| `adaptation-v2/` | 2 | 230,199 | 0 |
| `headroom/` | 6 | 1,406,635 | 1 |
| `history/` | 3 | 508,649 | 1 |
| `history-infrastructure-retry/` | 2 | 413,303 | 0 |
| `preflight/` | 1 | 10,426 | 0 |
| `preflight-tokendance/` | 1 | 10,030 | 0 |
| `test/` | 2 | 0 | 2 |
| `test-tokendance-slot-1/` | 6 | 1,504,352 | 0 |
| `test-tokendance-slot-2/` | 3 | 369,375 | 0 |
| `test-tokendance-slot-3/` | 3 | 720,856 | 0 |
| `validation-ablation-skill/` | 2 | 0 | 2 |
| `validation-tokendance-bundle/` | 2 | 0 | 2 |
| `validation-tokendance-verified-bundle/` | 6 | 1,140,171 | 0 |
| `validation-tokendance-verified-skill/` | 2 | 507,848 | 0 |
| `validation-v1/` | 4 | 741,984 | 0 |
| `validation-v2/` | 3 | 838,435 | 2 |

全研究共 51 个有 trajectory 的调用/执行，已知至少 8,726,540 tokens，10 个 usage 不完整；完整总量 UNKNOWN。模型调用前失败没有 trajectory，另保留原始错误目录，不虚构计量。



所有行的 code / provider / prompt / verifier / 原始目录可从 [RESULT_REPORT](RESULT_REPORT.md) 和 [evidence.json](evidence.json) 回溯。

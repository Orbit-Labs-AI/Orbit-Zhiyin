# TOKEN_REPORT — online、学习和研究成本

正式 held-out：Ours 4/4、LLM 4/4、Vanilla 3/4。Ours online 为 1,177,452 tokens，相对 LLM 增加 69.71%，相对 vanilla 增加 62.78%。

所有正式 cohort usage 完整。Ours 相对 LLM 的成功率持平，但 online 和 adaptation 都更高，因此本样本下不存在靠重复同分布任务回收额外学习成本的 token 盈亏平衡点。不能用 validation 的节省率替代 test 的实测。

| arm | 通过 / 全部 | 失败 / 未知 | online tokens | tokens / success |
| --- | --- | --- | --- | --- |
| Vanilla | 3/4 | 1 / 0 | 723,323 | 241,108 |
| Ours | 4/4 | 0 / 0 | 1,177,452 | 294,363 |
| LLM | 4/4 | 0 / 0 | 693,808 | 173,452 |


## 正式逐题 tokens

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

有错误请求未报告 usage 时，总量为 UNKNOWN，单独保留 `known_total_tokens` 下限，不能把缺失当作 0。正常任务失败照常计入 token；额度错误、开发拒绝、预检、学习、headroom 和消融均在全尝试 ledger 中保留。正式主表只使用 `cohorts/<task>.json` 按预先规则选定的完整同 provider 三组，绝不按成功与否或 token 高低选运行。

逐任务 ratio 为 ours / baseline；合计 ratio 是两臂总 token 之比；二者平均方式不同，均明确标注。`tokens/success = 该臂所有正式任务 token / 通过题数`，包含该臂失败题的成本。通过题数不同的组不宜仅按这个商推断因果效率。

## 离线适应成本

| 阶段 | Ours | LLM self-personalization |
| --- | ---: | ---: |
| v1：首次归纳及被拒调用 | 225,834（112,458 被拒 + 113,376 接受） | 98,443 |
| v2：同 validation 反馈修订 | 121,337 | 108,862 |
| 实测合计 | **347,171** | **207,305** |

Ours 比 LLM 多 139,866 adaptation tokens。首次引用校验误拒消耗的 112,458 已计入；修复后可能避免该开销，但不能把“未来可以省”从本轮实测中扣除。两次投影不可用的尝试在模型调用前失败，不虚构 token；其错误仍留存。检索本身不调用模型。

五条 history 的已知 token 合计为 921,952，其中一次 429 缺少 usage，因此只是下限。这批历史是两种学习 arm 的共享开发输入，未加到某一组的 online 或 adaptation。Oracle、verification、transport 预检、开发验证、Skill-only 对照也作为研究成本单列，不隐藏在最终 online 比较之外。

下表的“online + adaptation”只做本轮 4 题上的学习成本摊销；它仍不包含共享 history、headroom 和验证研究成本，不是用户真实部署的完整总拥有成本。

| arm | online | adaptation | 合计 | 合计 / success |
| --- | --- | --- | --- | --- |
| Vanilla | 723,323 | 0 | 723,323 | 241,108 |
| Ours | 1,177,452 | 347,171 | 1,524,623 | 381,156 |
| LLM | 693,808 | 207,305 | 901,113 | 225,278 |


## 实际余额与研究总成本

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

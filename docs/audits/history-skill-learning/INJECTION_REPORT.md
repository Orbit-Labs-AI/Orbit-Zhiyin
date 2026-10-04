# INJECTION_REPORT — 历史到实际使用

本报告配合 [RESULT_REPORT](RESULT_REPORT.md)、[TOKEN_REPORT](TOKEN_REPORT.md)、[POSITIVE_REPORT](POSITIVE_REPORT.md) 和 [NEGATIVE_REPORT](NEGATIVE_REPORT.md)。所有本地路径以 `/Volumes/Data/OrbitBenchmark/study/run-005` 为根；机器证据与冻结哈希见 [evidence.json](evidence.json)。

## 原链路为什么没有所需 Skill

12 条 history 已成功导入。原版本只有命令类别、文件画像与工具失败证据参与推荐，没有从跨会话操作轨迹归纳文档方法。`ai_generate=false`，实际生成模型调用为 0。旧目录 665 项中的 62 个 Skill 又全部被 Pi 标签预过滤；唯一内置排错 Skill 虽然通过阈值与去重，却因同一问题最多两项，被更高分的 Hook 和 Rule 占去名额。

| 原版本阶段 | 数量与类型 | 分数 / 证据 / 去向 |
| --- | --- | --- |
| history ingestion | 12 sessions、459 mapped records、880 events | unparsed=0；原始导入不是空输入 |
| analytics evidence | 一项 active 环境失败 | unzip 在 5/9 会话失败；命令头无法表达 PDF / 表格方法 |
| catalog agent filter | 665→6 项；Skill 62→0 | Agent 标签不等于正文能力兼容 |
| raw candidates | 1 hook + 1 rule + 1 skill | 都围绕同一个 unzip 环境问题 |
| scoring / threshold | 3→3 | priority：Hook 35.43、Rule 32.82、Skill 25.66 |
| dedup | 3→3 | 无淘汰 |
| final selection | 3→2 | Skill `cap:problem`；不是低置信度淘汰 |
| Pi injection | 1 hook + 1 rule；0 skill | 上游没有 Skill 可序列化 |
| runtime | 392 次 hook 调用；0 次阻断 | 调用不等于有效；无 Skill 可触发 |

上述是旧快照重放，不能套用到当前主线。合并 `47c15b85` 后，`8da9178c` 的真实 API 重放保留当前目录全部 608 个 Skill（目录 2,022→Pi 1,122 项）；原始候选 7 项（2 hook、2 rule、3 skill），评分与兼容均保留 7，阈值保留 4（1 hook、1 rule、2 skill），去重仍 4，最终两项 Skill 均为 `cap:problem`，仍只留下 Hook / Rule。新增目录项是 `temporal-developer`，不是文档操作技能。目录与分析版本同时变化，这不是单因素实验。完整逐候选 score、supporting evidence、保留/拒绝理由已保存；[根因审计](../history-skill-root-cause.md) 记录旧版与新版边界。

## 新路径保留了什么

新路径是后端显式 `recommend.learn` / `recommend.refine` AI job，默认统计推荐保持原行为。它不自动安装或执行技能，也未新增 UI 自动学习入口。五条独立训练历史经正式 data API 导入：154 条 mapped records、291 events、64 tool calls、54 model calls。冻结提交上的 data→analytics→recommendation→funnel 端到端验收通过，8.950 秒，验收本身 0 模型调用（`learning-e2e-frozen`）。这一步默认产出 prompt / workflow / rule，证明原数据与统计链路接通；两个 Skill 则由显式学习/修订 job 和后续检索获得，第二版 artifact 为 `af_53f8f6fb7364453b`，不是默认统计推荐自动转成 Skill。

学习输入的任务级结果标为 `unknown_without_external_validation`；导入 native session 时不会把会话结束后运行的外部 verifier 结论伪装成历史事实。两组学习使用相同 canonical 历史与相同脱敏片段：5 sessions、160 个可见事件中保留 151、遗漏 9、裁剪 22；保留 61 tool.call、59 tool.result、26 公开 assistant、5 user。估算输入 47,667 tokens，38 次脱敏。最多 8 sessions，每会话 160 events / 48,000 chars，头尾保留；工具 input 上限 12,000 chars、result 4,000、user 6,000。不包含隐藏推理、L0 原文或图片像素，不能宣称完整无损 trajectory。主线升级前后模型可见材料逐字相同，SHA-256 为 `eb2c69ee2b6484f63b25018ba4894923b9f7fd08b533774dc15edb4011386f49`。

候选 schema 允许 skill / rule / hook / workflow / subagent / MCP，要求 activation、avoid、requires、procedure、verification、termination、limitations 与真实 session/event 引用。本次实际只产生 2 个 Skill，其余类型为 0；没有为凑类型生成空 Hook 或 MCP。引用检查证明引用存在，不能证明每条文字主张都由证据语义蕴含。

| 冻结候选 | 支持历史 | 正文版本 | 验证 |
| --- | --- | --- | --- |
| `pdf-acroform-court-form-filler` | 3 个 court history；另有独立 validation 反例 | `learned_79bce4b31b2996d48c0c` | native 与 TokenDance 各一次 full-bundle validation 通过并确认使用 |
| `calendar-pdf-meeting-scheduler` | 2 个 schedule history | `learned_1a21812b557b147d1cfd` | native 与 TokenDance 各一次 full-bundle validation 通过并确认使用 |

验证凭据绑定内容 hash、任务、报告与使用审计 hash。正文变化使旧凭据失效；未修改的 scheduler 在第二次迭代逐字保留。`validation` 标签由调用方声明，接口本身不是第三方评估器。

## 正式 test 检索漏斗

每道任务独立：raw 2 skills→scoring 2→至少 2 条 history 支持 2→relevance 1→capability compatibility 1→validation gate 1→exact-procedure dedup 1→top-k 1。其余所有类型为 0。分数是确定性词项余弦相关性，不是成功概率；关键词权重为 2，阈值 0.06，top-k=2。只读取当前任务 prompt，不读取 test verifier 或解答。

| task（均为 test） | 表单 Skill score | 日历 Skill score | 保留 / 拒绝 |
| --- | ---: | ---: | --- |
| court-form-filling-5 | 0.123181 | 0.049032 | 表单保留；日历 `below_relevance_threshold` |
| court-form-filling-6 | 0.151347 | 0.045072 | 表单保留；日历 `below_relevance_threshold` |
| schedule-planning-4 | 0.044835 | 0.328168 | 日历保留；表单 `below_relevance_threshold` |
| schedule-planning-5 | 0.044835 | 0.328168 | 日历保留；表单 `below_relevance_threshold` |

候选任务覆盖率 4/4，最终推荐覆盖率 4/4。这里的“覆盖”只表示有对应候选，不表示它必然正确或有效。

## 最终注入内容

正文原样保存为 [ours 表单 Skill](assets/ours-form.md)、[ours 日历 Skill](assets/ours-calendar.md)、[LLM 合并 Skill](assets/llm.md)。对应字符数为 7,223 / 4,993 / 11,688；字符数不当作 token。Ours 每题注入检索到的一项；LLM 每题注入一份合并两种任务方法的自由格式 Skill。两组共享以下 bundle activation instruction，均无 Hook：

> Before planning the task, inspect the available skill descriptions. Read the full body of each skill whose activation condition matches the current task, then apply its procedure and verification checks. Derive all task-specific values from the current inputs. If a skill's assumptions do not hold, skip it and explain the mismatch. Current user instructions take priority.

注入为只读文件挂载、Skill name/description 清单与上述指令；validation 证据和筛选审计不挂载给 agent。Pi 使用 fresh agent directory、memory off、禁止环境自带 Skill / context / extension 自动发现，仅启用隔离的 read/write/edit/bash 执行器。测试与参考解在 agent 结束后才挂载到 verifier。Memory OFF 并不禁止实验显式提供 Skill；三组之间没有共享会话状态。

| task / arm | injected | body read | confirmed use | unreviewed | 后续证据目录 |
| --- | --- | --- | --- | --- | --- |
| court-form-filling-5 / vanilla | 0 | 0 | 0 | 0 | 无个性化资产 |
| court-form-filling-5 / ours | 1 | 1 | 1 | 0 | `test-tokendance-slot-1/court-form-filling-5--ours/usage-review.json` |
| court-form-filling-5 / llm | 1 | 1 | 1 | 0 | `test-tokendance-slot-1/court-form-filling-5--llm/usage-review.json` |
| court-form-filling-6 / vanilla | 0 | 0 | 0 | 0 | 无个性化资产 |
| court-form-filling-6 / ours | 1 | 1 | 1 | 0 | `test-tokendance-slot-3/court-form-filling-6--ours/usage-review.json` |
| court-form-filling-6 / llm | 1 | 1 | 1 | 0 | `test-tokendance-slot-3/court-form-filling-6--llm/usage-review.json` |
| schedule-planning-4 / vanilla | 0 | 0 | 0 | 0 | 无个性化资产 |
| schedule-planning-4 / ours | 1 | 1 | 1 | 0 | `test-tokendance-slot-2/schedule-planning-4--ours/usage-review.json` |
| schedule-planning-4 / llm | 1 | 1 | 1 | 0 | `test-tokendance-slot-2/schedule-planning-4--llm/usage-review.json` |
| schedule-planning-5 / vanilla | 0 | 0 | 0 | 0 | 无个性化资产 |
| schedule-planning-5 / ours | 1 | 1 | 1 | 0 | `test-tokendance-slot-1/schedule-planning-5--ours/usage-review.json` |
| schedule-planning-5 / llm | 1 | 1 | 1 | 0 | `test-tokendance-slot-1/schedule-planning-5--llm/usage-review.json` |

正式完整 cohort：ours 候选与最终推荐覆盖均为 4/4；ours 与 LLM 的注入、正文读取、确认实际使用均为 4/4。LLM 使用固定合并资产，没有单独的候选筛选漏斗；vanilla 不注入。所有 Hook 数为 0。实际使用条件下的成功率与 token 比较即主表，因为所有学习组都确认使用；没有未使用子组可用于估计使用本身的因果收益。

另有两个被额度错误中断的原生 LLM 尝试：保留其注入事件与未完成的使用观测，不把它们计作完整 cohort 的未触发失败。


`injected` 来自 manifest 事件；`activated` 要求成功读到完整正文；`actual usage` 还要求人工对照后续真实 tool-call ID 与方法步骤。审计不读取隐藏推理，不把模型口头说“我会使用”算作使用。实际使用允许部分遵循，不等同于所有检查都执行完毕，更不是因果效应估计。

## Validation 消融

| 因素 | 观测 | 可得结论 |
| --- | --- | --- |
| 旧 top-k / dedup | top-k 3/10 或关闭去重仍 0 Skill；每问题上限 2→3 仅恢复通用排错 Skill | 不能靠名额补出未归纳的文档方法 |
| history 数量 | 当前库支持为 3 / 2；只保留前 1/2 条证据时都不够 2-session 门槛；前 3 条仅 scheduler 足够 | 是固定库的证据敏感性，不是少样本重新学习的因果实验；不能证明 5 条普遍充分 |
| support threshold | 1 或 2 不改变选择；3 会排除 scheduler | 阈值过严会杀掉已有重复证据 |
| relevance | 0.15 会排除 court validation；0 会引入另一无关家族 Skill | 有精度与召回权衡；未依据 test 调整 |
| top-k 1/4、dedup off | 默认只剩一项，选择不变 | 本轮新链路不是这些环节造成丢失 |
| capabilities | 增加 network/MCP/subagent 能力不改变选择 | 两项实际只需已有工具；描述性的未编译组件不假装可运行 |
| trigger / bundle | 两题 Skill-only 与 bundle 均读正文并采用方法 | 未观测到 trigger 过窄；不能证明额外指令必需 |
| court Skill-only / bundle | 均 PASS；408,611 / 187,867 tokens | 单次随机运行，不能将 2.18 倍差异全部归因于指令 |
| schedule Skill-only / bundle | 均 PASS；99,237 / 99,466 tokens | 差异约 0.23%，无明显收益证据 |

Skill-only 取消共享 activation instruction，保留相同 Skill 正文和 descriptor。默认 bundle 在正式测试前已经固定；不按各题消融优劣混选配置。所有消融均在 validation 上完成，原生额度错误与错误 transport 的尝试也保留。

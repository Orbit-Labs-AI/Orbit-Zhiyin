# NEGATIVE_REPORT — 未实现全面优势的原因

正式 held-out：Ours 4/4、LLM 4/4、Vanilla 3/4。Ours online 为 1,177,452 tokens，相对 LLM 增加 69.71%，相对 vanilla 增加 62.78%。

本轮修复了 history 到 Skill 的链路，并在成功率上优于 vanilla；但与 LLM 成功率持平、成本更高，**未达到 ours 全面优于 LLM / vanilla 的目标**。不再依据这批 test 调整实现或重跑到有利结果。

## 正式 test 的成本退化

| 正式负面观测 | Ours | 对照 | 诊断层级 |
| --- | --- | --- | --- |
| court-form-filling-5 | 489,324 tokens；22 tools；2 tool errors | LLM 247,587 | 方法已使用；XFA/Parent API 错误与密集视图检查带来恢复和上下文成本 |
| court-form-filling-6 | 401,473 tokens；21 tools；10 image reads | LLM 140,783；12 tools；4 image reads | 方法已使用；检查成本高，且未观察到独立机器校验的完整缺失/多填集合 |
| schedule-planning-4 | 123,574 tokens | vanilla 103,332 | 方法已使用但相对 vanilla 成本退化；中间 DST 偏移错误被最终可行时段掩盖 |
| schedule-planning-5 | 163,081 tokens | LLM 162,969；vanilla 147,379 | 方法已使用且三组均通过；相对 LLM 无可见节省，相对 vanilla 更多 |


表单两题的 Skill 均读取并采用了字段枚举、问题分类与验证方法。它们的失败模式不再是“没有推荐 / 被过滤 / 未触发”，而是**能得到正确输出，但过程仍冗长且没有稳定的成本约束**。Task 5 的两个工具错误分别是 pypdf 间接对象/XFA 查询和不存在的 `Parent` 键；恢复后仍保留全部 token。Task 6 额外读取多个高分辨率 crop，和较高缓存上下文 token 同时出现；未做单因素对照，不能将全部差额归因于某条 Skill 指令。

本轮 validation 对正确性提升给出了放行，但没有要求每个候选同时满足跨多个实例的效率约束。样本也不足以估计成本方差。这解释了验证改善为何没有转化为对 LLM 的稳定优势；不在 test 后放宽/修改 gate 来改写本轮结果。

## 保留的开发失败

- 原 ours 没有得到所需方法：旧统计表示丢失操作过程，目录兼容与每问题名额进一步压缩，注入端没有可以激活的 Skill。当前主线已修复可移植 Skill 兼容，但不等于自动拥有从历史归纳方法的能力。
- v1 court：ours 45/47，漏两项必答 No；LLM 46/47，多填 CourtInfo。两组都注入、读取并采用了方法，故为方法/检查无效，而不是未触发。第二次迭代把相同 validation 反例给两组；ours 只修订失败候选、保留 scheduler 字节不变。
- v2 native court：两组都通过，但 ours 已知 token 下限 522,202，LLM 277,144。完整 ours 总量因恢复后的 429 缺报而未知，已经至少多 88.42%；修订不是无成本改善。工具行为含字段名修复和 XFA 探索。
- 学习初次有 112,458 tokens 的返回因引用检查过严被拒。修复对所有实际步骤引用取并集后仍把这次费用算入 ours。主线数据投影需升级时的两个空历史尝试在模型调用前失败，通过正式 import API 升级并验证材料字节一致后继续。
- 原 Kimi 的五小时额度错误保留为 UNKNOWN。第一次 TokenDance 尝试因仅写模型缓存、没有显式 provider 注册而发错协议，401 且余额未扣；修复发生在 freeze 前。成功预检保存实际 `openai-completions` / `kimi-k3` 协议证明。不能将这些基础设施失败记为任务失败或删除成本。

## 不能推出的结论

测试是同家族新实例：表单复用 SC-100 模板，排程复用版式和任务说明，仅输入请求与占用块变化，不能当作跨家族或新模板泛化。仅 2 个家族、4 个 held-out 实例，每臂每题一次随机运行，不提供统计显著性，也不代表全部 assistant、task family 或“所有 LLM personalization”。LLM baseline 用相同历史/反馈/输出预算生成一份全局合并 Skill；ours 是结构化分项库加检索。因此观察到的是整套组织方式的差异，不能单独归功于检索或某一句提示。

验证集每家族只有一道题，validation-gated selection 有开发集适应风险。学习产生的表单正文仍带 SC-100 具体知识，包含“必答题未提及时取 No”“payment-demand Yes”等可能过度泛化的语句；后端的引用存在检查不验证这些命题在所有任务上都成立。日历正文也保留固定配色、午夜锚点、约 1 单位 inset 等经验，以及未经验证的 PST 固定偏移限制。没有在 test 后手改这些正文。

法院 verifier 主要验证字段值而非完整视觉质量或真实诉讼适用性；本实验是合成文件操作评测。排程任务的“最早且全部可容纳”仍依赖 benchmark 的排序约定。Family 在 validation headroom 后选定，因此结果适用于具备该筛选条件的任务。原 run-003/004 12 题与本次 4 题不是同一集合，不能把旧 7/12 与新结果之差宣称为代码因果收益。

Pi memory OFF 只隔离代理会话记忆，不能排除公共 benchmark 已存在于模型预训练中的可能。TokenDance 的底层服务路由不能独立审计；原生与代理端点分 cohort 报告，不默认为严格等价。余额差是账户区间实扣，若账户同时被他处使用，会混入其他消费；本轮未观测到这种并行消费。

## 检查边界

完整 `pnpm check` 的 Python 部分 4,912 passed / 3 skipped，串行 75 passed；连接器检查和 lint 通过。Swift 阶段因本机只有 Command Line Tools、缺少完整 Xcode 的 XCTest / PlatformPath 而未完成。本改动不涉及 Swift；没有把整条 `pnpm check` 宣称通过。其余原型产物、文档链接与安装后 wheel 验收单独通过。后续 AI/学习与评测相关变更分别补验 323 / 19 项通过；报告新增内容另跑文档检查。

## 正式 test 事后 verifier 审计

`court-form-filling-6` vanilla 的 3 项失败中，两项电话是格式误报：PDF 字段与可见文本都保留了完整号码，只加入连字符；verifier 的 `normalize_text` 只折叠空白、转小写，却要求未分隔的号码。独立只读解析保存在 `posthoc-court6-phone-audit.json`。另一项失败是给应留空的 CourtInfo 填入城市/县名，所以即使忽略两项电话格式误报，这题仍有内容约束失败。正式结果保持原 verifier，不据此重跑、排除题目或改分。

`schedule-planning-4` ours 的工具代码将 GMT 到 New York 写成 −5 小时；该日实际为 UTC−4。最终选择 10:00–11:00 恰好同时属于错误窗口和正确窗口，因而仍通过。它说明 pass 不保证中间方法完全正确。排程 verifier 主要比较预设日期、时间及收件人，并不完整验证正文模板、duration 与所有中间时区推导；只有两项测试的 PASS 不能替代全部需求审查。


## 后续研究边界

这四道 test 现在已暴露，未来只能作为开发资料。后续若继续，需另行冻结新 test：评估基于风险的渲染/裁剪预算、可执行的独立验证模板、引用的语义支持、时区解析与成本分布。这里提出的是下一轮假设，本轮未实现、未重跑，也不宣称它们一定有效。

原始失败与每次使用证据见 [evidence.json](evidence.json)；全部正式 task 的内容摘要、family、split、verifier、SHA 与原始目录见 [RESULT_REPORT](RESULT_REPORT.md)。

# POSITIVE_REPORT — 已证实的局部改善

Ours 四道 held-out 均通过，方法从 history 到实际使用的证据链可以追踪。正面结果主要是相对 vanilla 的成功率，以及单个排程案例相对 LLM 的 token 节省；完整比较仍不支持 ours 全面领先。

## 历史方法能够穿过完整链路

旧 12-session 链路没有归纳文档操作程序，即使放开每问题名额也只是恢复一项通用排错 Skill。新增路径把显式选择的 canonical 轨迹送入有界脱敏 pack，再跨会话归纳 activation、procedure、verification 与 termination；候选通过内容绑定的 validation，再由当前任务检索。正式四题均产生、保留并注入对应家族 Skill。这里修复的是“history 里有操作，却到不了可执行方法”的链路断点。

数据端、分析端和推荐端在真实 Gateway API 下联通；冻结提交 `2225b37c` 的五条训练历史 E2E 8.950 秒通过，12 条旧历史当前主线重放 9.742 秒通过。新技能由显式 AI job 产生并保留独立 hash，没有用手写 benchmark 规则替换推荐算法。两条历史学习库中的方法仍是具体任务族经验，不因此宣称跨所有任务通用。

## Held-out：表单 task 6 修正多填信息

`court-form-filling-6` 是单原告押金纠纷，要求只填必要字段，未给出和法院填写内容留空。Vanilla 44/47，ours 与 LLM 均 47/47。Vanilla 对电话的两项失败是 verifier 格式敏感性；独立的实质错误是多填 CourtInfo。两种学习方法均保留了“不从城市推断 CourtInfo”的约束，输出没有这个多填错误。因此这题支持相对 vanilla 的约束遵循改善，不支持 ours 独有的能力优势。

Ours 的证据链是：3 条 court history → v1 validation 暴露必答遗漏 → 与 LLM 共享同一份反例 → 局部修订得到 `learned_79bce4b31b2996d48c0c` → 当前 prompt score 0.151347 通过门槛 → `read_0_6c6f7109` 读取正文 → `bash_2_84a32b1c` 枚举字段 → `bash_4_93a38c36` 对照问题文字与位置 → `bash_7_dd0431e0` 回读字段 → `bash_8_46b1f58f` 渲染检查 → 47/47。原始路径为 `test-tokendance-slot-3/court-form-filling-6--ours`。

这是可追溯的机制解释，不是把多项改动隔离后的因果估计。成本代价明显：ours 401,473 tokens，LLM 140,783，vanilla 178,600；详见 [NEGATIVE_REPORT](NEGATIVE_REPORT.md)。

## Held-out：排程 task 4 相对 LLM 节省 token

`schedule-planning-4` 三组都通过。Ours 123,574 tokens，LLM 142,469，少 18,895（13.26%）。当前任务只检索 scheduler，score 0.328168；表单方法 score 0.044835 被过滤。注入的 scheduler 正文 4,993 字符，LLM 合并正文 11,688 字符；正文大小差异与 token 节省相容，但单次结果不能证明全部节省由正文压缩造成。

工具证据：`read_0_6aab378b` 读 Skill；`bash_4_45c9a640` 提取矢量块和文本坐标；`bash_6_7727cdc8` 排除蓝色可覆盖时间、联合回溯排程并渲染；`bash_13_6ef8da52` 回读所有回复。原始路径为 `test-tokendance-slot-2/schedule-planning-4--ours`。

这题也有边界：vanilla 只用 103,332 tokens；ours 中间代码用了错误的 GMT/ET 偏移，最终时间恰好仍正确。因此只把它列作相对当前 LLM baseline 的 token 改善，不能写成全面优势或完全正确的时区处理。

## Validation 上的局部修订确实改变了失败方式

v1 court 的 ours 在已经读取并使用 Skill 后仍漏了两项必答 No（45/47），说明“注入成功”不能替代方法验证。第二版用相同反例改进“必答 / 可选 / court-filled 分类”和独立预期集合检查，并保持已通过的 scheduler 正文不变。TokenDance 复验两组均 2/2；ours 合计 287,333 tokens，比 LLM 346,513 少 17.08%。这是开发集改善，为进入冻结测试提供依据；不能用该验证成绩替代最终 test 的成本退化。

完整逐运行注入、读取与实际使用证据见 [INJECTION_REPORT](INJECTION_REPORT.md) 和 [evidence.json](evidence.json)。方法实际使用依据后续工具动作，不依据模型自述或隐藏推理。

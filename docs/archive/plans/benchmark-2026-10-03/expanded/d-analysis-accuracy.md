---
added: 2026-10-03
---

# D-分析准确性

> 历史来源：本页为2026-10-01 至 10-03 的历史方案，2026-10-07 从团队 Vault 迁入。原位置：`项目/Orbit/benchmark/后续扩展/D-分析准确性.md`。正文与原有日期、结论保留，仅整理导航和空白；私人会话定位不公开。本文中的“当前”、TODO、测试数量和执行命令仅对原文基线成立，本次没有重新验证，也不自动形成任务或授权。现行入口：[源码文档](<../../../../../evals/README.md>)。

[总入口](<overview.md>) · [共同协议](<protocol.md>) · 执行：S4

目标：覆盖八族分析，以及任务关系、统计输出、语义模型和 judge。确定性事实用独立金标；语义判断用独立人工标签。规则自己生成的答案不能再用来证明规则准确。

| ID | 优先级 | 对象与样本 | 指标 / 关键反例 | 入口或缺口 |
| --- | --- | --- | --- | --- |
| D01 | P0 | Cost / Time：手算模型调用、缓存、并行区间 | 计数精确一致；Token 不重复、区间并集、未知不补零 | `analytics/cost_time`、bottleneck 与 duration / model_usage 契约测试 |
| D02 | P0 | Respond：调用起止、失败、重试、子代理 | 配对 / 状态 / 失败分类精度；缺结束、重 ID、工具成功≠目标完成 | `analytics/respond` 与关系测试 |
| D03 | P0 | Interaction：确认、纠偏、介入、重复要求 | 命中 Precision；完整池再算 Recall/F1；正常补充不能误判纠偏 | `analytics/interaction`、独立真人标注 |
| D04 | P0 | Task：任务边界、类型、目标、工作图 | 边界 / 成员归属 F1、任务类型混淆矩阵、版本边有效率 | `analytics/task` / `work_graph`；任务金标待复核 |
| D05 | P0 | Preference：显式偏好、作用域、撤回、冲突 | 抽取 P/R/F1、scope 与撤回准确率；不能把任务要求当长期偏好 | `evals.analytics.preference_local`、preference 测试 |
| D06 | P0 | Instruction：动作、约束、格式、验收要求 | 要素 P/R/F1、引用保真；提到“测试”不等于已验证 | instruction quality / functional / format 测试 |
| D07 | P0 | 主观 Outcome：认可、否定、混合、模糊、目标缺失 | 分类矩阵、覆盖与 abstain；客气用语不能代替认可 | `evals.analytics.subjective_outcomes`、独立标签 |
| D08 | P0 | 客观 Outcome：检查结果与产物版本 / 验收集合绑定 | 完整目标验收准确率；部分通过、过期检查、无版本保持未知 | `analytics/outcome`、acceptance / validation 测试 |
| D09 | P0 | 问题、瓶颈、时刻、推荐依据与原文证据 | 证据存在 / 范围 / 时间有效率；语义支持 Precision、覆盖率 | `scripts/check-feature-diagnostics.sh`、pipeline / probe；真实诊断标签待补 |
| D10 | P1 | overall / session / project / model / UI 统计一致 | 分母、归属、统计值与跨视图守恒；小样本 / 缺失展示一致 | `tests/regression/test_analysis_equivalence.py`、统计与 presentation 测试 |
| D11 | P1 | semantic facet / cascade、重排的真实模型输出 | JSON 合法率、引用有效率、人工一致率、标签精度、成本 / 超时 | `facet_quality` / FakeEngine 只验证机械契约；真实模型需独立标签与授权 |
| D12 | P2 | LLM judge 与校准、交换顺序、模型升级 | 与人工金标的混淆矩阵、κ、顺序不一致率、校准误差 / 漂移 | 需双人金标与真实 judge；未校准不能充当真值 |

## 标注设计

1. 冻结标签说明和证据单位，先做小批试标，分歧经讨论后冻结定义；正式测试集不再用来调规则。
2. 快速抽检：每个核心检测器 30 个命中，标 confirm / inaccurate / unknown，只能报告命中精度与 n。
3. 完整质量：另抽具有代表性的正例、负例、近似负例、多任务和缺失样本，对完整样本池标注，才计算 Recall/F1 与混淆矩阵。
4. 多标注者覆盖同一子集，标签先独立提交再仲裁；一致性与算法准确率分开。一个人复看两次不算两个独立标注者。
5. 标签 unknown 与系统 abstain 分别统计；不只挑系统有答案的样本报告总体“准确率”。

建议至少 20–50 个完整主会话起步，兼顾中英文、短 / 长、单 / 多任务、子代理、失败、正常协作。它是覆盖建议，不保证每类都有足够统计量。人格 / 风格文案只评事实支持、可理解性和自述一致性，不作心理测量有效性声明。

## 可复用命令

```sh
uv run --locked pytest -q packages/backend/tests/bottleneck packages/backend/tests/analytics
uv run --locked pytest -q tests/regression/test_analysis_equivalence.py
uv run --locked python -m evals.analytics.subjective_outcomes
uv run --locked tandem eval run --suite pipeline --suite probe --suite facet_quality --no-store --json .local/benchmark/s4-suites-01.json
```

真实诊断在用户明确给出已有 canonical 快照后再加 `--home` 或 `--db`；不扫描新来源。先核对 `tandem eval list` 与各 suite 实现，报告 skipped 原因。这里的命令是入口清单，不意味着全部已验证通过。

## 交付与边界

按 D01–D12 交付金标说明、匿名化标注统计、精确差异 / 混淆矩阵、覆盖率、错误案例与证据。真实标签仅在本机保存；共享集必须是构造或经确认的脱敏材料。S4 不修改生产检测规则来迎合测试集，发现问题交对应 Issue；修复后另留原版结果，避免只报告修复后的赢家数字。

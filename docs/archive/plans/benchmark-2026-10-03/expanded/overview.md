---
added: 2026-10-03
---

# benchmark硬效果

> 历史来源：本页为2026-10-01 至 10-03 的历史方案，2026-10-07 从团队 Vault 迁入。原位置：`项目/Orbit/benchmark/后续扩展/benchmark硬效果.md`。正文与原有日期、结论保留，仅整理导航和空白；私人会话定位不公开。本文中的“当前”、TODO、测试数量和执行命令仅对原文基线成立，本次没有重新验证，也不自动形成任务或授权。现行入口：[源码文档](<../../../../../evals/README.md>)。

这份规划回答：**Orbit 的分析是否可信，推荐是否让接下来的任务做得更好，以及这些效果能否复现。** 共八类、60 项，可以交给多个 session 独立准备、实现和运行，再用同一份冻结协议汇总。

状态：AI 整理的评测提案，待团队确认；本次只规划，没有运行 benchmark，没有产生效果数字，也不新增 MVP 功能承诺。产品取舍由 `yhyfhgs` 负责，MVP 范围由 `yhyfhgs`、`MistyHuang03`、`genius-FXC` 共同确认。

## 先从这里开始

1. S0 按[共同协议](<protocol.md>)固定代码、样本、动作、预算和验收标准。
2. 按[并行 Session 执行说明](<session-prompts.md>)复制对应任务给新 session。现在能准备的先做；缺真人复核、checkpoint 或授权的实验保留缺口。
3. 第一轮优先 A01–A04、B01–B03、C01、D01–D09、E03–E04、F01–F06、G01–G03、H01–H03。先让主证据链闭环，再扩大矩阵。
4. S0 最后统一验收；session 各写自己的结果，不能同时修改总表、样本清单或公共评分器。

这里的“所有 benchmark”覆盖当前产品链路及已有 EV 方案。尚未实现、需要长期观察或外部服务的项目也列入，但单独标记，不为凑齐评测临时增加产品功能。

## 八类分类

| 类别 | 要回答的问题 | 主要指标 | 证据用途 | 执行 session |
| --- | --- | --- | --- | --- |
| [A 未来任务收益](<a-future-utility.md>) | 推荐后，未来任务是否更容易完成、少花资源？ | Pass@5k/10k/20k、成功配对 Token / 轮次 / 工具调用 / 墙钟差 | 核心硬效果 | S1 |
| [B 推荐质量](<b-recommendation-quality.md>) | 推荐是否选对动作，什么时候应该不推荐？ | Regret@1/@K、Harm、误触发、覆盖率 | 推荐决策的硬效果；反馈为辅助证据 | S2 |
| [C 个性化与时间稳定性](<c-personalization-stability.md>) | 是否真的用对这个人的历史，效果能否持续？ | 个性化增益、消融差、时间 / 缺失 / 跨项目退化 | 支撑“懂这个用户” | S3 |
| [D 分析准确性](<d-analysis-accuracy.md>) | 八族特征、任务与证据是否算对、识别准？ | 精确一致率、Precision / Recall / F1、覆盖率、证据有效率 | 效果成立的前提 | S4 |
| [E 资源与安装闭环](<e-resource-installation.md>) | 是否找得到、生成得对、装得上、撤得回？ | Recall@K / NDCG@K、兼容性、误拦、安装往返一致率 | 可执行性与产品闭环 | S5 |
| [F 数据完整性与鲁棒性](<f-data-robustness.md>) | 输入变化、损坏、并发和隐私边界下是否可靠？ | 对账差异、幂等 / 等价性、恢复率、越界 / 泄漏数 | 硬门禁 | S6 |
| [G 性能与规模](<g-performance.md>) | 数据多了是否仍快、资源开销多大？ | 吞吐、p50/p95、峰值 RSS、库体积、冷 / 热耗时 | 工程性能，不能替代效用 | S7，独占计时 |
| [H 界面与读者体验](<h-reader-experience.md>) | 用户是否能看懂、核验并完成闭环？ | 流程完成率、理解正确率、事实保真、操作时间 | 可用性与路演证据 | S8，含真人环节 |

## 当前可复用什么

代码核对基线：`Orbit-Labs-AI/Orbit-Source` 本地 HEAD `b9e6e0a09199093b75fd4abc7697b07c8eaf7500`。这里确认的是文件、接口和实现边界，**不是这些检查本次已经通过**。正式运行时以 S0 冻结的新 SHA 为准。

| 现有入口 | 可直接复用的部分 | 仍需补齐的部分 |
| --- | --- | --- |
| `evals/benchmark/{local,prepare,score}.py` | 时间切分、冻结推荐、待复核 / 执行格子、配对效用与 action sweep 评分 | 真人边界复核、精确任务 checkpoint、真实执行日志；raw-history 等策略的实际冻结与执行 |
| `evals/analytics/`、`evals/recommendation/` | 构造质量、关系诊断、推荐回放、扰动与原生导入验证 | 独立真实标签、未来任务收益、跨用户数据 |
| `tandem eval`、`evalrun/suites/` | pipeline、probe、recommend、recommend_replay、facet_quality、ai_ledger、privacy、install_roundtrip、readability、insights、realtime | 每个 suite 都要读其来源；FakeEngine / 构造得分不能写成真实模型精度 |
| `benchmarks/` | 导入、分析、推荐、Catalog、Gateway 的构造性能入口 | 统一硬件 / 负载 / 重复次数；部分脚本需补原始样本才能算 p95 |
| `pnpm check`、`pnpm check:ui` | 回归、契约、安装后与原型行为检查 | 自动测试不能替代真人读者、真实任务效果或 macOS 打包验收 |

现有 `ExecutionRecord.method` 只接受 `no_recommendation / generic / raw_history_llm / ours / oracle`。UI 画像、原生 memory、模型档位等新增对照需先由 S0 扩展冻结和评分协议；不能把新方法改名为 `ours` 混入已有分数。

## 优先级与完成标准

| 优先级 | 范围 | 完成的含义 |
| --- | --- | --- |
| P0 | 主收益、推荐决策、关键特征、安装与数据门禁、主流程 | 样本和对照齐全，能复跑；失败、未知、缺失都有分母和原因 |
| P1 | 消融、真实标签扩充、模型档位、规模、细分体验 | 解释“为什么有效 / 何时失效”，不靠更多任务掩盖 P0 缺口 |
| P2 | 长期装后、跨用户 / Agent、内置个性化对照、校准 judge | 数据与能力具备后运行，前置条件不具备就明确 unavailable |

优先级是这轮实验排程，不是对已有 MVP 范围的修改。任务数量只是建议起步规模，不构成统计功效保证。

每个结果都标清：真实配对执行、历史观察、构造数据、人工评价、性能计时。只在预算、验收和配对完整时用“实测提升”；自动时间隔离检查通过只表示协议检查通过。

## 建议第一轮规模

- A：先争取 20 个独立、已复核且可重放的任务。默认单用户 3 锚点 × 后续 5 任务至多 15 个任务格，重叠后独立任务更少；需增加预先确定的锚点或获授权用户才能扩大样本，不能事后挑任务凑数。
- 费用按 `Q = 冻结主研究的 (sample_id, task_uid) 对数` 计算，另报唯一任务 U，U≤Q。以 Q=20 为预算示例：A 的 3 方法 × 10k 共 60 格，上界 60 万 Token；这不是当前已有样本量。
- B：同样本冻结的 4 个已审阅 Skill + 不干预，Q=20 时共 100 格，10k 上界 100 万 Token；实际目录不足或动作不可执行时，S0 先确定可比较子集并另冻研究。
- 扩到三种预算后，A 在 Q=20 时为 180 格，上界 `20 × 3 × (5k + 10k + 20k) = 210 万 Token`。变体 / 更多锚点另增 Q；不把一次 20k 跑完的轨迹截短冒充低预算独立执行。
- 以上不包含未在格子里登记的数据准备、独立语义标注等费用；A/B 不预先假设能复用同一执行。所有实际调用由统一账本核算。
- D：先做构造金标与每个核心检测器 30 个命中抽检；要报告 Recall/F1，再增加独立完整标注的正负样本池。
- G：一轮预热、至少 3 次独立进程重复；交互延迟建议 200 次请求。H：先做 3–5 名读者的探索轮，报告个体结果与 n。

这轮最值得展示的三张图是：A 的同预算成功率与成功配对开销、B 的 Regret / Harm、C 的正确历史与消融差。D/F 的正确性证据和 G 的性能表附后。没有真实配对结果时，展示实验进度与缺口，不放预测的提升百分比。

## 来源与旧方案对应

以当前实现为事实来源，旧方案只用来核对覆盖范围；其中的数值门槛、MVP 归属和未来能力不自动视为已确认。

- [过去到未来 Benchmark](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/b9e6e0a09199093b75fd4abc7697b07c8eaf7500/evals/benchmark/README.md)：A/B/C 的冻结与评分基础。
- [EV 评测方案](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/b9e6e0a09199093b75fd4abc7697b07c8eaf7500/docs/plans/evaluation-module.md)：EV-01/01.1/01.2 → D/F；EV-02/02.1/03/04/04.1/04.2 → D；EV-05/05.1/05.2 → B/C；EV-06/06.1/13 → E；EV-07/07.1/08 → A/C；EV-09/09.1/10/10.1 → H；EV-11 → A/F/G；EV-12 → 共同协议；EV-14 → F。
- [质量评测入口](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/b9e6e0a09199093b75fd4abc7697b07c8eaf7500/evals/README.md)、[性能入口](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/b9e6e0a09199093b75fd4abc7697b07c8eaf7500/benchmarks/README.md)、[测试指南](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/b9e6e0a09199093b75fd4abc7697b07c8eaf7500/docs/development/testing.md)。

本目录只保存规划与无隐私的汇总入口。后续代码、数据集契约和维护文档归 Hackathon 仓库；真实日志与执行明细留在各自本机忽略目录。执行进度以 GitHub Issue 为准，这里不再维护第二份任务状态表。

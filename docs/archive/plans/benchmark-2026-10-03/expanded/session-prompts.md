---
added: 2026-10-03
---

# 并行Session执行说明

> 历史来源：本页为2026-10-01 至 10-03 的历史方案，2026-10-07 从团队 Vault 迁入。原位置：`项目/Orbit/benchmark/后续扩展/并行Session执行说明.md`。正文与原有日期、结论保留，仅整理导航和空白；私人会话定位不公开。本文中的“当前”、TODO、测试数量和执行命令仅对原文基线成立，本次没有重新验证，也不自动形成任务或授权。现行入口：[源码文档](<../../../../../evals/README.md>)。

[总入口](<overview.md>) · [共同协议](<protocol.md>)

本轮只准备任务包，由你之后开 session 执行；不在当前聊天自动启动多个任务。建议先开一个 S0 协调 session，冻结一次共同输入，再把独立类别分发出去。

## 启动顺序

| 阶段 | 做什么 | 可以并行的工作 | 不能抢跑的工作 |
| --- | --- | --- | --- |
| 0：冻结 | S0 核对最新代码、数据授权、任务 / 动作 / 验收 / 预算，建立执行清单 | S4/S5/S6 准备构造样本；S7 准备计时脚本；S8 准备读者材料 | 真实执行、外发历史、安装真实配置 |
| 1：准备和检查 | S1 接执行器；S2 登记 action sweep；S3 做本地消融；其余跑非计时检查 | 文件范围和输出目录分离后可并行 | 改公共契约、评分器、同一冻结快照 |
| 2：测量 | 前置条件具备后跑 A/B/C；S4 做真人标签，S8 做读者轮 | 不抢同一 checkpoint、数据库或 API 配额的执行 | 以 AI 替代真人复核；用缺失记录补零 |
| 3：性能 | S7 在单独机器或独占时段跑 G | 其他 session 只做轻量审阅，或切到另一台机器 | 同机大规模模型执行、导入、测试、构建 |
| 4：汇总 | S0 验证摘要、样本覆盖、重复、失败和统计，统一评分 | 各 session 处理自己结果的说明问题 | 各自改总分或只提交最好的运行 |

S1 的执行器若尚未就绪，S2/S3 可先完成队列、输入与统计准备，等待适配器交付；不能称为已执行。真人标签、第二用户、历史 checkpoint、模型数据传输授权等等待项与可自动完成的工作分开。

## 资源和文件归属

写代码的 session 各用隔离工作树与分支，按 Hackathon AGENTS 从最新 main 起步；先复用适合且无人并写的已有工作树。基于 S0 固定的研究版本运行，工作分支更新后记录新 SHA，不混用前后版本。纯运行可以复用同一只读代码 checkout，但不得在其中 checkout 分支、修改源码或共享可写运行目录。

| Session | 主责 | 独占新增 / 修改范围建议 | 输出 |
| --- | --- | --- | --- |
| S0 | 共同契约、冻结、分片、结果合并 | `evals/benchmark/{contracts,local,prepare,score,metrics}.py` 等公共文件、共同测试 | `frozen/`、`merged/` |
| S1 | A、真实执行适配 | 需要时新增 `evals/benchmark/execution/` 与专属测试 | `s1/run-*/` |
| S2 | B、动作质量与排序统计 | 需要时新增 `evals/recommendation/benchmark_quality.py` 与专属测试 | `s2/run-*/` |
| S3 | C、消融与时间变体 | 需要时新增 `evals/benchmark/ablation_report.py` 与专属测试 | `s3/run-*/` |
| S4 | D、八族金标与语义质量 | `evals/analytics/` 的质量脚本与专属构造夹具 | `s4/run-*/` |
| S5 | E、目录 / 生成物 / 安装 | `evals/recommendation/catalog.py`、专属安装 / 检索评测与夹具 | `s5/run-*/` |
| S6 | F、数据 / 隐私 / 恢复 | `evals/analytics/robustness*.py` 与专属鲁棒性夹具 | `s6/run-*/` |
| S7 | G、工程性能 | `benchmarks/`；计时采集，不改业务语义 | `s7/run-*/` |
| S8 | H、读者 / UI 流程 | 专属 UI 评测与 reader 案例；产品页面修复另立任务 | `s8/run-*/` |

这些是必要时的代码范围建议，不要求先建空目录或再造评测框架。S4 不编辑 S6 的 `robustness*`；S2 不编辑 S5 的 `catalog.py`。根配置、锁文件、公共 fixture / conftest、生产算法和其他 session 的文件先交 S0 协调，不能擅自一起改。

同一工作树的依赖安装 / 构建由一个 session 完成；其他 session 消费已准备环境。SQLite、app.db、服务端口、缓存和安装根各自独立；输出目录必须新建，失败重试新建 attempt，不覆盖原日志。S0 的冻结包只读共享，注意原生文件引用并不会因为数据库复制而自动隔离。

A/B/C 的任务领取以统一 run 清单为准，按稳定任务身份分片；同时属于多个锚点的任务保留关联，不把重复任务算独立 n。一个 task 的所有方法 / 动作由同一执行编排负责，避免各 session 使用不同环境。运行量大时再分 S1a/S1b 等执行分片，方法、预算和配额规则不变。

模型调用建议先从每个 provider 总并发 2 起步，再按实际限额调整；这个并发上限由 S0 统一控制，不能每个 session 都各自开 2 路。冻结最大格子数、Token 总额和重试上限。此处的建议不是对付费调用或外发数据的授权。

## 少开几个 session 的合并方式

| 可用数量 | 建议安排 |
| --- | --- |
| 4 个 | S0+S8；S1+S2；S3+S4；S5+S6+S7。最后一组内部串行，G 单独排独占窗口 |
| 6 个 | S0+S8；S1；S2+S3；S4；S5+S6；S7 |
| 9 个 | S0 加 S1–S8，各一类；受执行器 / 数据 / 真人和独占计时依赖约束，不等于九个重负载进程同时跑 |

大多数加速来自标签、脚本、质量检查和独立执行格子的并行，不来自多个 session 反复跑同一套 `pnpm check`。

## 可直接复制的启动 Prompt

每个 block 是一个独立任务。代码仓库工作目录设为 `Action Mesh/Hackathon`；规划位于旁边的 `../team-hub/Hackathon/benchmark/`。先核对路径与本轮冻结版本，保留已有修改。当前文档是提案，不把其中尚未确认的产品功能当实现授权。

### S0：冻结与协调

```text
请执行 Orbit benchmark 的 S0。阅读 ../team-hub/Hackathon/benchmark/benchmark硬效果.md、共同协议.md、并行Session执行说明.md，并遵守仓库 AGENTS。
先核对当前实现，准备冻结代码 / 环境 / 数据 / 任务 / 动作 / 预算 / 验收清单；已有 canonical 数据、checkpoint、真人复核和外部调用授权都逐项核实，缺少则记录，继续完成独立准备工作。
优先复用 evals/benchmark/local、prepare、score 和既有 evalrun。明确三条首轮方法以及各 session 的只读输入、独占输出、运行格子、文件归属和资源配额。先用构造样本验证协议；不要把待填字段填成真实测量。
你是公共契约与最终汇总的唯一写入方。收到各类别交付后验证摘要、重复 / 缺失、对照公平性并统一评分，生成脱敏总报告。源码变动按仓库要求检查、小步提交和正常 PR，不合并他人 PR；不自动向其他聊天发消息或创建聊天。
```

### S1：未来任务收益

```text
请执行 Orbit benchmark 的 S1。阅读 ../team-hub/Hackathon/benchmark/A-未来任务收益.md、共同协议.md、并行Session执行说明.md，并遵守仓库 AGENTS。
优先 A01–A04，先核实 S0 冻结包与待执行格子。补齐必要的受控执行适配，仅在已复核、有精确 checkpoint 且授权充分的任务上执行 no_recommendation / generic / ours 的 10k 配对研究。
每格恢复同一环境，记录实际干预正文、推荐及执行 Token、验收、停止原因和原始日志摘要。不能用历史观察或构造结果冒充真实配对；无条件的格子列为缺失。A05–A07 只在条件具备后扩展。
只写你的分配范围和 s1/run-*，不修改公共协议、样本或评分器。交付 executions.json、metrics.json、run-manifest.json、report.md 与缺口清单；遵循仓库检查与提交规则。
```

### S2：推荐质量

```text
请执行 Orbit benchmark 的 S2。阅读 ../team-hub/Hackathon/benchmark/B-推荐质量.md、共同协议.md、并行Session执行说明.md，并遵守仓库 AGENTS。
优先 B01–B03，在 S0 冻结动作集上准备并完成包含 no_intervention 的完整 10k action sweep，复用 S1 已验证执行适配器；按统一清单领取任务，不与 A 重复抢跑。
计算 Regret@1/@3、Harm 和无需干预误触发；候选缺执行时保持 unproven，不在不完整动作集上造 oracle。B04–B06 另报相关性、解释与曝光，不把点击当收益。
只写分配范围和 s2/run-*，不改候选集、公共评分器或 S5 的 catalog 文件。交付执行记录、效用矩阵、指标、报告和缺失清单；遵循仓库检查与提交规则。
```

### S3：个性化与时间

```text
请执行 Orbit benchmark 的 S3。阅读 ../team-hub/Hackathon/benchmark/C-个性化与时间稳定性.md、共同协议.md、并行Session执行说明.md，并遵守仓库 AGENTS。
先对 S0 冻结输入完成 C01–C04 的单因素本地重放，记录 full_system / structured_features / task_context_only、窗口、历史缺失与跨项目的输入摘要、覆盖和推荐变化。
效用必须另有相同任务与预算的配对执行。wrong-user 必须是独立获授权用户；raw-history、UI-profile、原生 memory 等未具备冻结契约时只交付接入缺口，不伪装成现有 method。
只写分配范围和 s3/run-*，公共协议变更交 S0。交付逐变体指标、可比较运行清单、report.md；清楚区分稳定性诊断与实测收益，遵循仓库检查与提交规则。
```

### S4：分析准确性

```text
请执行 Orbit benchmark 的 S4。阅读 ../team-hub/Hackathon/benchmark/D-分析准确性.md、共同协议.md、并行Session执行说明.md，并遵守仓库 AGENTS。
覆盖八个特征族，先完成 D01–D09 的构造金标、证据与关系检查。制定独立人工标签说明与抽样，只有命中标签时只报 Precision，完整正负样本池具备后才报 Recall/F1。
区分 FakeEngine 机械检查、规则质量和真实模型准确性；你不能代填 independent_human 标签或用算法输出作为真值。真人环节待完成时继续整理混淆矩阵工具与缺口。
只写分配范围和 s4/run-*，不改 S6 的 robustness 文件，不为提高测试分数改生产规则。交付各族状态、金标统计、覆盖、错误案例与报告；遵循仓库检查与提交规则。
```

### S5：资源与安装

```text
请执行 Orbit benchmark 的 S5。阅读 ../team-hub/Hackathon/benchmark/E-资源与安装闭环.md、共同协议.md、并行Session执行说明.md，并遵守仓库 AGENTS。
先完成兼容性、生成物校验、安装往返与冲突矩阵 E02–E05；复用现有 install_roundtrip 与测试夹具，在独立临时配置路径运行。E01 检索金标与 S2 共用冻结目录。
不写用户真实 Agent 配置，不下载模型或擅自安装资源。E06 真实加载 / 触发缺授权或沙箱时记录缺口；安装到文件不等于已经加载或有收益。
只写分配范围和 s5/run-*。交付检索统计、兼容性 / 安装矩阵、预览和撤销证据、report.md；遵循仓库检查与提交规则。
```

### S6：数据与鲁棒性

```text
请执行 Orbit benchmark 的 S6。阅读 ../team-hub/Hackathon/benchmark/F-数据完整性与鲁棒性.md、共同协议.md、并行Session执行说明.md，并遵守仓库 AGENTS。
先跑构造数据的来源对账、全量 / 增量 / 幂等、scope、损坏恢复、并发隔离、隐私和 AI 账本检查。桥接测试先构建 TypeScript producer，不能静默跳过。
原生重建只使用 S0 明确获授权且已索引的文件清单，不新增来源；核验前后摘要。未知类型与缺失事实保持可见，隐私和注入样本用合成材料。
只写分配范围和 s6/run-*，避开 S7 独占计时。交付每项扰动的固定预期、实际差异、恢复与隐私证据、report.md；遵循仓库检查与提交规则。
```

### S7：性能与规模

```text
请执行 Orbit benchmark 的 S7。阅读 ../team-hub/Hackathon/benchmark/G-性能与规模.md、共同协议.md、并行Session执行说明.md，并遵守仓库 AGENTS。
先准备 G01–G07 的构造输入和环境清单，复用 benchmarks。正式计时使用单独机器或独占时段；其他 session 正在重负载运行时先做准备，不产出伪装为独占的性能数字。
优先 G01–G03，记录冷 / 热、预热、每次原始数据、阶段耗时、RSS 范围和负载。best-of 字段不能写成 p95；并发吞吐 G07 单独报告。
只写 benchmarks 分配范围和 s7/run-*。交付环境、原始测量、规模 / 延迟表、等价性验证与报告；遵循仓库检查与提交规则。
```

### S8：界面与读者

```text
请执行 Orbit benchmark 的 S8。阅读 ../team-hub/Hackathon/benchmark/H-界面与读者体验.md、共同协议.md、并行Session执行说明.md，并遵守仓库 AGENTS。
优先 H01–H03，核对实际已接线能力后完成构造 E2E、未知 / 错误状态和文案事实检查。准备隐藏版本且交换顺序的读者包，以及无需主持人提示的关键目标脚本。
评分与复述由真实读者提供，不把你自己的判断填作人工验收，不自动联系他人。没有正式 macOS target / 安装包时 H06 保持未实现，浏览器通过不等于原生 App 验收。
只写分配范围和 s8/run-*，性能时段避开浏览器重负载。交付流程结果、待填或已独立填写的匿名评分、理解错误与报告；遵循仓库检查与提交规则。
```

## 每个 session 的交付检查

结束时报告：完成了哪些 ID；输入 / 代码版本；实际命令；预计 / 完成 / 有效 / 缺失数量；核心指标与证据类型；失败与下一步；产物目录；提交 / PR（如有）。这份信息回到 S0 统一汇总。未运行就写未运行，缺真人 / 数据 / 权限就写具体缺口，不统一写成“测试通过”。

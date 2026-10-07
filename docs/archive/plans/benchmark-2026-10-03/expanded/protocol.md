---
added: 2026-10-03
---

# 共同协议

> 历史来源：本页为2026-10-01 至 10-03 的历史方案，2026-10-07 从团队 Vault 迁入。原位置：`项目/Orbit/benchmark/后续扩展/共同协议.md`。正文与原有日期、结论保留，仅整理导航和空白；私人会话定位不公开。本文中的“当前”、TODO、测试数量和执行命令仅对原文基线成立，本次没有重新验证，也不自动形成任务或授权。现行入口：[源码文档](<../../../../../evals/README.md>)。

[返回总入口](<overview.md>) · [Session 分工](<session-prompts.md>)

状态：待确认的执行协议。S0 在开始测量前冻结；其他 session 消费同一版本，不能各自调整样本、阈值或统计口径。

## 一、证据与状态

| 证据 | 能支持的结论 | 不能混成什么 |
| --- | --- | --- |
| `paired_execution` | 同任务、同环境、同预算的实测比较 | 不同难度任务的前后对比 |
| `historical_observation` | 历史中观察到了什么 | 安装 / 推荐造成了改善 |
| `constructed_execution` / 构造夹具 | 确定性行为、边界与关系验证 | 真实用户平均收益 |
| 独立人工标签 | 标签定义范围内的准确性、理解与偏好 | 生产成功率或心理测评 |
| 性能计时 | 指定硬件、规模和负载下的速度 | 其他设备上的 SLA |

执行层用 planned / ready / running / completed / blocked / failed；证据层沿用评分器的 measured / constructed_only / unproven / invalid。尚无入口写 not_implemented，缺第二用户等写 unavailable，二者只作计划注释，不强塞进现有 JSON enum。`status=passed` 可能仅指不变量检查通过；汇总必须读到指标自己的状态。

## 二、一次冻结包含什么

冻结清单至少记录以下内容，现有 `study-manifest.json` 不支持的元信息另存伴随清单，不私自加字段破坏严格契约：

| 对象 | 必须固定的内容 |
| --- | --- |
| 代码 / 环境 | Git SHA、依赖锁摘要、Python 3.13 / Node 版本、OS / 硬件、harness、模型与推理档位、工具与权限 |
| 数据 | 用户匿名 ID、授权范围、快照摘要、来源覆盖、时间范围、任务抽样规则、去重规则、train/dev/test 划分 |
| 任务 | task_uid、真人目标、边界证据、独立复核、任务开始前文件及配置 checkpoint、验收检查定义和摘要 |
| 推荐 | t0、可见历史和 available_at、输入摘要、固定资源版本与正文摘要、候选动作集、当时 Top-1 / Top-K |
| 实验 | 方法、seed、预算、运行顺序、最大尝试数、停止规则、主指标、次指标、排除条件、最小有意义差异 |
| 产物 | 原始日志摘要、推荐调用与执行调用账本、验收输出、运行错误、缺失原因、研究与评分器版本 |

精确 checkpoint 不只有 Git commit：未提交文件、任务输入、依赖、受控配置、工具版本和必要外部状态都需可恢复。无法恢复就不能把历史任务当成可重放实测；改用新建的前瞻研究，不重写过去。

任务是一个真实用户目标，不是消息、工具调用或文件。主会话、子代理、重试和 review 不增加独立任务数。禁止运行后删除难例、换验收条件或择优保留 seed。

## 三、时间与方法

主设置沿用现有协议：7 天历史，最多 72 小时内后续 5 个任务；3 个滚动锚点只作时间覆盖，重叠任务要去重报告。历史窗口 `[t0−7d, t0)`；未来只用于验收。标注、语义观察、配置与资源都按自己的可用时间判定，不能用后来补齐的事实回填 t0。

冻结执行的三条首轮方法：

- `no_recommendation`：不加入 Orbit 干预；基础 Agent 配置保持一致，已有原生 memory / rules 不偷偷关闭。
- `generic`：预先固定的通用推荐，不根据未来任务挑选。
- `ours`：只用 t0 前信息选择的、当时即可执行的 Top-1；`needs_context` 不能当成已可执行。

`raw_history_llm` 和 `oracle` 已出现在 enum，但现有准备包并不等于已冻结、已执行这些策略。raw-history、UI-profile、原生个性化对照及模型档位研究，须先完成策略和评分兼容工作。事后 action oracle 是 B 类效用上界，不是能提前部署的方法。

资源或模型在历史 t0 是否已存在不能证明时，结论写“当前资源与模型上的历史重放”，不声称当时可部署。任何训练 / 调参使用 dev 集；最终 test 集只评一次，修改方法后开新版本研究。

## 四、预算和统计

沿用现有执行契约的默认值：模型 `gpt-6.1-sol`、effort `medium`，5k / 10k / 20k 总 Token，20 轮、50 次工具调用、300 秒。S0 核对实际执行器是否支持这些条件；不支持则先改协议并冻结新研究，不能默默替代模型。

总 Token = 未缓存输入 + 缓存读 + 缓存写 + 输出 + 推荐自身调用开销。输入的供应商口径若包含缓存，要先规范化成互斥桶，不能重复计量。推荐是共享前置计算时，预先固定各任务的分摊办法，另报实际总账；未知成本保持 null。费用只有固定价格快照齐全才计算，不拿当前价格回填历史。

`Pass@10k` 是 10k 总 Token 及其余预算内通过完整验收的比例，不是“尝试十千次”。预算耗尽 / 执行错误按冻结规则计入失败；未运行、取消、Token 不可测、验收缺失保持缺失并阻止完整 headline。评分器区分这些状态，不能通过只算完成者掩盖缺失。

每次低预算执行独立从同一 checkpoint 开始。主比较 seed=0；7/11/19 是现有缺失历史扰动的种子，不自动变成执行重复。新增执行 seed 要同步计划和评分器。若供应商不支持固定 seed，记录该限制；编排 seed 不等于模型随机性受控。

建议起步 20 个独立任务，正式扩大时争取多个用户、项目和任务类型。预先分层，报告每组 n。不能从单用户、重叠锚点或同任务重复运行推断“所有用户”。

- 主指标：`ΔPass@10k = Pass_ours − Pass_no_recommendation`，同时报告绝对通过数和完整分母。
- 次指标：5k/20k 成功率；仅在双方成功配对上计算 Token、轮次、工具调用与墙钟差。这个子集存在选择性，要同时展示主成功率。
- 每任务相对 Token 改善 `(baseline−ours)/baseline`；基线为 0 时相对值为 null，保留绝对差。
- 不把消息和锚点当独立抽样单位。需要区间时按用户 / 独立任务簇重采样；样本簇太少则描述性报告，明确区间不稳定。
- 门禁与效果分开：来源未变、无越界、契约 / 冻结完整等应全部通过；收益阈值由 S0 在看结果前登记。没有预设阈值时只报告估计，不能事后宣布“达标”。

## 五、现有命令与前置条件

以下命令从 Hackathon 仓库根执行；真实来源只在用户明确选定已有 canonical 快照后运行。此文不授权读取所有本机来源、向外部模型发送历史或安装到真实配置。

```sh
# 冻结首轮研究；替换 /path/to/canonical，输出目录必须未存在。
.venv/bin/python -m evals.benchmark.local --home /path/to/canonical --output .local/benchmark/study-main-01 --history-days 7 --future-counts 5 --anchors 3

# 独立留存打印的摘要，后续 prepare / score 均核对。
shasum -a 256 .local/benchmark/study-main-01/study-manifest.json

# 生成待复核与待执行格子，不会替人填写答案或执行任务。
.venv/bin/python -m evals.benchmark.prepare --study .local/benchmark/study-main-01 --output .local/benchmark/prepared-main-01 --expected-study-digest FROZEN_SHA256

# 各 session 执行结束，经 S0 验证和合并记录后评分。
.venv/bin/python -m evals.benchmark.score --study .local/benchmark/study-main-01 --executions .local/benchmark/merged/executions.json --task-reviews .local/benchmark/merged/task-reviews.json --output .local/benchmark/score-main-01 --expected-study-digest FROZEN_SHA256
```

`FROZEN_SHA256` 是需替换的占位符。不要把上面的 prepare 当 executor；仓库现有工具不会替你重放真实任务、生成真人复核或证明日志真实性。S1/S2 需先完成执行器接入或受控人工运行，并校验实际 Skill 正文与记录摘要一致。

当前评分器默认枚举五方法和三预算。首轮只执行三方法的 10k 时，完整的对应行可以有自己的 measured 状态，而全局 forward_utility 仍可能 unproven；必须保留这个区别，不虚填 raw-history / oracle 或未跑预算以获得总绿灯。prepare 的主格子与 score 的主研究采用 correct_history、7 天、5 任务；其他变体另读 variations，S0 核对实际清单再估算费用。

## 六、并行产物与单写入规则

统一的本机根目录为 `.local/benchmark/<study-id>/`，每个 session / run 使用新目录，例如 `s4/run-001/`。这里只约定形状，不在本次生成运行数据。

```text
<study-id>/
  frozen/                 S0 创建后只读
  s1/run-001/             S1 独占，其他 session 只读
  s2/run-001/             S2 独占
  ...
  merged/                 仅 S0 写入
```

每个 session 交付 `report.md`、`metrics.json`、`run-manifest.json` 和日志位置 / 摘要。A/B 另交严格符合 `ExecutionRecord` 的 `executions.json`；真人任务复核单独交 `task-reviews.json`。通用指标至少包含 benchmark_id、证据类型、代码 / 数据摘要、预计 / 完成 / 有效 / 失败 / 缺失 n、分子 / 分母、值与单位、条件、限制、下一步。没有数值写 null + reason，不填 0。

原始执行唯一键要含 study、sample、task、method、action、purpose、budget、seed、attempt；重复上传不能增加 n。重试由计划限定并保留失败日志，不采用 best-of。A 的 method_comparison 与 B 的 action_sweep 默认独立登记；若想复用日志，由 S0 核对包括干预、推荐开销在内的全部条件与评分契约，只记一次实际账单。

真实数据库、日志、输入、人工标签和可反识别的结果均留在 `.local`，不能写入 team-hub。共享材料只保留脱敏聚合、构造样本、代码和方法。数据库快照可能仍依赖原生来源文件；S0 要核验其只读引用、哈希和可访问性，不能只复制 `tandem.db` 就假定完整隔离。

## 七、统一收尾

S0 检查每个 session 的输入摘要一致、缺失完整、日志可回溯、没有测试集调参，再汇总。源码修改按仓库规范做小步提交和正常 PR；不替任何其他成员审查、合并或关闭 PR。整合后的代码执行 `bash scripts/bootstrap.sh`、`pnpm check`，涉及原型再跑 `pnpm check:ui`；计时期间避开这些重负载检查。

最终材料分为核心收益、推荐决策、个性化证据、工程可靠性、用户评价五部分；逐条标注证据级别、版本与范围。若只有构造数据和自动回归，结论就是“协议 / 实现可验证，真实效果待测”。

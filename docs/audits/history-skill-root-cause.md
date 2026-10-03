# 12 条历史为何只留下 1 rule、1 hook、0 skill

原实验版本的结论：历史已经导入，但旧链路主要保留了工具失败和命令类别，未从完整轨迹归纳任务方法。当时 Pi 标签过滤又使目录中的 62 个 Skill 全部无法进入检索；唯一来自内置知识库的排错 Skill 虽通过 gate，却被同一问题最多两项的名额挡住。序列化和 Pi 注入不是这次 Skill 消失的位置。后续主线已经修复可移植 Skill 的跨 Agent 兼容，不能把这项旧过滤结论套到当前版本。

这是开发诊断，不能当作新的 held-out 效果。原实验 run-003 / run-004 的实例均已暴露；后续隔离约束见[评测协议](../plans/history-skill-learning.md)，机制依据见[研究记录](../research/history-skill-learning.md)。

## 证据与重放边界

- 原始目录：本机 `/Volumes/Data/OrbitBenchmark/study/run-004`；复制 app / canonical / analytics / catalog 数据库后诊断，不修改原运行。
- 推荐输入 SHA-256：`da2279b19e87e3f706e164953556796a22c7255b5417788dc707adcbb5a3cbff`。
- 已提交代码重放：`4aa8b343`；完整逐候选 JSON：`run-005/funnel-legacy-history-committed.json`。它复用旧分析输入和旧目录快照，不能描述成一次全新数据导入。
- 旧完整性记录：12 sessions、880 events、459 records；unknown / unparsed / capture errors 均为 0。
- 后端漏斗 API 保存 candidate ID、类型、分数、证据与每一级原因；原始捕获完整性依然由导入验证报告证明，未观测的 runtime 数据保持 unknown。

另以 `447d88fe` 的产品代码通过真实 Gateway 完成一次重新导入，结果保存在 `run-005/legacy-e2e-current`：12 sources / sessions、459 mapped records、880 events、198 tool calls，12 个源引用和 459 条记录 hash 全部验证通过，unparsed=0。分析 worker → 推荐运行 → 漏斗 API 均通过，14.313 秒、0 模型调用，最终仍是 1 hook + 1 rule。该入口脚本当时是开发中的 `evals/skill_learning/pipeline.py`，产品代码已提交；它补足快照重放不等于新导入的边界。

合并主线 `47c15b85` 后又以 `8da9178c` 重跑正式 API 链路，保存在 `run-005/legacy-e2e-merged`：12 段历史、9.742 秒、0 模型调用、`rec-engine-v2.4`。当前目录有 2,022 项，Pi 预过滤保留 1,122 项，其中全部 608 个 Skill 都保留；这一兼容问题已经由主线修复。当前原始池变为 7 项（2 hook、2 rule、3 skill），评分和兼容均保留 7 项，阈值保留 4 项（1 hook、1 rule、2 skill），去重仍保留 4 项，最终因 `cap:problem` 排除两项 Skill，仅留下 1 hook + 1 rule。新增的目录 Skill 是 `temporal-developer`，并非历史文档操作方法。新目录与新分析版本同时变化，这次重放不构成兼容修复的单因素因果实验。

## 候选在哪里丢失

| 阶段 | 观测 | 含义 |
| --- | --- | --- |
| History ingestion | 12 条有效会话 | 不是空历史或导入失败 |
| 文件与任务表示 | 190 个 bash 调用的规范化 `files` 都为空；文件类型画像主要只剩 `.py`、`.json` | bash 脚本中的 PDF / DOCX / XLSX 路径和操作过程没有进入这一特征表示。路径提及也不能直接冒充已发生的文件操作 |
| 重复流程 | 固定四步命令序列最多跨 2 会话，未到 3 会话门槛 | `python3` 等命令头相同不足以表示同一种方法；正确但不同写法的操作也难以形成严格序列复现 |
| Analytics problems | `unzip` 环境失败 5/9 为 active；另一类工具失败 1/6 未达阈值 | 主要关注摩擦问题，没有形成文档任务的执行程序 |
| Catalog 预过滤 | 665 项中 Pi 条件后仅 6 项，62 个 Skill 全部排除 | 目录声明 Agent 标签造成兼容召回损失，不能据此断言内容本身不兼容 |
| Feature retrieval | Pi 0 项、Codex 16 项、不限 Agent 42 项 | 同一画像的检索受 Agent 条件明显影响 |
| Raw candidates | 3 项：hook、rule、skill 各 1 | 都围绕同一个环境失败问题 |
| Scoring / gates | 3/3 通过，priority 为 35.43、32.82、25.66 | 排错 Skill 并非在这一级因低置信度被淘汰 |
| Deduplication | 3/3 保留 | 这次不是过度去重 |
| Final recommendation | 2/3 保留；Skill 为 `cap:problem` | 同一问题最多两项，较高分 hook / rule 已占满 |
| Serialization / injection | 1 rule、1 hook 正常进入执行器 | 不能把上游未选中归因于注入丢失 |
| Runtime | 392 次 Hook 调用，0 次阻断 | Hook 在运行；这不证明它产生收益。没有 Skill 可激活 |

三项实际候选为：重复失败熔断 Hook、unzip 环境约定 Rule、系统化排错 Skill。最后一项只是通用排错方法，即便放开名额，也不是所需文档处理程序。

旧配置 `ai_generate=false`，实际没有生成模型调用。打开当前 AI expert 也不能直接解决输入缺失：它读取聚合问题、画像和候选，提供有界建议与扩展查询，不读取完整操作轨迹。既有 Skill 生成提示同样侧重摩擦补救，不能等同于跨会话程序归纳。相比之下，旧 LLM self-personalization 获得了完整历史文本；两条链路在有效方法信息上不对称。

## 无模型选择消融

消融只作用于已暴露快照；没有修改生产默认值、安装资源或调用模型。完整输出为 `run-005/legacy-selection-ablations.json`。

| 变化 | Raw | 最终 hook / rule / skill | 结论 |
| --- | ---: | --- | --- |
| 原选择 | 3 | 1 / 1 / 0 | 基线重现 |
| 关闭去重 | 3 | 1 / 1 / 0 | 去重不是本例根因 |
| 全局 top-k=3 或 10 | 3 | 1 / 1 / 0 | 加大全局列表仍受每问题名额限制 |
| 全局 top-k=1 | 3 | 1 / 0 / 0 | 只剩最高分 Hook |
| 每问题名额 2→3 | 3 | 1 / 1 / 1 | 排错 Skill 恢复，但没有新方法生成 |
| 放开 Agent 过滤 | 6 | 1 / 1 / 0 | 新增 3 个目录候选仍因来源未核验被挡住 |
| 放开 Agent，且每问题 3 项 | 6 | 1 / 1 / 1 | 仍只有原内置排错 Skill |

因此，单独提高 top-k、降低阈值或把所有目录项标成 Pi 兼容，都不足以构造缺失的方法。下一步需要有界读取用户选中的完整历史，跨会话归纳 activation / procedure / verification，保留证据，再把离线学习与新任务检索分开。是否有收益必须经过独立 validation；不能先承诺最终 test 一定超过基线。

## 已补的可观测性

推荐主链路记录原始池、评分、兼容、阈值、画像重叠、去重和名额；AI expert 的目录预过滤、证据拒绝和剩余名额也单独记录。持久化卡片被压缩或超出数量上限时，不再抹掉候选证据。Pi 执行记录 manifest 摘要、实际注入数量和成功读取 Skill 的事件；actual usage 仍须用后续工具步骤证明，不能用读取次数代替。

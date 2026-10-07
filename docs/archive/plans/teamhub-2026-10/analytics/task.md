---
created: 2026-10-02
added: 2026-10-02
---

# Task 任务

> 历史来源：本页为2026-10-01 至 10-03 的历史方案，2026-10-07 从团队 Vault 迁入。原位置：`项目/Orbit/分析模块/Task 任务.md`。正文与原有日期、结论保留，仅整理导航和空白；私人会话定位不公开。本文中的“当前”、TODO、测试数量和执行命令仅对原文基线成立，本次没有重新验证，也不自动形成任务或授权。现行入口：[源码文档](<../../../../modules/analytics/README.md>)。


## 本轮实现与验收（2026-10-02）

**代码、函数接入和五类测试已完成；真实语义质量和团队最终口径仍待确认。** 需求与回看账号：`MistyHuang03`；实现及技术验收：AI；人工确认人：未确认；合并由 `yhyfhgs` 决定。

代码从 `main` 的 `c97c818` 创建 `feat/analytics-preference-task`，实现版本 `d030c2a`，特征版本 `feature-analytics-v2`。[PR #13](https://github.com/Orbit-Labs-AI/Orbit-Source/pull/13) · [关联 Issue #4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4) · [完整五类验收报告](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/d030c2a3d3d4197cc8c9ed04054845fe26c4d47c/docs/backend/analytics/validation.md)。

下方原 Feature TODO 保留为最终口径确认清单；每项已完成的代码与测试在本页标出，不把 AI 技术验收写成团队已认可语义准确性。具体进度以 PR／Issue 为准。

| 验证类型 | 已完成的方法与结果 | 尚未证明的部分 |
| --- | --- | --- |
| 单元 | 两族共 29 项，覆盖六个入口函数及证据、清理、范围、缺失等共享函数；均通过。 | 不等于穷尽自然语言表达。 |
| 功能／mock | 3 项：Mock 数据服务经真实 API 路由，以及临时 SQLite → CLI／API 对照；均通过。 | 不覆盖生产网络与部署。 |
| 端到端／真实 | 固定原始历史日志 → 新 SQLite → CLI 完整 JSON → FastAPI ASGI，无 mock；重导入与原快照、API 与 CLI 记录均一致，证据 ID 合法。 | 尚无真实语义人工金标准；ASGI 不是 TCP 部署验证。 |
| 性能 | 100／1,000／10,000 条合成真人消息，各 3 次；耗时中位数约 0.029／0.326／3.320 秒；1 万条约 3,012 条／秒，Python 分配峰值 23.09 MiB。 | 关闭文本投影，不含导入／序列化；未测并发、10 万级或冲突密集长历史。 |
| 正确性／质量 | 30 个由 AI 编写的固定标签案例，加 1 个相容否定测试，均通过；正反例、否定、引文、未知和时间均可复现。 | 开发集不是盲测，不将通过率写成真实准确率。 |

新增测试 63 项；全库 **461 项通过**，Ruff 与差异检查通过。原有文本表示回归保留；单元／mock／质量进入常规 CI，真实数据和性能脚本显式执行。完整原文、真实 ID、数据库和端到端结果仅保留在开发仓库忽略的 `.local/semantic-families/`，本页只写汇总与合成例子。

## Feature TODO

- [ ] **任务领域 `domain`**：确定领域词表、提取规则和未知类别。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。
- [ ] **任务类型 `task_type`**：定义调研、编写、修改等类型及多标签规则。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。
- [ ] **任务标题 `task_title`**：生成可回溯到原始请求的简短标题。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。
- [ ] **任务目标 `task_goal`**：提取用户要达成的目标及变更记录。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。
- [ ] **预期产物 `expected_artifacts`**：提取交付物、格式和明确对象。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。
- [ ] **任务起止位置 `task_boundaries`**：定位任务边界，处理未结束和中途改题。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。
- [ ] **关联会话 `related_session_ids`**：保留跨会话任务关系及关联依据。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。

- [ ] **目标版本 `task_goal_history`：已实现及测试；团队口径待确认。** — `MistyHuang03`，[Issue #4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。

认领时在 TODO 后补 GitHub 账号和 Issue 链接；未完成项可备注“开发中／待验收”。

完成特征口径确认、函数接入和样例验收，并补上实现链接后再勾选。已有基础统计也按此条件核对。

[返回分析模块分类](<classification.md>) · [对照现有 Feature](<../feature-inventory-2026-10-02.md>)

> 本页初始特征口径、新增字段名和函数接口为 AI 整理草案，待团队确认；函数表列出建议接口，实际实现以关联代码和验收记录为准。

## 范围

描述用户在做什么，以及一个任务覆盖哪些记录。任务可以跨会话，一次会话也可以包含多个任务；边界尚不明确时保留候选与证据。复杂度可作为辅助标签；任务新颖度和精细的开放程度评分暂缓。

## 特征口径

| 字段 | 粒度／类型 | 定义与提取规则 |
| --- | --- | --- |
| `domain` / `task_type` | 任务 · 类别列表 | 依据用户请求和任务上下文提取；多领域可多标签，证据不足记未知，词表待确认。 |
| `task_title` / `task_goal` | 任务 · 文本 | 标题概括当前目标；目标改动另留版本和生效位置，不覆盖原始目标。 |
| `expected_artifacts` | 任务 · 对象列表 | 保留用户明确要求的产物及格式；实际生成的产物通过执行与结果记录关联。 |
| `task_boundaries` | 任务 · 事件位置 | 记录起止事件 ID、边界依据和待确认状态；未结束任务的结束位置留空。 |
| `related_session_ids` | 任务 · 会话关系 | 凭显式延续、任务 ID 或经确认的关系关联；同目录只能作为候选线索。 |

## 分析函数

| 建议函数 | 输入 → 输出 | 主要处理 |
| --- | --- | --- |
| `segment_tasks(events)` | 有序消息与事件 → 任务边界及关联记录 | 识别新任务、目标变化与延续，保留边界证据和未决候选。 |
| `extract_task_features(task_events)` | 单任务记录 → 领域、类型、标题、目标与产物 | 从真人请求提取，返回证据和缺失原因；标签词表单独版本化。 |
| `summarize_task_distribution(tasks, scope)` | 任务集合与筛选范围 → 领域／类型分布 | 按任务 ID 去重，说明多标签计数方式，并列出有效与未知任务数。 |

## 对接已有分析

[现有 Feature 一览](<../feature-inventory-2026-10-02.md>)中的 `top_terms`、`cluster_id` 和 `novelty` 可作为文本检索或分组线索；它们不能直接替代任务领域、任务边界或任务创新程度。

## 验收样例

- 一次会话先调研、后明确要求写代码：保留两个任务或目标阶段，并能定位切换位置。
- 同一任务明确在另一会话继续：保留两个会话关系，任务汇总去重；仅工作目录相同不自动合并。
- 用户只说“帮我处理一下”：未明确的目标、产物和类型保留未知。

## 补充特征与函数

先更新开头的 TODO 和对应表格，再在这里复制下面的小节补充细节。认领时填 GitHub 账号和 Issue 链接；实现进度以 Issue 为准，验收后勾选 TODO。

~~~markdown
### 新特征：名称

- 字段名、类型／单位、统计粒度：
- 定义与用途：
- 输入数据与证据定位：
- 提取规则／公式、缺失值与排除规则：
- 正例、反例和预期结果：
- 提出人／确认人（GitHub 账号）、Issue／实现链接：

### 分析函数：建议函数名

- 计算哪些特征、回答什么问题：
- 输入、输出、参数与依赖的特征族：
- 算法步骤、分母、缺失处理与适用范围：
- 验收样例、预期输出、实现与版本链接：
- 提出人／确认人（GitHub 账号）、Issue 链接：
~~~


## 本轮技术完成清单

- [x] `task/` 独立目录：任务分段、字段提取、分布、本族字典、版本化词表。
- [x] 原 `text.py` 的向量、聚类、投影移入 `task/representation.py`，旧导入继续兼容。
- [x] 三个分析函数接入 `/v1/analytics/tasks`；会话详情提供 task_ids 与 preference_ids。
- [x] 七项原定字段及 task_goal_history 有实现、证据、缺失处理和正反例。
- [x] 五类验证均已执行；跨会话身份以构造样例验证。
- [ ] 独立真实任务金标准、无明确提示的隐含换题、真实跨会话正例和人工语义验收。

[实现目录](https://github.com/Orbit-Labs-AI/Orbit-Source/tree/d030c2a3d3d4197cc8c9ed04054845fe26c4d47c/src/tandem_backend/analytics/task) · [单元测试](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/d030c2a3d3d4197cc8c9ed04054845fe26c4d47c/tests/analytics/test_task.py) · [功能测试](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/d030c2a3d3d4197cc8c9ed04054845fe26c4d47c/tests/analytics/test_functional.py) · [固定标签集](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/d030c2a3d3d4197cc8c9ed04054845fe26c4d47c/tests/fixtures/semantic-quality-v1.json) · [详细特征族说明](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/d030c2a3d3d4197cc8c9ed04054845fe26c4d47c/docs/backend/analytics/task.md)。

### 新特征：任务目标版本

- 字段名、类型／单位、统计粒度：`task_goal_history`，目标版本列表；每个 task_id 下保留 goal 与 evidence。
- 定义与用途：区分初次目标、明确修改与普通跟进，避免用最后一次目标覆盖过去的解释。
- 输入数据与证据定位：确认真人的直接消息；版本保留 event_uid、session_uid、seq、ts、原分句。
- 提取规则／公式、缺失值与排除规则：初次可识别动作成为目标；“目标改为”等明确修改追加版本；标题是当前目标前 60 字符；含糊输入的目标为 null，不生成想象的目标。
- 正例、反例和预期结果：“实现接口”后“目标改为编写脚本”有两个目标版本；“以后这个项目用中文”不替换任务目标；“帮我处理一下”保持未知。
- 提出人／确认人、Issue／实现链接：本轮 `MistyHuang03` 需求，AI 实现；团队语义确认待完成；[Issue #4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)、[PR #13](https://github.com/Orbit-Labs-AI/Orbit-Source/pull/13)。

### 分析函数：segment_tasks

- 计算哪些特征、回答什么问题：任务起止位置、关联会话、消息归属及开放边界。
- 输入、输出、参数与依赖的特征族：`(events, sessions)` → records、task_by_event、coverage；向 Preference 提供任务映射。
- 算法步骤、分母、缺失处理与适用范围：按会话和 seq 排序；首条可用请求建立候选；显式新任务、可信 task_id 或阶段词加新动作产生边界；最后消息／助手完成不算结束；未观察结束留 null。
- 验收样例、预期输出、实现与版本链接：调研 → 现在实现形成两个候选阶段；用户明确结束关闭边界；相同可信 task_id 可跨会话合并，仅同路径或 legacy_inferred 不合并。
- 提出人／确认人、Issue：`MistyHuang03` 需求；AI 技术验证完成、团队确认待完成；[Issue #4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。

### 分析函数：extract_task_features

- 计算哪些特征、回答什么问题：领域、类型、标题、目标及版本、预期交付物。
- 输入、输出、参数与依赖的特征族：经 semantic_messages 确认和清理的单任务消息 → 字段、label_evidence、missing_reasons、semantic_status；词表版本 task-taxonomy-v1。
- 算法步骤、分母、缺失处理与适用范围：本地中英词表提供 6 个领域、10 类动作；多标签，无法识别为 null；产出动词之后的明确对象才算预期产物；标签始终是规则候选。
- 验收样例、预期输出、实现与版本链接：“修复代码并编写报告”是 software／writing 与 debug／create；“解释 README.md”不生成预期文件；“测试字段”不算测试动作；见 `d030c2a`。
- 提出人／确认人、Issue：`MistyHuang03` 需求；AI 技术验证完成、团队确认待完成；[Issue #4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。

### 分析函数：summarize_task_distribution

- 计算哪些特征、回答什么问题：不同任务的领域／类型分布和未知覆盖。
- 输入、输出、参数与依赖的特征族：`(tasks, scope=None)` → task_count、domain／task_type 的 counts、rates、effective_n、unknown_n。
- 算法步骤、分母、缺失处理与适用范围：按 task_id 去重，分母为有该字段标签的任务数；未知单列；多标签比例之和可大于 100%；零分母 rates=null。
- 验收样例、预期输出、实现与版本链接：2 个任务只有 1 个带 create 和 debug，两标签各为 100%，unknown_n=1；相同任务跨两会话仍计一次。
- 提出人／确认人、Issue：`MistyHuang03` 需求；AI 技术验证完成、团队确认待完成；[Issue #4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。

## 真实数据表现与剩余工作

固定真实快照得到 **5 个候选任务边界，2 个有词表标签、3 个未知**；类型包括批改、修改、发布。可用真人消息只有 9 条，另有 918 条来源未知；2 个有效任务的 education 占比 100% 不能代表完整历史。真实日志重导入与原快照一致；两族 CLI／API 记录一致、证据都属于被允许的真人消息。

实际全流程：导入约 7.27 秒、含文本表示的 CLI 分析约 3.11 秒、Task API 约 2.59 秒、Preference API 约 2.54 秒。实现未引入外部模型。跨会话关联当前只有构造正例，真实数据没有可靠关联来源可验收。

下一步先补 origin、规范项目 ID 和 task_id 来源，再人工标注真实任务；隐含换题、远距离延续、一个长请求内多个任务、完整复合目标和代词仍待解决。任务新颖度／复杂度／开放度评分继续暂缓；原文本 novelty 只作为旧表示结果保留。

## 讨论

待确认领域／类型词表，以及“目标变化”和“新任务”的边界判定。

## 结论与下一步

确认后在这里记录结论、确认人（GitHub 账号）、依据和适用范围；实现与验收进度更新开头 TODO，并链接对应 Issue。

本轮结论：实现与技术验收已完成，待 PR 评审与团队语义确认；上述未完成项没有因测试通过而自动勾选。

补充验收：Codex review 提出的全局偏好变更漏识别、跨会话任务目标顺序两项已修复，并各增加一条回归测试；最新 head 已重新触发 review，评审是否完成以 PR #13 为准。

## 评审与合并状态（2026-10-02）

PR #13 的 `d030c2a` 已完成代码评审、安全评审和 CI；没有 P0/P1，安全评审未发现问题。本次用户明确指定仅 P0/P1 阻断合并，以下三项 P2 已在原评论说明暂缓理由并关闭线程，问题本身尚未修复：

- 同时间的跨会话任务目标仍可能由 session_uid 的排序决定，不能据此认定真实先后。
- 开场闲聊可能被当成任务候选起点，使候选任务数量或起始位置不准确。
- 子会话的未知来源可能进入语义 coverage 统计，使其保守地标成 partial；不会进入两族的真人语义提取。

已尝试按已审 SHA 使用 merge commit 合并；自动审批拒绝该动作，理由是仍缺少负责人 `yhyfhgs` 对 PR #13 的明确授权记录。PR 保持打开、尚未合并。此处记录技术检查和执行状态，不代替负责人授权或团队语义验收。

---
created: 2026-10-02
added: 2026-10-02
---

# Preference 主观偏好

> 本页是 2026-10-01 至 10-03 的历史方案，内容待团队确认；文中的“当前”、TODO、测试数量和命令只对当时成立。现行入口：[分析模块](<../../../../modules/analytics/README.md>)。

## 实现与验收（2026-10-02）

**代码、函数接入和五类测试已完成；真实语义质量和团队最终口径仍待确认。** 需求与回看账号：`MistyHuang03`；实现及技术验收：AI；人工确认人：暂无；合并由 `yhyfhgs` 决定。

代码从 `main` 的 `c97c818` 创建 `feat/analytics-preference-task`，实现版本 `d030c2a`，特征版本 `feature-analytics-v2`。[PR #13](https://github.com/Orbit-Labs-AI/Orbit-Source/pull/13) · [关联 Issue #4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4) · [完整五类验收报告](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/d030c2a3d3d4197cc8c9ed04054845fe26c4d47c/docs/backend/analytics/validation.md)。

下方的 Feature TODO 作为最终口径的确认清单，各项已完成的代码与测试均在本页标出；具体进度以 PR／Issue 为准。

| 验证类型 | 已完成的方法与结果 | 尚未证明的部分 |
| --- | --- | --- |
| 单元 | 两族共 29 项，覆盖六个入口函数及证据、清理、范围、缺失等共享函数；均通过。 | 不等于穷尽自然语言表达。 |
| 功能／mock | 3 项：Mock 数据服务经真实 API 路由，以及临时 SQLite → CLI／API 对照；均通过。 | 不覆盖生产网络与部署。 |
| 端到端／真实 | 固定原始历史日志 → 新 SQLite → CLI 完整 JSON → FastAPI ASGI，无 mock；重导入与原快照、API 与 CLI 记录均一致，证据 ID 合法。 | 尚无真实语义人工金标准；ASGI 不是 TCP 部署验证。 |
| 性能 | 100／1,000／10,000 条合成真人消息，各 3 次；耗时中位数约 0.029／0.326／3.320 秒；1 万条约 3,012 条／秒，Python 分配峰值 23.09 MiB。 | 关闭文本投影，不含导入／序列化；未测并发、10 万级或冲突密集长历史。 |
| 正确性／质量 | 30 个由 AI 编写的固定标签案例，加 1 个相容否定测试，均通过；正反例、否定、引文、未知和时间均可复现。 | 开发集不是盲测，通过率不代表真实准确率。 |

新增测试 63 项；全库 **461 项通过**，Ruff 与差异检查通过。原有文本表示回归保留；单元／mock／质量进入常规 CI，真实数据和性能脚本显式执行。完整原文、真实 ID、数据库和端到端结果仅保留在开发仓库忽略的 `.local/semantic-families/`，本页只写汇总与合成例子。

## Feature TODO

- [ ] **偏好内容 `preference_statement`**：提取用户明确表达或确认的偏好原文。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。
- [ ] **偏好类型 `preference_type`**：定义详略、格式、工具、协作方式等类别。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。
- [ ] **适用范围 `preference_scope`**：区分本次任务、某个项目与明确的通用偏好。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。
- [ ] **偏好证据 `preference_evidence`**：关联原始消息、确认人及确认记录。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。
- [ ] **生效时间 `effective_at`**：记录何时适用，并保留未知时间。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。
- [ ] **偏好变化 `preference_history`**：保存修订、撤销和冲突关系。 — 已实现／测试；口径待确认；`MistyHuang03`，[#4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。

- [ ] **偏好极性 `polarity`：已实现及测试；团队口径待确认。** — `MistyHuang03`，[Issue #4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。

认领时在 TODO 后补 GitHub 账号和 Issue 链接；未完成项可备注“开发中／待验收”。

完成特征口径确认、函数接入和样例验收，并补上实现链接后再勾选。已有基础统计也按此条件核对。

[返回分析模块分类](<classification.md>) · [对照现有 Feature](<../feature-inventory-2026-10-02.md>)

本页初始的特征口径、新增字段名和函数接口是草案，函数表列的是建议接口；实际实现以关联代码和验收记录为准。

## 范围

描述用户明确希望采用的方式，并保留其适用范围和时间。一次任务的临时要求先留在 [Instruction](<instruction.md>)；用户明确说明长期适用时再记录为对应范围的偏好。隐式排序、完整偏好向量和推荐匹配参数暂缓。

## 特征口径

| 字段 | 粒度／类型 | 定义与提取规则 |
| --- | --- | --- |
| `preference_statement` / `preference_type` | 偏好记录 · 文本与类别 | 保存原文及规范化表述，只纳入用户明确表达或确认的内容。 |
| `preference_scope` | 偏好记录 · 作用范围 | 记录任务／项目／通用范围；用户没有说明时不擅自扩展。 |
| `preference_evidence` | 偏好记录 · 证据列表 | 关联消息 ID、确认内容与确认人；AI 推断只作为待确认候选。 |
| `effective_at` | 偏好版本 · 时间／事件位置 | 区分记录时间与生效时间；缺少时间戳时保留顺序位置和缺失原因。 |
| `preference_history` | 偏好记录 · 版本关系 | 变更产生新版本，保留被替代／撤销关系；冲突未解时同时保留。 |

## 分析函数

| 建议函数 | 输入 → 输出 | 主要处理 |
| --- | --- | --- |
| `extract_explicit_preferences(messages)` | 真人消息 → 明确偏好及待确认候选 | 返回内容、范围、证据和时间，不把使用次数直接转成偏好。 |
| `resolve_effective_preferences(history, task, at)` | 偏好历史、任务及时点 → 可适用偏好及冲突 | 依据明确范围与版本筛选；当前任务指令另行关联，不被历史统计覆盖。 |
| `summarize_preferences(preferences, scope)` | 有证据的偏好集合 → 按类别／范围汇总 | 每条能回到证据，列出尚未确认或冲突的记录。 |

## 对接已有分析

[现有 Feature 一览](<../feature-inventory-2026-10-02.md>)中的工具排行、文本片段、消息长度和格式要求可提供回看入口。它们本身不能证明用户更喜欢某种工具、内容或回答方式。

## 验收样例

- “以后这个项目都用中文”：记录项目范围的明确偏好及生效位置。
- “这次请简短一点”：保留任务范围，不扩展成全局偏好。
- 后来说“这个项目改用英文”：新增版本；分析过去任务仍使用当时有效的偏好。

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

## 技术完成清单（2026-10-02）

- [x] `preference/` 独立目录：提取、时点解析、汇总、规则及本族字段字典。
- [x] 三个分析函数接入 `/v1/analytics/preferences` 与原 `tandem analytics`。
- [x] 六个原定字段及 `polarity`、候选／本次指令分流、版本关系有实现和正反例。
- [x] 单元、mock、真实端到端、性能、固定标签质量验证全部执行。
- [ ] 独立真实标注集、人类业务确认、跨句确认与多用户身份隔离。

[实现目录](https://github.com/Orbit-Labs-AI/Orbit-Source/tree/d030c2a3d3d4197cc8c9ed04054845fe26c4d47c/src/tandem_backend/analytics/preference) · [单元测试](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/d030c2a3d3d4197cc8c9ed04054845fe26c4d47c/tests/analytics/test_preference.py) · [功能测试](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/d030c2a3d3d4197cc8c9ed04054845fe26c4d47c/tests/analytics/test_functional.py) · [固定标签集](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/d030c2a3d3d4197cc8c9ed04054845fe26c4d47c/tests/fixtures/semantic-quality-v1.json) · [详细特征族说明](https://github.com/Orbit-Labs-AI/Orbit-Source/blob/d030c2a3d3d4197cc8c9ed04054845fe26c4d47c/docs/backend/analytics/preference.md)。

### 新特征：偏好极性与保守候选

- 字段名、类型／单位、统计粒度：`polarity` 为 prefer／avoid；`candidates`、`task_instructions` 为记录列表；单位为一次表达。
- 定义与用途：区分“喜欢采用”和“避免采用”，并使临时要求、截断表达、备选值、未来生效计划不会被当成长久偏好。
- 输入数据与证据定位：确认 main 会话、actor=human/user、origin=human 的直接消息；保留 event_uid、session_uid、seq、ts 和原分句；有 author_id 才填 confirmed_by。
- 提取规则／公式、缺失值与排除规则：清理平台块、附件、引用和代码后匹配明确表达；类别限语言、详略、格式、工具、协作方式；没有范围即 unknown；未来日期尚未解析时只作候选。
- 正例、反例和预期结果：“以后这个项目用中文、不要英文”两项相容；“中文或者英文”是候选；“这次简短一点”进入本次指令；工具用了 80 次不构成偏好。
- 提出人／确认人、Issue／实现链接：本轮 `MistyHuang03` 需求，AI 实现；团队语义确认待完成；[Issue #4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)、[PR #13](https://github.com/Orbit-Labs-AI/Orbit-Source/pull/13)。

### 分析函数：extract_explicit_preferences

- 计算哪些特征、回答什么问题：明确表达、类型、范围、证据、即时生效位置及修改／撤销／重申。
- 输入、输出、参数与依赖的特征族：`(events, sessions, task_by_event=None)`，输入标准化事件和会话；Task 仅提供事件到任务的映射；返回 records、candidates、task_instructions、coverage。
- 算法步骤、分母、缺失处理与适用范围：确认真人 → 清理材料 → 提取类别／范围 → 连接 supersedes／revokes／reaffirms；未知范围不扩大到 global，legacy_project_id 不升级成规范 project_id。
- 验收样例、预期输出、实现与版本链接：项目中文 → 重申中文 → 改为英文 → 撤销英文，保留四次观察及关系；见上述单元测试和 `d030c2a`。
- 提出人／确认人、Issue：`MistyHuang03` 需求；AI 技术验证完成、团队确认待完成；[Issue #4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。

### 分析函数：resolve_effective_preferences

- 计算哪些特征、回答什么问题：指定任务／项目在某时点能采用哪些偏好，还有哪些冲突或未决范围。
- 输入、输出、参数与依赖的特征族：`(history, task=None, at=None)`；task 提供 task_id、project_id 或 legacy_project_id；返回 applicable、conflicts、unresolved。
- 算法步骤、分母、缺失处理与适用范围：先限制可见时间和范围，再处理版本；显式 task 优先于 project，再到 global；当前指令单独保留；at 包含该 UTC 毫秒时刻，缺时间不能加入历史查询。
- 验收样例、预期输出、实现与版本链接：时间 10 中文、30 英文、40 撤销；查 15 是中文、35 是英文、45 为空且不恢复旧中文；同时间跨会话不能凭排序认定先后。
- 提出人／确认人、Issue：`MistyHuang03` 需求；AI 技术验证完成、团队确认待完成；[Issue #4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。

### 分析函数：summarize_preferences

- 计算哪些特征、回答什么问题：有证据的表达分别属于哪些类别和范围，多少缺少时间。
- 输入、输出、参数与依赖的特征族：`(preferences, scope=None)` → record_count、by_type、by_scope、missing_time_count；无需其他族。
- 算法步骤、分母、缺失处理与适用范围：按 preference_id 去重；表达次数不解释为强度；输入不可用返回 null，候选和临时指令不计入 records。
- 验收样例、预期输出、实现与版本链接：重复传入相同记录只计一次；None 保持未知；见 `test_determinism_no_mutation_and_summaries`。
- 提出人／确认人、Issue：`MistyHuang03` 需求；AI 技术验证完成、团队确认待完成；[Issue #4](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/4)。

## 真实数据表现与剩余工作

固定快照截止北京时间 2026-10-01 23:43:13；35 个会话、40,664 条事件，只能确认 9 条真人消息，另有 918 条来源未知。本族 **0 条明确偏好**，代表可用证据不足，不能解释成“没有偏好”。真实输入的 API／CLI 对照、重新导入及证据范围均验证通过。

下一步先补可靠 origin、project_id 与用户确认记录，再由团队标注独立真实样例；之后处理“对／好的”的指代确认、将来生效日期、复合条件／否定、更多工具和多用户身份。隐式偏好排序、完整偏好向量、推荐参数仍按分类文档暂缓。范围与时点查询只依据当前筛选内的历史，不自动加载 from_ts 之前的偏好。

## 讨论

待确认偏好类别、范围表达，以及修改／撤销／冲突的处理方式。

## 结论与下一步

确认后在这里记录结论、确认人（GitHub 账号）、依据和适用范围；实现与验收进度更新开头 TODO，并链接对应 Issue。

2026-10-02 结论：实现与技术验收已完成，待 PR 评审与团队语义确认；上述未完成项仍未勾选。

补充验收：Codex review 提出的全局偏好变更漏识别、跨会话任务目标顺序两项已修复，并各增加一条回归测试；最新 head 已重新触发 review，评审是否完成以 PR #13 为准。

## 评审与合并状态（2026-10-02）

PR #13 的 `d030c2a` 已完成代码评审、安全评审和 CI；没有 P0/P1，安全评审未发现问题。用户明确指定本次仅 P0/P1 阻断合并，以下三项 P2 已在原评论说明暂缓理由并关闭线程，问题本身尚未修复：

- 同时间的跨会话任务目标仍可能由 session_uid 的排序决定，不能据此认定真实先后。
- 开场闲聊可能被当成任务候选起点，使候选任务数量或起始位置不准确。
- 子会话的未知来源可能进入语义 coverage 统计，使其保守地标成 partial；不会进入两族的真人语义提取。

PR 保持打开、尚未合并：按已审 SHA 以 merge commit 合并的尝试被自动审批拒绝，理由是仍缺少负责人 `yhyfhgs` 对 PR #13 的明确授权记录。

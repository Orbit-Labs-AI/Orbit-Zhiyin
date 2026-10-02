# Preference：有证据的主观偏好

这组特征回答“用户明确喜欢什么，这句话适用于哪里，当时是否已经生效”。实现位于 `packages/backend/src/tandem_backend/analytics/preference/`，通过 `/v1/analytics/preferences` 与现有 `tandem analytics` 输出接入。方法是本地、确定性的规则提取，不调用模型或外部服务。

当前已完成模板要求的六类字段、范围解析、修改／撤销／重申关系，以及可复现的测试。它是明确表达的偏好提取 MVP，尚不能据此宣称完整理解用户；隐式偏好、人格、推荐权重均未实现。业务词表与验收口径仍待团队确认，本文记录的是代码行为和 AI 技术验收。

## 已完成的特征

| 字段／结果 | 粒度 | 含义与方法 | 缺失处理 |
| --- | --- | --- | --- |
| `preference_statement` | 一次偏好观察 | 保留经过既有脱敏、引用清理后的直接表达及匹配分句。 | 不恢复被删除的附件、代码或截断内容。 |
| `preference_type`、`value` | 一次偏好观察 | 识别语言、详略、格式、工具、协作方式五类，词表保存在 `rules.py`。 | 未识别的表达不强行分类。 |
| `preference_scope` | 一次偏好观察 | 区分 task／project／global／unknown；只有明确“所有项目”等表达才是全局。 | 没说范围就是 unknown；没有项目 ID 时保留缺失，旧路径 ID 标为 legacy_path。 |
| `preference_evidence` | 一次观察的证据列表 | 保留 event_uid、session_uid、seq、ts、actor、直接表达；输入有 author_id 才填写 confirmed_by。 | 不虚构确认人；一条记录可回到真实消息。 |
| `effective_at`、`effective_position` | 一个偏好版本 | 即时规则以消息观察时间为生效基准；UTC 毫秒，另留会话内顺序。 | 缺时钟为 null；明天／下周等将来计划转为候选，不提前应用。 |
| `preference_history` | 版本关系 | 显式修改连接 supersedes，撤销连接 revokes，相同偏好再次表达连接 reaffirms。 | 不明确的冲突同时保留；跨会话缺时钟／同时间不能证明先后。 |
| `polarity` | 一次偏好观察 | 区分 prefer 与 avoid；“用中文、不要英文”可以相容。 | 不把“不再用英文”解释为肯定英文。 |
| `candidates`、`task_instructions` | 观察集合 | 截断、备选值、未解析的未来时间放候选；“这次简短一点”留作本次指令。 | 候选与临时指令不计入已观察偏好汇总。 |

“已观察”只说明观察到了符合规则的明确表达，不等于团队已确认分类准确。输入默认属于同一被分析用户；多用户身份隔离尚未实现。

## 分析函数与输入输出

| 函数 | 输入 → 输出 | 已测内容 |
| --- | --- | --- |
| `extract_explicit_preferences(events, sessions, task_by_event=None)` | analysis-input-v1 事件、会话、Task 映射 → records／candidates／task_instructions／coverage | 真人边界、引用／附件／代码、否定、范围、截断、版本关系、稳定 ID、无输入修改。 |
| `resolve_effective_preferences(history, task=None, at=None)` | 偏好历史、任务的 task_id／project_id／legacy_project_id、UTC 毫秒 → applicable／conflicts／unresolved | 历史时点、缺时间、范围优先级、重申、撤销、冲突、项目身份质量。 |
| `summarize_preferences(preferences, scope=None)` | 观察记录 → 类别／范围计数、缺时间计数 | 按 preference_id 去重；重复表达不当作偏好强度；输入不可用保留 null。 |

处理顺序是确认 main 会话和真人来源 → 清理引文／平台材料 → 匹配明确表达 → 解析类别与作用范围 → 连接版本 → 按查询时点和范围选取。会话内顺序使用 seq；跨会话不凭文件名建立时间顺序。当前指令单独返回，历史偏好不覆盖它。

`at` 为包含该时刻的时间点；API 共用的 `until_ts` 是不包含上界，所以内部使用 `until_ts - 1`。缺时间记录不会进入历史时点查询。API 不提供 task_id 时只解析全局适用项；提供 task_id 后才解析该任务／项目。所有查询仅使用本次筛选内的历史，`from_ts` 之前的偏好不会自动补入。

## 验收样例

合成例子：时间 10 用户说“以后这个项目用中文”，20 重申，30 说“这个项目改用英文”，40 撤销英文偏好。查询时间 15 得到中文，35 得到英文，45 没有有效偏好；撤销不自动恢复更早的中文。所有结果都保留对应证据 ID。

反例：“他说我喜欢详细回答”、引号里的示例、附件中的指令、工具调用 80 次，均不能证明本人偏好。“我喜欢简短回答”有明确内容但没有全局范围；“中文或者英文”保留待解析候选。

## 验证与真实数据效果

[五类测试记录](validation.md)提供测试命令、结果、真实性边界与性能。Preference 的单元和固定标注样例均已通过；mock API 验证 task_id、过滤与错误响应；真实日志重新导入后 CLI／API 记录一致。

固定真实快照有 9 条来源可确认的真人消息、918 条来源未知的用户角色消息；本族提取到 0 条明确偏好。这表示合格证据不足，不表示用户没有偏好。原文、完整结果和数据库只留在被忽略的 `.local/`。

## 待完成与待测试

- 尚未解析只说“对／好的”的上下文确认、代词指代、相对生效日期和未覆盖的工具名。
- 一句里复杂的条件／否定、格式可组合关系、多条冲突之间的人工裁决尚需扩展。
- 缺少独立的人工作真实历史标注；固定合成样例通过不能当作实际准确率。
- 尚无多用户身份隔离、长期偏好强度、并发服务与大规模全文表示容量结论。
- 下一步先改善 origin、规范 project_id 和可追溯的确认记录，再扩独立标注集；不为增加命中率而将未知消息算成人类。

# 会话数据契约

逻辑契约为 `orbit-session-v1`，分析输入为 `analysis-input-v1`。逻辑契约、SQLite 迁移号、parser / derivation / redaction 版本分别描述不同维度，不能用一个数字替代。当前迁移已到 [014.sql](../../packages/data/src/orbit_data/migrations/014.sql)，所有字段以[生成字典](../../packages/data/src/orbit_data/schemas/tables-v1.schema.json)为准。

## 层次与身份

| 层 | 职责 | 主要对象 |
| --- | --- | --- |
| L0 | 来源位置、版本、哈希；归档路径按采集方式保留 | source reference、source revision、archive blob |
| L1 | 每条原生记录的位置、身份与处理去向 | `raw_record`、`record_event` |
| L2 | 统一、脱敏、可追溯的事实 | `event`、`event_context` |
| L3 | 可复用实体、配对和计量 | `project`、`session`、`turn`、`tool_call`、`model_call` 等 |

原生扫描以来源索引为主，不默认复制整份会话；归档输入与 staging 桥接会保留相应原始字节。原文下钻是否可用取决于所用模式、来源是否存在和版本是否匹配。

`*_uid` 是不透明身份，不用于推导日期或排序。会话身份独立于可重建投影；事件按原生顺序和展开位置保留 `seq`，时钟回退不改变事件顺序。一条原始记录可贡献多个事件，一个事件也可由多条记录贡献，`record_event` 保存这种关系。

## L1 全记账与 L2 事实

每条原始记录都有去向。未识别类型保留 unknown 或相应诊断，坏记录保留未解析原因；不能通过跳过记录让覆盖率看起来更高。Schema 编程错误或归档损坏应使投影失败，不发布不一致结果。

L2 包含来源、会话、轮次、角色、事件类型、时间及其质量、正文、结构化属性和原生扩展。标准事件通过 [event-v1.schema.json](../../packages/data/src/orbit_data/schemas/event-v1.schema.json)校验。文本和扩展经过版本化脱敏；明确的原文读取不等于脱敏读取。

工具状态只来自协议状态、退出码或明确错误证据。外层包装成功不能推出内部成功，输出中出现 “error” 也不能单独判定失败。缺失时间、结果或配对身份保留未知。

## L3 的粒度

| 对象 | 一行代表什么 | 消费限制 |
| --- | --- | --- |
| `project` | 规范项目身份 | 使用 Git/目录及显式覆盖，不能只按显示名合并 |
| `session` | 逻辑会话与血缘 | main、subagent、review 等分开；未解析血缘有诊断 |
| `turn` | 原生或可识别的一次输入边界 | 轮次不等于分析任务 |
| `tool_call` | 配对后的逻辑调用 | 未知状态、歧义、状态范围与耗时质量分别保留 |
| `tool_call_file` | 调用参数指向的文件操作 | 表示已报告的操作意图，不证明产物内容或质量 |
| `model_call` | 有请求边界的 call/delta 用量 | 保留 request identity、边界质量和原始模型 |
| `usage_snapshot` | 某个 key/周期的累计观测 | 不直接求和，不伪造请求次数 |
| `session_feature` | 机械事实计数 | 不混入 LLM 标签 |
| `link` | 外部证据关联 | 只使用可回查的引用 |

`event_context` 记录事件发生时的项目、cwd、模型等归属；会话中途变化后不能将旧事件改到最终设置。014 增加一小时缓存写入 token、service tier、工具失败种类及文件操作表；旧数据需要从证据重建，不默认补零。

## 用量与时间

规范 `input_tokens` 表示未缓存输入，缓存读写分桶；`output_tokens` 包含思考，`reasoning_tokens` 是子集。来源语义不同应在 mapper 中转换。缺失成本或价格为 null，未知不是免费。

`model.usage` 区分 call/delta 与 cumulative。累计值以相同 key 和周期的最后观测为准，计数回退保留诊断；不能把首次导入值当成当天新增用量，也不能把根树累计与子代理逐次用量相加。

墙钟区间、原生执行报告、审批等待与模型延迟分别保存和汇总。原生耗时不反推缺失端点，重叠区间的总和与并集含义不同，均不代表人工工时。

## 范围与发布

通过 `read_analysis(home, AnalysisScope(...))` 在一致只读事务里读取 L2/L3、版本、覆盖、统计成员和样本边界。时间窗口为 `[from_ts, until_ts)`；上下文可辅助解释，但不能增加统计分母或泄漏截止点之后的结果。具体见[分析输入](analysis-inputs.md)。

成功重算登记投影版本和发布信息；未发布的新输入不能冒充完整结果。App 可明确显示上一份已发布快照与新鲜度。数据库使用 STRICT、WAL 与逐连接外键检查，各库的迁移与写入所有权独立。

## 跨语言桥接

TypeScript connector 写独立 staging。桥接验证归档分块大小与哈希，再导入 L0/L1 并使用 Python canonical mapper 重建；staging 的 L2/L3 和事件 ID 不能直接复制成 canonical 事实。`connector_record_link` 保留跨库记录对应。

两个数据库与归档目录必须分开，桥接只读 staging，不扩大为重新扫描上游。原生日志、原始归档和派生库不得提交 Git。

扩展方法见[连接器](../modules/data/agent-connectors.md)，库存语义见[安装清单](../modules/data/local-inventory.md)，验证入口见[测试指南](../development/testing.md)。

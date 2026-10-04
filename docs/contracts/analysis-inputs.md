# 分析输入契约

`analysis-input-v1` 是数据读取端向分析模块提供的语义边界。使用 [read_analysis](../../packages/data/src/orbit_data/analysis_input.py) 或后端 `CanonicalStore.analysis_bundle` 获取一致快照；不要在每个特征族重新解析 Agent 日志。

## 一次读取

```python
from orbit_data.analysis_input import AnalysisScope, read_analysis

data = read_analysis('.local/my-orbit', AnalysisScope(
    display_timezone='Asia/Shanghai',
    project_ids=None,
    include_children=True,
))
print(data['coverage'])
```

数据 home 必须已导入并具有可读取的投影。源码中的 Scope 定义与对应入口参数是实际可用字段；旧方案中的补充设想不作为 API 保证。

## Scope

| 字段 | 语义 |
| --- | --- |
| `display_timezone` | IANA 时区，控制日期/小时分桶，不修改 UTC 事实 |
| `project_ids` | 规范项目 ID 集合 |
| `model_ids` | 逐次请求的模型 ID，不用会话最终模型回填 |
| `effort_raw` | 来源自己的思考档位；跨厂商同名不等价 |
| `from_ts` / `until_ts` | UTC 毫秒，左闭右开 `[from_ts, until_ts)` |
| `root_session_uids` | 选定根会话，仍保留子会话身份 |
| `excluded_session_uids` | 明确排除的会话，不因切换其他筛选而恢复 |
| `include_children` | 是否带入已确认子代理过程，默认 true |
| `agent_ids` / `source_ids` | Agent 类型和具体来源分别筛选 |

集合参数 `None` 表示未限制，空 tuple 表示明确选中零个；HTTP 中的空 query 参数也应保留这个区别。无界读取与有界时间统计不同：未知时间不能进入确定的历史窗口。

`scene` 属于后端派生筛选，旧 CLI 的 `before` 属于兼容采样约定，不是数据层 Scope 的同名替代。接入时分别转换，不只改参数名。

## 数据集合与用途

| 输入 | 用途 | 不能推出什么 |
| --- | --- | --- |
| sessions / projects | 身份、范围、血缘、项目聚合 | 多根来源不等于多个人 |
| turns | 原生轮次和触发关系 | 一轮不等于一个完整任务 |
| events / event context | 正文、顺序、历史设置和证据 | 助手文本、引用或重放不等于真人意图 |
| tool calls / files | 配对、状态、参数意图、执行关系 | 命令提及不等于执行；写文件不等于验收 |
| model calls | 逐次请求与用量 | 未知边界不等于可靠请求 |
| usage snapshots | 累计观测及覆盖 | 不能与逐次用量无条件相加 |
| inventory / scans | 扫描时配置和文件的观察 | 不能证明历史会话已加载或使用 |
| links / features | 可复用机械事实与外部引用 | 不直接形成因果结论 |

完整列定义在[会话字段字典](../../packages/data/src/orbit_data/schemas/tables-v1.schema.json)。标准 JSON 文本列由读取器解码，调用方不应维护另一份列类型猜测。

## 统计成员与上下文

先按来源、时间、项目和模型确定统计成员，再带入解释它们所需的关联上下文。窗口之前的用户要求可以解释当前工具调用，但不增加本窗口要求次数；截止点之后的返回、反馈、验收和后补标注不能解释为当时已知。

保留 `statistical_members` 与上下文范围，不能只过滤 `events` 后继续复用旧的 session/turn/call 元数据。变更范围应重新调用读取端。主会话与已解析子代理可以形成一棵工作树，但真人消息和会话分母不能因子代理数量膨胀。

## 覆盖与版本

输出包含输入契约、schema/parser/derivation/redaction 版本、样本边界、诊断和覆盖。来源扫描边界、当前分析范围、安装扫描快照与 Catalog 快照是不同信息，不能混为一个“数据版本”。

| 状态 | 消费规则 |
| --- | --- |
| `available` | 可计算适用部分，仍逐字段检查 null |
| `partial` | 报告有效数、未知数和原因，限制结论 |
| `unavailable` | 结果保持未知，不用空数组证明没有发生 |
| `excluded` | 说明由范围或预算主动省略的部分 |

已知为空的 `[]` 与无法获得的 `None` 不等价。`reasons`、`reason_counts` 和可回查证据应贯穿 CLI、API、报告与 UI。来源日志没有的事实不能通过改状态恢复。

## 成本、结果与证据

规范 token 桶、累计值、墙钟和原生执行耗时遵循[数据契约](data.md)。工具失败的分母只包含适用的已知结果；结果未知不得视为成功。用户确认、客观验收、模型推断和关键词候选分别保留来源与证据等级。

事件可经 `record_event` 回查贡献记录，原文应按所选证据局部读取，并遵守排除项与截止范围。默认分析不批量加载所有原生扩展；完整正文与显示截断是不同层次。

## 接入检查

覆盖空选择、未知时间、窗口边界、未来反馈、子代理、重复/冲突身份、累计用量和缺安装扫描。CLI、API 与报告在同范围应给出一致的事实与缺口。参见[模块参考](../modules/README.md)与[测试指南](../development/testing.md)。

## 设置页覆盖摘要

`coverage_summary(conn, scope=None)` 经 `GET /v1/app/coverage` 返回轻量摘要，不加载完整分析输入；无库时为 `available=false / reason=no_database`。

| 字段 | 口径 |
| --- | --- |
| `sessions.rows/status_known_rows/status_known_share` | 会话数、已知状态数与占比；零分母为 null |
| `model_call.rows/unmapped_model_rows/unmapped_model_share/cost_usd` | 模型调用数、未映射模型数及占比、已计价成本 |
| `excluded_sessions` | coverage-v1 状态、原因与计数，附被排除调用、token、已计价成本和占比 |
| `excluded_sessions.reasons_labelled` | API 附加中文原因及数量，按数量降序 |

成本占比的分母是口径内加被排除部分的已计价成本；无计价时保持 null。

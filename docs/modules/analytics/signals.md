# Signal、问题与指标

`analytics/signals` 是八族之上的派生层，复用同范围事实生成信号、问题、关键时刻与会话结果。它不是第九个特征族，也不重新解析原始日志。

## 字典与规则版本

权威枚举和阈值在 [signals/dictionary.py](../../../packages/backend/src/orbit_backend/analytics/signals/dictionary.py)，当前为 `signals-v1.1`。闭集包含 correction、frustration、retry_loop、missing_verification、would_prompt、permission_denied、risky_command 和 interruption。

| 信号 | 需要的证据 | 解释限制 |
| --- | --- | --- |
| correction / frustration | 真人直接文本与前后过程 | 词面代理信号，不等同确认的心理或质量结论 |
| retry_loop | 失败、任务/工具/状态范围及重试关系 | 相邻或同名工具不够 |
| missing_verification | 编辑与后续可确认检查 | 验证信息不可用时保留未知 |
| would_prompt / permission_denied | 权限模式、命令或明确拒绝 | 只读命令头还需参数和重定向检查 |
| risky_command | 可解释命令模式与目标 | 静态风险提示，不是实际损害证明 |
| interruption | 明确轮次/生命周期状态 | 不自动判定任务最终失败 |

`None` 表示这类证据不可用，`[]` 表示可用且未观察到；两者不能一起当作零。每条信号保留锚点和 occurrences，计数与位置分开。

## 信号升级为问题

按问题类型、key、scope 聚合支持会话，分母只包括同范围有机会发生且证据可用的会话。当前默认要求达到类型的最少会话数，并使 Wilson 下界严格大于 0；旧文档的 0.05 门槛已不适用。类型可以声明独立背景阈值，不能把手写阈值描述为经过校准。

未升级项保留候选及原因；用户标签不删除事实。问题 ID 按稳定语义生成，重算仍能追踪同一问题。

## 关键时刻与结果

关键时刻围绕目标、纠偏、失败链、验证、压缩和结束组织，限制展示数量但保留总数。会话结果结合明确反馈、验证、可选 facet 与结构证据，保留 basis 和未知原因；不能用助手结束发言替代完整验收。

指标通过 [metrics.py](../../../packages/backend/src/orbit_backend/analytics/metrics.py)计算，明细通过 [drilldown.py](../../../packages/backend/src/orbit_backend/analytics/drilldown.py)读取。不同组汇总保持分母一致，小样本和未知分列。与 App 推荐问题构建的衔接见[推荐引擎](../recommendation/engine.md)。

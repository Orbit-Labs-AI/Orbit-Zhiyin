# Agent 连接器

连接器把特定 Agent 的记录映射为统一事实。发现来源、用户授权、捕获/索引、mapper 与发布是独立步骤；上层分析只消费 canonical 数据，不重新解释原始格式。

## 内置来源与边界

| 标识 | 主要形态 | 需要保留的差异 |
| --- | --- | --- |
| `claude_code` | JSONL 与子代理文件 | 消息拆分、重复表示、父子关系、usage |
| `codex` | rollout、状态元数据、可选 staging | 原生轮次、消息镜像、继承前缀、累计和逐次用量 |
| `dsh` | 版本化事件与压缩流 | 旧代记录、分帧、工具/审批、未知插件事件 |
| `pi` | 消息树与 fork | 有依据的复制段与分叉血缘 |
| `hermes` | SQLite session/message | 行版本与累计用量，缺请求边界时不造 model_call |
| `opencode` | SQLite message/part | 已适配代际、原地更新、WAL 与删除 |
| `kimi` | wire/session | 内容分片、控制事件、usage 去重与代际差异 |

上述格式均有构造回归。真实安装版本覆盖不均，原生未报告的状态和计量始终未知；特定基线上的验证见[导入审计](../../audits/ingestion-reliability-2026-10-03.md)，上游格式研究见[研究索引](../../research/agent-sessions/README.md)。

## 使用与扩展

用户入口是 `orbit ingest`，数据包入口是 `orbit-data scan`，两者都要求显式 Agent 与根目录。程序通过 `ImportRequest` / `ImportService` 接入，见[数据流程](../../architecture/data-pipeline.md)。

新增来源时先提供发现规则和最小原生样本，再实现 mapper 的准备与映射。映射结果使用标准事件，身份、顺序、校验、记录追溯和发布交给 Store。归档输入可经 `capture_stream`，自定义 mapper 经 `register_mapper` 接入；不要让新来源绕过 L1 记账。

必须声明时间质量、使用量含义、工具状态作用范围、父子身份和扫描覆盖。未识别类型留下可解释记录，损坏记录与 Schema 编程错误分别处理。每种来源都有 L1 去向，不能以跳过未知记录换取“全部成功”。

## TypeScript Codex producer

`packages/connectors` 负责独立 staging 的增量采集和监听，`import-connector` 校验归档后通过 Python mapper 重建 canonical。数据库和 raw 目录分开，两个包不能共写同一个 SQLite 文件。详见[connector README](../../../packages/connectors/README.md)。

## 验证

先运行所属数据包与 connector 检查，再按接口范围运行集成。构造样本覆盖首次/重复导入、更新删除、半帧/坏行、消息镜像、父子关系、范围与来源只读。真实来源仅在显式授权后读取，输出留在 `.local/`。

`bash scripts/check-data.sh` 提供数据层构造验收；`--real` 会追加真实来源读取，不能默认放进 CI。性能与逻辑等价性见[导入性能](import-performance.md)。

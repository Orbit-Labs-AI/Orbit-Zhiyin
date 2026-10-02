# 来源索引、完整正文与 App 轨迹读取

当前实现以七类 Agent 为范围：Claude Code、Codex、DSH、pi、Hermes、OpenCode、Kimi。原生 `scan` / `ImportService` 使用来源索引，不把用户的整个 session 文件或 SQLite 行导出再保存一份。存储 schema 为 5，事件契约仍为 v1。

## L0–L3

| 层 | 表 | 保存内容 |
| --- | --- | --- |
| L0 | `source`、`source_file`、`source_revision`、`source_reference`、`source_scan` | 已启用来源、文件位置、扫描范围、来源版本与解码内容的 SHA256；不保存原生文件副本 |
| L1 | `raw_record`、`file_record`、`record_location`、`record_event` | 每条记录的版本、原生顺序、字节位置或 SQLite 表与主键、哈希、解析去向和事件对应关系 |
| L2 | `event`、`event_context` | 完整标准化正文、参数、输出、当时的上下文；隐私脱敏继续生效 |
| L3 | `session`、`turn`、`tool_call`、`model_call`、`usage_snapshot`、`session_feature` | 会话、轮次、工具、模型请求、累计计量和派生事实 |

`usage_observation` 只保留 Hermes 可变累计计量行中的数字和计费维度，用于重算历史累计观测；它不保存聊天正文。未识别的原生记录有 L1 去向和 `unknown` 事件，可通过原文索引查看，不再把完整原生 payload 复制到 `ext.native`。

JSONL 用字节位置读取；原生 zstd 用解压后的偏移读取；SQLite 用白名单表和主键读取，保留 WAL 一致性。每次取原文都会校验记录哈希。文件中较早的行改写导致后续偏移变化时，重新扫描会更新 `record_location`，未变记录保留 UID。

全量扫描会以内容哈希识别唯一匹配的归档移动和压缩替换，更新来源位置并保留原记录 UID；多份相同内容无法唯一匹配时不会随意绑定。

新扫描不产生 `raw/*.zst`。已有 archive 数据会原样保留并可读取；`capture_stream` 和显式 `import-connector` 仍是旧归档兼容入口，不是 App 原生采集路径。它们会写归档，不能用于要求“不复制会话”的采集任务。App 应直接调用 `ImportService` 扫描七类原生来源。

## 正文完整性

统一事件的 `text` 不再有 8 KiB 预览限制，`attrs` / `ext` 的字符串不再有 8/32 KiB 截断，普通分析读取也不再默认受 100,000 候选事件限制。调用方仍可显式传入 `max_events` 作为报错式资源预算；不会静默裁掉后续事件。

表内字符串继续脱敏，内联二进制和加密字段继续保留引用。原文接口是显式的本地原始证据访问，能读取未脱敏、未裁剪的原生记录。外部附件路径只是记录中的引用，本模块不递归复制附件或获取远程媒体。

“完整”指已启用来源中可读取并已索引的记录。来源未安装、未授权、采样、文件读取失败、未知类型和不可解密内容都不能记为完整。`source_scan` 记录本轮发现数、索引数、样本选择和失败状态；分析覆盖会标明样本扫描。

## Mac App 接口

### 会话及标准事件

`GET /v1/sessions` 与 `GET /v1/sessions/{session_uid}/events` 读取已发布的会话和事件表，包括 review / import / auxiliary 会话。分析视图仍采用独立的统计范围，避免把自动评审或导入记录算作人类行为。

事件分页使用 `after_seq`。页大小只限制条数；单条消息和工具输出不会裁剪。事件携带 `record_uid`，可继续读取原文索引。

### 完整原生 trajectory

```text
GET /v1/sessions/{session_uid}/trajectory?limit=100
GET /v1/sessions/{session_uid}/trajectory?after=100&run_id=42&limit=100
```

返回 `items`、`total`、`run_id`、`next_after`。必须继续读取到 `next_after=null`，不能把第一页当成整个会话。后续页传回 `run_id`；发布版本改变返回 409，调用方重新分页，避免游标漂移。

默认包含子会话，可设置 `include_children=false`。这里不套用分析过滤：原生的忽略记录、未知类型、无效 JSON 行、重放记录及被撤销分支仍能看到，分别标明 disposition 和关联事件。DSH 较低格式代次也保留索引并归属同一轨迹。记录按来源文件、原生顺序排列，不把跨文件的未知时间伪造成精确的全局时序。

每个条目包含 `source_url`。关联事件通过 `events[].event_uid` 使用现有 evidence API 读取。SQLite 历史行若已经改写，只保留旧索引和分析事实，不能声称仍能恢复旧原文。

### 打开原文

```text
GET /v1/records/{record_uid}/source
GET /v1/records/{record_uid}/source?include_content=true
```

默认返回经过校验的位置、格式、主键或行号、字节范围和 SHA256；显式 `include_content=true` 返回整条原始记录。客户端只能传 canonical `record_uid`，不能通过这个接口读取任意路径。

App 应先检查 `status`，只在 `available` 时使用返回的原文：

| 状态 | 含义与处理 |
| --- | --- |
| `available` | 记录哈希一致，可显示 `content` 或按位置打开本地来源 |
| `changed` | 记录已被改写或位置失效；重新扫描，不显示不同内容作为旧证据 |
| `missing` | 来源文件/行已删除；已有 L2/L3 可继续展示，但原文不可恢复 |
| `unreadable` | 权限、编码或数据库读取错误；显示读取失败 |

`verify` 会检查当前来源引用和记录摘要；不可读来源返回 `integrity=partial` 及 `unavailable_sources`，不会把未检查的引用当成通过。

已索引文件删除后，同来源其他会话仍可更新。重算保留此前发布的标准化事实，并标记 `attrs.source_status=missing` 和原 mapper 版本，分析覆盖为 partial；这些是此前已经生成的 L2 表记录，不是重新保存原生 session。来源恢复后重新扫描会清除保留标记。活跃来源与保留事实具有同一事件身份时，以活跃来源为准。

## 映射和旧库

Codex 补齐旧式 `agent_message`、与 Responses 消息配对去重、旧式工具开始/结束、推理、审批、计划、压缩、回滚及子代理控制事件；读取最新版本的 state 索引、标题和导入关系账本。`history_base` 的截断边界影响当前标准事件，但原始分支仍在 trajectory。无法唯一判定活动分支时报告诊断，不随意选一条历史。

Claude 补齐带 `agentId` 的生命周期记录与字符串消息；Hermes 按 session 的 prompt hash 关联共享 system prompt；公共消息解析支持字符串、对象、块数组，Kimi 同步处理这些内容形状。现有 DSH / pi / OpenCode 的分片、重放、主键更新和工具映射继续使用原生语义。未来新类型仍进入 `unknown`，原始证据可定位，不用空文本伪装成功。

打开旧库会迁移表结构，不删除已有归档。mapper / redaction 版本升级使旧投影失效；必须重算后再供分析读取。已有原生来源重新 `scan` 后改用来源引用；不要把旧归档直接删除当作迁移步骤。归档编码保存在每个捕获版本的 `source_stat.capture_format`，不会因当前来源改成压缩文件而错误解码历史版本。仅凭索引无法恢复已经从来源删除、且从未归档的原文。

验收覆盖七家原生布局、长正文、直接原文、改写后的偏移修正、源文件删除、SQLite 主键与累计版本、zstd 残帧、旧归档兼容、消息去重和 App 分页。测试使用构造数据，不复制真实 session 作为样本。

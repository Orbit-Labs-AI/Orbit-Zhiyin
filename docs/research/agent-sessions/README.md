# Agent 会话与轨迹数据形态对比

> 研究对象：pi、Hermes Agent、DeepSeek Harness（下称 DSH）、OpenCode、Codex、Claude Code。
>
> 回答三个问题：每个 agent 完成一次 chat 之后，落盘的 session 长什么样；它的内部结构怎样决定了这份 trajectory 的数据形态；六者有哪些异同。
>
> 本目录是 [数据获取与标准化方案](../../plan/data-acquisition.md)（模块 1）的源码级依据。方案中的结论多来自本机实测，这里从源码出发逐条给出出处（GitHub permalink），并补上本机没有安装的 Hermes 与 OpenCode。

## 0. 结论先行

1. **两类介质，三种形态。** pi、Claude Code、Codex、DSH 写只追加的 JSONL；OpenCode、Hermes 写 SQLite。JSONL 里又分两派：pi 和 Claude Code 一行是一条消息（Claude Code 还会把一次模型响应按内容块拆成多行），Codex 和 DSH 一行是一个运行时事件，消息只是事件的一种。
2. **每家只有一个权威来源，旁边挂着可重建的索引。** Codex 的 `state_5.sqlite` 与 `thread_history_1.sqlite`、DSH 的投影缓存与可选 FTS、Hermes 的 FTS 虚表、OpenCode 的 `event` 表（迁移时被清空过）都不能当正文来源。
3. **消息方言决定能否原样回放。** Claude Code 存 Anthropic Messages 原生结构，Codex 存 OpenAI Responses 原生 item，Hermes 存 OpenAI Chat 形状加各家推理旁路列；pi、DSH、OpenCode 存自己的中立格式，换 provider 时由适配层转换。
4. **"一次模型调用"的边界六家各不相同。** pi、Hermes 是一行 assistant；OpenCode 是一条 assistant message；Claude Code 是同一 `message.id` 的多行；Codex 是一条 `token_usage_record` 及其前后的一组 item；DSH 是 step 内的一条 `assistant/message`。统计调用次数、token、耗时之前都要先按各家规则合并。
5. **链接模型有三种。** 树：pi（`id`/`parentId`）、Claude Code（`uuid`/`parentUuid`，并行工具会产生侧枝）；线性序号：Codex（`ordinal`）、DSH（`seq`）、Hermes（自增 `id`）；扇形：OpenCode 同一轮的每条 assistant 都直接挂在该轮 user 下。
6. **压缩都不真删原文，但标记方式不同。** pi、Codex、DSH、OpenCode 追加摘要类记录；Claude Code 开一个新根并用 `logicalParentUuid` 指回；Hermes 默认把旧行置为 `active=0, compacted=1`。
7. **计量口径差异大。** 都有逐次调用的 token，Hermes 例外，只有会话级与按模型的累计。美元成本：pi、OpenCode 逐次记录，Hermes、Claude Code 只有会话或进程累计，Codex、DSH 不记。缓存是否计入输入、推理是否计入输出也各不相同：Claude Code 输入不含缓存，Codex 输入含缓存命中，OpenCode 输出不含推理，pi 的推理计入输出。
8. **审批几乎不落盘。** 只有 DSH 完整记录 `approval/asked` 与 `approval/decided`；Claude Code 只记拒绝原因（`toolDenialKind`）；Codex、OpenCode、Hermes、pi 只能从工具结果间接推断。
9. **训练格式只有 Hermes 提供。** Hermes 可以显式开启 ShareGPT 轨迹（`<think>`、`<tool_call>`、`<tool_response>`），还能把会话导出成 Claude Code JSONL 形状。Codex 和 Hermes 都能导入 Claude Code 会话（只保留文本），Claude Code 的 JSONL 已经事实上成了跨 agent 的交换格式。
10. **数据方案已吸收大部分结论，仍有几处要按源码修正**：pi 在首条 user 消息时就落盘，且源码里没有 `subagent-artifacts/`；OpenCode 没有 `session_v2` 表；Claude Code `--resume` 的写法与 SDK 测试不一致；Hermes 的库不一定是 WAL，且会自动删除 90 天不活跃的会话；标准事件映射表还缺 Hermes 与 OpenCode 两列。详见 §6.2、§6.3。

## 1. 范围、方法与版本

| Agent | 仓库与分析 commit | 语言 | 源码 HEAD 版本 | 本机版本与数据 | 依据 |
| --- | --- | --- | --- | --- | --- |
| pi | [`earendil-works/pi@88ff80b`](https://github.com/earendil-works/pi/tree/88ff80b986e34d4fbd1fa94a4df65c60ae964516)（2026-10-01） | TypeScript | coding-agent 0.99.2 | 0.99.1，2 个会话 | 源码 + 本机 |
| Hermes Agent | [`NousResearch/hermes-agent@44a1ce9`](https://github.com/NousResearch/hermes-agent/tree/44a1ce9724502b9c692faaef00af3054bf11f1a6)（2026-10-01） | Python | 未标版本号；`state.db` schema v31 | 未安装 | 源码 |
| DSH | [`deepseek-ai/deepseek-harness@639ed01`](https://github.com/deepseek-ai/deepseek-harness/tree/639ed015397290b3745d163aafe02ffee4aa3f84)（2026-09-29） | TypeScript（cordis 插件） | 0.2.0-rc.2，会话格式 v4 | 0.1.1-rc.2（格式 v0），79 个会话 | 源码 + 本机 |
| OpenCode | [`anomalyco/opencode@63cf236`](https://github.com/anomalyco/opencode/tree/63cf236140b11c15cd645e90a7ded77bdc2193b4)（2026-10-01） | TypeScript（Bun + Effect） | 1.18.34 | 未安装 | 源码 |
| Codex | [`openai/codex@9552906`](https://github.com/openai/codex/tree/9552906b2b8358121f71695e1e6602791cdcecc0)（2026-10-01） | Rust | 仓库内为 `0.0.0-dev`，发版另打 tag | Codex Desktop，`cli_version` 0.98–0.159，906 个 rollout | 源码 + 本机 |
| Claude Code | CLI 闭源；参考 [`claude-agent-sdk-python@db750b2`](https://github.com/anthropics/claude-agent-sdk-python/tree/db750b20a88ae9645b1674d95193a88c89a265f9)（0.2.163，捆绑 CLI 2.1.286）、[`claude-agent-sdk-typescript@0e21ebb`](https://github.com/anthropics/claude-agent-sdk-typescript/tree/0e21ebb22c36caca1220c34ae6c9fe8ddad40e47)、[`claude-code@6160717`](https://github.com/anthropics/claude-code/tree/6160717d8994f236ab381cf534fc1cde5347c12f)（CHANGELOG） | — | 2.1.286 | 2.1.285，126 个主会话、269 个子代理文件 | SDK 源码 + 类型定义 + CHANGELOG + 本机 |

方法：

- 源码一律只读，按上表 commit 分析；文中链接都固定到该 commit。
- 本机数据只读，只统计结构（记录类型、字段集合、出现率、版本），不摘录任何对话正文。示例中的正文全部换成 `<user prompt>`、`<assistant text>`、`<tool output>` 等占位符，路径中的用户名写作 `~`，项目名写作 `<project>`。凭据文件（`~/.codex/auth.json`、`~/.dsh/.credentials.yaml`、`~/.pi/agent/auth.json` 等）没有打开。
- 所有 Mermaid 图都在 Mermaid 11 下做过解析与渲染检查；示例 JSON/JSONL 逐行可解析。

## 2. 六家的落盘形态总览

```mermaid
flowchart LR
  subgraph APPEND["只追加的 JSONL"]
    PI["pi<br/>~/.pi/agent/sessions/--cwd--/时间_uuidv7.jsonl"]
    CC["Claude Code<br/>~/.claude/projects/编码cwd/uuid.jsonl<br/>同名目录：subagents/、tool-results/"]
    CX["Codex<br/>~/.codex/sessions/Y/M/D/rollout-时间-uuidv7.jsonl<br/>archived_sessions/"]
    DS["DSH<br/>~/.dsh/sessions/--cwd--/会话id/session.v4.jsonl.zstd"]
  end
  subgraph DB["SQLite"]
    OC["OpenCode<br/>~/.local/share/opencode/opencode.db<br/>session / message / part"]
    HM["Hermes<br/>~/.hermes/state.db<br/>sessions / messages"]
  end
  subgraph SIDE["旁路索引与缓存（不作为权威来源）"]
    CXS["state_5.sqlite 线程索引<br/>thread_history_1.sqlite 分页投影"]
    DSP["storages/session_projcache<br/>可选 FTS 库"]
    OCE["event / event_sequence 表"]
    HMF["FTS5 虚表"]
    CCX["history.jsonl<br/>file-history/"]
  end
  CX -.-> CXS
  DS -.-> DSP
  OC -.-> OCE
  HM -.-> HMF
  CC -.-> CCX
```

## 3. 结构图与 trajectory 数据形态的对照

每份报告的 §1 是结构图（组件、数据流，虚线标出写入持久化的边）与一次 chat 的时序图，§5 是 trajectory 数据形态图，§6 是"组件 → 记录"对照表。下表把六家的因果关系压缩成一行：

| Agent | 结构特点：谁写、何时写 | 由此得到的数据形态 | 详见 |
| --- | --- | --- | --- |
| pi | `SessionManager` 是唯一写入者，订阅 agent loop 的 `message_end`，每条消息完成后追加一行；`/tree` 导航是一等功能 | 一会话一文件的 entry 树；消息完整，没有流式碎片；分支留在同一文件 | [pi.md](pi.md) §1.2、§1.3、§5.2、§6 |
| Hermes | 多个入口（CLI、TUI、gateway、ACP、cron）共用 `AIAgent` 与同一个 `state.db`，用租约协调；"先落库、再产生副作用" | 关系表中的 OpenAI Chat 消息行，带展示列与谱系列；压缩、撤销靠改标志而不是追加 | [hermes-agent.md](hermes-agent.md) §1.2、§1.3、§5.2、§6 |
| DSH | 一切都是 cordis 插件，所有插件经 `ctx.sessions.append` 写同一条事件日志，持久化后端只是订阅者 | 事件溯源日志：turn/step 括号、插件自定义事件，统计与标题都由投影重算 | [dsh.md](dsh.md) §1.2、§1.3、§5、§6 |
| OpenCode | 客户端/服务端架构：服务端把每次更新发成 durable 事件，在同一事务里投影到表；客户端靠 SSE 拿增量 | 关系表中的 message 与 part；part 是状态机（工具从 pending 到 completed），行被反复覆盖 | [opencode.md](opencode.md) §1.2、§1.3、§5.2、§6 |
| Codex | 会话事件总线同时服务模型（Responses API 回放）与 UI（app-server 分页），RolloutRecorder 两份都存 | 同一信息两种表示（`response_item` 与 `item_completed`）；`ordinal` 支撑分页投影 | [codex.md](codex.md) §1.2、§1.3、§5.4、§6 |
| Claude Code | 流式循环每完成一个内容块就写一行；宿主（Desktop）把界面状态也写进同一文件 | 一次响应拆多行且 usage 重复；树形链接；元数据行反复重追加 | [claude-code.md](claude-code.md) §1.2、§1.3、§5.2、§5.3、§6 |

同一个"提问 → 调工具 → 回答"的会话，在六家的链接方式：

```mermaid
flowchart LR
  subgraph PI["pi：id/parentId 树"]
    direction TB
    p0["session 头行"] --> p1["user"] --> p2["assistant<br/>thinking + toolCall"] --> p3["toolResult<br/>toolCallId"] --> p4["assistant<br/>text"]
    p1 --> p5["分支：/tree 后的新提问"]
  end
  subgraph CC["Claude Code：uuid/parentUuid 树"]
    direction TB
    c1["user"] --> c2["assistant thinking<br/>message.id A"] --> c3["assistant tool_use<br/>message.id A"] --> c4["user tool_result"] --> c5["assistant text<br/>message.id B"] --> c6["system<br/>turn_duration"]
  end
  subgraph CX["Codex：ordinal 线性 + 外键"]
    direction TB
    x0["session_meta"] --> x1["task_started<br/>turn_context"] --> x2["user message<br/>+ UserMessage"] --> x3["reasoning<br/>tool call call_id"] --> x4["CommandExecution<br/>tool output call_id"] --> x5["assistant message<br/>+ AgentMessage"] --> x6["task_complete"]
  end
  subgraph DS["DSH：seq 连续的事件"]
    direction TB
    d0["header"] --> d1["turn/start<br/>step/start"] --> d2["user/message"] --> d3["assistant/message"] --> d4["tool/call"] --> d5["tool/result<br/>sourceEventSeqs"] --> d6["step/end<br/>turn/end"]
  end
  subgraph OC["OpenCode：扇形挂在 user 下"]
    direction TB
    o0["session 行"] --> o1["user message"]
    o1 --> o2["assistant 1<br/>step-start, reasoning,<br/>tool, step-finish"]
    o1 --> o3["assistant 2<br/>step-start, text,<br/>step-finish"]
  end
  subgraph HM["Hermes：自增 id 线性"]
    direction TB
    h0["sessions 行"] --> h1["user"] --> h2["assistant<br/>tool_calls"] --> h3["tool<br/>tool_call_id"] --> h4["assistant<br/>finish stop"]
  end
  PI ~~~ CC ~~~ CX ~~~ DS ~~~ OC ~~~ HM
```

## 4. 同一次 chat 在六家的落盘对照

场景：新会话，用户提 1 个问题；模型第 1 次调用给出推理和 1 个工具调用；工具执行；模型第 2 次调用给出最终回答。各单元格按写入顺序列出产生的记录；完整示例见各报告 §7。

| 阶段 | pi | Hermes | DSH（HEAD v4） | OpenCode | Codex | Claude Code |
| --- | --- | --- | --- | --- | --- | --- |
| 会话创建 | 内存中备好 `session` 头行、`model_change`、`thinking_level_change`，等首条 user 消息时一起写出 | `sessions` 行 upsert，`system_prompts` 行 | 头行 `type:"session"`；本机 v0 的 Web 会话在第一个回合前还有 `permission/preset`、`sandbox/mode`、`approval/policy` | `session` 行（`POST /session`） | 首条输入时物化，写 `session_meta`（ordinal 0） | 没有头行；Desktop 先写 `queue-operation` |
| 用户输入 | `message(system)`（首轮的全量 prompt 分段与工具定义）、`message(user)` | `messages(role=user)`，在第一次调用模型之前写 | `agent/inbox/spliced` → `turn/start` → `step/start` → `system/message` → `user/message`（人类输入与注入的上下文）→ `request/header`、`request/context` | `message(user)` + text `part` | `task_started` → 注入上下文的 `response_item` 与 `world_state` → `turn_context` → `response_item(message user)` + `item_completed(UserMessage)` | `user`（`promptId`、`permissionMode`）、若干 `attachment`、`file-history-snapshot` |
| 第 1 次调用（推理 + 工具调用） | `message(assistant)`：`thinking`、`toolCall`、`usage`、`stopReason:"toolUse"` | `messages(role=assistant)`：`tool_calls`、`reasoning*`，在执行工具之前写 | `assistant/message`：`reasoning`、`tool-call`、嵌入的流、`usage` | `message(assistant 1, parentID=user)`，`step-start`、`reasoning`、`tool` part（pending→running） | `item_completed(Reasoning)`、`response_item(reasoning)`、`response_item(custom_tool_call)`、`token_usage_record` | 同一 `message.id` 拆两行：`assistant(thinking)`、`assistant(tool_use)`，两行 `usage` 相同 |
| 工具执行与结果 | `message(toolResult)`：`toolCallId`、`isError` | `messages(role=tool)`：`tool_call_id`，工具完成后立即写 | `tool/call` →（`approval/asked`、`approval/decided`）→ `tool/result`（`sourceEventSeqs` 指向 `tool/call`）→ `step/end` | `tool` part 覆盖为 `completed`（`output`、`time.start/end`）；`step-finish`（tokens、cost）；assistant 1 写 `finish:"tool-calls"` | `item_completed(CommandExecution)`、`response_item(custom_tool_call_output)`、`token_count` | `user(tool_result)` + `toolUseResult`；大输出写 `tool-results/`；编辑类写 `file-history-delta` |
| 第 2 次调用（最终回答） | `message(assistant)`：`text`、`stopReason:"stop"` | `messages(role=assistant)`：`finish_reason='stop'` | `step/start` → `assistant/message` → `step/end` | `message(assistant 2, parentID=user)`，`step-start`、`text`、`step-finish` part | `item_completed(AgentMessage)`、`response_item(message assistant, phase final_answer)`、`token_usage_record`、`token_count` | `assistant(text)`（新的 `message.id`） |
| 回合结束 | 没有专门记录 | 没有专门记录；会话结束时写 `ended_at`、`end_reason` | `turn/end{reason:completed}`；随后异步写 `session/title` | assistant 写 `time.completed`，没有回合记录；后台写标题 | `task_complete`（`duration_ms`、`time_to_first_token_ms`） | `system/turn_duration`，并重追加 `last-prompt`、`ai-title` 等元数据 |
| 用量落在哪里 | 每条 assistant 的 `usage`（含美元 cost） | `sessions` 汇总列与 `session_model_usage`，由后台线程增量写 | 每条 `assistant/message.usage`（无 cost） | `step-finish` part（含 cost），累加到 assistant 与 `session` 行 | `token_usage_record`（按 `response_id`）；`token_count` 是累计快照；无 cost | 每行 `message.usage`，需按 `message.id` 去重；`cost-state` 是进程累计 |
| 本例记录数 | 8 行 | 1 行 sessions、1 行 system_prompts、4 行 messages，另有用量行 | 头行 + 20 个事件 | 1 行 session、3 行 message、约 7–9 行 part，每次写入另追加 1 行 event | 20 行 | 10 行，另有元数据重追加行 |

## 5. 总对比表

### 5.1 存储与组织

| 维度 | pi | Hermes | DSH | OpenCode | Codex | Claude Code |
| --- | --- | --- | --- | --- | --- | --- |
| 权威存储 | JSONL 文件 | SQLite `state.db` | 多个 zstd 帧拼接的 JSONL 事件日志 | SQLite `opencode.db`（WAL） | JSONL rollout | JSONL transcript |
| 默认位置 | `~/.pi/agent/sessions/--<cwd>--/<时间>_<id>.jsonl` | `~/.hermes/state.db`，每个 profile 一个库 | `~/.dsh/sessions/--<cwd>--/<id>/session.v4.jsonl.zstd` | `~/.local/share/opencode/opencode.db`，macOS 也是这个路径 | `~/.codex/sessions/YYYY/MM/DD/rollout-<本地时间>-<id>.jsonl` 与 `archived_sessions/` | `~/.claude/projects/<编码 cwd>/<id>.jsonl` |
| 根目录覆盖 | `PI_CODING_AGENT_DIR`；会话目录另有 `PI_CODING_AGENT_SESSION_DIR`、`--session-dir`、`sessionDir` | `HERMES_HOME`、profile | `DSH_HOME`、profile patch | `XDG_DATA_HOME`、`OPENCODE_DB`；非正式渠道库名为 `opencode-<channel>.db` | `CODEX_HOME`、`CODEX_SQLITE_HOME` | `CLAUDE_CONFIG_DIR`、`CLAUDE_CODE_PROJECT_DIR_NAME` |
| 会话粒度 | 一个文件，含全部分支 | `sessions` 一行加 `messages` 多行 | 一个目录，取最高代日志文件 | `session` 一行加 `message`、`part` 多行 | 一个文件；revert 后是一条文件链 | 一个文件，加同名目录（子代理、大输出） |
| 会话 ID | UUIDv7 | `YYYYMMDD_HHMMSS_<hex>`（本地时间）；ACP 为 uuid4 | 顶层 `session-<uuid4>`；子代理为裸 uuid4 | `ses_` + 26 字符，按时间降序 | UUIDv7 | UUIDv4 |
| 项目归属 | 头行 `cwd`（目录名有损） | `sessions.cwd`、`git_repo_root` | 头行 `cwd`（目录名有损） | `project_id`（git 远程或根 commit 的哈希）与 `directory` | `session_meta.cwd` 与 `git`；`turn_context.cwd` 可变 | 每行 `cwd`（会话内可变，目录名有损） |
| 写入方式 | 同步逐行追加 | 每次 flush 一个事务；有 CAS 改写与软删除 | 200 ms 一批，每批一个 zstd 帧并 fsync | 每次 upsert 覆盖行，同一事务追加 `event` | writer task 逐行追加并 flush | 逐行追加；元数据行反复重追加 |
| 并发控制 | 无 | 回合租约、压缩租约 | `session.lock`（HEAD） | SQLite WAL、IMMEDIATE 事务 | `thread-writer-locks/<id>.lock` | 无 |
| 版本与迁移 | 头行 `version`（3），打开旧文件时迁移并重写 | `schema_version`（31），列声明式补齐 | 格式代 v0–v4，升级时写新代文件、旧代保留 | 迁移表；旧 JSON 存储已不再读取 | `history_mode` 分 legacy 与 paginated，迁移会原地改写文件 | 没有 schema 版本，每行带 CLI `version` |
| 保留与清理 | 不清理 | `sessions.auto_prune` 默认删除结束且 90 天不活跃的会话 | 不删除 | 不自动删除会话；`tool-output/` 与快照保留 7 天 | 不删除，可归档 | 默认 30 天后删除 |

### 5.2 消息与轨迹

| 维度 | pi | Hermes | DSH | OpenCode | Codex | Claude Code |
| --- | --- | --- | --- | --- | --- | --- |
| 记录单元 | 一行一个 entry，消息完成时写 | 一行一条消息 | 一行一个事件（v0 另有流式分片打包行） | 一行一条 message 或一个 part | 一行一个 item 或事件 | 一行一个 entry，assistant 按内容块拆行 |
| 消息方言 | 自定义 `AgentMessage`，`api` 字段记录实际 API | OpenAI Chat 形状，加推理旁路列 | 自定义中立格式（`ContentBlock`） | 自定义 part，经 AI SDK 转换 | OpenAI Responses 原生 item，另有 UI 层 `TurnItem` | Anthropic Messages 原生结构，外加信封字段 |
| 角色 | system、user、assistant、toolResult、bashExecution | user、assistant、tool；system 不入表 | system、developer、user、assistant、tool（v4） | user、assistant | message 的 user、assistant、developer，加各类 item | `type` 为 user、assistant、system、attachment 等 |
| 链接模型 | `id`/`parentId` 树，当前位置是最后一行 | 自增 `id` 线性；会话之间用 `parent_session_id` | `seq` 线性；`sourceEventSeqs` 回指 | 本轮 assistant 的 `parentID` 都指向 user；子会话用 `parent_id` | `ordinal` 线性，加 `turn_id`、`call_id`、`response_id` 外键；文件之间用 `history_base`、`parent_thread_id` | `uuid`/`parentUuid` 树：并行工具侧枝、rewind 分支、压缩新根 |
| 一次模型调用 | 一条 assistant entry | 一行 assistant | step 内一条 `assistant/message` | 一条 assistant message（step-start 到 step-finish） | 一条 `token_usage_record` 及对应的一组 item | 同一 `message.id` 的若干行 |
| 工具调用关联 | `toolCall.id` = `toolResult.toolCallId` | `tool_calls[].id` = `tool_call_id`；id 重复时用 `tool_call_uid` | `tool-call.id` = `tool/call.callId` = `tool/result` 的 `toolCallId` | tool part 自带 `callID` 与状态 | `call_id`；Code Mode 嵌套工具只能靠 `turn_id` 和行序 | `tool_use.id` = `tool_result.tool_use_id`；`sourceToolAssistantUUID` |
| 工具成败 | `toolResult.isError` | `effect_disposition` 与结果文本 | `tool/result` 的 `isError`、`error` | `state.status` 为 completed 或 error | `item_completed` 的 `status`、`exit_code`（`*_output` 里没有成败标志） | `is_error`、`toolDenialKind` |
| 大工具输出 | 截断后写入会话；bash 全文写到 `$TMPDIR`（临时） | 外置到 `cache/spillover/`，24 小时过期 | 截断后写入日志；全文写到 `$TMPDIR/dsh-spill-*`（临时） | 截断后入库；全文写到 `tool-output/`，7 天 | 完整输出写入 rollout，截断只作用于发给模型的历史；没有外置文件，图片以 base64 内联 | 超过 5 万字符写到 `<id>/tool-results/` |
| 推理内容 | `thinking` 明文加 `thinkingSignature` | `reasoning`、`reasoning_content`、`reasoning_details`、`codex_reasoning_items` 多列 | `reasoning` 明文；签名在 `replayState` | `reasoning` part；换模型后降级为普通文本 | `summary` 加 `encrypted_content`（全部加密） | `thinking` 加 `signature`，约一半只有签名 |
| 流式增量 | 不落盘 | 不落盘；中断时保留已输出的部分 | v0 逐个增量落盘；v2 起压缩后嵌入消息 | 不落盘；part 先写空值、结束时写全文 | 不落盘 | 按内容块落盘，不含 token 级增量 |
| system prompt 与工具定义 | 首轮 `system` 消息存全量分段与 `toolsAdded`，之后只存变化 | `system_prompts` 表按哈希去重；`tool_names` 指向工具数组 | v0 在 `request/header`，v3 起为 `system/message`；工具 schema 在 `request/header` | 不落盘（V1） | `session_meta.base_instructions` 与注入的 developer 消息；工具定义不全量保存 | 不作为字段保存；新版本有 `prompt_snapshot`、`deferred_tools_record` 附件 |

### 5.3 计量

| 维度 | pi | Hermes | DSH | OpenCode | Codex | Claude Code |
| --- | --- | --- | --- | --- | --- | --- |
| token 粒度 | 每次调用一份 `usage` | 会话累计与按「模型 × provider × 任务」累计；消息行没有 token | 每个 step 一份 `usage` | 每个 step 一个 `step-finish`；assistant 取最后一步，session 累计 | 每次调用一条 `token_usage_record`，另有累计的 `token_count` | 每次调用一份 `usage`，拆行后重复 |
| 缓存与推理口径 | `totalTokens` = 输入 + 输出 + 缓存读写；推理计入输出 | 输入、输出、缓存读写、推理分列 | 输入（不含缓存）、输出、缓存读、缓存写互不相交 | 输入不含缓存，输出不含推理 | 输入含缓存命中（`cached_input_tokens` 是其中一部分） | `input_tokens` 不含缓存；思考 token 在 `output_tokens_details` |
| 美元成本 | 每次调用，按价目表计算 | `estimated_cost_usd`、`actual_cost_usd`（会话级与按模型） | 无 | 每个 step 的 `cost`，按 models.dev 价目计算 | 无，只有 `rate_limits` 百分比 | 进程累计的 `cost-state.totalCostUSD` |
| 模型与 provider | assistant 的 `api`、`provider`、`model`；`model_change` | `sessions.model`、`billing_provider`；`session_model_usage` | `assistant/message.source` 的 `provider`、`model`；`request/header` | assistant 的 `providerID`、`modelID` | `turn_context.model`、`session_meta.model_provider` | `message.model`，没有 provider 字段 |
| 时间戳 | entry 为 ISO 字符串；消息为 epoch 毫秒 | epoch 秒（REAL） | epoch 毫秒 | epoch 毫秒 | 行 `timestamp` 为写入时刻的 UTC ISO（毫秒） | ISO UTC 毫秒，内容块完成时刻 |

### 5.4 控制流

| 维度 | pi | Hermes | DSH | OpenCode | Codex | Claude Code |
| --- | --- | --- | --- | --- | --- | --- |
| 压缩 | 追加 `compaction` entry（摘要、`firstKeptEntryId`、system 检查点），旧 entry 保留 | 默认就地：旧行 `active=0, compacted=1`，插入摘要行；遗留模式另开子会话 | `compaction/*` 事件，加 `surfaceOp: replace` | compaction user、`summary:true` 的 assistant、合成的 continue；prune 只给旧工具输出打标 | `compacted{replacement_history}`，加 `world_state`、`turn_context` | `system/compact_boundary` 开新根，`logicalParentUuid` 回指，加 `isCompactSummary` 行 |
| 分支、fork、rewind | 同文件分叉（`/tree`）；`/fork`、`/clone` 写新文件（`parentSession`） | rewind 软删除（`active=0`）；`/branch` 拷贝到子会话 | fork 开新会话，父会话前缀作为种子（`isSeeded`） | revert 提交时删除撤销点之后的消息行；fork 拷贝到新会话，不设 `parent_id` | fork、revert 用 `history_base` 指向父文件前缀；legacy 有回滚标记 | rewind 在同一文件分叉；fork、`/clear` 开新会话 |
| 文件快照 | 无 | shadow git，默认关闭，与会话无外键 | 无持久快照 | 影子 git，part 里存 tree hash | 无 | `file-history-snapshot`/`delta`，备份在 `~/.claude/file-history/` |
| 子代理 | 无内置 | 子会话（`parent_session_id`、`_delegate_from`）；父会话 tool 行里有结果 JSON | 子会话目录（头行 `origin:"subagent"`、`parentSession`、`delegationDepth`） | 子会话（`parent_id`）；父 tool part 存子会话 id | 子 rollout，先复制父前缀（`subagent_history_start_ordinal`）；`thread_spawn_edges` | `<id>/subagents/agent-<id>.jsonl` 与 `.meta.json` |
| 审批与权限 | 无 | 不落事件；被拦截的调用记 `effect_disposition='none'` | `approval/asked`、`approval/decided` 等完整落盘 | 不落盘 | 不落盘；只有 `declined` 状态和 guardian 子线程 | 只记拒绝原因（`toolDenialKind`）与权限模式 |
| 错误与中断 | `stopReason` 为 error/aborted，加 `errorMessage`；重试用 `context_edit` 标记 | `failed_turn` 行、`interrupted` 元数据、`effect_disposition` | `turn/end` 原因、`assistant/attempt`、`llm/retry`；resume 时补写闭合事件 | message `error`、tool part `error` | `turn_aborted`、`task_complete.error` | `system/api_error`、`<synthetic>` 行、中断标记文本 |
| 标题 | `session_info`（只有手动命名） | `sessions.title` 与 `title_source` | `session/title` 事件 | `session.title` | `session_index.jsonl` 与 `threads.title` | `ai-title`、`custom-title` 元数据行 |

### 5.5 读取、导出与互通

| 维度 | pi | Hermes | DSH | OpenCode | Codex | Claude Code |
| --- | --- | --- | --- | --- | --- | --- |
| 搜索索引 | 无 | FTS5：词索引、trigram、CJK | 可选 FTS5，默认关闭 | 无全文索引，标题 `LIKE` | `state_5` 元数据索引，加文件内容匹配 | 无 |
| 导出与分享 | HTML、当前分支 JSONL、`/share` | `sessions export`：jsonl、md、html、trace | session-query 的 ZIP 导出 | `opencode export`/`import`，分享到 opncd.ai | `exec --json` 事件流，app-server 分页接口 | `/export` 纯文本，`stream-json` |
| 训练轨迹 | 无专门格式（evals 用原生 JSONL） | ShareGPT（`<think>`、`<tool_call>`、`<tool_response>`），需显式开启；还有 batch_runner、trajectory_compressor | 无 | 无 | 无专门格式；rollout 本身可回放到 Responses API | 无 |
| 跨 agent 导入 | 可导入外部 pi JSONL | 导入 Claude Code、Codex 会话，只保留文本轮次 | 子代理可调用外部产品；兼容 Claude Code 与 Codex 的 hook 协议 | 无 | 导入 Claude Code、Cursor 会话，有损，只保留文本 | 无；它的 JSONL 被 Codex、Hermes 读取，Hermes 的 trace 导出也采用它的形状 |

## 6. 异同分析与对 Tandem 的启示

### 6.1 共同点与差异的来源

**共同点**

- 都在本地落盘，都以"追加"为主；即使是 SQLite 的两家，也是先插入、后修补或打标志。
- 工具调用与结果都靠 provider 下发的 call id 配对，没有一家自己重新编号。call id 在 Hermes 里可能重复，所以 Hermes 另加了 `tool_call_uid`。
- 压缩都保留原文，只改变"模型下次能看到什么"。
- 会话文件或会话行都是懒创建：没真正发出消息的会话不会留下数据。pi、Codex 在首条用户输入时物化；DSH 在首次追加时原子发布；Hermes 在首个回合开始时 upsert。OpenCode 是例外，在 `POST /session` 时就建 `session` 行。
- cwd 编码成目录名的规则都是有损的（pi、DSH、Claude Code），项目归属必须读记录里的 `cwd`。

**差异的来源**：数据形态基本由"谁在什么时机写"决定（§3 表格）。

- 写入者订阅"消息完成"事件（pi），就得到干净的消息日志。
- 写入者紧跟流式循环、按内容块落盘（Claude Code），就得到拆行与重复 usage。
- 写入者是同时服务模型回放与 UI 分页的事件总线（Codex），同一信息就会存两份。
- 写入者是插件化的事件日志（DSH），就得到事件溯源和投影。
- 写入者是服务端事务加投影（OpenCode），就得到可覆盖的关系行。
- 多个宿主共用一个库（Hermes），就需要租约、软删除和大量展示列。

**对解析的直接影响**

| 问题 | 需要按 agent 区分的规则 |
| --- | --- |
| 哪些 user 记录是真人输入 | pi：`role=user`；Claude Code：排除 `isMeta`、只含 `tool_result` 的行、压缩摘要，看 `origin.kind`；Codex：带 `metadata.user_input_order` 的 user 消息或 `UserMessage` 条目，注入的上下文也是 `role=user`；DSH：`source.kind:"user"`；OpenCode：排除 synthetic text 与 compaction part；Hermes：排除 `display_kind` 为 steer、model_switch、async_delegation_complete 等的行 |
| 一次模型调用怎么合并 | 见 §5.2「一次模型调用」一行 |
| token 怎么去重 | Claude Code 按 `message.id` 取一次；Codex 用 `token_usage_record`，`token_count` 只取最后一条作快照；OpenCode 用 `step-finish`，不要再加 assistant 上的值；子会话的用量都不含在父会话里，需要递归汇总（OpenCode、Hermes、Codex） |
| 回合边界 | 显式：Codex（`task_started`/`task_complete`）、DSH（`turn/start`/`turn/end`）、Claude Code（`promptId` 与 `system/turn_duration`）；隐式：pi、Hermes、OpenCode 只能由真人 user 记录推出 |
| 重放与复制 | Claude Code 的 fork 等操作会把历史复制进新文件（本机有同一 `uuid` 出现在多个文件）；Codex 子代理先复制父前缀；DSH fork 带种子前缀；Hermes `/branch` 复制历史但保留 `message_uid`；pi `/fork` 复制 entry 并保留原 id。统计时都要识别副本 |

### 6.2 对数据方案的补充与修正

[data-acquisition.md](../../plan/data-acquisition.md) 已经吸收了这批报告的大部分结论（DSH 新旧两代格式、Claude Code 的单链回溯问题与子代理占位 usage、Codex 的原地改写与审批、Hermes 与 OpenCode 的接入要点）。与方案当前版本（`7621e70`）逐条比对后，下面几处仍与源码不一致或缺失：

1. **pi**：方案写「首次助手回复前不落盘」。0.99.1 与 HEAD 都在首条 user（或 assistant）消息出现时建文件，用户的 prompt 先于首个回答落盘（[pi.md](pi.md) §4.1）。方案写「`subagent-artifacts/` 下的文件与主会话重复，跳过」，但 pi 源码中没有这个目录，pi 也没有内置子代理（§5.5），这条应删去或注明来自第三方扩展。方案列出的条目类型之外，还有 `usage`（缓存保温）、`context_edit`（重试时省略失败回合）、`custom_message`、`label`、`session_info`（§3.3）。
2. **OpenCode**：方案写「V2 表（`session_v2`、`session_message`）」。HEAD 的库里没有 `session_v2` 表；V2 的表是 `session_message`、`session_input`、`session_context_epoch`，会话行仍在 `session` 表。另外两点值得写进连接器：revert 提交时会删除撤销点之后的消息行，并从会话累计中扣回这些消息的用量，没有提前归档就会丢失这部分历史；ID 的 48 位时间前缀约 795 天回绕一次，不要按 ID 排序或推算时间（[opencode.md](opencode.md) §2.4–§2.6、§5.4）。
3. **Claude Code**：方案写「`--resume`、`--fork-session`、后台会话会把历史复制进新文件」。SDK 的端到端测试断言 `--resume` 沿用原 `sessionId`、追加到原文件，`--fork-session` 才是新文件（[claude-code.md](claude-code.md) §4.4）。本机 830 个重复 `uuid` 也可能来自 fork 与后台会话；两种说法也可能对应不同入口或版本，接入时用本机样本确认。
4. **Codex**：`function_call_output` 不序列化成败标志，工具成败以 `item_completed` 的 `status`、`exit_code` 为准；Code Mode 的嵌套工具条目 id 是 `exec-<uuid>`，与外层 `exec` 的 `call_id` 无关，只能按 `turn_id` 与行序归属，本机约 11% 的嵌套条目写在 `exec` 输出之后（[codex.md](codex.md) §3.5、§5.2）。
5. **Hermes**：方案写「SQLite，WAL」。源码在链接的 SQLite 有 WAL-reset 缺陷时（随包分发的 3.50.4 就在其中）让新库保持 DELETE 日志模式，所以要同时支持两种模式；`sessions.auto_prune` 默认开启，会删除已结束且 90 天不活跃的会话，与 Claude Code 的 30 天清理一样需要提前归档（[hermes-agent.md](hermes-agent.md) §4.2、§9）。
6. **标准事件映射**：方案 §4.4 的表只有 Claude Code、Codex、DSH、pi 四列，Hermes 与 OpenCode 两列见下面 §6.3。

### 6.3 补充 Hermes 与 OpenCode 的标准事件映射

方案 §4.4 的标准事件表目前有 Claude Code、Codex、DSH、pi 四列，下面补上另外两家：

| kind | Hermes | OpenCode |
| --- | --- | --- |
| `session.meta` | `sessions` 行（`source`、`cwd`、`model_config`、`profile_name`） | `session` 行（`directory`、`project_id`、`agent`、`model`、`version`） |
| `session.title` | `sessions.title` 与 `title_source` | `session.title` |
| `setting.change` | `display_kind='model_switch'` 的标记行；`model_config` 中的路由 | user message 的 `agent`、`model` 变化 |
| `turn.start` / `turn.end` | 由真人 user 行推出（一次 `run_conversation` 为一回合） | 由真人 user message 推出；结束看最后一条 assistant 的 `finish` |
| `message.user` | `role=user`，排除注入类 `display_kind` 与 `observed=1` 的旁听行 | user message 的 text part，排除 synthetic、compaction、subtask |
| `message.assistant` | assistant 行的 `content` | text part |
| `reasoning` | `reasoning`、`reasoning_content`、`reasoning_details`、`codex_reasoning_items` | reasoning part |
| `tool.call` / `tool.result` | assistant 行的 `tool_calls` / tool 行 | tool part（`callID`、`state`） |
| `model.usage` | `session_model_usage`（只有累计，没有逐次） | `step-finish` part |
| `context.inject` | `api_content` 与 `content` 的差异；`system_prompts` | 不落盘（V1） |
| `context.compaction` | `_compressed_summary=1` 的行；`active`、`compacted` 标志 | compaction part 与 `summary:true` 的 assistant |
| `permission.request` / `permission.decision` | 不落盘；只有 `effect_disposition` | 不落盘 |
| `branch` | `parent_session_id` 加 `_branched_from`、`_reset_from`；rewind 的 `active=0` | fork 出的新会话；`session.revert` |
| `subagent.spawn` / `subagent.result` | `_delegate_from` 子会话；父 tool 行的结果 JSON；`async_delegations` | 子会话 `parent_id`；tool part 的 `metadata.sessionId` |
| `plan.update` | 按工具名识别 | `todo` 表 |
| `file.change` | 工具参数 | `patch` part、快照 hash |
| `error` | `failed_turn` 行、`finish_reason`、`effect_disposition` | message `error`、tool part `error` |
| `ui.state` | `display_*` 列 | — |

## 7. 各 Agent 报告

| Agent | 报告 | 关键依据 |
| --- | --- | --- |
| pi | [pi.md](pi.md) | `packages/coding-agent/src/core/session-manager.ts`、`docs/session-format.md`；本机 2 个会话 |
| Hermes Agent | [hermes-agent.md](hermes-agent.md) | `hermes_state*.py`、`agent/session_persistence.py`、`agent/trajectory.py` |
| DeepSeek Harness | [dsh.md](dsh.md) | `packages/core/session`、`packages/session/session-persistence-jsonl`；本机 79 个会话 |
| OpenCode | [opencode.md](opencode.md) | `packages/core/src/database`、`packages/opencode/src/session` |
| Codex | [codex.md](codex.md) | `codex-rs/rollout`、`codex-rs/protocol`、`codex-rs/thread-store`；本机 906 个 rollout |
| Claude Code | [claude-code.md](claude-code.md) | Agent SDK 的会话读写实现、`sdk.d.ts`、CHANGELOG；本机 126 个主会话 |

每份报告结构相同：元信息 → 结构图与一次 chat 的时序图 → 存储布局 → 记录 schema → 写入语义 → trajectory 数据形态图 → 结构 ↔ 数据对照表 → 一次 chat 的完整落盘示例 → 本机核对 → 解析要点 → 可比较维度速查 → 源码索引。

## 8. 复现

源码浅克隆到指定 commit（以 pi 为例，其余仓库替换 URL 与 commit 即可）：

```bash
git init pi && git -C pi remote add origin https://github.com/earendil-works/pi.git && git -C pi fetch --depth 1 origin 88ff80b986e34d4fbd1fa94a4df65c60ae964516 && git -C pi checkout FETCH_HEAD
```

| 仓库 | commit |
| --- | --- |
| `https://github.com/earendil-works/pi.git` | `88ff80b986e34d4fbd1fa94a4df65c60ae964516` |
| `https://github.com/NousResearch/hermes-agent.git` | `44a1ce9724502b9c692faaef00af3054bf11f1a6` |
| `https://github.com/deepseek-ai/deepseek-harness.git` | `639ed015397290b3745d163aafe02ffee4aa3f84` |
| `https://github.com/anomalyco/opencode.git` | `63cf236140b11c15cd645e90a7ded77bdc2193b4` |
| `https://github.com/openai/codex.git` | `9552906b2b8358121f71695e1e6602791cdcecc0` |
| `https://github.com/anthropics/claude-agent-sdk-python.git` | `db750b20a88ae9645b1674d95193a88c89a265f9` |
| `https://github.com/anthropics/claude-agent-sdk-typescript.git` | `0e21ebb22c36caca1220c34ae6c9fe8ddad40e47` |
| `https://github.com/anthropics/claude-code.git` | `6160717d8994f236ab381cf534fc1cde5347c12f` |

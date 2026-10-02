# Agent 导入与标准化模块

本模块按 `yhyfhgs` 的选择统一在 `packages/data` 的 Python 实现内。它复用 PR #9 的 canonical 数据契约，不建立第二套 canonical 数据库；PR #11 的 TypeScript Codex staging 仍可通过原有归档桥接接入。

当前原生采集改用来源引用，完整正文和 App trajectory 接口见 [来源索引](indexed-trajectories.md)。历史实测数值对应当时版本。

## 运行与查看

需要 Python ≥ 3.13、uv，支持 macOS / Linux。在仓库根目录运行：

```sh
# 一键：环境、静态检查、单元/功能/CLI E2E、打包、六种原生格式演示、本机真实样本、性能测量
bash scripts/check-data.sh --real --open

# CI / 不读个人会话：省略 --real
bash scripts/check-data.sh

# 明确选择全量真实 DSH（默认真实验证每来源最多 2 个已静置 2 分钟、≤16 MiB 的主转录）
bash scripts/check-data.sh --real --full --agent dsh --open
```

每次使用独立的 `.local/connector-checks/<UTC时间>-<随机ID>/`，不覆盖历史结果。`report.html` 提供来源状态、L1/L2 计数、时间线、标准事件与 L3 派生行；`results.json` 是机器可读结果。查看页离线运行，无 CDN、网络请求或模型调用；外部文本只通过 `textContent` 展示。原始会话、数据库、报告只留在忽略目录。

真实来源缺席显示 `unavailable`，找不到符合边界的样本显示 `no_eligible_sample`；不能把它们当成真实测试通过。有未解析记录或捕获失败时退出码为 2，仍写出报告。未知类型生成 `unknown` 事件并报告诊断，不静默跳过。样本的索引数不等于全量覆盖。

日常导入：

```sh
uv run --project packages/data tandem-data discover
uv run --project packages/data tandem-data --home .local/tandem scan --agent claude_code --root ~/.claude
uv run --project packages/data tandem-data --home .local/tandem scan --agent kimi --root ~/.kimi-code
uv run --project packages/data tandem-data --home .local/tandem verify
uv run --project packages/data tandem-data --home .local/tandem rebuild
```

名字为 `claude_code / opencode / dsh / pi / hermes / kimi`，原有 `codex` 保留。`scan --limit N` 为有界样本；`ingest --file` 必须命中来源白名单。导出拒绝覆盖已有文件或写入 Agent 目录。CSV 对公式起始的文本加单引号作为字面量，JSONL 保持标准投影内容；完整原件仍在 L0。

## App 接入方式

```python
from pathlib import Path
from threading import Event
from tandem_data.store import Store
from tandem_data.service import ImportRequest, ImportService, event_page

with Store(Path.home() / 'Library/Application Support/Tandem') as store:
    service = ImportService(store, progress=lambda status: print(status))
    result = service.import_source(ImportRequest('pi', Path.home() / '.pi/agent'))
    # 进度回调不包含会话正文；可转成 App 的 IPC progress 消息。
    # service.watch(request, stop=Event(), interval=2) 提供可取消的轮询迭代器。

# App 查询走只读连接和 seq 游标，页大小最多 1000。
page = event_page(Path.home() / 'Library/Application Support/Tandem', session_uid, limit=100)
```

App 负责选择/启用来源、启动一个后台 worker、显示进度/覆盖和分页数据。采集 worker 独占输出目录的 `import.lock`（POSIX advisory lock），不锁定源 Agent。一次导入可在文件之间取消；L2/L3 事务提交后读者看到新投影。每个 worker 线程使用自己的 Store；不要把 sqlite3 连接跨线程共享。App 的分析入口仍是 `analysis_input.read_analysis` 和 `v_analysis_*` 视图，不依赖各家 native 字段。

## 文件职责

| 文件/目录 | 职责 |
| --- | --- |
| `service.py` | 来源导入任务、单写者、进度、取消、轮询 |
| `discovery.py` | 根目录、环境变量、路径白名单、DSH 代次选择；不读取凭据 |
| `store.py` | SQLite 迁移、来源索引与旧归档兼容、L1 行版本、原文读取与哈希校验 |
| `connectors/base.py` | 小型 mapper 协议、公共消息块与 usage 归一；不承担文件 IO |
| `connectors/{claude_code,opencode,dsh,pi,hermes,kimi}.py` | 原生语义、身份、时间、分片/重放规则 |
| `pipeline.py` | 按来源重建 L2、记录全记账、去重、证据关联、事务发布 |
| `contract.py`、`schemas/` | Python 类型、UTC 时间语义、JSON Schema、生成的表字段字典 |
| `reduce.py` | L3 项目、轮次、工具配对、逐请求用量、独立累计快照、基础特征 |
| `analysis_input.py` | 分析范围、覆盖说明、只读分析输入 |
| `query.py` | 统一投影新鲜度检查、App 游标读取；分析/导出/分页都拒绝过期版本 |
| `migrations/` | 权威 DDL；契约仍为 v1，存储 user_version=6（兼容升级 v1） |
| `validation/` | 原生格式构造样本、真实样本验证、离线查看页、性能测量 |
| `tests/data/` | 单元、语义回归、SQLite/WAL 功能测试、CLI 和完整模块 E2E |

没有加入消息队列、服务器、ORM 或通用 ETL 插件框架。新增 Agent 只需明确发现规则、实现 `prepare/map` 并注册 mapper；新增语义必须有构造样本和证据记账断言。

## 数据与正确性

- 原生 JSONL / JSON / zstd 和白名单 SQLite 表只读索引；L0 保存位置和哈希，不复制整个 session。SQLite 通过一次读事务按主键建立行索引。
- L1 记录来源、位置、版本、哈希、去向和事件关联。半行待补齐；损坏压缩帧不会推进索引。上游删除或改写后，原文读取明确报告不可用状态。
- L2 保存完整脱敏正文，取消文本和字段长度截断。未知类型保留 L1 索引和诊断，可按需打开原文；内联媒体与加密字段使用引用。
- `verify` 校验当前引用、记录摘要、旧归档、证据关联、Schema、外键和数据库完整性；不可读来源报告 partial。
- 时间按各来源声明的单位转换；缺失时间仍为 null。排序使用 native seq/行序；SQLite V2 按 `(session_id, seq)`，不以消息 ID 的字典序充当轨迹顺序。
- 累计快照和逐次用量分开存储，零成本与未知成本不同；不按公开价目表猜账单。模型原名和路由保留，规范模型映射沿用 `model_alias`。
- 来源索引先提交，重建失败时回滚 L2/L3；`watermark.projected_revision` 只在成功发布时更新。取消/失败后可恢复。未变化来源不解压、不重建，变化来源单独重算；模型/mapper/reducer 版本改变会使旧投影失效。

## 来源差异与覆盖

| Agent | 实现与测试重点 | 已知边界 |
| --- | --- | --- |
| Claude Code | 多根目录、JSONL 内容块、人类/注入/通知区分、工具拒绝/中断/耗时、分片用量选择最终完成观测、UUID 重放、cost-state 累计、subagent/workflow 元数据 JSON | CLI 闭源，依据官方 SDK、项目源码调研与本机样本；没有最终用量的子代理仍标未知覆盖，不编造完整计费 |
| OpenCode | SQLite V1 message/part、V2 session_message 原生序号、同会话 V2 优先、嵌入工具状态、原地更新/删除、毫秒端点、output+reasoning | 不凭 fork 标题相似就把另一会话的请求删掉；缺乏明确 lineage 的旧复制历史保留原始证据 |
| DSH | v0–v4、最高代、拼接 zstd 帧、打包分片归并、残缺流保留、v0–v3/v4 工具结果差异、seed、独立 retry/compaction usage、slash command 与审批 | 结果落盘顺序可能等待前序工具，事件差值只标估计耗时；缺父证据的 seed 明确报告缺口 |
| pi | v3 树、模型/思考设置、fork 原 entry ID + 完整记录一致性、人类/扩展/系统消息、工具与手动 bash、compaction、辅助 usage | 无父会话证据时不会仅凭短 entry ID 跨会话去重 |
| Hermes | sessions/messages/session_model_usage/system_prompts、稳定 message_uid、inactive/compacted/rewind、tool_call_uid、秒时间、分模型累计版本 | 原生只有累计用量时不生成虚构 model_call；无成功字段的工具状态保持 unknown |
| Kimi Code | `~/.kimi-code` / `KIMI_CODE_HOME`、wire 1.x 持久事件、index 工作目录、agent 分离、loop 消息/工具、usage.record 与 step.end 去重、控制/审批/compaction/branch | 新 Kimi Code wire 1.0–1.5；早期 `~/.kimi` Python CLI 的另一套 wire 及迁移副本尚未宣称兼容。本机尚无真实样本 |

性能取舍：变化文件流式重建索引，L1 复用未变化记录，L2/L3 按来源重算。未变化文件快速跳过；SQLite 每次读取事务快照。未实现单会话尾追，长文件重算成本仍存在。

## 验证证据

- 自动套件涵盖六家原生布局和七家公共管线（保留 Codex 回归）、重复导入、改写/截断/删除、WAL、可空时间、错误隔离、部分流、fork、JSON sidecar、取消、并发写者、导出边界及已安装 CLI。
- 2026-10-02 本机曾全量验证 DSH **79 个会话、159,023 条原始记录**：首次约 **34.9 秒**，重复扫描约 **0.017 秒**；所有归档和记录哈希一致，未解析记录为 0。这是当前机器的一次测量，不是性能承诺；后续修正了其中两种 slash-command 的映射，补齐反向外键索引后同一数据集全量重算约 **25.7 秒**，14,310 个 L2 事件、零诊断。
- Claude（含第二账号）与 pi 已跑本机历史样本。真实测试发现了 `output_tokens_details=null` 和“占位 usage → 最终 usage”，并补入永久回归。
- 本机没有 OpenCode、Hermes、Kimi 的 session；其构造/SQLite E2E 已运行，真实来源状态必须保持 unavailable，不能混写成六家均已真实验证。

## 源码与开源经验

实现为独立代码；下列项目用于核对格式、去重/只读原则与测试策略，没有复制限制许可代码。

- [Claude 官方 SDK](https://github.com/anthropics/claude-agent-sdk-python/tree/bfb895c6ef46e095191938b4eda798a025957c09)，以及仓库 `docs/research/agent-sessions/claude-code.md`。
- [DSH v0 打包 codec](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/session/session-format-v0-to-v1/src/codec.ts)、[持久化格式](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/session/session-persistence-jsonl/README.md)。不逐 token 展开为大量 Python 对象，按响应归并并保存所有原行证据。
- [pi session format](https://github.com/earendil-works/pi/blob/7fbbd5f/packages/coding-agent/docs/session-format.md)。fork 要结合 lineage 和记录一致性，不做全局短 ID 去重。
- [OpenCode V2 message schema](https://github.com/anomalyco/opencode/blob/a79ecfe/packages/schema/src/session-message.ts)、[数据库 schema](https://github.com/anomalyco/opencode/blob/a79ecfe/packages/core/src/database/schema.gen.ts)。读取原地更新后的事务快照，区分 V1 与 V2。
- [Hermes 状态存储](https://github.com/NousResearch/hermes-agent/blob/be5e9f7/hermes_state.py)、[计量存储](https://github.com/NousResearch/hermes-agent/blob/be5e9f7/hermes_state_usage.py)。累计行按完整计费主键版本化。
- [Kimi wire manifest 1.5](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/packages/agent-core-v2/docs/wire-manifest.d.ts)、[loop 归并](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/packages/agent-core-v2/src/agent/contextMemory/loopEventFold.ts)、[usage reducer](https://github.com/MoonshotAI/kimi-code/blob/21406fb4c805cc8c715e6d1f16ad3fb5f25f4fe3/packages/agent-core-v2/src/session/usage/usageAgentModel.ts)。以原生 reducer 为准：usage.record 做加法，session/turn 表示用途，不能凭名称判断累计。
- [ccusage 去重实现](https://github.com/ccusage/ccusage/blob/48785b7f3e2793ca174598c42d99547e89dec5ba/rust/adapters/claude/src/daily.rs)。借鉴稳定身份与确定性 survivor；同时用原生源码独立核对其计量假设。
- [Agent Sessions Hermes parser](https://github.com/jazzyalex/agent-sessions/blob/45535d74d738320ecaf81dfc10590b2e11c9145d/AgentSessions/Services/HermesSessionParser.swift)。借鉴只读 SQLite 与来源独立解析；Orbit 另保留完整证据和缺失值。

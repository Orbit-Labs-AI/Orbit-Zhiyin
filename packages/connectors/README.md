# Orbit Codex Connector

把 Codex Desktop / CLI 的本地轨迹导入 Orbit：原始归档 → 每条记录的处理账本 → 标准事件 → 会话、轮次、工具调用与模型调用。实现依据 `yhyfhgs` 的数据获取方案与 Codex 源码调研，使用 TypeScript、Node ≥24.7、内置 SQLite 与 zstd。没有模型调用、远程上传或凭据读取。

## 运行

在 `packages/connectors/` 执行：

```sh
pnpm install --frozen-lockfile
pnpm check
pnpm tandem init

# 仅发现来源，不导入
pnpm tandem discover --codex-home "$HOME/.codex"

# 明确启用该来源：首次回填，以后增量
pnpm tandem ingest --codex-home "$HOME/.codex"
pnpm tandem watch --codex-home "$HOME/.codex"
pnpm tandem stats
```

省略 `--codex-home` 时取 `CODEX_HOME`，再回退到 `~/.codex`。默认 staging 输出为 `~/Library/Application Support/Tandem/connectors/codex`，可以用 `--data-dir` 修改；它与统一库默认目录分开。来源根目录会规范化软链接；输出不得位于来源目录内。

用构造样本跑演示，不需要读取真实会话：

```sh
mkdir -p .local/codex/sessions
cp tests/fixtures/paginated.jsonl .local/codex/sessions/rollout-demo.jsonl
pnpm tandem ingest --codex-home .local/codex --data-dir .local/tandem
pnpm tandem stats --data-dir .local/tandem
```

构建后可直接运行 `node dist/cli.js`。`--help` 列出全部命令。`ingest` 输出 JSON，包括文件变动、失败文件、导入记录数、派生会话数、各去向计数与诊断数量；存在读取失败、会话重建失败（`rebuild_failed`）或 `unparsed` 时退出码为 2。单个会话映射或校验出错只回滚该会话：其投影保持上次结果、保留待重建标记并写 `rebuild_failed` 诊断（含脱敏后的错误与 `session_uid`），其余会话照常重建。维护锁被持有时跳过该轮，不推进游标。未知类型会归档、生成 `unknown` 事件和告警，不导致整次导入失败。

## 接入分析或 Mac App

前端与分析模块以只读方式打开 `tandem.db`，设置 `query_only`、`busy_timeout`，一次查询在一个读事务内完成。不要对 Orbit 以外的 Codex 数据库执行迁移或写入。

库入口导出 `CodexConnector`、`ConnectorStore`、`discoverCodex`、`watchCodex`、`readRawRecord`、`readRedactedRecord`、`archivedBytes`、`validateEvent` 和事件类型：

```ts
import { CodexConnector, ConnectorStore } from '@tandem/connectors';

const store = new ConnectorStore('/absolute/path/to/tandem');
try {
  const connector = new CodexConnector(store, '/absolute/path/to/codex-home');
  const result = await connector.ingest();
  console.log(result.accounting);
} finally {
  store.close();
}
```

单个进程内的监听串行执行导入，同一 Connector 禁止重入。`watchCodex` 接受 `AbortSignal`，中止后等待当前导入收尾再释放数据库。文件通知合并 1 秒，正常监听每 10 分钟扫描兜底；监听不可用时报告错误并降级到 2 秒轮询。默认一个数据库只启动一个采集进程，App 与其他模块只读。

标准数据契约采用 [001.sql](schema/001.sql) 初始化，再依次应用 [002.sql](schema/002.sql) 与 [003.sql](schema/003.sql)；当前 `PRAGMA user_version=3`、`application_id=1413697358`。002 是对齐 `analysis-input-v1` 的结构：`event.ts` 可空，新增 `event_path/native_key`、时间质量、证据多对多、上下文与累计快照。003 给 `turn` 增加 `duration_ms/ttft_ms`、给 `usage_snapshot` 增加 `counter_cycle`，并删除 Codex 记录无法填充的 `tool_call.approval_wait_ms/error_class/skill/subagent_session_uid` 与 `session.spawn_call_uid`；事件种类同时去掉从未发出的 `queue`、`subagent.message/wait/close`（子代理的等待、发消息等动作是 `tool_call`，类别 `subagent`）。旧库保留 L0/L1，由迁移重新生成 L2/L3。所有事件经过 JSON Schema 校验。

时延口径：Codex 只在 `task_complete` 报告整轮的 `duration_ms` 与 `time_to_first_token_ms`，写入 `turn`。同一轮的请求顺序发出，所以该轮首个 `model_call` 记该轮 TTFT；仅当一轮恰好一次请求且没有工具调用时，`model_call.latency_ms` 才等于该轮耗时，其余请求的 `latency_ms/ttft_ms` 保持 NULL，因为 rollout 没有逐请求计时。`cost_usd` 同样保持 NULL（`cost_source='unknown'`），本包不内置价目表。

| 层 | 表或目录 | 内容 |
| --- | --- | --- |
| L0 | `raw/<source_id>/<sha256>.zst`、`archive_chunk` | 不可变压缩块与顺序清单，可还原每代原始文件字节 |
| L1 | `source_file`、`raw_record`、`current_record`、`record_event` | 文件水位、每行位置与哈希、原生类型、去向和多对多事件关联 |
| L2 | `event`、`event_fts`、`event_context` | 稳定来源顺序、可空时间及质量、脱敏文本、当时的项目和模型设置 |
| L3 | `session`、`project`、`turn`、`tool_call`、`model_call`、`usage_snapshot`、`session_feature`、`link` | 配对调用、逐次请求与独立累计快照、基础操作特征、外部关联 |

`session_uid` 由 Agent、来源根目录的哈希和原生线程 ID 组成，避免不同配置目录相互覆盖。事件优先按原生条目 ID、工具 call ID、模型 response ID 定义 `native_key`，再按 `[native_key, kind, event_path]` 生成身份；缺少原生 ID 时使用来源记录身份。内容路径是固定语义路径，如 `tool.call`、`tool.result`、`usage.call`，不取 L2 序号。工具配对限定到线程与轮次。

每条事件携带 `attrs.time` 的来源字段、语义、质量和原始时间字段；缺时间保持 `null/missing`，写入时间标为 `written`。`seq` 来自原生 ordinal/行序和固定展开位置，时钟回退不改变顺序。工具缺少原生端点时不填精确起止；有原生耗时仍可保留耗时及 `duration_source/quality`。

`current_record` 只包含各逻辑文件的当前代；旧代仍在 L0/L1，可按 `record_uid` 取回原始字节。上游文件消失标为 `gone_upstream`，保留其最后一代及已有事件。文件改写则更新当前投影，不把旧版消息继续算进当前指标。

常用查询：

```sql
-- 当前处理账本：总数应等于所有去向之和
SELECT disposition, COUNT(*) FROM current_record GROUP BY disposition;

-- 人类输入，隔离通知、其他 Agent 和自动评审
SELECT e.* FROM event e JOIN session s USING(session_uid)
WHERE s.kind = 'main' AND e.kind = 'message.user'
  AND json_extract(e.attrs, '$.origin') = 'human';

-- 主会话及其子代理的用量；不计 guardian、导入、自动化与辅助线程
SELECT project_id, model_id, effort_raw,
       SUM(input_tokens), SUM(cache_read_tokens), SUM(output_tokens)
FROM main_model_usage GROUP BY project_id, model_id, effort_raw;

-- 实际动作；Code Mode 外层包装仍保留，分析时排除
SELECT * FROM tool_call WHERE is_wrapper = 0;
```

导出标准事件与取回证据：

```sh
pnpm tandem export --session '<session_uid>' --output .local/session.jsonl
pnpm tandem raw --record '<record_uid>'
pnpm tandem rebuild
```

`export` 输出脱敏 JSONL，拒绝覆盖已有文件或写入 Agent 来源目录。`raw` 明确读取原始字节，内容可能含未脱敏数据。分析需要完整工具输出时使用 `readRedactedRecord`，仍执行同一脱敏规则，解除 8 KB 预览预算。`rebuild` 从已保存 L1 重算，不重新读取 Agent 文件。

## 与统一数据库对接

本包写入 Connector staging 库，`packages/data` 写入 canonical 库，物理 schema 和 ID 命名不同。两者必须使用不同的目录；本包会拒绝把其他数据库当成旧 staging 库迁移。不要让两个进程共写同一个 `tandem.db`。

`packages/data` 的 `import-connector` 已能只读本包的 `source/source_file/archive_chunk/raw_record`，验证归档块与每条记录的 SHA，建立 `connector_record_link`，再由统一库重算。L0/L1 桥接不依赖 staging 的 L2/L3 表布局。

当 `packages/data` 分支可用时，在仓库根目录运行：

```sh
uv run --project packages/data tandem-data --home .local/canonical init
uv run --project packages/data tandem-data --home .local/canonical import-connector \
  --connector-home packages/connectors/.local/tandem
uv run --project packages/data tandem-data --home .local/canonical rebuild
uv run --project packages/data tandem-data --home .local/canonical verify
```

两个库的事件结构均可提供 `analysis-input-v1` 逻辑输入。本包导出的真实 L2 已通过统一库事件 Schema 校验。桥接后仍须核对 canonical 的解析去向和覆盖，不能因为归档及 crosswalk 正确就宣称重新派生已完整。

## Codex 口径

- 递归读取 `sessions/` 与 `archived_sessions/` 的 `rollout-*.jsonl(.zst)`。归档移动或压缩替换保持逻辑文件身份；revert 产生的多个 rollout 分别索引；按 threads.rollout_path 的活动文件追溯 history_base，并限制前代的 end_ordinal_exclusive，撤销尾部只留 L0/L1。没有当前索引且出现多个分支时，按原生文件名顺序推定并提示覆盖缺口。
- 最高版本 `state_<n>.sqlite` 只读打开，不用 `immutable=1`。在一个读事务内读取支持的 `threads` 元数据列、`thread_spawn_edges`、`projects` 与 `project_roots`；账号 ID 不读取。库暂时不可读时保留已有索引、报告失败，正文扫描继续。
- `session_index.jsonl` 按追加日志读取；标题优先级是 `threads.name` → 索引的最后一条 → `threads.title/preview`。`external_agent_session_imports.json.records` 标记导入来源，默认不计入主会话用量。
- 按记录形状兼容 legacy 与 paginated，不按 `cli_version` 切分。消息首选 UI 的 `item_completed` 或旧 `user_message/agent_message`；匹配的 Responses 表示去重，未匹配的 user/developer 表示作为注入上下文保留。
- 工具类别由 `normalize.ts` 的 `TOOL_CATEGORIES` 名称表决定（shell、file.edit、file.read、image.view、image.generate、subagent、plan、ask_user、web.search、tool.search、sleep、automation、mcp；Code Mode 外层包装为 `wrapper`）。表外名称归 `other` 并写 `unknown_tool_name` 诊断，`stats` 的 `unclassified_tools` 给出各名称次数。
- 工具首选完成条目的参数、`status`、`exit_code` 和 `duration`。直接工具按 call ID 去重；`exec-…` 嵌套动作与外层包装分别保留。`parent_wrapper_id` 由同轮行序关联，即使动作在外层输出之后到达也可归属，属于顺序推断。
- 用量优先每个 `response_id` 的 `token_usage_record`。同轮旧单次表示去重，`total_token_usage` 累计部分进入独立 `session_snapshot/cumulative`；没有精确记录的旧轮次，只有能关联稳定响应条目时才把 `last_token_usage` 标为 `call/delta`。累计重复不吞掉新单次值。合成的上下文窗口饱和值不计费。
- `call/delta` 派生为 `model_call`；累计事件只进入 `usage_snapshot`，不产生虚构请求 ID。`reported` 保存原始计数，缺失分桶保留 null，`coverage=self` 表示该线程的原生计量。模型与思考档位按请求当时的上下文/设置记录；模型不明确的会话累计不回填最后模型。
- 统一的输入 token 不含缓存：原生 input 减去 cache read 和 cache write；output 已含 reasoning，不再相加。原生 usage 留在 `attrs.native_usage`。`rate_limits` 根据 `window_minutes` 判断 5 小时/周窗口。
- 仅 `thread_spawn` 子代理使用继承切点；旧格式回退到触发消息或首个不在父会话里的 turn。guardian 单独标为 `review`，不套用切点。缺少父证据时保留 `replayed` 与缺口说明，不生成虚假的父事件。
- URI 形式的命令 cwd 和图片路径转成普通路径；时间转 UTC 毫秒。Git remote 规范化并归并 worktree；本地仓库不存在时使用记录里的 Git remote，再回退到路径。临时目录用常量表归入“临时工作区”：`~/Documents/Codex/`、`~/.claude/remote/` 总是归入；`/tmp`、`/private/tmp`、`/var/folders` 仅在不属于 Git 仓库时归入。
- 用量缺少 `cache_write_input_tokens` 字段时按 0 计并标 `cache_write_assumed_zero`：OpenAI usage 只有缓存读取分桶，没有缓存写入计费。其他分桶缺失仍为 null。
- 旧版协议事件：`error`/`stream_error` 映射为 `error`；`exec_command_end`、`patch_apply_end`、`mcp_tool_call_end` 按 call_id 补全对应工具结果（退出码、耗时、成败）。`web_search_end`、`background_event` 等其余旧事件暂不支持，落为 `unknown` 并告警。`exit_code=-1` 表示没有进程退出状态（拒绝、中断或未启动），状态取原生 status，不单独判失败。

## 原始归档与隐私

原方案的 L0 语义保留，物理布局采用不可变 zstd 块和事务清单。块先写临时文件、改名，再提交清单与水位；进程中断只可能留下未引用块，不会把半个压缩帧提交成有效归档。追加时只归档新增字节，包含尚未写完的 JSONL 尾行；L1 从经哈希校验的不可变归档解析，检查点也由归档计算，避免源文件在两次读取间改写造成证据错配；偏移只越过完整行。

每个文件记录设备、inode、大小、纳秒 mtime、头部与已归档尾部哈希、行号、原生 ordinal 和字节偏移。截断、替换、同大小改写或检查点不匹配触发新一代归档和全文件重扫。压缩文件增量解码需从头穿过帧，但已完成的解压行会跳过。维护锁是持久文件，不能仅按存在判断忙碌；Linux 只读检查 `/proc/locks`，macOS 用 `lsof` 保守检测打开的维护描述符，无法检测时仍用前后 stat 检查保护读取，不对 Codex 加锁。

SQLite 元数据以所读取的行导出为 JSONL，再归档；不复制 Codex 数据库本身。JSON 导入账本同时保留原文件，`archive_chunk.generation=-g` 是该代的原始 JSON，正代是可按行寻址的导出。原始账本中未使用的顶层字段也保留。

Orbit 目录权限 `0700`，数据库、归档和导出文件 `0600`。L1 的解析缓存与 L2 的 `text/attrs/ext` 都递归脱敏，移除 creator 账号字段；内联媒体和加密推理只保留哈希引用。工具输出截断到约 8 KB，全文通过 L0 取回；普通消息不按工具输出预算截断。事件不再复制整条原生记录：`event.ext` 只存 `native_type`，未消费字段经 `event.record_uid` → `raw_record.body`（脱敏 L1）或 `readRedactedRecord` 取回，避免 staging 库体积翻倍。

不读取 `auth.json`、`.key`、`logs_*.sqlite`、Desktop 闭源数据库或配置凭据；不对 thread writer lock 加锁，不修改上游目录。连接器不执行日志里的代码或命令。

## 验证与边界

```sh
pnpm typecheck
pnpm test
pnpm build
```

35 项构造回归覆盖消息与工具双表示、缓存口径、单次/累计分离、空时间与时钟回退、guardian、子代理继承、同线程多 rollout、半行追加、改写/移动/压缩/删除、WAL 索引、隐私、维护锁、未知类型、漂移、监听降级、v1 迁移与 CLI。测试不包含真实会话内容。CI 对 Node 24、26 执行同一检查。

已对有界真实 Codex rollout 实际执行导入、重算、查询、重复导入、事件 Schema 校验和原文 SHA 对账；真实日志和结果仅保留在 `.local/`。授权本机验证可以限定范围，避免默认扫描全量正文：

```sh
pnpm tandem ingest --codex-home "$HOME/.codex" --data-dir .local/real-staging \
  --file 'archived_sessions/<真实 rollout 文件名>.jsonl' --no-index
```

`--file` 可重复，`--no-index` 排除索引、标题旁车与导入账本；`source_boundary` 保存本轮读取范围。范围只影响此次读取，已归档其他文件仍保留。查询须说明样本边界；排除账本的样本不能声称已完成全部导入关系核对。

当前边界：

- 成本没有接入价目表，`cost_usd=NULL`、`cost_source=unknown`。模型原名保留，尚未接入 models.dev 的跨供应商别名表。
- 旧版工具输出没有原生成功标志时状态为 `unknown`。精确审批来源和等待时长不推断；只把原生 `declined` 记为拒绝。
- 项目索引行已经归档；项目归属按 Git remote、仓库根与 cwd 推导，用户项目合并/拆分与 override 暂未实现。
- 单行上限 32 MiB，超限记录进入 `unparsed` 并保留 L0。文件变动检测采用头/尾检查点；对伪装成追加的任意中段改写不作完整前缀哈希扫描。
- 线程状态来自轮次是否闭合，不能证明对应进程仍存活。监听的 2 秒降级是扫描间隔，真实大库的回填时间与 5 秒可见目标尚未实测。
- 已验证有界真实历史样本；尚未做全量历史回填和计费对账。基础输入已落库，画像、推荐和前端算法不在本包。

分析补充字段状态：参数摘要来自完整可用的脱敏参数，截断、秘密或加密字段存在时摘要不可用；外层结果带 `status_scope=outer_script` 与观察到的已知/失败内层命令数，未知返回值数量保持 null。完整可见回复可计字符（Unicode code point、不计拼接分隔符）；摘要/文件正文边界和 `artifact_body_present` 未做语义判定，保持 null。澄清问答的结构化 answer 尚未单独抽取。精确审批等待、逐请求延迟、安装清单、Catalog、模型别名和项目 override 明确未接入。

## 依据

- [数据获取与标准化方案（固定于 0f6477c）](https://github.com/ActionMesh-AI/Hackathon/blob/0f6477c/docs/plan/data-acquisition.md)：第 3.2、3.3、4、7、8 节。
- [Codex 会话与轨迹调研（固定于 0f6477c）](https://github.com/ActionMesh-AI/Hackathon/blob/0f6477c/docs/research/agent-sessions/codex.md)：第 3、5、9 节。
- [OpenAI 官方配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)：本地配置与存储选项。
- [上游 TurnItem 定义（固定于 cb6da58）](https://github.com/openai/codex/blob/cb6da58876afed3ede0ab11084f67dd5394ecb48/codex-rs/protocol/src/items.rs)、[用量定义](https://github.com/openai/codex/blob/cb6da58876afed3ede0ab11084f67dd5394ecb48/codex-rs/protocol/src/protocol.rs)。
- [Node zlib](https://nodejs.org/api/zlib.html)、[RFC 8878](https://www.rfc-editor.org/rfc/rfc8878)：zstd 流与帧边界。实现逐帧流式解码，覆盖本机 Node 默认只读第一帧的行为。

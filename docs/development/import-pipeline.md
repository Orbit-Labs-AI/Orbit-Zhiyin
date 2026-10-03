# 导入流程：根因、状态机、阶段说明与排障

状态：现行 · 适用：`packages/backend/src/orbit_backend/services`（jobs、supervisor、worker_ingest、gateway、routes_data）、`packages/data/src/orbit_data`（service、scheduler、pipeline、indexing、query）、Advance UI 导入进度 · 维护者 `yhyfhgs` · 核对版本：Orbit v0.0.2 现场 + `fix/app-deep-debug`（2026-10-03）

本文回答三件事：Orbit 一次导入从 onboarding 提交到页面可读经过哪些阶段、每个数字是什么意思；v0.0.2 上「反复 prepare / project / map」「projection_pending 不消失」「0 个会话」的根因；遇到导入问题时怎么查。

## 1. 根因（v0.0.2 现场诊断）

### 1.1 现场与取证方式

用户正在运行已安装的 Orbit v0.0.2（gateway、ingest worker 及其 8 个映射子进程、analysis worker）。数据目录 `~/Library/Application Support/Orbit` 只读取证：读 `app-state.json`（任务日志）、`logs/*.log`、`maintenance.json`，用 `sqlite3 'file:…?mode=ro'` 做短查询，并以只读方式每秒轮询任务进度；未写入、未 checkpoint、未结束任何进程。

| 现场 | 数值 |
| --- | --- |
| `orbit.db` / `orbit.db-wal` | 7.1 GB / 5.8 GB（10:46）；两小时后 7.2 GB / 9.3 GB（12:47），WAL 只增不减 |
| `analysis.sqlite` | 3.8 GB |
| 遗留目录 | `import-1caqqqr8`（585 项、1.2 GB）；`import-w7d74_63` 是正在运行任务的溢出目录 |
| 首次导入（origin=user，phase=auto） | 08:57:48 → 09:37:43，共 2395 s |
| 之后的任务 | 09:57–10:09 连续 5 个 origin=sync、phase=full 的导入，各 137–156 s，首尾相接；10:10:55 ingest worker 被终止，任务记为 interrupted；10:23 重启后的 sync 任务 30 分钟后仍在运行 |
| 概览页 | 「服务暂时不可用（projection_pending）· 显示上一屏数据，1 秒后重试」「数据投影尚未完成 · 重新计算」「0 个会话」 |

用源码网关在临时 `ORBIT_HOME` 上复现（第 7 节的探针，合成数据 med 档 + 一个 Codex 根目录 + 模拟 Agent 持续写入），8 分钟内：1 个首次导入后接着 22 个 sync 任务（中位 15 s 一个，首尾相接）；每个 sync 任务 4 个来源却触发 9 次重建尝试；469 次 `/v1/sessions` 读取里 465 次只能拿到「上一屏」缓存（`X-Orbit-Freshness: stale`），而 `/v1/status` 同时一直报 `projection: ready`；任务全部以 `partial` 结束。

### 1.2 根因

**RC-1 实时同步把整源导入首尾相接地排队。** `sync_mode=live` 时网关的 `_sync_loop` 只看上一个 sync 任务的结果：只要有文件变化（`changed>0`），间隔就重置为 2 s 并立即再提交一个 `import phase=full`。正在使用的 Agent（包括 Orbit 自己的工作流 agent）每一轮都会追加会话文件，于是每轮都「有变化」，任务一个接一个，ingest worker 持续 100% CPU，界面上 capture → prepare → map → derive 一遍遍出现。任务中断（例如退出 App 时 worker 先被终止）后，循环在 0.4 s 内又提交了新任务（现场 f5bdaa88）。

**RC-2 一个来源级问题让整个 `~/.claude` 失去增量投影。** `scheduler.closure()` 只要看到某来源有「来源级」L2/L3 问题（`file_id` 与 `record_uid` 都为空）就放弃会话闭包，改为整源重建。`reduce.derive` 恰好把 `unresolved_session_lineage`（父会话不存在）写成来源级问题，而且同一来源的所有此类会话共用一个 `issue_uid`。Claude Code 工作流的 `subagents/workflows/*/journal.jsonl` 没有 `sessionId`，被映射成父会话不存在的 `journal:journal`；父会话被 Claude Code 定期清理掉的子代理也是同样形态。结果是 `~/.claude` 每轮只变 3–11 个文件，却每次 `scope: source` 重建 1946 个文件、约 60 万条记录（136–155 s），并写出 GB 级 WAL。只读查询确认 `~/.claude`、`~/.claude-account2`、`~/.codex` 各有 1 条这样的问题。

**RC-3 源文件在导入途中变化 → 保留旧事实 → 一直「待投影」→ 每个来源步骤都重建 Codex（活锁）。** 捕获只记录行摘要（source reference），投影时重读活文件逐行校验。Codex 的 `state_5.sqlite` 持续被 Codex 写入（SQLite 行快照没有可比的 stat，每次扫描都重读），投影读到的行与捕获时不同 → `SourceUnavailable(changed)` → 整个重建回滚，再带着「保留该文件旧事实」完整重来一遍；发布时这个文件不写 `projected_revision`。此后同一任务里每个来源的 `import_source` 都查询全库「是否有未投影文件」，又一次对 Codex 整源重建（Codex 不支持会话闭包），而这期间 `state_5.sqlite` 又变了，永远追不上；保留中的文件在下一次捕获时还会因为 `source_unavailable` 问题被视为「已变化」再生成新修订。现场：只读查询显示唯一未投影的文件是 Codex `state_5.sqlite`（revision 2、无 `projected_revision`、有 `source_unavailable(changed)`）；进度轨迹 10:54:38 prepare 0→975、10:55:12 reset_projection（回滚重来）、10:57:55 prepare 0→975、10:58:52 map，一轮 8–10 分钟。被保留文件的新行版本始终是 unparsed，任务因此全部记为 `partial`。继续只读观察：重启后的 sync 任务 a25c10af 从 10:23:27 跑到 11:18:59（55.5 分钟，结果 partial），期间至少 4 次 Codex 整源重建；下一个 sync 任务 1 秒后开始，又立刻重建 Codex；11:30 开始的任务在第一个来源上「prepare → reset_projection（回滚）→ prepare」用了 20 分钟，到第二个来源又从 prepare 976 个 Codex 文件开始，12:48 才以 `partial` 结束（78 分钟，至少 4 次回滚重来）；之后的 sync 任务仍然首尾相接，前后间隔约 1 秒（RC-1）。

**RC-4 读侧把「L1 比已发布的 L2 新」当成错误。** 捕获按组提交，新 L1 修订立即可见；投影在之后另一个长事务里提交。`orbit_data.query.current_projection` 在 `source_revision` 行数 ≠ 最新 `projection_run.l1_revision_count` 时抛出 "Projection is pending"，网关所有读路由返回 503 `projection_pending`，analysis worker 也以 `projection_pending` 失败。实际上上一次发布的 L2/L3 是完整一致的快照，完全可以读。RC-1/RC-3 让「已捕获未发布」的窗口几乎覆盖全部时间，RC-3 的保留文件又让 `l1_revision_count` 永远追不上（现场 run 20：3137 vs 3139）。网关的 LastGood 只缓存同一个 URL 的上次响应，换筛选或 App 重启后就没有，UI 于是显示「0 个会话」、Agent 筛选只剩一项；onboarding 的 `_main_sessions` 遇到错误直接返回 0。与此同时 `/v1/status` 只看内存里的上次发布，一直报 `projection: ready`，状态与读取结果自相矛盾，用户也没有可执行的重试入口。

**RC-5 WAL 只增不减。** 一次整源重建在一个写事务里删除并重写数十万事件，单个事务就写出 GB 级 WAL；写连接没有设置 `journal_size_limit`，SQLite 在检查点重置 WAL 后不会截断文件。唯一的 `wal_checkpoint(TRUNCATE)` 在后台维护里、且只在 VACUUM 之后执行；实时同步下一个任务 2 s 内就到，新写入者每次都打断后台维护（`maintenance.json` 停在 09:23）。分析 worker 的长读事务还会让被动检查点停在半途。

**RC-6 worker 被终止后遗留 `import-*` 溢出目录。** 进程池的溢出目录由 `WorkerPool.spill_dir()` 在数据目录下 `mkdtemp`，只在 `close()` 时删除。10:10:55 ingest worker 被终止（`logs/ingest.log` 只有 resource_tracker 的信号量泄漏警告，没有 traceback），`close()` 没有执行，留下 1.2 GB 的 `import-1caqqqr8`。

**RC-7 首次导入重复整源重建。** worker 的 phase=auto 计划把会话按 head / window / rest 分批，rest 再按 200 个文件切块（为了能在块之间暂停）。对不支持会话闭包的 Codex，每一批都是整源重建：现场 974 个文件分 4 批，累计映射 2549 个文件次；`~/.claude` 因 RC-2 也是 head、window 各整源重建一次。首次导入因此用了 40 分钟。

**RC-8 阶段和数字没有说明。** 进度帧只有内部阶段名和 `completed/total`，没有单位、来源序号、批次和重试次数；一个任务里每个来源都会从 capture 走到 published，再加上 RC-3 的回滚重来，看上去就是「反复 prepare、project、map」。UI 直接把 `map`、`reset_projection` 这样的内部名显示给用户。设置页「立即重新索引」发送不带 `source_ids` 的导入请求，网关以 422「Select at least one enabled source」拒绝，重试入口本身也是坏的。

**RC-9 会话闭包遇到「属于闭包外已有会话的新文件」时整次导入失败。** 闭包在计算时还不知道全新文件的记录属于哪个会话（尚未映射）。如果新文件属于闭包外的已有会话——之后才写出的会话标题 `custom-title.json`、又一个工作流 `journal.jsonl`（RC-2 所说，全部映射进同一个会话）——它的事件按闭包内从 0 重新编号插入，与该会话保留的事件撞号，`UNIQUE constraint failed: event.session_uid, event.seq`，整次导入失败；该来源一直待发布，之后每次扫描都失败，其他来源的步骤也会在「顺带发布」时失败。v0.0.2 上 `~/.claude` 因 RC-2 一直整源重建才没暴露；修好 RC-2 后用真实来源副本复现到：首次导入的 window 批与之后每个 sync 任务的两个来源全部报错。没有孤儿会话的用户在 v0.0.2 上重命名一个 Claude Code 会话就会碰到。

### 1.3 修复对照

| 根因 | 修复 | 回归测试 |
| --- | --- | --- |
| RC-1 | `gateway.sync_wait`：上一次 sync 导入结束后至少再等它用掉的时间（导入最多占一半时间）；无变化时 2 s → 30 s 退避；失败、中断、取消后等 30 s；网关关闭途中不再提交 | `test_import_pipeline.py::test_sync_wait_never_runs_sync_imports_back_to_back`、`::test_sync_loop_waits_as_long_as_the_last_sync_import_took` |
| RC-2 | `reduce.derive` 把 `unresolved_session_lineage` 挂在声明父会话的记录上；闭包重建会删除并重算它，结果与整源重建一致 | `test_incremental_projection.py::test_orphan_subagent_keeps_session_closures` |
| RC-3 | 保留的修订记为 settled（`retained_revision`/`retained_versions`），在新捕获之前不算 stale、不算 pending；已知 settled 文件从第一次尝试就保留；活 SQLite 索引按捕获时的行投影（内存，≤64 MiB） | `test_import_freshness.py` 三项 |
| RC-4 | `query.projection_state` 区分 ready / pending / 不可读；L2/L3 读者读已发布快照并标 `X-Orbit-Freshness: stale` + `X-Orbit-Projection: pending`；`/v1/status.projection` 反映真实新鲜度，`projection_info` 给出待发布文件数、`stuck` 与重试请求 | `test_import_pipeline.py::test_pending_capture_serves_the_published_snapshot`，`test_query_indexes.py`、`test_native_connectors.py`、`test_edges.py` 相应断言 |
| RC-5 | 写连接 `journal_size_limit = 64 MiB`；每个任务结束时 `wal_checkpoint(TRUNCATE)`（读者占用时最多等 2 s） | `test_import_pipeline.py::test_import_progress_explains_itself_and_never_moves_backwards`（`wal`） |
| RC-6 | 溢出目录名带属主 pid；ingest worker 启动时删除属主已退出的目录，持有导入锁时也删除 v0.0.2 旧名目录 | `test_import_pipeline.py::test_worker_start_removes_spill_directories_of_killed_imports` |
| RC-7 | 不支持会话闭包的来源（Codex 等）首次导入保留 head、window，rest 合成一批 | `test_import_pipeline.py::test_import_progress_explains_itself_and_never_moves_backwards` |
| RC-8 | 阶段目录 `orbit_data.progress.STAGES`；进度帧增加 `label`/`unit`/`detail`/`step`/`steps`/`batch`/`attempt`/`overall` 等；UI 按 `detail` 显示、进度条按 `overall` 走；`import` 不带 `source_ids` 时导入全部已启用来源 | 同上，及 `::test_import_without_sources_reindexes_every_enabled_source`、UI 测试 |
| RC-9 | `pipeline.ClosureSequences`：闭包重建里第一次给闭包外、已有事件的会话编号时扩大闭包重试（至多 4 次，之后整源） | `test_incremental_projection.py::test_new_file_of_a_session_outside_the_closure_escalates`（标题 sidecar、新 journal 两种） |
| 卡住 | 导入 15 分钟没有任何进度帧即停止并记为 `interrupted(job_stalled)`，可重试 | `test_import_pipeline.py::test_stalled_import_is_stopped_with_a_retryable_error` |

## 2. 一次导入从提交到可读

```text
引导「开始分析」/ 设置「立即重新索引」/ 实时同步
  POST /v1/app/sources（启用来源） → POST /v1/app/jobs {kind:"import", source_ids?}
    JobService.submit → AppState.create_job：queued（app-state.json 立即落盘）
    IngestRunner.start → ingest worker（stdin JSON Lines {"op":"run"}）
      started → running
      对第 i/n 个来源：
        计划批次（phase=auto）：head（最新 50 个会话及 7 天内）→ window（30 天内）→ rest（更早）
          不支持会话闭包的来源 rest 合成一批；phase=full 时是一批 full；recent_days 之前的文件不导入
        对第 b/m 批：ImportService.import_source
          capture          读取文件、写 L1 修订（按组提交）
          normalize        有待发布的文件时进入投影
          scheduler.project：对每个有待发布文件的来源
            会话闭包可用 → scope=closure，否则 scope=source（整个来源）
            reset_projection → prepare → map → derive_* → validate_projection → published
            （源文件在导入途中变化：回滚，带 attempt+1 保留该文件上次的事实重来）
          published 帧（data_rev、counts、freshness） → 网关 Revisions → SSE data.published
            → 30 s 防抖后预热分析快照
      done：completed | partial；异常 failed；取消 cancelled
      worker 退出 / 卡住 15 分钟 / App 重启：interrupted（worker_exited / job_stalled / app_restarted）
    网关：任务结束后重读新鲜度；sync_mode=live 时 _sync_loop 用 sync_wait 安排下一次 origin=sync 的导入
  analysis worker：按 (section, scope, data_rev, …) 计算快照；读已发布快照，pending 时照常计算
  UI：job 帧驱动引导页「导入历史会话」与侧栏入口；页面读 /v1/sessions 等（stale 时显示「更新于 …」）
```

任务状态只单向推进：`queued → running → completed | partial | failed | cancelled | interrupted`，结束后不再变化；重试（`POST /v1/app/jobs/{id}/retry`）以相同来源、文件选择与 phase 新建一个任务（`origin=retry`），不扩大范围。`partial` 表示数据已发布但有需要注意的地方：捕获错误、未解析记录、被保留的文件或某个来源出错，逐项见 `results[]`。一个任务里每个来源、每一批都会完整走一遍 capture → published，这是分批发布，不是重来；真正的重来只有 `attempt>1`。

## 3. 阶段与数字

阶段目录在 `packages/data/src/orbit_data/progress.py`（`STAGES`），worker 把它补进每个进度帧。

| 内部名 | 中文名 | 这一步做什么 | completed / total | 主要耗时因素 |
| --- | --- | --- | --- | --- |
| `capture` | 读取会话文件 | 逐个读取本批允许导入的文件，记录每行位置与摘要（不复制会话内容）；stat 未变的文件直接跳过；SQLite 索引每次都读 | 本批文件数（个文件） | 新增字节数；首次导入读全部文件 |
| `normalize` | 准备发布 | 本批读完且有待发布文件，开始投影 | — | — |
| `reset_projection` | 开始重建 | 清掉重建范围（会话闭包或整个来源）里的旧会话事实 | —；`attempt` 第几次尝试，`retained` 保留的文件数 | 范围内事件数：整源删除几十万事件要几分钟 |
| `prepare` | 预读会话文件 | 每个文件映射前预读一遍（会话头、子代理、用量去重） | 重建范围内文件数 | 文件数与大小 |
| `map` | 解析会话记录 | 把原生记录映射成统一事件；`records` 是已映射记录条数 | 重建范围内文件数 | 记录数；Claude Code / pi / DSH 多进程并行，Codex / OpenCode / Hermes 在写入进程里单线程 |
| `derive_metadata` | 汇总会话信息 | 每个会话的标题、目录、父会话 | 会话数（个会话） | 会话数 |
| `derive_projects` | 归属项目 | 按工作目录与 Git 信息归到项目 | 会话数 | 会话数 |
| `derive_sessions` | 统计轮次与工具 | 逐个会话推导轮次、工具调用、耗时与用量 | 会话数 | 事件数 |
| `validate_projection` | 校验 | 外键与「记录—事件」对应关系 | — | 重建行数 |
| `published` | 已发布 | 一次原子提交，新的 `data_rev` 对页面可见 | 重建范围内文件数 | 提交大小 |

进度帧字段（`job` 事件的 `progress`，`GET /v1/app/jobs/{id}` 同样返回）：

| 字段 | 含义 |
| --- | --- |
| `stage`、`completed`、`total`、`records`、`agent` | 原有字段，含义不变 |
| `label` | 中文阶段名 |
| `unit` | `completed/total` 的单位：`files` / `sessions` / `batches`；无计数时为 `null` |
| `detail` | 一行说明：来源与序号、批次、重建范围、第几次尝试；map 阶段附已解析的记录条数。计数本身看 `completed/total` 与 `unit`（UI 显示为「419 / 975 个文件」） |
| `step` / `steps` | 第几个来源 / 本任务来源数 |
| `source_id` / `source_agent` | 正在导入的来源 |
| `batch` / `batches` / `batch_phase` | 来源内第几批 / 批数 / `head`·`window`·`rest`·`full`·`selection` |
| `projecting`、`source_index`、`sources`、`files_stale` | 正在重建哪个来源（可能是之前中断留下待发布文件的其他来源）、第几个、共几个、待发布文件数 |
| `scope` | `closure`：只重建受影响的会话；`source`：重建整个来源 |
| `attempt`、`retry_reason`、`retained` | 重建尝试次数；`attempt>1` 表示源文件在导入途中变化，已回滚并保留其上次的事实 |
| `overall` | 整个任务的估计进度（0–1），按来源、批次与阶段权重估算，同一任务内只增不减 |
| `origin`（帧顶层） | `user` / `retry` / `sync`；UI 把 `sync` 写作「后台同步」，侧栏导入入口和引导页只跟随用户发起的导入 |

UI 读这些字段：引导页「导入历史会话」下的说明行是「中文阶段名 · detail」，右侧是「completed / total + 单位」，进度条用 `overall`；页面顶部进度条同样；`partial` 记为已导入并注明原因（少量记录未能解析或暂时保留了上一版本），不再显示「导入没有完成」。

## 4. 新鲜度与读取

| 状态 | 含义 | 读取 |
| --- | --- | --- |
| `absent` | 还没有任何发布（首次导入未完成） | 列表返回空结构（`X-Orbit-Freshness: none`）；首次发布前 503 `projection_pending` |
| `ready` | 每个已捕获修订都已发布 | `fresh` |
| `pending` | 有文件已捕获、尚未发布（导入在捕获与发布之间，或曾被中断） | 已发布快照照常读取：`X-Orbit-Freshness: stale`、`X-Orbit-Projection: pending`；分析照常计算（快照键用已发布的 `data_rev`） |
| retained（settled） | 文件在投影时又变了，保留其上次的事实，带 `source_unavailable` 问题 | 视为已计入；下一次捕获出新修订时重新投影 |
| `invalid` | mapper / reducer / redaction 版本过期或结构不符 | 409 `rebuild_required`，下一次导入会重建 |

`/v1/status` 的 `projection` 取上表状态，`projection_info` 补充 `pending_files`、`retained_files`、`pending_since`；`pending` 或 `invalid` 持续 60 s 以上且没有导入在跑时 `stuck: true`，并给出 `retry: {"method":"POST","path":"/v1/app/jobs","body":{"kind":"import"}}`（不带 `source_ids` 即导入全部已启用来源）。严格读者（`current_projection`：CLI 导出、轨迹分页）仍拒绝 pending，保证分页固定在一次发布上。

## 5. 实时同步节奏

`sync_mode` 为 `live` 时网关每轮检查一次（有任务在跑就 2 s 后再看），下一次 `origin=sync`、`phase=full` 的导入在上一次 sync 导入结束后按 `sync_wait` 等待：

| 上一次 sync 导入 | 再等多久 |
| --- | --- |
| 有文件变化 | max(2 s, 它用掉的时间) |
| 没有变化 | max(当前空闲间隔, 它用掉的时间)；空闲间隔 2 s 起每次无变化翻倍，最多 30 s |
| 失败 / 中断 / 取消 | max(30 s, 它用掉的时间) |
| `hour` 模式 | 距上次结束满 1 小时 |

所以持续同步时导入最多占一半时间；采集暂停时不同步，恢复后立刻补一次；网关关闭途中不提交。

## 6. 存储维护

- WAL：写连接设置 `journal_size_limit = 64 MiB`，每次 WAL 重置都截断到这个大小；每个导入任务结束时执行 `wal_checkpoint(TRUNCATE)`，有读者占用旧快照时最多等 2 s，返回 busy 就留给下一次（结果在 `done` 帧的 `wal`）。后台维护（`maintenance.json`）在空闲时做 VACUUM / incremental_vacuum。
- 溢出目录：映射子进程把大结果写到 `<home>/import-<pid>-*`，任务结束删除；进程被杀留下的目录在下一次 ingest worker 启动时删除。
- 活 SQLite 索引（Codex `state_*.sqlite` 等）捕获时的行在内存里保留到同一次导入投影完，每个导入至多 64 MiB，不落盘。

## 7. 排障指南

1. **任务在做什么**：`GET /v1/app/jobs`（或只读查看 `app-state.json` 的 `jobs`）。看 `origin`（user / sync / retry）、`status`、`progress.detail`、`results[].projection.scope.kind`（closure / source）、`error.code`（`worker_exited`、`job_stalled`、`app_restarted`、`service_unavailable`）。同一来源每次都是 `scope: source` 时查第 3 步。
2. **页面显示旧数据**：`GET /v1/status` 的 `projection_info`。`pending` 且有导入在跑属正常；`stuck` 时点重试或 `POST /v1/app/jobs {"kind":"import"}`。
3. **只读查询**（Orbit 运行时也安全，不要对库做写入或 checkpoint）：

   ```sh
   DB="$HOME/Library/Application Support/Orbit/orbit.db"
   # 待发布与被保留的文件
   sqlite3 "file:$DB?mode=ro" "SELECT source_id, relative_path, json_extract(watermark,'\$.revision'), json_extract(watermark,'\$.projected_revision'), json_extract(watermark,'\$.retained_revision') FROM source_file WHERE COALESCE(json_extract(watermark,'\$.projected_revision'),-1) <> COALESCE(json_extract(watermark,'\$.revision'),0)"
   # 会让会话闭包失效的来源级问题
   sqlite3 "file:$DB?mode=ro" "SELECT source_id, code, count(*) FROM ingest_issue WHERE stage IN ('l2','l3') AND file_id IS NULL AND record_uid IS NULL GROUP BY 1,2"
   # 最近几次发布
   sqlite3 "file:$DB?mode=ro" "SELECT run_id, datetime(completed_at/1000,'unixepoch','localtime'), event_count, l1_revision_count FROM projection_run ORDER BY run_id DESC LIMIT 5"
   ```

4. **WAL 很大**：Orbit 运行时不要删 `-wal` / `-shm`。任务结束的 checkpoint 或下一次 WAL 重置会把它截回 64 MiB 以内；长时间不缩小说明有读者一直持有旧快照（看 analysis worker 是否在跑长任务）。
5. **`import-*` 目录**：下一次 ingest worker 启动时自动删除；Orbit 未运行时可手动删除。
6. **复现**：`uv run python -m benchmarks.data.live_sync --preset med --minutes 8 --work <目录>` 在临时 `ORBIT_HOME` 上起源码网关，导入合成来源（Claude Code / pi / DSH、带 `state_5.sqlite` 的 Codex 目录、一个父会话缺失的子代理），开 `sync_mode=live`，一边持续追加 Claude 会话、更新 Codex `threads` 行，一边每秒读 `/v1/sessions` 与 `/v1/status`，输出每个任务的重建尝试次数、重建范围、耗时、读取结果、WAL 与遗留溢出目录。基准只用构造数据；要看真实来源，在 `.work/appfix-tmp/` 下 `mktemp -d`，只用 `cp -c` 复制允许导入的会话文件（不含 `auth.json`、`.credentials*` 等凭据），再按同样步骤手动启动网关。

## 8. 修复前后对比

合成数据（`benchmarks.data.live_sync` 同一场景：med 档 Claude Code / pi / DSH 各 300 个会话、300 个 Codex 会话与 `state_5.sqlite`、一个孤儿子代理；`sync_mode=live`，Claude 每 2 s 追加一行、Codex 每 1 s 改一行 `threads`；8 分钟；修复前 = v0.0.2 代码，修复后 = 本分支）：

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| 首次导入 | 12.3 s，`partial`，5 次重建尝试（Codex 回滚重来 1 次） | 26.4 s（同时段机器负载高；不经网关直接计时两轮：修复前 21.9 / 22.5 s，修复后 21.4 / 22.8 s），`completed`，4 次尝试、无回滚 |
| 8 分钟内 sync 任务 | 22 个，中位 15.2 s，每个 9 次重建尝试（每个来源步骤都重建 Codex，`~/.claude` 整源） | 67 个，中位 2.7 s，每个 2 次（Claude 只重建受影响的 1 个文件，Codex 整源 1 次） |
| ingest worker 忙碌占比 | 95%（前后任务间隔中位 1.1 s） | 50%（间隔中位 2.7 s，等于上一任务耗时） |
| `partial` 任务 | 23 / 23 | 0 / 68 |
| `/v1/sessions` 每秒读取 | 469 次中 465 次只能拿到同一 URL 的缓存（换 URL 即 503），2 次 503 | 466 次中 459 次 200（其中 200 次是待发布期间的已发布快照，标 stale），7 次 503 都在首次发布之前 |
| `/v1/status.projection` | 读取失败时仍报 `ready` | 与读取一致；首次发布前 `absent` |
| WAL（最大 / 结束） | 174.6 / 174.4 MB | 156.2 / 0 MB |
| 遗留 `import-*` | 无（未杀进程） | 无；被杀进程的目录在下次启动时删除（回归测试覆盖） |

真实来源副本（`cp -c` 克隆，不含凭据：`~/.claude` 4 个项目目录的 451 个允许导入文件 512 MB，`~/.codex` 近 5 天的 rollout、`session_index.jsonl`、`state_5.sqlite` 共 108 个文件 255 MB；同样的持续写入，14 分钟；两次运行与测试并行，耗时只作量级参考）：

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| 首次导入 | 108 s，`partial`：Codex `state_5.sqlite` 被保留、1174 条行记录未解析；`~/.claude` 的 head、window 两批都整源重建 | `completed`：window 批只重建受影响的会话，Codex 无保留文件（与测试并行，245 s）。不经网关、无写入时直接计时：修复前 83.6 s，修复后 78.3 s |
| sync 任务 | 113 / 164 / 354 s，第 4 个到结束仍在跑；全部 `partial`；每个 5 次重建尝试；前后间隔 0.8 s | 6 个，37–55 s，全部 `completed`；每个 2 次（Claude 闭包 + Codex 整源）；间隔等于上一任务耗时 |
| WAL（结束） | 899 MB | 0 MB（导入中最大 1.2 GB，任务结束截断） |
| 停网关后的 `import-*` | 留下 1 个 | 无 |
| 修复中途发现 | — | 修好 RC-2 后 `~/.claude` 走闭包，首次运行即复现 RC-9（window 批与之后每个 sync 都 IntegrityError），修复后即上表 |

## 9. 已知限制

- Codex、OpenCode、Hermes 不支持会话闭包，映射也在写入进程里单线程；它们的任何文件变化都会让整个来源重建。现场 975 个 Codex 文件一次约 6–10 分钟。修复后不再重复、不再回滚重来，实时同步也按耗时退避，但 Codex 正在使用时每一轮同步仍要整源重建一次。根治需要 Codex 的会话闭包（`state_5.sqlite` 是一张涵盖全部线程的表，需要按记录而不是按文件划定闭包）或按文件并行映射。
- Claude Code 工作流的 `journal.jsonl` 没有 `sessionId`，现有映射把同一来源的所有工作流 journal 合成一个父会话不存在的 `journal:journal` 会话。修复后它不再关闭会话闭包，但这个合成会话本身仍不准确；改正需要升级 mapper 版本（会触发一次全量重建）。
- 一个正在运行、带几百个子代理的 Claude Code 会话，任何一个子代理文件变化都会让整棵会话树（主会话及全部子代理文件）进入闭包重建。

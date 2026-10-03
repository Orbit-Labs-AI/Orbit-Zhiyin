# 导入流程：根因、状态机、阶段说明与排障

状态：现行 · 适用：`packages/backend/src/tandem_backend/services`（jobs、supervisor、worker_ingest、gateway、routes_data）、`packages/data/src/tandem_data`（service、scheduler、pipeline、indexing、query）、Advance UI 导入进度 · 维护者 `yhyfhgs` · 核对版本：Orbit v0.0.2 现场 + `fix/app-deep-debug`（2026-10-03）

本文回答三件事：Orbit 一次导入从 onboarding 提交到页面可读经过哪些阶段、每个数字是什么意思；v0.0.2 上「反复 prepare / project / map」「projection_pending 不消失」「0 个会话」的根因；遇到导入问题时怎么查。

## 1. 根因（v0.0.2 现场诊断）

### 1.1 现场与取证方式

用户正在运行已安装的 Orbit v0.0.2（gateway、ingest worker 及其 8 个映射子进程、analysis worker）。数据目录 `~/Library/Application Support/Tandem` 只读取证：读 `app-state.json`（任务日志）、`logs/*.log`、`maintenance.json`，用 `sqlite3 'file:…?mode=ro'` 做短查询，并以只读方式每秒轮询任务进度；未写入、未 checkpoint、未结束任何进程。

| 现场 | 数值 |
| --- | --- |
| `tandem.db` / `tandem.db-wal` | 7.1 GB / 5.8 GB（WAL 始终不收缩） |
| `analysis.sqlite` | 3.8 GB |
| 遗留目录 | `import-1caqqqr8`（585 项、1.2 GB）；`import-w7d74_63` 是正在运行任务的溢出目录 |
| 首次导入（origin=user，phase=auto） | 08:57:48 → 09:37:43，共 2395 s |
| 之后的任务 | 09:57–10:09 连续 5 个 origin=sync、phase=full 的导入，各 137–156 s，首尾相接；10:10:55 ingest worker 被终止，任务记为 interrupted；10:23 重启后的 sync 任务 30 分钟后仍在运行 |
| 概览页 | 「服务暂时不可用（projection_pending）· 显示上一屏数据，1 秒后重试」「数据投影尚未完成 · 重新计算」「0 个会话」 |

用源码网关在临时 `TANDEM_HOME` 上复现（第 7 节的探针，合成数据 med 档 + 一个 Codex 根目录 + 模拟 Agent 持续写入），8 分钟内：1 个首次导入后接着 22 个 sync 任务（中位 15 s 一个，首尾相接）；每个 sync 任务 4 个来源却触发 9 次重建尝试；469 次 `/v1/sessions` 读取里 465 次只能拿到「上一屏」缓存（`X-Tandem-Freshness: stale`），而 `/v1/status` 同时一直报 `projection: ready`；任务全部以 `partial` 结束。

### 1.2 根因

**RC-1 实时同步把整源导入首尾相接地排队。** `sync_mode=live` 时网关的 `_sync_loop` 只看上一个 sync 任务的结果：只要有文件变化（`changed>0`），间隔就重置为 2 s 并立即再提交一个 `import phase=full`。正在使用的 Agent（包括 Orbit 自己的工作流 agent）每一轮都会追加会话文件，于是每轮都「有变化」，任务一个接一个，ingest worker 持续 100% CPU，界面上 capture → prepare → map → derive 一遍遍出现。任务中断（例如退出 App 时 worker 先被终止）后，循环在 0.4 s 内又提交了新任务（现场 f5bdaa88）。

**RC-2 一个来源级问题让整个 `~/.claude` 失去增量投影。** `scheduler.closure()` 只要看到某来源有「来源级」L2/L3 问题（`file_id` 与 `record_uid` 都为空）就放弃会话闭包，改为整源重建。`reduce.derive` 恰好把 `unresolved_session_lineage`（父会话不存在）写成来源级问题，而且同一来源的所有此类会话共用一个 `issue_uid`。Claude Code 工作流的 `subagents/workflows/*/journal.jsonl` 没有 `sessionId`，被映射成父会话不存在的 `journal:journal`；父会话被 Claude Code 定期清理掉的子代理也是同样形态。结果是 `~/.claude` 每轮只变 3–11 个文件，却每次 `scope: source` 重建 1946 个文件、约 60 万条记录（136–155 s），并写出 GB 级 WAL。只读查询确认 `~/.claude`、`~/.claude-account2`、`~/.codex` 各有 1 条这样的问题。

**RC-3 源文件在导入途中变化 → 保留旧事实 → 一直「待投影」→ 每个来源步骤都重建 Codex（活锁）。** 捕获只记录行摘要（source reference），投影时重读活文件逐行校验。Codex 的 `state_5.sqlite` 持续被 Codex 写入（SQLite 行快照没有可比的 stat，每次扫描都重读），投影读到的行与捕获时不同 → `SourceUnavailable(changed)` → 整个重建回滚，再带着「保留该文件旧事实」完整重来一遍；发布时这个文件不写 `projected_revision`。此后同一任务里每个来源的 `import_source` 都查询全库「是否有未投影文件」，又一次对 Codex 整源重建（Codex 不支持会话闭包），而这期间 `state_5.sqlite` 又变了，永远追不上；保留中的文件在下一次捕获时还会因为 `source_unavailable` 问题被视为「已变化」再生成新修订。现场：只读查询显示唯一未投影的文件是 Codex `state_5.sqlite`（revision 2、无 `projected_revision`、有 `source_unavailable(changed)`）；进度轨迹 10:54:38 prepare 0→975、10:55:12 reset_projection（回滚重来）、10:57:55 prepare 0→975、10:58:52 map，一轮 8–10 分钟。被保留文件的新行版本始终是 unparsed，任务因此全部记为 `partial`。

**RC-4 读侧把「L1 比已发布的 L2 新」当成错误。** 捕获按组提交，新 L1 修订立即可见；投影在之后另一个长事务里提交。`tandem_data.query.current_projection` 在 `source_revision` 行数 ≠ 最新 `projection_run.l1_revision_count` 时抛出 "Projection is pending"，网关所有读路由返回 503 `projection_pending`，analysis worker 也以 `projection_pending` 失败。实际上上一次发布的 L2/L3 是完整一致的快照，完全可以读。RC-1/RC-3 让「已捕获未发布」的窗口几乎覆盖全部时间，RC-3 的保留文件又让 `l1_revision_count` 永远追不上（现场 run 20：3137 vs 3139）。网关的 LastGood 只缓存同一个 URL 的上次响应，换筛选或 App 重启后就没有，UI 于是显示「0 个会话」、Agent 筛选只剩一项；onboarding 的 `_main_sessions` 遇到错误直接返回 0。与此同时 `/v1/status` 只看内存里的上次发布，一直报 `projection: ready`，状态与读取结果自相矛盾，用户也没有可执行的重试入口。

**RC-5 WAL 只增不减。** 一次整源重建在一个写事务里删除并重写数十万事件，单个事务就写出 GB 级 WAL；写连接没有设置 `journal_size_limit`，SQLite 在检查点重置 WAL 后不会截断文件。唯一的 `wal_checkpoint(TRUNCATE)` 在后台维护里、且只在 VACUUM 之后执行；实时同步下一个任务 2 s 内就到，新写入者每次都打断后台维护（`maintenance.json` 停在 09:23）。分析 worker 的长读事务还会让被动检查点停在半途。

**RC-6 worker 被终止后遗留 `import-*` 溢出目录。** 进程池的溢出目录由 `WorkerPool.spill_dir()` 在数据目录下 `mkdtemp`，只在 `close()` 时删除。10:10:55 ingest worker 被终止（`logs/ingest.log` 只有 resource_tracker 的信号量泄漏警告，没有 traceback），`close()` 没有执行，留下 1.2 GB 的 `import-1caqqqr8`。

**RC-7 首次导入重复整源重建。** worker 的 phase=auto 计划把会话按 head / window / rest 分批，rest 再按 200 个文件切块（为了能在块之间暂停）。对不支持会话闭包的 Codex，每一批都是整源重建：现场 974 个文件分 4 批，累计映射 2549 个文件次；`~/.claude` 因 RC-2 也是 head、window 各整源重建一次。首次导入因此用了 40 分钟。

**RC-8 阶段和数字没有说明。** 进度帧只有内部阶段名和 `completed/total`，没有单位、来源序号、批次和重试次数；一个任务里每个来源都会从 capture 走到 published，再加上 RC-3 的回滚重来，看上去就是「反复 prepare、project、map」。UI 直接把 `map`、`reset_projection` 这样的内部名显示给用户。设置页「立即重新索引」发送不带 `source_ids` 的导入请求，网关以 422「Select at least one enabled source」拒绝，重试入口本身也是坏的。

### 1.3 修复对照

| 根因 | 修复 | 回归测试 |
| --- | --- | --- |
| RC-1 | 进行中 | 进行中 |
| RC-2 | 进行中 | 进行中 |
| RC-3 | 进行中 | 进行中 |
| RC-4 | 进行中 | 进行中 |
| RC-5 | 进行中 | 进行中 |
| RC-6 | 进行中 | 进行中 |
| RC-7 | 进行中 | 进行中 |
| RC-8 | 进行中 | 进行中 |

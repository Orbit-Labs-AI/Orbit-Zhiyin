# 存储去重、查询索引与 PRAGMA（存储 v8）

存储迁移 `008` 只改变物理存储形式和索引，事件契约仍为 v1，`event_page` / `trajectory_page` 的输出与改动前逐字节一致。背景与基线数字见 `docs/plans/data-audit.md` §3.5–§3.6、§5.4–§5.5。

## 迁移阶梯

- `007` 预留给 `feat/data-app-integration` 的外键反向索引。`008` 用 `CREATE INDEX IF NOT EXISTS` 以相同名称重复声明这些索引，所以两边合并先后不影响结果。
- `Store` 对 `007` 及以后的迁移按“文件存在且库版本较低就执行”处理：v6 库（有或没有 FK 索引）、v7 库都直接升级到 v8；v8 库重新打开不会再执行。
- `008.sql` 可以重复执行，用于版本号被回拨的库。
- `SCHEMA_VERSION=8`，`MAPPER_VERSION` 不变：已有库升级后旧事件仍以内联形式保存并可正常读取，不会被迫重算。

## ext 大字符串的内容寻址存储（`payload.py`）

- 写入：`store.insert` 和新增的 `store.insert_rows`（executemany）对 `event.ext` 做外置。UTF-8 不少于 4 KiB 的字符串写入 `content_blob(sha256 PK, codec='zstd', raw_len, data, refs)`，原位置改为 `{"$blob": sha256, "len": 字符数}`。相同内容只存一份。
- 读取：`query.event_page`、`store.verify`、CLI 导出和缺失来源保留（`retained.py`）都会先还原再使用。
- 转义：原生数据里如果有形似引用的字典，或恰好只有一个 `$lit` 键的字典，会存为 `{"$lit": {...}}`，读取时原样还原。
- 引用计数：`event` 上的触发器维护 `refs`。重算结束后，`Store.optimize()` 删除 `refs=0` 的 blob；`verify()` 会重算全部引用，并校验每个 blob 的摘要和长度。出现悬空引用或计数不一致时，`verify()` 失败。
- `event.text` 保持内联，因为检索和分析都直接读取它。
- 已知限制：pipeline 合并重复事件时，会把旧的已存储 `ext` 与新的逻辑 `ext` 用 UPDATE 直接写回。若新增部分含有不少于 4 KiB 的字符串，就以内联形式保存（结果正确，只是没有压缩）。若新增部分含有形似引用的原生字典，就不会被转义；这要求原生日志恰好写出 `{"$blob": 64 位十六进制, "len": 整数}`，目前没有遇到。

## Claude Code 去重

`ext.envelope` 不再复制 `toolUseResult`。原值只在 `ext.toolUseResult` 中保存一份，非 dict 值也原样保留；该记录没有 `tool.result` 事件时，保存在第一个事件上。以前，40 KB 级工具输出在同一事件中要存三份：`text`、`ext.toolUseResult`、`ext.envelope.toolUseResult`。

## 检索索引

`event_fts` 及其触发器已删除；它对全部 `text` 建索引，包括工具输出。新的 `event_search` 是 FTS5 trigram 表（contentless、可删除），只索引 `message.user`、`message.assistant` 和 `session.title`。查询写法：

```sql
SELECT e.* FROM event_search s JOIN event e ON e.rowid = s.rowid
WHERE event_search MATCH '"修复第 2 个"' LIMIT 20;
```

trigram 要求关键词至少 3 个字符，更短的关键词仍用 `LIKE`。工具命令和文件名直接查 `tool_call` 的列。

## 索引

- 外键反向索引全套，名称为 `fk_<表>_<列>`。`test_query_indexes` 断言每个外键列都是某个索引的首列。
- `session(started_at)`、`session(project_id, started_at)`、`session(source_id, started_at)`、`tool_call(name, started_at)`、`raw_record(file_id, locator, version)`。
- `source_file_unprojected`（部分索引）和 `source_file_projection_versions`（表达式索引）。`current_projection` 用它们判断新鲜度，不再每次对 `source_file` 全表执行 `json_extract`。

## 查询

- `trajectory_page`：先物化会话相关的 `record_uid` 集合，再连表分页。集合由三路组成：会话记录、事件证据、同文件转录。以前用 `OR … IN`，会全表扫描 `raw_record`。
- `source_status(connection)`：按来源用索引统计会话数、文件数和最近扫描时间。
- `bridge.import_connector`：每个文件一次性读取记录对照表，用 executemany 写入链接。

## PRAGMA

- 写连接：`synchronous=NORMAL`、`temp_store=MEMORY`、`cache_size=-262144`、`mmap_size=1 GiB`。在 WAL 模式下，进程崩溃不会丢失已提交的事务；只有断电可能丢失最后几个事务，下次扫描会从源文件补回。
- 每次 `rebuild` 后：清理 blob、`PRAGMA optimize`、`wal_checkpoint(PASSIVE)`。
- 导入后维护见下节；`ImportService` 的导入路径（串行与并行）都不在导入计时内压实。

## 导入后维护（`Store.maintain` / `ImportService(maintenance=...)`）

- **触发**：`import_source` 产生新发布（结果含 `projection`）或 `import_progressive` 至少发布一批后，由导入结束钩子触发，发生在写锁释放之后，不计入导入耗时与首批可读时间。
  - `background`（默认，App ingest worker 使用）：独立连接的守护线程，先等 1 s 宽限期（按来源连续导入时下一次导入会在宽限期内取消它），再取写锁执行。新的写者（导入、verify、rebuild、inventory）先中断它并等待线程退出；被中断的 VACUUM 整体回滚，库保持原样，下一次导入结束再排入。
  - `wait`：在调用返回前同步执行，结果放在 `result["maintenance"]`（CLI `scan/ingest --maintenance` 默认 wait，`benchmarks/data/import_bench.py --maintenance wait` 单独计时）。
  - `off`：不维护。
- **判断**：先查 `freelist_count` 与 `dbstat` 的 `unused`。合成数据首导后空闲页为 0、页内空闲约 40%（small），膨胀全部来自碎片（bulkload 推迟建索引、随机 uid 键、reducer 回填使行变长），所以首导后必须整库 `VACUUM`。VACUUM 前设置 `auto_vacuum=INCREMENTAL`；之后只有空闲页、碎片（dbstat unused 占已用页）低于 5% 时用 `incremental_vacuum` 归还空闲页，不再整库重写。`maintenance.json` 记录上次检查的页数，库增长不足 25%、空闲页不足 5% 时跳过 dbstat 全库扫描（watch 每次重扫都会排入维护）。
- **页大小**：每个表和索引至少占一页（约 130 个对象）。按库大小分档并带回差：<6 MiB 用 1 KiB，<16 MiB 且当前大于 4 KiB 时用 4 KiB，≥12 MiB 的 1 KiB 库升到 4 KiB，≥32 MiB 用 16 KiB。small（801 事件）用 4 KiB 页为 4.09 MB（0.810×），空对象占约 37 页×4 KiB，trigram FTS 只有 4 个段、`optimize` 不再缩小；把 `event_context` 改成 WITHOUT ROWID 因 70 字符 uid 进入二级索引只省 12 KB，所以改用 1 KiB 页，降到 3.86 MB。
- **与只读连接共存**：WAL 下 VACUUM 只占写锁，已开始的读事务继续读旧快照，结果不变；新事务在提交后读到压实后的文件，不会看到中间状态或 pending 投影（测试 `test_background_maintenance_keeps_reads_stable`）。改页大小需要暂时退出 WAL，必须是唯一连接；有读者时退回同页大小的普通 VACUUM，下次无读者时再换页。
- 只读连接：同样设置 `temp_store`、`cache_size`、`mmap_size`。

## 实测（2026-10-02，合成数据）

测试使用审计时的 `gen.py` 生成合成数据，不读取真实会话。机器为 14 核 Apple Silicon、SQLite 3.53，测试期间有多个并行 agent 占用 CPU（load average 10–60）。导入耗时的绝对值受干扰较大，所以表中写的是同时运行的配对结果。查询数字取 3 次中的最好值，用只读连接测量。

| 指标 | 基线 | v8 | 目标 |
| --- | --- | --- | --- |
| `event_page` 完整输出（med 900 会话 / 77,403 事件） | — | 与基线逐字节相同（基线只去掉重复的 `envelope.toolUseResult`）；`trajectory_page` 也相同 | 相同 |
| ≥39 KB 工具输出读回 sha256（full 1,461 条 / med 208 条） | — | 全部与源文件一致 | 一致 |
| `verify` / `foreign_key_check` / 记账不一致 | ok / 0 / 0 | ok / 0 / 0 | — |
| `ext` 列总字节（full） | 145.0 MB | 20.5 MB（0.14 倍；blob 只占 57 KB，因为合成输出重复度极高） | ≤0.4 倍 |
| 库体积（full，checkpoint 后） | 2,824 MB | 2,879 MB（1.02 倍） | ≤0.8 倍，**未达到** |
| 首次全量导入（full，配对同时运行） | 795 s | 726 s（1.10 倍） | ≤270 s，**未达到** |
| 首次全量导入（med，配对同时运行） | 64.9 s | 47.8 s（1.36 倍） | — |
| med 单文件追加 1 行后重扫 | 309 s（同负载） | 14.7 s | ≤30 s |
| `trajectory_page` 100 条（full） | 2,075 ms | 3.9 ms | ≤100 ms |
| 来源状态（full） | 1,009 ms（旧 SQL） | 1.1 ms（`source_status`） | ≤50 ms |
| 某工具最近 5 次调用（full） | 14.4 ms | <0.01 ms | ≤5 ms |
| `current_projection`（full） | 6.0 ms | 0.18 ms | — |
| 中文子串检索（full，命中 0 条的最坏情况） | `LIKE` 356–453 ms | `event_search` 0.01–0.08 ms | ≤100 ms |
| 会话列表、按项目、按工具的查询计划 | `SCAN` + `TEMP B-TREE` | 走索引，无 `TEMP B-TREE` | 无 `TEMP B-TREE` |

体积没有下降的原因：合成数据中 `ext` 只占全库约 5%，去重省下约 125 MB；新增的外键反向索引和查询索引约增加 180 MB。剩余体积主要是 70 字符 uid 及其在各索引中的重复，以及 `attrs`，不在本包范围内。对 med 库执行 `VACUUM` 还能再小约 7%。

导入提速有限的原因：PRAGMA 和检索索引只覆盖消息带来了收益，但 30 个外键索引和 5 个查询索引在首次导入时需要实时维护，抵消了一部分。导入时间主要仍是 Python 端的 jsonschema 校验和映射，由并行与增量任务包（b）处理。

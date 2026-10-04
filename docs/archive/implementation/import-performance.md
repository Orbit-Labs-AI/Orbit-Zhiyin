# 导入性能：并行、增量、首启渐进与采集暂停

> 文档状态：历史记录。正文保留原基线、日期与证据；其中的状态和数字不代表当前版本。现行入口见[文档导航](../../README.md)。


本文说明 DT-02 / DT-02.1 的导入调度：捕获与映射如何并行、重扫如何只重算受影响的会话、首次启动如何先发布最近的会话，以及采集暂停与补扫。数据契约、L0–L3 分层与来源索引见 [来源索引、完整正文与 App 轨迹读取](../../modules/data/indexed-trajectories.md)。

原则：并行与增量只改变“谁来算、算多少”，不改变结果。任何路径的逻辑摘要必须与 `workers=1` 的串行全量重建逐表一致；做不到的情况一律退回串行或整来源，不跳过记录。

## 入口

| 入口 | 作用 |
| --- | --- |
| `ImportService(store, workers=None)` | `None` 取 `ORBIT_IMPORT_WORKERS`，否则 `min(8, CPU-1)`（至少 2）；`workers=1` 完全是旧的串行整来源路径 |
| `import_source(request)` | 捕获 + 投影一个来源；有变化时按会话闭包增量重算 |
| `import_progressive(requests, cancel=None, on_batch=None)` | 首次导入：最近会话先发布，其余分批后台完成，可取消 |
| `watch(request, stop)` | 轮询；采集暂停时只返回 `{"paused": true}`，不捕获 |
| `pause_collection()` / `resume_collection()` / `collection_state()` | 读写数据目录内的 `collection.json` |

实现位于 `parallel.py`（进程池、捕获扫描、两段式映射）与 `scheduler.py`（闭包范围、渐进批次、暂停状态）。`pipeline.py`、`indexing.py`、`service.py` 只保留调用钩子，未传新参数时走原逻辑。

## 并行捕获

`parallel.capture` 用 spawn 进程池按文件计算逐行字节位置、记录哈希与原生类型（`scan_lines`），写者只做 `executemany` 写 `raw_record`、`file_record`、`record_location`。版本号与 `record_uid` 规则与逐行写入一致。作业少于 24 个文件时在本进程内执行，避免启动进程池的开销。SQLite 行来源与无法读取的文件仍走写者串行路径。

**JSONL 追加快速路径**：同一 inode、size 增大，且上一版 `decoded_bytes` 前缀的 sha256 等于上一版 `source_sha256` 时，用 `INSERT…SELECT` 搬运旧的 `record_location`，只解析尾部（包含上一版未完成的末行）。任一条件不满足即整文件重扫。`iter_indexed_file` 一次查询加载 ordinal→行，不再逐行 SELECT。

## 两段式映射

1. **worker**：白名单内的独立文件（`claude_code`、无 `parentSession` 的 `pi`、无继承前缀的 `dsh`）在只读连接上完成 prepare、map、envelope、脱敏与事件契约校验（`pipeline.map_native`）。worker 看到的 store 是只记录 identity / issue / raw_record 更新的门面；mapper 一旦读写其他状态就抛 `NeedsWriter`，该文件退回写者串行。
2. **写者**：按原拓扑顺序回放（`pipeline.apply_mapped`）。存在性用一次批量查询加内存字典判断，常见路径批量写入（`_insert_rows` 委托 `store.insert_rows`，`event.ext` 照常经 payload 打包）；遇到已存在事件、同记录重复或映射错误时先 flush，再走原 apply 逻辑，所以 `seq`、folded / replayed 判断不变。

依赖前序文件 L2 的 mapper 留在写者串行：Codex fork / 历史、DSH 旧代、带 `parentSession` 的 pi、Kimi 索引，以及 OpenCode / Hermes 数据库。

事件契约校验（`contract.validate_event`）先走手写的 `event_certainly_valid`：它按 `event-v1.schema.json` 逐项判定，只在确定合法时放行；任何不确定（非法输入，或 `1.0` 这类少见但合法的形态）都交给 `Draft202012Validator`，所以非法事件抛出的 `ValidationError` 与之前相同。jsonschema 逐事件校验原占串行导入 CPU 约 40%。修改 schema 时须同步该函数；`tests/test_contract_fast.py` 用合成导入产生的信封做逐字段变异，断言快速判定从不接受 schema 拒绝的输入。

写者连接在会话内把 `cache_size` 提到 256 MiB（只升不降，不影响结果）；默认 2 MiB 时每批写入反复读回索引页，10 万事件规模约慢 4 倍。

## 受影响会话闭包

重扫有变化时，重算范围从“整个来源”缩小为受影响会话的闭包：变化文件所属的会话、证据链接、事件父子、`parent` / `fork` / `root` 谱系，以及 mapper 的父文件。以下情况退回整来源：

- 闭包超过来源文件的 30%；
- 来源含 Codex 等依赖型 mapper、保留证据或来源级问题。

重建过程中若守卫发现闭包外依赖（例如父事件不在闭包内），抛 `ScopeEscalation`，扩大闭包后重试。发布前的外键与 L1 记账校验按范围执行，`COMMIT` 时 SQLite 仍校验延迟外键。新消失的已索引文件标为 stale，按保留证据重新投影。

## 首启渐进发布

`import_progressive` 按 mtime 倒序排列所有来源的文件，按会话分组（Claude 子代理与主会话同组，DSH 同一会话目录的各代同组）。首批按最近修改时间依次取会话组，满足任一条件即截止：累计源文件字节超过 `FIRST_BATCH_BYTES`（6 MB，字节数近似事件量，从而近似首批可读时间）、已取 200 个会话、遇到 7 天以前的会话；首批至少包含最新的一个会话组。其余文件按来源归并，每个来源的剩余部分作为一批（批次按各来源最新剩余会话排序），因此每个来源只再整体投影一次，不再按约 500 个文件切成多批。空库上每批都整源重建过期来源，与普通首次导入走同一条发布路径。每批在同一个写事务内完成捕获与发布，读者始终看到上一份一致快照，不会读到 pending 投影。`source_scan.selection` 中间批次记为 `progressive`，最后一批为 `full`。`cancel` 在批次之间生效，已发布的批次保留。

## 采集暂停与补扫

`collection.json`（权限 0600）记录 `paused`、`paused_at`、`resumed_at`。暂停期间 `watch` 和 `import_progressive` 跳过，不产生新 revision；显式调用 `import_source` 仍按用户请求执行。恢复后下一次 `watch` 按文件 stat 与水位补扫，结果与未中断的导入相同。

## 验证

| 测试 | 覆盖 |
| --- | --- |
| `tests/test_parallel_import.py` | 全部 fixture Agent 与跨文件关系树（claude 子代理与 resume 复制前缀、pi `parentSession`、dsh 旧代与 fork、codex fork）在 `workers=1`、`workers=8`（进程内与进程池）下逐表一致；`workers=1` 不进入并行代码；追加快速路径；映射期间源文件变化时拒绝发布 |
| `tests/test_incremental_projection.py` | 随机 24 步追加、改写、删除、重命名、新增后，闭包增量结果与副本上的串行全量重建逐表一致；`verify`、`foreign_key_check`、记账检查通过 |
| `tests/test_progressive_import.py` | 读线程每 100 ms 调 `event_page`，首批之后 0 次 pending；最终摘要等于普通全量导入；暂停期间无 revision，恢复后摘要等于未中断导入 |

逻辑摘要目前在 `tests/_integrity.py` 内实现，覆盖 `raw_record` 去向、`record_event`、`event_page` 全量、L3 全表与 `ingest_issue`。与 (d) 合并后改用 `orbit_data.validation.integrity.logical_digest`。

## 实测

机器负载很高时绝对耗时不可信，因此按“与审计基线代码（`747b0da`）成对交替运行的加速比”判定。med 合成数据（审计脚本 `gen.py`，claude_code / pi / dsh 各 300 会话，7.74 万事件），基线与本包交替各跑 3 次取中位数；新代码使用默认 `workers`。单文件追加为 pi 首个文件末尾追加 1 行后对三个来源各重扫一次。

| 场景 | 基线 wall / CPU | 本包 wall / CPU | 加速比 | full 规模目标比例 |
| --- | --- | --- | --- | --- |
| 首次全量导入 | 64.2 s / 53.0 s | 21.0 s / 43.2 s | 3.1× | ≥2.9×（383→130 s） |
| 无变化重扫 | 0.27 s / 0.25 s | 0.09 s / 0.09 s | 3.1× | 绝对 ≤1 s |
| 单文件追加 1 行后重扫 | 249 s / 180 s | 0.78 s / 0.76 s | 约 320× | ≥63×（190→3 s） |
| 首批可读（渐进导入首批发布） | 64.2 s（须等全量完成） | 4.4 s | 14.6× | 绝对 ≤15 s |

三轮测量开始时 1 分钟 load average 为 15–79；本包第二轮全量因负载 44–69 达 209 s，被中位数排除。三次运行的事件数一致（77404）。full 规模的最终达标在与 (c) 合并及体积优化后统一测量。

### 实测结果

合入全部导入与分析优化（含首导写者 `wip/yhyfhgs-writer2` 与分析单进程路径 `wip/yhyfhgs-analysis-serial`）后的最终验收复测（2026-10-03 04:34–04:58，`wip/yhyfhgs-int` 的 `a29da8b`；同一提交 `pnpm check` 全部通过）。

- **对照**：审计基线 `747b0da`。两边用各自的 `.venv`（CPython 3.13.15），读取同一份共用合成数据：med 7.99 万事件、60 MB 源；full 52.67 万事件、395 MB 源。
- **方式**：所有计时都在机器级基准锁里串行执行，每次新进程，基线与新代码紧挨着成对运行。full 首次导入成对 2 次（第 1 对基线在前，第 2 对新代码在前）；med 首导（含追加重扫、无变化重扫）与渐进导入各 1 次。新代码使用默认 `ImportService`（默认 `workers`、`maintenance="background"`）。
- **库体积**：新代码在导入返回后关闭服务与连接，用 `wait_for_maintenance` 等后台维护完成，再 `wal_checkpoint(TRUNCATE)` 后量 `orbit.db`；基线没有维护，导入后直接 checkpoint 再量。压实耗时不计入导入耗时。
- **追加重扫**：在 pi 首个文件末尾追加 1 行，再对 pi 重扫一次。**无变化重扫**：维护完成后重新打开库，各来源重扫一次。
- **负载**：机器为 14 核 Apple M4 Pro，测量期间有其他 agent 占用 CPU；表中“负载”为每次运行开始时的 1 分钟 load average。

| 场景 | 基线 | 新值 | 加速比 / 比例 | 目标 | 达标 | 负载（开始，基线 / 新） |
| --- | --- | --- | --- | --- | --- | --- |
| full 首次导入 wall（CPU），第 1 对 | 350.7 s（326.4 s） | 75.1 s（72.4 s） | 4.67×（CPU 4.51×） | ≥5.1× | 否 | 6.9 / 3.1 |
| full 首次导入 wall（CPU），第 2 对 | 348.8 s（328.8 s） | 76.2 s（73.6 s） | 4.58×（CPU 4.47×） | ≥5.1× | 否 | 4.2 / 3.3 |
| full 首次导入，两对合计 | 699.5 s | 151.3 s | 4.62× | ≥5.1× | 否 | — |
| med 首次导入 wall（CPU，参考） | 49.8 s（46.8 s） | 19.1 s（14.5 s） | 2.61×（CPU 3.22×） | — | — | 10.6 / 13.7 |
| med 渐进导入首批可读 | 49.8 s（须等全量完成） | 2.21 s | — | ≤10 s | 是 | 14.3 |
| med 渐进导入全程（4 批） | 普通导入 19.1 s | 17.6 s | 0.92 倍 | ≤1.3 倍 | 是 | 14.3 |
| med 库体积（维护后） | 443.0 MB | 332.9 MB（渐进 333.0 MB） | 0.752 倍 | ≤0.8 倍 | 是 | — |
| full 库体积（维护后） | 2,920.0 MB | 2,184.3 MB | 0.748 倍 | ≤0.8 倍 | 是 | — |
| 压实耗时（整库 VACUUM，不计入导入） | — | med 0.54 s（渐进 0.59 s）、full 3.26 s | — | — | — | — |
| med 单文件追加 1 行后重扫 | 208.7 s | 0.087 s | 约 2,400× | ≥60× | 是 | 10.6 / 13.7 |
| med 无变化重扫 | 0.379 s | 0.216 s | 1.8× | ≤1 s | 是 | 同上 |

**未达标项与原因**

- **full 首次导入（两对 4.67× / 4.58×，合计 4.62×，目标 5.1×）**：新代码运行时 load 只有 3.1–3.3，wall 与 CPU 基本相等（75 s / 72 s），说明耗时落在单写者的 CPU 上，而不是被负载挤占；基线在低负载下为 349–351 s，低于上一轮 load 12 时的 385 s，加速比因此比上一轮（4.70×）还略低。新代码 wall 相对上一轮 82.0 s 缩短约 8%（写者批量插入去掉逐行搜索触发器、外键校验每表一次扫描），但仍不足以达到 5.1×；剩余差距在单写者的 L2 插入与派生阶段，见下节剖析。
- med 首次导入本轮 19.1 s 高于上一轮 13.2 s，开始时 load 13.7（上一轮 8.1），且 wall 明显高于 CPU（19.1 s / 14.5 s），属负载影响；它不是验收目标，渐进全程仍低于普通导入。
- 其余导入项全部达标，渐进首批、库体积、追加重扫与无变化重扫均未退化。

### 首导写者剖析与重叠（`wip/yhyfhgs-fullimport`）

med 首导（默认 workers，基准锁内，load≈12）按阶段计时，写者共 12.6 s：

| 阶段 | 耗时 | 说明 |
| --- | --- | --- |
| map（含 L2 批量插入 2.6 s、父链接、invalid 扫描、FTS 收尾） | 5.1 s | `executemany` 插入 event 本身约 2.2 s，主要是随机主键 B 树与触发器 |
| derive_sessions + derive_metadata | 2.6 s | `_derive_session` 1.7 s，其余为逐会话两次读事件与 JSON 解码 |
| capture（写者 `index_file` 1.5 s） | 2.0 s | |
| 发布校验（范围内外键、记账、水位、COMMIT） | 1.3 s | `MapPlan.validate` 0.7 s |
| prepare（等待 worker 阶段 A） | 1.2 s | 写者空等 |
| reset_projection / 索引重建 / FTS | 0.4 / 0.13 / 0.07 s | |

据此做的改动（结果不变：small、med 的 `logical_digest` 与 `8dca571` 逐字节相同，med 为 `424f28b4…`；`verify` ok、`foreign_key_check` 空、记账不一致 0）：

- **捕获与映射重叠**：首导时 `parallel.capture` 每写完一个行格式文件就提交其 `map_file` 任务；`MapPlan` 只在重新构造的任务与之完全相等时复用该 future，否则取消并清理溢出文件。渐进批次传 `premap=False`。
- **derive**：元数据阶段只取元数据事件与含 `git_root` 的事件；会话阶段只读用到的列；tool_call / tool_call_event / turn / session_feature 按表 `executemany`。
- **映射收尾**：父事件链接一次 `executemany`；invalid 记录扫描限定本次重建文件（其他来源的 L2 问题不会被删除）；水位更新一次 `executemany`。

### 导入后维护复测（`wip/yhyfhgs-compact`）

并行导入（默认 workers、`maintenance="background"`）结束后关闭导入连接，再等待后台维护完成后量 `orbit.db`。全部在一次基准锁内串行执行；基线 `747b0da` 与新代码交替运行，med 各 2 次。full 只跑新代码 1 次，基线体积沿用上表 2,920.0 MB（同代码、同数据，体积确定）。load average（1 分钟）为 6.4–8.7。

| 规模 | 基线库 | 新库（维护后） | 比例 | 目标 | 首导 wall（CPU），基线 → 新 | 维护耗时（不计入首导） |
| --- | --- | --- | --- | --- | --- | --- |
| small | 5.046 MB | 3.865 MB（1 KiB 页） | 0.766× | ≤0.8× | 0.484 s → 0.223 s | 0.016 s |
| med | 442.97 MB | 332.91 MB | 0.7515× | ≤0.8× | 49.7 s（47.5）→ 11.9 s（10.6），4.17× | 0.54 s |
| med 渐进 | — | 332.97 MB | 0.7517× | ≤0.8× | 首批 1.70 s，全程 12.8 s | 0.48 s |
| full | 2,920.0 MB | 2,184.3 MB | 0.748× | ≤0.8× | 新 95.1 s（86.4），上轮 100.8 s | 3.95 s |

维护在写锁释放后才开始（另有 1 s 宽限期），首批可读时间与导入返回时间都不包含它；med 首导 11.9 s 与 full 95.1 s 均不高于上一轮。首导后空闲页只有 1–3 页，slack 为 10–11%（small 41%），膨胀来自页内碎片，因此三种规模都走整库 VACUUM。小规模完整性（并行 + 维护 vs 串行无维护）：`logical_digest` 相同、`verify` 通过、`foreign_key_check` 为空、`event_page` 全部会话输出相同。

## 合并注意

本包与进行中的 `feat/data-app-integration` 在 `pipeline.py`、`service.py` 有文本冲突，解决时注意语义：

- `map_native` 的 envelope 需改用 `override_version or mapper_version_for(record.agent)`，并包在 `record_redactions()` 内（缓存为进程内 ContextVar，worker 中同样成立）；`MapPlan` 传给 worker 的 `mapper_version` 相应改为按 Agent 计算。
- DSH 父文件改为多代 `files_by_native` 列表后，保留本包的 `plan.owns(mapper)` 分支；闭包计算的“mapper 父文件”也需包含全部代次文件。
- `service.py` 的过期来源判断与 `scheduler.STALE_FILES` 应统一改为 `query.outdated_sources`，按 Agent 比较 mapper 版本。
- 事件批量写在与 (c) 合并后改为委托 `store.insert_rows`。

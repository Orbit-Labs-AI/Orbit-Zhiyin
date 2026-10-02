# 导入性能：并行、增量、首启渐进与采集暂停

本文说明 DT-02 / DT-02.1 的导入调度：捕获与映射如何并行、重扫如何只重算受影响的会话、首次启动如何先发布最近的会话，以及采集暂停与补扫。数据契约、L0–L3 分层与来源索引见 [来源索引、完整正文与 App 轨迹读取](indexed-trajectories.md)。

原则：并行与增量只改变“谁来算、算多少”，不改变结果。任何路径的逻辑摘要必须与 `workers=1` 的串行全量重建逐表一致；做不到的情况一律退回串行或整来源，不跳过记录。

## 入口

| 入口 | 作用 |
| --- | --- |
| `ImportService(store, workers=None)` | `None` 取 `TANDEM_IMPORT_WORKERS`，否则 `min(8, CPU-1)`（至少 2）；`workers=1` 完全是旧的串行整来源路径 |
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
2. **写者**：按原拓扑顺序回放（`pipeline.apply_mapped`）。存在性用一次批量查询加内存字典判断，常见路径批量写入（`_insert_rows`）；遇到已存在事件、同记录重复或映射错误时先 flush，再走原 apply 逻辑，所以 `seq`、folded / replayed 判断不变。

依赖前序文件 L2 的 mapper 留在写者串行：Codex fork / 历史、DSH 旧代、带 `parentSession` 的 pi、Kimi 索引，以及 OpenCode / Hermes 数据库。

写者连接在会话内把 `cache_size` 提到 256 MiB（只升不降，不影响结果）；默认 2 MiB 时每批写入反复读回索引页，10 万事件规模约慢 4 倍。

## 受影响会话闭包

重扫有变化时，重算范围从“整个来源”缩小为受影响会话的闭包：变化文件所属的会话、证据链接、事件父子、`parent` / `fork` / `root` 谱系，以及 mapper 的父文件。以下情况退回整来源：

- 闭包超过来源文件的 30%；
- 来源含 Codex 等依赖型 mapper、保留证据或来源级问题。

重建过程中若守卫发现闭包外依赖（例如父事件不在闭包内），抛 `ScopeEscalation`，扩大闭包后重试。发布前的外键与 L1 记账校验按范围执行，`COMMIT` 时 SQLite 仍校验延迟外键。新消失的已索引文件标为 stale，按保留证据重新投影。

## 首启渐进发布

`import_progressive` 按 mtime 倒序排列所有来源的文件，按会话分组（Claude 子代理与主会话同组，DSH 同一会话目录的各代同组）。首批按最近修改时间取至多 200 个会话，遇到 7 天以前的会话即截止（至少一个）；其余每批约 500 个文件。每批在同一个写事务内完成捕获与发布，读者始终看到上一份一致快照，不会读到 pending 投影。`source_scan.selection` 中间批次记为 `progressive`，最后一批为 `full`。`cancel` 在批次之间生效，已发布的批次保留。

## 采集暂停与补扫

`collection.json`（权限 0600）记录 `paused`、`paused_at`、`resumed_at`。暂停期间 `watch` 和 `import_progressive` 跳过，不产生新 revision；显式调用 `import_source` 仍按用户请求执行。恢复后下一次 `watch` 按文件 stat 与水位补扫，结果与未中断的导入相同。

## 验证

| 测试 | 覆盖 |
| --- | --- |
| `tests/test_parallel_import.py` | 全部 fixture Agent 与跨文件关系树（claude 子代理与 resume 复制前缀、pi `parentSession`、dsh 旧代与 fork、codex fork）在 `workers=1`、`workers=8`（进程内与进程池）下逐表一致；`workers=1` 不进入并行代码；追加快速路径；映射期间源文件变化时拒绝发布 |
| `tests/test_incremental_projection.py` | 随机 24 步追加、改写、删除、重命名、新增后，闭包增量结果与副本上的串行全量重建逐表一致；`verify`、`foreign_key_check`、记账检查通过 |
| `tests/test_progressive_import.py` | 读线程每 100 ms 调 `event_page`，首批之后 0 次 pending；最终摘要等于普通全量导入；暂停期间无 revision，恢复后摘要等于未中断导入 |

逻辑摘要目前在 `tests/_integrity.py` 内实现，覆盖 `raw_record` 去向、`record_event`、`event_page` 全量、L3 全表与 `ingest_issue`。与 (d) 合并后改用 `tandem_data.validation.integrity.logical_digest`。

## 实测

机器负载很高时绝对耗时不可信，因此按“与审计基线代码（`747b0da`）成对交替运行的加速比”判定。med 合成数据（审计脚本 `gen.py`，claude_code / pi / dsh 各 300 会话，7.74 万事件），基线与本包交替各跑 3 次取中位数；新代码使用默认 `workers`。单文件追加为 pi 首个文件末尾追加 1 行后对三个来源各重扫一次。

| 场景 | 基线 wall / CPU | 本包 wall / CPU | 加速比 | full 规模目标比例 |
| --- | --- | --- | --- | --- |
| 首次全量导入 | 64.2 s / 53.0 s | 21.0 s / 43.2 s | 3.1× | ≥2.9×（383→130 s） |
| 无变化重扫 | 0.27 s / 0.25 s | 0.09 s / 0.09 s | 3.1× | 绝对 ≤1 s |
| 单文件追加 1 行后重扫 | 249 s / 180 s | 0.78 s / 0.76 s | 约 320× | ≥63×（190→3 s） |
| 首批可读（渐进导入首批发布） | 64.2 s（须等全量完成） | 4.4 s | 14.6× | 绝对 ≤15 s |

三轮测量开始时 1 分钟 load average 为 15–79；本包第二轮全量因负载 44–69 达 209 s，被中位数排除。三次运行的事件数一致（77404）。full 规模的最终达标在与 (c) 合并及体积优化后统一测量。

## 合并注意

本包与进行中的 `feat/data-app-integration` 在 `pipeline.py`、`service.py` 有文本冲突，解决时注意语义：

- `map_native` 的 envelope 需改用 `override_version or mapper_version_for(record.agent)`，并包在 `record_redactions()` 内（缓存为进程内 ContextVar，worker 中同样成立）；`MapPlan` 传给 worker 的 `mapper_version` 相应改为按 Agent 计算。
- DSH 父文件改为多代 `files_by_native` 列表后，保留本包的 `plan.owns(mapper)` 分支；闭包计算的“mapper 父文件”也需包含全部代次文件。
- `service.py` 的过期来源判断与 `scheduler.STALE_FILES` 应统一改为 `query.outdated_sources`，按 Agent 比较 mapper 版本。
- 事件批量写在与 (c) 合并后改为委托 `store.insert_rows`。

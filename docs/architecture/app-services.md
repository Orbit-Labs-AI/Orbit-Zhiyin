# Orbit App 服务层：封装、UI 衔接与分析快照

> 状态：已定方案，服务层（§5.1 包 A）按本文实现于 `packages/backend/src/tandem_backend/services/`，实现细节与基准见 §7。审计基于 `main`（`0459c8f`）；性能数字来自合成数据，不含真实会话。
> 回答三个问题：Q3 数据模块如何封装为 App 的一部分（多个本地服务）；Q4 数据模块如何与 Lite / Advance 的对应环节衔接；Q7 分析模块如何与 UI 衔接并打包进 App（高可用、低延迟）。
> 关联：[功能映射](../plans/feature-map.md)（§5 前端→后端、§6.1 DT、§6.2 AN、§6.10 缺口对照）、[模块契约](../plans/module-contract.md)（§3.1 Scope / meta、§5.3 前端 API）、[缺口对照](../audits/backend-gap.md)、[后端架构](backend.md)、[数据管线](data-pipeline.md)、[模块接入表](module-map.md)。

## 0. 结论先行

1. **逻辑上 4 个服务，物理上 3 个进程**：`gateway`（对 UI 的唯一入口：HTTP + SSE、鉴权、只读查询、快照缓存、监管）、`ingest-worker`（唯一写者：发现 / 监听 / 导入 / 重建）、`analysis-worker`（计算、写分析结果）。`data-query` 不单独成进程，作为 gateway 内的只读连接池。Swift 宿主只拉起 gateway，gateway 拉起并监管两个 worker。
2. **SQLite 单写者 + WAL + 只读连接**：`tandem.db` 只有 ingest-worker 写；其余全部 `mode=ro`。`analysis.sqlite` 只有 analysis-worker 写。UI 永远不等写者。
3. **UI 的数字全部来自“快照”**：分析结果按 `(section, scope_hash, data_rev, rules_version)` 物化；请求命中即返回（目标 < 300 ms 首屏），数据变了先返回旧快照并标记 `stale`，同时后台重算，算完经 SSE 推送。绝不让 UI 在 10 秒级计算上同步等待。
4. **首启先秒开 UI，再渐进导入**：静态页面不依赖数据；先导入最近一批会话并发布（首个有数据画面），再补 30 天、再补全量，每一批原子发布。
5. **前端只加一层适配（`TandemLive`）**：Lite 与 Advance 共用同一份适配代码（mock ↔ live 切换、加载 / 空 / 错 / 陈旧 / 计算中 / 导入中六态、SSE 订阅），逐页绑定；未绑定的页面在 live 模式明确标“示例数据”，不静默混用。
6. **本次审计发现三个必须先在设计里解决的实测问题**（§1.2）：读路径在导入中途会抛 “Projection is pending”；`analyze_store` 同一范围重复调用仍耗时 10 s 级、全量结果 220 MB；增量导入不比全量快。它们分别落到 gateway 的“最后一次发布版本兜底”、按 section 分片快照，以及数据 / 分析审计包的前置依赖（§5.3）。

## 1. 现状盘点

### 1.1 已有（可直接复用）

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 本机 HTTP API | `packages/backend/src/tandem_backend/api/routes.py`（349 行） | `create_app()`：`/v1/analytics/*` 十余段、`/v1/sessions`、`/v1/projects`、`/v1/catalog*`、`/v1/evaluation`；`tandem serve` 用 uvicorn 绑端口 8765，无鉴权、无 SSE、无任务接口 |
| 导入服务 | `packages/data/src/tandem_data/service.py` | `ImportService.import_source(ImportRequest, cancel)`：`flock(import.lock)` 单写者、文件级取消、`progress` 回调（只含阶段与计数）、`watch()` 2 s 轮询；`ImportRequest.files` 可只导入子集 |
| 来源发现 | `tandem_data/discovery.py` | `candidates()` 只列目录，不读正文；`inputs(agent, root)` 是白名单 |
| 规范库读取 | `tandem_backend/data_access/store.py::CanonicalStore` | 每次读新开 `mode=ro` 连接；`counts / sources / session_page / event_page / evidence` 全是 SQL 分页 |
| 分析结果历史 | `analytics/history.py` + `tandem_data/analysis_history.py` | `recorded()` 记录每次运行与内容寻址的压缩结果（`analysis.sqlite`），但**不用于命中缓存** |
| 桌面外壳与应用状态 | `origin/feat/data-app-integration`（未合入） | Swift AppKit/WKWebView 宿主、随机端口 + 启动令牌、`DesktopService`（单队列任务、`interrupted` 恢复、`app-state.json`）、`/v1/app/*`、PyInstaller 打包脚本；旧目录布局，正与 main 合并 |

### 1.2 合成数据实测（300 会话 × 12 轮 × 每轮 3 次工具调用；Apple Silicon，Python 3.13）

| 项目 | 结果 | 含义 |
| --- | --- | --- |
| 全量导入 300 个会话 | 19.6 s（约 15 会话/s）；`tandem.db` 194 MB | 首启全量导入不可能同步等待，必须分批发布 |
| 再追加 60 个会话后增量导入 | 24.0 s（比全量还慢） | 增量路径疑似重算全库；归数据审计包处理，gateway 只依赖“批次可发布” |
| 读：`session_page(50)` / `counts` / `event_page(100)` | 1.5 / 1.6 / 2.8 ms | 直读 SQLite 远低于 UI 预算，**不必为这些接口做缓存** |
| 导入进行中并发读 | 稳态 p50 2.0 ms、p99 2.9 ms；但导入“已捕获、尚未重建”的窗口里，读线程收到 `ValueError: Projection is pending` | `current_projection()` 在待重建时一律拒绝读。gateway 必须有兜底（§4.2）；数据包应提供“读最后一次已发布投影” |
| `analyze_store(scope, with_text=False)` | 首次 10.8 s；**相同范围再次 10.5 s** | 没有结果缓存；`with_text=True` 38.8 s |
| 分析结果体积 | 全部 section 序列化 220 MB：`sessions` 75 MB、`projects` 44 MB、`bottleneck_features` 44 MB、`statistics` 39 MB、`lexical` 35 MB；**`overview` 仅 0.01 MB** | 前端要的往往只是极小切片，却要先算完整包。必须按 section 物化与分页（会话列表 ≤ 200 行紧凑摘要） |
| `analysis.sqlite` | 3 次运行后 90 MB | 历史按“完整结果”落盘，膨胀快；快照应按 section 存、保留最近 N 版 |

以上说明：**读与导入可以并行且互不阻塞；真正的延迟风险全在分析，必须异步 + 预计算 + 陈旧优先。**

## 2. Q3：数据模块封装为 App 的多个本地服务

### 2.1 服务划分

| 服务 | 职责 | 进程 | 读写 |
| --- | --- | --- | --- |
| **gateway** | 对 UI 的唯一入口：Bearer 鉴权、Host / Origin 校验、HTTP 路由、SSE 事件总线、任务登记、监管 worker、只读查询（会话 / 事件 / 项目 / 来源 / 清单 / 搜索）、快照读取与过期判断、静态页面（`/app`、`/lite`） | 主 helper 进程（uvicorn + asyncio；阻塞 SQL 走线程池，每线程一个 `mode=ro` 连接） | 读 `tandem.db`；读写 `cache/ui.sqlite`（响应缓存，可丢弃）、`app-state.json`（来源开关与设置） |
| **ingest-worker** | 来源发现（只列目录）、导入、重建投影、校验 / 备份、持续同步（轮询，监听留给 v1）；分批优先级调度；向 gateway 回报进度与“已发布版本” | 子进程 | **唯一写 `tandem.db` / `raw/`**；`flock(import.lock)` 兜底防双写 |
| **analysis-worker** | 执行 section 计算（`analyze_store` / `analyze_product_store` 及后续新增）、写分析结果与快照、预热、超时与取消、RSS 看门 | 子进程 | 读 `tandem.db`（`mode=ro`）；写 `analysis.sqlite` |
| **catalog / recommend / AI** | 沿用现有 `create_app()` 内的 `/v1/catalog*`、`/v1/recommendations`、`/v1/ai/*`（后续）。MVP 留在 gateway 进程内，不单独起服务；AI 作业之后注册为新的任务种类，复用同一套任务与 SSE | gateway 内 | 各自库 |

不拆更多进程的理由：CPU 密集的分析（scikit-learn / jieba，10 s 级，GIL）会卡住 gateway 的事件循环，且不可协作取消，所以必须进程隔离（超时直接杀进程重启）；导入的崩溃（坏日志、OOM）不应带走读接口，所以写者也隔离。再往下拆（每个 Agent 一个采集进程、独立 query 服务）在 MVP 阶段没有收益。

### 2.2 进程拓扑

```text
Orbit.app (Swift AppKit + WKWebView)           ← 原生能力：目录选择 / bookmark、保存面板、窗口、通知
   │  Process() 拉起，注入 TANDEM_API_TOKEN / TANDEM_PARENT_PID；读取 stdout 首行 {"port":N}
   ▼
tandem-helper gateway  (127.0.0.1:随机端口，Bearer token)
   ├─ HTTP  /app /lite（静态页）  /v1/*（JSON）  /v1/events（SSE）
   ├─ 只读连接池 ───────────────► tandem.db  (WAL, mode=ro)
   ├─ 响应缓存 ──────────────────► cache/ui.sqlite（可丢弃）
   ├─ 监管器 + 任务登记 ─────────► app-state.json（来源开关 / 设置 / 任务记录）
   │        │ stdio JSON Lines（请求 / 进度 / 结果 / 心跳）
   │        ├──► tandem-helper worker ingest   ──► 写 tandem.db、raw/
   │        └──► tandem-helper worker analysis ──► 读 tandem.db，写 analysis.sqlite
```

### 2.3 进程间通信

| 链路 | 方式 | 理由 |
| --- | --- | --- |
| WebView → gateway | `http://127.0.0.1:<随机端口>`，`Authorization: Bearer <启动令牌>`；页面由 gateway 同源提供，无 CORS | WKWebView 的 `fetch` 不能直连 Unix socket；令牌由宿主生成，经子进程环境与 `WKUserScript` 传递，不进命令行与 URL。沿用 `data-app-integration` 已验证的做法 |
| 宿主 ↔ gateway | stdout 首行 JSON 报端口；`GET /health` 轮询；`TANDEM_PARENT_PID` 看门（父进程变化即退出） | 避免宿主崩溃后残留进程 |
| gateway ↔ worker | 子进程 stdin / stdout，每行一个 JSON：`{"op":"run","job":…}`、`{"t":"progress"…}`、`{"t":"done"…}`、`{"t":"hb"}`；stdin 关闭即 worker 退出 | 无端口、无额外鉴权，生命周期随父进程；协议小到可以在测试里用管道直接驱动 |
| gateway → UI 推送 | 单路 SSE：`GET /v1/events`（用 `fetch` 流读取，可带 Authorization；原生 `EventSource` 不能设头，所以不用） | 一条连接复用所有主题；见 §3.4 |

不使用 Unix socket / launchd 的原因：WebView 无法直连；launchd 仅在 v1“App 关闭后继续采集”时才需要（届时用 `SMAppService` 登录项拉起同一个 `tandem-helper worker ingest --daemon`，与本设计兼容）。

### 2.4 数据所有权与并发规则

1. **写者唯一**：`tandem.db`、`raw/` 只由 ingest-worker 写；分析与 gateway 只读。`import.lock` 保留作双保险。
2. **发布即版本**：每次投影发布产生新的 `projection_run.run_id`；gateway 把 `data_rev = max(run_id)` 与 `inventory_rev = max(scan_id)` 缓存在内存，仅在收到 worker 的 `published` 事件时更新，请求路径上不查库取版本。
3. **读到“待重建”**：导入已捕获但尚未重建时，`current_projection()` 拒绝读（§1.2）。gateway 的规则：命中响应缓存则返回缓存并标 `freshness: stale`；无缓存则返回 `503 projection_pending` + `Retry-After`，前端保持上一屏数据并显示“正在整理”。数据审计包应让只读查询可读取最后一次已发布的投影（§5.3 依赖 D1），届时此兜底只剩缓存命中路径。
4. **分析不阻塞导入，导入不阻塞读**：三类连接互不持锁；analysis-worker 的读事务只持续到取完 bundle。
5. **脱敏边界不变**：gateway 只返回已脱敏的 L2 / L3 与分析结果；原文只经 `GET /v1/evidence/{id}/raw` 且需用户确认（沿用契约 §5.2）。

### 2.5 任务模型与可恢复

沿用 `data-app-integration` 的任务状态机：`queued / running / completed / partial / cancelled / failed / interrupted`，字段 `id, kind, status, created_at, progress{stage, completed, total, records}, result, error{code,message,retryable}`，持久化到 `app-state.json`（临时文件 + `rename` 原子写）。

| 种类 | 执行者 | 恢复规则 |
| --- | --- | --- |
| `import`（含 `phase: head/window/rest`） | ingest | 文件级水位线与原子发布使其天然可续：重启后把 `running` 标为 `interrupted`，用户或自动策略以原范围 `retry`；**不自动扩大采集范围** |
| `rebuild / verify / backup / inventory` | ingest | 同上；`rebuild` 只重建过期来源（既有行为） |
| `analysis.compute`（`section, scope, priority`） | analysis | 幂等：worker 崩溃后自动重排一次；同键任务合并（去重）；连续失败 3 次熔断，直到数据版本变化或手动 `recompute` |
| `analysis.prewarm` | analysis | 低优先级、可被交互请求抢占；被抢占时丢弃（不记失败） |

同一时刻：ingest 一个写任务；analysis 一个运行任务，优先级队列 `interactive > prewarm`。

### 2.6 启动顺序与首启体验

```text
T+0      宿主启动 gateway；加载静态页（不依赖数据，立即可用）
T+~0.3s  gateway 就绪（打印端口）；/v1/status 返回 state = onboarding | ready（< 20 ms，无库也能答）
T+~0.5s  gateway 拉起 ingest、analysis worker（懒启动：首个任务到达时才 fork，空闲 5 分钟回收 analysis）
         有历史数据：UI 立即用响应缓存 / 最近快照出图；后台检查新增文件
         无历史数据：欢迎页 → 发现来源（只列目录）→ 用户勾选 → 创建 import 任务
导入分批：
  head    最近 N=50 个会话（按 mtime 倒序，且不少于最近 7 天）  → 发布 → SSE data.published → UI 出第一屏（目标 ≤ 5 s；数据审计包优化后目标 ≤ 2 s）
  window  最近 30 天                                             → 发布 → 预热轻量 section
  rest    其余全部（低优先级、可暂停：用户打开重查询页时让路）      → 发布 → 全量预热（去抖 30 s，避免连续发布反复重算）
```

`ImportRequest.files` 已支持子集导入，分批只需 gateway / ingest 按 `stat().st_mtime` 排序切片，无需改数据层内部。每批发布都是一致的投影，中途退出不留半成品。进度只含阶段与计数，不含会话正文。

### 2.7 监管、健康检查、崩溃恢复

| 事件 | 处理 |
| --- | --- |
| worker 心跳 5 s 一次；15 s 无心跳 | 判定卡死，SIGTERM → 3 s 后 SIGKILL；重启 |
| worker 退出（崩溃 / OOM） | 指数退避重启 0.5 → 1 → 2 → 4 s；60 s 内超过 5 次进入 `degraded`，停止自动拉起并经 SSE 通知，UI 提示“后台服务异常，可重试” |
| 分析任务超时（轻量 20 s / 重型 120 s，可配） | 杀 analysis-worker 并重启；任务记 `failed(timeout)`；旧快照保留 |
| analysis-worker RSS > 1.5 GB | 当前任务完成后回收重启 |
| gateway 崩溃 | 宿主 `/health` 连续 3 次失败（2 s 间隔）→ 重启 gateway（新端口、新令牌），通过 `evaluateJavaScript` 设置 `window.__TANDEM_ENDPOINT__ = {base, token}` 并触发 `tandem:endpoint` 事件，适配层重连，不整页刷新；子 worker 因 stdin 关闭自行退出，不会残留 |
| 宿主退出 | gateway 父进程看门退出；ingest 在文件边界取消，已发布数据不受损（既有语义） |
| `/health` | 进程存活 + 各服务 readiness：`{ok, version, services:{ingest:{state,pid,restarts,last_hb}, analysis:{…}}, data_rev, projection:"ready|pending|absent"}` |

### 2.8 打包

- **形态**：`Orbit.app/Contents/{MacOS/Orbit（Swift 宿主）, Resources/ui/{advance.html, lite.html}, Resources/helper/tandem-helper/（PyInstaller onedir）}`。`tandem-helper` 是**一个**冻结可执行文件，用子命令区分角色：`gateway`、`worker ingest`、`worker analysis`；gateway 以自身可执行文件路径拉起 worker（冻结环境下不能用 `python -m`）。
- **复用**：`origin/feat/data-app-integration` 的 `apps/macos/Tandem.swift`（Process 拉起、令牌与端口握手、`NSOpenPanel` + security-scoped bookmark、退出时终止 helper）与 `apps/macos/build.py`（PyInstaller + swiftc + `codesign` + 可选公证）。**不重做**；本设计只把 helper 入口由单进程 `desktop.py` 换成 `tandem-helper` 三角色，并增加 Lite 页面资源。
- **Node 连接器**：MVP 不随包分发。Python 原生映射器已覆盖七个 Agent；TS 连接器（FSEvents 增量、`tandem-ingest`）作为 v1 的可选 sidecar，打成单个 Node 可执行文件由 ingest-worker 拉起，经现有 `bridge.import_connector()` 汇入。理由：少带约 40 MB 运行时与一套签名 / 升级面；轮询对 MVP 的“近实时”足够（自适应 2 s → 30 s）。
- **体积与签名（需实机测量）**：scikit-learn / scipy / jieba 使 onedir 体积需实测（预期 200 MB 量级）；PyInstaller 加载 numpy 动态库可能需要 `disable-library-validation` 之类的 entitlement；当前为非 Sandbox 独立分发，Developer ID + Hardened Runtime + 公证需用户提供身份。Sandbox 版（App Store）另立目标，不在本文范围。
- **数据目录**：`~/Library/Application Support/Tandem/`（`tandem.db`、`raw/`、`analysis.sqlite`、`cache/ui.sqlite`、`app-state.json`、`backups/`）；`--home` 覆盖用于演示与验收。

## 3. Q4：数据模块与 UI 的衔接（Lite 与 Advance）

### 3.1 通用约定

- **前缀**：应用生命周期沿用 `/v1/app/*`（与 `data-app-integration` 一致：`state / discovery / sources / settings / jobs / storage / export`）；数据与分析读取沿用 `/v1/*` 与 `/v1/analytics/*`（契约 §5.3）。不新增第三套命名。
- **Scope**：`GET` 带重复 query 参数（`project_ids / source_ids / model_ids / from_ts / until_ts / excluded_session_uids / display_timezone`，显式空值 `x=` 表示零个）。前端把时间预设换算为 `from_ts`（取本地日起点），`until_ts` 不传表示“到最新”，使同一预设在同一天内产生相同 `scope_hash`、命中同一份快照。Agent 筛选由适配层把 agent id 映射为 `source_ids`。
- **响应**：保持现有各 section 的键不变（不破坏旧测试与旧页面），**在顶层追加 `meta`**：`{contract, scope_hash, data_rev, rules_version, freshness: fresh|stale|computing|failed|none, computed_at, source: cache|computed, duration_ms, coverage, selection}`；`coverage / selection / unknown_counts` 等沿用现有键，不得把未知补成 0。
- **条件请求**：分析与列表响应带 `ETag: W/"<rules>:<rev>:<scope_hash>:<section>"`，`If-None-Match` 命中返回 `304`（≤ 5 ms）。
- **错误**：`{"error":{"code","message","retryable"}}`；`401 unauthorized`、`403 invalid_host/origin`、`404`、`409 job_conflict / rebuild_required`、`422 invalid_request / analysis_scope_too_large`、`503 projection_pending / service_unavailable`（带 `Retry-After`）。
- **空与计算中不是错误**：无数据 → `200` + `meta.freshness:"none"` + `meta.reason:"no_projection|scope_empty"`；计算中 → `202` + `{"meta":{"freshness":"computing","job_id","progress"}}`。

### 3.2 UI 区块 → 接口映射

延迟目标为本机、快照已就绪时的 p95 服务端耗时（不含渲染）。现状：✔ 已有，PR = 在 `data-app-integration`，**新** = 本设计的服务层包提供，依赖 = 取决于数据 / 分析审计包的产出。列出的是 MVP 路径；v1 项（实时、通知、小组件）在 §3.4 说明。

| 区块（feature-map） | Lite | Advance | 接口 | 参数 / 返回要点 | 目标 | 现状 |
| --- | --- | --- | --- | --- | --- | --- |
| 侧边栏计数、Agents 列表（SB-05/06）、置顶项目（SB-07） | 抽屉侧栏 | ✔ | `GET /v1/status`；`GET /v1/app/state`；`GET /v1/projects` | status：`state`、`sources[{id,agent,enabled,sessions,last_scan}]`、`counts`、`data_rev`、`jobs_active`、`services`；停用来源不计入 | 20 ms | 新 / PR / ✔ |
| 全局筛选栏（FB、FE-02） | ✔ | ✔ | 无独立接口：改 `Scope`，驱动所有页面请求 | 预设→`from_ts`；Agent→`source_ids`；排除会话→`excluded_session_uids` | — | 前端 |
| A1 概览（FE-03） | ✔ | ✔ | `GET /v1/analytics/overview`；`GET /v1/analytics/metrics?metric[]&bucket=day`；`GET /v1/analytics/profile`（迷你卡） | `overview.counts/usage`、日序列带 `{value,n,lo,hi,basis}`；缺失用 `null` 不用 0 | 命中 < 100 ms；首屏全部 < 300 ms | ✔ overview；依赖 metrics / profile |
| A2 协作人格（FE-04） | ✔ | ✔ | `GET /v1/analytics/profile`、`/profile/history`、`/preferences` | 四轴 `{value,lo,hi,n_units}`、`code`、`experimental`；样本不足 `status:"insufficient"` | 100 ms | ✔ preferences；依赖 profile |
| A3 会话列表（FE-05） | ✔ | ✔ | `GET /v1/analytics/sessions?offset&limit≤200&q&sort`；`GET /v1/search?q`（DT-23） | 紧凑摘要行（≤ 100 KB/页），不带全量特征；`next_offset`、`total` | 列表 < 150 ms；搜索 < 150 ms | ✔ 路由（但返回过重，见 §1.2）；依赖 search |
| A3 会话详情与轨迹 | ✔ | ✔ | `GET /v1/analytics/sessions/{id}`；`GET /v1/sessions/{id}/events?after_seq&limit≤500`；`GET /v1/evidence/{event_id}` | 事件游标分页，保留 `record_uid` 证据定位 | 30 ms（直读 SQL） | ✔ |
| A4 工具调用（FE-06） | ✔ | ✔ | `GET /v1/analytics/tools`；`GET /v1/analytics/tools/calls?name&limit`（AN-01.2） | `by_tool`、成功 / 失败 / 未知状态分列 | 100 ms | ✔ tools；依赖 calls |
| A5 项目习惯（FE-07） | ✔ | ✔ | `GET /v1/analytics/projects`；`GET /v1/inventory` | 项目聚合 + 配置覆盖（清单只读） | 100 ms | ✔ |
| A6 情绪与语义（FE-08） | ✔ | ✔ | `GET /v1/analytics/text`、`/tasks`、`/signals?kind` | 簇、高频反馈语、摩擦类型 | 150 ms | ✔ text / tasks；依赖 signals |
| A7 优化建议（FE-09） | ✔ | ✔ | `GET /v1/recommendations`、`POST …/feedback`（推荐模块） | gateway 透传，同样返回 `meta` | 150 ms | 推荐包 |
| A8 资源库（FE-10） | ✔ | ✔ | `GET /v1/catalog`、`/catalog/search`、`GET /v1/inventory` | 来源状态、本地清单 | 100 ms | ✔ / 依赖 |
| A9 生成工坊、问本地 Agent（FE-11/13） | — | ✔ | `POST /v1/ai/jobs`、`GET /v1/ai/jobs/{id}`、SSE | 复用任务与 SSE 基础设施，AI 模块注册作业种类 | — | AI 包 |
| 首次启动、数据源（FE-16、OB） | — | ✔ | `GET /v1/app/discovery`；`POST /v1/app/sources`；`POST /v1/app/jobs {kind:"import", phase}`；SSE `job` | 发现只扫目录名与属性；进度含阶段 / 计数 / 已发布批次 | 发现 < 500 ms | PR → 新 |
| 设置与存储（FE-15、SET） | 最小面板 | ✔ | `PATCH /v1/app/settings`；`GET /v1/app/storage`；`POST /v1/app/jobs {verify|rebuild|backup}` | 同步模式、默认范围、来源开关、容量 | 50 ms | PR → 新 |
| 导出（FE-19、EXP） | ✔ | ✔ | `GET /v1/app/export`；`GET /v1/export/csv?table` | 当前 Scope 的脱敏结果；原文不经此接口 | 异步 job 完成后下载 | PR / 依赖 |
| 命令面板（FE-14、PAL） | ✔ 全局搜索 | ✔ | `GET /v1/search?q&scope` | FTS5 子串，带 `Scope` | 150 ms | 依赖 DT-23 |

Lite 只使用 A1–A8、全局筛选、命令面板、导出与最小设置，Advance 全量；两者**共用同一组接口与同一份适配层**，差别只在页面绑定了哪些资源（`GET /v1/status` 的 `capabilities.mode` 可回报，但不改变接口）。

### 3.3 前端适配层（`TandemLive`）

形态：一份无依赖的浏览器脚本，同时嵌入 Lite（单文件 HTML 的带标记区块）和 Advance（`src/js` 新增文件，由构建拼接）；用同步脚本保证两处内容一致并可校验。

| 能力 | 行为 |
| --- | --- |
| 模式 | `mock`（默认；`file://` 或独立打开）/ `live`（由 gateway 提供的 `/app`、`/lite`，或 `?live=1`）。live 下端点来自 `window.__TANDEM_ENDPOINT__` / `__TANDEM_TOKEN__`，开发期可用 `#token=`；**live 一旦建立，失败时显示错误并保留上一屏数据，不回退成演示数据** |
| 请求 | `get(path, {scope, waitMs, signal})`：带 `If-None-Match`；返回 `{data, meta, state}`；同键并发请求合并；页面切换用 `AbortController` 取消 |
| 资源状态 | `idle / loading / ready / stale / computing / empty / error / importing` 八态；保留 last-good，陈旧数据加“更新于 xx · 正在刷新”徽标，计算中显示骨架并订阅 `analysis.ready` |
| 推送 | `fetch` 读取 `/v1/events`（SSE 文本帧），指数退避重连，`Last-Event-ID` 续传，缺口过大则 `resync`（重新 `GET /v1/status` 并失效相关资源）；事件到来只失效对应资源并 `render()` |
| 适配 | 每页一个 `bind(page, resources[], toViewModel)`：把 API 响应转成该页现有渲染代码消费的形状（`null` 显示 “—”）。**不在前端重算指标**（Demo 的 `stats()/persona()/15-derive` 在 live 下不再用于展示）；`basis / n / lo / hi / coverage / freshness` 用现有标注组件展示（FE-20） |
| 未绑定页面 | live 模式下显示“示例数据”徽标，避免真实与虚构混排 |
| 状态组件 | 顶部导入进度条（来自 `job` 事件）、陈旧 / 计算中徽标、服务异常横幅（`degraded`）、空态（引导去设置来源） |

### 3.4 SSE 事件（`GET /v1/events?topics=job,data,analysis,service`）

| 事件 | 载荷 | UI 动作 |
| --- | --- | --- |
| `job` | `{id, kind, status, progress{stage,completed,total}, phase}` | 进度条、完成提示 |
| `data.published` | `{data_rev, phase, counts, sources}` | 失效所有列表 / 计数资源；首次发布时离开“空态” |
| `analysis.ready` | `{section, scope_hash, rev}` | 命中的页面重新取并去掉“陈旧” |
| `analysis.failed` | `{section, scope_hash, code}` | 保留旧快照，显示可重试 |
| `service` | `{name, state: ok|restarting|degraded}` | 异常横幅 |
| `realtime`（v1，AN-13） | 运行中会话 / 当前工具 / 压缩前提示 | 菜单栏面板、HUD、小组件；先在同一连接预留主题 |

帧带单调 `id`；gateway 保留最近 1000 帧环形缓冲，15 s 心跳。

## 4. Q7：分析模块与 UI 的衔接、打包与高可用

### 4.1 快照模型

```text
snapshot_key = (section, scope_hash, data_rev, inventory_rev, rules_digest)
  scope_hash    = sha256(规范化后的 Scope JSON)（含 display_timezone，不含“当前时间”）
  rules_digest  = hash(RULE_VERSIONS + feature_schema_version + 引擎代码版本)   → 升级代码自动失效
  ETag          = W/"<rules_digest>:<rev>:<scope_hash>:<section>"
```

- 存放：analysis-worker 把**每个 section 的紧凑结果**写成独立快照（压缩 JSON，附 `meta`）；gateway 保存 ≤ 64 MB 的内存 LRU，并在 `cache/ui.sqlite` 落盘已渲染的响应体（`gzip`），重启后第一屏仍可秒出。两者都是可丢弃缓存，真值在 `tandem.db` + `analysis.sqlite`。
- **不在请求路径上序列化整包**：分析包 220 MB 级（§1.2）；快照按 section 与分页切片（会话列表 ≤ 200 行紧凑摘要，详情另取）。
- 保留策略：每个 `(section, scope_hash)` 保留最新 2 版；总容量上限（默认 512 MB）按最近访问淘汰；`analysis.sqlite` 的完整历史运行保持现状，不由本层管理。
- 与“分析审计包”的边界：快照的**内容与持久化模式**（哪些指标增量更新、按会话 / 按日分片缓存、`signal / problem / profile` 派生表）归分析审计包；本层只约定接口（§5.3 依赖 A1–A3）并提供默认实现（调用现有 `analyze_store` + `response_section`）。

### 4.2 请求流程

```text
GET /v1/analytics/{section}?scope…            （wait_ms 默认 0；适配层首屏用 800）
 1. 解析 Scope → scope_hash；rev = 内存中的 data_rev（无 DB 往返）
 2. If-None-Match == 当前 ETag                      → 304
 3. 精确命中 (section, scope_hash, rev, rules)       → 200  meta.freshness=fresh
 4. 命中同 (section, scope_hash) 的旧 rev            → 200  meta.freshness=stale  + 入队 interactive 计算（同键合并）
 5. 完全未命中
      有库：入队 interactive 计算；wait_ms>0 则最多等 wait_ms，完成即 200 fresh；否则 202 computing(+job_id)
      无库 / 范围为空：200 + meta.freshness=none
 6. 读库遇 projection_pending：有缓存按 3 / 4 返回；无缓存 503 + Retry-After
 7. 计算完成：写快照 → SSE analysis.ready；失败：SSE analysis.failed，旧快照继续服务
```

### 4.3 预计算与按需计算

- **触发**：每次 `data.published`（去抖 30 s；`head / window` 批次只预热轻量 section）；来源启停、设置变更；用户请求未命中（interactive，最高优先）；`POST /v1/analytics/recompute {sections, scope}` 手动。
- **预热范围**：默认范围（最近 30 天、全部 Agent）＋ 最近 5 个使用过的 Scope（MRU 存 `app-state.json`）。每个范围先算轻量 section（`overview`、`sessions` 摘要、`tools`、`projects`），再算重型（`text / lexical / statistics / tasks`）。重型 section 标注 `cost: heavy`，UI 进入对应页面时才升为 interactive。
- **成本控制**：prewarm 以较低 OS 优先级运行（`setpriority`）、单并发；interactive 到来时丢弃当前 prewarm（可被抢占）；用户正在拖动筛选时合并为最后一个 Scope。
- **更新**：按 `data_rev` 整体失效是 MVP 的保守默认；分析审计包若提供按会话 / 按日增量，则把“失效”收窄为受影响的快照，网关接口不变（只是 `rev` 更细）。

### 4.4 超时与降级

| 情况 | 行为 |
| --- | --- |
| 命中旧快照 | 先返回旧快照（`stale`），后台重算，完成后推送；UI 不闪、不空白 |
| 计算超时（轻量 20 s / 重型 120 s） | 杀 worker 重启，任务 `failed(timeout)`；有旧快照继续服务，无则返回 `503 analysis_unavailable`（可重试），页面显示“范围较大，请缩小”；3 次熔断后需数据变化或手动重算 |
| 范围过大 | 沿用 `422 analysis_scope_too_large`（`data-app-integration` 的预算语义），提示缩小时间 / Agent / 项目；概览允许降级为 SQL 聚合（`aggregate_only`，未算项为 `null`） |
| analysis-worker 不可用 | 读接口、会话 / 事件 / 搜索 / 清单照常；分析接口只服务缓存，UI 显示异常横幅 |
| 导入进行中 | 缓存继续服务（`stale`）；新数据发布后再重算，避免对一个正在变化的数据集反复计算 |

### 4.5 高可用与延迟预算

- **只读查询与导入互不阻塞**：WAL + `mode=ro`；实测稳态 p99 < 3 ms（§1.2）。投影待重建窗口按 §2.4-3 兜底。
- **自动恢复**：见 §2.7；所有后台状态可从 `app-state.json` + 两个 SQLite 重建，无内存独占状态。
- **预算（p95，快照就绪，本机）**：`/v1/status` 20 ms；会话 / 事件 / 项目 / 来源直读 30 ms；分析快照读 100 ms（`304` 5 ms）；首屏（status + overview + 当前页 section）≤ 300 ms；搜索 150 ms。冷启动到首个可交互画面 ≤ 1 s（静态页 + 缓存）；首批数据画面 ≤ 5 s（目标 ≤ 2 s）。这些是**验收目标**；服务层包用合成数据基准给出实测并设回归阈值（已有数据量级见 §1.2）。
- **内存**：gateway 常驻目标 < 300 MB（含快照 LRU 64 MB）；analysis-worker < 1.5 GB 触发回收。

### 4.6 与 Swift 宿主的分工

宿主：窗口 / 菜单 / 目录选择与 bookmark / 保存面板 / 通知授权 / helper 生命周期与重启；不解析数据、不直连库。分析与数据的一切读写经 gateway，因此 Lite 与 Advance 的原生壳可以共用：菜单“Lite / Advance”只改起始路径（`/lite` / `/app`），数据目录与服务共享。

## 5. 任务包与边界

### 5.1 拆分

| 包 | 内容 | 文件边界（不重叠） | effort |
| --- | --- | --- | --- |
| **A. 服务层** | gateway、监管、worker 协议、任务与进度、SSE、快照读写与 ETag、`/v1/status`、`/v1/app/*`、分析与列表路由 | 仅 `packages/backend/src/tandem_backend/services/**`、`packages/backend/tests/services/**`、`packages/backend/pyproject.toml`（入口脚本）、`docs/architecture/app-services.md`；**不改** `api/routes.py`、`packages/data/**`、`analytics/**` | high |
| **B. 前端适配层** | `TandemLive`、同步脚本、Lite / Advance 绑定与状态组件、单元与浏览器检查 | 仅 `prototypes/shared/**`（新）、`prototypes/lite/**`、`prototypes/advance/**`（Advance 仅新增 `src/js` 文件并重建 `tandem-demo.html`，对既有文件至多一行挂钩） | medium |

两包之间只通过本文的 JSON 约定耦合：B 用手写夹具（`prototypes/shared/fixtures/`）按 §3.1–3.4 的形状做测试，A 用 TestClient 验证形状；合并后再做一次端到端联调（A 的 gateway + B 的适配层，合成数据）。

### 5.2 与其他分支的关系（避免重复与冲突）

- `origin/feat/data-app-integration`（单进程桌面服务）：**思路复用，代码不直接依赖**。A 的 `/v1/app/*` 路径、任务状态机、`app-state.json` 字段、令牌握手与 Host / Origin 校验与其一致。A 开工时该分支尚未合入 main，因此 A 在 `services/jobs.py` 写了等价的最小实现（`AppState` + `JobService`），执行器经接缝 `JobRunner` 交给 ingest worker 子进程；该分支合入后由 `DesktopService` 取代应用状态部分，只保留 `JobRunner` 的 worker 实现。
- `origin/fix/analysis-coverage-status`：覆盖输入契约。gateway 不解释 `coverage`，原样放入 `meta`；因此不会与其冲突。
- 已有 `api/routes.py`：A 不修改它。gateway 自己的路由先注册，其余请求回落到 `create_app()` 返回的既有应用（`mount("/")`），并手动转发其 shutdown 处理（`catalog_service.close`）。新增分析 section 由路由表（`SECTIONS` 注册表）声明，默认实现调用现有函数，分析审计包后续只需新增注册项。

### 5.3 对数据 / 分析审计包的依赖（只约定接口，不约定实现）

| 编号 | 需要方 | 内容 | 缺失时的退化 |
| --- | --- | --- | --- |
| D1 | 数据包 | 只读查询可读取“最后一次已发布投影”，导入捕获中不抛 `Projection is pending`；或提供 `published_revision()` | gateway 靠缓存兜底并返回 503（§2.4-3） |
| D2 | 数据包 | 分批导入（`files` 子集）每批可原子发布且发布后 `rev` 递增；`progress` 回调保持 `{stage, completed, total, records}`；增量导入只处理变化文件 | 分批仍可用，但每批 `rebuild` 慢 |
| D3 | 数据包 | `search(q, scope, limit)`（FTS5，DT-23）、`inventory` 读取函数保持 service 层可调用 | 搜索接口返回 `501 not_available` |
| A1 | 分析包 | 公开 `compute_section(store, scope, section, params) -> dict`（按 section 计算、不序列化整包）与 `RULES_DIGEST` | 默认实现整包计算后切片，慢但正确 |
| A2 | 分析包 | 会话列表的紧凑摘要函数（≤ 200 行 / 页、无全量特征） | 网关在快照写入时裁剪 |
| A3 | 分析包 | 新增 `metrics / profile / signals / problems` 的 section 注册 | 对应路由 404，前端对应页保持“示例数据” |

### 5.4 风险与实机验证项

1. **冻结 helper 的 worker 拉起**：PyInstaller 下以自身可执行文件 + 子命令拉起 worker，需在打包产物上验证（开发态用 `python -m`）。
2. **PyInstaller 体积 / entitlement / 公证**：见 §2.8，需实机。
3. **Lite 单文件并行编辑**：`genius-FXC` 持续修改 Lite 设计；适配层在 Lite 中只占一个带标记的连续区块与少量挂钩，mock 模式下视觉与行为不变（现有 `check-benchmark.cjs` 必须继续通过）。
4. **快照膨胀与失效过粗**：MVP 按 `data_rev` 整体失效；用户活跃导入期间可能频繁重算。去抖与“导入期间不重算”是缓解，真正解决依赖分析审计包的增量计算。
5. **SSE 经 `fetch` 读取**：需在 WKWebView 验证流式读取与后台节流；备选是 15 s 轮询 `/v1/status`（接口已够用）。
6. **令牌轮换**：gateway 重启后的新令牌注入路径（`evaluateJavaScript` + 事件）需宿主配合，原型验证。

## 6. 验收口径（两包合并后）

- 合成数据（≥ 300 会话）下：`/v1/status`、会话 / 事件直读、命中快照的 overview 满足 §4.5 预算；`304` 命中；首屏 ≤ 300 ms。
- 导入进行中并发 100 次读无一次失败（命中缓存或 503 带 `Retry-After`），读 p99 不退化。
- 杀死 analysis-worker：读接口不受影响，worker 自动重启，在途计算任务重排一次；杀死 ingest-worker：任务标 `interrupted`，重启后可原范围重试且数据一致（`verify` 通过）。
- 数据发布后旧快照返回 `stale`，计算完成收到 `analysis.ready`，页面无整屏闪烁。
- Lite 与 Advance 在 mock 与 live 两种模式下页面均无控制台错误；live 模式下未绑定页面显示“示例数据”；服务中断时保留上一屏并显示异常横幅。

## 7. 实现说明

服务层位于 `packages/backend/src/tandem_backend/services/`，入口 `python -m tandem_backend.services gateway | worker ingest | worker analysis`（安装后为 `tandem-helper`，冻结后以 `<可执行文件> worker <role>` 拉起 worker）。`--home` 覆盖数据目录，默认沿用 `tandem_data.paths.default_home()`。

### 7.1 模块

| 模块 | 职责 |
| --- | --- |
| [`gateway.py`](../../packages/backend/src/tandem_backend/services/gateway.py) | 组装 FastAPI：自身路由先注册，`mount("/")` 懒加载回落 `create_app()`（无库时回 `503 no_projection`），lifespan 中转发其 shutdown；内存中的 `Revisions`（`data_rev / inventory_rev / counts`，启动时读一次库，之后只由 worker 的 `published` 更新）；去抖预热；持续同步轮询；`run_gateway` 绑定随机端口、stdout 首行打印 `{"port":N}`、`TANDEM_PARENT_PID` 看门 |
| [`auth.py`](../../packages/backend/src/tandem_backend/services/auth.py) | 纯 ASGI 中间件（不缓冲 SSE）：Host 必须是本机回环加端口，Origin 若存在必须同源，`Authorization: Bearer`（`TANDEM_API_TOKEN` ≥ 32 字符，常量时间比较）；所有响应追加 `Cache-Control: no-store`、`nosniff`、`X-Frame-Options: DENY`、CSP 等；`ApiError` 统一错误体 |
| [`supervisor.py`](../../packages/backend/src/tandem_backend/services/supervisor.py) | `WorkerProcess`（懒启动、心跳看门、退避重启、`degraded`）；`IngestRunner`（`JobRunner` 的 worker 实现，退避窗口内提交的任务在重新拉起后下发）；`AnalysisQueue`（`interactive > prewarm` 优先级、同键合并、崩溃重排一次、超时、熔断、RSS 回收、空闲回收、interactive 运行时暂停 ingest 的 rest 批次） |
| [`worker_protocol.py`](../../packages/backend/src/tandem_backend/services/worker_protocol.py) | stdio JSON Lines；worker 的 fd 1 专供协议，库的 `print` 改走 stderr（写入 `logs/<role>.log`） |
| [`worker_ingest.py`](../../packages/backend/src/tandem_backend/services/worker_ingest.py) / [`ingest_plan.py`](../../packages/backend/src/tandem_backend/services/ingest_plan.py) | 唯一写者；`phase=auto` 时按 mtime 切 head / window / rest，每批经 `ImportRequest.files` 调 `ImportService` 并回报新 `data_rev`；rest 按块（默认 200 个文件）在块间可暂停；取消在文件边界生效 |
| [`worker_analysis.py`](../../packages/backend/src/tandem_backend/services/worker_analysis.py) / [`sections.py`](../../packages/backend/src/tandem_backend/services/sections.py) | 按 `SECTIONS` 注册表计算；同一 worker 内对同一 `(scope, with_text, rev)` 复用最近两次完整分析，避免各 section 重复跑整包；错误分类为 `not_found / invalid_request / analysis_scope_too_large / projection_pending / analysis_failed` |
| [`snapshots.py`](../../packages/backend/src/tandem_backend/services/snapshots.py) | 快照键、内存 LRU 与 `cache/ui.sqlite`；损坏的缓存文件直接重建 |
| [`jobs.py`](../../packages/backend/src/tandem_backend/services/jobs.py) | `AppState` 与 `JobService`；逐文件进度合并为“阶段变化或每 0.25 s 一帧”，避免一次导入挤满 1000 帧缓冲 |
| [`events.py`](../../packages/backend/src/tandem_backend/services/events.py) | SSE 总线；`Last-Event-ID` 早于缓冲时先发无 id 的 `resync` 帧 |
| [`routes_data.py`](../../packages/backend/src/tandem_backend/services/routes_data.py) / [`routes_app.py`](../../packages/backend/src/tandem_backend/services/routes_app.py) / [`routes_analytics.py`](../../packages/backend/src/tandem_backend/services/routes_analytics.py) | 直读、`/v1/app/*` 与 `/v1/events`、快照分析路由与 `POST /v1/analytics/recompute` |

### 7.2 接口与已定取舍

- 直读：`/v1/status`、`/health` 只读内存；`/v1/sessions`（保持既有列表形状，总数放 `X-Total-Count`）、`/v1/sessions/{id}/events`、`/v1/projects`、`/v1/sources`、`/v1/inventory` 用每线程一个 `mode=ro` 连接。`/v1/projects` 改为直读 `[{project_id, name, sessions, sessions_all, last_started_at}]`，不再在请求路径上跑 `profiling.analyze`；`sessions` 只计 main 会话，与 `/v1/sessions?project_id=` 默认的 `X-Total-Count` 一致，`sessions_all` 计全部 kind；没有会话的项目默认隐藏（`include_empty=true` 列出），重名项目后缀父目录。`/v1/sessions` 列表项为 `{id, title, project_id, project, model, started_at, kind, agent}`，`model` 取会话中最常用的模型调用，`kind` 参数默认 `main`，`all` 或逗号列表放宽，非法值 `422 invalid_kind`。投影待重建时同一请求的上一份结果带 `X-Tandem-Freshness: stale` 返回，否则 `503 projection_pending` + `Retry-After`。首次导入前尚无 tandem.db 属于“空”而非“暂不可用”：列表与汇总直读（含 `/v1/analytics/tool_calls`、`/v1/uiview/{sessions,projects,sentiment}`）在内存中的空 canonical schema 上照常查询，返回与有数据时同形的 `200`，带 `X-Tandem-Freshness: none`，对象体另加 `meta.freshness:"none"`、`meta.reason:"no_projection"`；按 id 查询返回 `404`；空结果不进响应缓存，首次导入发布期间仍是 `503 projection_pending`。
- 分析：`/v1/analytics/{overview,sessions,sessions/{id},tools,projects,text,tasks,preferences,instruction}` 走 §4.2。原先落到 `create_app()`、在网关进程内同步计算的重型路由也改走 §4.2 的 analysis worker：`statistics`、`lexical`、`bottleneck`、`presentation`、`recommendations`（GET/POST）、`products`（`sessions` 按 `offset/limit` 分页）、`products/sessions` 与 `products/compare`（复用 products 快照，网关只做搜索分页与对比）、`POST /v1/analytics/compare`、`/v1/analysis`、`/v1/catalog/match-analysis`（worker 产出匹配请求，目录匹配仍在网关）。这些段只按需计算、不预热；`products`、`presentation`、`compare` 预算 1800 s，其余按轻量 / 重型预算；失败一次即熔断，同一数据版本下直接返回 `503 analysis_unavailable`（消息带 `timeout` 等原因），数据变化或手动 recompute 才重算。202 所带 `job_id` 可用 `GET /v1/analytics/jobs/{job_id}` 查询 `queued / running / completed / failed` 与错误码。`/v1/analytics/runs*` 仍由 `create_app()` 提供（只读分析历史）。
- 载荷：分析段的 `sample_boundary` 只带 `file_count` 与 `files_digest`，文件清单改由 `GET /v1/analytics/sample_files?offset&limit≤1000` 分页提供。`/v1/sessions/{id}/events`（默认 `max_chars=8000`）与 `/v1/evidence/{event_id}`（网关直读，默认 64000）截断超长 `text` 与 `details` 字符串，标出 `truncated`、`truncated_fields` 与 `text_range{offset,length,total}`；全文用 `?text_offset=&max_chars=`（≤ 4,000,000）按区间读取。会话列表快照只存紧凑摘要行，分页在 gateway 做，ETag 的 section 段带 `[offset:limit]`。`preferences?task_id=` 与会话详情把参数并入 `scope_hash`。
- 快照失效按 `(data_rev, inventory_rev)` 整体判断；导入进行中命中旧快照时仍会排队重算（同键合并），去抖只作用于预热。预热范围为默认范围（最近 `default_range_days`，默认 30 天，UTC 日起点）加最近 5 个 MRU 范围；head / window 批次只预热轻量 section。
- 分批导入的每一批以 `files` 子集调用 `ImportService`，因此 `source_scan.selection` 记为 `sample`；“上游已删除”标记仍只在 `phase=full` 的全量导入中执行。持续同步（`sync_mode=live`）使用 `phase=full`。
- `/v1/app/export` 不在本包实现（`capabilities.export=false`）。`DesktopService` 合入后由其接管 `AppState` 部分。

### 7.3 配置（`SupervisorConfig`）

| 项 | 默认 | 说明 |
| --- | --- | --- |
| `heartbeat_s` / `stale_s` | 5 / 15 | worker 心跳间隔与判定卡死阈值（经 `TANDEM_WORKER_HEARTBEAT_S` 传给 worker） |
| `backoff_s` / `max_restarts` / `restart_window_s` | 0.5,1,2,4 / 5 / 60 | 崩溃重启退避；窗口内超过次数进入 `degraded`，用户提交导入或重试时复位 |
| `light_timeout_s` / `heavy_timeout_s` | 20 / 120 | 分析超时；按 section 的 `cost` 选择 |
| `max_failures` | 3 | 同 `(section, scope_hash)` 在同一版本下的熔断阈值；数据版本变化或 `recompute` 解除 |
| `rss_limit_bytes` / `analysis_idle_s` | 1.5 GB / 300 | analysis worker 回收条件 |
| `plan` | `{}` | 传给 `plan_batches` 的覆盖（`head_sessions`、`head_days`、`window_days`、`rest_chunk`） |
| `worker_env` | `{}` | 额外环境变量；`TANDEM_ANALYSIS_MAX_EVENTS` 设定分析事件预算，`TANDEM_WORKER_DEBUG_DELAY_MS` 仅供测试拉宽竞态窗口 |

### 7.4 验证与基准

- 测试：`uv run --no-sync pytest -q packages/backend/tests/services`（合成 Codex JSONL 70 个会话，真实子进程 worker 与 uvicorn），覆盖鉴权 401 / 403、无库 status、分批发布与 SSE 续传、导入中并发读、快照 202 → ready → fresh → 304 → stale、同键合并、杀 worker 恢复、超时熔断、卡死与 degraded、回落与 shutdown 转发。
- 基准：[`benchmarks/gateway_latency.py`](../../benchmarks/gateway_latency.py)，`uv run python -m benchmarks.gateway_latency --sessions 300 --repeats 200 [--strict]`。客户端经回环 HTTP keep-alive 计时。阈值即 §4.5 的 p95 预算；`--strict` 超预算返回 1。

2026-10-02 在 Apple M4 Pro、Python 3.13.15 上用 300 个合成会话的一次测量（ms）：

| 项目 | p50 | p95 | 预算（p95） |
| --- | --- | --- | --- |
| `/v1/status` | 0.57 | 0.84 | 20 |
| `/v1/sessions?limit=50`（直读） | 1.64 | 1.90 | 30 |
| `/v1/sessions/{id}/events?limit=100` | 1.81 | 2.16 | 30 |
| `/v1/analytics/overview`（命中快照） | 1.88 | 2.22 | 100 |
| 同上 `If-None-Match` → 304 | 0.67 | 0.92 | 5 |
| `/v1/analytics/sessions?limit=50`（快照分页） | 7.27 | 24.4 | 150 |

同次测量：分批导入全程 4.6 s，首批（head）发布 0.64 s；300 会话的 overview 冷算 4.8 s（期间 UI 得到 202 / stale，不阻塞）。数字随机器变化，回归以预算判定。

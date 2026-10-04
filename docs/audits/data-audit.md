# 本地数据模块（DT）审计：完成度、导入性能与优化任务包

> 文档状态：审计快照。正文保留原基线、日期与证据；其中的状态和数字不代表当前版本。现行入口见[文档导航](../README.md)。


> 审计基线：分支 `feat/yhyfhgs-dev`（`747b0da`，含最新 main `0459c8f`）。范围为 `packages/data`（`orbit_data`）、`packages/connectors`（TS 连接器与 staging 库），以及 `packages/catalog` 中与本地清单有关的部分。
> 功能口径以 `docs/archive/plans/feature-map.md` §6.1（DT 29 项）、§5 / `feature-map.csv`（UI→后端链）和 §6.10（缺口对照）为准。
> 性能数字全部来自构造数据（脚本见附录），没有读取或导入本机真实会话。数字是本机一次测量，**不构成性能承诺**。测量机器：Apple Silicon 14 核、48 GB 内存、Python 3.13.15、SQLite（Python 自带）。

## 0. 结论摘要

1. **完成度**：DT 29 项中，MVP 主干已经可用的有 DT-01（7 个连接器）、DT-04、DT-05、DT-06、DT-09、DT-15、DT-19、DT-20，共 8 项。部分完成 11 项，缺失 9 项，DT-21 在 PR 中。直接阻塞 Lite / Advance 接入真实数据的缺口有：DT-23 统一检索（只有 `event_fts`，没有查询接口，也不支持中文子串）、DT-02 Python 端增量与运行状态、DT-02.1 暂停 / 补扫、DT-03 / DT-15 的「占用分项 + 一键清除」、DT-22 来源能力探测、DT-24 resume 命令。另外 DT-07 的 `model_alias` 没有写入路径，DT-10 没有提供规则列表和预览接口。
2. **性能**：构造数据为 3 种 Agent × 2000 会话，共 **51.6 万事件**、源文件 349 MB。
   - 首次全量导入耗时 **383 s**（约 1350 事件/s），库体积 **2.82 GB**，是源数据的 **8.1 倍**。
   - 只给 1 个文件追加 1 行，就会重算整个来源。在已补外键索引的前提下仍要 **190 s**；不补外键索引时，中等规模（7.7 万事件）已经要 **147 s**。
   - 导入期间，所有读取都会被 `current_projection()` 判为 pending。因此**首启和实时监听都会让 UI 整体不可读**。
3. **五个主要瓶颈**：
   - ① 每个事件都做一次 `jsonschema` 校验，占 40% 的 CPU。
   - ② 逐行 `execute`，约 100 万次；外键反向索引缺失，导致重算时每次 DELETE 都要全表扫描。
   - ③ 增量粒度停留在「来源」，任何改动都重映射整个来源。
   - ④ Claude Code 的工具输出在 `event` 行内存了 **3 份**（`text`、`ext.toolUseResult`、`ext.envelope.toolUseResult`），脱敏也跑 3 遍。
   - ⑤ 写库没有调优 PRAGMA，只读连接也没有 `mmap` / `cache` 配置。
4. **优化方案**：
   - 采用文件级「进程池解析 + 映射 + 脱敏 + 校验」，由单写者按原文件顺序合并，批量提交。
   - 增量单位从「来源」缩小到「受影响会话闭包」，JSONL 追加走快速路径。
   - 首启按最近修改时间分批发布，后台补全。
   - 去掉 ext 中的重复载荷，大字段做内容寻址压缩。
   - 补外键索引和 UI 覆盖索引；对 PRAGMA 做调优。
   - 完整性用「逻辑摘要」做等价校验：串行旧路径 = 并行 / 增量新路径。
   - 目标：首次导入 ≥5 倍提速（≤75 s）；单文件追加 ≤3 s（≥60 倍）；库体积 ≤0.8 倍；首批最近会话 ≤15 s 内可读。
5. **任务包**共 4 个，文件互不重叠，见 §8：
   - (a) 补齐 DT 缺失接口；
   - (b) 并行 + 增量 + 首启渐进 + 暂停；
   - (c) 存储去重 + 索引 + PRAGMA；
   - (d) 合成基准 + 完整性回归。
   - (a)、(d) 可以立即开工；(b)、(c) 与 `feat/data-app-integration` 的 `pipeline.py / store.py / service.py / query.py / reduce.py / codex.py` 改动重叠，本轮已提前开工：新逻辑放进新模块，旧文件只留调用钩子，迁移号 007 留给该分支、(c) 用 008，见 §9。

---

## 1. DT feature 逐项对照（§6.1）

状态说明：**已完成** = MVP 范围在 main 可用；**部分** = 主体在，缺 MVP 必需子项或性能 / 接口；**缺失** = main 无实现；**PR 中** = 仅在未合并分支。

| ID | 名称 | 审计状态 | 证据（文件:行） | 缺什么 |
| --- | --- | --- | --- | --- |
| DT-01 | 连接器与数据源发现 | 已完成（MVP+P1） | `connectors/__init__.py`（7 个 mapper：claude_code、codex、dsh、pi、hermes、opencode、kimi）；`discovery.py:50-119` 白名单 glob | P2 Antigravity / Copilot 未做（按计划） |
| DT-01.1 | 通用自定义来源导入器 | 缺失（v1） | 无格式嗅探代码；`ImportRequest.root` 可指向任意目录，但只接受已注册 mapper（`service.py:60-66`） | 嗅探 + 字段映射（v1） |
| DT-02 | 增量读取、监听与运行状态 | 部分 | Python：`indexing.py:63-77` stat 未变即跳过，`service.py:188` 2 s 轮询；TS：`ingest.ts:125-137` 按 inode / size / 首尾哈希做追加增量，`watch.ts` | Python 端没有追加快速路径，变化文件整文件重哈希（`store.py:435-543`）；**任何变化都重算整个来源**（`service.py:149-163` → `pipeline.py:39-46`）；无运行中判定 |
| DT-02.1 | 采集暂停与恢复补扫 | 缺失 | `grep pause` 在 data 包无结果 | 暂停开关、恢复后按水位补扫 |
| DT-03 | L0 原始归档 | 部分 | 原生路径不复制会话（`source_reference`，`migrations/006.sql`）；`capture_stream` / bridge 仍写 zstd 归档（`store.py:300-424`） | 关闭归档与一键清除（SET-17）缺失 |
| DT-04 | L1 原始记录与全记账 | 已完成 | `001.sql:33-49`（`raw_record.disposition`），`:88-94` `record_event`，`:175` `ingest_issue`，`:220-224` `v_raw_record_ledger`；发布前校验 `pipeline.py:481-488` | 校验对全库做，增量时浪费（见 §4） |
| DT-05 | L2 标准事件 | 已完成（Python） | `schemas/event-v1.schema.json` 26 种 kind（含 `permission.request`） | TS `normalize.ts` 仍缺 `permission.request`（V12）；App 主路径为 Python，影响小 |
| DT-06 | L3 派生表与归一 | 已完成（MVP） | `reduce.py:185-575` 会话 / 轮次 / 工具 / 模型 / 特征 | `session.commits_n`（v1）未做 |
| DT-06.1 | 会话本地时区字段 | 缺失（v1） | `001.sql:104-106` 已有 `timezone / timezone_source`，没有 `utc_offset_min` | v1 |
| DT-07 | 项目归属与模型归一 | 部分 | `project(key_type)`、`project_override`（`001.sql:50-58`，`004.sql`）；`reduce.py:98-122` 读 `model_alias` | `model_alias` 无写入 / 种子；`effort_rank` 无来源；项目合并 / 拆分接口（A5-04）缺 |
| DT-08 | token 与成本 | 部分 | `contract.normalize_usage()` 六方言分桶；`usage_snapshot`、`v_session_call_usage`（`001.sql:229-237`） | 价目表折算（v1，依赖 DT-14） |
| DT-09 | 已安装清单 | 已完成（MVP） | `inventory/`（7 Agent、6 类、`005.sql` 版本化快照） | agent / command 类型与「由 Orbit 安装」标记（随 IN-04）；每次扫描全量复制快照（`inventory/__init__.py:98-121`），扫描与导入共用写锁（`:49`） |
| DT-10 | 脱敏 | 部分 | `privacy.py:69-177`（`redact / sanitize`，`REDACTION_VERSION`） | SET-12/13 需要的规则清单与样例预览接口缺；用户可编辑规则（v1）缺 |
| DT-11 | 生态来源抓取 | 部分（catalog） | `packages/catalog`（sync、checkpoint、FTS5、向量） | 不在本审计主范围 |
| DT-12 | Catalog 实体与去重 | 部分（catalog） | `migrations/catalog/schema.sql` | 同上 |
| DT-12.2 | 本地 Catalog 条目写入 | 缺失 | — | 依赖 AI-13 / AI-07 |
| DT-13 | 共享能力词表 | 部分 | `session_feature`（`001.sql:171-174`）、`item_feature` | `feature_vocab`、命令族表（只读命令 / 破坏性命令）缺 |
| DT-14 | 模型清单与公开成绩 | 部分（catalog） | 表已建 | 数据导入计划 |
| DT-14.1 | 上下文窗口阈值表 | 缺失（v2） | — | v2 |
| DT-15 | 存储、迁移与导出 | 已完成（核心） | `store.py:129-225` 迁移阶梯到 v6；`cli.py:101-106` `rebuild / import-connector / stats / verify / export` | SET-15「分项占用」、SET-17「清除全部」缺；首启进度与只读连接调优缺 |
| DT-16 | Hooks 与 OTel | 缺失（P1） | — | P1 |
| DT-17 | 额度快照 | 部分 | TS `normalize.ts:251-255` 把 `rate_limits` 记为 `ui.state` | Python `connectors/codex.py` 不处理 `rate_limits`；该文件在 `feat/data-app-integration` 里改了 827 行，**等合并后再补** |
| DT-18 | `/insights` 产物对照 | 缺失 | `grep usage-data` 无结果 | 只读读取器 |
| DT-19 | staging→canonical 桥接 | 已完成 | `bridge.py:10-129` | 性能：先解压再重压一份（`:96`），逐行查对照表（`:107-119`）；App 主路径不走它 |
| DT-20 | legacy 库适配 | 已完成 | backend `analytics/inputs.py::legacy_bundle()` | 过渡项 |
| DT-21 | 应用状态与桌面服务 | PR 中 | `origin/feat/data-app-integration`：`application.py`、`app_api.py`（旧目录） | 等迁入 `packages/backend` |
| DT-22 | 来源版本与能力探测 | 部分 | 每条记录存 `raw_record.harness_version`（`store.py:497-498`），会话存 `session.harness_version` | 支持矩阵（hooks / skills / MCP / 子代理 / headless）与 24 h 缓存缺 |
| DT-23 | 统一本地检索 | 缺失（main） | `001.sql:204-214` `event_fts`（unicode61，**对所有 text 建索引，含大段工具输出**） | 无查询函数与 `GET /v1/search`；中文子串需要 trigram；标题 / 项目 / 命令头 / 文件名未合并检索 |
| DT-24 | resume 命令模板 | 缺失 | — | 纯函数 + 运行中禁用 |

**依赖 DT 的 UI 条目**（`feature-map.csv` 309 行中 131 行的链路含 DT）：状态分布为 部分 68、计划 44、PR 中 16、已实现 3。其中 MVP 未完成的有 73 行。按 DT 侧原因归并如下：

| DT 侧原因 | 影响的 MVP UI 条目 | 由哪个任务包补齐 |
| --- | --- | --- |
| 无统一检索（DT-23） | A3-05、PAL-02、PAL-04、PAL-05、SB-03、A8-01（本地部分） | (a) 检索函数与接口；(c) trigram 索引 |
| 导入期间读取被判为 pending；无暂停 / 补扫 / 进度（DT-02 / 02.1） | GL-06、A1-02、A3-01、MB-04、SET-06、SET-07、SET-11、INIT-01、SB-08 | (b) |
| 占用分项、清除、导出（DT-03 / 15） | SET-15、SET-16、SET-17、MB-06 | (a) |
| 来源能力 / 版本（DT-22） | DM-02、SET-06（格式漂移告警）、FB-02 | (a) |
| 脱敏规则列表与预览（DT-10 只读） | SET-12、SET-13、SB-08、A9-06/07 | (a)（只读清单 + 预览） |
| 会话源文件定位、resume（DT-24、AN-16.1 的 `source_files`） | A3-10 | (a) |
| 轨迹 / 工具明细查询慢（DT-06 查询性能） | A3-12、A3-13、A4-10、A4-09 | (c) 索引；trajectory 查询重写 |
| model_alias / effort（DT-07） | A3-08、FB-03、A5-04 | 本轮不做（与 data-app-integration 的 codex / reduce 改动冲突），建议合并后另开 |
| 审批等待（DT-16）、额度（DT-17）、上下文阈值（DT-14.1） | A4-07、A4-13、A9-08 | P1 / v1 / v2，本轮不做 |

---

## 2. 建库与「导入 → 标准化表」流程梳理

```
discovery.inputs()              白名单 glob（同步、单线程）
  └─ ImportService.import_source(agent)      每个 Agent 串行；持有 import.lock 写锁
       ├─ capture（逐文件串行）   indexing.index_file
       │    stat 未变 → 跳过（✓ 快）
       │    否则：整文件读取 → 逐行 sha256 + json.loads + shape_hash
       │          → 逐行 SELECT MAX(version) + INSERT raw_record / file_record / record_location
       │          每个文件一个事务（✓），但单行 execute
       ├─ stale_sources = 有未发布 revision 的「来源」              ← 增量粒度 = 整个来源
       └─ pipeline.rebuild(source_ids)       一个大事务 BEGIN IMMEDIATE
            reset：按来源 DELETE L2/L3 全部行（外键反向检查无索引 → 全表扫描）
            prepare：逐文件 iter_file（重新读源文件、再算逐行 sha256、逐行 SELECT record_location）
            map：逐记录 mapper.map → envelope（脱敏 redact/sanitize）→ jsonschema 校验
                 → 逐事件 SELECT 是否已存在 → INSERT event / record_event + FTS 触发器
                 → 每条记录 2–3 次 UPDATE raw_record
            derive：逐会话再读全部事件、json.loads attrs → session/turn/tool_call/model_call…
            validate：PRAGMA foreign_key_check（全库）+ v_raw_record_ledger（全库）
            projection_run 发布
读者：query.current_projection() 要求「所有 source_revision 已发布」，否则报 pending
```

Inventory：`scan_inventory()` 扫描每个已授权根目录，每次把全部条目重新写成新快照。它与导入共用 `import.lock`，导入期间会被阻塞。体量很小，不构成瓶颈。

TS 连接器（只有 Codex）已经实现真正的追加增量：按 inode、size、首尾 4 KB 哈希判断，并按偏移续读。它把原文切块存成 zstd，并在 staging 库建了自己的 L2/L3。bridge 再把这些块解压、重压，写进 canonical 的 `raw/`，于是 Codex 走 bridge 时**原文至少存 2 份、L2 也存 2 份**，而且每条事件的 `ext.native` 还会带一份完整原生 JSON（`pipeline.py:196-199`）。App 原生路径用的是 Python Codex mapper 和 `source_reference`，不走这条链。

---

## 3. 实测（构造数据）

数据生成器 `gen.py`（附录）按 claude_code / pi / dsh 三种原生格式造会话。每轮包含用户消息、助手文本、工具调用（含 usage）和工具结果；5% 的工具输出约 40 KB，其余为短输出。

| 规模 | 会话 | 文件 | 原始记录 | L2 事件 | 源大小 |
| --- | --- | --- | --- | --- | --- |
| med | 3 × 300 | 900 | 54,600 | 77,400 | 53 MB |
| **full** | **3 × 2000** | **6,000** | **364,000** | **516,000** | **349 MB** |

### 3.1 全量导入分阶段耗时（full，未开 profiler）

| 阶段 | 秒 | 占比 |
| --- | --- | --- |
| capture（L0/L1 建索引） | 82.6 | 21.5% |
| prepare | 4.7 | 1.2% |
| **map（L2 映射 + 写入）** | **234.1** | **61.1%** |
| derive_metadata / projects | 2.2 | 0.6% |
| derive_sessions（L3） | 30.5 | 8.0% |
| validate_projection（全库 FK + 记账检查） | 27.1 | 7.1% |
| 其他 | 2.2 | 0.5% |
| **合计** | **383.4** | 约 1,346 事件/s，0.91 MB/s |

参考：`docs/modules/data/agent-connectors.md:104` 记录过真实 DSH 样本（79 会话、15.9 万记录）首次导入 34.9 s，量级一致。

### 3.2 CPU 热点（med，cProfile，总 84.7 s）

| 热点 | 累计秒 | 说明 |
| --- | --- | --- |
| `contract.validate_event`（jsonschema） | 33.5（40%） | 每事件一次完整 Draft 2020-12 校验；未开 profiler 时约 124 µs/事件。改用 fastjsonschema 约 10.4 µs（12 倍） |
| `sqlite3.execute` | 24.1（28%） | 103 万次调用，几乎全是单行 |
| `envelope`（`redact / sanitize`） | 13.9 | 对每个字符串都先算 sha256（`privacy.py:160`），结果大多用不上；Claude 输出要脱敏 3 遍 |
| capture `index_file` | 8.7 | 逐行哈希 + `json.loads` + `shape_hash` + 单行 INSERT |
| `derive` | 5.0 | 逐会话重新读取并 `json.loads` attrs |

### 3.3 改动变体对比（med，未开 profiler，全新库）

| 变体 | 全量秒 | 倍数 |
| --- | --- | --- |
| 基线 | 52.3 | 1.00 |
| PRAGMA（`synchronous=NORMAL`，`temp_store=MEMORY`，`cache_size=256MB`，`mmap=1GB`） | 36.8 | 1.42 |
| 跳过 jsonschema | 38.8 | 1.35 |
| 导入期间停掉 FTS 触发器，结束后再 `rebuild` | 43.4 | 1.21（合成数据词汇少，真实数据收益更大） |
| 以上三项 + 外键反向索引 | 25.9 | **2.02** |

结论：不并行、只做「低风险配置」就能拿到 2 倍；剩下的时间主要是 Python 端 CPU（映射、脱敏、序列化），要靠进程池并行。

### 3.4 增量与重扫

| 场景 | 结果 |
| --- | --- |
| 无变化重扫（med） | 0.23 s ✓（stat 跳过有效） |
| med：1 个 pi 文件追加 1 行 | **147 s**（未开 profiler）/ 176 s（profiler）。重算整个 pi 来源；SQL 占 158 s |
| med：同上，先补外键反向索引（`feat/data-app-integration` 的 FK 索引） | **26.7 s**（6.6 倍） |
| full：1 个 pi 文件追加 1 行（已补外键索引，profiler） | **189.6 s**：整个 pi 来源 18.2 万事件重映射 |

`ImportService.watch()` 每 2 s 轮询一次，只要有 Agent 正在写会话，每轮都会触发上述整来源重算。CPU 会被持续占满。

### 3.5 体积（full）

| 项目 | 大小 |
| --- | --- |
| 源文件 | 349 MB |
| **orbit.db（checkpoint 后）** | **2,822 MB（8.1 倍）** |
| `event` 表 | 1,022 MB（text 194 + attrs 262 + ext 145 MB，其余是标识符） |
| `raw_record` / `event_context` / `record_event` 及其索引 | 199 / 100 / 85+93 MB |
| 每行事件的标识符（`event_uid` 70 字符 sha256 等）均值 | **454 B/行**，在 8 个索引和 4 张子表中重复 |

已核实：Claude Code 的 40 KB 工具输出在同一行事件里存了 3 份（`text`、`ext.toolUseResult.stdout`、`ext.envelope.toolUseResult.stdout`）。根源是 `connectors/claude_code.py:146-163` 的 `unused()` 没有排除 `toolUseResult`，而 `:190` 又单独存了一份。

### 3.6 UI 关键查询（full，只读连接，取 3 次最好成绩）

| 查询（对应 UI） | 耗时 | 问题 |
| --- | --- | --- |
| `current_projection`（每个读接口都调） | 6 ms | 对 `source_file` 做全表 `json_extract` |
| 会话列表按 `started_at` 倒序（A3-06） | 3 ms | `SCAN session + TEMP B-TREE`（无索引，规模更大会变慢） |
| `event_page` 100 条（A3-12） | 7.5 ms | ✓ |
| **`trajectory_page` 100 条**（原文轨迹） | **2,175 ms** | `query.py:79-83` 的 `OR … IN (subquery)` 让 `raw_record` 全表扫描 |
| 工具 Top-N（A1-24 / A4-09） | 56 ms | 可接受 |
| 某工具最近 5 次调用（A4-10） | 14.5 ms | `SCAN tool_call`，无 `(name, started_at)` 索引 |
| `v_analysis_event` 全量计数（分析读入） | 3,059 ms | 4 表 JOIN + 视图过滤 |
| 正文 `LIKE` 子串（当前中文检索唯一办法） | 935 ms | 无 trigram |
| **来源状态**（SET-06 / SB-06） | **1,015 ms** | 无预聚合，`source × session × source_file` JOIN |

---

## 4. 瓶颈逐项核查（任务清单）

| 核查项 | 结论 | 证据 |
| --- | --- | --- |
| 串行逐文件处理 | **是**。Agent 之间、文件之间、记录之间全部串行；14 核只用 1 核 | `service.py:105`、`pipeline.py:365-412` |
| 整段会话内容多层重复拷贝 | **是**。Claude 工具输出 ×3；bridge 路径原文 ×2 + `ext.native` ×1 + staging L2；发布前、重算时还会把所有记录重新读一遍、重新哈希一遍（`indexing.py:140-176`） | §3.5 |
| 逐行 INSERT / UPDATE | **是**。约 100 万次 `execute`；每条记录 2–3 次 `UPDATE raw_record`（`pipeline.py:215-219, 341-345, 363-370`）；每个事件先 `SELECT` 是否存在（`:229-231`） | §3.2 |
| PRAGMA | 只有 `WAL`、`foreign_keys`、`busy_timeout`（`store.py:140-142`）；没有 `synchronous=NORMAL`、`temp_store`、`cache_size`、`mmap_size`；只读连接同样没有（`:55-63`） | §3.3：1.42 倍 |
| 批量导入前建索引 | 索引和 FTS 触发器在导入过程中实时维护。全新库首导可以先停 FTS 触发器、最后 `rebuild`（1.2 倍以上）；二级索引在首导时可以延后创建 | §3.3 |
| UI 查询缺索引 | **是**。缺外键反向索引（重算慢 6.6 倍）；缺 `session(started_at)`、`session(project_id, started_at)`、`tool_call(name, started_at)`、`raw_record(file_id, locator, version)`（`store.py:479-483` 每个变化行一次 MAX 查询）；`trajectory_page` 走全表扫描 | §3.4、§3.6 |
| 重复 JSON 解析 | **是**。capture 解析一遍，prepare 再解析一遍（`iter_indexed_file`），derive 再把 attrs 解析一遍；同一事件做 3 次 `canonical()` + 3 次 sanitize | §3.2 |
| 无增量 | **半有**。L0/L1 能按 stat 跳过，但 L2/L3 的增量粒度是「整个来源」；JSONL 追加没有快速路径；`validate_projection` 每次都对全库检查（27 s） | §3.4 |
| 首启阻塞 | **是**。导入期间 capture 逐文件提交新 revision，`current_projection()`（`query.py:20-22`）一旦发现 revision 数 ≠ 已发布数就报 pending。full 规模下首启 6.4 分钟 UI 完全不可读，此后每次重扫也会让 UI 不可读，持续到重算结束（单文件追加要 3 分钟） | §2 |

---

## 5. 优化方案

### 5.1 并行导入（单写者）

- **capture 并行**：用进程池按文件分片，worker 只读源文件，计算逐行 `(ordinal, offset, len, sha256, native_type, native_id, harness_version, shape_hash)`，以元组批量返回。写者事务内先一次性取出 `locator → MAX(version)` 和上一版 `locator → sha` 的映射，再用 `executemany` 写入。源文件读取一致性仍用前后 `source_stat` 比对（与现有逻辑一致）。
- **map 两段式**：
  - **阶段 A（并行）**：判定为「独立文件」的，worker 直接在只读连接上执行 `mapper.prepare / map`，并完成 `envelope`（脱敏、`canonical` 序列化）与契约校验。独立文件指 mapper 不读前序文件 L2 的文件，包括 claude_code 主 / 子转录、无 `parentSession` 的 pi、dsh 最高代、opencode / hermes / kimi 的单库文件；判定规则做成白名单，不确定就不并行。
    - worker 里的 `store` 换成门面：`identity()` 只做纯 `uid` 计算，同时记下待插入行；`issue()` 和 `UPDATE raw_record` 都记成待执行动作。
  - **阶段 B（串行写者）**：严格按现有拓扑顺序（`pipeline.py:150-177`）合并。已存在事件的 folded / replayed 判断、`seq` 分配、`first_by_native` / `parent_keys` 都留在写者里。改用内存字典判断事件是否已存在，替代逐行 `SELECT`；插入一律 `executemany`；`raw_record` 的更新按文件攒批。
  - 依赖前序文件的 mapper（Codex fork / 历史选择、dsh 旧代、带父会话的 pi、Kimi 索引）仍在写者里串行执行。
- **保持确定性**：因为阶段 B 的顺序与旧路径完全相同，`seq` 和合并结果逐字节一致。worker 数为 1 时必须退化为旧路径。
- **契约校验**：不加新依赖时，校验放进 worker 并行跑（14 核约 8–10 倍）。如果团队同意加 `fastjsonschema`，单核就有 12 倍；锁文件变更由负责人决定。

### 5.2 增量导入

- **捕获层**：JSONL 追加快速路径（借鉴 TS 实现）。条件是 inode 不变、size 增大，且新文件前 `decoded_bytes` 字节的 sha256 等于上一版的 `source_sha256`。满足时用 `INSERT … SELECT` 把旧 revision 的 `record_location` 整体搬到新 revision，只解析新增的尾部行。不满足时退回整文件重建索引。
- **投影层**：重算单位由「来源」改为**受影响会话闭包**，步骤如下：
  1. 变化文件中的 `raw_record.session_uid`，取旧值和新值的并集，得到受影响会话；
  2. 向外扩展：这些会话涉及的所有文件、父子 / fork / root 关系（`session.parent_uid / root_uid / forked_from`），以及 mapper 层面的父文件（Codex `parent`、pi `parentSession`、dsh 同目录旧代）；
  3. 只 DELETE 和重映射闭包内的会话和文件，`derive` 也只针对这些会话；
  4. 闭包超过来源文件数的 30% 时，退回整来源重算。
- **发布前校验按范围做**：外键与记账检查限定在本次范围内，用 JOIN 查询代替全库的 `PRAGMA foreign_key_check`。全库检查留给 `verify` 和全量重算。
- **读者不再整体判 pending**：`current_projection()` 改为按文件判断。每个批次在同一事务里完成 capture 和投影发布（或 capture 后立即发布该批），保证提交点上不存在「已捕获未发布」的 revision。这样读者始终能看到上一次的一致快照。

### 5.3 首启渐进

`ImportService.import_progressive()` 的流程：

1. 一次发现全部 Agent 的输入，按 mtime 倒序排列。
2. **首批**按会话分组（同一会话的主文件、subagent 与 meta 文件同批）后取最新的组，满足任一条件即截止：已满 200 个会话、下一组早于最近 7 天、源文件累计超过 6 MB（`FIRST_BATCH_BYTES`）；至少包含最新一组。首批 capture → 闭包投影 → 发布，UI 立即可用。
3. 其余文件不再按固定文件数切分，而是**每个来源一批**（按该来源最新剩余会话的先后排序），每个来源只再整体投影一次；每批在同一写事务内 capture 并发布，支持取消、暂停（DT-02.1）和进度回调。规则见 `orbit_data.scheduler.plan_batches`。
4. 补全期间 `source_scan.selection='progressive'`，coverage 标为 partial，与 `fix/analysis-coverage-status` 的覆盖契约对齐。
5. 首导时可以先停 FTS 触发器，补全完成后统一 `rebuild`。代价是补全期间检索结果不全，需要给出 coverage 提示。

### 5.4 存储去重与内容引用（四层无损不变）

- `claude_code.py`：`unused()` 排除 `toolUseResult`（它已整体存在 `ext.toolUseResult`），去掉一份完整副本。
- `ext` 中 ≥4 KB 的字符串改存 `content_blob(sha256 PK, codec='zstd', raw_len, data BLOB)`，原位置写 `{"$blob":"<sha256>","len":n}`。相同内容只存一份，压缩后通常只有原来的 1/5 到 1/10。
- `query.event_page()` 读取时还原，接口输出与改动前逐字节相同。`event.text` 保持内联，原因是 FTS 和分析都直接读它。分析读取本来就不读 `ext`（`analysis_input.py:128`），不受影响。
- FTS 改为只对用户消息、助手消息和会话标题建 trigram 索引（新表 `event_search`），工具输出不进全文索引。命令头和文件名直接查 `tool_call` 列，从而支持中文子串，体积也大幅下降。
- 标识符方面，70 字符 sha256 的 uid 是契约字段，**本轮不改**，只记为契约 v2 候选：改成 128 bit base32（26 字符）可以省下约 60% 的标识符体积。

### 5.5 索引与 PRAGMA

- **写连接**：`synchronous=NORMAL`（WAL 下进程崩溃不丢已提交数据，只有断电可能丢最后几个事务）、`temp_store=MEMORY`、`cache_size=-262144`、`mmap_size=1 GiB`。导入结束后执行 `PRAGMA optimize`，然后 `wal_checkpoint(PASSIVE)`。
- **只读连接**：`mmap_size`、`cache_size`、`temp_store`。
- **新增索引**（用 `CREATE INDEX IF NOT EXISTS`，与 `feat/data-app-integration` 的 FK 索引同名，可重复执行）：
  - 外键反向索引全套；
  - `session(started_at DESC)`、`session(project_id, started_at)`、`session(source_id, started_at)`；
  - `tool_call(name, started_at)`；
  - `raw_record(file_id, locator, version)`。
- **`trajectory_page` 重写**：先用 UNION 物化会话相关的 `record_uid` 集合，再连表查询，去掉 `OR … IN` 子查询。
- **来源状态**：在 `source_scan` 里存聚合计数，或按需走 `session(source_id)` 索引计数。

### 5.6 完整性与等价性校验（各包共用）

先定义 `logical_digest(home)`。它是只基于**逻辑输出**的 sha256，不依赖物理存储形式，确定性地依次拼接以下内容：

1. `raw_record (record_uid, file_id, locator, version, sha256, native_type, disposition, session_uid)`，按 `record_uid` 排序；
2. `record_event` 全表排序；
3. 每个会话 `query.event_page()` 的全部事件（`ext` 已还原，不含 `rowid`）；
4. `session / turn / tool_call / tool_call_event / model_call / usage_snapshot / session_feature / link` 全列排序（排除 `captured_at / last_scan_at / completed_at / detected_at` 等时间戳）；
5. `ingest_issue (code, stage, file_id, record_uid)`；
6. 最新 inventory 快照的 `(agent, type, name, locator, content_hash)`。

再配合以下不变量：

- `store.verify()` 通过；`PRAGMA foreign_key_check` 结果为空；`v_raw_record_ledger` 中不一致行数为 0。
- 每个当前记录都有处理去向；每个 `mapped / folded` 记录至少关联一个事件。
- 各 Agent 的会话数和事件数等于生成器清单给出的期望值。
- 合成数据中每条 ≥40 KB 的工具输出，经 `event_page` 读回后，sha256 与源文件中的值一致。

**判定方式**：同一份数据，「旧串行路径」与「并行 / 增量 / 去重新路径」的 `logical_digest` 必须完全一致。增量路径另外要求：对随机追加、改写、删除、重命名后的源树，增量结果的 digest 等于对同一源树全量重建的 digest。

---

## 6. 预期效果（目标，需由任务包实测确认）

| 指标（full 合成数据，本机） | 基线 | 目标 |
| --- | --- | --- |
| 首次全量导入 | 383 s | (c) 单独 ≤270 s；(b) 单独 ≤130 s；(b)+(c) ≤75 s（≥5 倍） |
| 首批最近会话可读 | 383 s（全部完成前一直不可读） | ≤15 s |
| 单文件追加 1 行 | 190 s（已补 FK 索引）；不补时 ≥15 分钟级 | ≤3 s |
| 无变化重扫 | <1 s | <1 s |
| 库体积 | 2.82 GB | ≤0.8 倍（含新增索引）；`ext` 总字节 ≤0.4 倍 |
| `trajectory_page` / 来源状态 / 某工具最近 5 次调用 | 2,175 / 1,015 / 14.5 ms | ≤100 / ≤50 / ≤5 ms |
| 中文子串检索 | 935 ms（LIKE） | ≤100 ms（trigram） |

---

## 7. 与进行中分支的关系

- `origin/feat/data-app-integration`（DT-21，旧目录，正与 main 合并）改了 `pipeline.py`（179 行）、`connectors/codex.py`（827 行）、`store.py`、`service.py`、`query.py`、`reduce.py`、`privacy.py`、`contract.py`、`analysis_input.py`，并带一个与 main 冲突的 `migrations/006.sql`（30 个 FK 索引）。
  - 包 (b)、(c) 必须动这些文件，本轮提前开工，改动尽量放进新模块，旧文件只留调用钩子，该分支合入时按同名索引与迁移阶梯对齐。
  - 迁移编号约定：**007 预留**给该分支 FK 索引（从它的 006 改名）；包 (c) 使用 **008**，并在 008 里用 `IF NOT EXISTS` 重复声明同名 FK 索引。`store.py` 的迁移阶梯按「文件存在且版本较低就执行」处理 007 和 008，这样无论合并先后都能正确升级。
- `origin/fix/analysis-coverage-status` 改了 `analysis_input.py`、`inventory/__init__.py`，新增 `coverage.py`。本轮各包都不碰这三个文件。(b) 的渐进补全只写 `source_scan` 的覆盖状态，由覆盖契约读取。
- DT-17（Python Codex 额度）、DT-07（`model_alias` 种子、effort）、DT-09 新类型都会碰到上述分支的文件，本轮不做，等合并后再开。

---

## 8. 任务包（文件互不重叠）

| 包 | 主题 | 何时开工 | effort |
| --- | --- | --- | --- |
| (a) | 补齐 DT 缺失接口：检索、resume、能力探测、占用 / 清除、脱敏规则只读 + 预览、`/insights` 只读 | 立即 | medium |
| (b) | 并行 + 增量 + 首启渐进 + 暂停 / 补扫 | 与 (a)(d) 并行，避让 data-app-integration | high |
| (c) | 存储去重 + 索引 + PRAGMA + 查询重写 | 与 (a)(d) 并行，避让 data-app-integration | medium |
| (d) | 合成数据基准 + 逻辑摘要 + 完整性回归 | 立即 | medium |

文件清单与验收标准见返回的结构化任务列表。各包的公共约束：

- 不读取本机真实会话；
- 只用 `orbit_data` 现有依赖，新增依赖须经负责人同意；
- 提交前运行仓库根目录 `pnpm check` 中 data / backend 相关的子集，即 `uv run pytest -q packages/data/tests`，(a) 另跑 `packages/backend/tests`；
- 修改 DDL 后按 AGENTS.md 运行 `schema_export` 更新 `tables-v1.schema.json`（只有 (c) 改 DDL）。

---

## 附录：复现

脚本都在本审计的 scratchpad 目录 `audit/`，任务包 (d) 会把它们正式化到 `benchmarks/data/`。

```sh
python3 gen.py full 2000 15                               # 3 × 2000 会话，约 51.6 万事件
uv run python bench.py full h_full                        # 分阶段耗时、表体积、无变化重扫、单文件追加
uv run python exp.py med h_exp pragma,novalidate,nofts,fkidx   # 变体对比
uv run python uiq.py h_full                               # UI 查询耗时
uv run --with fastjsonschema python valbench.py h_med/orbit.db
```

# 数据导入基准与完整性回归

只使用构造数据，不读取本机任何 Agent 目录。背景与基线见数据模块审计（`docs/audits/data-audit.md` §3、§5.6）。

```sh
uv run python -m benchmarks.data.synthetic --preset small --out .local/benchmarks/data/synthetic
uv run python -m benchmarks.data.import_bench --preset med --check --output .local/benchmarks/data-med.json
uv run pytest -q packages/data/tests/test_import_integrity.py
```

## 合成数据（`synthetic.py`）

同一预设与 seed 两次生成，所有文件（含 SQLite 来源库与 `manifest.json`）字节一致。

| 来源 | 覆盖的形态 |
| --- | --- |
| `claude_code` | 主会话；每 10 个会话 1 个 subagent（含 `.meta.json`）；1 个 `--resume` 新会话，复制前 2 轮，记为 replayed |
| `pi` | 主会话；每 10 个会话 1 个 `parentSession` 分叉，逐字复制父会话第 1 轮 |
| `dsh` | `session.v4.jsonl`；每 10 个会话附 1 个 `session.v3.jsonl` 旧代，L1 入账、L2 ignored |
| `opencode` | SQLite 来源 `opencode.db` |
| inventory | `inventory/claude_code`：skills、MCP、hooks、plugins、rules（CLAUDE.md 与 `rules/`） |

每个来源的工具输出中每 20 个有 1 个 ≥40 KB（5%）。

| 预设 | 每个 JSONL 来源会话 × 轮 | opencode 会话 | 事件 | 用途 |
| --- | --- | --- | --- | --- |
| `small` | 10 × 4 | 4 | 801 | CI 回归，导入 <1 s |
| `med` | 300 × 15 | 30 | 约 8 万 | 本地对比 |
| `full` | 2000 × 15 | 100 | 约 53 万 | 与审计基线对比（审计数据为 3×2000×15，无 subagent/resume/opencode） |

`manifest.json`：`agents.<agent>.{sessions,events,records,files}` 是期望计数（事件数按 `synthetic.EVENTS` 中钉住的每类记录事件数计算，mapper 改变事件形态时须同步更新）；`large_outputs[]` 记录 `{agent, session(native_id), bytes, sha256}`；`inventory.items[]` 记录 `{type, name, locator, content_hash}`；`totals` 为合计。

## 逻辑摘要（`tandem_data.validation.integrity`）

- `logical_digest(home)`：按固定顺序对以下分区求 sha256；`section_digests(home)` 给出各分区的摘要与行数，用于定位差异。
  1. `raw_record (record_uid, file_id, locator, version, sha256, native_type, disposition, session_uid)`
  2. `record_event` 全表
  3. 每个会话经 `query.event_page()` 读回的全部事件
  4. L3：`project / session / turn / tool_call / tool_call_event / model_call / usage_snapshot / session_feature / link`，排除 `captured_at / observed_at / last_scan_at / completed_at / detected_at / discovered_at`
  5. `ingest_issue (code, stage, file_id, record_uid)`
  6. 每个 inventory 来源最新快照的 `(agent, type, name, locator, content_hash)`
- 排序在 SQL 中显式指定，与 rowid、索引、页布局无关；VACUUM、REINDEX 后不变。标识符包含来源根路径，只有同一份源树（同一路径）的导入结果可以比较。
- `invariants(home)`：`store.verify()`、`foreign_key_check`、记账视图一致性、无出处事件、发布事件数；`problems` 为空表示全部成立。

并行、增量、去重等改动的等价判定：同一源树上，旧路径与新路径的 `logical_digest` 必须相同。

## 基准输出（`import_bench.py`）

默认工作目录 `.local/benchmarks/data`（已忽略）；源树按预设与 seed 缓存，数据库每次全新创建，结束后删除（`--keep` 保留）。

| 字段 | 内容 |
| --- | --- |
| `environment` | Python、SQLite、平台、CPU 型号、逻辑核数、内存、启动时负载 |
| `preset / parameters / seed / repeats` | 规模与 UI 查询重复次数 |
| `dataset` | 生成耗时（复用缓存时为 null）、源大小 MB、manifest 计数 |
| `first_import` | 总秒数、按进度阶段（capture / map / derive_sessions / validate_projection 等）分秒数、各 Agent 秒数、事件/秒、MB/秒 |
| `maintenance` | 默认 `--maintenance wait`：首导计时结束后同步执行导入后维护（`Store.maintain`），记录动作、前后字节、页大小、slack 与秒数；`size` 因此是维护后的体积。`--maintenance off` 跳过 |
| `inventory_scan` | 秒数与条目数 |
| `size` | checkpoint 后库体积 MB、`dbstat` 分表与索引 MB、`event.text/attrs/ext` 字节 |
| `ui_queries_ms` | 12 条 UI 关键查询，取 `repeats` 次最好成绩（与审计 §3.6 相同） |
| `integrity` | `--check` 时：摘要、摘要耗时、不变量问题（`--skip-verify` 跳过逐行 verify） |
| `noop_rescan_seconds` | 无变化重扫全部来源 |
| `append_one_file` | 给 1 个 pi 文件追加 1 行后重扫 pi 的秒数与分阶段耗时；结束后还原源文件；`--no-append` 跳过 |
| `audit_baseline` | 仅 `full`：审计基线（383.4 s、2822 MB、189.6 s）及实测比值 |

计时受并发负载影响；记录 `load_average_at_start`，对比时说明规模、硬件与负载。

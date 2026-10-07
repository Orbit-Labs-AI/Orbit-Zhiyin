---
added: 2026-10-03
---

# G-性能与规模

> 历史来源：本页为2026-10-01 至 10-03 的历史方案，2026-10-07 从团队 Vault 迁入。原位置：`项目/Orbit/benchmark/后续扩展/G-性能与规模.md`。正文与原有日期、结论保留，仅整理导航和空白；私人会话定位不公开。本文中的“当前”、TODO、测试数量和执行命令仅对原文基线成立，本次没有重新验证，也不自动形成任务或授权。现行入口：[源码文档](<../../../../../evals/README.md>)。

[总入口](<overview.md>) · [共同协议](<protocol.md>) · 执行：S7

目标：测清楚 Orbit 自身的速度和资源开销。**同机性能计时独占运行**；其他 session 可以先写方案 / 审阅，暂停模型执行、大型导入、测试和构建。并行吞吐另开 G07，不能和单任务延迟混成一组数据。

| ID | 优先级 | 对象与规模 | 指标 | 当前入口 / 边界 |
| --- | --- | --- | --- | --- |
| G01 | P0 | 首次导入、无变化重扫、追加一文件；small / med / full | 秒数、事件/秒、MB/秒、阶段耗时、库体积、RSS | `benchmarks.data.import_bench`；独立 work 目录避免缓存和追加互撞 |
| G02 | P0 | 分析全链 500 / 1000 / 2500 会话，视资源增加规模 | read / bundle / select / 聚合 / products / JSON / 持久化耗时 | `benchmarks.analytics.full_pipeline`；setup 与测量分开 |
| G03 | P0 | Gateway：status、会话页、热快照、304、首次发布 | p50/p95/max、错误率、首次可用时间；冷 / 热分开 | `benchmarks.gateway_latency`；现有阈值是内部预算，非设备无关 SLA |
| G04 | P1 | 推荐 4 / 1000 项目录；Catalog 3000 项、200 查询起步 | 中位数、最大值、吞吐、检索延迟 / 内存 | `benchmarks/recommendation.py` 与 `catalog_bench`；不含外部 Skill 执行 |
| G05 | P1 | Instruction、semantic families、subjective outcomes 不同规模 | 耗时—规模曲线、RSS、质量等价性 | 已有三个 analytics benchmark；语义模型网络时延另列 |
| G06 | P1 | Orbit 自身 AI 分析 / 推荐、缓存命中、失败重试 | 实际 Token / 调用 / 缓存率、单位任务开销、延迟、输出大小 | `ai_usage` / `ai_ledger` 可对账；FakeEngine 不代表真实费用 |
| G07 | P1 | 1 / 2 / 4 个并发用户任务或后台作业，固定资源限制 | 总吞吐、单请求 p95、排队 / 执行时长、失败率、峰值 RSS | 需受控负载脚本；独立数据库 / 端口，区别于 F05 正确性 |

## 计时方法

每组固定 Git SHA、输入摘要、seed、硬件、OS、运行时、依赖、供电 / 电源模式与负载。先预热，再至少 3 次独立进程重复；记录每次原始值，不只报最好成绩。前后版本采用相同数据与交替顺序，不能“昨天繁忙 vs 今天空闲”。

- 冷启动与热缓存各一栏；清哪些缓存、包含哪些初始化要写清。不要为了制造冷启动删除用户真实缓存。
- 少量独立重复报中位数 / 范围；路由延迟建议 200 次请求计算 p95。3 次运行的最大值不叫 p95。
- `import_bench.ui_queries_ms` 当前取重复中的最好成绩，不能改名为平均 / p95；需要尾延迟则补原始采样工具并留旧字段。
- 有些 RSS 是进程生命周期峰值，须标清是否包含子进程；不能把 Python 分配峰值当整个 App 的常驻内存。
- `--check` / `--strict` 的现有阈值及退出码如实保留；本机受负载影响的失败不静默跳过，也不直接推广为所有 macOS 的性能结论。

## 可复用命令

以下只用构造数据，输出名和 work 必须每次唯一。先创建 `.local/benchmark/s7-run-01/`，再执行：

```sh
uv run --locked python -m benchmarks.data.import_bench --preset med --check --work .local/benchmark/s7-run-01/data-work --output .local/benchmark/s7-run-01/import.json
uv run --locked python -m benchmarks.analytics.full_pipeline --sizes 500 1000 2500 --repeats 3 --canonical --output .local/benchmark/s7-run-01/analysis.json
uv run --locked python -m benchmarks.gateway_latency --sessions 300 --repeats 200 --output .local/benchmark/s7-run-01/gateway.json
uv run --locked python -m benchmarks.catalog_bench --items 3000 --queries 200 --json .local/benchmark/s7-run-01/catalog.json
uv run --locked python -m benchmarks.analytics.instruction --output .local/benchmark/s7-run-01/instruction.json
uv run --locked python -m benchmarks.analytics.semantic_families --sizes 100 1000 --repeats 3
uv run --locked python -m benchmarks.analytics.subjective_outcomes --sizes 1000 10000 --repeats 3
```

无 `--output` 的脚本保存 stdout / stderr。目录检索默认不下载 embedding；本地模型实验须显式配置，并将模型加载时间与查询时间拆开。推荐入口计时可复用 `bash scripts/test-recommend.sh --output .local/benchmark/s7-rec-01`，先核对其包含的检查与计时边界。

## 交付与完成条件

交付环境清单、每次原始测量、阶段分解、规模曲线、负载说明、质量等价性检查。若机器被其他 session 占用，先完成脚本和输入准备，把正式计时排到独占窗口；不因需要并行加速而悄悄放宽测量口径。

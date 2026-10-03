# 数据导入与同步基准

用固定构造来源比较导入阶段、增量、维护、查询和逻辑完整性。默认不读取任何个人 Agent 目录。

```sh
python3 scripts/heavy.py uv run python -m benchmarks.data.import_bench --preset med --check --output .local/benchmarks/data-med.json
python3 scripts/heavy.py uv run python -m benchmarks.data.live_sync --preset med --minutes 8 --output .local/benchmarks/live-sync.json
```

## 输入与计时

`synthetic.py` 按 preset/seed 生成多来源、子代理、fork、重复与大输出等构造记录，manifest 保存预期身份、计数和哈希。mapper 形态变化时独立检查预期，不用实际输出反向生成 oracle。

import_bench 分别报告生成、首次导入、各阶段、库存、维护、空间、UI 查询、无变化重扫和单文件追加。维护默认与首导分开计时；不同模式、源树路径和硬件不能混成一个对照。

live_sync 启动临时 gateway，在构造来源中追加/更新记录，观察任务、重建次数、读取、WAL 与残留目录；用于定位同步退避和整源重复工作，不作普通 CI 门槛。

## 逻辑等价

`orbit_data.validation.integrity` 的 logical_digest、section_digests 和 invariants 按明确排序比较 L1 去向、贡献关系、标准事件、L3、诊断与库存。过程时间等已声明字段可排除，事实与覆盖不能随意忽略。

身份依赖来源根，因此比较使用同一源树路径。VACUUM 或索引布局变化可改变文件字节，但不应改变逻辑摘要。验证先于速度解释，失败时保留具体分区差异。

历史测量见[数据审计](../../docs/audits/data-audit.md)，当前策略见[导入性能](../../docs/modules/data/import-performance.md)。真实环境结果如另行授权取得，必须与构造结果分列。

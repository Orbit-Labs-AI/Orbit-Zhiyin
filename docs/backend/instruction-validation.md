# Instruction 实现与五类测试验收

2026-10-02，`MistyHuang03` 发起、Codex 实施。代码与验收脚本基线：`875dc02`，分支 `feat/analytics-instruction`，从最新可见 main `c97c818` 创建。关联 [Issue #4](https://github.com/ActionMesh-AI/Hackathon/issues/4)。这是 AI 技术验证，不是独立人工质量评审或团队口径确认。

范围仅为 Instruction。实现、字段和待办见 [特征族文档](../../src/tandem_backend/analytics/instruction/README.md)。

## 测试结果

| 类别 | 方法与范围 | 结果 | 边界 |
| --- | --- | --- | --- |
| 单元 | 正文、结构计数、提取、汇总、时点解析；来源、重复、未知、截断、冲突与显式替换 | 20 项通过 | 只验证定义过的行为 |
| 功能／mock | mock legacy adapter，检查 engine、CLI、API 结果及筛选一致；另用合成原生日志贯穿导入和 SQLite | 3 项通过 | 合成导入不冒称真实数据 E2E |
| 真实端到端 | 固定快照原生日志重新解析 → SQLite → CLI → 实际 localhost HTTP → 详情与筛选 | 通过；重解析 36 个会话、41,740 事件 | 只有 9 条可确认真人消息；零明确指令命中正例 |
| 性能 | 100／1,000／10,000 条合成消息，提取＋汇总＋结构＋解析，三次计时；单独测提取内存 | 最大批次中位数 2.9696 s，3,367 条/s，提取峰值 35.40 MiB | 本机 Python 3.12.3、macOS arm64；不是服务器 SLA |
| 正确性／质量 | 48 个构造输入，逐例比较八字段与类别的完整预期；中英正反例 | 48/48 完全匹配 | 规则回归集，不是独立真实世界准确率 |

Instruction 共 71 项 pytest 测试。完整仓库 `pytest -q`：469 passed，耗时 6.00 s；`ruff check src tests scripts` 通过。现有 Starlette/AnyIO 依赖弃用提示 1 条，未改变依赖。`tandem demo` 通过；`tandem evaluate` 的 readability 8/8、pipeline 34/34、probe 12/12。均未把结果写回用户历史。

首轮反例发现并修复：内联代码中的中文指令误报、编号列表切句、历史／习惯陈述误报、解释请求误报、单引号引用、逗号后独立指令被前面的否定污染。

## 真实性能与容量

| 合成消息数 | 三次耗时中位数 | 最慢一次 | 吞吐（条/s） | 提取峰值内存 |
| --- | --- | --- | --- | --- |
| 100 | 0.0288 s | 0.0340 s | 3,476 | 0.35 MiB |
| 1,000 | 0.2801 s | 0.3095 s | 3,570 | 3.53 MiB |
| 10,000 | 2.9696 s | 3.4695 s | 3,367 | 35.40 MiB |

每条消息带不同文件目标，含范围、测试、禁止推送要求。内存使用 tracemalloc，统计提取阶段新增 Python 分配，不含输入分配、完整服务 RSS 和其他进程。脚本默认检查每个批次中位数不超过 15 秒；机器负载变化会影响绝对速度。

真实数据的全流程计时：重导入 6.7574 s、CLI 完整确定性分析 4.0771 s、HTTP Instruction 请求 3.0778 s。这些耗时包含已有 analytics 的其他测量，并非纯 Instruction 提取时间。

## 真实数据边界和结果含义

沿用原台账已有快照：截至北京时间 **2026-10-01 23:43:13**（UTC 15:43:13），保留原有 1 个排除会话。源数据库以只读方式备份；只在新副本中使签名失效以强制真实解析，没有修改源台账或扩大快照。

台账有 36 会话、41,740 事件；analytics 排除复制历史边界未知的会话后选中 35 会话、40,664 事件，其中确认主会话 33 个，真人消息 9 条，来源未知消息 918 条。9 条均无当前规则支持的明确指令命中；抽查未将日志、设置回复等材料误收为指令。这里的未知既可能来自信息不足，也可能是规则尚不支持，不能等同于没有要求。

已验证真实导入、序列化、来源证据、消息分母、CLI/HTTP 完整结果一致、会话详情、排除筛选和时间边界。**尚未验证真实正例召回和真实授权变更解析**；不会为了测试通过把 918 条来源未知记录纳入真人分母。首轮脚本把“至少命中一个正例”当成前置条件而失败；核对数据后将该样本覆盖限制明确报告，最终实际链路检查通过。

完整本地输出位于本工作区 `.local/instruction-validation/real-v2/`，含 `summary.json`、`analytics.json`、数据库和运行日志；性能在 `performance-final.json`。这些文件均被忽略，不进入 Git。仓库中只保留脚本、合成夹具和汇总。

## 复现

在仓库根目录使用已安装 requirements-dev.lock 的 Python 环境：

```sh
python -m pytest -q tests/analytics/instruction
python -m pytest -q
ruff check src tests scripts
PYTHONPATH=src python scripts/benchmark_instruction.py \
  --output .local/instruction-validation/performance.json --max-seconds 15
PYTHONPATH=src python scripts/validate_instruction_real.py \
  --source-ledger /path/to/existing/frozen/history.sqlite \
  --codex-home /path/to/codex \
  --output .local/instruction-validation/fresh-real-run
PYTHONPATH=src python -m tandem_backend demo --output .local/instruction-validation/demo
PYTHONPATH=src python -m tandem_backend evaluate --output .local/instruction-validation/evaluation.json
```

真实 E2E 是显式运行的本地测试，不进入需要私有历史的 CI；必须有匹配数据源的既存固定快照，并使用尚不存在数据库的新输出目录。CI 使用合成测试，不需要私有文件。HTTP 通过绑定本机临时端口启动真实 uvicorn 进程；没有使用 TestClient 替代此项。

## 待完成

- 真实正例、独立人工标签、复杂否定和条件例外的质量评估。
- 更大规模、长文本、并发、冲突密集输入与其他平台性能验证。
- 团队口径确认与前端消费验收；未把 AI 测试结果标成成员已经确认。

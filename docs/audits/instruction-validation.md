# Instruction 实现与五类测试验收

> 文档状态：审计快照。正文保留原基线、日期与证据；其中的状态和数字不代表当前版本。现行入口见[文档导航](../README.md)。


**五类测试都已执行，Instruction 的 88 项测试和全库 486 项测试通过。** 真实日志已经从导入跑到 HTTP API，但可确认的真人消息只有 9 条，而且没有命中指令正例。因此，这次能确认流程可运行，还不能确认真实指令的识别效果。

2026-10-02，`MistyHuang03` 发起，Codex 实施。范围仅为 Instruction，代码从当时最新的 `main c97c818` 创建分支 `feat/analytics-instruction`。[PR #16](https://github.com/ActionMesh-AI/Hackathon/pull/16) · [Issue #4](https://github.com/ActionMesh-AI/Hackathon/issues/4) · [特征与接口说明](../../packages/backend/src/orbit_backend/analytics/instruction/README.md)。

用户已确认本次 MVP 的三人范围确认和 `yhyfhgs` 对 PR #16 的合并授权均已满足。下列测试由 AI 编写和执行，独立人工质量评估尚未完成。

## 测试结果

| 类别 | 怎么测 | 测到了什么 | 还没测到什么 |
| --- | --- | --- | --- |
| 单元 | 正文、结构计数、提取、汇总、时点解析；来源、重复、未知、截断、冲突与显式替换 | 37 项通过 | 只验证定义过的行为 |
| 功能／mock | 模拟数据适配器，核对分析引擎、命令行和 API 的结果与筛选；另用合成日志检查导入 SQLite | 3 项通过 | 真实日志另在下一项验证 |
| 真实端到端 | 重新解析固定快照中的原始日志 → SQLite → 命令行 → 实际本机 HTTP 服务 → 详情与筛选 | 通过；重解析 36 个会话、41,740 事件 | 只有 9 条可确认真人消息；零明确指令命中正例 |
| 性能 | 100／1,000／10,000 条合成消息，提取＋汇总＋结构＋解析，三次计时；单独测提取内存 | 最大批次中位数 3.3921 s，2,948 条/s，提取峰值 35.41 MiB | 本机 Python 3.12.3、macOS arm64；不是服务器 SLA |
| 正确性／质量 | 48 个构造输入，逐例比较八字段与类别的完整预期；中英正反例 | 48/48 完全匹配 | 规则回归集，不是独立真实世界准确率 |

Instruction 共 88 项 pytest 测试。完整仓库 `pytest -q`：486 passed，耗时 6.31 s；`ruff check src tests scripts` 通过。现有 Starlette/AnyIO 依赖弃用提示 1 条，未改变依赖。`orbit demo` 通过；`orbit evaluate` 的 readability 8/8、pipeline 34/34、probe 12/12。均未把结果写回用户历史。

Codex review 另指出后半句条件错误约束前半句计划，已拆分独立命令并增加 5 项中英文条件／文件名回归测试；例如“先给方案，等我确认后再改文件”中的计划要求保持无条件有效。

构造反例时也修复了一些误判：代码示例和引用被当成当前指令，“我们每天都跑测试”被当成测试要求，以及“不要推送，请运行测试”中后半句被前面的否定影响。编号列表和解释请求也补了相应测试。

## 速度和处理能力

| 合成消息数 | 三次耗时中位数 | 最慢一次 | 吞吐（条/s） | 提取峰值内存 |
| --- | --- | --- | --- | --- |
| 100 | 0.0318 s | 0.0407 s | 3,145 | 0.35 MiB |
| 1,000 | 0.3211 s | 0.3624 s | 3,114 | 3.53 MiB |
| 10,000 | 3.3921 s | 3.7837 s | 2,948 | 35.41 MiB |

每条消息带不同文件目标，含范围、测试、禁止推送要求。内存使用 tracemalloc，统计提取阶段新增 Python 分配，不含输入分配、完整服务 RSS 和其他进程。脚本默认检查每个批次中位数不超过 15 秒；机器负载变化会影响绝对速度。

真实数据的全流程计时：重导入 7.2245 s、CLI 完整确定性分析 5.5795 s、HTTP Instruction 请求 3.8082 s。这些耗时包含已有 analytics 的其他测量，并非纯 Instruction 提取时间。

## 真实数据边界和结果含义

沿用原台账已有快照：截至北京时间 **2026-10-01 23:43:13**（UTC 15:43:13），保留原有 1 个排除会话。源数据库以只读方式备份；只在新副本中使签名失效以强制真实解析，没有修改源台账或扩大快照。

台账有 36 会话、41,740 事件；analytics 排除复制历史边界未知的会话后选中 35 会话、40,664 事件，其中确认主会话 33 个，真人消息 9 条，来源未知消息 918 条。9 条均无当前规则支持的明确指令命中；抽查未将日志、设置回复等材料误收为指令。这里的未知既可能来自信息不足，也可能是规则尚不支持，不能等同于没有要求。

这次真实测试检查了：日志能否重新导入、结果能否保存为 JSON、每项是否能回到来源、统计分母是否一致、CLI 与 HTTP 是否返回相同内容，以及详情、排除范围和时间筛选是否正确。

**还没有验证真实指令能识别出多少，也没有验证真实授权变化能否判断正确。** 918 条来源未知消息没有进入真人统计。首轮脚本曾要求“至少命中一个正例”，因此失败；检查这批数据后，脚本改为检查确实存在真人消息，并如实报告命中数为零，最终流程检查通过。

完整本地输出位于本工作区 `.local/instruction-validation/real-reviewed/`，含 `summary.json`、`analytics.json`、数据库和运行日志；性能在 `performance-reviewed.json`。这些文件均被忽略，不进入 Git。仓库中只保留脚本、合成夹具和汇总。

## 复现

在仓库根目录先运行 `uv sync --locked --all-packages --dev`；以下命令使用当前 workspace：

```sh
uv run python -m pytest -q packages/backend/tests/analytics/instruction
uv run python -m pytest -q
uv run ruff check packages/backend/src packages/backend/tests packages/data/src packages/data/tests tests scripts evals benchmarks
uv run python -m benchmarks.analytics.instruction \
  --output .local/instruction-validation/performance.json --max-seconds 15
uv run python -m evals.analytics.instruction_real \
  --source-ledger /path/to/existing/frozen/history.sqlite \
  --codex-home /path/to/codex \
  --output .local/instruction-validation/fresh-real-run
uv run python -m orbit_backend demo --output .local/instruction-validation/demo
uv run python -m orbit_backend evaluate --output .local/instruction-validation/evaluation.json
```

真实 E2E 是显式运行的本地测试，不进入需要私有历史的 CI；必须有匹配数据源的既存固定快照，并使用尚不存在数据库的新输出目录。CI 使用合成测试，不需要私有文件。HTTP 通过绑定本机临时端口启动真实 uvicorn 进程；没有使用 TestClient 替代此项。

复审还修复了无约束普通消息污染范围状态、检查／处理／操作动词漏报冲突，并补充 12 项回归测试。完整测试 486 项通过；性能和真实 E2E 数字对应 `b17d0ee` 的复验，后续两项修复另由单元和全量回归验证。

## 待完成

- 真实正例、独立人工标签、复杂否定和条件例外的质量评估。
- 更大规模、长文本、并发、冲突密集输入与其他平台性能验证。
- 更多表达方式、独立人工质量评估，以及前端能否正确使用这些结果。

## 评审中暂缓的问题

评审发现三项 P2：直接说“请检查代码／请构建项目”时可能漏识别；“无需确认直接执行”这类连写可能漏掉执行顺序；build、ruff、lint 等动作的允许与禁止可能漏报冲突。按用户指示，本轮暂缓修复，具体例子和原评论见 [特征族待办](../../packages/backend/src/orbit_backend/analytics/instruction/README.md#评审中暂缓的三项-p2)。

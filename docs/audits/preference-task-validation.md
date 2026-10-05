# Preference / Task 开发与五类验收

> 文档状态：审计快照。正文保留原基线、日期与证据；其中的状态和数字不代表当前版本。现行入口见[文档导航](../README.md)。


本轮从 `main` 的 `c97c818` 创建 `feat/analytics-preference-task`。代码实现基线为 `62bc623`，特征 schema 升为 `feature-analytics-v2`。交付范围是语义／画像象限中的 [Preference](../modules/analytics/preference.md) 与 [Task](../modules/analytics/task.md)，其余族维持既有代码。关联 [Issue #4](https://github.com/Orbit-Labs-AI/Orbit/issues/4)。

两个特征族已经接入共用分析服务、CLI 和 API，旧接口与旧导入路径仍可用。模板所列字段都有规则实现及验收例；尚未实现的语义能力和真实人工质量验收明确列为下一步，不用测试通过代替业务确认。

## 目录与兼容性

```text
analytics/
  common.py                 # 真人边界、清理、证据与覆盖
  preference/
    features.py             # 提取、按时点解析、汇总
    rules.py                # 明确表达、范围、极性词表
    dictionary.py           # 本族字段定义
  task/
    features.py             # 分段、字段与分布
    taxonomy.py             # 版本化领域／任务类型词表
    representation.py       # 原 text.py 的文本表示实现
    dictionary.py           # 本族字段定义
  text.py                   # 兼容旧导入
  service.py                # 统一调度，沿用同一筛选范围
```

旧 `features.py` 里的工具、指令和交互统计不属于这两族，此次没有代其他成员重构；旧反馈／画像链路维持兼容。`legacy_bundle` 明确把推断 task_id 标为 legacy_inferred，新 Task 不据此跨会话合并。

## 五类测试结果

| 类别 | 方法与范围 | 结果／限制 |
| --- | --- | --- |
| 单元 | `packages/backend/tests/analytics/test_preference.py`、`test_task.py`，覆盖六个族入口和共享函数；文本表示沿用原回归 | 29 项通过；覆盖正反例、时间、缺失、重放、范围、去重和无输入修改。 |
| 功能／mock | `test_semantic_functional.py` 用 Mock 替换数据服务，经真实 FastAPI 路由检查响应；另用临时 SQLite 对照 CLI／API | 3 项通过；验证筛选、404、422、旧接口和新字段。 |
| 端到端／真实 | 原始 Codex 日志 → 新 SQLite → CLI 完整分析与 JSON → FastAPI ASGI；没有 mock | 通过；与原固定快照一致，API／CLI 两族记录一致，所有证据属于合格真人事件；未做外网部署／TCP 链路测试。 |
| 性能 | 完整 analyze_bundle，禁用文本投影；100／1,000／10,000 条合成真人消息，各重复 3 次；单独采样 Python 分配内存 | 结果如下；不是并发压测或服务器 SLA，也不包括导入和 JSON 序列化。 |
| 正确性／质量 | `semantic-quality-v1.json` 的 30 个固定期望样例（16 偏好、14 任务），加 1 个相容否定关系测试 | 31 项通过；案例由 AI 编写并在开发中使用，非盲测、非团队人工验收、非真实总体准确率。 |

本轮新增 63 项；全库 **461 项通过**，Ruff 与 `git diff --check` 通过。保留一条既有 Starlette／AnyIO 弃用提示。没有为了测试改变生产数据或向外部模型发送消息内容。

## 性能实测

环境：macOS-14.6.1-arm64-arm-64bit，Python 3.12.3；下列是 3 次计时中位数，内存另用 tracemalloc 测量，表示 Python 对象分配峰值，不等同进程 RSS。

| 消息数 | 会话数 | 分析中位耗时 | 吞吐量 | Python 分配峰值 |
| --- | --- | --- | --- | --- |
| 100 | 5 | 0.029 秒 | 3,467 条／秒 | 0.22 MiB |
| 1,000 | 50 | 0.326 秒 | 3,065 条／秒 | 2.13 MiB |
| 10,000 | 500 | 3.320 秒 | 3,012 条／秒 | 23.09 MiB |

这些数据验证了这次合成输入规模下的处理能力；尚未验证 10 万级以上、并发请求、极长消息、冲突密集且无时钟的偏好历史。`with_text=True` 的旧全文表示尤其是历史 novelty 可能更慢，需要单独容量测试。API 当前仍计算共用结果，真实样本单次请求约 2.5 秒，后续可考虑基于内容摘要缓存。

## 真实快照验收

沿用既有固定快照截止 `2026-10-01T15:43:13Z`（北京时间 23:43:13），保留原排除策略；重导入不覆盖原数据库。

- 选择 35 个会话，其中 33 个确认主会话；40,664 条事件。
- 可确认真人来源的消息 9 条；918 条用户角色消息来源未知，未提升为真人。
- 生成 5 个候选任务边界：2 个有领域／类型标签，3 个未知；命中批改、修改、发布。标签数量可超过任务数。
- 明确偏好 0 条；这是输入证据不足，不能解释成用户没有偏好。
- 原始导入耗时 7.27 秒；CLI 完整分析（含文本表示）3.11 秒；Task API 2.59 秒，Preference API 2.54 秒。

真实验收推动增加教育／批改、修改／上传词表；同时增加合成反例，防止把“测试字段”误识别为执行测试。真实数据仅检验流程、证据完整性和部分可解释输出，尚无足量真人金标准。

完整重导入数据库、分析 JSON 和测试摘要保存在被 Git 忽略的 `.local/semantic-families/`；不将原始消息、真实 ID 或本机路径放进共享文档。公开可复现案例都是合成输入。

## 复现命令

从仓库根运行，使用既有 `.venv`，无需新依赖：

```sh
.venv/bin/pytest -q
.venv/bin/ruff check packages/backend/src packages/backend/tests packages/data/src packages/data/tests tests benchmarks/analytics/semantic_families.py evals/analytics/semantic_history.py
.venv/bin/python -m benchmarks.analytics.semantic_families --sizes 100 1000 10000 --repeats 3
.venv/bin/python -m evals.analytics.semantic_history --reference-db .local/history.sqlite --output .local/semantic-families/fresh-verification
```

最后一条必须使用新的输出目录，且引用库有固定快照策略；脚本限制真实结果只写入 `.local`。真实库不在 CI／代码仓库内，因此真实端到端与性能为显式运行的验收命令，常规 CI 只运行确定性的单元、mock、质量及原有回归测试。

查询：`GET /v1/analytics/tasks`，再用返回的 task_id 调用 `GET /v1/analytics/preferences?task_id=...`；两者沿用原时间／项目／会话筛选。CLI `analytics --no-text` 仍计算这两族，只跳过向量表示。

## 完成度与下一步

代码接入、六个分析入口、模板核心字段、五类验证与文档已完成；词表和边界是保守的候选实现。真实质量、含糊任务切分、指代确认、多用户身份、未来生效日期和并发容量仍待完成。优先补齐 origin、任务关联来源和 project_id，再建立独立人工标注集；之后才决定是否引入语义模型。

分支通过 PR 交给 `yhyfhgs` 决定合并；技术测试通过不代表 Codex review、团队语义验收或 main 发布已经完成。

本轮 Codex review 的两条意见已采纳：全局范围改用语句纳入版本解析；跨会话任务消息按可用时间归并并保持各会话原生 seq，增加两条回归测试。最新评审状态以 PR #13 的当前 head 为准。

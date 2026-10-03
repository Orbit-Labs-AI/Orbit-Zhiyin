# UI 分析功能与端到端验收

实际分布统计、词频、短语、共现、相似会话、两组对比和默认持久化历史见[统计分析与完整分析记录](statistics-history.md)。

这份文档面向后端、数据和 UI 开发者，说明八个分析族怎样组合成可展示的结果，以及怎样用构造记录和开发者本地 session 验证整条链路。对应 Lite 与 Advance 的分析页面，不含推荐、安装与资源匹配。

**现在可以从原生 session 导入，生成工具占比、调用转移概率、情绪表达图表、会话轨迹与验收卡，并核对 API、JSON 和导出的一致性。** 检查通过表示这批记录通过所列验收，不表示所有来源、语义判断和未来数据都没有问题。

## 已实现的分析功能

每行说明一个 UI 功能；“需要证据”表示函数已实现，但来源缺少对应记录时应显示未知。

| 归属 | 功能与一句话说明 | 适用页面 |
| --- | --- | --- |
| Respond | 工具占比：按工具名称或类型统计调用次数与占比，同时列出成功、失败和未知状态。 | 两版概览、工具 |
| Respond | 下一调用概率：统计同一会话内筛选后保留的相邻调用，给出每条转移的次数、条件分母和证据。 | 两版工具矩阵 |
| Respond | 调用级下钻：让每个有可确认后继的调用都能查到后继调用 ID、类型和对应转移概率。 | Advance 工具明细、轨迹 |
| Respond | 失败恢复链：连接已确认的失败与重试，区分恢复成功、仍失败和结果未知。 | 两版会话、工具 |
| Respond | 常见执行流程：按不同会话统计重复出现的三步工具类型组合，不让长会话重复增加支持数。 | Advance 项目工作流 |
| Respond | 文件语言使用：从调用记录中的文件操作统计语言，和提示语中提到的扩展名分开。 | Lite 语言排行；需要文件证据 |
| Task | 任务轨迹：将阶段、调用和关键时刻关联到明确任务或候选任务边界，并保留关联依据。 | 两版任务与轨迹 |
| Task | 任务与主题分布：展示现有领域、任务类型和可选文本聚类，并保留未分类样本与原始证据。 | 两版语义兴趣 |
| Instruction | 有效要求：展示明确任务在截止时点的有效要求、冲突和待确认候选。 | 两版任务详情 |
| Instruction 与 Outcome | 验收关联：把已确认且有任务与产物版本的标准对到验证结果，词面候选不自动变成验收标准。 | 两版会话结果；需要确认记录 |
| Preference | 有效偏好：展示当前筛选内的偏好及其适用任务、修改、撤销和冲突。 | 两版画像与任务详情 |
| Interaction | 人工介入：在轨迹中定位已确认的介入与反馈，并按真实轮次统计用户消息和 Agent 步骤。 | 两版会话、画像 |
| Cost-Time | 用量与时间：复用请求 Token、费用、时延及可靠执行区间，日志跨度不命名为人工工作时长。 | 两版概览、项目 |
| Cost-Time | 重试耗时：累计确认重试中有可靠执行端点的时间，缺失区间单列。 | 两版失败分析 |
| Cost-Time | 日周月趋势：按显示时区统计消息与调用活动，并提供星期与小时的联合热力图。 | 两版概览 |
| Cost-Time | 模型档位分组：按请求实际记录的模型与思考档位汇总用量，不用会话模型近似分摊。 | Advance 用量分析 |
| Cost-Time | 上期比较：用紧邻且等长的窗口比较会话、消息、调用和 Token，基期为零时不生成增长百分比。 | 两版趋势 |
| Outcome | 验收卡：分别列出验证运行、验收项、未匹配或版本不符的标准，以及首次通过前的验证次数。 | 两版会话、项目 |
| Subjective Outcome | 交付反馈：保留用户接受、拒绝、返工及无反馈的记录，与客观验收分开展示。 | 两版会话结果 |
| Subjective Outcome | 高频反馈语：统计规则识别到的明确反馈原句，并附实际出现过的消息 ID。 | 两版反馈语 |
| Subjective Outcome | 情绪表达趋势：绘制明确积极、消极、混合和中性表达的日趋势，未识别与截断消息保留未知。 | Advance 情绪；实验性 |
| Subjective Outcome 与 Respond | 反馈关联：比较有失败与无已观测失败会话的表达差异，每个会话一票，不作因果解释。 | 实验性；原 Advance「情绪前因」卡已删除，当前无页面使用 |
| 跨族 | 月度行为历史：按月展示消息、会话、规划要求和验证要求的证据；本产品不出四字母类型（`type_code=null`），类型由 `uiview.persona` 产生。 | 两版画像演变 |
| 跨族 | 会话检索：按标题或项目查找，并按最后活跃时间稳定排序和分页。 | 两版会话列表 |
| 跨族 | 双会话对比：用相同单位并排提供两个会话的轨迹、用量、时间和结果。 | Advance 对比 |
| 跨族 | 最后观测状态：用明确生命周期事件显示运行、等待、结束或未知，并保留最后记录时间。 | Advance 菜单栏、悬浮组件的数据基础 |
| 跨族 | 同源导出：从同一分析快照生成终端表格、JSON、CSV 和无需联网的 HTML 图表。 | 两版报告与开发验收 |

两版 Demo 仍使用各自的样例数据，本次没有改动 UI 源码；上述结果通过新 API 和报告命令供真实前端接入。

## 后端结构与维护约定

计算顺序是：**统一数据读取 → Scope 筛选 → 请求内索引 → 八族分析 → UI 组合 → 展示或导出**。

| 文件 | 职责 |
| --- | --- |
| [`analytics/context.py`](../../../packages/backend/src/tandem_backend/analytics/context.py) | 同一次请求只选择一次数据，为会话建立索引，并复用相同范围的执行族计算。 |
| [`analytics/semantic.py`](../../../packages/backend/src/tandem_backend/analytics/semantic.py) | 一次提取任务、偏好和要求，保留各自的证据与会话索引。 |
| [`analytics/service.py`](../../../packages/backend/src/tandem_backend/analytics/service.py) | 分别组装会话、项目和总体结果，保留旧字段与兼容入口。 |
| [`analytics/products/`](../../../packages/backend/src/tandem_backend/analytics/products/) | 按工具、反馈、轨迹、趋势和结果卡组合八族特征，独立于推荐。 |
| [`validate_analysis_products.py`](../../../evals/analytics/products.py) | 完成显式导入、数据完整性核验、组合检查、API 对照和报告导出。 |

新的公共函数有类型和简短 docstring；计算、组织与渲染分别维护。各族规则保持原目录归属，组合层复用它们，不复制另一套工具成功或验收判断。缓存只存在于单次请求，不会在导入新记录后误用旧结果。

原生调用顺序通过 `call_event_uid / result_event_uid` 回到事件 `seq`；没有可确认顺序时不猜测。这个补充修复了“L3 调用已有记录，但真实导入后的转移矩阵为空”的接线问题。

## API 与结果约定

| 入口 | 功能 |
| --- | --- |
| `GET /v1/analytics/products` | 返回一次完整的 UI 分析快照。 |
| `GET /v1/analytics/products/sessions` | 使用 `query`、`offset`、`limit` 检索并分页返回会话。 |
| `GET /v1/analytics/products/compare?first=…&second=…` | 对比当前筛选内的两个会话。 |

共用原有日期、项目、模型、档位、根会话、排除项与子代理筛选，新增可重复的 `source_ids`；例如 `source_ids=` 明确选择零个来源。`bucket=day|week|month` 控制活动分桶，`with_text=true` 才运行较昂贵的本地文本表示，`compare_previous=true` 要求同时给出 `from_ts / until_ts`。分析不调用远程模型。

结果版本为 `analysis-products-v1`，包含 `scope`、数据与规则版本、`analysis_digest` 和覆盖说明。主要数据段是 `overview / tools / activity / feedback / profile / profile_history / tasks / preferences / instruction / sessions / projects / model_effort / languages`。

比例等指标携带 `value / unit / effective_n / unknown_n / status / basis`：已观测的零保留为 0，无法计算为 null，部分样本与主动排除分开展示。JSON 禁止 NaN，HTML 转义来源文本，CSV 防止工具名被表格软件当作公式执行，导出文件权限为仅当前用户可读写。

工具矩阵位于 `tools.transitions.kind` 与 `.name`；`rows` 是聚合边，`next_calls` 是调用级后继，`terminal_counts` 是排序片段的终点。缺 seq 的会话不参与转移，有并列 seq 时在歧义处断开。比例描述筛选后的已观测相邻关系，不能解释成完整历史的因果执行关系。每条边最多内嵌 50 条示例证据，并明确标识截断；完整后继仍在 `next_calls`。

情绪平衡值为“积极消息数减消极消息数，再除以已识别消息数”；混合与明确中性均贡献 0，未知不进入分母。图表按真实日期间距绘制，缺失日期或未知值处断线。反馈关联至少每组 5 个可用会话才显示差值，这只是展示门槛，不是统计显著性结论。

## 一条命令跑构造案例

先在仓库根执行 `bash scripts/bootstrap.sh`，再运行：

```sh
uv run python scripts/validate_analysis_products.py \
  --synthetic --output .local/analysis-products-synthetic
```

脚本使用 Codex、Claude Code、DeepSeek Harness、pi、Hermes、OpenCode、Kimi 的虚构原生记录，确实经过导入器、L0/L1、统一数据库、分析和 API。每次使用独立数据目录，重复运行不叠加旧样本；数据目录记录在 `validation.json` 的 `data_home` 中。

输出包括：

- `validation.json`：来源选择、归档和记录哈希核验、组合断言、API 一致性、覆盖与检查结果。
- `report/analysis.json`：供 UI 接入或定位问题的完整分析快照。
- `report/report.txt`：终端可读的工具占比、转移概率、情绪表达和验收表。
- `report/report.html`：工具柱状图、调用转移表、情绪趋势及对应数字表，不需要外部资源。
- `report/tools.csv`：与 JSON 使用同一计数的工具表。

固定构造案例应产生 14 次调用、6 个相邻调用对；类型为 shell 的出边中，shell 占 50%，file.read 与 web.search 各占 25%。明确积极与消极表达各 1 条，“请翻译：我很满意”保留未知。脚本还验证图表不是靠空数组通过验收。

## 导入开发者本地记录

仅 `--source` 明确启用的目录会被读取，发现目录不等于授权导入；下面先取 Codex 最近两个文件：

```sh
uv run python scripts/validate_analysis_products.py \
  --source "codex=$HOME/.codex" --limit-files 2 \
  --output .local/analysis-products-local
```

多个来源可重复写 `--source`，例如 `claude_code=$HOME/.claude`、`dsh=$HOME/.dsh`、`pi=$HOME/.pi/agent`。`--limit-files` 按文件修改时间选择，并不等于会话数；默认每来源 3 个文件，设为 0 才读取全部。只选明确会话时，在单一来源后重复使用 `--file sessions/相对路径.jsonl`；来源自身仍由导入器白名单限制。

可以使用 `--from-ts / --until-ts` 限定分析时间，单位为 UTC 毫秒、上界不包含；这不会减少此前选择文件的归档范围。超出数据读取器 100,000 个事件限制时应缩小来源样本或时间窗口，不静默截掉后续记录。大样本默认不跑文本聚类，需要时加 `--with-text`。

真实来源只读，归档、数据库和报告只放本地忽略目录；脚本拒绝在 Git 未忽略的位置输出，也拒绝把数据目录放进来源目录。构造案例和真实记录不能使用同一个输出目录。若仓库工作区本身位于 `~/.codex/worktrees/`，导入 `~/.codex` 时应把输出指定到该来源之外的另一个本地忽略目录。

复用已有统一数据库生成报告，不再导入：

```sh
uv run tandem --home /实际的Orbit数据目录 analysis-report \
  --display-timezone Asia/Shanghai --output .local/ui-report
```

报告命令支持 `--source-id`、`--project-id`、`--model-id`、`--effort-raw`、`--root-session-uid`、`--exclude-session`、`--no-include-children`、`--bucket` 和 `--compare-previous`；多值筛选重复传参。

## 组合测试覆盖什么

模块测试位于 [`test_products.py`](../../../packages/backend/tests/analytics/test_products.py)，服务流程测试位于 [`test_analysis_products.py`](../../../tests/e2e/test_analysis_products.py)，已有各族测试继续运行。

| 场景 | 验证内容 |
| --- | --- |
| 工具占比与转移 | 用独立构造的 Read → Exec → Read → Exec 和另一会话验证 40%／60% 占比及跨会话不连边。 |
| 原生导入后的调用顺序 | 从真实形态 Codex 记录导入后确实产生转移对，避免只测手工补好 seq 的夹具。 |
| 歧义与缺失 | 并列或缺失序号不生成错误后继，未知状态不当成成功，空筛选和不可用数据分开。 |
| 情绪反例 | 区分直接表达、混合表达、提问、假设、翻译请求、非真人材料与未来消息。 |
| 要求与执行结果 | 同一明确任务经历失败、重试和通过时，验收卡记录首次通过次数，但不伪造用户接受。 |
| 来源与时间范围 | 同样的原生 session ID 来自不同根目录时保持隔离，上期为零时不产生无穷大增长率。 |
| API 与导出 | CLI、API 与 JSON 结果一致，HTML 转义来源内容，CSV 不执行工具名中的公式。 |
| 验收脚本本身 | 七种来源连续运行两次仍通过，故意破坏工具计数会让组合检查失败。 |

退出码 0 表示所选检查通过，1 表示导入诊断或组合检查不通过，2 表示路径、参数或运行错误；出现未解析记录、读取失败、API 或导出不一致时不会报告通过。

2026-10-02 的本地抽样实际导入了四种 Agent 的 8 个文件：2,520 条原始记录、7 个主会话、389 次工具调用、383 个相邻调用对，未解析记录为 0，API 与导出一致。21 条确认真人消息均没有命中严格的情绪表达规则，因此真实情绪图表保留未知；这不是用户没有情绪，也不是语义准确率结论。原文、会话身份、来源路径和完整报告未纳入仓库。

## 仍需数据或产品定义的能力

这些边界在结果中明确显示，不能用 Demo 常量补齐：

| 项目 | 当前处理与后续条件 |
| --- | --- |
| 四字母人格 | 本产品（`interaction_habits`、`profile_history`）只提供真实行为与月度证据，`type_code` 恒为 `null`。App 展示的 16 型由 `uiview.persona`（`uiview-persona-v0`，[profiling.md](profiling.md)）产生：1 个会话即出完整 4 字母，每轴按 50 分界，没有单位的轴按 50 计，只有四轴都无值才不揭晓；各轴分界是产品默认值，尚未经人群校准。 |
| 配置覆盖 | 已透传主干配置清单及扫描诊断；未扫描时 `configuration.status=unavailable`，分析请求不自行扫描用户目录。 |
| 上下文占用与额度 | `context_capacity.status=unavailable`；需来源给出明确占用、容量和额度窗口，不能由累计 Token 反推。 |
| 实时推送 | 已提供最后观测状态；连续采集与推送需 App 调用已有 ImportService watch 并刷新分析，尚未新增 SSE 订阅。 |
| 任意任务要求与成果符合度 | 有明确验收标准和产物版本时可核对；任意自然语言要求不能自动转成已确认验收。 |
| 长期偏好与人工纠错 | 当前仍限于本次筛选内的显式历史；窗口前背景补入、偏好冲突裁决、任务拆合与标签持久化需后续标注接口。 |
| 隐含情绪和复杂主题 | 只提供保守规则与可选本地文本表示；不声称理解隐含情绪，不把无名称文本簇解释为人格。 |

产品设计依据：[Lite 范围](../../design/lite-review.md)、[设计归属](../../design/README.md)、[画板索引](../../design/boards.md)。这份文档记录当前代码能提供什么；新增产品范围仍由三位成员共同确认。

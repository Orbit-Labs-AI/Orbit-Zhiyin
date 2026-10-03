# 推荐端 P0：先接收资源，再用证据匹配

本轮按《推荐端目录设计》建立统一的资源接收与推荐链路。原设计没有显式的 P0 清单，因此这里把 P0 解释为：资源尚未齐全时也能运行；团队补齐 JSON 后可以直接接入；推荐必须有瓶颈证据、兼容性判断和可解释排序。

当前只消费已有的非语义瓶颈诊断，不新增数据采集或依靠人格标签生成推荐。运行时不联网、不调用 LLM、不下载模型、不安装或执行资源。排序权重和瓶颈阈值是初始启发式，尚未证明能改善真实任务表现。

偏好排序和条件收益估计已接入同一推荐入口，具体对照与生成案例见[推荐测试报告](validation.md)。在仓库根执行 `bash scripts/test-recommend.sh` 可重跑测试和报告；公共资源评测目录在 `evals/recommendation/fixtures/reviewed-skills.json`，不自动替换全部抓取草稿。

## 两套推荐栈与 engine v2（App 主栈）

仓库里并存两套推荐栈，App 界面使用的是 **engine v2**；本文后续「算法与分数含义」等章节描述的是 **service 栈**。

| 栈 | 入口路由 | 代码 | 用途 |
| --- | --- | --- | --- |
| engine v2 | `GET /v1/recommendations`、`/v1/recommendations/{id}`、`/recompute`、`/runs`、`/v1/labels` 等（`services/routes_recommend.py`） | `runs.py` → `engine.build_slate` | App 各 surface 的卡片 |
| service | `GET/POST /v1/analytics/recommendations`（`api/routes.py`） | `service.recommend` | analytics 展示与 P0 验收 |

engine v2 流程：`recall/multi.recall_all`（`problems.build` 把信号与 SQL 事实提升为问题，Wilson 下界判定 active）→ 11 路召回 → 加权 RRF → `ranking/gates` 13 道门 → `ranking/rank.score` → `ranking/slate.select`（MMR + 配额）→ `narrate` 生成卡片。

召回路线（`recall/multi.py`）与 RRF 权重：

| 路线 | 内容 | 权重 |
| --- | --- | --- |
| `kb` | KB 规则按问题类型精确匹配 | 1.0 |
| `subtract` | 常驻上下文 / 未用组件的精简 | 1.0 |
| `template` | 谓词模板（验证缺口、纠偏螺旋、混合会话） | 0.8 |
| `catalog` | `packages/catalog` 资源库（无 catalog.db 时用随包 legacy seed 的 BM25） | 0.7 |
| `model` | 模型与思考强度配置 | 0.6 |
| `hashed_lexical` | 512 维符号特征哈希余弦，**词面相似而非语义向量**，仅在 catalog E5 向量未就绪时启用 | 0.5 |
| `profile` / `feature` / `graph` | 画像匹配、画像 × 资源特征、已装项的搭配补集 | 0.4 |
| `generative` | 无现成方案时的 AI 草稿占位 | 0.3 |
| `generic` | <10 个会话时的冷启动通用规则 | 0.2 |

融合为加权 RRF：`Σ w_route / (k + rank)`，`k = 60` 取自 Cormack, Clarke & Büttcher（SIGIR 2009）。**各路权重未经校准**，只表达手写信任序；合成回放集太小，不能拟合权重。`recall_all(weights=, rrf_k=, hashed_threshold=)` 可覆盖权重、k 与 hashed 阈值（默认 0.15，同样未校准）。

排序（`ranking/rank.py`）：

- `value = (B · c · p · f)^(1/4)`：收益 B、置信 c（问题的 Wilson 下界）、生效率 p（Beta 先验 + 标签与效果追踪后验）、匹配度 f 的几何平均，仍在 [0, 1]；任一因子为 0 则为 0。
- `net = value / (1 + cost) − risk`，`risk ∈ {0.05, 0.25, 0.6}`，`cost = setup_minutes / 30 + context_tokens / 2000`。
- `priority = 100 · max(0, net) · personal · decay`：量纲是「100 分制的风险调整后期望价值指数」，不是分钟或概率；`personal` 限制在 [0.6, 1.4]，与 `store._weight` 共用常量。
- `utility ≤ 0` 的候选被 engine 标记为 `net_non_positive` 拦下，slate 里有 rank 的卡 utility 全部 > 0。12 个原回放 case 的 top1 priority 由旧公式的 0–2.02（其中 4 个为 0 且 net 为负）变为 15.1–58.0（中位约 22.9）。
- 收益 B：有问题证据时 `1 − exp(−每周次数 × 单次分钟 / 30)`；单次分钟未知时按事件频次（`benefit_basis = frequency_only`）；精简卡按 `1 − exp(−常驻 tokens / 2000)`，与添加 tokens 的成本同一换算（`units.CONTEXT_TOKENS_PER_UNIT`）。

节省比例（`narrate._save`）：只按当前范围的真实轨迹给百分比，不折算小时。分析层 `recommend_inputs` 的 `facts.trajectory`（`section._ledger`）沿用 App 的口径统计总 token（输入 + 缓存读写 + 输出）、协作时长（会话树事件间隔，每段封顶 5 分钟）与用户轮次，并把每个会话树的时间间隔与请求 token 分摊到具体工具调用：间隔归正在运行或等待模型读取结果的调用，请求的 token 归它读取的那些调用结果，都按人数均分；汇总成全部调用、失败调用、失败的测试 / 构建、只读审批等待四类的实测成本（审批只计等待时间、不计 token；Codex 取 permission request → decision 的间隔）。

| 问题类型 | 对应操作 | 每次的成本 |
| --- | --- | --- |
| `permission_friction` | 只读审批等待 | 实测等待，token 为 0 |
| `tool_env_failure` | 失败的工具调用 | 失败调用的平均 token 与时间 |
| `buggy_output`、`late_build_failure` | 失败的测试 / 构建 | 同上；没有计时数据时按平均工具调用近似 |
| `polling`、`repeated_workflow` | 工具调用（重复流程 × 步数） | 平均工具调用 |
| `resident_cost`、`installed_unused`（精简卡） | 常驻上下文 | 常驻 tokens × 对应 Agent 的请求数；时间未实测 |
| 其余（纠偏、重复说明、压缩、review 轮次等） | 返工轮次 | 一轮用户对话的平均 token 与时间 |

对应操作占比 = 观测窗口内的次数 × 每次成本 ÷ 总 token / 总协作时长（不超过该类操作的实测总量）；预计节省 = 占比 × 生效率（Beta 先验均值），区间取先验约 90% 范围，是情景边界而不是置信区间，也不扣除未知的配置成本。`ui.save` 给出 `time_pct`、`token_pct`、两者的区间、`share`（占比）、`effect`、`op`、`key` 与中文 `basis`；`ui.gain` 是同一组百分比的标题（如「省时 1.5% · 省 token 0%」），`ui.tok_pct` 是卡片自身常驻上下文占全部 token 的比例。同一问题的替代方案共用 `key`，界面合计时每个问题只取最大值。没有问题证据的 catalog / model 卡和还没有轨迹账本的旧快照显示「未估算」。

来源与兼容：catalog 条目只有 `verification` 为 `repository_and_skill_read` / `repository_and_source_read` 时视为已核验；资源库的 `agents` 列表只作提示，未给出支持矩阵时各 agent 为 unknown（门禁给 needs_context）。只有 Claude Code 与 Codex 有已知落地路径，其他 agent 的 `path_hint` 为空，卡片改为手动方案。

## 三层偏好与收益输入

`POST /v1/analytics/recommendations` 的 `context.preferences` 接受显式偏好；`state.py` 同时复用 analytics 的偏好历史解析器。作用域优先级为 `task > project > global`，同范围内为本次请求 > 显式偏好历史。Instruction 的历史要求只作为证据，不进入有效偏好；当前任务的明确覆盖通过 `context.preferences` 提供。撤销、修改、生效时间和冲突沿用 analytics 语义。多个值冲突时不任选其一，也不回退到低范围值；根会话有多个未选定任务时不应用某一个任务的偏好。

```json
{
  "family": "skills",
  "context": {
    "agent": "codex",
    "preferences": [
      {"scope": "global", "dimension": "capability", "value": "retry_control"},
      {"scope": "project", "target_id": "实际项目 ID", "dimension": "tool", "value": "pytest"},
      {"scope": "task", "target_id": "实际解析任务 ID", "dimension": "task_type", "value": "debug"}
    ]
  }
}
```

维度为 `language`、`detail`、`format`、`tool`、`collaboration`、`task_type`、`capability`；`polarity` 为 `prefer` 或 `avoid`，默认 `prefer`。`global` 不带 target_id；项目和任务必须绑定解析后的规范 ID。`avoid` 是软排序偏好，严格禁止项通过已有 `denied_permissions` 等硬约束表达。

资源新增 `preference_support`，例如 `{"detail":["brief"],"tool":["pytest"]}`，只允许有内容依据的审核元数据；工具、能力、任务类型还分别复用 requirements.tools、capability.tags、target_task.tags。匹配、未知、明确不匹配分别取 1、0.5、0，每个维度等权，同一表达重复出现不增加权重。偏好只能调整已有瓶颈证据支持的候选；不能绕过兼容性、权限、已安装、来源或审核过滤。

收益输入位于 `context.benefit_scenarios`。资源、信号、快照、改善区间和 basis 必填；其余成本缺失时保留未知，字段如下：

| 字段 | 含义 |
| --- | --- |
| resource_id、signal_id、analysis_digest | 对应资源、观察信号和同一分析快照；过期或越界时拒绝估计 |
| reduction.low / high | 明确假设的改善比例，0–1；不是 effect_match 或 priority_score |
| repeated_windows | 预测重复观察窗口数，默认 1；不自动解释为天、周或任务数 |
| minutes_per_occurrence、tokens_per_occurrence | 每个观察事件的成本区间，low / high |
| setup_minutes、setup_tokens | 一次配置成本区间 |
| extra_minutes_per_window、extra_tokens_per_window | 每个预测窗口新增的运行和验证成本区间 |
| basis | 改善、成本和重复窗口的假设说明；不允许空白 |

当前从纠偏次数、同参数重试对数、明确工具失败数取基线事件数，不从比率推算事件数。其余规则尚未建立成本口径时返回不足。缺少单次成本时连毛节省也未知；缺少配置或运行成本时仅显示毛节省，净收益为 null；明确为零时必须显式填写 0。

`benefit_estimate` 按“事件数 × 窗口数 × 单次成本 × 改善比例 − 配置成本 − 窗口数 × 新增成本”计算分钟、Token 的上下限和回本窗口，保留负收益。未知依赖和适配条件随估计返回；多条规则／多个 Skill 不累加，避免对同一次失败重复记账。卡片的 `effect_status` 仍为 `unmeasured`，`evaluation_plan.observed_effect` 仍为 null，直到另有成对执行实验提供效果证据。

权重、收益假设和真实资源内容是三种不同信息。报告展示规则行为和算术正确性，不把自设改善比例当作预测准确率。旧画像入口与 UI 原型尚未接入这些新增字段。

## 本轮完成的链路

```text
已筛选的 analytics + 同一快照的瓶颈诊断 + 显式环境 context
  → 按根会话建立 RecommendationState
  → 加载部分资源目录，规范化 item，校验 family 特有字段
  → 排除已知不可用资源
  → rules / sparse / effect / context 召回；有效偏好存在时增加 preferences 路线
  → RRF 融合
  → 公共候选特征与加权评分
  → MMR 多样性选择
  → 带证据、待确认条件和试验方法的推荐卡片
```

实现把 hard filter 提前到有数量上限的召回之前，避免不兼容资源挤掉可用候选。未知条件保留为待确认项；是否能试用还要看卡片状态。没有瓶颈证据时，关键词或环境匹配不能单独变成推荐。

## 目录职责

| 位置 | 职责 |
| --- | --- |
| `contracts.py` | 统一 item、envelope、state、context、candidate、result 和排序策略的数据合同 |
| `catalog.py` | 加载目录或传入列表、逐项诊断、冲突处理、稳定的目录 digest |
| `sources/normalize.py` | 统一格式验证、旧资源适配、未来目录包记录的草稿接收；不负责用户匹配 |
| `state.py` | 复用已有诊断，检查快照与会话边界，提取任务标签、瓶颈向量和上下文 |
| `families.py` | 七类资源的字段验证，把工具依赖和权限要求送入公共过滤器 |
| 七个 family 的 `dictionary.py` / `features.py` | 各类资源的专属字段与规范化入口 |
| `model_configs/benchmarks.py` | 模型、推理配置及 harness 对应的 benchmark observation 合同 |
| `recall/` | service 栈：规则、BM25、效果方向、环境召回与 RRF；engine v2 的 11 路召回（见上节）；`dense.py` 只报告 service 栈未配置 embedding |
| `features.py` | 计算跨 family 的任务、触发、效果方向、环境、证据、成本和风险特征 |
| `preferences.py` | 按范围及来源解析显式偏好，计算匹配解释并召回候选 |
| `benefit.py` | 从当前快照的事件计数与显式情景参数计算净收益区间 |
| `ranking/` | 已知不兼容过滤、透明评分、去重与 MMR |
| `explain.py` | 生成观察 → 触发 → 瓶颈 → 干预 → 预期改善的结构化解释 |
| `service.py` | 新推荐主入口；API 层不需要直接操作 BM25 或 family 实现 |
| `legacy.py` / `__init__.py` | 保留原画像推荐函数的调用合同 |

`analytics` 说明发生了什么，已有瓶颈诊断说明哪些观察达到问题门槛，本目录说明哪些干预值得试验。`state.py` 不会重新定义纠偏、工具失败或任务成功。

## 团队如何准备资源 JSON

目录使用七个固定文件名：`rules_prompts.json`、`skills.json`、`plugins.json`、`mcp.json`、`hooks.json`、`model_configs.json`、`workflows.json`。每个文件是 `recommendation-catalog-v1` envelope；`schema_version`、`family`、`items` 必须显式存在，文件名、envelope family、条目 family 必须一致。

每个 item 使用 `recommendation-item-v1`。公共字段包括 `identity`、`target_task`、`trigger`、`capability`、`expected_effect`、`requirements`、`compatibility`、`friction`、`risk_permission`、`evidence_quality`、`source`、`action`；各 family 的额外字段统一放在 `family_features`。可以先省略带默认值的字段接收为草稿，不要用猜测填补未知信息。

下面是可接收的 **skills 草稿文件示例**，不是已审核资源，也不是随包提供的新资源。保存到自己准备的目录中的 `skills.json` 后，接收层会记录 `draft`；它不会进入试用推荐。

```json
{
  "schema_version": "recommendation-catalog-v1",
  "family": "skills",
  "items": [
    {
      "schema_version": "recommendation-item-v1",
      "identity": {
        "id": "team-example-retry-diagnosis",
        "name": "待审核：重试前诊断流程"
      },
      "family": "skills",
      "target_task": {"text": "需要排查重复失败的开发任务", "tags": ["debugging"]},
      "trigger": {"rule_ids": ["identical_retries"]},
      "capability": {"text": "记录失败证据，再决定是否重试", "tags": ["retry_control"]},
      "expected_effect": {"targets": {"identical_retries": 1.0}, "status": "unmeasured"},
      "compatibility": {"agents": {"codex": "unknown"}},
      "evidence_quality": {"status": "draft", "score": 0.0},
      "source": {"origin": "local", "status": "draft"},
      "family_features": {},
      "action": {"limitations": ["等待实际资源、来源核验、依赖信息和试用步骤。"]}
    }
  ]
}
```

当前 `trigger.rule_ids` 和 `expected_effect.targets` 的受控键是：

| 键 | 对应的已确认瓶颈 |
| --- | --- |
| `correction_density` | 确认纠偏达到门槛 |
| `repeated_requirements` | 同任务、同对象要求重复强调 |
| `identical_retries` | 确认失败后的相同参数重试 |
| `tool_failures` | 同工具失败密度达到门槛 |
| `validation_failures` | 同任务、版本、范围的重复验证失败 |
| `acceptance_evidence_gap` | 明确验收集合中缺少匹配证据 |
| `context_pressure` | 高输入占比与确认重试或压缩记录共现 |

已有能力标签是 `scope_alignment`、`requirements_memory`、`debugging`、`retry_control`、`tool_preflight`、`verification`、`validation_visibility`、`context_budget`。能力标签应有资源内容支持，不能从 README 宣传语或 GitHub 人气直接推导。`expected_effect.targets` 的数值范围为 0–1，表达干预相关性的先验；`1.0` 不代表改善 100%，`status` 始终为 `unmeasured`。

草稿准备完成后，需要人工补齐和审核以下信息，才能成为试用候选：

1. 稳定的资源 ID、实际适配方式、工具/软件/其他资源依赖，以及需要的权限。
2. 能力证据与审核人：`evidence_quality.status=reviewed`、`reviewed_by` 和有依据的质量分数。
3. 来源快照：`source.status=verified` 与内容 SHA-256；GitHub 资源还需仓库 URL、相对文件路径、固定 commit SHA 和明确许可。建议同时保留 blob SHA、核验时间和核验方式，沿用旧种子的可追溯信息。
4. 可操作的 `action.setup_steps`、`preview`、`trial` 和限制说明。源码存在不代表已经测试兼容；需要改造的接入方式写 `adaptation_required`。
5. 只填写已知的 family 字段。hook 用 `event / condition / action`；模型配置用 `model / reasoning_effort / agent_harness`。缺少这些字段时会列为待补充条件，不应声称可以运行。

本地原创模板也需要内容摘要与能力审核，不能只把 `source.status` 改成 `verified` 代替实际审核。来源核验与能力审核均不等于真实效果已经测量。

### 接收规范与验证

加载器允许七个文件部分到齐，也支持 `items: []`。UTF-8 和 UTF-8 BOM 均可；单个文件最多 8 MB，单个 envelope 最多 10,000 项。它拒绝未知版本、重复 JSON 键、非有限数值、错误字段类型、不安全来源路径和未知受控规则键。

坏条目单独诊断，同文件其他合法条目继续接收；坏 envelope 或不可解析 JSON 按文件诊断。相同 `identity.id` 的所有冲突记录都排除，不按文件或输入顺序选择胜者。诊断只包含字段位置与错误类别，不回显字段中的原始输入内容。

统一接收层先检查公共合同；`service.py` 再检查对应 family 字段。例如 skills 的 `required_tools` 会并入公共工具依赖，MCP/plugin 的 `permissions` 会进入权限检查。[data/recommend/](../../../packages/backend/src/orbit_backend/data/recommend/) 中的七份 `*.schema.json` 由这些合同生成，供编辑器及资源提供方校验。

安装项目依赖后，在仓库根目录运行：

```sh
uv run python -m evals.recommendation.catalog /path/to/catalog --agent codex
```

脚本只读取指定目录的七个资源文件，不读取聊天历史、不联网。格式错误返回非零退出码；缺失、空文件内容列表、待审核条目通过接收检查，但会在输出中明确标记。`eligible` 也不等于全部环境条件已满足，还需查看 `pending_requirements`。

分析已授权的数据库时可显式接入该目录：

```sh
orbit --db .local/synthetic.sqlite analytics --no-text --recommendation-catalog /path/to/catalog --recommendation-agent codex --recommendation-family skills --output .local/recommendation-result.json
orbit --db .local/synthetic.sqlite serve --recommendation-catalog /path/to/catalog
```

`GET /v1/analytics/recommendations` 保留原参数并新增 `family`；同路径 `POST` 接收 `context`、`family`、`limit`，通过 context 明确工具清单、已安装资源与权限。项目、时间和根会话筛选仍使用既有 query 参数。目录路径由服务启动配置，HTTP 请求不能指定本地路径。

## 空目录、旧种子和未知值

随包的 `data/recommend/` 七个文件目前都是空 envelope，表示资源等待团队整理。它们没有伪装成已经收集完整的七类资源。

| 调用方式或状态 | 行为 |
| --- | --- |
| `load_catalog()` 或推荐入口默认参数 | 读取七个新文件，再适配原有 12 项已审核资源：5 个原创 prompt、7 个固定版本社区资源 |
| `include_legacy=False` | 默认目录只读取新文件；目前没有新条目 |
| 显式 `catalog_directory=...` | 只读取指定目录，不回退旧种子 |
| 显式 `catalog=[]` | 空目录；仍可返回诊断信号和门槛检查 |
| 文件缺失 / 空 envelope | 分别记录 `missing` / `empty`，其余 family 继续加载 |
| 合法但未审核条目 | 接收为 `draft`，过滤阶段不能成为试用候选 |
| 格式无效条目 | 输出诊断，不进入目录 |
| 已审核条目，但环境条件未知 | 可作为 `needs_context` 建议，列出条件；不声明已经适配或允许执行 |
| 已知不兼容、缺失依赖、权限不允许、已安装、来源撤回/不可用 | 排除，记录原因 |

`catalog` 与 `catalog_directory` 互斥。旧 `kind=prompt/skill/hook/agent` 分别映射到 `rules_prompts/skills/hooks/workflows`，`legacy_kind` 保留原卡片类型。旧 agent 是角色模板；旧 hook 是需要适配的示例，不补造可执行配置。

环境 context 中，`None` 表示未知，`[]` 表示已经确认的完整空清单。比如资源需要 pytest，`tools=None` 会产生 `tools:pytest` 待确认项；`tools=[]` 则表示明确没有该工具，会排除该资源。权限同理：未提供权限清单不等于全部允许。`denied_permissions` 始终表示明确禁止。

## Python 接入

使用已有合成夹具或获授权输入生成的 `analysis_result`；不要为了试推荐而读取本机个人聊天数据。下面假定 `analysis_result` 已由 `analytics.service.analyze_bundle` 生成，`path/to/prepared/catalog` 是团队准备的资源目录。

```python
from orbit_backend.recommend.catalog import load_catalog
from orbit_backend.recommend.service import recommend

catalog_directory = "path/to/prepared/catalog"
received = load_catalog(directory=catalog_directory)
print(received.diagnostics)

result = recommend(
    analysis_result,
    context={
        "agent": "codex",
        "os": "linux",
        "tools": None,
        "software": None,
        "permissions": None,
        "installed_resources": [],
    },
    catalog_directory=catalog_directory,
    family="skills",
    limit=5,
)
print(result["status"])
print(result["recommendations"])
```

新入口是 `orbit_backend.recommend.service.recommend`。`from orbit_backend.recommend import recommend` 保留旧画像接口，不要把两者的输入与返回类型混用。新入口也接受 `catalog=[RecommendationItem 或统一格式 dict]`、可选的同快照 `bottlenecks`、`RecommendationPolicy` 和 `RankingPolicy`。

如果传入 `bottlenecks`，其 `feature_digest`、`analysis_digest`、`scope` 必须匹配当前 analytics；信号证据必须属于对应根会话树。不同会话的样本不会合并来凑门槛。原始对话正文与 persona 标签不进入检索文本；解析后的显式 preference 通过独立路线和特征参与排序。

输出版本为 `recommendation-pipeline-v1`，保留 `signals`、`assessments`、`states`、`diagnostics`、`excluded_resources`、策略参数及输入/目录 digest。整体状态包括 `ready`、`no_matching_resources`、`insufficient_evidence`、`no_threshold_met`。`ready` 表示存在卡片，具体卡片仍可能是 `needs_context`，应检查 `recommendation_status`。

## 算法与分数含义

以下召回路线默认每路最多 50 项：

- `rules`：匹配已经成立的规则 ID 或能力标签，不重新判断原始特征阈值。
- `sparse`：无外部依赖的 BM25，英文技术名称与中文二元词片匹配；默认 `k1=1.2`、`b=0.75`。
- `effect`：瓶颈向量与资源效果方向向量的点积。每个根会话的同规则强度取 `severity × confidence` 的最大值。
- `context`：利用已知 Agent、OS、语言、框架和依赖匹配召回相关候选。
- `preferences`：存在有效偏好时启用，召回有明确匹配元数据的候选，避免其被其他路线的数量上限挤出。

RRF 只融合各路名次：`RRF(i) = Σ 1 / (60 + rank(i))`，名次从 1 开始。它不把 BM25 分数与规则分数直接相加；原始分数保留在卡片中供排查。service 栈各路线等权，RRF 特征按已启用路数的理论上限归一化（engine v2 为加权 RRF，见上文）。

公共评分的默认正向权重是：任务匹配 0.10、触发匹配 0.20、效果方向匹配 0.25、环境匹配 0.10、资源证据质量 0.20、RRF 匹配 0.15；有效偏好存在时增加偏好匹配 0.30。接入/运行成本罚项权重 0.10，风险罚项权重 0.15。

```text
base = max(0, (正向加权和 − 成本罚项 − 风险罚项) / 正向权重和)
score = clip(base × 瓶颈证据置信度 × 兼容系数, 0, 1)
```

只有匹配到有证据的 trigger 或效果方向时，`score` 才能为正。效果方向特征是点积除以当前瓶颈强度总和；成本特征为 `0.7 × setup_cost + 0.3 × runtime_cost`。兼容系数为 native/manual=1、adaptation_required=0.55、unknown=0.35；明确 unsupported 提前排除。service 栈未启用 embedding，候选特征里不提供语义相似度字段。

MMR 使用 `0.8 × score − 0.2 × 与已选项的最大相似度`；相似度是能力、正向效果键和 family 描述集合的 Jaccard 值。最终同资源 ID 只保留一项，每条瓶颈规则最多两项，数量上限为 1–20。相同输入使用稳定顺序，输入不会被算法修改。

卡片的 `priority_score=100 × score` 仅表示启发式试用优先级。它不是收益百分比、成功概率或 benchmark 提升。`effect_status=unmeasured`，`evaluation_plan.observed_effect=None`；试验需要固定任务输入、模型配置、产物版本和验收范围，同时统计新增提示、调用、Token 和时间成本，不能通过减少验证让指标变好。

## 来源适配与后续工作

`sources.normalize.legacy_item` 只适配原有已审核目录，保留固定 commit、文件路径和内容摘要。它把原有能力映射为规则方向先验，仍保留原能力交集条件，避免宽泛规则映射改变旧资源的推荐依据。

`sources.normalize.catalog_resource` 为 `packages/catalog` 中的 `orbit_catalog` 包提供显式接收边界：输入该包的 Resource 字典，仅把 `origin=curated` 的受控 feature 转成匹配字段。README/body、自动提取特征、人气和安装命令不成为能力真值；即使有 curated 标签，适配结果仍保持 draft，Agent 兼容性保持 unknown。调用方需显式选择这个 adapter，不会自动猜测其他 JSON 格式，接收适配仍独立于采集与索引的实现。上游包负责来源采集/存储；本包负责审核后资源与用户瓶颈的匹配。

后续按真实需求补充：

- 审核团队提供的七类资源，记录真实依赖、权限与来源快照；先以合成任务验证接入。
- 为新瓶颈增加受控 rule ID 与证据门槛，再扩展资源标签；不能只往 JSON 写一个新效果名称就默认算法已支持。
- 接入来源刷新、缓存陈旧状态和明确的重新审核流程，保持采集与推荐分离。
- `recall/dense.py` 只返回 disabled 状态；service 栈没有配置或调用 embedding backend。真正的 E5 向量在 `packages/catalog`，engine v2 在其未就绪时用 `hashed_lexical` 词面路线兜底。
- 使用获授权 benchmark 校准阈值、权重和试用收益；采纳/点击反馈不等于效果改善。模型 benchmark observation 也不能直接宣称对用户任务有效。
- 按需要增加 LLM rerank、自动 crawler、安装/回滚与效果反馈；这些均不属于当前 P0。

当前自动化验证只使用合成特征、合成目录和既有公开资源元数据。没有对本机个人聊天数据做端到端测试。

## 初始 P0 验证记录

下列为目录迁移前的历史结果；当前偏好／收益版本的命令和结果以[推荐测试报告](validation.md)为准。

- 全量 `pytest -q`：1,055 项通过；原有 Starlette/AnyIO 弃用警告 1 项。
- `ruff check src tests` 及两个推荐脚本检查通过，`git diff --check` 通过。
- `orbit demo`、`orbit evaluate` 和推荐演示脚本在临时目录中通过；显式空目录、Agent 和 family 命令行参数已验证。
- 离线构建 wheel 并在临时目录导入：七份接收 JSON、七份 Schema 均随包发布，默认旧资源适配及新 service 可用。
- 独立检查未发现 P0/P1 阻塞问题。上述检查不代表权重已校准或真实收益已得到验证。

PR #26 同步 main 的统一数据层后，API 默认保留 `CanonicalStore` 和 `home` 参数，并支持推荐目录配置；CLI 同时传递两个配置。Python 3.13 全量测试 1,068 项通过、1 项 connector staging 集成测试因本机缺少构建产物跳过；另补充 canonical 数据与显式空推荐目录的 GET/POST 联调回归。推荐演示、demo、evaluate、workspace 构建与资源打包检查通过，均使用合成数据。

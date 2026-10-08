# Recommendation 端目录设计

> 本页是 2026-10-01 至 10-03 的历史方案，文中的“当前”、TODO、测试数量和命令只对当时成立。现行入口：[文档导航](<../../../README.md>)。

> 目标分支：`feat/analytics-preference-task`
> 参考位置：`src/tandem_backend/analytics/`
>
> 设计目标：与现有 `analytics` 的组织方式保持一致——**feature family / recommendation family 分包，公共计算与 orchestration 放在顶层**；同时避免把资源抓取、特征表示、召回算法和业务 API 混在一起。

---

## 1. 从现有代码得到的约束

当前 `analytics/` 已经体现出比较清晰的组织原则：

- `task/`、`preference/` 是独立 feature family；
- family 内部再拆：
  - `dictionary.py`：词典/规范定义；
  - `features.py`：特征提取；
  - `rules.py`：显式规则；
  - `taxonomy.py`：分类体系；
  - `representation.py`：向量化、聚类等表示；
- `analytics/common.py`、`inputs.py`、`service.py` 负责跨 family 的公共能力和 orchestration；
- 根目录已有：
  - `catalog.py`：推荐资源的离线 seed 与远端校验元数据；
  - `bottlenecks.py`：从观测信号连接到问题/瓶颈；
  - `feedback.py`：用户反馈信号；
  - `evaluation.py` / `pipeline_eval.py`：评估。

因此推荐端不应该重新实现 analytics 或 bottleneck diagnosis，而应该把它们作为输入。

---

# 2. 推荐目录结构

建议新增：

```text
src/tandem_backend/
├── analytics/
│   └── ...
│
├── recommend/
│   ├── __init__.py
│   ├── contracts.py
│   ├── state.py
│   ├── catalog.py
│   ├── features.py
│   ├── service.py
│   ├── explain.py
│   │
│   ├── rules_prompts/
│   │   ├── __init__.py
│   │   ├── dictionary.py
│   │   ├── features.py
│   │   └── representation.py
│   │
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── dictionary.py
│   │   ├── features.py
│   │   └── representation.py
│   │
│   ├── plugins/
│   │   ├── __init__.py
│   │   ├── dictionary.py
│   │   ├── features.py
│   │   └── representation.py
│   │
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── dictionary.py
│   │   ├── features.py
│   │   └── representation.py
│   │
│   ├── hooks/
│   │   ├── __init__.py
│   │   ├── dictionary.py
│   │   ├── features.py
│   │   └── representation.py
│   │
│   ├── model_configs/
│   │   ├── __init__.py
│   │   ├── dictionary.py
│   │   ├── benchmarks.py
│   │   ├── features.py
│   │   └── representation.py
│   │
│   ├── workflows/
│   │   ├── __init__.py
│   │   ├── dictionary.py
│   │   ├── features.py
│   │   └── representation.py
│   │
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── github.py
│   │   ├── registry.py
│   │   ├── benchmark.py
│   │   ├── normalize.py
│   │   └── cache.py
│   │
│   ├── recall/
│   │   ├── __init__.py
│   │   ├── rules.py
│   │   ├── sparse.py
│   │   ├── dense.py
│   │   ├── effect.py
│   │   ├── context.py
│   │   └── fusion.py
│   │
│   └── ranking/
│       ├── __init__.py
│       ├── filters.py
│       ├── score.py
│       ├── diversity.py
│       └── rerank.py
│
├── catalog.py          # MVP 期间保留为 compatibility shim
├── bottlenecks.py
├── feedback.py
└── data/
    └── recommend/
        ├── rules_prompts.json
        ├── skills.json
        ├── plugins.json
        ├── mcp.json
        ├── hooks.json
        ├── model_configs.json
        └── workflows.json
```

---

# 3. 顶层 recommend 模块

## `contracts.py`

定义整个推荐系统统一的数据 contract，避免七类资源各自长成完全不同的数据结构。

核心对象建议至少包括：

```python
RecommendationItem
RecommendationState
Candidate
RecommendationResult
Evidence
SourceMetadata
```

其中 `RecommendationItem` 的公共字段建议固定为：

```text
identity
family
target_task
trigger
capability
expected_effect
requirements
compatibility
friction
risk_permission
evidence_quality
source
```

最重要的是：

- `trigger`：什么用户状态下应该推荐；
- `expected_effect`：预计改善哪些 bottleneck；
- `requirements / compatibility`：能不能在当前环境中工作；
- `friction / risk_permission`：推荐成本和副作用。

七类推荐资源只增加自己的特有字段，不改变这套公共 contract。

---

## `state.py`

把 analytics 侧的高维 feature 转成推荐算法真正消费的 `RecommendationState`。

输入主要来自：

```text
analytics task features
analytics preference features
workflow / interaction / outcome / cost features
bottlenecks.py
当前 agent / model / tool / project context
```

输出建议包括：

```text
task_state
workflow_state
interaction_state
outcome_state
cost_state
preference_state
context_state
bottleneck_vector

task_text
problem_text
desired_effect_text
```

这里**不要只读 persona / UI 画像**。

推荐主路径仍然是：

```text
raw analytics feature
        +
bottleneck
        +
context
        ↓
RecommendationState
```

persona 只能作为轻量 rerank feature。

---

## `catalog.py`

统一加载七类推荐资源，并返回标准化后的 `RecommendationItem`。

建议后续把目前根目录 `tandem_backend/catalog.py` 的逻辑迁入这里：

```text
offline seed
+
optional remote verification metadata
+
family normalization
        ↓
unified catalog
```

MVP 期间可以保留旧文件：

```python
# tandem_backend/catalog.py
from .recommend.catalog import resources, skills
```

这样不破坏现有调用方。

---

## `features.py`

存放**跨推荐 family 的公共推荐特征**，不要放具体召回算法。

例如：

```text
task_match_features
trigger_match_features
effect_match_features
context_match_features
compatibility_features
friction_features
risk_features
evidence_features
```

最后形成统一的 candidate feature vector：

```text
[
    task_match,
    trigger_match,
    semantic_match,
    effect_match,
    context_match,
    evidence_quality,
    friction,
    risk,
]
```

供 ranking 使用。

---

## `service.py`

整个推荐 pipeline 的唯一主要入口。

建议接口类似：

```python
recommend(
    analytics_result,
    bottlenecks,
    context,
    limit=5,
)
```

内部 orchestration：

```text
build RecommendationState
        ↓
load catalog
        ↓
multi-route recall
        ↓
RRF fusion
        ↓
hard filtering
        ↓
feature scoring
        ↓
diversity
        ↓
optional rerank
        ↓
explanation
```

API 层只调用这里，不直接依赖 BM25 / embedding / family 内部实现。

---

## `explain.py`

专门生成“为什么推荐给你”的结构化解释。

尽量先 deterministic：

```text
观察到了什么 feature
→ 激活了什么 trigger
→ 对应什么 bottleneck
→ 推荐项提供什么 intervention
→ 预计改善什么
```

例如：

```json
{
  "reason": "frequent_manual_test_after_edit",
  "observed": {
    "manual_test_rate": 0.84,
    "pytest_detected": true
  },
  "trigger": "repeated manual verification",
  "expected_effect": ["manual_actions_down", "verification_up"]
}
```

LLM 可以把结构化 reason 转成自然语言，但不应该凭空产生推荐依据。

---

# 4. 七个 recommendation family

七个 family 都尽量遵循相同内部结构：

```text
dictionary.py
features.py
representation.py
```

这样和 `analytics/task/`、`analytics/preference/` 的风格一致。

---

## `rules_prompts/`

对应：

```text
Rules
Prompts
Persistent instructions
Project instructions
```

特有 feature：

```text
scope
instruction_type
positive_constraint
negative_constraint
persistence
token_overhead
target_behavior
```

典型 trigger：

```text
重复提出相同约束
反复纠正格式
长期稳定表达偏好
```

---

## `skills/`

表示可复用的 agent workflow / skill。

特有 feature：

```text
invocation_condition
workflow_steps
inputs
outputs
required_tools
scripts
assets
side_effect
```

典型 trigger：

```text
相似多步骤任务重复出现
用户反复解释同一套执行流程
固定任务需要跨工具协作
```

---

## `plugins/`

表示较高层的 capability bundle。

特有 feature：

```text
included_skills
included_mcp
included_hooks
bundle_coverage
dependencies
installation_cost
permissions
```

Plugin 很可能覆盖多个 capability，因此需要比 Skill 更强调 dependency graph 和 bundle overlap。

---

## `mcp/`

表示外部软件 / service / data source 的接入能力。

特有 feature：

```text
service
tool_list
read_actions
write_actions
auth_type
permissions
local_or_remote
rate_limit
```

典型 trigger：

```text
用户频繁在 agent 与 GitHub / Drive / Slack 等外部服务之间 copy-paste
任务需要 agent 当前无法直接访问的数据或动作
```

---

## `hooks/`

建议直接建模为：

```text
(event, condition, action)
```

特有 feature：

```text
event
condition
action
pre_or_post
blocking
deterministic_or_prompt
runtime_overhead
failure_behavior
```

典型 trigger：

```text
固定动作总是在某事件之后手动执行
例如 edit → pytest
commit → lint
stop → verification
```

---

## `model_configs/`

注意推荐单位不是单独的 model，而是：

```text
(model, thinking/reasoning config, harness)
```

特有 feature：

```text
model
reasoning_effort
agent_harness

coding_score
reasoning_score
research_score
long_horizon_score
tool_use_score

latency
cost
token_usage
context_window
benchmark_source
benchmark_date
```

典型 trigger：

```text
简单任务成本过高
复杂任务反复失败
长任务中断
context 不够
```

---

## `workflows/`

表示完整的人机/agent 协作经验。

特有 feature：

```text
steps
DAG
roles
tools
checkpoints
human_in_loop
failure_recovery
entry_condition
exit_condition
```

Workflow 不一定是“可安装资源”，也可以是推荐给用户的最佳实践模板。

典型 trigger：

```text
单点 Skill/Hook 无法解决的跨阶段问题
任务存在明显重复的人机 handoff
长链路任务缺少 checkpoint / recovery
```

---

# 5. `sources/`：推荐资源从哪里来

这一层只负责**获取与规范化候选资源**，不参与用户匹配。

## `github.py`

获取 GitHub 上的：

```text
skills
hooks
MCP servers
plugins
workflow templates
```

只保存来源内容和 source metadata，不直接信任仓库描述形成 capability truth。

---

## `registry.py`

处理结构化 registry：

```text
MCP Registry
Plugin directories
Skill directories
```

把不同 registry 的字段转换到统一 source schema。

---

## `benchmark.py`

负责 model + thinking benchmark 数据。

输出原始 benchmark observation，例如：

```text
model
reasoning_effort
benchmark
score
cost
latency
date
source
```

具体 feature aggregation 放到：

```text
model_configs/features.py
```

---

## `normalize.py`

把各种外部来源先转换成 family-specific intermediate record，再交给各 family 的 `features.py`。

不要让 GitHub README 原文直接进入推荐逻辑。

---

## `cache.py`

负责：

```text
source cache
verified sha
fetch time
staleness
source status
```

可以复用现有 `catalog.py` 已经存在的校验思想。

---

# 6. `recall/`：多路召回

召回只回答：

> 哪些 candidate 值得进入下一阶段？

不负责最终排序。

---

## `rules.py`

确定性高 precision 召回。

例如：

```text
pytest_detected
AND manual_test_rate > threshold
→ retrieve testing hooks
```

MVP 必做。

---

## `sparse.py`

BM25 / FTS 召回。

适合：

```text
pytest
GitHub
React
Playwright
Notion
Slack
LaTeX
```

这些技术实体和精确关键词。

MVP 必做。

---

## `dense.py`

embedding semantic recall。

至少建议区分：

```text
task embedding
trigger embedding
capability embedding
```

不要把整个 item 压成一个 embedding。

匹配：

```text
user.task_text      ↔ item.target_task
user.problem_text   ↔ item.trigger
user.desired_effect ↔ item.capability
```

MVP 可以只做一个简单本地/远端 embedding backend，但 schema 先支持三路。

---

## `effect.py`

实现：

```text
bottleneck → expected effect
```

如果用户瓶颈向量为：

\[
b_u
\]

item 的 improvement vector 为：

\[
g_i
\]

则最简单可以：

\[
S_{\mathrm{effect}} = b_u^\top g_i
\]

这是推荐系统区别于普通 semantic search 的关键一路。

---

## `context.py`

按：

```text
agent
model
OS
language
framework
repository
tool availability
installed resources
```

召回上下文相关候选。

注意这一路与后面的 hard filter 不同：

- context recall：优先找相关资源；
- hard filter：删除明确不可用资源。

---

## `fusion.py`

融合各路召回。

MVP 建议使用 RRF：

\[
S_{\mathrm{RRF}}(i)
=
\sum_m \frac{w_m}{k + rank_m(i)}
\]

原因：

```text
无需训练
无需统一 BM25 / cosine / rule 的 score scale
容易调试
容易解释
```

---

# 7. `ranking/`：候选排序

## `filters.py`

hard compatibility filtering：

```text
agent incompatibility
OS incompatibility
missing required software
permission violation
deprecated/unavailable
already installed
duplicate
```

明确不可用的候选应该在 scoring 前删除。

---

## `score.py`

对融合后的 candidate 计算统一结构化 score。

MVP：

\[
S_i =
w_t S_{task}
+w_g S_{trigger}
+w_e S_{effect}
+w_c S_{context}
+w_q S_{evidence}
-w_f C_{friction}
-w_r C_{risk}
\]

这里消费 `recommend/features.py` 产生的公共 feature vector。

---

## `diversity.py`

防止 Top-K 全部推荐高度重复的东西。

MVP 可以使用 MMR：

\[
MMR(i)
=
\lambda S_i
-
(1-\lambda)\max_{j\in selected} sim(i,j)
\]

例如避免最后出现：

```text
pytest hook A
pytest hook B
pytest hook C
testing skill A
testing skill B
```

而变成：

```text
pytest hook
GitHub MCP
debugging skill
model routing rule
verification workflow
```

---

## `rerank.py`

可选 LLM reranker。

只处理 Top-N candidate，不参与全 catalog recall。

输入：

```text
RecommendationState
Top-N candidates
structured scores
```

输出：

```text
reranked candidate IDs
rerank reason
```

MVP 可以先不做，或者只作为 feature flag。

---

# 8. 推荐数据目录

建议不要继续把所有类型塞进当前单个：

```text
data/skills.json
```

逐步迁移为：

```text
data/recommend/
├── rules_prompts.json
├── skills.json
├── plugins.json
├── mcp.json
├── hooks.json
├── model_configs.json
└── workflows.json
```

每个文件里的 item 都先遵守 `RecommendationItem` 的公共 schema，再加入 family-specific 字段。

这样以后从 GitHub / registry refresh 时，也可以按 family 更新。

---

# 9. 推荐系统完整数据流

```text
                    analytics/
                       │
                       │ raw feature families
                       ▼
                recommend/state.py
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
 task/context      bottleneck      preference
        │              │              │
        └──────────────┼──────────────┘
                       ▼
              RecommendationState
                       │
                       │
             ┌─────────┴─────────┐
             │                   │
             ▼                   ▼
      recommend/catalog      recommend/recall
             │                   │
     RecommendationItem           │
             │                   │
             └─────────┬─────────┘
                       ▼
                 multi-route
                    recall
                       │
                       ▼
                     RRF
                       │
                       ▼
                hard filtering
                       │
                       ▼
               feature scoring
                       │
                       ▼
                  MMR diversity
                       │
                       ▼
              optional LLM rerank
                       │
                       ▼
                 explanation
                       │
                       ▼
               Top-K recommendation
```

---

# 10. 48h MVP 建议真正实现的文件

完整目录可以先建好，但不要全部实现。

第一版建议优先：

```text
recommend/
├── contracts.py
├── state.py
├── catalog.py
├── features.py
├── service.py
├── explain.py
│
├── hooks/
│   ├── dictionary.py
│   └── features.py
├── skills/
│   ├── dictionary.py
│   └── features.py
├── mcp/
│   ├── dictionary.py
│   └── features.py
├── model_configs/
│   ├── dictionary.py
│   └── features.py
│
├── recall/
│   ├── rules.py
│   ├── sparse.py
│   ├── dense.py
│   ├── effect.py
│   └── fusion.py
│
└── ranking/
    ├── filters.py
    ├── score.py
    └── diversity.py
```

第一版甚至可以暂缓：

```text
plugins/
rules_prompts/
workflows/
sources/ 的全自动互联网 crawler
LLM rerank
```

但 schema 和目录先留好。

---

# 11. 最关键的代码边界

整个系统要保持下面四层不混：

```text
analytics
= 用户实际上发生了什么

bottleneck
= 哪些 observed feature 构成问题

recommendation item features
= 某个 intervention 在什么情况下有效、会改变什么

matching
= 当前 bottleneck 与 intervention 是否匹配
```

因此不要出现这种代码：

```python
if persona == "Verifier":
    recommend("pytest-hook")
```

而应该是：

```text
analytics.manual_test_rate
analytics.task.python
context.pytest
        ↓
bottleneck.manual_verification
        ↓
hook.trigger_match
hook.expected_effect_match
        ↓
pytest-hook candidate
```

Persona 最多作为 ranking 的弱特征。

---

# 12. 推荐命名约定

建议统一：

```text
analytics/*
    Feature / Observation

recommend/*/features.py
    RecommendationItemFeature

recommend/state.py
    RecommendationState

recommend/recall/*
    RecallCandidate

recommend/ranking/*
    RankedCandidate

recommend/service.py
    RecommendationResult
```

这样可以避免项目后面同时出现很多含义不同的 `feature`、`score`、`result`。

---

## 一句话总结

推荐端最好形成两个正交维度：

```text
横向：七类 recommendation family
Rules / Skills / Plugins / MCP / Hooks / Model Config / Workflow

纵向：统一 recommendation pipeline
Source → Normalize → Item Feature → Recall → Fusion → Filter → Rank → Explain
```

其中 family 目录解决“**推荐的是什么**”，`recall/` 和 `ranking/` 解决“**为什么现在推荐它、如何从候选中选出来**”。这和现有 `analytics` 的 feature-family 组织方式能够自然对接，也为后续从规则系统升级到 learning-to-rank / contextual bandit 保留了接口。

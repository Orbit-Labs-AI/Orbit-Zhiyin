# 任务领域分类 v2

本模块把确认来自主会话真人的**当前请求**映射成可解释的多标签候选。它服务于概览、项目卡片、会话任务列表和画像中的任务分布，不参与四轴人格打分，不从词数推断兴趣强度或技能水平。

实现：[taxonomy.py](../../../packages/backend/src/tandem_backend/analytics/task/taxonomy.py)、[features.py](../../../packages/backend/src/tandem_backend/analytics/task/features.py)。自造中英语料：[task-domain-corpus-v2.json](../../../packages/backend/src/tandem_backend/data/task-domain-corpus-v2.json)。

## 层级与稳定标识

旧 `domain` 保留 `software / mathematics / data_analysis / writing / design / education` 六个 ID。新增 `domain_details`，细分为 27 类；父类 ID 不要求等于子类 ID 的前缀，前端应读取 `parent_id`。

| 父类 | 细分 ID 与中文标签 |
| --- | --- |
| software 软件工程 | `software.frontend` 前端开发；`software.backend_api` 后端与 API；`software.testing_debugging` 测试与调试；`software.devops` 部署与运维；`software.database` 数据库工程；`software.architecture` 架构与重构；`software.automation` 脚本与自动化；`software.security` 软件安全；`software.ai_engineering` AI 应用与代理 |
| data_analysis 数据工作 | `data.engineering` 数据获取与清洗；`data.statistics` 统计与数据分析；`data.visualization` 数据可视化；`data.machine_learning` 机器学习与特征工程 |
| writing 写作与文档 | `writing.technical` 技术文档；`writing.research` 研究与学术写作；`writing.content` 内容与通用报告；`writing.translation` 翻译与本地化 |
| design 设计 | `design.ux_ui` 界面与交互设计；`design.visual` 视觉与平面设计；`design.presentation` 演示与排版设计 |
| mathematics 数学 | `math.linear_algebra` 代数与线性代数；`math.calculus` 微积分与分析；`math.probability` 概率与统计理论；`math.discrete` 离散数学与优化理论 |
| education 教育与学习 | `education.lesson_design` 课程与教学设计；`education.tutoring` 知识讲解与辅导；`education.assessment` 作业与学业评测 |

一个任务可以同时包含前端与后端，也可以同时包含教学与数学。多标签计数之和可能大于任务数。旧六类维持粗粒度兼容，但会去除 `矩阵 → 数学`、`证明 → 数学` 等缺少上下文的误判，不能假设与 v1 数字完全一致。

## 处理规则

1. 沿用共同语义入口：只分析已确认的真人主会话消息，排除重放、平台包装、代码块、引用块与引号内文字。不读取助手文本补齐用户意图。
2. 在原有任务边界算法内按句处理。排除偏好陈述、否定请求、举例、条件假设、引用标题和明显的过去完成/状态陈述。转折后的肯定请求仍可以保留，例如“不要实现后端接口但请创建海报”。
3. 当前句需存在动作或请求标志才分类；无动作的裸词“React Vue API”不算当前任务。没有找到具体领域时保留未知，不强行分到“其他”。
4. 先匹配具体短语，再匹配带上下文的歧义词。例如“矩阵”需要代数、定理或特征值等数学锚点；“测试”需要软件上下文；React/Vue 需要组件或前端上下文；agent、RAG、MCP、prompt 等需要 AI/模型/工具上下文。英文词边界避免短词在其他单词内部命中。
5. 每个细分标签保留匹配术语、命中方式、上下文词、规则 ID、来源事件、session、时间、请求片段。父类取细分类父级与兼容粗分类的并集。
6. 任务聚合按 `task_id` 去重，标签在每个任务内只记一次；重复关键词、重复要求、消息长度不会提高权重。既有显式新任务、目标修订、原生跨会话身份与关闭规则不变。

`task_type` 另外补充 `analyze`、`design` 以及优化/部署动词，用于识别原来漏掉的统计分析与设计请求；仍然是候选动作标签。

## 输出与前端接入

示例为自造句“请测试这个后端函数”的部分输出：

```json
{
  "domain": ["software"],
  "taxonomy_version": "task-taxonomy-v2",
  "domain_details": [{
    "id": "software.testing_debugging",
    "label": "测试与调试",
    "parent_id": "software",
    "parent_label": "软件工程",
    "rule_id": "task-taxonomy-v2:software.testing_debugging",
    "taxonomy_version": "task-taxonomy-v2",
    "status": "candidate",
    "evidence": [{
      "event_uid": "synthetic-event",
      "session_uid": "synthetic-session",
      "matched_terms": ["测试"],
      "match_basis": "term_with_context",
      "context_term": "后端"
    }]
  }]
}
```

真实输出还会包含同句命中的后端与 API 标签。`label_evidence.domain_details[细分ID]` 保存同一组证据，供项目/会话筛选时逐条投影；筛选后应重建可见标签，不能复制整个跨会话任务的标签到每个项目。

分布 `summary.domain_details` 提供 `counts / effective_n / unknown_n / rates / labels / taxonomy_versions`：

\[
n_{known}=\sum_t 1[\text{任务 }t\text{ 至少有一个细分标签}],\qquad
p_k=\frac{\sum_t1[k\in labels(t)]}{n_{known}}.
\]

分母为至少有一个细分标签的任务数。`unknown_n` 单独显示；无已知任务时 `rates=null`，不是零。旧 records 没有 `domain_details` 时，仍可统计已有粗领域与任务个数，但细分覆盖计未知，不用标题反推缺失标签。词频、Token 数和工具失败率均不进入此分布权重。

## 语料与验证边界

语料包含 **112 条完全自造的中英文句子**：74 条开发/别名/反例样本，38 条组合与对抗表达样本。两组文本互不重复，每组均覆盖全部 27 个细分 ID；包含多领域并列、否定与肯定混合、过去完成、标题引用、转移矩阵、测试报告和重复关键词。另有独立代码测试覆盖语境证据、按任务去重、旧 records 缺字段、歧义短词与输入不变性。

后 38 条属于 heldout-style 组合回归，不是外部盲测：规则与样本由同一实现者编写，发现失败后会修复。**112/112 通过只表示这组语义回归通过，不能宣称真实人群准确率达到 100%。** 不存在通过语料频次训练出来的权重；语料用于审计、复现和后续扩充。

规则对省略宾语、长距离指代、复杂嵌套否定、领域隐喻以及同一段混合历史背景和请求仍可能漏判或误判。语言当前主要为中英；法律、医学、财务等专业细类未覆盖。需要扩展时先加自造正反例，再增加稳定 ID 或上下文别名，不把本地个人原文写入仓库。

运行（仓库根，Python 3.13）：

```sh
uv run pytest packages/backend/tests/analytics/test_task_taxonomy_v2.py packages/backend/tests/analytics/test_task.py packages/backend/tests/analytics/test_semantic_quality.py -q
uv run ruff check packages/backend/src/tandem_backend/analytics/task packages/backend/tests/analytics/test_task_taxonomy_v2.py
```

Windows 旧测试夹具未声明 UTF-8 时需设置 `PYTHONUTF8=1`。涉及完整 API 的测试请使用项目支持的 Linux/macOS 环境，Catalog 有 `fcntl` 依赖。

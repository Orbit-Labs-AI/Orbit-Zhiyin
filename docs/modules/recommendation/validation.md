# Recommend 偏好与收益测试报告

生成时间：2026-10-02T10:42:39.021080+00:00。本报告由 `evals.recommendation.validation` 实际调用推荐入口生成。

**案例 27/27 通过；自动测试状态：passed。**

## 结论与证据范围

已实现用户全局、项目、任务三层显式偏好影响 Skill 召回和排序，并接入 analytics 已解析的偏好历史。收益使用瓶颈实际计数与明确填写的成本／改善假设，分别给出分钟和 Token 的净收益区间。

这里的四个 Skill 来自已下载的公共仓库快照，内容与来源经过 Codex 阅读核对；会话、成本和改善幅度均为构造案例。测试只运行 recommend，不执行上游 Skill，因此不能把通过率或收益数字当作真实效果评测。

## 调试发现和修改

| 调试前 | 修改后 | 验证依据 |
| --- | --- | --- |
| preference_state 只有 ID，used_for_ranking 恒为 false | 复用历史解析器，加入显式三层偏好及独立召回路线 | 单变量对照、撤销／冲突／跨根会话测试 |
| 任意目录排序靠瓶颈、关键词和环境，无法表达当前偏好 | preference_support 声明支持；缺失标签保留 unknown | 排序解释包含维度、作用域、来源、命中与分数贡献 |
| 只有启发式 priority_score，effect_status=unmeasured | 新增 benefit_estimate；优先级和收益互不替代 | 手算区间、负收益、未知成本、零改善、过期信号 |
| 信号 ID 可能跨快照稳定，不能单独确认收益基线 | 情景同时绑定 analysis_digest，回本计算使用未舍入数值 | 同 ID 的旧快照拒绝；微小正收益仍能计算回本窗口 |
| 全量抓取 JSON 尚未审核，直接运行没有推荐 | 保持草稿过滤，另建四项内容审阅评测目录 | 核对 commit、blob 和解析正文 SHA-256 |

## 输入和资源

所有单变量对照使用同一构造会话：8 条确认意图消息中 3 条验收纠偏；10 次工具调用中 3 次失败，形成 2 对同参数重试；5 次模型请求合计 20,000 输入、500 输出 Token。所有环境依赖均明确给出。

```json
{
  "agent": "codex",
  "languages": [
    "python",
    "typescript"
  ],
  "tools": [
    "shell",
    "pytest",
    "playwright"
  ],
  "software": [
    "python",
    "pytest-cov",
    "chromium"
  ],
  "permissions": [
    "repository_read",
    "repository_write"
  ]
}
```

| Skill | 固定来源 | 元数据依据与限制 |
| --- | --- | --- |
| systematic-debugging | [源文件](https://github.com/openai/plugins/blob/5fd93af4cd0c623e020d0cc7e9ce178b4ac1f70f/plugins/superpowers/skills/systematic-debugging/SKILL.md) | 先复现失败并定位根因，再验证一个修复假设。 仅手工试用兼容，执行效果未测。 |
| test-driven-development | [源文件](https://github.com/openai/plugins/blob/5fd93af4cd0c623e020d0cc7e9ce178b4ac1f70f/plugins/superpowers/skills/test-driven-development/SKILL.md) | 用失败测试描述目标行为，再实现最小改动并执行回归。 仅手工试用兼容，执行效果未测。 |
| pytest-coverage | [源文件](https://github.com/github/awesome-copilot/blob/143a3d976b3c1603cc8932984d5e1f28501cb5fc/skills/pytest-coverage/SKILL.md) | 用 pytest-cov 找出未覆盖代码，并补充有实际断言的测试。 仅手工试用兼容，执行效果未测。 |
| webapp-testing | [源文件](https://github.com/anthropics/skills/blob/8a1541c4a3ffa5a20a5a91de0dcf3f0bab1d1ef4/skills/webapp-testing/SKILL.md) | 用 Python Playwright 检查本地 Web 应用的渲染状态和交互行为。 仅手工试用兼容，执行效果未测。 |

真实快照核对：

```json
{
  "status": "passed",
  "raw_count": 1033,
  "checks": [
    {
      "name": "systematic-debugging",
      "passed": true
    },
    {
      "name": "test-driven-development",
      "passed": true
    },
    {
      "name": "pytest-coverage",
      "passed": true
    },
    {
      "name": "webapp-testing",
      "passed": true
    }
  ],
  "unreviewed_export": {
    "count": 1033,
    "accepted": 1033,
    "recommended": 0,
    "status": "no_matching_resources"
  }
}
```

## 三类偏好的对照案例

每一对只更改偏好值；候选 Skill、瓶颈、模型与工具环境保持相同。首选断言在运行前固定，并不按输出倒填。

| 案例 | 作用域及偏好 | 首选 Skill | 优先级 | 结果 |
| --- | --- | --- | ---: | --- |
| global-retry_control | global / capability=retry_control | systematic-debugging | 36.83 | 通过 |
| global-verification | global / capability=verification | webapp-testing | 38.04 | 通过 |
| project-pytest | project / tool=pytest | pytest-coverage | 35.22 | 通过 |
| project-playwright | project / tool=playwright | webapp-testing | 38.06 | 通过 |
| task-debug | task / task_type=debug | systematic-debugging | 36.83 | 通过 |
| task-create | task / task_type=create | test-driven-development | 35.11 | 通过 |

优先级是启发式试用顺序，不是效果百分比。MMR 会照顾能力多样性，因此第二、第三张卡片不保证按原始优先级递减。偏好匹配权重默认为 0.30；无有效偏好时不加入该权重及路线。

## 具体输入和生成结果

### project-pytest

仅改变 project 的 tool=pytest

在上面的共同环境 context 中加入：

```json
{
  "preferences": [
    {
      "scope": "project",
      "target_id": "synthetic-project",
      "dimension": "tool",
      "value": "pytest"
    }
  ]
}
```

实际输出节选：

```json
{
  "name": "pytest-coverage",
  "recommendation_status": "trial",
  "priority_score": 35.22,
  "matched_preferences": [
    {
      "dimension": "tool",
      "value": "pytest",
      "polarity": "prefer",
      "scope": "project",
      "target_id": "synthetic-project",
      "origin": "request",
      "evidence": [],
      "outcome": "matched",
      "supported_values": [
        "pytest"
      ]
    }
  ],
  "observed_rules": [
    "correction_density"
  ],
  "net_minutes": null,
  "net_tokens": null,
  "effect_status": "unmeasured"
}
```

### task-create

仅改变 task 的 task_type=create

在上面的共同环境 context 中加入：

```json
{
  "preferences": [
    {
      "scope": "task",
      "target_id": "87c5ef20d45a7b828bd8f0fd",
      "dimension": "task_type",
      "value": "create"
    }
  ]
}
```

实际输出节选：

```json
{
  "name": "test-driven-development",
  "recommendation_status": "trial",
  "priority_score": 35.11,
  "matched_preferences": [
    {
      "dimension": "task_type",
      "value": "create",
      "polarity": "prefer",
      "scope": "task",
      "target_id": "87c5ef20d45a7b828bd8f0fd",
      "origin": "request",
      "evidence": [],
      "outcome": "matched",
      "supported_values": [
        "create",
        "modify"
      ]
    }
  ],
  "observed_rules": [
    "correction_density"
  ],
  "net_minutes": null,
  "net_tokens": null,
  "effect_status": "unmeasured"
}
```

### benefit-positive

10 个窗口的净时间与 Token 估计

在上面的共同环境 context 中加入：

```json
{
  "preferences": [
    {
      "dimension": "capability",
      "value": "retry_control"
    }
  ],
  "benefit_scenarios": [
    {
      "resource_id": "skill:github.com:1172963839:plugins/superpowers/skills/systematic-debugging/SKILL.md",
      "signal_id": "480be9ad5390770f97de176b",
      "repeated_windows": 10,
      "analysis_digest": "f94ed6c8eded78589928a442",
      "reduction": {
        "low": 0.25,
        "high": 0.5
      },
      "minutes_per_occurrence": {
        "low": 10,
        "high": 10
      },
      "setup_minutes": {
        "low": 5,
        "high": 10
      },
      "extra_minutes_per_window": {
        "low": 1,
        "high": 2
      },
      "tokens_per_occurrence": {
        "low": 1000,
        "high": 1000
      },
      "setup_tokens": {
        "low": 300,
        "high": 500
      },
      "extra_tokens_per_window": {
        "low": 100,
        "high": 200
      },
      "basis": "构造测试假设：未来 10 个窗口重复当前 2 次无效重试；每次 10 分钟 / 1000 Token；改善 25%–50%，尚无实测。"
    }
  ]
}
```

实际输出节选：

```json
{
  "name": "systematic-debugging",
  "recommendation_status": "trial",
  "priority_score": 36.83,
  "matched_preferences": [
    {
      "dimension": "capability",
      "value": "retry_control",
      "polarity": "prefer",
      "scope": "global",
      "target_id": null,
      "origin": "request",
      "evidence": [],
      "outcome": "matched",
      "supported_values": [
        "debugging",
        "retry_control"
      ]
    }
  ],
  "observed_rules": [
    "identical_retries",
    "tool_failures"
  ],
  "net_minutes": {
    "low": 20.0,
    "high": 85.0
  },
  "net_tokens": {
    "low": 2500.0,
    "high": 8700.0
  },
  "effect_status": "unmeasured"
}
```

## 收益计算和敏感性

净收益 = 观察到的事件数 × 预测窗口数 × 单次成本 × 改善比例 − 一次配置成本 − 窗口数 × 每窗口新增成本。下界使用最小节省减最大开销，上界相反。分钟和 Token 分开计算，不能相互抵消。

正例的 2 次重复重试来自构造会话中的真实计算；假设未来重复 10 个窗口、每次 10 分钟、改善 25%–50%，则毛节省为 50–100 分钟，扣除 15–30 分钟开销，净节省 **20–85 分钟**。Token 的同口径净节省为 **2,500–8,700**。这些上下限是情景边界，不是置信区间。

| 案例 | 改变条件 | 净时间收益 | 结果 |
| --- | --- | --- | --- |
| benefit-positive | 10 个窗口的净时间与 Token 估计 | {'low': 20.0, 'high': 85.0} | 通过 |
| benefit-short-horizon | 仅用一次时可能尚未收回配置开销 | {'low': -7.0, 'high': 4.0} | 通过 |
| benefit-negative | 开销过高时保留负收益 | {'low': -250.0, 'high': -200.0} | 通过 |
| benefit-unknown-cost | 缺少运行成本时不计算净收益 | 未知／不计算 | 通过 |
| benefit-zero-effect | 改善假设为零时不会输出正收益 | {'low': -30.0, 'high': -15.0} | 通过 |
| benefit-stale-signal | 过期或其他会话的信号不能借用当前计数 | 未知／不计算 | 通过 |
| benefit-stale-snapshot | 信号 ID 未变但快照变更时拒绝旧估计 | 未知／不计算 | 通过 |

同一失败可能同时触发工具失败和重复重试；不同 Skill 也可能处理同一事件，所以结果是可选情景，不提供可累加总收益。当前自动取数支持 correction_density、identical_retries、tool_failures；其他瓶颈缺少明确的事件成本口径时不估算。

## 多角度结果

| 案例 | 检查内容 | 实际状态 | 结果 |
| --- | --- | --- | --- |
| no-preferences | 去掉偏好，记录未个性化排序 | ready | 通过 |
| task-wins | 同一维度按 task > project > global 选择 | ready | 通过 |
| wrong-project | 其他项目的偏好不参与排序 | ready | 通过 |
| conflicting-preferences | 同范围冲突保留，不能任选一个 | ready | 通过 |
| unknown-style | 资源没有声明表达详略时返回 unknown | ready | 通过 |
| known-empty-tools | 已确认没有所需工具时排除候选 | no_matching_resources | 通过 |
| unknown-tools | 工具未知时保留待确认状态 | ready | 通过 |
| denied-write | 强偏好不能覆盖明确禁止的权限 | no_matching_resources | 通过 |
| already-installed | 已安装资源不重复推荐 | ready | 通过 |
| explicit-empty-catalog | 显式空目录不能回退到种子 | no_matching_resources | 通过 |
| unreviewed-drafts | 下载完成不等于完成能力审核 | no_matching_resources | 通过 |
| partial-invalid-catalog | 单个非法条目不拖垮其余资源 | ready | 通过 |
| preference-without-evidence | 只有偏好没有瓶颈时不声称需要干预 | no_threshold_met | 通过 |
| benefit-positive | 10 个窗口的净时间与 Token 估计 | ready | 通过 |
| benefit-short-horizon | 仅用一次时可能尚未收回配置开销 | ready | 通过 |
| benefit-negative | 开销过高时保留负收益 | ready | 通过 |
| benefit-unknown-cost | 缺少运行成本时不计算净收益 | ready | 通过 |
| benefit-zero-effect | 改善假设为零时不会输出正收益 | ready | 通过 |
| benefit-stale-signal | 过期或其他会话的信号不能借用当前计数 | ready | 通过 |
| benefit-stale-snapshot | 信号 ID 未变但快照变更时拒绝旧估计 | ready | 通过 |
| permutation-stability | 资源顺序反转不改变推荐 | ready | 通过 |

自动测试还覆盖历史修改／撤销、未来时间、引用文本、项目和任务隔离、API 422 校验、偏好候选不被召回上限挤出、输入不变、未知数据与布尔／NaN／无限值拒绝。

```json
{
  "status": "passed",
  "exit_code": 0,
  "tests": 330,
  "failures": 0,
  "errors": 0,
  "skipped": 0,
  "command": "python -m pytest -q packages/backend/tests/recommend tests/integration/test_recommend_validation.py"
}
```

## 性能观察

运行环境：Python 3.13.15，macOS-14.6.1-arm64-arm-64bit-Mach-O。

只计已生成 analytics 后的 recommend 调用；不含抓取、模型运行或 Skill 执行。1,000 项是四种元数据的构造复制，不能代表真实大目录质量或并发吞吐。

| 条目数 | 次数 | 中位耗时 ms | 最大耗时 ms |
| ---: | ---: | ---: | ---: |
| 4 | 20 | 5.67 | 6.21 |
| 1000 | 5 | 411.61 | 419.92 |

## 本地复现

在仓库根目录执行：

```bash
bash scripts/test-recommend.sh
```

脚本运行推荐模块和报告集成测试，随后生成 `.local/recommendation-validation/report.md`、`results.json`、`input-bundle.json`、`analysis.json`、`pytest.xml` 和 `pytest.log`。失败返回非零退出码。输出只含构造会话与公共资源元数据。

完整结果保留每个案例的 context、推荐卡片、原始分数贡献、召回路线、信号证据与收益参数；报告中的 JSON 是节选。初次使用先按仓库指南同步 Python 3.13 workspace。

API 使用 `POST /v1/analytics/recommendations`，请求中的 `context.preferences` 和 `context.benefit_scenarios` 与上述案例一致。收益情景的 signal_id 和 analysis_digest 必须取自同一分析快照；project/task target_id 必须对应解析后的规范 ID。

## 仍需验证

偏好能改变排序已经得到规则测试支持，但还没有独立人工标注的推荐相关性评估。收益具备可复算的估计接口，但改善比例和单位成本尚未从 A/B 实验校准。应固定任务、模型、输入和验收标准，成对执行基线／Skill，记录成功率、用时、Token、配置与验证开销，才能检验预测是否准确。

原始抓取结果仍以草稿为主；本报告只审阅四项作接入评测，不代表已完成全部目录审核。单根会话包含多个未选定任务时，任务偏好保持未解析。只凭偏好、没有瓶颈证据时不会输出干预推荐。UI 原型尚未接入本轮新增字段。

## 本次仓库级回归记录

2026-10-02 在当前工作区执行 `pnpm check`；以下是本次额外运行的仓库检查，单独运行推荐脚本不会重新执行这一整组检查。

| 检查 | 结果 |
| --- | --- |
| 全量 Python 测试 | 1,260 通过；1 项本地 E5 模型集成测试因未提供权重快照跳过 |
| TypeScript 连接器 | 35 项通过；typecheck 和 build 通过 |
| Python lint 与 data 格式 | 通过 |
| Lite / Advance 原型产物检查 | 通过 |
| 文档链接与目录归属 | 通过 |
| 三个 wheel 构建和仓库外安装验收 | 通过；demo、evaluate、API 导入及七类目录／Schema 完整性通过 |
| git diff --check | 通过 |
| Swift 测试 | 环境阻塞：CommandLineTools 无法确定 SDK PlatformPath，报 XCTest not available |

因此 `pnpm check` 整体退出码为 1，不能记为全绿。Swift 中断后的原型、文档与安装验收已逐项另行执行并通过；该限制没有通过跳过 Swift 检查掩盖。Python 另有既存 Starlette / AnyIO 弃用警告。完整日志与机器可读结果保存在本地报告目录的 `repository-check.log`、`repository-remaining-checks.log`、`repository-verification.json`。

## engine v2 离线回放（合成集，仅回归）

`uv run python -m evals.recommendation.replay` 跑 `evals/recommendation/fixtures/replay-cases.json`（v2，2026-10-03）。

- **标注来源**：旧版 `relevant` 按引擎同一张 `mechanism.REMEDY_PRIORITY` 优先序给出，`hit@3=1.0` 只是自证。v2 由 Claude（AI，audit-recommend 任务）按每个 case 的 `label_rationale` 独立重标，依据是解法是否直接作用于问题成因（机械强制 > 常驻约定 > 需手动触发），不读引擎输出；待 `yhyfhgs` 复核。`timeline-cases.json` 的采纳目标同样为手写虚构选择。
- **样本**：14 个正例（含 2 个 KB 规则被静音、只能由资源库条目满足的 catalog 路 case）与 5 个负例（0 会话、4 会话、30 个无摩擦会话、问题类型被静音、全部问题被静音），负例断言 `status` 与不出现问题驱动卡。
- **当前结果**：`hit_rate@3 = 1.0`、`ndcg@3 = 0.7652`、`negative_pass_rate = 1.0`（n_positive=14，n_negative=5）。`verify-kb-muted-catalog` 的 nDCG 只有 0.20：KB 被静音后排在前面的是模板工作流，资源库的自检 skill 被 `cap:problem` 挤掉，这是如实的弱项。
- **口径**：输出带 `disclaimer`（合成集，仅回归）。样本量小、全部虚构，指标只用于发现排序回退，不能说明对真实用户有效；测试里的阈值是上述实测值的回归下限，而不是质量目标。

# UI ↔ 后端对齐报告（第 4 轮）

> 状态：审计结论 + 本轮修复后估计 · 维护者 `yhyfhgs` · 2026-10-02 · 分支 `wip/yhyfhgs-backend-r4`

这份报告回答四个问题：前端每个 UI 元素有没有后端支撑；资料库（MCP / hooks / skills / plugins 等）够不够完整；推荐能不能做到 UI 的效果；分析能不能百分之百还原 UI。

**依据。** 五份审计表（推荐、资料库、分析 A1–A3、分析 A4–A6、外壳与流程）在本机 `.work/be-notes/parity-*.md`，不入库。审计对象是 `wip/yhyfhgs-backend-r4` @ `8902890`，全部用合成数据驱动真实 Gateway 测得，没有读取真实 `~/.claude` 或 `~/.codex`。之后合入了 12 个修复包，到 `5b380b6` 为止。「本轮后」一列按各包的修复报告和包规格计算，没有逐行复审；推荐的样例在合入后的分支上重新跑过一遍。UI 依据 Advance 原型、Lite 原型和 [feature-map.md](feature-map.md) §5；口径约定见 [backend-gap.md](../audits/backend-gap.md)。

## 1. 结论

**一句话：** 本轮修复之后，代码层面约 86% 的 UI 元素有了后端支撑（加权口径）。但现在还不能直接接 UI，原因有两个：一是分析适配层 `/v1/uiview/*` 已经写完，却还没挂到 Gateway 上；二是所有结论都只在合成数据上验证过。另有 15 个元素（占 4%）永远做不到 100%，UI 上必须改成「估计 / 数据不足 / 删除」。

**口径说明。**
- 状态：full（完整）、partial（部分）、missing（缺失）、in_progress（第 3 轮进行中）、frontend_only（纯前端）、not_derivable（日志推不出）。
- 加权 =（full + frontend_only + 0.5 × partial）÷ 行数。严格 =（full + frontend_only）÷ 行数。
- 下表单元格写作「审计时 → 本轮后」。
- 不同审计之间有少量重复行（如 A7-16、A1-25、OB/REV），各自独立计数。

| 页面 | 行数 | full | partial | missing | in_progress | frontend_only | not_derivable | 加权 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A7 推荐 + 各入口 | 32 | 5 → 24 | 20 → 5 | 4 → 0 | 2 | 0 | 1 | 47% → 83% |
| A8 资料库 | 40 | 8 → 29 | 23 → 6 | 4 → 0 | 1 | 0 | 4 | 49% → 80% |
| A1 概览 / A2 人格 / A3 会话 / Lite / 首启 / 揭晓 | 113 | 16 → 79 | 59 → 10 | 13 → 0 | 3 → 2 | 15 | 7 | 54% → 88% |
| A4 工具 / A5 项目 / A6 情绪 / Lite | 54 | 5 → 37 | 40 → 11 | 3 → 0 | 1 | 3 | 2 | 52% → 84% |
| 外壳与流程（A9、菜单栏、HUD、设置、安装、问答） | 155 | 45 → 85 | 45 → 13 | 9 → 1 | 10 | 45 | 1 | 73% → 88% |
| **合计** | **394** | **79 → 254**（20% → 64%） | **187 → 45**（47% → 11%） | **33 → 1** | **17 → 16** | **63**（16%） | **15**（4%） | **60% → 86%** |

严格口径从 36% 升到 80%。

**本轮后的数字有三个前提，接 UI 之前必须先解决：**
1. **接线没做（P0）。** Gateway 的路由元组里没有 `routes_uiview`、`routes_uiview_a4a6` 和 `uiview.routes_sessions`。`services/sections.py` 也没有 import `uiview.section`。因此 A1–A6 和 Lite 的 `/v1/uiview/*`（约 140 行）现在只能在测试里挂载调用，真实 Gateway 上访问不到。推荐还有 3 处路由改动没接：widget 默认只给 1 条、列表返回 `counts`、按 `problem_id` 过滤。
2. **只验证了合成数据。** 真实库里 `tool_call.status` 有 55.88% 是 unknown（见 feature-map 的实测）。真实数据上的表现要单独复测。
3. **外壳的 full 只代表形状对得上。** 菜单栏、小组件和面板里的推荐质量，取决于下面第 3 节说的那些问题。

**需要 `yhyfhgs` 决定的事：**
- A7 的排序口径：UI 按 `save`（h / 月）排，后端按 priority 排。两种做法，一是前端按 `ui.save.min_month` 重排，二是把 UI 文案改成「按优先级」。（2026-10-03 起改为按轨迹占比：UI 按 `ui.save.time_pct` 排，时间未实测时按 `token_pct`，见 [推荐引擎](../modules/recommendation/engine.md)。）
- 人格的权威定义：本轮新增的 `uiview-persona-v0` 用 UI 的四轴（D/S、P/I、M/F、V/T，Wilson 区间）；分析核心的 `collaboration-profile-v1` 用 C/D、E/P、A/V、S/O；第 3 轮的分享卡读的是后者。需要统一成一套。
- 是否从 UI 删除示例元素：全体用户对照、「同类型用户在用」、热门安装量、0–100 契合度分、−1~+1 情绪曲线。feature-map 已经决定删除一部分，其余见第 4 节。

## 2. 资料库完善度

**结论：** 骨架完整：检索、列表、facets、详情、本地条目、安装声明和模型库都已经有了。本轮补上了两个结构性空洞：全新安装时库里是 0 条，以及 MCP 几乎为空。剩下的问题在内容质量：hook 太薄；离线种子是用修复前的数据打的包；所有来源都拿不到安装量。

**本轮新增和修复：**
- 新增来源：`wshobson/agents`、`obra/superpowers`、`anthropics/claude-code`、`openai/skills`、`VoltAgent/awesome-claude-code-subagents`、`ComposioHQ/awesome-claude-skills`、Gemini CLI 扩展（审计实测 2082 条）、ClawHub（带下载量）、`orbit-kb`（Orbit 官方条目 25 条）。
- 新增离线种子快照 `library-seed.v1`：1277 条，1.3 MB（2026-10-03 用修复后的来源重打：hook 按插件目录命名、无 skill 内部规则、镜像去重；MCP 注册表实测 ≥ 24000 个），首启时导入，联网同步后退役。
- 新增后台定时刷新。
- HttpClient 对 5xx、429 和超时做退避重试。
- MCP 这类长分页源改为分段发布，中途失败时保留已经拉取的页。
- 排除 skill 目录内部的 `agents/`、`rules/` 文件，不再把它们当成独立条目。
- hook、`.mcp.json` 和 `plugin.json` 来源的条目现在可以安装。
- 许可证统一归一化成 SPDX。
- 详情增加 `scan`、`source_label`、`compat_label`，以及 `stars_scope` / `updated_scope`（标明是仓库级还是条目级）。
- 新增 `GET /v1/catalog/library`（A8 专用视图，带 `m` 和三段分项）和批量取卡接口。

| 类型 | 主要来源 | 审计实测条数（联网同步） | 首启种子条数 | 字段填充（审计实测） | 本轮后 / 剩余问题 |
| --- | --- | --- | --- | --- | --- |
| skill | anthropic-skills、claude-plugins、openai-plugins、awesome-copilot；新增 superpowers、openai/skills、Composio、ClawHub | 1037 | 400 | 简介 99.9%，作者 99.6%，许可 60%，README 59%，版本 4% | 可按固定 commit 安装；种子里许可只有 22%，README 16% |
| plugin | marketplace 497 条 + plugin.json 119 条；新增 claude-code、wshobson | 616 | 250 | 简介 89%，许可 15%，README 13%，可安装 83% | plugin.json 已补安装声明；Codex 插件的落点仍未映射 |
| subagent | 同上；新增 VoltAgent、wshobson | 279（含被误判的 skill 内部文件） | 150 | 许可 94%，README 94% | 来源已修；种子里仍有 5 条误判 |
| command | 各插件仓库 | 75 | 60 | 简介 85%，许可 79% | — |
| rule / workflow | 同上 | 333（其中 148 条是 skill 内部文件）/ 22 | 60 / 20 | 规则简介 54% | 来源已修；**种子里的 60 条规则仍是 `_sections`、`_template` 这类 skill 内部文件，简介 0%** |
| hook | claude-plugins、awesome-copilot；新增 orbit-kb 官方条目 5 条 | 17（其中 16 条都叫 "hooks"，且全部不可安装） | 16 | 简介 47% | 已解析 `install.hook`，并按插件目录命名；**种子里的 16 条仍然都叫 "hooks"**；UI 上的 retry-breaker、readonly-allowlist 等现在以官方条目入库 |
| mcp_server | MCP 官方注册表（实测 ≥ 5100 个） | 1（首次同步 294 秒后 http_500 失败） | 300 | 种子：简介 100%，`packages` 72%，安装量 0 | 入库时即生成 `install.mcp`；重试加分段发布后**没有联网复测**全量条数 |
| model / benchmark | models.dev、litellm、SWE-bench | 12823 / 324 | — | 完整 | full |

**所有类型共有的缺口：**
- `installs` 全部是 0，只有 ClawHub 提供下载量。
- stars 和更新时间都是仓库级，现已用 `*_scope` 标注。
- awesome-copilot 的条目只标了 copilot。
- 第三方条目的 friction 标签来自词典提取（权重 0.6），比人工标注弱。

## 3. 推荐能否达到 UI 效果

**结论：** 有证据的卡已经能达到 UI 卡片的形态，包括主数字、依据、追踪基线和落点。整页还达不到：在合成数据上，30 张卡里约有 13 张没有任何证据，是资料库里的填充卡；新增的知识库条目还会漏出模板变量。

**实测。** 在合入后的分支上跑真实 Gateway：导入 36 个未标注的合成 Codex 会话，扫描清单，再调用 `GET /v1/recommendations`。

| | 审计时 | 本轮后 |
| --- | --- | --- |
| 状态 | `no_matching` | `ready` |
| 卡片数 | 0 | 30 |
| problems | — | 12 个，全部 active：permission_friction、buggy_output、tool_env_failure、context_loss、missing_verification、installed_unused ×4、resident_cost ×2 |
| dims | — | rule 2、skill 11、hook 3、flow 13、agent 1、mcp 0、model 0 |

**卡片字段逐项对照：**

| UI 字段 | 后端字段 | 现状 | 差距 |
| --- | --- | --- | --- |
| 类型、图标、难度 L1–L4 | `ui.dim`、`ui.type`、`ui.lvl` | 由安装动作推出；教程类卡为 L4 | — |
| 主数字（h / 月） | `ui.save{min_month,label,low,high,basis}` | 有区间，并写明「（估计）」 | 无证据的卡显示「—」；排序仍按 priority（2026-10-03 起改为 `ui.save{time_pct,token_pct,share,effect,key,basis}`，按真实轨迹的占比） |
| 收益 | `ui.gain` | 月度数值，如「−34 次审批 / 月」 | 无证据的卡显示「0 个会话出现」（2026-10-03 起为百分比标题，如「省时 1.5% · 省 token 0%」） |
| 标题、原因 | `title`、`ui.why` | 中文自然 | **`{software}`、`{build_command}` 仍会漏出** |
| 依据 N 个会话（跳到 A3） | `ui.evq.session_uids` | 可以精确解析 | — |
| 兼容、落点 | `ui.compat`、`ui.target` | 按实际在用的 Agent 和项目名给出 | — |
| 主按钮 | `ui.primary` | 复制片段 / 一键应用 / 一键移除 / 预览并安装 / 查看教程 | — |
| 说明 Tab | `explain{reason,mechanism,capability,trial}` | 不再出现 RC 内部编号 | — |
| 预览、教程 | `ui.file`（逐行 `+` / `ai` 标记）、`ui.steps`、`ui.commands` | 知识库卡有内容 | 大多数卡 `commands` 为空 |
| 效果追踪 | `ui.track` 三行 | triggered 行带安装前基线（如 2.88 次/周） | mechanical、guardrail 两行没有基线 |
| 维度 Tab 计数 | `dims[]` | 可用 | mcp、model 为 0；`counts{installed,not_applicable}` 和 `problem_id` 过滤还没接路由 |
| run 稳定性 | `run_id` | catalog 为空时重复 GET 已复用同一个 run | — |

**实际输出样例（节选）：**

```text
#1  rule  完成前自检清单          ≈ 47 min/月 [28–75]  −8 次漏验/月  依据 12 个会话  复制片段 → AGENTS.md (Codex)
    basis: 近 4.2 周共 12 次漏验 × 每次 6 分钟 × 生效率 0.62（估计）
    why:   12 个会话在没有验证证据时就宣布完成。   track: [缺验收证据的完成声明, 基线 2.88, —, 次/周]
#3  flow  验证阶梯：编译→单测→端到端  ≈ 1.9 h/月 [53–188 min]  −19 次返工/月  查看教程 (L4)
hook      只读命令自动放行        ≈ 17 min/月  −34 次审批/月  一键应用 → ~/.codex/config.toml
    why:   6 个会话里你手动批准了约 8.64 次/周只读命令（git status、gh pr view、git diff、git log、ls）。
rule      AGENTS.md：写明 {software} 的环境约定      ← 模板变量漏出
hook      编辑后自动运行 {build_command}             ← 模板变量漏出
flow      api / README / configuration / gotchas / patterns   ← 种子里的 skill 内部文件，无证据
skill     cloudflare / adobe-create-mockups / physical-ai-…  ← 与问题无关的资料库填充卡，save「—」
```

**差距和原因：**
1. 尾部被资料库填充卡占满（约 13/30 张）。原因有两个：一是种子快照来自修复前的数据；二是没有证据的 catalog 卡没有被闸门拦下。
2. 新增的 8 条知识库条目里有模板变量没有填充。
3. 出现重复卡：「一个会话只做一件事」同时来自知识库和模板两条路。
4. mcp 维为 0（合成数据里没有闲置 MCP）。model 维为 0，因为合成数据没有 effort；完整的模型建议本来就属于 v1（RC-08）。
5. UI 演示的 13 个场景里，本轮新增了 PR review 封顶、worktree、只读审查子代理、headless 定时检查等 8 条；**引用核查、LaTeX hook、审稿 skill** 这三条学术场景仍然缺。
6. 永远做不到 100% 的部分：
   - save 本质上是估计值。
   - Claude Code 的审批数据要等 collect-hooks 装好后才开始累积。
   - 安装后的追踪必须真实经过 7 天。
   - 纠偏、重复要求这类问题，在关掉 AI 的情况下只能做 SQL 近似。

## 4. 分析能否百分之百达到 UI

**结论：不能。** 下面这些元素需要的数据，日志里本来就没有。uiview 适配层已经按「缺失保持 null，每个字段带 `basis`」实现，UI 必须按「UI 口径」一列显示。原型 `15-derive.js` 里的魔数（auto × 1.54、人格线性公式、`fitOf`、`regress`）要全部删除，或换成后端口径。

| 页 | 元素 | 为什么到不了 100%（日志里缺什么） | UI 口径 |
| --- | --- | --- | --- |
| A1 / Lite | 会话结果构成、完成率 | 没有用户确认，Agent 日志也没有成功标记 | 加「估计」徽标，可以隐藏；对应筛选置灰 |
| A1 / A5 / Lite | 协作时长 | 只有观测跨度，里面含空闲和并行重叠 | 显示「估计活跃时长」（事件间隔封顶 5 分钟），旁注跨度；A5 写「观测跨度」 |
| A1 / A5 / A6 | 摩擦率、纠偏数 | 只有词面候选：测试的 10 句纠偏只命中 1 句 | 显示「纠偏候选率」并写 n；EV-02 校准之前不下结论 |
| A1 / A3 | Tokens | Codex 只有累计快照；分析核心的视图缺列（D2） | 对 L1 求和并标 basis，Codex 标「估算」 |
| A1 / A3 / A4 / Lite | 错误率、成功率 | status 多为 unknown（真实库 55.88%） | 显示「已知结果中 x%（未知 y%）」；没有已知结果时显示「—」，不能把 unknown 算成成功 |
| A2 / Lite | 四字母人格 | 是规则推断，不是心理测量；样本不够 | 1 个会话即出完整 4 字母（每轴 ≥ 50 取高值一极、< 50 取另一极）；少于 30 会话时置信度「低」并提示「基于 N 个会话，数据越多越准」；0 个会话才是空态 |
| A2 | 全体用户对照、0–100 契合度 | 没有人群数据；契合度公式是原型编的 | 删除对照；契合度改成描述性对比（会话数、纠偏率、估计完成率） |
| A2 / 揭晓 | 6 个候选类型的匹配度 | 原型没有定义 | 用轴距离，标 `basis=axis_distance` |
| A2 / A6 | 盲点和 7 类摩擦类型 | 需要 AI-03 标注 | 规则兜底只能给 2 类，并标 `type_source`；AI facet 就绪后替换 |
| A3 | 上下文峰值 %、上下文面积 | 没有 used/capacity 的观测 | 估计值 = 单次 prompt ÷ 模型窗口；没有窗口表时隐藏；压缩标记照常显示 |
| A3 | 逐消息情绪 ±x | 只有显式的词面表达 | 改成「纠偏 / 正常」两态 |
| A3 | 关键时刻里的「偏离」「放弃」 | 没有标注 | 只给五类：目标、纠偏、连续失败、验证、压缩 |
| A4 | 审批次数和等待 | Claude Code 日志没有审批事件 | 按 Agent 标「未采集」；等待时间只统计有时长的记录，写 n |
| A4 | 耗时 p50 / p95 | Codex 的耗时是用日志间隔估出来的 | 标「估计」；p95 只在 n ≥ 20 时显示 |
| A4 | MCP 常驻 token | 配置文件里没有工具描述的体积 | 显示「未测」 |
| A5 / Lite | 完成度散点、回归线 | 没有统一的结果字段 | 改成「验证通过 / 接受 / 返工」各自的 n；删除回归线，注明「相关不等于因果」 |
| A5 | 子代理配置行 | 清单扫描没有覆盖 `.claude/agents` | 显示「未扫描」 |
| A6 / Lite | −1~+1 情绪曲线、情绪前因 | 显式情绪只出现在约 17% 的消息里 | 改称「显式情绪表述」，断点处不插值，标实验性并写 n；前因样本不够时显示「数据不足」；Lite 不画 |
| A6 | 主题名 | 簇名只是字符 n-gram | 用 taxonomy 标签；AI 命名后标「AI 命名」 |
| A6 | 「原文不离开本机」 | 脱敏后的文本会经引擎发到服务商 | 如实写出用的是哪个引擎、脱敏范围是什么 |

## 5. 外壳与流程

**做得扎实的部分：** 通知与实时（投递矩阵、免打扰、冷却、静默、暂停与补扫、实时五态、SSE）、安装闭环（plan → preview → apply → revert → ledger）、生成工坊链路（预览 → 作业 → 产物自检 → 安装）。

**本轮修复：**
- 包级 `platform.notify()` 原来是空操作，已修，作业完成和磁盘不足通知现在会入库。
- 会话完成通知加了 10 分钟阈值。
- 补上每周报告、发现新来源、分析完成三类通知的生产者。
- 新增 `GET /v1/shell/{popover,onboarding,reveal}`。
- 问答的 scope 现在支持时间窗、项目、来源和持久排除。
- 画像回答不再打印 dict。
- 设置键扩展：0 表示全部、每小时同步、`weekly_report`、`onboarding_step`；`recent_days` 已接入导入计划。
- 新增脱敏规则表、开关和预览。
- 新增清除数据、关于、工具映射。
- 停用的来源默认不再进入分析。

**剩余缺口：**
- 依赖第 3 轮，共 10 行：导出（EXP-01–05、MB-06）、collect-hooks（POP-04、HUD-03、SIM-02 的「等你确认」，以及 MB-13 的角标）。
- 计划内的 v1 / v2 项：Cursor（SET-08）、自定义来源（SET-09）、产物版本链（A9-02）、按行勾选（INST-03）、Ollama。
- 小改动：A9-08 让作业接受 `model` 参数；A9-04「工作流」类产物等 ai-v1-tasks；WG-05、PAL-06 受推荐路由接线影响。
- 宿主负责：SET-04 登录时启动。

## 6. 本轮已修复与剩余缺口

**本轮合入的 12 个包：**

| 方向 | 包 | 主要解决 |
| --- | --- | --- |
| 资料库 | library P1 / P2 / P3 | 来源与重试、离线种子、首启导入与定时刷新、官方 KB 条目、A8 视图、friction 打标、详情补全 |
| 推荐 | rec-fact-problems、rec-card-fidelity、rec-kb-coverage | 未标注日志也能出卡；save / tok / n；三行追踪；run 稳定；8 条 KB 场景；7 类新 problem |
| 分析 | a1a3 P1 / P2、a4a6-tools、a4a6-projects-sentiment | `/v1/uiview/{facts,overview,persona,sessions,tools,projects,sentiment}`，每个字段带 basis |
| 外壳 | shell P1 / P2 | 外壳聚合接口、通知生产者与 notify 修复、设置、脱敏、数据生命周期、问答 scope |

**剩余缺口（按优先级排列，可以直接作为下一轮工作包）：**

| 优先级 | 工作包 | 内容 | 涉及行 | 验收 |
| --- | --- | --- | --- | --- |
| P0 | uiview-wiring | Gateway 挂上 `routes_uiview`、`routes_uiview_a4a6`、`uiview.routes_sessions`；`sections.py` 注册 `uiview_facts`；推荐路由补 widget=1、`counts`、`problem_id` | A1–A6 / Lite 约 140 行；A7-07、A6-03、WG-05 | 真实 Gateway 端到端测试：每个 `/v1/uiview/*` 返回 200 或 202；性能目标是 facts 每千会话 ≤ 200 KB |
| P0 | rec-slate-hygiene | A7 主列表拦下没有证据的 catalog 卡（降级到资料库）；新 KB 条目的模板变量要么填上，要么不出卡；跨召回路去重 | A7-08、A7-11、A1-25、POP-07、LITE-REC | 合成 E2E：没有证据的卡 ≤ 3 张，没有 `{…}`，标题不重复 |
| P0 | lib-seed-rebuild | 用 P1 修复后的连接器和新来源重新打种子包；hook 命名、规则过滤、多 Agent 推断都要生效；联网复测 MCP 全量条数 | A8-04.*、A8-01、LIB-data.seed | 种子里没有叫 "hooks" 的 hook，没有 `_sections` 这类规则，MCP ≥ 300 |
| P1 | analysis-core-fixes（分析核心负责人） | D1 `analytics_scope.agent_ids`；D2 tokens 视图补列；D3 摘要行带 agent；D4 presentation / products 走快照并分页；D6 AI 关闭时也开放 narrate 的 L0 模板 | FB-agent、A1-18b、A3-11d、A1-PERF、A1-07 | 用 `?agent_ids=codex` 过滤后会话数正确；tokens 不为 null |
| P1 | persona-unify | 选定唯一的人格四轴定义（见第 1 节的决定）；分享卡、揭晓和 A2 读同一个来源 | A2-*、REV-*、L-persona-* | 三处的四字母一致 |
| P1 | real-data-verify | 经用户同意后，在本机真实日志上跑一遍 uiview、推荐和资料库：unknown 占比、卡片数、性能 | 全部 | 写出一份真实数据对照表，只放本地 |
| P2 | lib-personal | A8「不感兴趣」：`LabelRequest.target_kind` 增加 `catalog_item`；个人化理由带 session_feature 计数；MCP README 改为链接；提高已安装条目的匹配率 | A8-07、A8-05.why、A8-detail.readme、A8-02 | 能隐藏和撤销；why 里带个人数字 |
| P2 | analysis-tail | 工具矩阵三步链的逐步概率；确认版重试 Top 5；A5 工作流命名；项目人格差异 | A4-11、A4-11b、A5-05、A5-08、A5-11 | — |
| P2 | rec-kb-academic | 补引用核查、LaTeX hook、审稿 skill 三条 KB；steps 补 `commands` | A7-14 | 演示的 13 个场景全部有对应条目 |
| 依赖他人 | 第 3 轮 / AI 任务 | export、collect-hooks、rec-eval、quota；AI-03 摩擦 facet、AI-04 主题命名 | 16 行 in_progress；A6-08、A6-09 | 随各分支合入 |

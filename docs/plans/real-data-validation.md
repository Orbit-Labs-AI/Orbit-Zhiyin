# 真实数据验证：分析、推荐、安装与 AI 后端能否还原 UI

> 状态：验证报告（只读验证） · 维护者 `yhyfhgs` · 2026-10-02；§8 为 2026-10-03 的 round 6 复测
> §0–§7 保留 round 4 基线（`wip/yhyfhgs-backend-r4` @ `606634d`）的原始结论，其中「修复分支均未合入」的说法已过时：修复已合入集成分支，复测结果与剩余问题见 §8。
> 数据：本机真实日志只读导入，仅含聚合结果。不含任何提示词、文件内容、项目名、路径、邮箱或凭据；需要复现的边界用构造数据写成测试。
> 代码基线：`wip/yhyfhgs-backend-r4` @ `606634d`。UI 参照 `prototypes/advance/src/js/` 的 A1–A9、Lite 页面与 [功能映射](feature-map.md) §5。此前构造数据审计按 113 个元素逐项计数；本文按 UI 功能组判定，两者口径不同，不能直接相加。

## 0. 结论

1. **数据层基本达标**：4 个 agent、6 个来源根、1,895 个会话、77.2 万事件全部导入，未解析记录为 0。主要缺口是元数据：Claude 主会话缺 cwd/项目，成本和延迟为空，模型标识全是 unknown。
2. **分析层在真实规模下无法通过网关出数**：除最小的两个来源外，所有范围都是先返回约 80 s 的 202，然后 503。直算的数值大多正确，但耗时 12–740 s，峰值内存最高 16 GB。按 42 个 UI 功能组判定：matches_ui 8、partial 10、empty 11、wrong 8、not_derivable 5。
3. **推荐只能给出泛化的目录卡**：3 天窗口 17 张卡，全部来自目录或模板；摩擦驱动的卡在 30 天窗口被证据闸门全部挡下。证据可追溯率为 0/17，即卡片只带计数，没有可点击的会话。
4. **安装预览准确**：8 类 spec 的 diff 与 before/after 文本一致，在临时 HOME 中 apply→revert 8/8 字节级还原。环境识别有 4 处偏差，都已有修复分支；叠加安装后按正序撤销不能字节还原。
5. **AI 上下文包脱敏有效、估算合理**：叙述类上下文包只有 95–160 token。缺陷是不指定会话的 facet 请求会打包全部片段，约 38 万 token，超出预算近 10 倍，而且没有被拒绝。
6. 共开出 **21 个修复分支**（`wip/be-rd-*`），都只用构造数据跑过针对性测试，**还没有在真实数据上重跑**。重跑前，§2–§3 的结论仍以本文为准。

## 1. 数据规模与导入性能

| 项 | 值 |
| --- | --- |
| 来源 | 4 个 agent（Claude Code、Codex、dsh、pi）；6 个来源根（Claude Code 两个账户目录与桌面 agent 会话、Codex、dsh、pi），共 2,639 个文件 |
| 原始体积 | 约 5.9–6.0 GB |
| 会话 / 事件 | 1,895 个会话（main 469 个）；772,103 个事件；工具调用 13.2 万；模型调用 8.9 万；项目 121 个 |
| 账本 | 770,803 条记录：unparsed 0；ignored 2.2%（都有已声明原因）；folded 25.8%（主要是 dsh 步骤）；unknown 事件 364 条，来自 3 种 Claude 原生类型；ingest_issue 7,090 条（0.92%） |
| 文件覆盖 | Claude 848/848、Codex 974/974、dsh 79/79、pi 2/2 |
| 导入耗时 | 捕获：Claude 约 154 s（13.6 MB/s）、Codex 100 s（39 MB/s）、dsh 70 s（1.3 MB/s）；rebuild 单线程 2,146 s（359 记录/s，占总耗时约 2,540 s 的 85%） |
| 库大小 | tandem.db 10.18 GB，是原始体积的 1.7 倍（event 表 5.4 GB，FTS 1.6 GB）；analysis.sqlite 没有保留策略，验证期间从 28 KB 涨到 1–4 GB |

- **活日志不能直接导入**：第一轮直接对正在写入的日志运行 `tandem ingest`，每个根都在 prepare 之后因 `Indexed source changed` 中止，每次白白耗掉 40–300 s。第二轮先做 APFS 克隆快照，再一次性 rebuild，才成功。部分修复见 `wip/be-rd-live-append`：跳过的来源记为部分完成，不再整体中止。
- **Codex 继承前缀**：6,619 条 issue 是 `inherited_parent_evidence_unavailable`，但 7 个父会话都在库里。也就是说约 69% 的继承前缀记录没关联上，原因是前缀匹配失败，而不是父会话缺失。

## 2. 分析各页还原度

**判定方法**：用 SQL 对 tandem.db 求真值，再与两条路径的结果对比：一是网关 HTTP（真实产品路径，轻量预算 20 s、重量预算 120 s），二是进程内不限时直算。表中的判定针对直算数值；**网关可达**一列单独列出。

### 2.1 计数

| 页 | 组数 | matches_ui | partial | empty | wrong | not_derivable | 网关可达（真实范围） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A1 概览 | 10 | 4 | 0 | 2 | 3 | 1 | 否（仅 pi、dsh 可达） |
| A2 画像 | 6 | 0 | 3 | 1 | 1 | 1 | 否 |
| A3 会话 | 7 | 1 | 2 | 2 | 1 | 1 | 列表与轨迹可达，但轨迹需 10–34 s |
| A4 工具 | 8 | 2 | 1 | 3 | 1 | 1 | 仅 `/v1/analytics/tool_calls` 下钻可达 |
| A5 项目 | 5 | 0 | 1 | 2 | 2 | 0 | 否 |
| A6 文本 | 3 | 0 | 2 | 0 | 0 | 1 | 否 |
| Lite | 3 | 1 | 1 | 1 | 0 | 0 | 否（首启默认 30 天的人格揭晓出不来） |
| **合计** | **42** | **8** | **10** | **11** | **8** | **5** | |

### 2.2 各组关键原因

- **A1**
  - matches_ui：会话数、消息数、日/时/周×时热力格、各 agent 日序列、与上期对比，均与 SQL 完全一致，比率都在 [0,1] 内。
  - empty：Tokens 全为 null（模型调用视图缺 usage_scope、measurement、boundary_reliable，8.9 万条逐次记录被判无效）；人格卡为空。
  - wrong：
    - 协作时长：7 天窗口内会话跨度相加为 660 h，而窗口只有 168 h。
    - 工具 Top 成功率：Edit、Read、WebFetch 已知状态的只占 0.1–6%，而且全是失败，所以显示失败率 100%。
    - weekday/hour 下钻参数被静默忽略。
  - not_derivable：会话结果构成。
- **A2**
  - empty：四轴都没有字母，code 为 null。
  - wrong：委托轴只有 1 个有效任务就给出 score=1.0。
  - partial：
    - 规划轴 0 个任务，验证轴 8/449，编排轴没有提取。
    - 9 个月里有 8 个月显示"不可用"。
    - 指纹外环只有 1 个点。
  - 判定门槛是 5 任务 + 2 会话，不是 UI 写的 30 + 10。粗略词面探测显示：中文占 70%，验证类措辞约 12%，说明抽取召回可能很低，需要 EV-02 标注确认。后端四轴的定义仍与 UI 不同。
  - not_derivable：对照"全体用户"、契合度分。
- **A3**
  - matches_ui：详情中的工具序列与工具统计。
  - partial：
    - 列表行缺 agent、开始时间和结果。
    - 带 until_ts 的范围会丢掉全部标题：title 事件的 ts 为 NULL，7 天和 30 天范围的标题都是 0%，无界范围为 98%。
    - 轨迹页数据正确，但冷启动 9.7–12.6 s，4 并发时 p50 为 15–27 s。
  - empty：模型/思考档位（模型 100% unknown）；key_moments、signals。
  - wrong：64 个无工具会话的工具调用数是 null，而不是 0。
  - not_derivable：结果徽章、上下文 %、情绪值。
- **A4**
  - matches_ui：页头、KPI、明细表与最近 5 次的计数与 SQL 一致；转移矩阵正确。
  - partial：三步链是 shell→shell→shell，支持率 93.5%，没有信息量。
  - wrong：错误率口径。41% 的工具调用状态为 unknown，Claude Code 的非 Bash 工具几乎都是 unknown；用户拒绝的 51 次被算进 unknown（rejected_count=0）。
  - empty：
    - 失败原因：error_class 只覆盖 16/3,766；按结果文本规则可以分出约 69%。
    - 子代理并行度：spawn_call_uid 100% 为空。
    - 覆盖五格：导入的 home 没做清单扫描。
  - not_derivable：
    - 审批与"只读命令自动放行"：审批共 69 条，其中 17 条是 dsh 放行、52 条是 Claude 拒绝；Claude 的放行审批在日志里完全没有。
    - "只读自动放行"样本 N=2，而且这 2 条都是用户拒绝的命令。
- **A5**
  - wrong：
    - 54/121 个项目显示 0 会话。
    - 最大的"项目"没有名字：142 个 Claude 主会话、62,273 次调用都没有 cwd/project。
    - 已删除的 worktree 目录被拆成约 50 个独立项目。
  - partial：项目下的工具统计漏掉了未归属的会话。
  - empty：覆盖格（A5-12）；按项目统计的成本（cost_usd 99.97% 为空）。
  - 在克隆 home 上补扫清单后：实际有 11 个 MCP；出现过调用的 22 个 MCP 中，有 18 个不在清单里。
- **A6**
  - not_derivable：情绪。2,014 条真人消息里，显式情绪命中 0 条。
  - partial：
    - 纠偏率对词表非常敏感：严格词表命中 1.2%，宽松词表命中约 8.6%。
    - 时区只有 Codex 有上报（902 个会话）；Claude、dsh、pi 都是 unknown，`local_inferred` 从未生成。
- **Lite**
  - matches_ui：概览数字（直算）。
  - partial：推荐卡，只能是泛化目录卡，见 §3。
  - empty：首启人格揭晓（网关 503，四轴也没有字母）。

### 2.3 真实数据下不可能 100% 的元素，以及 UI 应显示的口径

| UI 元素 | 原因 | UI 应显示的口径 |
| --- | --- | --- |
| 会话结果（完成/部分/放弃） | 日志里没有用户确认 | 标"估计"，依据末轮状态、失败连发和验证，允许隐藏 |
| 情绪数值、情绪点填色 | 显式情绪命中为 0 | 改为"纠偏/正常"二态，并注明所用词表 |
| 上下文峰值 % 与面积曲线 | 没有 used/capacity 观测 | 单次请求 token ÷ 模型窗口，标"估计"；没有窗口表就隐藏 |
| 成本、Tokens | cost 99.97% 为空，usage 边界不可靠 | 显示"数据不足"及覆盖率，不显示 0 |
| 工具成功率 / 错误率 | 41% 状态未知 | 只按已知结果计算，并同时显示"已知 x%" |
| 审批、自动放行 | Claude 的放行不落日志 | 只显示拒绝次数；"自动放行"标注样本量，N<10 时隐藏 |
| 四轴字母、契合度、全体用户对照 | 样本不足，也没有人群数据 | 显示"样本不足（n/门槛）"；删除对照开关；契合度改为描述性对比 |
| 子代理并行度 | 派发关联为空 | 隐藏 |
| 协作时长 | 会话跨度重叠且含空闲 | 按窗口截断的活跃时长，与跨度分开显示 |

## 3. 推荐在真实数据上的效果

**测试范围**：网关上的 GET 只在 3 天窗口成功。7 天窗口（908 个会话）连续 3 次超过 120 s 后熔断，之后一直返回 202 且 job_id 为 null。30 天窗口在克隆 home 上进程内复刻：recommend_inputs 用时 397 s、峰值 RSS 5.4 GB，引擎本身不到 0.3 s。全时段窗口预计要 25 分钟以上，没有跑。

| 指标 | 3 天窗口（网关） | 30 天窗口（进程内） |
| --- | --- | --- |
| 卡片数 | 17 | 21–23 |
| 维度分布 | skill 10、rule 5、mcp 1、model 1；hook/agent/flow 0 | skill 19–20、model 1、移除类 mcp 1–2；rule/hook/flow 0 |
| 来源 | 目录 16、模板 1；摩擦驱动 0 | 摩擦驱动候选 7 张，全部被证据闸门挡下 |
| 证据可追溯 | 17/17 带 evidence 结构，但 session_uids 和 signal_ids 都是 0/17，只有计数 | 同左 |
| 增益口径 | 17/17 显示"0 个会话出现"；未使用的 MCP 显示"−0 常驻 token" | 同左 |

**闸门参数**：最常见的问题出现在 16/390 个会话中，Wilson 下界 0.025，低于写死的 0.05。390 个会话时，至少要 28 个会话（7.2%）出现才能过闸。

**输入质量**：
- tool_call.approval 几乎都是 NULL；
- 失败调用的 error_class 全是 NULL（约 3.7k 条）；
- command_head 约 83% 是 `cd` 或 shell 包装。

**与 UI 卡片的差距**：
- `ui` 的 16 个字段都有，但没有 save（h/月）、tok、n。UI 的排序和主数字依赖 save。
- 目录卡的 why 是英文简介；mechanism、trial、limitation、steps、file 为空，主按钮却是"预览并安装"。
- 清单关联在实时 home 上的 coverage 是 unavailable，因为从未扫描；分析 worker 里 FeatureService 没有绑定，导致已安装的条目仍被推荐（修复分支 `wip/be-rd-recs-B2`）。

**目录**：
- 共 15,206 项，其中 mcp_server 只有 1 项。
- 9 个源有 7 个同步完成；另外 2 个超过 25 分钟没完成，取消请求发出后任务仍是 running。
- 含下划线的查询会触发 FTS 报错（修复分支 `wip/be-rd-recs-B4`）。

## 4. 安装：环境识别、预览与撤销

**操作约束**：真实 HOME 只做 GET 和 preview；apply 和 revert 都在临时 HOME 中进行，临时 HOME 复制了真实配置文件，并保留原有的软链形态。

- **环境识别正确的部分**：
  - Claude Code 的二进制、版本和 profile；
  - 各配置层的 exists/size/mtime，与 stat 完全一致；
  - 30 个项目的 6 个标志位，0 处不符；
  - pi 版本；
  - 不存在的 agent 正确报告为不存在。
- **环境识别的偏差**（均有修复分支）：
  - B3：随桌面 App 打包的 Codex CLI 没被发现，导致 AI 引擎也报 unavailable；预发布版本号被截掉后缀。
  - B1：没有清单扫描时，installed_counts 全为 0，却标注 basis=inventory。
  - B2：插件数数的是插件目录条目（9），实际已安装为 0。
- **预览**：
  - 覆盖 8 类 spec：权限规则、MCP、两种 hook、规则、skill、插件、危险 hook。
  - diff 的 `+` 行都在 after 文本中，`-` 行都在 before 文本中，adds/dels 与 difflib 一致。
  - JSON 只新增预期的键；TOML 标记块可以被解析。
  - 风险分级：一般为 safe；hook 为 caution；`curl | sh` 为 dangerous，且不 override 时 can_apply=false。
- **撤销**：
  - 8/8 个 spec 单独 apply→revert 后字节级还原。
  - 两次叠加安装后按逆序撤销能字节还原；**按正序撤销不能**，Codex 的 hooks.json 有残留。
  - 用户手动改过目标文件后再撤销，**不会拒绝**，而是直接执行。
- **目录条目**：
  - hook 17/17、mcp 1/1 没有安装声明；skill 多数是 link_only 或 needs_fetch；部分插件返回 422 `catalog_not_installable`。
  - Claude 侧同名 MCP 会与旧条目深度合并，风险仍判为 safe；Codex 侧同样情况会报冲突（修复分支 `wip/be-rd-install-ai-B4`）。
  - Codex 的规则文件是软链时，返回 unmappable（`path_policy:symlink_escape`）。

## 5. AI 上下文包：脱敏与 token 估算

只做了 context-pack preview，没有调用任何真实模型。

| 任务 | token（预算） | 脱敏命中 | 预估费用 |
| --- | --- | --- | --- |
| narrate.overview（7/30/90/400 天） | 95–160（10k）；会话清单项 1,779 token，默认不勾选 | 0 | 约 $0.008 |
| facet.session，单个会话 | 73–2,005（40k） | 0–20 | $0.020–0.022 |
| facet.session，多个会话 | 5,195（40k） | 28 | $0.025 |
| facet，不指定会话 | **379,181（40k，超出）** | 790 | $0.88 |
| generate.skill / rule | 29–905（12k） | 0–1 | $0.015–0.017 |

- 脱敏在真实片段上会命中（单个会话最多 20 处），命中数随所选会话增加。
- 超预算时会标出 `over_budget=true`，但请求不会被拒绝，也不会被截断。
- 叙述类上下文包只含摘要，token 很少，因此给出的叙述信息量有限。

## 6. 性能

机器上同时有约 20 个 agent 在跑（14 核，load 7–28）。绝对值大约偏高 1.5–3 倍，但失败模式和比例可信。

| 端点 / 路径 | p50 / p95 或单次 |
| --- | --- |
| status、sources、inventory、attention、features/profile、catalog | ≤ 20 ms（4 客户端，暖态） |
| projects、sessions | 21–32 / 36 ms |
| events 100 条 / 500 条 | 43 / 60 ms；197 / 278 ms |
| search（检索） | 单客户端 19 / 22 ms；**4 客户端时 48 次里 46 次返回空结果**，p50 434 ms |
| 会话轨迹 | 冷 9.7–12.6 s；4 并发 p50 15–27 s，p95 34 s |
| analytics/tool_calls | 0.3–0.9 s（冷 2.9 s） |
| analytics/{overview,sessions,tools,projects,text} | 网关上 202 约 80 s，然后 503。直算 overview/sessions：dsh 12/4 s，单项目 70/100 s，7 天 247/238 s，30 天 361/738 s，全量 351/625 s；峰值 RSS 0.8–16.4 GB |
| 旧版 analytics/products（全量） | 在网关内同步跑 635 s，返回 955 MB JSON；网关 CPU 160%、内存约 10 GB |
| recommendations（3 天窗口） | 首次排队约 4 min；之后每次 GET 都重建 run，1.2–4.5 s，最慢 12 s |
| inventory/linked | 0.4–1.2 s（skill 用量聚合约占 1 s） |
| 安装环境 / 预览 / apply / revert | 刷新 0.22 s、缓存 1–2 ms；预览 ≤ 0.1 s；apply 和 revert 各 < 0.5 s；目录条目首次生成计划 28–55 s |
| AI preview | engines 0.2–0.5 s；narrate.overview 约 1.0 s；generate.hook 2.3–6.5 s；facet（不指定会话）4.0 s |

**热点定位**：
- overview 约 52% 的时间花在 `summarize_durations`：每个会话都重扫全部事件，O(S×E)。
- sessions 段 34–47% 的时间花在 `temporal_novelty`：逐实体重新拟合 TF-IDF+SVD，O(N²)。
- `read_analysis` 的事件查询不按范围走索引，547 个事件的范围也要 37 s。

## 7. 缺陷、修复分支与剩余问题

### 7.1 已开修复分支

都基于 `wip/yhyfhgs-backend-r4`，未推送也未合入，都只在构造数据上验证过。

| 范围 | 分支 | 内容 |
| --- | --- | --- |
| 分析可用性 | `wip/be-rd-data-D1` | 线性化热点、默认事件预算、超时/内存熔断、清理僵尸运行 |
| | `wip/be-rd-data-D2` | 重型分析路由改由受监管的 analysis worker 计算 |
| | `wip/be-rd-a1a3-B1` | 按范围内事件数放宽预算，超过上限报 `scope_too_large` |
| | `wip/be-rd-a1a3-B2` | 按会话一次性分组事件，消除 O(S×E) |
| | `wip/be-rd-a1a3-B3` | temporal_novelty 改为按前缀检查点重拟合，消除 O(N²) |
| | `wip/be-rd-a1a3-B4` | 分析响应只带样本边界计数；文件清单改走分页端点 |
| | `wip/be-rd-a4a6-B1` | 分析读取按 scope 走索引键，不再全表扫描、整表解码 |
| | `wip/be-rd-a4a6-B2` | 旧版 products/statistics/presentation 移入 worker，限制载荷和历史增长 |
| 数据质量 | `wip/be-rd-data-D4` | Claude 主会话元数据取自第一条含该字段的记录 |
| | `wip/be-rd-a4a6-B3` | 会话 meta 缺 cwd 时回退到首个事件；项目查询保留未归类会话 |
| | `wip/be-rd-a4a6-B4` | 失败率只按已知结果算；Claude Code 无错误标记的结果视为完成 |
| | `wip/be-rd-data-D3` | 轨迹页按会话索引取记录 |
| | `wip/be-rd-live-append` | 被跳过的来源视为部分完成 |
| 推荐 | `wip/be-rd-recs-B1` | 重复 GET 复用同一个 run |
| | `wip/be-rd-recs-B2` | worker 未绑定 FeatureService 时，只读计算清单关联与 profile |
| | `wip/be-rd-recs-B3` | 推荐输入熔断后返回 503；重型预算可配置 |
| | `wip/be-rd-recs-B4` | FTS 报错时只降级词法这一路；补下划线查询回归测试 |
| 安装 | `wip/be-rd-install-ai-B1` | 未扫描清单时 installed_counts 回退到配置文件计数 |
| | `wip/be-rd-install-ai-B2` | 插件和 skill 计数改为已安装数与真实 skill 数 |
| | `wip/be-rd-install-ai-B3` | 检测 App 内置的 Codex CLI，保留预发布版本后缀 |
| | `wip/be-rd-install-ai-B4` | 同名但内容不同的 MCP server 报 `mcp_exists` 冲突 |

`wip/be-rd-data-D1` 与 a1a3-B1/B2/B3、a4a6-B1、`wip/be-rd-data-D2` 与 a4a6-B2 分别改到同一批热点，合入前需要先选定一条路线，再在真实数据上重跑 §2 和 §6。

### 7.2 剩余问题（按优先级）

**P0：不解决就无法演示真实数据**

1. 修复分支合入后在真实数据上重跑，确认 A1–A6、Lite 在 30 天默认范围内能通过网关出数，并且峰值内存可控。
2. 检索在 4 并发时 46/48 次返回空结果。这是静默错误，不是变慢。
3. 推荐输入在 30 天窗口需要 397 s 和 5.4 GB 内存；7 天及以上窗口在网关上无法完成。
4. 不指定会话的 facet 上下文包超预算近 10 倍，却没有被拒绝或截断。

**P1：数值错误或口径误导**

5. Tokens 与成本：model_alias 从未被填充，cost 99.97% 为空；usage 边界字段缺失；latency/ttft 全空；`/v1/sessions` 的模型 100% 是 unknown。
6. 工具状态 41% 未知，error_class 几乎全空，用户拒绝没有单独计数。
7. 已删除 worktree 被拆成约 50 个项目；带 until_ts 的范围丢标题；无工具会话的计数是 null 而不是 0。
8. A2 四轴：样本门槛与 UI 不一致，抽取召回偏低，委托轴单样本就满分；四轴定义要先和 UI 对齐。
9. 推荐卡缺 save/tok/n，证据不带 session_uids，增益显示"0 个会话"；闸门的 Wilson 下界写死为 0.05，按真实会话量需要重新标定。
10. 安装：叠加安装后按正序撤销不能字节还原；目标文件被改过后撤销不拒绝。

**P2：覆盖与体验**

11. 时区只有 Codex 有；`local_inferred` 未实现。
12. Codex 继承前缀约 69% 没关联上。
13. 3 种 Claude 原生类型落为 unknown。
14. rebuild 单线程 359 记录/s。
15. analysis.sqlite 没有保留策略。
16. 目录中 MCP 只有 1 项；2 个源同步卡住，且取消无效；目录条目首次生成计划需要 28–55 s。
17. hook/MCP 目录条目没有安装声明；Codex 规则文件是软链时无法安装。
18. 审批、子代理并行度、情绪：按 §2.3 的口径降级显示，不再追求和 UI 数字一致。

## 8. 复测与修复（round 6，2026-10-03）

> 基线：`wip/yhyfhgs-backend` @ `2c66362`。§7.1 的修复分支除四个外都已合入：`wip/be-rd-a1a3-B2`、`-B3` 与 `wip/be-rd-data-D1` 由并行的分析冷算性能工作取代，`wip/be-rd-a4a6-B3` 由 `wip/be-rd-data-D4` 取代。另有 round 6 的 11 个修复包。
> 数字来自真实数据的 APFS 克隆（1,895 个会话、77.2 万事件，用当前代码重建），机器仍被其他任务占用（load 6–16），只说明量级。只含聚合结果。
> 数据层改动靠重新派生生效（现为 `MAPPER_VERSION` 1.3.6、`REDUCER_VERSION` 1.2.4，旧库自动重建）。真实库只做过只读探针，没有整库重导，所以数据层各项的真实占比还没有重新测。

### 8.1 网关出数：before → after

| 项 | round 4 基线 | round 6 |
| --- | --- | --- |
| 真实范围经网关出数 | 所有真实范围先 202 循环约 80 s，再返回 503 | 首个 7 天数据约 57 s 就绪，期间 202 带 `meta.progress` |
| 首个窗口就绪后 | 不可达 | persona / facts 0 s，sessions 1.4 s，analytics overview 0.11 s |
| 更宽窗口 | 不可达 | 30 天约 200 s、全时段约 355 s，后台渐进就绪 |
| 进程树峰值内存 | 直算最高 16.4 GB | 10.6 GB |

直算分节（独立进程冷算）。基线是 round 6 perf 包开始时的 `3b9af5d`，它已含第一轮冷算优化，所以和 §6 的 round 4 直算耗时不同：

| 窗口 | facts：基线 → 现在 | 之后的 sessions：基线 → 现在 |
| --- | --- | --- |
| 7 天 | 169 s / 13.1 GB → 84–97 s / 6.9–7.8 GB | 67 s（overview 18.6 s）→ 2.3 s（overview 0.7 s） |
| 30 天 | 284 s / 16.8 GB → 131 s / 13.7 GB | 104 s → 4.2 s |
| 全时段 | 280 s / 16.6 GB → 149 s / 11.1 GB | 111 s / 19.2 GB → 3.7 s |

两张表口径不同（网关端到端与直算分节），不能直接相减。主要手段：超时预算按事件数放宽并封顶 900 s、运行中按内存熔断、读取共享重复值（每事件约 7.9 → 6.5 KB）、缓存不再被体积上限立即淘汰（上限 3 GB，并有保留策略）、导入后自动按 7 → 30 天 → 全时段预热。

### 8.2 其他模块

| 模块 | round 4 基线 | round 6 |
| --- | --- | --- |
| 检索，4 客户端并发的空结果 | 46/48（真实数据） | 0/48（构造数据基准：250 个会话 × 100 条消息，p50 16 ms）；响应带 `partial_reasons`，空结果一定有原因；未在真实网关复测 |
| 推荐，30 天窗口 | 30 天：摩擦驱动候选 0/7 过闸；3 天：证据可追溯 0/17 | 11 张排序卡；带证据的卡，session uid 全部可解析（离线回放真实输入） |
| AI 上下文包：facet，不指定会话 | 379k token，超 40k 预算近 10 倍，4.0 s | 37.9k token，在预算内，其余 215 个会话标为排队，0.45 s |
| AI 上下文包：generate.hook / narrate.overview | 38.7k token（预算 12k）/ 暖态 1.0 s | 4.5k token / 0.25 s |
| 协作时长，30 天 | 1,042 h（窗口只有 720 h） | 522 h，区间取并集并按窗口截断 |
| 纠偏计数（AI 外发包） | 80，多为 `不是`、`again` 的误命中 | 8，抽查都是真实纠偏 |
| 有会话的项目数 | 68（已删除 worktree 被拆开） | 26（用 1,895 个会话的 cwd 内存重放） |
| shell 调用的 `command_head` | 约 83% 是 `cd` 或 shell 包装 | 94,378 条探针里，含路径或赋值的为 0 |
| Codex 后台命令时长 | 14,355 / 27,829 条是假的 0 ms | 改为缺失（`duration_unmeasured`） |

- **推荐闸门**：Wilson 下界按范围内会话数缩放（超过 60 个会话时乘 √(60/n)，下限 0.01），不再写死 0.05。离线回放 30 天输入时，23/390 个会话出现的工具环境失败问题能过闸，`kb:retry-breaker` 与 `kb:systematic-debugging` 随之通过。
- **安装的撤销**：
  - 叠加安装按任意顺序撤销都能字节还原。撤销时从账本继承先前已撤销安装创建的文件，只剩 Tandem 容器时删除；用户加过自己的内容则保留。
  - 用户改过我们装入的条目后撤销会拒绝（`modified`，带三方 diff），不再直接执行。行为变化：用户改了我们加的数组项，现在也是拒绝，而不是报 `already_reverted`。
  - 符号链接的规则文件和 skill：指向家目录内真实文件的，装入真实文件并保留链接；指向家目录外的仍是 unmappable，但所有 unmappable 都带中文 `reason_text`，不再露出 `path_policy:symlink_escape`。
  - 同名但内容不同的 MCP 报 `mcp_exists`；App 内置的 Codex CLI 能被发现；目录里不可安装的 hook / MCP / 插件返回 `link_only` 计划，不再是 422。

### 8.3 缺陷 id → 状态

各 lane 的编号独立，同一问题可能在多个 lane 各占一条（如 Claude 主会话缺 cwd）。按 lane 计共 83 条：已修 66、部分 17、未修 0（recs-B13 在 round 5 已修）。

| lane | 已修 | 部分（剩余内容） | 未修 |
| --- | --- | --- | --- |
| install-ai（17） | B1–B12、B17 | B13（只改了 AI 外发脱敏，共享隐私规则与导出路径仍漏 CGNAT / 公网 IP）；B14（AI 侧已修，features 的命令族标签仍带分隔符）；B15（AI 侧校验已修，skill 文件键名错误仍通过 `validate_spec`）；B16（安装查找变快且不再 422，目录条目详情首调仍建相似索引；17 个 hook 里只有 1 个可直接安装） | — |
| recs（15） | B1–B6、B8–B14（B13 在 round 5 `ce3111b` 已修：小组件默认 1 条、列表 `counts`、`problem_id` 过滤） | B7（模型路由卡的头条增益仍是「N 个会话出现」，无时间 / token 估算）；B15（每个数据版本首调仍冷读约 1 s，需要部分索引） | — |
| data（16） | D2–D9、D12、D14–D16 | D1（预算、僵尸运行、内存熔断已修，内存目标未达成）；D10（被跳过的来源记为部分完成，不再整体中止；被跳过的来源本轮没有导入）；D11（别名和 Claude 价格表已有，GPT 类模型没有价格，成本仍为 NULL）；D13（增加宽松匹配和压缩历史匹配，真实库恢复多少未测） | — |
| a4a6（15） | B1–B4、B6–B8、B10–B12、B14 | B5（数据侧已修，analytics 的 p50 / p90 仍含估算时长，旧版 `exec_command_end` 未读）；B9（Codex skill 不再误判未使用，清单扫描根已补，无清单扫描时的 ask 措辞未单独验证）；B13（纠偏候选 25 → 45 / 1,883 条真人消息，显式情绪命中仍为 0）；B15（analytics 的项目口径仍按事件级 `project_id`，重名后缀只在 `/v1/projects`） | — |
| a1a3（20） | B1–B9、B11、B12、B14–B17、B19、B20 | B10（`agent_ids` 已生效，未声明参数返回 422，`weekday` / `hour` 只是明确拒绝，没有实现）；B13（同 a4a6-B15）；B18（四轴样本不足时不出分，门槛 5 个任务 + 2 个会话，真实召回未复测，口径仍与 UI 不同） | — |

D8、D9、D11、D12、D14、D16 等数据层项在代码与构造数据上验证通过，真实占比（例如工具状态 unknown 的比例）要等整库重导后才能给出。

### 8.4 剩余的已知限制

1. **分析 worker 内存没有降到 2 GB**：父进程仍要持有整个窗口，冷态峰值约 7 GB（7 天）、10–11 GB（30 天与全时段）。family / semantic / lexical / statistics 需要整个选区，按根分块流式读取没有做。
2. **冷态 7 天首次出数仍要约 1 分钟**：随机器负载 57–115 s（约 30 万事件，读取 13–45 s，计算约 35 s）。期间客户端拿到的是带进度的 202。
3. **16 GB 的 Mac 上，全时段窗口可能返回 422**（`analysis_scope_too_large`，熔断线为物理内存的 3/4，夹在 4–24 GB 之间）；7 天和 30 天仍能出数。
4. **`/v1/uiview/sessions` 的叠加层没有时区**：它用不带时区的方式取事实行，所以取不到按非 UTC 客户端时区算出的快照。该问题早于本轮，尚未处理。
5. **计时类测试在 xdist 并行下会抖动**：`test_thousand_sessions_warm_requests_meet_latency_budgets` 与召回延迟用例单独跑都通过；召回延迟用例已标为串行，高负载时其他预算类用例仍会偶发失败。

另外未验证或未覆盖：

- 宽窗口就绪前，persona（`period=90`）与 overview（`range=30`）从 7 天窗口出数，只覆盖 7 天；`meta.window` 会如实标明，前端要切换。
- `/v1/analytics/runs*` 仍由进程内的只读路径提供，`/runs/{id}/result` 可能返回数百 MB 的历史快照。
- 显式情绪在真实数据上仍为 0，保持实验指标并带样本量。
- 本轮修复都没有在真实网关上端到端复测过检索、实时状态和安装目录首调。

# 分析模块输入说明：来源、L2/L3 数据表与使用口径

> 文档版本：`analysis-input-v1`，2026-10-02。
>
> 面向分析模块开发者。本文解释分析入口应收到什么数据、去哪里取、每个字段是什么意思，以及材料不足时怎样继续工作。入口可以接收 SQLite 查询结果、对象列表或 DataFrame；函数命名、文件拆分与调用方式由实现者决定。
>
> 本文以最新的数据获取方案为目标契约，并核对了正在实现的连接器基础和分析后端。**目标契约不代表所有字段已经落库。** 第 10 节列出当前实现差异；标为「补充约定」的字段是本文提出的输入要求，尚需数据层与分析层在联调时落地，不表示新增算法已获确认或已经实现。

## 1. 开发时先拿哪些输入

通常先取 **L3 的会话、轮次、配对工具调用、模型请求与基础特征**，再取这些会话对应的 **L2 事件序列**。L3 用于聚合和复用，L2 用于读原话、恢复过程、核对证据和调整统计。仅给总量无法支持纠偏、任务划分、重复失败或回复改写分析。

| 输入来源 | 谁生成 | 给分析模块什么 | 什么时候需要 |
| --- | --- | --- | --- |
| `orbit.db` 的 L3 | 采集与标准化模块从 L2 派生 | `project`、`session`、`turn`、`tool_call`、`model_call`、`session_feature`、`link` | 基础统计、项目与模型比较、工具和协作过程分析 |
| `orbit.db` 的 L2 `event` | 各 Agent 连接器标准化、合并、去重 | 按会话排序的标准事件、正文、结构化属性和追溯 ID | 需求与反馈、语义分析、过程重建、证据下钻 |
| `source`、`source_file`、L1 `raw_record` | 发现、增量读取与记账 | 来源身份、采集覆盖、解析异常、原始记录位置 | 判断样本边界和数据质量；按证据定位原文 |
| L0 `raw/` 与附件归档 | 采集模块归档原始字节 | 截断文本的全文、原生结构、历史文件代次 | L2 不足时按 ID 局部读取；不作为每次分析的全量输入 |
| `inventory_item` | 本机配置扫描 | 已安装并启用的 Skill、MCP、Hook、规则、插件及作用域 | 判断「已装、启用、观察到使用」各自的含义 |
| `catalog.db` | 生态采集模块 | 资源、版本、能力特征、模型信息与公开成绩 | 分析完成后的匹配或模型比较；基础分析可独立运行 |
| 本次分析的范围和数据版本 | 数据读取端与分析调用方 | 项目、模型、时间区间、排除项、读取版本、覆盖说明 | 每次调用都需要，防止不同范围混算 |

原始会话来自 Claude Code、Codex、DeepSeek Harness、pi、OpenCode、Hermes Agent 等数据目录。分析模块通过统一的表消费它们，不再各自解析 Agent 日志。各 Agent 的来源差异仍保留在 `source.agent`、`session.harness_version` 和事件属性中，用于解释数据可用性。

同一 Agent 的多个账号或配置根目录是不同 `source`。多根目录不能直接理解成多个人；也不能把同一会话的镜像、导入副本或 fork 复制段当成新的行为样本。Demo 中的模拟会话、固定画像、情绪曲线和推荐卡片只用于展示，不能回填为分析事实。

## 2. 一次分析入口的公共输入

以下是**逻辑上的输入组织**，无需新增一套数据库或框架。数组可以换成查询结果或迭代器，但字段含义、筛选范围和证据关系应一致。

### 2.1 范围参数

这些参数属于分析调用的补充约定，不是数据库列。

| 参数 | 类型与默认值 | 具体含义 |
| --- | --- | --- |
| `project_ids` | 字符串数组；省略表示全部可用项目 | 使用规范 `project_id`，不按项目显示名匹配；传 `[]` 表示明确选中零个项目 |
| `model_ids` | 字符串数组；省略表示全部模型 | 使用逐次请求的规范 `model_id`；未知模型单列，不能从会话最后使用的模型回填 |
| `effort_raw` | 字符串数组；可省略 | 在相应模型或厂商内部筛选思考档位；跨厂商的同名档位不等价 |
| `from_ts`、`until_ts` | UTC 毫秒整数或 `null` | 统计区间采用 `[from_ts, until_ts)`，省略端点表示无该方向限制；有界时间统计不能把时间未知的记录塞入区间 |
| `display_timezone` | IANA 时区名；调用方明确给出 | 仅用于日期、星期、小时等分桶与展示，不修改原始 UTC 时间；不是历史事件时区的证据 |
| `root_session_uids` | 字符串数组；可省略 | 精确选择根会话；仍可带入其子代理的工具与用量，但要保留子会话身份 |
| `excluded_session_uids` | 字符串数组；默认 `[]` | 排除评测、Orbit 自身分析、已指定忽略的会话；排除项不能因为换筛选条件而重新进入 |
| `include_children` | 布尔；默认 `true` | 根会话的工作过程包含已确认的子代理与 workflow agent；真人消息与会话分母仍按主会话计算 |
| `scene` | 字符串或 `null` | 可选的任务场景筛选；它是分析派生标签，不能改写用户原来的任务、读者和语言要求 |

项目与模型是主要分类维度。Agent 用于来源追溯、格式质量和资源兼容性，不作为默认的画像分类维度。

**统计成员与上下文材料分开。** 时间或模型筛选先确定需要统计的请求、工具调用或任务，再读取与它们有关的用户请求、回复、返回和后续反馈。区间前的原始要求可以作为上下文，但不增加区间内的要求计数；区间后的反馈不能用于当时快照的结论。模型筛选也不能把关联的用户请求和工具返回删掉。来源不支持可靠归属时，该部分标为未知。

当前 Python 原型使用的 `before` 是包含截止点的筛选；本文的 `until_ts` 是排除截止点的上界。接入时明确转换边界，不能只换参数名。

### 2.2 数据版本与覆盖说明

| 输入项 | 来自哪里 | 含义与要求 |
| --- | --- | --- |
| `input_contract` | 本文 | 输入语义版本，例如 `analysis-input-v1`；不同于后端输出 JSON 的版本 |
| `db_schema_version` | `PRAGMA user_version` 或当前存储实现的版本标识 | 说明实际字段集合；没有版本标识时明确记为未知，不能伪装成目标 schema |
| `parser_version`、`derivation_version`、`redaction_version` | 采集、派生与脱敏过程 | 区分同一来源在不同规则下的结果；当前未保存的版本是待补能力 |
| `sample_boundary` | 导入策略及来源覆盖信息 | 说明哪些根目录、哪些时间范围和排除项已经进入台账；本次查询只能在这个范围内进一步筛选 |
| `catalog_snapshot` | 生态库快照或固定资源版本 | 可空；用于复现匹配结果，不应控制用户画像 |
| `coverage` | 读取端对所选数据的检查结果 | 按数据集或字段说明可用行数、未知行数、截断行数、时间未知行数和缺失原因 |

这组版本与覆盖字段是入口元数据，**不要求把同名字段加进每张表**。可以由现有版本标识、查询计数和采集诊断组装；未实现的部分保持未知。一次读取应使用一致的数据库快照，不能混用重算前的 `event` 和重算后的 `tool_call`。读取端记录当次采用的台账与生态快照，避免结果复跑时悄悄换材料。

`coverage` 状态的建议约定：

| 状态 | 解释 | 分析如何使用 |
| --- | --- | --- |
| `available` | 来源支持此输入，所选范围已完成读取 | 可以计算，但仍逐字段检查空值 |
| `partial` | 只读到部分记录、字段缺失或文本截断 | 只计算可支持的部分，带上有效样本分母与缺口 |
| `unavailable` | 来源不支持、尚未实现或归档已缺失 | 对应结果为未知，给出缺失原因 |
| `excluded` | 被样本策略主动排除 | 不计入样本；说明排除规模即可 |

设置页的数据覆盖卡不加载整份分析输入，而是调用 `orbit_data.analysis_input.coverage_summary(conn, scope=None)`，经 `GET /v1/app/coverage` 返回（库不存在时为 `{"available": false, "reason": "no_database"}`）：

| 字段 | 含义 |
| --- | --- |
| `sessions.rows`、`sessions.status_known_rows`、`sessions.status_known_share` | 分析口径内的会话数、结果状态已知的会话数及其占比；分母为 0 时占比为 `null` |
| `model_call.rows`、`model_call.unmapped_model_rows`、`model_call.unmapped_model_share`、`model_call.cost_usd` | 分析口径内的模型调用数、模型名未识别的调用数与占比、已计价花费 |
| `excluded_sessions` | 与 `coverage-v1` 相同的 `status`、`rows`、`reasons`、`reason_counts`，另加被排除会话的 `model_calls`、`tokens`、`cost_usd` 与 `cost_share`（占「口径内 + 被排除」已计价花费的比例，无计价时为 `null`） |
| `excluded_sessions.reasons_labelled` | 仅 API 附加：`[{code, label, count}]`，`label` 为中文原因，按数量降序 |

`[]` 只有在来源支持且所选范围已完整读取时才表示「观察到零条」。来源根本没有工具、正文或逐次用量记录时，不能用空数组证明「用户不用工具」「用户没有反馈」或「成本为零」。

### 2.3 字段的通用规则

| 类型或情况 | 输入约定 |
| --- | --- |
| ID | `*_uid`、`project_id`、`source_id`、`item_id` 等作为不透明标识；不从中解析日期、项目名或顺序。`file_id` 的现有实现与草图类型不同，读取端保持原类型或统一序列化，不能混用两库的 ID |
| 时间与时长 | 时间为 UTC 毫秒整数；时长为毫秒非负数。来源未知时为 `null`；不能用导入时刻、文件 mtime、绝对值或 0 兜底 |
| 数值 | token 与计数为非负整数，金额为美元数值；零必须来自明确的观测。缺失不变成零，比例分母为零时结果为空 |
| JSON | SQLite 中的 `attrs`、`ext`、`files`、`paths`、配置和目录字段是 JSON 文本；进入分析对象前解析为对象或数组。JSON 损坏是输入缺口，不能默默当成 `{}` 或 `[]` |
| 状态 | 仅接受对应实体的状态；工具 `completed`、轮次 `completed`、会话 `completed` 分别描述协议状态，不直接表示任务成功 |
| 空正文 | `text=null` 表示不可用；`text=""` 可能是无文本事件。两者都不能推断「用户未表达要求」 |
| 未知字段 | 保留 `ext` 用于追溯与格式升级；未确认语义前不参与指标。不能让原始日志文本或资源正文变成分析规则 |

## 3. L3：直接用于分析的数据表

下列列名采用数据获取方案的目标 DDL。没有写为必需的描述、时间、状态与度量字段都允许未知。身份和关联缺失会影响配对与证据，不能靠相邻位置补齐。

### 3.1 `project`：项目身份与归属

粒度：一个规范项目一行。

| 字段 | 类型 | 输入解释 |
| --- | --- | --- |
| `project_id` | 字符串，必需 | 分组与连接键；名称相同的目录未必是同一项目 |
| `key_type`、`key` | 字符串，必需 | 归属依据：`git_remote`、`git_root`、`path`、`bucket`；规范远程地址优先，其次主仓库根，再次工作路径 |
| `name` | 字符串 | 展示名，不作为去重键 |
| `git_remote` | 字符串或空 | 已规范化的远程地址；缺失不代表没有 Git |
| `paths` | 字符串数组 | 归入同一项目的克隆、worktree 或工作目录集合 |

同一仓库的多个 worktree 按数据层的归属结果连接。用户手动合并或拆分由 `project_override` 生效，分析端使用重算后的 `project_id`，不另写一套路径归并规则。仅有旧原型的 cwd 分组时，明确标为路径口径，不能声称已完成仓库级归并。

### 3.2 `session`：会话身份、血缘与边界

粒度：一个逻辑会话一行，子代理也是会话。

| 字段 | 类型 | 输入解释 |
| --- | --- | --- |
| `session_uid`、`source_id`、`native_id` | 字符串，必需 | 标准会话 ID、来源 ID、原生会话 ID；原生 ID 不能脱离来源直接全局去重 |
| `kind` | 枚举，必需 | `main`、`subagent`、`workflow_agent`、`review`、`automation`、`import`、`auxiliary` |
| `parent_uid`、`root_uid` | 会话 ID 或空 | 直接父会话与根会话；按已确认关系连接，不以目录名或标题猜测 |
| `spawn_call_uid` | 工具调用 ID 或空 | 哪次调用派生该子会话，用于连接委派与返回 |
| `depth` | 整数 | 委派层级；不能单独用它识别 fork 或 import |
| `forked_from`、`imported_from` | 会话 ID 或空 | 分叉或恢复的来源、跨 Agent 导入的原会话；保留样本相关性与副本关系 |
| `project_id` | 项目 ID 或空 | 当前派生归属；中途切目录时需结合相关事件，不能把全部工具文件强归到初始 cwd |
| `cwd`、`git_branch`、`git_sha` | 字符串或空 | 工作目录与来源提供的 Git 信息，不表示已经产出或保留了某次提交 |
| `client`、`harness_version` | 字符串或空 | CLI、桌面、IDE 等入口与 Agent 版本；用于说明记录能力和版本变化 |
| `title`、`title_source` | 字符串或空 | 标题与标题来源，便于展示；不作为任务意图的权威证据 |
| `started_at`、`ended_at` | UTC 毫秒或空 | 排除重放历史后的会话边界；只是已观察轨迹的起止，不是用户实际工作时长 |
| `timezone`、`timezone_source` | 时区及来源 | 来源为 `reported`、`local_inferred`、`unknown`；本机推定不能冒充历史时区 |
| `status` | 字符串或空 | 活跃、完成、打断或未知等来源状态；上游文件不再写入不足以证明任务完成 |

默认把 `main` 作为真人协作的会话单位。子代理与 workflow agent 的新工具操作和用量可以归到根会话，但其注入历史和代理消息不能增加真人输入分母。`review`、`automation`、`import`、`auxiliary` 默认不参与真人画像；需要分析这些工作时单独明确范围。fork 中新增的真人行为可以分析，复制历史不能再计数，相关会话也不能视为独立样本。

### 3.3 `turn`：一次输入到完成的轮次

| 字段 | 类型 | 输入解释 |
| --- | --- | --- |
| `turn_uid`、`session_uid` | ID，必需 | 轮次与所属会话 |
| `idx` | 整数，必需 | 会话内轮次顺序，不是跨会话时间序号 |
| `trigger` | 字符串或空 | 人类、排队消息、通知、对等 Agent、自动化等触发者；不是每轮都由真人开始 |
| `status` | 字符串或空 | 完成、打断、失败等；来源没有明确结束时保持未知 |
| `started_at`、`ended_at` | UTC 毫秒或空 | 来源明确或有依据派生的端点；质量与依据仍需随关联事件保留 |
| `first_event_uid`、`last_event_uid` | 事件 ID 或空 | 该轮已观察事件的边界，用于取完整过程和下钻 |

**轮次不等于任务。** 同一任务可以经历多轮修改，一轮中也可能出现新的补充或插话。`task_id`、场景、阶段、读者、交付语言是分析模块根据真人输入与交付上下文生成的结果，不是现成的 L3 基础表列。

### 3.4 `tool_call`：配对后的工具调用

粒度：一次逻辑工具调用一行；调用和返回两条事件不能算两次调用。

| 字段 | 类型 | 输入解释 |
| --- | --- | --- |
| `call_uid`、`session_uid` | ID，必需 | 调用的标准身份与所属会话；不要只按原生 `call_id` 全局配对 |
| `turn_uid` | 轮次 ID 或空 | 所属轮次；未知不排除该调用，但不能纳入依赖轮次归属的指标 |
| `call_event_uid`、`result_event_uid` | 事件 ID 或空 | 对应 L2 调用与结果；只有一端时保留未配对状态，不生成虚构结果 |
| `name_raw`、`kind` | 字符串，必需 | 原工具名与归一类别，如 `shell`、`file.read`、`file.edit`、`web.search`、`mcp`、`subagent`、`skill`、`ask_user`、`other` |
| `mcp_server`、`mcp_tool`、`skill` | 字符串或空 | 实际服务、工具或技能身份；安装清单中存在不等于发生调用 |
| `subagent_session_uid` | 会话 ID 或空 | 此调用关联的子会话；用于委派路径与用量归属 |
| `command_head` | 字符串或空 | 归一命令头，如 `git status`、`gh pr`、`latexmk`；不等于完整参数或验证范围 |
| `files` | 字符串数组或空 | 此调用涉及的文件；相对路径需结合调用时 cwd，不能仅按文件名合并 |
| `status` | 状态或空 | 完成、失败、拒绝、打断、运行中或未知；由明确协议判定，不通过 stdout 中出现 `error` 猜测 |
| `exit_code`、`error_class` | 整数、字符串或空 | 命令退出码与已确认错误类别；非零可支持「该命令返回失败」，不直接证明任务失败或浪费 |
| `started_at`、`ended_at`、`duration_ms` | UTC 毫秒、毫秒或空 | 原生端点与时长；只有完整可比较端点才能做区间并集 |
| `duration_source`、`duration_quality` | 枚举或空 | 依据为 `reported`、`native_bounds`、`event_difference`、`unknown`；质量为 `reported`、`estimated`、`missing` |
| `approval`、`approval_wait_ms` | 字符串、毫秒或空 | 决策与等待；缺少等待证据时为空，不能把工具耗时当审批等待 |
| `attribution` | 对象或空 | 调用由哪个技能、MCP、Hook 或代理引起的来源证据；不等于效果归因 |
| `is_wrapper` | 布尔；当前连接器已有，目标草图未列 | 是否为编排外层；外层与内层应采用明确的计数口径，不能重复累计同一操作 |

重复失败还需要参数摘要，验证检测还需要命令与目标信息，包装脚本还需要状态适用范围。这些从对应 L2 的结构化属性取，补充字段见 4.4。只给 `name_raw + status` 不足以证明「相同操作连续失败」。

时长使用优先级：原生时长 → 同一时钟的原生端点 → 配对事件时间差。事件差是估算，按调用顺序批量提交的返回通常只能给上界。并行调用计算覆盖跨度时取区间并集，例如 `0–5 秒` 与 `3–8 秒` 的并集是 8 秒；每次调用的时长之和是 10 秒，两者含义不同。跨会话相加只描述采样规模；计算根会话树的墙钟覆盖时还需合并子会话重叠区间。

失败率要写分母：例如「明确完成或失败的调用中，失败占比」。拒绝、打断、仍在运行和状态未知单列。只按有结果的调用计算时，同时报告未配对规模，不能把未知结果当成功。

### 3.5 `model_call`：逐次模型请求

粒度：能确认请求边界的一次模型请求一行。**累计快照不进入这张表冒充单次请求。**

| 字段 | 类型 | 输入解释 |
| --- | --- | --- |
| `call_uid`、`session_uid` | ID，必需 | 请求标准身份与所属会话；与工具调用的 `call_uid` 属于不同实体 |
| `turn_uid`、`request_id` | ID 或空 | 所属轮次与原生请求；原生请求 ID 缺失时，由数据层提供稳定请求身份 |
| `provider` | 字符串或空 | 实际供应商或路由；不能仅凭它认定是不同规范模型 |
| `model_raw`、`model_id` | 字符串或空 | 原始模型名与规范模型 ID；后者用于跨 Agent 分组，前者用于核对别名 |
| `effort_raw`、`effort_rank` | 原值、厂商内序号或空 | 思考档位，排名只在对应厂商体系内解释；缺失不代表最低档 |
| `purpose` | 字符串或空 | 主对话、子代理、压缩、标题、分类、评审等用途；未知不能自动归到主对话 |
| `input_tokens` | 非负整数或空 | 未缓存输入，不含缓存读和缓存写 |
| `cache_read_tokens`、`cache_write_tokens` | 非负整数或空 | 缓存读与缓存写，分别记录，缺失不能补 0 |
| `output_tokens` | 非负整数或空 | 输出总量，已包含思考部分 |
| `reasoning_tokens` | 非负整数或空 | 输出中的思考部分，不再与 `output_tokens` 相加 |
| `cost_usd`、`cost_source` | 美元数值、来源或空 | 原生报告、按价格表折算或未知；价目版本和原始金额要能追溯到 L2 或入口元数据 |
| `latency_ms`、`ttft_ms` | 毫秒或空 | 请求延迟、首字延迟；需要请求边界或流式信号，不能用回复写入间隔代替 |
| `stop_reason` | 字符串或空 | 原生停止原因；不表示用户接受答案 |
| `ts` | UTC 毫秒或空 | 请求采用的时间，具体语义由关联事件说明；不明确时不能硬归到某日 |

目标 `model_call` 草图没有直接的 usage 事件外键。输入仍需能回到相应 `model.usage`：有 `request_id` 时按来源、会话和请求身份关联；没有时由数据层附带稳定请求与事件对应关系。**补充约定：可以在入口附带 `model_usage_refs`，每项含 `model_call_uid` 和 `event_uids`，不要求增加同名表。** 无法可靠连接时标注证据缺口，不能按最近的 usage 猜配。

token 的统一计算口径：

```text
输入总量 = input_tokens + cache_read_tokens + cache_write_tokens
总 token = 输入总量 + output_tokens
缓存读占比 = cache_read_tokens / 输入总量
```

只在相关分桶完整、同口径且分母大于零时计算总量与占比。`reasoning_tokens` 已包含在输出中。例如未缓存输入 1200、缓存读 500、缓存写 0、输出 300（含思考 100），总量是 2000，不是 2100。只有部分分桶时可以报告已知分项，但不能给完整总量或完整缓存占比。

归一换算由数据层完成：OpenAI/Codex 的输入需扣除已包含的缓存读；Anthropic、OpenCode 和 DSH 已拆开的输入不重复扣减；OpenCode 原生输出不含 reasoning，需要加进标准输出，Claude、Codex、pi 已包含时不再相加。分析端消费统一分桶，同时保留原始报告以便核对。

金额为 0 和金额未知分别保留。API 价目折算额不等于订阅账单，也不代表真正节省了这些金额。逐次金额与累计金额的覆盖关系按 4.5 处理。

### 3.6 `session_feature`、`link`：可复用的基础输入

| 表与字段 | 粒度与解释 | 如何使用 |
| --- | --- | --- |
| `session_feature(session_uid, feature, value, n)` | 一个会话 × 特征类型 × 特征值；`n` 为该提取规则下的出现次数 | 做基础统计、候选筛选和生态能力匹配；不能代替原事件证据 |
| `link(session_uid, turn_uid, kind, ref, ts)` | 会话或轮次与 PR、commit、artifact 等外部对象的关联 | 定位交付物或开发过程；存在链接不证明内容正确、合并成功或用户验收 |

特征词表沿用 `agent`、`tool_kind`、`command`、`mcp_server`、`software`、`skill`、`hook_event`、`file_type`、`domain`。`n` 的单位随特征定义说明，例如按工具调用、Hook 执行还是文件访问计数；Agent 或领域标签的存在标记不能与调用次数相加。`friction`、偏好、任务场景和人格标签属于分析结果，不能拿预设结果反过来当用户事实。

基础统计可以通过这些表的 SQL 或视图生成，不要求已有一张 `metrics` 表。缓存的统计必须同时携带粒度、分母、范围和派生版本；换范围后重新计算。

## 4. L2：用来读过程、原话与证据的输入

### 4.1 `event` 的公共字段

粒度：一条标准事件。一条原始记录可以拆出消息、思考、工具调用与 usage 等多个事件，反之多个流式记录也可以合成一个事件。

| 字段 | 类型与必需性 | 输入解释 |
| --- | --- | --- |
| `event_uid`、`session_uid` | 字符串，必需 | 标准事件身份与所属会话；报告中的证据引用使用 `event_uid` |
| `event_path` | 字符串，目标契约必需 | 原生内容路径或稳定合成路径，用于区别同一记录中的多个事件 |
| `seq` | 会话内唯一整数，必需 | 稳定投影顺序；轨迹按 `(session_uid, seq)` 排列，不按时间戳排序 |
| `ts` | UTC 毫秒或空 | 事件相关的原生时刻；未知时事件仍可参加消息和调用计数 |
| `kind`、`actor` | 字符串，必需 | 发生了什么、由谁产生；两者共同解释，不能只看 user 角色 |
| `turn_uid` | 轮次 ID 或空 | 可重建的轮次关联，首次写入可能尚未派生 |
| `parent_uid` | 事件 ID 或空 | 原生树或已确认父关系；相邻事件不自动构成父子 |
| `call_id` | 原生调用 ID 或空 | 配对提示，作用域由来源声明；可能重复，不等于标准 `call_uid` |
| `text`、`text_truncated` | 脱敏文本或空、`0/1` | 可检索和展示的正文；截断时不能假定余下部分不存在 |
| `attrs` | 对象，必需 | 共有的时间信息和按 `kind` 约定的标准语义字段 |
| `ext` | 对象或空 | 未映射的原生字段，不默认参与计算 |
| `record_uid`、`native_id` | 原始记录 ID 必需、原生 ID 可空 | 回到 L1/L0 的入口与原生标识；一条事件的其他合并来源由 L1 引用追溯 |

`seq` 只在会话内有意义。父子会话靠 `parent_uid`、`root_uid` 和派生调用连接，不把不同会话的 `seq` 拼成全局时间线。重算可能重排 `seq` 或改变事件集合，保存的分析结论应携带输入版本，失效的证据引用需要重建。

### 4.2 `attrs.time`：每条事件的时间解释

| 字段 | 含义 |
| --- | --- |
| `source_field` | `ts` 所依据的原生字段路径；无来源时为空 |
| `semantics` | `created`、`request_start`、`started`、`completed`、`written`、`unknown` |
| `quality` | `reported`、`estimated`、`missing`；`ts=null` 对应 `missing` |
| `reported` | 原始时间字段和值，包括没有选作 `ts` 的其他端点 |
| `timezone`、`timezone_source` | 可选的事件级时区覆盖；否则沿用会话信息 |

`reported` 只表示时间值可直接换算，**不表示一定是动作发生时刻**。`semantics=written` 的两条日志之差只能作为写入跨度。`attrs.order.quality=derived` 的稳定展示顺序也不能证明并发操作的真实完成先后。

节律分析依赖可用时间，流程频次可以依赖稳定顺序。缺时间的事件要在覆盖统计中列出；有界日期统计排除它们并解释数量，不在时间轴上填导入当天。

### 4.3 消息与上下文

| `kind` | 应读取的字段 | 给分析模块的信息与边界 |
| --- | --- | --- |
| `message.user` | `text`、`actor`、`attrs.origin`、`turn_uid` | 原始请求、补充、反馈；`origin` 分为 `human`、`queued`、`notification`、`peer`、`automation`、`injected` |
| `message.assistant` | `text`、`attrs.phase`、截断信息 | 可见回复；过程说明与最终交付分开，不能把 commentary 当最终回答 |
| `context.inject` | `attrs.origin`、来源角色与上下文结构 | 规则、技能清单、环境、MCP 描述等注入材料；不是用户偏好 |
| `reasoning` | `attrs.format`、可见摘要及不透明字段 | 格式为 `text`、`summary`、`encrypted`、`redacted`；加密、签名等不展示、不检索，不作为用户意图 |
| `context.compaction` | 压缩方式、摘要、原生替换或遗忘范围 | 说明上下文改变；压缩摘要不再作为一次真人要求，也不单独证明丢约定 |
| `session.meta`、`setting.change` | 当时的 cwd、模型、档位、权限、上下文容量等 | 恢复事件发生时的设置；当前设置不能反向覆盖历史请求 |

情绪、纠偏、满意度和协作要求默认只消费 `message.user` 中明确的 `origin=human`。排队消息需有真人来源证据才能作为相应的人类行为使用；任务通知、对等 Agent 和系统注入均不进入真人分母。来源尚未确认时保留未知，不能把所有 user 角色消息都提升为真人原话。

问答回执只取用户的 answer，不把 AI 给出的 question、候选选项或解释当成用户要求。用户输入中的代码、引用和系统包装与其本人陈述分开；同一轮、同角色、同内容的界面镜像不重复计数，不同内容的补充仍保留。

以下是为保留当前分析能力提出的**补充约定**；现有 Python 后端已在自己的消息附加数据中保留相关信息，目标 L2 的每类 Schema 仍需接入这些字段：

| 补充字段 | 类型 | 为什么需要 |
| --- | --- | --- |
| `attrs.input_format` | `prompt`、`question_reply` 或未知 | 区分直接请求与澄清答复；仍需结合前文判断任务关系 |
| `attrs.message_digest` | 字符串或空 | 截断前完整规范正文的摘要，用于核对镜像；来源身份和语境仍须一致，不能仅凭相同文本删除不同请求 |
| `attrs.original_chars` | 非负整数或空 | 规范正文在展示截断前的字符数；不是原始字节数，也不是中文词数 |
| `attrs.writing_measurements` | 对象或空 | `reply`、`summary`、`body` 各自的 `chars`、`surface`、`quality`、`complete`；必须在完整正文和可辨边界上计算 |
| `attrs.artifact_body_present` | 布尔或空 | 回复是否含可识别的文件正文；只有链接不能评价文件内容 |

篇幅不足以通过前缀猜全长。截断文本只能给可确认的下界；如果没有正文或摘要边界，对应测量未知。多条连续交付需要保留各自事件 ID，并且不能把人为拼接分隔符算进字数。文档链接、文件写入动作和报告中声称完成都不能代替实际正文或验收。

### 4.4 工具、审批、错误与操作证据

| `kind` | 字段来源 | 输入解释 |
| --- | --- | --- |
| `tool.call` | `attrs.name`、`attrs.category`、参数或输入、调用时 cwd、命令、文件、MCP 与归因 | 实际操作是什么；`category` 对应 L3 的工具 `kind`，工具名称本身不证明调用效果 |
| `tool.result` | `attrs.status`、`exit_code`、原生起止、时长、错误标记与结构化结果 | 发生了什么返回；文本里的普通 `error` 单词不是失败协议 |
| `permission.request`、`permission.decision` | `decision`、`source`、`wait_ms` 及调用关联 | 审批是否发生、谁做决定、等了多久；策略配置不等于每次都弹出审批 |
| `error` | 原生错误类别、重试与中止信息 | 请求或流程的异常事实；与工具结果区分，避免一次错误多次计数 |
| `file.change` | 变更文件、补丁或快照、动作状态 | 编辑、撤销和验证顺序；没有内容或版本链时不能证明代码保留或正确性 |
| `hook.run` | 事件类型、处理器、原生执行结果 | 某 Hook 是否被观察到执行；安装 Hook 不等于执行过 |
| `subagent.spawn`、`subagent.result` | 子会话身份、派生调用、返回状态 | 委派链及回传，和子会话 L3 关系交叉核对 |
| `branch` | fork、rewind、rollback、resume 与来源关联 | 活跃路径和撤销动作；保留历史，不将已撤销或重放段当作新的已完成工作 |
| `plan.update`、`link`、`queue` | 计划、外部关联、排队操作的原生属性 | 支持过程解释；待办完成、链接存在或进入队列都不是最终验收 |

全参数、完整工具输出只在必要时按 `record_uid` 回归档读取。重复调用检测通常只需要安全摘要和归一后的操作信息，不需要把所有代码或文档正文送进分析入口。

以下也是**补充约定**；部分信息已在当前 Python 原型的附加数据中提供，接入目标 L2 时需完善对应 Schema：

| 补充字段 | 用途 | 缺失时怎么处理 |
| --- | --- | --- |
| `tool.call.attrs.argument_digest` | 判断同工具、同参数的重复操作；摘要应由截断前完整参数生成，并注明采用字面还是规范化口径 | 可以统计工具失败，不能确认同参数重试 |
| `tool.result.attrs.status_scope` | 区分直接命令返回、显式工具错误、外层编排、内层命令汇总等范围 | 工具完成只代表已知协议层，不能外推到内层所有命令 |
| `tool.result.attrs.known_command_results`、`failed_command_results`、`unknown_return_values` | 包装调用中已知、失败、未知结果的数量 | 缺失的内层结果保持未知，不能因外层退出 0 判断全部成功 |
| 命令的结构化参数、验证目标与结果引用 | 区分测试、lint、typecheck、build，及 targeted/full 等范围 | 只看到命令头时，可标「出现验证命令候选」，不能确认完整验证覆盖 |
| 操作的原生时长、`duration_source`、`duration_quality` | 解释原生耗时还是日志差估算 | 缺时间时只做次数与顺序分析；不推出等待时长 |

参数摘要相同也可能只是编排外层相同；检测内层重复失败需要对应内层操作身份。预期失败测试、用户主动运行命令、环境错误、审批拒绝与用户打断应按证据区分。不能把三次返回失败直接写成「浪费三次」，也不能将缺失结果理解为操作没有副作用。

### 4.5 `model.usage`：单次值与累计快照

这是模型输入中最容易混算的部分。除了 token、模型、provider、purpose、金额与原始报告，还必须读取下面的计量字段。

| `attrs` 字段 | 取值与输入含义 |
| --- | --- |
| `usage_scope` | `call` 为逐次请求；`session_snapshot` 为会话累计；`session_model_snapshot` 为会话内按模型等维度累计 |
| `measurement` | `call` 对应 `delta`；两类 snapshot 对应 `cumulative` |
| `request_id` | 原生请求身份，可空；snapshot 不虚构请求 ID |
| `snapshot_key` | snapshot 必需的稳定口径键，包含来源、会话、scope、模型、provider、purpose 和原生计费维度 |
| `coverage` | `self`、`root_tree`、`unknown`；是否已经包含子代理 |
| `reported` | 原生 token 与金额字段，不覆盖归一值 |

归一分桶见 3.5；来源缺失时用 `null` 或省略，不补零。只把 `call/delta` 且能确认请求边界的记录派生为 `model_call`。只有累计值的来源仍能提供会话或模型总量，但不能因此推算请求次数、每次 token 或平均请求延迟。

| 来源情形 | 分析采用的口径 |
| --- | --- |
| 完整逐次请求 | 对明确覆盖范围内的单次值求和；多内容块、镜像或重复 token 事件先去重 |
| 同一口径的累计值 | 同一 `snapshot_key`、同一计数周期内，取来源顺序最后可信的快照；不能将多个快照相加 |
| 同范围同时有逐次值与快照 | 选择一套作为总量，另一套用于核对；不能相加 |
| 父快照 `coverage=root_tree` | 已包含子代理，同覆盖指标不能再加子代理请求或快照 |
| 父、子各自 `coverage=self` | 明确身份、排除复制历史且数据完整时，可归并到根会话 |
| `coverage=unknown` 或覆盖不完整 | 已知分项和缺口分列，不输出貌似完整的根会话总量 |

以上选择要**逐指标**进行。例如父快照有成本总额，子会话有 token 明细，不代表 token 与成本拥有同样覆盖。不能因为一个指标完整就给所有指标统一打「完整」标记。

连续快照只有在口径一致、计数周期未重置且两个观测点可定位时才可做差。首次读到累计 8000 token 不表示导入当天用掉 8000；重置需有明确证据，否则计数回退是异常，不输出负用量或补零。只知道一段区间增量时可以描述该区间，不能把它均摊到每天或伪装成一次请求。snapshot 的 `ts` 是原生快照更新时间，不是全部累计用量的发生时间。

### 4.6 上下文容量与运行状态

压缩次数可以直接来自 `context.compaction`。上下文占用率、峰值、等待用户与运行状态还需要额外的原生信号，不能仅凭会话 token 总量计算。

**补充约定：** 分析入口若提供上下文观测，应包含 `session_uid`、可定位的 `event_uid`、`used_tokens`、同一时刻的 `context_window_tokens`、时间与观测来源。当前统一 DDL 没有独立的上下文观测表；具体 L2 属性位置由连接器 Schema 确认后采用，不能把本文描述的逻辑输入冒充已有列。

容量缺失、来源切换窗口或数值不属于同一时刻时，占用率未知。`model_info.context_window` 只是模型上限信息，不保证等于该次运行的有效窗口。工具结果最近写入、锁文件存在和会话状态是运行提示；精确等人时间依赖审批或交互端点，精确等模型时间依赖请求端点。

## 5. 来源、覆盖与全文下钻

分析入口不需要每次带入全部原始记录，但必须能解释这批输入覆盖了什么，并按证据 ID 找回所需材料。

| 表或归档 | 应读取的字段 | 给分析模块的意义 |
| --- | --- | --- |
| `source` | `source_id`、`agent`、`root_path`、`label`、`enabled`、`discovered_at` | 来源与配置身份；路径仅供本机读取，不必原样出现在公开报告中 |
| `source_file` | `file_id`、`source_id`、`path`、`generation`、`role`、`format`、`status`、水位与扫描信息 | 当前读取到哪个文件代次、什么位置，是否仍在上游或发生错误 |
| `raw_record` | `record_uid`、`file_id`、原生位置、哈希、类型、`disposition`、`ref_event_uid`、`note` | 每条原始记录映射、合并、重放、重复、忽略或解析失败的去向 |
| L0 与附件 | 文件代次归档、内容哈希、记录位置、附件引用 | 精确取回正文或原生结构；不通过当前上游文件路径代替历史归档 |

下钻链为 `event_uid → event.record_uid → raw_record → source_file / 对应归档代次 → 原始内容`。合并事件的其他来源通过 L1 的 `folded / duplicate / replayed` 引用追溯。原始记录数不等于事件数、消息数或调用数。

上游已删除但成功归档的文件仍可分析；`gone_upstream` 不等于材料已丢失。相反，`unparsed`、不完整尾帧、未完成回填、未知类型和断裂关联都会影响覆盖，应通过采集诊断与统计说明。只有元数据的来源可以展示会话列表，不能产生正文画像、工具失败率或 token 曲线。

读取截断全文后也沿用样本排除、脱敏和截止边界；归档中的后续记录不能泄漏进早期快照的结论。分析端从 L2 获取默认脱敏文本，需要全文时经同一读取规则取对应片段，不重新扫描所有用户目录。

## 6. 可选输入：已安装清单、生态与模型资料

这些输入帮助解释配置与匹配。没有它们时，用户轨迹的基础统计、画像和瓶颈案卷仍然可以完成。

### 6.1 `inventory_item`：配置中观察到的安装状态

| 字段 | 输入解释 |
| --- | --- |
| `inv_id`、`agent`、`scope`、`project_id` | 安装项身份、适用 Agent、用户/项目/插件等作用域与项目关联 |
| `type`、`name` | Skill、MCP、Hook、规则、插件等类型及名称，名称不是全局唯一键 |
| `config_path`、`config` | 配置出处和可消费的配置结构；只传入匹配需要的字段，不含凭据 |
| `content_hash`、`enabled`、`seen_at` | 内容版本、是否启用、何时观察到；当前观察不能自动代表历史会话当时的配置 |
| `catalog_item_id`、`match_confidence` | 与规范资源的匹配及其置信度；弱匹配不能当作已确认安装同一资源 |

「安装」「启用」「实际注入」「实际调用」是四种不同事实。使用证据来自 `context.inject`、工具归因、Hook 执行等，而不是仅来自安装清单。「已装未用」要求该安装项在所选范围内有效、相应使用信号可被完整观察；否则只能说「本次记录未观察到使用」。

### 6.2 Catalog：能力与版本输入

| 表与字段 | 给分析或后续匹配什么 |
| --- | --- |
| `catalog_item.item_id / type / name / title / summary` | 规范资源身份、类型与能力描述；同名 Skill 不自动合并 |
| `repo_url / repo_path / homepage / license / agents / tags` | 原出处、许可、兼容 Agent 与标签；兼容性需要匹配实际运行环境 |
| `install / popularity / official / status / canonical_of` | 安装说明、热度、官方标识、状态、规范条目关系；热度不是有效性证据 |
| `first_seen / last_seen / latest_version` | 目录观察时间与当前版本，不能代替历史输入版本 |
| `item_version.version_id / item_id / version / commit_sha / content_hash / manifest / body / risk / fetched_at` | 被核对的具体内容版本、清单、正文和执行风险信息；推荐证据引用到版本 |
| `catalog_source.source_id / kind / url / fetched_at / status`，`item_source` 的来源记录 | 数据来自哪里、何时读取、是否可用；资源正文不能修改分析规则 |
| `item_feature(item_id, feature, value, weight, origin)`、`feature_vocab` | 与会话侧共用的能力词表；`origin` 区分声明、规则抽取和模型标注 |
| `item_component`、`item_relation` | 插件组成、依赖、复制或替代关系，防止重复匹配和把组件当成不同能力重复推荐 |

画像与瓶颈的输入不包含「想推荐哪个 Skill」或「预期应该出现哪个标签」。资源目录在这些结果形成后再参与匹配，避免用目录标签倒推用户需求。资源能力、同任务证据和适用范围同时具备，才支持提出一次试用；安装方式是描述输入，不授权分析模块执行安装。

### 6.3 模型信息与公开成绩

| 输入 | 字段 | 使用条件 |
| --- | --- | --- |
| `model_info` | `model_id`、`provider`、`family`、`aliases`、`context_window`、`max_output`、`price`、`reasoning_levels`、`released_at`、`source`、`as_of` | 别名、价格和规格须有来源及版本；未知价格不补零，价格表不直接代表用户账单 |
| `benchmark_result` | `model_id`、`effort`、`harness`、`benchmark`、`benchmark_version`、`score`、`unit`、`measured_at`、`source_id`、`url` | 只在基准、版本、harness、档位与分数单位可比时比较；公开成绩不等于该用户任务的效果标签 |

更细价格桶、额度窗口、资源效果评分、人工 outcome 和偏好标签并非当前统一输入中已存在的事实。后续接入需先有独立来源与 schema；不能从调用次数、沉默或公开分数补造。

## 7. 面向分析工作的输入清单

这里按开发者要回答的问题组织输入，不绑定具体函数或算法。每个结果都应保留有效分母、来源范围与证据 ID。

| 分析工作 | 最小输入 | 支持的结论及缺失处理 |
| --- | --- | --- |
| 概览、项目与模型分布 | `project`、`session`、`model_call`、范围与覆盖 | 报观察到的规模；模型数按规范模型，不能按消息数冒充模型请求数 |
| 任务、读者、语言与协作要求 | 真人 `message.user` 全文或可用片段，相关回复与轮次 | 由当前任务的明确请求提取；标题和中文消息本身不能覆盖明确英文交付要求；缺正文时保留缺口 |
| 用户反馈、纠偏与情绪 | 真人原话、前后回复、任务关系、打断事件 | 识别有上下文的候选信号；沉默、继续、结束会话不能当接受或满意 |
| 工具分布、失败与重复操作 | `tool_call`，对应调用/结果，参数摘要与状态范围 | 报有明确协议支持的次数与失败；缺摘要不能认定同参数重试，缺返回不能认定成功 |
| 效率、等待与并发覆盖 | 工具、请求、轮次的原生起止、时长质量、审批端点 | 区分日志跨度、调用耗时和等人/等模型；只有次数时不输出时间结论 |
| 验证、交付与质量证据 | `file.change`、命令参数及明确返回、最终回复、`link` | 看最后编辑之后是否观察到相应验证；没有完整过程不能断言「没验证」，日志完成不能当用户验收 |
| 摩擦与返工候选 | 真人纠偏、同任务操作链、失败、审批、branch、compaction | 形成可回看的事件案卷；次数只是结构事实，失败原因与效果需要进一步证据 |
| token、缓存与成本 | `model_call`、L2 `model.usage`、scope/measurement/coverage、价格版本 | 按一致计量范围汇总；无逐次值时保留累计总量能力，不伪造逐次趋势 |
| 上下文压力与压缩后变化 | 压缩事件、当时的上下文观测与容量、前后约定和操作 | 压缩次数可数；没有容量不能算压力，没有前后证据不能认定丢约定 |
| 协作、委派与自主过程 | 根/子会话关系、spawn/result、真人输入、工具与非进度回复 | 报委派关系与日志协作密度；子代理注入不增加真人分母，密度不直接等于自主性 |
| 节律、日期与阶段/流程 | 可信 `ts`、展示时区、会话内 `seq`、任务与工具类别 | 日期统计排除时间未知；稳定顺序支持流程频次，但推断并发瓶颈需要真实端点 |
| 原回复与改写比较 | 同任务的原回复正文、修改请求、新版正文、相对评价 | 只能形成可标注的候选对；缺正文或明确比较时不训练偏好，不宣称事实等价或收益 |
| 已装能力与推荐候选 | 使用证据、安装范围、session/item features、固定资源版本、独立画像和瓶颈 | 可以解释适用性和试用理由；未观测使用不等于未用，推荐不等于有效 |

同一会话说十次「讲清楚」，可以是十条消息证据，但只是一个支持会话；任务数按分析派生的任务去重，会话数按主会话去重。场景可在一个会话中共存，场景会话数不能简单相加。分场景的比例采用该场景有效样本分母，不能沿用全局分母。

## 8. 一个可直接讨论联调的输入例子

全部 ID、路径与正文均为虚构。这里展示对象形式；数据表形式具有相同含义。未列出的可空列保持空，不意味着实际查询应丢弃关联字段。

```json
{
  "input_contract": "analysis-input-v1",
  "scope": {
    "project_ids": ["project-example"],
    "from_ts": 1790899200000,
    "until_ts": 1790985600000,
    "display_timezone": "Asia/Shanghai",
    "include_children": true,
    "excluded_session_uids": []
  },
  "coverage": {
    "events": {"status": "partial", "time_unknown_rows": 1},
    "tool_call": {"status": "available", "rows": 1},
    "model_call": {"status": "unavailable", "reason": "示例没有逐次用量"},
    "catalog": {"status": "unavailable", "reason": "本次只做轨迹分析"}
  },
  "projects": [
    {"project_id": "project-example", "key_type": "path", "key": "/example/project", "name": "示例项目", "paths": ["/example/project"]}
  ],
  "sessions": [
    {"session_uid": "session-example", "source_id": "source-example", "native_id": "native-example", "kind": "main", "project_id": "project-example", "parent_uid": null, "root_uid": "session-example", "timezone": "Asia/Shanghai", "timezone_source": "reported"}
  ],
  "turns": [
    {"turn_uid": "turn-example", "session_uid": "session-example", "idx": 0, "trigger": "human", "status": "unknown", "first_event_uid": "event-request", "last_event_uid": "event-result"}
  ],
  "events": [
    {
      "event_uid": "event-request", "session_uid": "session-example", "event_path": "message.content[0].text", "seq": 0,
      "ts": 1790902800000, "kind": "message.user", "actor": "human", "turn_uid": "turn-example", "parent_uid": null, "call_id": null,
      "text": "请修复测试，并解释修改原因。", "text_truncated": 0,
      "attrs": {"origin": "human", "time": {"source_field": "timestamp", "semantics": "created", "quality": "reported", "reported": {"timestamp": "2026-10-02T01:00:00Z"}}},
      "ext": {}, "record_uid": "record-request", "native_id": "message-example"
    },
    {
      "event_uid": "event-call", "session_uid": "session-example", "event_path": "tool.call", "seq": 1,
      "ts": 1790902801000, "kind": "tool.call", "actor": "assistant", "turn_uid": "turn-example", "parent_uid": null, "call_id": "native-call-example",
      "text": null, "text_truncated": 0,
      "attrs": {"name": "shell", "category": "shell", "command_head": "pnpm test", "time": {"source_field": "started_at_ms", "semantics": "started", "quality": "reported", "reported": {"started_at_ms": 1790902801000}}},
      "ext": {}, "record_uid": "record-call", "native_id": "native-call-example"
    },
    {
      "event_uid": "event-result", "session_uid": "session-example", "event_path": "tool.result", "seq": 2,
      "ts": null, "kind": "tool.result", "actor": "tool", "turn_uid": "turn-example", "parent_uid": null, "call_id": "native-call-example",
      "text": null, "text_truncated": 0,
      "attrs": {"name": "shell", "status": "failed", "exit_code": 1, "duration_ms": 900, "duration_source": "reported", "duration_quality": "reported", "time": {"source_field": null, "semantics": "unknown", "quality": "missing", "reported": {}}},
      "ext": {}, "record_uid": "record-result", "native_id": "native-result-example"
    }
  ],
  "tool_calls": [
    {"call_uid": "tool-call-example", "session_uid": "session-example", "turn_uid": "turn-example", "call_event_uid": "event-call", "result_event_uid": "event-result", "name_raw": "shell", "kind": "shell", "command_head": "pnpm test", "status": "failed", "exit_code": 1, "started_at": 1790902801000, "ended_at": null, "duration_ms": 900, "duration_source": "reported", "duration_quality": "reported", "approval_wait_ms": null}
  ],
  "model_calls": []
}
```

这个例子支持「观察到一条真人请求、一条配对工具调用和明确失败返回」。调用开始在区间内，因此能取其返回作为关联材料；返回时间未知，不能按返回日期统计。原生报告的 900 ms 可以用于该调用耗时，但缺完成端点，不能把它放进有可信起止的区间并集；不能用开始时间加耗时补成一个原生完成时刻。没有助手交付和用户反馈，不能判断测试最后是否修好、用户是否满意。没有逐次用量，token 和成本保持未知。

如果另有累计快照，示意输入为：

```json
{
  "usage_scope": "session_model_snapshot",
  "measurement": "cumulative",
  "snapshot_key": "source-example/session-example/model-example/main-cycle",
  "request_id": null,
  "coverage": "root_tree",
  "model": "model-example",
  "provider": "provider-example",
  "purpose": "main",
  "input_tokens": 6000,
  "cache_read_tokens": 1000,
  "cache_write_tokens": 0,
  "output_tokens": 1000,
  "reasoning_tokens": 200,
  "reported": {}
}
```

这是某个计数周期下的根会话树累计总量 8000 token。它仍需放在 L2 `model.usage.attrs`，保留事件身份、原生时间和真实 `reported`；不能填进 `model_calls` 生成一条请求，也不能和同覆盖逐次请求相加。实际 `snapshot_key` 由数据层按完整原生维度生成，示例字符串只用于说明。

## 9. 联调时要核对的输入条件

这些是数据提供方与分析实现者的共同验收点，不要求每位开发者重写采集测试。

| 情形 | 期望输入与行为 |
| --- | --- |
| 正常主会话与子代理 | 工具与模型关联可追溯，根会话聚合不多算复制历史，子代理不增加真人分母 |
| 镜像、fork 与跨 Agent 导入 | 原始记录仍有记账去向，标准事件不重复；fork 新行为保留，import 默认排除 |
| 时间缺失、回退或写入时刻 | 顺序由 `seq` 决定，时间与质量一致；缺端点不输出精确等待、节律或墙钟耗时 |
| 返回缺失与包装调用 | 未配对规模保留，状态范围明确，外层成功不抹掉内层未知或失败 |
| 逐次值与累计快照同时出现 | 每指标选择一致覆盖的口径，快照不生成虚构请求，不重复计入子代理 |
| 正文截断或只交付文件链接 | 保留截断与全文读取能力，篇幅仅用完整测量或下界，正文缺失不评价内容 |
| 元数据来源或尚未完成回填 | 数据集状态为不可用或部分可用，不能用零填出完整分析 |
| 项目、模型、时间和场景筛选 | 统计成员、上下文证据和样本边界各自明确；要求、回复与反馈不会因筛选错配 |
| 排除评测与自身分析会话 | 导入策略和查询都沿用排除边界；预期标签、评审结果不会进入画像证据 |
| 解析升级与重算 | L2/L3 在同一版本上读取，全部事件外键可追溯，旧结论和缓存按输入版本失效 |

输入若只缺某项可选能力，继续生成其他有证据支持的结果；报告具体的数据缺口。身份冲突、错配、混用版本或突破样本边界属于不可接受的输入，先修复该批读取结果，再计算受影响的分析。

## 10. 当前实现进度与接入差异

核对范围为 2026-10-02 下列提交。本 PR 从 `main` 新建，仅增加说明文档与入口链接，不携带其他开发分支的实现。文档采用固定提交来源，相关 PR 合并前也能查到依据。

| 来源 | 当前状态 | 接入本文时应注意 |
| --- | --- | --- |
| [数据获取与标准化方案，`f377366`](https://github.com/ActionMesh-AI/Hackathon/blob/f3773669f95f90ba88576e0e06b29c71d11091a4/docs/plan/data-acquisition.md)（[PR #6](https://github.com/ActionMesh-AI/Hackathon/pull/6)） | L2 身份、可空时间、usage 粒度、L3 基础表与 Catalog 的目标设计 | DDL 是草图，不表示全量实现；本文使用它的字段含义，补充分析入口的消费要求 |
| [连接器 DDL，`d3351bb`](https://github.com/ActionMesh-AI/Hackathon/blob/d3351bb5559ccf079cb68e636d18f3b14b2229fc/packages/connectors/schema/001.sql) 与 [事件 Schema](https://github.com/ActionMesh-AI/Hackathon/blob/d3351bb5559ccf079cb68e636d18f3b14b2229fc/packages/connectors/schema/events.schema.json) | 已建立本地归档、记账、数据库和 Schema 基础；该提交尚未提供具体 Agent 解析器 | `event.ts` 仍必填且无 `event_path`；严格 attrs 尚未接入统一 time 和 usage scope；缺部分会话/工具质量字段、目录和基础特征表。不能在旧 Schema 下直接写入本文扩展字段 |
| [分析后端数据类型，`b996c79`](https://github.com/ActionMesh-AI/Hackathon/blob/b996c79b46605ce0181e4437c78de732ad01389d/src/tandem_backend/models.py) 与 [存储](https://github.com/ActionMesh-AI/Hackathon/blob/b996c79b46605ce0181e4437c78de732ad01389d/src/tandem_backend/store.py)（[PR #5](https://github.com/ActionMesh-AI/Hackathon/pull/5)） | 已用 Codex 日志生成分析原型，采用自己的 `sessions/events` 与消息附加数据 | 表名、ID、事件类型、ISO 时间和目标 L2/L3 不同，尚未直接消费 `orbit.db`。现有 cwd 项目与事件模型筛选也不能直接替代仓库级项目和逐次模型口径 |
| [后端导入器](https://github.com/ActionMesh-AI/Hackathon/blob/b996c79b46605ce0181e4437c78de732ad01389d/src/tandem_backend/importers/codex.py)、[画像说明](https://github.com/ActionMesh-AI/Hackathon/blob/b996c79b46605ce0181e4437c78de732ad01389d/docs/backend/profiling.md)、[过程架构](https://github.com/ActionMesh-AI/Hackathon/blob/b996c79b46605ce0181e4437c78de732ad01389d/docs/backend/architecture.md) | 已有镜像核对、问答回执、参数摘要、状态范围、完整篇幅测量与样本隔离等逻辑 | 接入统一表时保留这些信息和边界；旧原型只排除部分非用户来源，不能替代目标契约的全部来源分类。累计 token 也不能直接当 `model_call` |

建议先接通「范围与覆盖 + 主会话 + 真人消息 + 回复 + 配对工具」的最小输入，保持原型已有的证据与隔离能力；再按实际数据层进度接入逐次模型、快照、基础特征、安装清单与 Catalog。分析开发者可先用本文的虚构对象和自己的构造案例实现输入消费，来源尚不支持的能力明确返回未知。具体算法和模块范围仍沿用团队确认，不因某个字段出现在本文就扩大 MVP。

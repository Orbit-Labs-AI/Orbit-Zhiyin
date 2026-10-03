# 本地数据服务：检索、resume、能力、占用与清除、脱敏规则、insights

本文说明 `orbit_data` 在导入主链之外提供的只读服务（清除除外）。它们读取已发布的投影 `orbit.db`，不改 L0–L3 数据，不联网，也不读取 Agent 目录；`insights` 只读调用方显式给出的目录。

| 功能 | 模块 | CLI | HTTP |
| --- | --- | --- | --- |
| DT-23 统一检索 | `search.py` | `search <q> [--source-id …] [--from-ts] [--until-ts]` | `GET /v1/search?q=&source_id=&from_ts=&until_ts=&limit=&offset=` |
| DT-24 resume 命令 | `resume.py` | `resume --session <session_uid>` | `GET /v1/sessions/{session_uid}/resume` |
| DT-22 来源能力 | `capabilities.py` | `capabilities [--refresh]` | `GET /v1/sources/capabilities?refresh=` |
| DT-15 分层占用 | `maintenance.py` | `storage` | `GET /v1/storage` |
| DT-03 / DT-15 清除全部 | `maintenance.py` | `purge --confirm "DELETE ALL LOCAL DATA"` | `POST /v1/storage/purge {"confirm": …}` |
| DT-10 规则清单 / 预览 | `privacy_rules.py` | `privacy-rules`、`privacy-preview --text …` | `GET /v1/privacy/rules`、`POST /v1/privacy/preview {"text": …}` |
| DT-18 `/insights` 对照 | `insights.py` | `insights --path <usage-data> [--match]` | 不提供（路径须由本机用户显式给出） |

CLI 形如 `uv run orbit-data --home .orbit search "修复第 7"`。这些子命令在打开可写 `Store` 之前处理，不会建库或迁移。HTTP 路由在 `orbit_backend/api/data_routes.py`，由 `register(app, home)` 挂载；`api/routes.py` 未改，集成时在 `create_app` 末尾加一行 `data_routes.register(app, canonical_home)`。

## 检索（DT-23）

- **命中来源**：消息与标题事件（`message.user`、`message.assistant`、`session.title`）、`session.title`、项目名、`tool_call.command_head`（只含程序头，如 `git status`、`ruff`）、`tool_call.files`。工具输出不参与检索。
- **引擎**：库中存在带 `text` 列的 `event_search`（trigram FTS5，`content='event'`，rowid 与 `event` 对齐）时，长度不小于 3 的查询走该表，支持中文和任意子串。否则 `event_fts`（unicode61）处理整词；含非 ASCII 字符或少于 3 个字符的查询改走限定消息 / 标题类事件的 `LIKE` 回退，按时间倒序，最多 `max_hits` 条（默认 1000）。`LIKE` 的 `%`、`_` 按字面匹配。
- **过滤**：`source_ids` 按 `session.source_id` 过滤；时间窗对消息用 `event.ts`，对工具调用用 `tool_call.started_at`（缺失时取会话开始时间），对标题和项目用 `session.started_at`。不同来源的命中互不重叠，所以分来源计数之和等于合并计数。
- **排序**：相关度 × 类型权重（标题 3、项目 2、命令和文件 1.5、消息 1）× 时间衰减（半衰期 30 天，保底 0.25；无时间戳的命中直接取保底，不优于任何有时间的同类命中）。相关度对 FTS 命中由 bm25 映射到 [1, 2)，对 `LIKE` 命中固定为 1。这些常量是产品默认，未用真实点击数据校准；依据是 `packages/data/tests/test_search_ranking_eval.py` 中 12 条手写成对偏好与参数网格：保底必须大于 0（否则归档会话按标题搜不到），标题权重在网格上只能取 3 或 4，半衰期 7–90 天都可行，出厂值位于可行域中部。
- **返回**：`total`、`truncated`、按类型的 `counts` 和分页后的 `hits`。每条命中包含 `session_uid`、`source_id`、`agent`、`title`、`project`、`hit_type`、`event_uid` 或 `call_uid`、`ts`、`score`、`snippet`。片段先在匹配点前后 2000 字符的窗口内重新执行 `privacy.redact`，再截取，所以落在窗口边缘的密钥也能识别。
- **实测**（med 合成数据：900 个会话，77,403 个事件，`orbit.db` 约 404 MiB；Apple M4 Pro 14 核 48 GB；并行任务同时占用 CPU，负载约 32；每个查询取 3 次中的最好值）：
  - 无 `event_search` 表：中文子串（走 `LIKE` 回退）33–43 ms，英文词、命令头、项目名 3–11 ms。
  - 在副本上临时建 trigram `event_search` 表（只收录消息和标题，建表耗时 0.7 s）：中文子串 23–43 ms；2 字符查询仍走 `LIKE`，约 78 ms。
  - 两条路径的命中数一致。

## resume（DT-24）

`resume_template(agent, native_id, …)` 是纯函数，只拼字符串，从不执行。返回 `argv`、可展示的 `command`（需要时带 `cd <cwd> &&`），以及上游出处 `evidence`。

| Agent | 模板 | 出处 |
| --- | --- | --- |
| claude_code | `claude --resume <id>` | Claude Code CLI |
| codex | `codex resume <id>` | `third_party/codex` 的 `Resume` 子命令 |
| opencode | `opencode --session <id>` | `third_party/opencode` 中 `tui.ts` 的 `session` 选项 |
| pi | `pi --session <会话文件>` | `third_party/pi` 中 `args.ts`；文件路径取自 `raw_record → source_file` |
| hermes | `hermes --resume <id>` | `third_party/hermes-agent` 中 `sessions_cmd.py` |
| dsh | `dsh tui --resume <id>` | `third_party/deepseek-harness/apps/cli/README.md` |
| kimi | `kimi --session <id>` | 未 vendored，`verified=false`，需按本机安装版本确认 |

`status='active'` 的会话仍返回命令，但 `disabled=true`。以下情况返回 `supported=false` 并给出原因：子代理或其他非 main 会话（应从根会话 resume）、缺少 id、cwd 或会话文件、id 以 `-` 开头或包含控制字符。

## 来源能力（DT-22）

`capabilities(home)` 返回两部分：

- 静态矩阵：7 个 Agent 对 `hooks / skills / mcp / subagents / headless` 的支持情况（`supported / partial / unsupported / unknown`），每项附出处。
- 来源信息：从投影读取各来源最近一次会话的 `harness_version`、出现过的版本列表、会话数，以及实际观测到的次数（hook 事件、skill 和 MCP 调用、子代理会话）。

结果缓存在 `<home>/cache/capabilities.json`（权限 0600），有效期 24 小时。指纹由最新 `projection_run`、来源数和最近 inventory 扫描组成，任一变化即重新计算；`refresh=true` 强制重算。数据目录不存在时不会为写缓存而创建它。

## 占用与清除（DT-15 / DT-03）

`storage_usage(home)` 返回各层字节数：

- `l1` / `l2` / `l3` / `fts` / `inventory` / `other` 来自 `dbstat`（aggregate 模式），按表归并，索引计入所属表。这几层之和等于 `dbstat` 总量，再加 `free`（空闲页）等于 `page_count × page_size`。
- `wal` 是 WAL、SHM 和 journal 文件。
- `raw` 是 `raw/` 下的普通文件，遍历时不跟随符号链接。

同时返回逐表字节数。med 库（404 MiB）在页缓存热时约 110 ms。首次调用要读遍所有页，冷缓存时实测 1.8 s，CPU 和 IO 繁忙时实测 5.2 s；full 规模（约 2.8 GB）的冷缓存耗时未实测，按体积估计会更长，前端应异步加载。

`purge_all(home, confirm)` 只删除 `orbit.db`、`-wal`、`-shm`、`-journal`、`raw/` 和 `cache/capabilities.json`，`catalog.db` 等其他文件保留。删除前先完成全部检查，任一项不通过即拒绝，且不删除任何文件：

- 确认词不完全等于 `DELETE ALL LOCAL DATA`；
- 数据目录本身是符号链接，或是文件系统根目录、用户主目录；
- 目录里既没有 `orbit.db` 也没有 `raw/`；
- 删除集合中出现符号链接，或有路径解析到数据目录之外；
- 导入锁 `import.lock` 被占用（HTTP 409）。

清除后可以直接重新 `Store(home)` 初始化。HTTP 服务进程若仍持有旧库连接，旧连接只能看到已被删除的文件，需在集成层重开连接（见风险）。

## 脱敏规则（DT-10 MVP，只读）

`rules()` 按 `privacy.redact / sanitize` 的执行顺序列出 9 条固定规则：

- JSON 凭据键
- 身份字段删除
- 认证头
- PEM 私钥
- 已知格式 API Key
- Bearer 令牌
- 凭据赋值
- URL 凭据
- 结构化不透明载荷

每条规则带 `id / category / scope / marker / description / example`，MVP 中都不可关闭或编辑。`preview(text)` 直接调用 `privacy.redact`，按替换标记类型计数，输入里已有的标记不计入；结果不落库，最多 100,000 字符。测试断言预览结果与仓库现有脱敏样例经 `redact` 处理后的结果逐字一致。

## insights（DT-18）

`read_usage_data(path)` 只读解析显式给定目录下的 `session-meta/*.json` 与 `facets/*.json`，也接受 `usage-data` 的上级目录，没有默认路径。以下文件记入 `errors` 后跳过：损坏的 JSON、顶层不是对象、超过 2 MiB、非普通文件（含符号链接）。所有值经过 `privacy.sanitize`。

`match_sessions(home, report)` 按 `native_id` 匹配 Orbit 中 Claude Code 的 main 会话，并列出 insights 的数值字段（如 `tool_counts`），以及 Orbit 的工具次数、按工具计数和真人消息数，供 EV-01.1 一次性对照。insights 字段在 Claude Code 各版本间是否稳定尚未验证（V20），读取器不假设固定字段名。

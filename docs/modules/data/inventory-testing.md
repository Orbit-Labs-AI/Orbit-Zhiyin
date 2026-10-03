# 安装清单扫描：测试方案与验收标准

本文定义本仓库安装清单模块的验收标准，覆盖七个内置 Agent connector、SQLite 快照、CLI 和分析接口。它是工程验收依据，不是外部认证，也不代表已验证所有 Agent 版本或整台机器的运行时状态。

实现与使用说明见 [本机安装清单](local-inventory.md)，字段含义见 [数据契约](../../contracts/data.md)。初次验收针对 scanner `1.1.1`，存储 `user_version=5`，分析输入仍为 `analysis-input-v1`。

后续 scanner `1.2.0` 的真实漏项、修正和新增回归见 [完整性复核记录](inventory-audit.md)。初次验收结果仅代表当时列明的路径，不能代替来源完整性验证。

## 1. 什么才算通过

必须同时满足以下条件：

1. 七个内置 connector 都能通过相同 CLI/API 扫描显式指定的来源，不需要访问真实用户目录。
2. 对支持的静态格式，输出名称、类别、启用状态、证据类型、来源路径和定位符符合构造样本的独立预期。不能仅断言“没有抛异常”或“返回非空”。
3. 未扫描、观察到零项、格式不支持、读取失败、静态无法确认分别表达。坏文件不得让健康来源的事实丢失，也不能被悄悄当成空配置。
4. 更新、删除、历史截止、项目筛选、并发读取和失败回滚符合下述快照契约。
5. 来源文件不被修改，凭据不会被打开，配置正文与命令参数不落库；扫描不执行插件／Hook／表达式、不连接配置中的远程资源。
6. SQL 约束、生成的字段字典和解码后的实际数据一致；分析端不能丢掉 inventory 或扫描诊断。
7. 所有仓库规定的验证命令通过。若修改实现或修复失败，再运行受影响的验证；通过后不为增加数字而重复扩大测试范围。

**不允许**通过删除失败用例、忽略未知格式、把 `null` 改为 `false/0`、放宽目录权限、隐藏 diagnostics，或把所有 coverage 写成 available 来“通过”。

## 2. 覆盖语义标准

| 情况 | 条目与覆盖结果 | 判定原则 |
| --- | --- | --- |
| 没有符合查询范围的扫描 | `items=null`、整体 `unavailable`，原因为 `no_inventory_scan` | 不能声称观察到零项；也适用于显式选择的项目从未扫描 |
| 已扫描、支持类别没有条目 | 该类别 `available`、`rows=0` | 只针对所选根与实现支持的布局，不推断整台机器未安装 |
| Agent 没有已实现的静态类别 | 该类别 `unavailable`、`rows=null` | Pi/OpenCode 的动态 Hooks、定时任务属于此情况 |
| 坏配置、权限、越界链接、触限 | 受影响类别 `partial`，附 diagnostics | 保留可读取的健康观察；不能声称完整 |
| 根目录缺失 | 所支持类别标记部分覆盖，并记录 `root_unavailable` | 扫描未成功观察该根，空条目不能用于证明没有安装 |
| 可选默认文件不存在 | 不单独报错 | 如没有 `hooks.json`，允许在当前静态布局中观察到零项 |
| 配置显式引用的必需文件缺失 | `partial`、`missing_reference` 或具体 manifest 诊断 | 与上一行有意区分，例如 DSH Hook 的 `configPath` |
| 一次失败后成功重扫 | 最新扫描的诊断清空，旧快照仍保留旧诊断 | 不把旧错误当作当前错误，也不改写历史 |

扫描命令返回的 `status=available` 表示该扫描没有读取错误；**不等于所有六类都可确认**。读取清单的整体 coverage 汇总各来源／类别：任一类别不可用或部分覆盖时，整体保持 partial。调用方应查看 `scans[].coverage` 与 `scans[].diagnostics`。

`rows` 是观察条数，不是去重后的安装数量。配置声明、登记表记录与缓存记录可以指向同一个插件，不能简单相加后作为“安装数”。

## 3. 七个 Agent 的独立预期

下表是验收输入与预期，不从扫描器的 `SUPPORTED` 自动生成，以免实现和测试犯同一个错误。

| Agent | 主测试入口 | 必须能验证的事实 | 不能过度推断 |
| --- | --- | --- | --- |
| Codex | `config.toml`、Skills／规则、插件缓存、automation TOML | 六种类别、禁用 Skill/MCP、缓存组件、暂停任务 | 缓存不证明正在启用；当前配置不证明历史使用 |
| Claude Code | settings、`.mcp.json`、显式 `.claude.json`、安装登记 | Hooks 总开关、安装证据、全局与项目 MCP、敏感账号字段不落库 | 不自动读取所选根之外的账号文件 |
| DSH | Cordis YAML、profile package/bundle、Hook 引用、schedule JSON | 静态插件与 MCP、profile 隔离、任务状态、动态表达式诊断 | 不执行 `!!js`，不求解整个运行时继承和 patch 顺序 |
| Pi | settings、extensions、Skills、MCP JSON | package/extension 声明、扩展文件、MCP 禁用、额外 Skill 引用 | 扩展代码内动态注册的 Hook/调度器仍未知 |
| Hermes | config YAML、profile、plugin/HOOK manifest、cron JSON | profile 配置、禁用规则、插件组件、暂停任务 | manifest 的存在不证明 handler 实际运行成功 |
| OpenCode | JSONC 与 v1/v2 配置、插件文件 | 注释／尾逗号、两版 MCP 与插件字段、Skill/规则路径 | 不执行配置中的环境变量或文件插值；配置根不同于会话数据根 |
| Kimi | config TOML、安装注册表、manifest、cron 文件／wire | 插件总开关与组件状态、旧任务被日志删除、健康会话保留 | 已持久化的 cron 不代表会话已恢复或正在执行 |

每个 Agent 都有非空 CLI 验收：构造一个禁用的 MCP 和一个规则文件，断言精确名称、`enabled=0`、`evidence=configured`、Agent 标识、类别覆盖、快照 ID 与条目数量。重复扫描还须保持同一位置观察的 ID 和哈希稳定，且来源字节与 mtime 不变。

## 4. 快照、标识与时间标准

- `inv_id` 标识同一来源、类别、文件路径与 locator 的观察位置。内容改变时 ID 保持、hash 改变；移动文件、改变数组索引或改变来源归属时，不保证语义身份不变。
- 每次显式扫描生成独立快照。重扫 B 不能删除 A 的观察；两次扫描时间戳相同时，用后一次 scan_id 确定该来源的最新快照。
- 最新快照反映删除；旧快照仍可查。失败扫描可以发布 partial 观察，但不得用旧的完整结果假装当前扫描成功。
- 历史截止为 `observed_at < until_ts`，边界不包含等于截止时刻的快照；每个来源分别选取符合条件的最后快照。
- inventory 是截止时间前最后一次配置观察，**不是**会话时间窗口内的事件统计。因此 `from_ts`、模型和会话筛选不删掉全局观察；显示时区不改变 UTC 毫秒截止结果。
- 指定项目时保留全局和关联项目的观察；无关联的项目配置不能混入其他项目。Claude 账号文件内部的项目 MCP 也须遵守该规则。
- 会话 projection rebuild 不删除清单；只读访问旧版数据库不自动执行迁移。
- 一个写事务发布扫描与全部条目。插入中途失败必须回滚；有其他 writer 时拒绝本次扫描且不多出快照。已有读事务在新写事务提交后仍看到原快照；新读事务看到更新。

## 5. 隐私与输入边界标准

| 边界 | 测试方法 | 必须满足 |
| --- | --- | --- |
| 来源只读 | 扫描前后保存所有样本文件字节和 mtime | 完全相同；不要求文件系统 atime 不变 |
| 凭据不读取 | `AGENTS.md` 链接到九类凭据路径，监视 `Path.open` | 即使授权父目录也不得打开目标；只返回安全诊断 |
| 目录授权 | 越界链接与已授权共享目录分别构造 | 默认拒绝；授权后允许正常资源；凭据禁令不被授权覆盖 |
| 不执行、不联网 | 原生 CLI 验收中阻止 `Popen`、`os.system`、`socket.create_connection` | 扫描仍通过；原有样本同时包含插件代码、命令和远程声明 |
| 不落盘敏感正文 | 在 env/headers/args/prompt/账号等字段放唯一哨兵，检查数据库和 raw 目录 | 哨兵不进入数据库，raw 归档为空 |
| 非普通文件 | 将配置入口建成 FIFO | 在打开前拒绝，不能阻塞等待管道输入 |
| 解析边界 | 非 UTF-8、YAML 对象标签／别名、非法结构、畸形 URL、无法展开的用户目录 | 报告 partial，健康文件继续发布，不输出解析器携带的原文 |
| 资源上限 | 构造文件大小、目录项数、路径深度、结构深度超限 | 明确 partial 和相应诊断；不能完整返回零项 |
| 写入目的地 | `--home` 放入主来源根或 `--allow-root` | CLI 在创建数据库前拒绝 |

测试中的进程／网络拦截覆盖常见调用边界，不等价于对任意未来实现的操作系统级隔离证明。符号链接测试也不构成恶意进程并发替换文件的 TOCTOU 安全审计。

## 6. 可执行测试矩阵

新增主验收文件为 [`test_inventory_acceptance.py`](../../../packages/data/tests/test_inventory_acceptance.py)，参数化后共 50 项。用例 ID 写在测试 docstring 中，便于把标准和失败输出对应起来。

| ID | 测试函数后缀（均以 `test_acceptance_` 开头） | 主要判定 |
| --- | --- | --- |
| INV-01 | `native_cli_facts_coverage_and_source_readonly` | 七个 Agent 的独立精确事实、coverage、重复扫描、只读、不执行、不联网 |
| INV-02 | `content_changes_keep_identity_and_isolate_sources` | 内容哈希、ID 稳定、多来源隔离、相同时间戳与截止边界 |
| INV-03 | `reader_snapshot_and_single_writer` | WAL 读一致性、query-only、writer 排他、失败不发布 |
| INV-04 | `sql_contract_rejects_invalid_facts` | 非法类别／证据／布尔状态／JSON／FK 被拒绝，实际行符合字段字典 |
| INV-05 | `unknown_enablement_is_not_false` | 仅原生 bool 能成为 0/1；缺失和错误类型保持 null |
| INV-06 | `credential_targets_never_opened` | auth、mcp-auth、env、credentials、backups、OAuth、密钥目标不可读取 |
| INV-07 | `fifo_and_invalid_utf8_do_not_block_or_abort` | 非普通文件与解码失败不会阻塞或吞掉健康规则 |
| INV-08 | `resource_limits_publish_partial` | 四类触限均有明确诊断 |
| INV-09 | `malformed_urls_do_not_abort_valid_siblings` | URL 解析失败被隔离，其他观察保留 |
| INV-10 | `unresolvable_home_reference_is_diagnostic` | `~user` 展开失败被隔离 |
| INV-11 | `missing_explicit_dsh_inputs_are_not_known_empty` | 声明输入缺失不能算完整观察到零项 |
| INV-12 | `cli_rejects_source_overlap_before_creating_database` | 非法写入目的地在建库前被拒绝 |
| INV-13 | `old_database_read_does_not_implicitly_migrate` | v4 只读兼容，不偷偷升级 |
| INV-14 | `schema_names_do_not_change_existing_call_coverage` | 生成文件一致；不同表的同名字段不会互相污染 |
| INV-15 | `declared_shapes_and_future_versions` | 七类来源的合法／非法结构和未来版本边界 |
| INV-16 | `failed_scan_recovery_replaces_diagnostics` | 错误恢复与历史诊断保留 |

原有专项测试继续作为验收的一部分，不用同样的断言重新堆叠用例：

| 文件 | 已覆盖内容 |
| --- | --- |
| [`test_inventory.py`](../../../packages/data/tests/test_inventory.py) | 六类别、缓存与安装区别、删除／历史、共享链接、循环、坏配置、权限失败、项目筛选、v4→v5 迁移、rebuild 保留、写入事务回滚 |
| [`test_inventory_agents.py`](../../../packages/data/tests/test_inventory_agents.py) | connector 注册齐全、七种空目录、各 Agent 复合原生样本、profile 隔离、JSONC 两版、YAML 标签／别名、Kimi cron 覆盖与删除、组件禁用、CLI 与项目归属 |
| [`test_inventory_input.py`](../../../tests/integration/test_inventory_input.py) | inventory 与 inventory_scans 透传、内容指纹更新、健康／失败来源的诊断保留、显示时区与会话／模型筛选不改变配置观察截止结果 |

## 7. 执行步骤与发布门槛

所有用例均在 pytest 临时目录中构造数据，不依赖用户 HOME、不调用真实 Agent，也不需要网络下载测试资源。解析依赖来自仓库的统一锁文件。

开发时运行聚焦套件：

```sh
uv sync --locked --all-packages --dev
uv run pytest -q packages/data/tests/test_inventory.py \
  packages/data/tests/test_inventory_agents.py \
  packages/data/tests/test_inventory_acceptance.py \
  tests/integration/test_inventory_input.py
```

定位某一标准：

```sh
uv run pytest -q packages/data/tests/test_inventory_acceptance.py \
  -k malformed_urls --tb=short
```

提交前按最新 workspace 要求运行一次完整检查：

```sh
bash scripts/bootstrap.sh
pnpm check
```

`pnpm check` 包括 TypeScript producer 构建、Python 全套、Swift 客户端、原型产物、文档链接和 wheel 安装后验收；原型未修改时不额外运行 UI 浏览器行为测试。

修改数据库字段字典生成逻辑时，重新生成 `packages/data/src/orbit_data/schemas/tables-v1.schema.json` 并验证实际行；本轮不改变 DDL 或事件 schema。最新 workspace 的 `pnpm check` 统一执行 TypeScript connector 检查，再运行 Python 桥接回归，避免因缺少产物静默跳过。下表保留重构前验收的执行记录。

2026-10-02 本轮实际执行结果：

| 检查 | 结果 |
| --- | --- |
| 锁定依赖同步 | 通过 |
| Ruff lint / 数据包格式检查 | 通过 |
| 后端完整测试 | 1,078 passed；现有 Starlette 弃用警告 1 条 |
| 数据包完整测试 | 180 passed |
| Workspace 全包构建 | 通过 |
| `orbit demo` | 通过 |
| `orbit evaluate` | readability 8/8、pipeline 34/34、probe 12/12；human acceptance 仍为 pending |
| `git diff --check` | 通过 |

其中本轮新增 50 项数据验收测试和 2 项分析透传／时间范围测试。所有新增用例均正常运行，没有使用 skip 或 xfail 掩盖失败。本表是本轮执行记录，后续版本须重新运行相应检查，不能把旧结果当成新版本认证。

本轮新用例首先复现并修复了以下缺陷：

- inventory 的字符串 locator 被生成字典误标为数组；同名 coverage 还错误影响了 model_call 和 usage_snapshot 的字符串列。已改为按表区分字段类型。
- 畸形 URL 与无法展开的 `~user` 引用会中止扫描。已改为安全诊断，其他有效文件仍可发布。
- DSH 明确引用但不存在的 Hook／bundle patch 被当作可选缺失文件。已区分必需引用与可选发现入口。

## 8. 测试不能证明的内容

本轮不执行真实本机全量扫描、第三方代码运行、远程 MCP 握手或 Agent 运行时对照。因此通过表示**所列静态契约和构造输入**满足验收，不表示已安装资源实际可用、存在某项历史调用、任务正在运行、推荐产生收益，或所有上游未来版本均兼容。

同样不将测试数量当作行覆盖率，不宣称覆盖率 100%，也不设置未经测量的性能 SLA。若需要发布前真实目录验收，应单独明确授权根目录，在本机核对 inventory 与原生管理界面，只记录脱敏计数与差异；真实配置、会话、数据库和归档不得提交。

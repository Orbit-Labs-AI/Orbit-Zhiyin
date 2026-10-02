# 本地数据模块与 Mac App

本版将 Advance 的开屏导入、数据源、会话、事件证据、分析、安装清单与存储维护接到 Python canonical 数据层。离线设计 Demo 保持独立；访问本机服务 `/app` 才进入真实数据模式。Lite 的独立设计文件未改动。

## 构建与启动

构建机器使用 Python 3.13、uv、Node/pnpm 和 Xcode Command Line Tools。成品用户不需要这些工具。当前产物为 Apple Silicon，macOS 15 是编译目标；其他 macOS 版本和 Intel 未做实机验收。

```sh
uv sync --locked --all-packages --dev
pnpm --dir docs/design/demo install --frozen-lockfile
uv run python apps/macos/build.py
open .local/macos-build/Tandem.app
```

产物为 `.local/macos-build/Tandem.app` 和 `Tandem.zip`。包内有原生 AppKit/WKWebView 宿主、冻结的 Python 运行时、全部后端依赖、DDL/Schema/资源目录和离线 Advance HTML。构建中用到 PyInstaller 6.22.3；它只是打包工具，不建立第二份应用依赖锁。

默认数据目录是 `~/Library/Application Support/Tandem`。演示和验收使用独立目录：

```sh
open -n .local/macos-build/Tandem.app --args --home /absolute/private/demo/data
```

本地默认 ad-hoc 签名，构建脚本执行完整签名校验。对外分发需要配置 `TANDEM_SIGN_IDENTITY`，以及可选的 `TANDEM_NOTARY_PROFILE`（已有的 notarytool keychain profile）；脚本将使用 Developer ID、Hardened Runtime、公证和 stapling。当前环境没有 Developer ID 身份，本地运行通过不等于已公证分发。

当前是独立分发的非 Sandbox App。系统目录选择器会保存 bookmark；来源扫描仍只使用用户选择的根目录和白名单。Mac App Store/Sandbox 的容器、helper entitlement 与权限传递需要单独发布目标，不能直接宣称此包已经支持。

## 运行组成

```text
AppKit / WKWebView
  ├─ 系统目录选择、导出保存面板、窗口控制
  └─ 启停本地 Python helper、就绪检测、异常提示
          ↕ 带每次启动随机令牌的 loopback HTTP
DesktopService + FastAPI
  ├─ 单一任务队列、可取消导入、原范围重试
  ├─ 来源与设置、任务日志、15 秒可选轮询
  ├─ 只读分页、分析缓存、安装清单、备份/校验
  └─ ImportService → L0/L1 → Python canonical L2/L3
          ↕
tandem.db / raw / app-state.json
```

`application.py` 是应用生命周期边界；`app_api.py` 只做路由、请求校验与查询编排；`app_contracts.py` 为来源、任务、进度和存储提供可生成客户端的 OpenAPI 响应结构。原有 `/v1/analytics/*` 保持兼容。

helper 仅绑定 `127.0.0.1` 的动态端口。令牌由原生宿主产生，通过子进程环境和 WKUserScript 传递，不放在日志、命令行或页面 URL 中；除无数据的 `/app` 外所有接口均需要 Bearer token，另检查 Host 和 Origin。WebView 为非持久存储，页面禁用外部字体及外部网络资源。宿主退出或崩溃后 helper 结束，避免残留采集进程。

## 开屏闭环

1. 欢迎页说明本地处理与来源选择。
2. 发现来源只扫描目录名与文件属性，不读取正文；来源默认不勾选。用户可使用系统目录选择器或输入根目录。
3. 点击导入后创建后台任务。进度为实际文件计数与标准化阶段；可在后台继续或请求取消。样本模式明确标记 `sample`，最近 90 天是分析范围，不截断 L0 归档。
4. 显示实际会话、标准事件、原始记录与任务状态，进入会话列表和存储结果。关闭并重开后复用数据库和设置。

任务状态：`queued / running / completed / partial / cancelled / failed / interrupted`。来源失败不会吞掉同批其他来源的结果；原文和中间归档仍可追溯。重启时将未完成任务标为 `interrupted`，不会自动扩大采集范围。重试保留原先的来源、文件选择与 limit。

停用来源停止后续采集，已归档记录保留。持续同步默认关闭，用户显式开启后每 15 秒检查已启用的完整来源。文件间取消沿用数据层语义：单个大文件及标准化事务尚不能立即抢占；UI 如实说明等待边界。

## UI 对应关系

| Advance 功能 | 后端事实或接口 | 不可用状态 |
|---|---|---|
| 首次启动 / 数据源 | discovery、sources、jobs、settings | 未发现、无样本、权限失败、部分导入 |
| 概览 | scoped overview、usage、工具摘要、覆盖 | null 不显示为 0，不将跨度当工时 |
| 协作人格 | preferences 的明确偏好与证据 | 四维人格评分未校准，明确不生成类型 |
| 会话与轨迹 | SQL 分页的 sessions、seq 游标事件 | 缺时间不猜测；预览截断可见 |
| 工具调用 | tools 的已知成功/失败、未知状态、耗时 | 工具状态不等于任务成功 |
| 项目习惯 | canonical project 与 scoped project aggregates | 未知项目不推断身份 |
| 情绪与语义 | task records 和解释依据 | 未提供校准情绪评分 |
| 优化建议 | 独立 recommend 服务 | 没有充分证据时保留空结果；不宣称收益 |
| 资源库 | 显式 inventory 扫描的配置/安装观察 | 不把“安装”当作“实际调用”；不自动安装 |
| 生成工坊 | 当前范围脱敏特征/证据的 JSON 上下文包 | 未接入本地 Agent 执行 |
| 设置 / 存储 | 源开关、轮询、schema/投影状态、数量、容量、verify/rebuild/backup | 过期投影可重算，不伪装参数错误 |
| 导出 | 当前选择范围的脱敏分析 JSON、原生保存面板 | 原始归档不通过 UI 导出接口暴露 |

这些接入使用现有 Advance 外壳、字体和组件。数据页面由独立的 `98-app.js` 适配层渲染；设计预览的模拟统计、随机事件和安装动画不参与 App 模式。未实现的 LLM/安装功能明确留有能力状态，不会显示假完成。

## API

统一前缀 `/v1/app`；原生宿主消费与浏览器验收相同的协议。

| 方法与路径 | 含义 |
|---|---|
| GET `/state` | 来源、设置、任务日志、存储与能力 |
| GET `/discovery` | 候选来源和文件数 |
| POST `/sources` | 显式启用或停用 agent/root |
| PATCH `/settings` | 开屏完成、默认时间范围、同步模式 |
| POST `/jobs` | import / inventory / rebuild / verify / backup |
| GET `/jobs/{id}` | 实际进度、结果与状态 |
| POST `/jobs/{id}/cancel` | 请求取消 |
| POST `/jobs/{id}/retry` | 保持原始范围重试 |
| GET `/sessions` | agent/project/time/title 过滤，offset/limit 分页 |
| GET `/sessions/{id}/events` | after_seq 游标，保留 evidence locator |
| GET `/projects` | 已存储的项目与会话数 |
| GET `/analysis?section=…` | 同一范围的特征切片或按需推荐 |
| GET `/inventory` | 已发布安装观察，不扫描配置 |
| GET `/storage` | 无需当前投影即可读的数据库状态和容量 |
| GET `/export` | 当前范围的脱敏分析 JSON |

`/health` 返回进程存活和独立 readiness；过期投影的数据接口统一返回 409 + `rebuild_required`。非法范围返回 422，后台任务冲突返回 409，未授权返回 401。文档 `/docs` 和 `/openapi.json` 同样需要令牌。

## 正确性与维护

- Python Codex 入口增加最高版本 state index、标题索引和导入标记；索引只读取允许的列，不采集账号身份列。
- canonical 在映射前选择活动历史分支、过滤 legacy rollback 和完全一致的归档副本。过滤只影响当前投影，L0/L1 保留证据。直采与 TypeScript staging 桥接共同经过这些规则。
- Codex mapper 按索引、Responses item、UI event 拆分。`codex_history.py` 单独维护跨文件历史选择；`codex_index.py` 单独维护读取白名单。
- 时间范围复用同一份校验，采用 `[from_ts, until_ts)`，拒绝相等和逆序端点。
- 工具、用量、会话、项目、轮次、累计快照的范围过滤下推 SQL。事件读取仍有 100,000 个候选事件上限；App 超限应缩小范围。
- 单进程分析缓存最多 4 份，按发布版本、安装清单版本、完整范围和文本选项失效。正常分析请求不计算推荐，推荐路由按需调用；App 普通页面不触发昂贵的全量文本表示。
- 备份持有写锁，使用 SQLite backup API 保存一致数据库，并复制不可变 raw 与应用状态；恢复需关闭 App，再从该备份目录启动。不是只复制运行中的 SQLite 主文件。

仍保留完整变化文件快照和来源级重算；尚未改为逐字节尾追。持久归档暂未加入自动删除/配额回收。以上边界应按后续真实容量测量迭代，不以暖扫描时间冒充持续追加性能。

## 验收与展示

```sh
# 七种构造原生格式，通过实际开屏点击进入导入、会话、证据、分析和导出
uv run python scripts/check-desktop.py

# 只有显式授权后才执行；output 必须在所有 Agent 根目录之外
uv run python scripts/demo-local-sessions.py --real --output /absolute/private/desktop-real

# 在 App 中展示同一份真实导入结果
open -n .local/macos-build/Tandem.app --args --home /absolute/private/desktop-real/data
```

构造验收目录为 `.local/desktop-checks/run-*/`，包含数据库、服务日志及开屏完成/会话证据/存储页面截图。真实样本最多选择每 Agent 两个已静置至少 120 秒、每文件不超过 16 MiB 的主转录，优先最近修改记录；不会扫描凭据。`results.json` 保存选择边界、任务状态、各来源数量和哈希/完整性验证。缺席来源显示 unavailable。

本次在本机实际导入 Claude Code、Codex、DSH、pi 各两个会话：8 个会话、3,916 条 L1 原始记录、3,622 个 L2 事件，8 个归档与全部记录哈希通过，未解析为 0。这是有界样本的单次验证，不代表全量覆盖；OpenCode、Hermes、Kimi 未计入本机真实验证。

提交前仍执行根 AGENTS.md 的 Python、TypeScript、build、demo、evaluate 检查；Advance UI 运行 `pnpm check` 与完整 `pnpm test`，另运行上述真实 API 驱动的 Playwright 验收。

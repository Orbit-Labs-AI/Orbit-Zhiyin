# 本地数据模块与 Mac App

本版将 Advance 的开屏导入、数据源、会话、事件证据、分析、安装清单与存储维护接到 Python canonical 数据层。离线设计 Demo 保持独立；访问本机服务 `/app` 才进入真实数据模式。Lite 的独立设计文件未改动。

## 构建与启动

构建机器使用 Python 3.13、uv、Node/pnpm 和 Xcode Command Line Tools。成品用户不需要这些工具。当前产物为 Apple Silicon，macOS 15 是编译目标；其他 macOS 版本和 Intel 未做实机验收。

```sh
uv sync --locked --all-packages --dev
pnpm install --frozen-lockfile
uv run python apps/desktop/build.py
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

`application/desktop.py` 是桌面生命周期边界，保留主干的 `application/reports.py` 报告用例；`app_api.py` 只做路由、请求校验与查询编排；`app_contracts.py` 为来源、任务、进度和存储提供可生成客户端的 OpenAPI 响应结构。原有 `/v1/analytics/*` 保持兼容。

helper 仅绑定 `127.0.0.1` 的动态端口。令牌由原生宿主产生，通过子进程环境和 WKUserScript 传递，不放在日志、命令行或页面 URL 中；除无数据的 `/app` 外所有接口均需要 Bearer token，另检查 Host 和 Origin。WebView 为非持久存储，页面禁用外部字体及外部网络资源。宿主退出或崩溃后 helper 结束，避免残留采集进程。

## 开屏闭环

1. 欢迎页说明本地处理与来源选择。
2. 发现来源只扫描目录名与文件属性，不读取正文；来源默认不勾选。用户可使用系统目录选择器或输入根目录。
3. 点击导入后创建后台任务。默认导入全部来源文件，进度覆盖来源索引、准备、映射与派生阶段；可在后台继续或请求取消。用户选择样本模式时明确标记 `sample`，最近 90 天是分析范围，不缩小来源索引范围。
4. 显示实际会话、标准事件、原始记录与任务状态，进入会话列表和存储结果。关闭并重开后复用数据库和设置。

任务状态：`queued / running / completed / partial / cancelled / failed / interrupted`。来源失败不会吞掉同批其他来源的结果；原文索引和已有归档仍可追溯。重启时将未完成任务标为 `interrupted`，不会自动扩大采集范围。重试保留原先的来源、文件选择与 limit。

停用来源停止后续采集，已有索引、投影和历史归档保留。持续同步默认关闭，用户显式开启后每 15 秒检查已启用的完整来源。文件间取消沿用数据层语义：单个大文件及标准化事务尚不能立即抢占；UI 如实说明等待边界。

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

### 会话标题与上下文

`presentation.py` 统一提供展示信息，保留原生 `title` 与事件证据不变。标题优先级是原生标题、来源任务标签、首条已确认人类消息的摘要、Agent/会话类型/稳定标识。API 同时返回 `display_title_source`，界面标明标题来源；无标题、空白标题、工作流子代理和没有人类消息的会话均可区分。

`context.inject` 表示运行时加入模型上下文的记录，包含环境、工具清单、文件内容、用量提醒、媒体引用及继承历史，不等同于聊天消息。展示层读取已经脱敏的结构化附件；有文本就显示预览，仅有结构化数据就显示类型说明与可读字段。连续上下文默认折叠，展开后可回查标准属性与原始记录标识。预览截断会明确标记，不生成缺失的正文。

解析器与展示层分别演进：新附件类型保留通用说明和原始结构，不要求识别所有来源名称才能展示；未知原生事件仍有 `unknown` 与诊断记录，友好名称不把它转成已确认的业务行为。

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

`/health` 返回进程存活和独立 readiness；过期投影的数据接口统一返回 409 + `rebuild_required`。非法范围返回 422，后台任务冲突返回 409，未授权返回 401。详细分析或导出超过内存预算时返回 422 + `analysis_scope_too_large`，提示缩小范围。文档 `/docs` 和 `/openapi.json` 同样需要令牌。

## 正确性与维护

- Python Codex 入口增加最高版本 state index、标题索引和导入标记；索引只读取允许的列，不采集账号身份列。
- canonical 在映射前选择活动历史分支、过滤 legacy rollback 和完全一致的归档副本。过滤只影响当前投影，L0/L1 保留证据。直采与 TypeScript staging 桥接共同经过这些规则。
- Codex mapper 按索引、Responses item、UI event 拆分。`codex_history.py` 单独维护跨文件历史选择；`codex_index.py` 单独维护读取白名单。
- 时间范围复用同一份校验，采用 `[from_ts, until_ts)`，拒绝相等和逆序端点。
- 工具、用量、会话、项目、轮次、累计快照的范围过滤下推 SQL。App 请求在解码事件前显式选择 100,000 条及 64 MiB 编码载荷的双重预算，既限制大量小记录，也限制少量大记录。App 概览超限时提供 SQL 基础统计，明确标记 `aggregate_only`；未计算的用量和语义结果为 excluded，不补零。App 详细分析和导出需要缩小范围；数据层及 CLI 默认保留主干的完整读取语义，调用方可显式设置预算。
- 分析时区由客户端提供，服务端默认 UTC；不绑定开发机器的时区。SQL 概览遵守同一套项目、根会话、子代理、排除项、模型、effort 与时间范围，不支持的语义范围显式拒绝。
- 数据库迁移 007 为反向外键查询补索引，避免来源重建删除父记录时反复扫描其他来源。主干 006 的来源索引表保留，并兼容早期 App 只含索引优化的 v6 布局；两类 v6 的证据保留均有迁移回归。字段字典按当前 DDL 生成。构造测试检查查询计划实际使用索引。
- 每个连接器独立声明 mapper 版本；公共派生与脱敏另有版本。修复某个 Agent 时仅重建过期来源。重建使用已有证据，不执行新的来源导入。历史归档可独立重建；原生索引按主干规则验证来源，来源已变更或消失时保留已有事实并报告不可用。校验、未解析等不完整状态显示 partial。
- 映射延迟引用只保存定位信息，同一记录内复用有界脱敏结果，父历史索引在兄弟会话间复用，避免保留重复大载荷。缓存结束于记录边界，不改变脱敏规则。
- Codex 的父历史先于子代理映射，嵌套 spawn、跨文件片段及延迟镜像引用均可关联。原生 paginated fork 可能重写 item/turn ID；有明确继承边界但无法逐条对应父事件时，记录为可追溯的继承上下文，不再重复计算用户消息、工具调用、模型用量和轮次。
- 单进程分析缓存最多 4 份，按发布版本、安装清单版本、完整范围和文本选项失效。正常分析请求不计算推荐，推荐路由按需调用；App 普通页面不触发昂贵的全量文本表示。
- 备份持有写锁，使用 SQLite backup API 保存 canonical 数据库；分析历史和 Catalog 分别保存一致快照，再复制既有 raw 与应用状态。它不复制原生来源目录，索引引用的原文仍受来源可用性约束。恢复需关闭 App，再从该备份目录启动。

原生导入沿用最新主干：L0 是只读来源引用，L1 保存索引，默认不复制完整原生文件；变化文件重新索引，投影按来源重算。旧版不可变归档和 staging 桥接仍可读取，既有证据不删除。原始来源可用性、完整轨迹分页与分析运行历史保持主干协议。

## 验收与展示

```sh
# 七种构造原生格式，通过实际开屏点击进入导入、会话、证据、分析和导出
uv run python scripts/check-desktop.py

# 可选的少量真实样本演示，不能用它代表全量覆盖
uv run python scripts/demo-local-sessions.py --real --output /absolute/private/desktop-real

# 显式授权后的全量验收：所有发现的来源根目录，不限制文件数、大小、时间
uv run python scripts/check-full-import.py --real --output /absolute/private/desktop-full

# 仅核验现有全量快照，沿用原发现清单和历史任务记录
uv run python scripts/check-full-import.py --real --verify-only --output /absolute/private/desktop-full

# 关闭已运行的 Tandem 后，在 App 中展示该数据目录
open .local/macos-build/Tandem.app --args --home /absolute/private/desktop-full/data
```

构造验收目录为 `.local/desktop-checks/run-*/`，包含数据库、服务日志及开屏完成/会话证据/存储页面截图。来源发现通过注入目录清单隔离，测试不枚举开发者实际 home；构造覆盖全部七个连接器。开屏验收检查七个来源全部选中、七项导入结果、至少九个实际会话和零失败请求，不只检查页面出现。添加来源期间锁定表单，避免异步重绘覆盖下一项选择。真实样本脚本最多选择每 Agent 两个已静置至少 120 秒、每文件不超过 16 MiB 的主转录，它与全量脚本分开。

全量验收保存导入前清单、每来源文件覆盖、初次/增量任务、修复任务、L0/L1 哈希、事件契约、外键与完整性检查，以及分页/分析 API 读取结果。只读原生来源，output 必须位于所有来源根目录之外。清单开始后仍在运行的 Agent 可能新增、移动或追加文件，报告分别列出这些变化；覆盖声明以捕获快照为准。校验失败或没有发现来源时不能返回成功。

迁移前，2026-10-02 的授权全量快照验收覆盖 6 个来源根目录（Claude Code 3 个、Codex/DSH/pi 各 1 个）：导入前 2,313 个白名单文件全部覆盖，最终归档文件索引 2,333 个；存储 1,748 个会话、722,215 个标准事件、732,779 条原始记录（含保留的历史版本）。2,202 个归档和全部原始记录哈希通过，未解析为 0，数据库与事件契约检查通过。保留 2,804 条语义诊断：未知原生类型 2,736、未配对工具结果 37、未解析会话关系 3、累计计数器回落 28；`unparsed=0` 只证明每条原始记录已有去向，不代表所有语义都已经理解。OpenCode、Hermes、Kimi 的本机真实来源缺席，覆盖来自构造回归。

真实日志、完整报告与截图均在本地忽略目录，不进入仓库。这里的数量是一次容量和闭环验收证据；生产逻辑不依赖这些数量、本机路径、会话 ID 或特定日期。

适配主干 `927d254` 后，原全量归档库先备份，再迁移到 schema 7 并按 mapper 1.4.0 重建。最终为 1,748 个会话、724,366 个事件、732,779 条原始记录；2,202 个归档与全部 L1 哈希、事件契约、外键和 SQLite 完整性再次通过，未解析为 0。仍保留 362 条诊断：未知原生类型 258、未配对工具结果 73、未解析会话关系 3、累计计数回落 28。本次真实库验收使用固定归档快照；默认原生索引路径另由七种构造来源验证，运行期间新增或移动文件路径单列于报告。

最新版已保留主干的 Agent/来源筛选、偏好证据、展示指标、覆盖诊断、分析历史和推荐偏好改进。随包运行时同时验证 App 会话/概览与主干 presentation/products 接口；这些检查使用隔离构造库，不依赖开发机器的实际会话。冻结包显式携带分析历史需要的依赖发行元数据。

提交前执行最新根 AGENTS.md 的 `bash scripts/bootstrap.sh`、`pnpm check`、`pnpm check:ui`，以及上述真实 API 驱动的开屏验收。检查包含全部 Python、TypeScript、Swift 客户端、文档链接、wheel 独立安装和原型测试。

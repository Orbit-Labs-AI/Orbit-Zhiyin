# Orbit

Orbit-Labs-AI 组织的公开 Orbit-Zhiyin 仓库（Orbit·知音的源码、安装包与版本说明；原 Orbit 源码仓库，2026-10-14 与发布仓库合并），默认分支 `main`；版本说明与许可快照在 `releases/<版本>/`，发布流程见 [RELEASING.md](RELEASING.md)。产品名 **Orbit**（原暂定名 Tandem / 同频；本仓库中的 Orbit 均指 Orbit·知音，`Orbit-Labs-AI/Orbit` 是另一个仓库），目标为本地 macOS App；当前采用 Python workspace、TypeScript 连接器与 UI 原型。Orbit·知音已于 2026-10-14 停止开发，不再新增功能。

- 文档、界面文案与提交说明里的产品名一律写 Orbit，全名带字标时写 Orbit·知音。代码标识自 2026-10-03 起同样统一为 orbit（`orbit_*` 包、`orbit` CLI、`ORBIT_*` 环境变量、`Application Support/Orbit`、`orbit.db`、`OrbitLive`、`@orbit/*`、`orbit-demo.html` 等），不再新增 tandem 命名；旧数据与旧设置的兼容集中在 `packages/data/src/orbit_data/legacy.py`，见 [品牌](docs/design/brand.md#名称)。改名前开出的分支先运行 `python3 scripts/orbit-rename.py` 再合并 main，`--check` 列出残留。
- 标志与 App 图标以 `docs/design/logo/` 为准：参数只在 `orbit-spec.json`，`generate.py` 写出矢量、`export.mjs` 渲染位图，素材在 `logo/kit/`。所有尺寸都是 App 图标曲线的整体等比缩放，不重绘、不改线宽；App 原型与 App 构建原样引用这些文件。

## App 版本与设计归属

- **Lite**：采用 `genius-FXC` 的设计，参考 `prototypes/lite/orbit-benchmark-demo.html`（PR #12）。
- **Advance**：采用 `yhyfhgs` 的设计，参考 `prototypes/advance/orbit-demo.html`、`prototypes/advance/src/` 与 `docs/design/visual-cases-v1/`。
- 版本名统一使用 **Lite / Advance**；历史文档中的 `Advanced` 指 **Advance**。设计入口与详细说明以 [设计资料](docs/design/README.md) 为准。
- 两版是同一个 App（`prototypes/advance`，侧栏顶部一键切换），共用侧栏、卡片、栏目、控件、小组件与动效；Lite 只做页面数量与尺度上的减法，不另建一套组件。
- 以上规定版本与设计的对应关系。可运行界面在 prototypes，原生宿主在 apps/desktop；Orbit·知音停止开发后，MVP 功能范围不再扩展。

## 成员与分工

成员一律以 GitHub 账号指代。AI 与成员讨论需求、方案或开始实现前，主动给出对应提醒。

- **[`yhyfhgs`](https://github.com/yhyfhgs)**（负责人，PR 唯一审批人）：关注产品输入、输出、workflow 与总体架构，决定模块取舍。提醒：避免过度抽象与通用化，不追求企业级设计；MVP 范围须经三位成员共同确认。
- **[`MistyHuang03`](https://github.com/MistyHuang03)**：关注功能可行性、技术选型与验证。提醒：避免过度分析，优先实现，以可运行原型验证判断。
- **[`genius-FXC`](https://github.com/genius-FXC)**：关注真实需求、产品展示与路演。提醒：持续质疑需求；不单方面因新需求增加 feature，先与团队对齐。

## 分支与 PR

- `main` 仅通过 PR 更新：任何人（含 `yhyfhgs`）不得直接提交、推送、强推或删除。分支从最新 `main` 创建，命名 `<type>/<简述>`（feat／fix／docs／refactor／chore）。
- PR 标题用 `type(scope): 描述`，正文包含改动摘要、验证方式与关联 Issue。
- PR 一律以正常（ready for review）状态创建，不开 draft：`gh pr create` 不加 `--draft`，网页端选 Create pull request。PR 应在本地检查通过后再开；尚未完成的工作留在分支上继续提交，不用 draft 占位。误开的 draft 用 `gh pr ready <N>` 转为正常状态。
- 本仓库不再要求 AI 触发、读取、等待或跟进 Codex review（`chatgpt-codex-connector`），也不将其完成状态或意见处理作为合并前置条件；本条覆盖全局指令中的 Codex review 流程。
- 其他成员提交的 PR 由 `yhyfhgs` 统一管理；未经其明确指派，AI 不主动审查、修改、回复评论、合并或关闭这些 PR。
- merge 与 close 仅由 `yhyfhgs` 决定。`yhyfhgs` 自己分支（含 AI 为其开发）的 PR 满足下节「合并门槛」即可合并，无需逐个再问；其他成员的 PR 仍须得到 `yhyfhgs` 对该 PR 的明确指示。合并使用 `gh pr merge --merge --match-head-commit <当前 head SHA>`。
- 统一使用 merge commit 保留分支提交历史，不 squash、不 rebase。
- 主分支协作规则持续执行；分支保护是否启用以仓库设置为准。

## 合并门槛与本机并行

**不过度测试。** 合并门槛只有两条：与最新 `origin/main` 无冲突；改动涉及模块的检查在合并结果（`origin/main` + 分支）上通过。

- 按改动范围选检查（命令见 [测试指南](docs/development/testing.md)）：只改某个 Python 包跑该包的 `uv run pytest -q <包>/tests`；连接器跑 `pnpm --filter @orbit/connectors check`；原型跑 `pnpm check:ui`；Swift 客户端跑 `swift test --package-path packages/catalog-macos`；纯文档跑 `pnpm check:docs`。只有改动依赖与锁文件、DDL / Schema 契约、跨包接口或构建脚本时才跑全量 `pnpm check`。
- 不为合并加跑：重复全量、Benchmark、多轮配对测量、截图巡检、安装验收（除非改了打包）。新增测试只用于锁住本次修的 bug 或新行为，不为凑覆盖率补测试。
- head 在验证后又有新提交时，只补验新提交涉及的模块。计时类测试失败先单独重跑一次；单独复现才算 bug。
- 发现的 bug 只修与本次改动相关的；无关问题记录下来另开任务，不阻塞合并。

**本机并行，避免竞争。** 同一台机器上常有多个 agent 会话同时工作。

- 每个任务用独立 worktree（`.work/wt-<任务>`，从最新 `origin/main` 建分支）；不在别人正在使用的 checkout 上切分支、stash 或改文件，主 checkout 只做 `--ff-only` 更新。
- 重负载命令一律经闸门：`python3 scripts/heavy.py <命令>`，包括全量 `pnpm check`、`pnpm check:ui` / Playwright、整包 pytest、Benchmark、Swift 构建与 wheel 安装验收。默认全机同时最多 2 个，其余排队；单个模块的小范围测试与 typecheck 可直接运行。
- 合并串行：`HEAVY_NAME=merge HEAVY_SLOTS=1 python3 scripts/heavy.py <合并脚本或命令>`，一次只合一个 PR；合并后立即 ff 本地 `main`，再把新 `main` 合入仍在进行的后续分支。
- 测试不用固定端口、全局目录或固定文件名；并行跑 pytest 时 worker 数不超过 `-n 4`，避免与其他会话叠加压满 CPU。
- 不另起 Claude 程序：不在命令行运行 `claude` / `claude -p`、不新开桌面会话、不通过任务卡片（spawn_task）派生会话；并行只用当前会话内的子代理或 workflow。能在当前会话完成的不开子代理，需要并行时同时活跃的子代理不超过 4 个。
- 多 agent 编排时按条目流水线推进（一项完成即进入下一阶段），不设全局屏障。

## 提交

- 每完成一个功能点或可独立说明的步骤即提交并推送；AI 与开发者均应主动小步提交，便于他人审查与学习。
- 每个提交单一目的，信息用 `type(scope): 描述`，说明改动内容与原因。
- 提交前确保可运行或通过现有检查；有意提交的未完成状态须在提交信息中注明。
- 已推送的提交不 amend、不强推，修正以新提交完成。
- 禁止提交密钥、`.env` 与个人隐私数据。

## Codex Connector

- 代码位于 `packages/connectors/`，TypeScript + Node ≥24.7；使用内置 `node:sqlite` 和 `node:zlib`，不引入原生扩展依赖。
- 提交前在该目录执行 `pnpm check`（typecheck、构造样本回归、build）。CLI 文档与 SQL / JSON Schema 是分析模块和前端接入的数据契约。
- 来源目录只读；仅在用户明确启用来源时导入。构造或脱敏样本进仓库，真实日志、原始归档和派生数据库只放本地忽略目录。
- 新类型须有 L1 去向；不能通过跳过未知记录或把缺失成本/状态当成 0/成功来让检查通过。
## 数据契约包检查

目标是 macOS App。Python 统一为 3.13（`.python-version`），仓库根的 `uv.lock` 管理 `packages/backend`、`packages/data` 与 `packages/catalog` workspace；不要新增平行 Python 锁文件。

从仓库根运行 `bash scripts/bootstrap.sh`、`pnpm check`（日常合并按「合并门槛」只跑对应模块）。后者执行 lint、全部 Python 测试、连接器检查、Swift 客户端测试、原型产物检查、文档链接检查和 wheel 安装后验收；TypeScript producer 必须先构建，桥接测试不允许静默跳过。修改原型后还须运行 `pnpm check:ui`。分类与局部检查见 [测试指南](docs/development/testing.md)。

数据库的权威结构是 `packages/data/src/orbit_data/migrations/`。改变 DDL 后，用 `uv run python -m orbit_data.schema_export --output packages/data/src/orbit_data/schemas/tables-v1.schema.json` 更新字段字典，并保持 `event-v1.schema.json` 与导入校验一致。实际本机会话、`.orbit/` 数据库和原始归档禁止提交；连接器 staging 库必须通过桥接导入，不能当成同一版 canonical 库直接写入。

## 目录与接入

- 根 `pyproject.toml` / `uv.lock` 与 `pnpm-workspace.yaml` / `pnpm-lock.yaml` 分别统一两种语言的依赖；不新增包内锁文件。
- 后端实现在 `packages/backend/src/orbit_backend/`；兼容导出文件不新增业务逻辑。模块与数据流见 [模块接入表](docs/architecture/module-map.md)。
- 模块测试随包；根 `tests/` 只放跨包和服务流程。评测放 `evals/`，性能放 `benchmarks/`，根 `scripts/` 保持薄入口。
- 统一 App 界面在 `prototypes/advance`，`prototypes/lite` 保留设计原稿；原生宿主在 `apps/desktop`，静态设计资料在 `docs/design`。Catalog 与 Swift 客户端分别位于 packages/catalog 和 packages/catalog-macos。
- 活跃分支遵循 [目录迁移说明](docs/archive/migrations/structure-migration.md)，不要在 merge 时恢复旧目录或平行锁文件。
- 文档按 [文档导航](docs/README.md) 分区：用户（getting-started、guides）、现行参考（product、design、architecture、contracts、development、modules）、审计（audits）、开发调研（research）、历史（releases、archive）。需求、提案、竞品与方法研究和团队模块设计在 TeamHub 的 [Orbit 项目页](https://github.com/Orbit-Labs-AI/TeamHub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/README.md) 维护，不放进本仓库；`research` 只收代码直接依据的外部源码、日志格式与平台规范快照。新增文档在所属目录 README 登记，搬迁同时修正入站与相对链接，见 [文档维护](docs/development/documentation.md)。

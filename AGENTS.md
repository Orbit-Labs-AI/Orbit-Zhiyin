# Hackathon

ActionMesh-AI 组织的私有比赛仓库，默认分支 `main`。产品名 **Orbit**（原暂定名 Tandem / 同频），目标为本地 macOS App；当前采用 Python workspace、TypeScript 连接器与 UI 原型。

- 文档、界面文案与提交说明里的产品名一律写 Orbit。代码标识（`tandem_*` 包、`tandem` CLI、`TANDEM_HOME`、`Application Support/Tandem`、`TandemLive`、`@tandem/*`、`tandem-demo.html` 等）暂不改名，对照见 [品牌](docs/design/brand.md)。
- 标志与 App 图标以 `docs/design/logo/orbit-*` 为准，由 `generate.py` 生成；App 原型的 `orbitMark` 用同一组参数。

## App 版本与设计归属

- **Lite**：采用 `genius-FXC` 的设计，参考 `prototypes/lite/tandem-benchmark-demo.html`（PR #12）。
- **Advance**：采用 `yhyfhgs` 的设计，参考 `prototypes/advance/tandem-demo.html`、`prototypes/advance/src/` 与 `docs/design/visual-cases-v1/`。
- 版本名统一使用 **Lite / Advance**；历史文档中的 `Advanced` 指 **Advance**。设计入口与详细说明以 [设计资料](docs/design/README.md) 为准。
- 两版是同一个 App（`prototypes/advance`，侧栏顶部一键切换），共用侧栏、卡片、栏目、控件、小组件与动效；Lite 只做页面数量与尺度上的减法，不另建一套组件。
- 以上仅规定版本与现有设计的对应关系。本次结构整理将可运行原型归入 prototypes；画板与界面行为仍由对应设计任务推进，MVP 功能范围仍须三位成员共同确认。

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
- merge 与 close 仅由 `yhyfhgs` 决定。AI 须得到 `yhyfhgs` 对该 PR 的明确指示后执行，合并使用 `gh pr merge --merge --match-head-commit <当前 head SHA>`。
- 统一使用 merge commit 保留分支提交历史，不 squash、不 rebase。
- GitHub Free 私有仓库无法启用分支保护，上述规则依约定执行。

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

从仓库根运行 `bash scripts/bootstrap.sh`、`pnpm check`。后者执行 lint、全部 Python 测试、连接器检查、Swift 客户端测试、原型产物检查、文档链接检查和 wheel 安装后验收；TypeScript producer 必须先构建，桥接测试不允许静默跳过。修改原型后还须运行 `pnpm check:ui`。分类与局部检查见 [测试指南](docs/development/testing.md)。

数据库的权威结构是 `packages/data/src/tandem_data/migrations/`。改变 DDL 后，用 `uv run python -m tandem_data.schema_export --output packages/data/src/tandem_data/schemas/tables-v1.schema.json` 更新字段字典，并保持 `event-v1.schema.json` 与导入校验一致。实际本机会话、`.tandem/` 数据库和原始归档禁止提交；连接器 staging 库必须通过桥接导入，不能当成同一版 canonical 库直接写入。

## 目录与接入

- 根 `pyproject.toml` / `uv.lock` 与 `pnpm-workspace.yaml` / `pnpm-lock.yaml` 分别统一两种语言的依赖；不新增包内锁文件。
- 后端实现在 `packages/backend/src/tandem_backend/`；兼容导出文件不新增业务逻辑。模块与数据流见 [模块接入表](docs/architecture/module-map.md)。
- 模块测试随包；根 `tests/` 只放跨包和服务流程。评测放 `evals/`，性能放 `benchmarks/`，根 `scripts/` 保持薄入口。
- 可运行原型放 `prototypes/lite` 与 `prototypes/advance`；静态设计资料留在 `docs/design`。正式 App 不建立空实现；Catalog 与 Swift 客户端分别位于 packages/catalog 和 packages/catalog-macos。
- 活跃分支遵循 [目录迁移说明](docs/development/structure-migration.md)，不要在 merge 时恢复旧目录或平行锁文件。
- 文档按 [文档导航](docs/README.md) 分区：现行（product、design、architecture、contracts、development、modules）、方案（plans）、审计（audits）、调研（research）、历史（releases、archive）。新增文档放进对应分区并在导航登记。

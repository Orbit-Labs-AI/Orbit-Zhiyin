# 参与 Orbit

状态：现行协作规范；维护者：`yhyfhgs`。适用于本仓库的代码、设计、文档与构造样本；项目规则以 [AGENTS.md](AGENTS.md) 为准。

Orbit 当前是 ActionMesh-AI 的私有比赛项目。请先确认问题和负责模块；新增功能及 MVP 范围须由 `yhyfhgs`、`MistyHuang03`、`genius-FXC` 共同确认，功能建议不代表已承诺实现。讨论和评审遵循[行为准则](CODE_OF_CONDUCT.md)，安全问题按[安全政策](SECURITY.md)私下报告。

## 提交问题

在现有 Issues 中确认是否已有相同问题，再使用 [Bug 或功能建议模板](https://github.com/ActionMesh-AI/Hackathon/issues/new/choose)。Bug 应包含提交版本、运行环境、最小复现步骤、预期与实际结果；功能建议先说明真实场景、现有做法的不足与最小验收条件。

只提交构造或充分脱敏的样本。不要上传真实 Agent 会话、个人路径、数据库、密钥、`.env`、原始归档或带隐私信息的截图。

## 准备开发环境

需要 Python 3.13、uv、Node ≥24.7、pnpm 11.25.0；完整检查还需要 macOS 上的 Swift 5.9+。在仓库根运行：

```sh
bash scripts/bootstrap.sh
uv run tandem demo
pnpm dev --home .local/demo/data
```

Demo 使用虚构数据；真实来源只有用户明确启用后才能导入。详细用法见[使用指南](docs/development/usage.md)，模块边界见[模块接入表](docs/architecture/module-map.md)。

## 分支与提交

从最新 `main` 创建 `<type>/<简述>` 分支，例如 `docs/contributing-guide`、`fix/session-import`。不得直接提交或推送到 `main`。

提交信息和 PR 标题沿用 [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) 的结构：

```text
type(scope): 描述改动及原因
```

常用类型为 `feat`、`fix`、`docs`、`refactor`、`chore`、`test`、`perf`；分支类型遵循 [AGENTS.md](AGENTS.md) 中的约定。每个提交只做一件可独立说明的事，完成并通过相应检查后提交、推送。已推送的提交用新提交修正，不 amend 或强推。

文档和界面使用产品名 Orbit；既有 `tandem_*`、`tandem` 等代码标识暂不改名。依赖锁文件仅在仓库根维护；第三方源码引用保留原项目的许可与归属。

## 验证与 PR

提交 PR 前，从仓库根执行：

```sh
bash scripts/bootstrap.sh
pnpm check
```

修改 UI 原型还须执行 `pnpm check:ui`。检查分类、浏览器安装和显式启用的真实数据评测见[测试指南](docs/development/testing.md)；不要为通过检查而跳过未知记录、伪造缺失值或放宽测试。

使用仓库的 PR 模板说明问题、结果、实际验证及关联 Issue（没有则注明）。新功能更新模块接入表；新增文档登记在[文档导航](docs/README.md)。本地检查通过后创建正常 PR，不使用 draft 占位。

`yhyfhgs` 是唯一 PR 审批人，由其明确决定合并与关闭；合并保留 merge commit，不 squash 或 rebase。Codex 自动 review 不作为本仓库的必需流程或合并条件。

## 贡献许可

项目采用 [Apache License 2.0](LICENSE)。提交贡献前，请确认有权提供这些内容；除另有明确说明或单独协议外，向本项目提交的贡献按该许可证第 5 条处理。引入第三方材料时保留其原始许可、版权与必要的归属声明。

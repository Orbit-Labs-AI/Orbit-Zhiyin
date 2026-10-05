# 为 Orbit 贡献

欢迎通过问题反馈、使用体验、文档、构造样本和代码帮助 Orbit。先从 [README](README.md)了解产品，再选择一个边界明确、能复现或验证的改进。

## 提交问题或建议

使用 [Issue 模板](https://github.com/Orbit-Labs-AI/Orbit-Source/issues/new/choose)，说明环境、操作步骤、预期与实际结果。功能建议先描述使用场景和最小输入输出；排期与范围由维护者讨论确认。安全问题按 [SECURITY.md](SECURITY.md)私下报告。

只提交构造或充分脱敏的材料。不要上传真实会话库、原始日志、密钥、`.env`、个人路径或含隐私的截图。机器生成的建议也需要贡献者检查其事实、许可和行为。

## 配置环境

从[开发环境](docs/development/setup.md)开始。Python 和 Node 依赖分别使用根目录的 `uv.lock`、`pnpm-lock.yaml`；不新增包内锁文件。运行时包括 Python 3.13、uv、Node ≥24.7、pnpm 11.25.0；原生构建另需 macOS 和 Xcode Command Line Tools。

```sh
git clone https://github.com/Orbit-Labs-AI/Orbit-Source.git Orbit
cd Orbit
bash scripts/bootstrap.sh
uv run orbit demo
```

外部贡献者可 fork 后提交 PR。已有写权限的贡献者也通过分支和 PR 更新 `main`，不直接提交或推送主分支。

## 开始改动

从最新 `main` 建立 `feat/简述`、`fix/简述`、`docs/简述`、`refactor/简述` 或 `chore/简述` 分支。多个本机任务使用独立 worktree，避免切换或清理其他任务正在使用的工作区。

产品名用 **Orbit**，带字标的全名为 **Orbit·知音**，代码标识用 `orbit`。原生日志解析归数据包，业务编排归后端，界面源文件归 `prototypes/advance/src/`；先看[模块接入表](docs/architecture/module-map.md)选择修改位置。生成产物从源文件构建，不另维护一份手改结果。

提交保持单一目的，信息和 PR 标题使用 `type(scope): 描述`，例如 `docs(guides): 补充首次导入的排障步骤`。已推送的提交以新提交修正，不 amend 或强推。

## 验证与 PR

按[测试指南](docs/development/testing.md)选择与改动相关的检查。纯文档运行 `pnpm check:docs`；跨包接口、DDL、依赖或构建脚本改动才需要全量检查。不要为让检查通过而跳过未知数据、补造结果或放宽断言。

PR 说明解决的问题、最终行为、实际验证和关联 Issue（没有则注明）。新接口同步契约，新入口登记导航；与最新 `main` 的合并结果也应通过所需检查。本地工作完成并检查通过后创建 ready PR，不用 draft 占位。

`yhyfhgs` 是 PR 审批负责人，合并保留 merge commit，不 squash 或 rebase。AI 与维护者执行合并时遵循当前任务授权和 [AGENTS.md](AGENTS.md)；Codex 自动 review 不是本仓库的强制门槛。

## 贡献许可与交流

原创代码与文档按 [Apache License 2.0](LICENSE)贡献；引入第三方材料时保留其许可、版权与归属。不要把未经许可的私人资料提交到公开仓库。所有讨论遵守[行为准则](CODE_OF_CONDUCT.md)。

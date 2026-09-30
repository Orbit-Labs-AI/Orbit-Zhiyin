# Hackathon

ActionMesh-AI 组织的私有比赛仓库，默认分支 `main`。赛题、技术栈与检查命令确定后补充至本文件，此前不预设框架。

## 成员与分工

成员一律以 GitHub 账号指代。AI 与成员讨论需求、方案或开始实现前，主动给出对应提醒。

- **[`yhyfhgs`](https://github.com/yhyfhgs)**（负责人，PR 唯一审批人）：关注产品输入、输出、workflow 与总体架构，决定模块取舍。提醒：避免过度抽象与通用化，不追求企业级设计；MVP 范围须经三位成员共同确认。
- **[`MistyHuang03`](https://github.com/MistyHuang03)**：关注功能可行性、技术选型与验证。提醒：避免过度分析，优先实现，以可运行原型验证判断。
- **[`genius-FXC`](https://github.com/genius-FXC)**：关注真实需求、产品展示与路演。提醒：持续质疑需求；不单方面因新需求增加 feature，先与团队对齐。

## 分支与 PR

- `main` 仅通过 PR 更新：任何人（含 `yhyfhgs`）不得直接提交、推送、强推或删除。分支从最新 `main` 创建，命名 `<type>/<简述>`（feat／fix／docs／refactor／chore）。
- PR 标题用 `type(scope): 描述`，正文包含改动摘要、验证方式与关联 Issue。
- 合并前须通过 Codex review（`chatgpt-codex-connector`）：
  - 开 PR 时自动触发；此后每次推送须评论 `@codex review` 重新触发。
  - 汇总评论为 `✅ Completed` 且 Commit 与当前 head 一致；每条意见经独立判断后修复，或在原评论下说明不采纳理由；无未解决线程。
- merge 与 close 仅由 `yhyfhgs` 决定；其他成员与 AI 只可开 PR、推送修复、回复评论。AI 须得到 `yhyfhgs` 对该 PR 的明确指示后执行，合并使用 `gh pr merge --merge --match-head-commit <已审 SHA>`。
- 统一使用 merge commit 保留分支提交历史，不 squash、不 rebase。
- GitHub Free 私有仓库无法启用分支保护，上述规则依约定执行。

## 提交

- 每完成一个功能点或可独立说明的步骤即提交并推送；AI 与开发者均应主动小步提交，便于他人审查与学习。
- 每个提交单一目的，信息用 `type(scope): 描述`，说明改动内容与原因。
- 提交前确保可运行或通过现有检查；有意提交的未完成状态须在提交信息中注明。
- 已推送的提交不 amend、不强推，修正以新提交完成。
- 禁止提交密钥、`.env` 与个人隐私数据。

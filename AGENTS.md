# Hackathon

ActionMesh-AI 组织的私有比赛仓库，默认分支 `main`。赛题、技术栈与检查命令确定后补充到本文件；在此之前不预设框架。

## 团队成员

文中提到成员时，以 GitHub 账号为准识别身份。

| 成员 | GitHub | 关注重点 | 仓库权限 |
| --- | --- | --- | --- |
| 叶昊洋（fhgs） | [`yhyfhgs`](https://github.com/yhyfhgs) | 产品架构与模块取舍 | 负责人；唯一有权批准 PR 合并／关闭 |
| 黄婧扬 | [`MistyHuang03`](https://github.com/MistyHuang03) | 可行性分析与技术选型 | 开发者 |
| genius-FXC | [`genius-FXC`](https://github.com/genius-FXC) | 需求验证与产品展示／路演 | 开发者 |

## 分支与 PR

- **main 受保护**：任何人（含 `yhyfhgs`）不直接提交、推送、强推或删除 `main`。所有改动从最新 `main` 分出 `<type>/<简述>` 分支（type：feat／fix／docs／refactor／chore），经 PR 合入。
- **PR 内容**：标题用 `type(scope): 描述`；正文写改动摘要、验证方式及关联 Issue。
- **Codex review 门禁**（reviewer：`chatgpt-codex-connector`）：
  1. 开 PR 自动触发首轮；之后每次推送都要在 PR 评论 `@codex review` 重新触发。
  2. 通过标准：汇总评论 Status 为 `✅ Completed` 且 Commit 等于当前 head；每条意见已处理（成立的修复，不采纳的在原评论下说明理由），无未解决线程。
  3. 意见先独立判断再修改，不照单全收。
- **合并与关闭**：仅由 `yhyfhgs` 批准。其他成员与 AI 只能开 PR、推送修复、回复评论；AI 须得到 `yhyfhgs` 针对该 PR 的明确指令才执行 merge／close，合并时锁定已审 head（`gh pr merge --merge --match-head-commit <sha>`）。
- **合并方式**：merge commit，保留分支提交历史；不 squash、不 rebase。
- **平台限制**：组织为 GitHub Free，私有仓库无法启用分支保护，以上规则靠约定执行；升级或公开仓库后再配置平台级保护。

## 提交规范

- **小步频繁提交**：每完成一个功能点或可独立说明的步骤就提交，AI 与开发者都应主动 commit，不把多个功能攒成一个大提交。
- **一次一事**：提交信息用 `type(scope): 描述`，说明做了什么、为什么，使他人能按提交顺序审查和学习。
- **可验证**：提交前确认能运行或通过已有检查；刻意保留的中间状态在提交信息中注明。
- **及时推送**：提交后推送分支保持进度可见；已推送的提交不 amend、不强推，修正用新提交。
- **安全**：不提交密钥、`.env`、个人隐私数据。

## 成员协作提醒

AI 与对应成员讨论需求、方案或开始实现前，主动给出以下提醒。

- **genius-FXC（`genius-FXC`）**：持续质疑产品的真实需求，思考如何展示功能与路演；不单方面因新需求增加 feature，先与团队对齐再决定。
- **黄婧扬（`MistyHuang03`）**：持续做功能可行性分析，完成技术选型取舍与具体验证；避免过度分析，优先动手实现，用可运行原型验证判断。
- **叶昊洋（`yhyfhgs`）**：梳理产品输入、输出、workflow 与总体架构，决定模块做与不做；避免过度抽象和通用化，不追求企业级设计；MVP 范围须经三位成员共同确认。

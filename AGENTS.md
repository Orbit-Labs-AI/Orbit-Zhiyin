# Hackathon

- ActionMesh-AI 组织私有仓库，用于 Hackathon 比赛；负责人 fhgs（`yhyfhgs`）。
- 赛题、技术栈、检查命令确定后在此补充；在此之前不预设框架。
- 比赛期间优先快速迭代，但仍不提交密钥、`.env` 与个人隐私数据。

## main 分支保护

- `main` 受保护：任何人（包括 fhgs）都不直接向 `main` 提交或推送，也不强推、不删除 `main`；所有改动从 `main` 分出 `<type>/<简述>` 分支（type 如 feat / fix / docs / refactor），经 PR 合入。
- PR 必须通过 Codex review（GitHub 用户 `chatgpt-codex-connector`）才能合并：
  1. 开 PR 自动触发首轮 review；推送修复后在 PR 评论 `@codex review` 触发新一轮。
  2. 通过标准：Codex 汇总评论的 Status 为 `✅ Completed`，且 Commit 等于当前 head SHA；每条意见都已处理——成立的已修复，不采纳的在该评论下写明理由，评论线程无未解决项。
  3. Codex 意见要独立判断后再改，不照单全收；新 head 必须重新 review。
- PR 的合并与关闭完全由 fhgs（`yhyfhgs`）确认：成员与 AI 只能开 PR、推送修复、回复评论，不得自行 merge 或 close；AI 只在 fhgs 对该 PR 明确说“合并”或“关闭”后才执行。
- 合并默认用 merge commit，保留分支上的提交历史；不 squash、不 rebase 掉过程提交。
- 当前组织为 GitHub Free，私有仓库无法开启平台级分支保护，以上规则靠约定执行；升级或仓库公开后再在 GitHub 上配置对应保护。

## 分支开发与提交

- 每实现一个功能点或完成一个可独立说明的小步骤就提交一次，AI 与开发者都应主动、频繁地 commit，不把多个功能攒成一个大提交。
- 每个提交只做一件事，提交信息用 `type(scope): 描述`，写清做了什么和为什么，方便他人按提交顺序检查和学习。
- 提交前确认改动能运行或通过已有检查；无法通过的中间状态在提交信息中注明。
- 提交后及时推送分支，让进度对团队可见；已推送的提交不 amend、不强推，修正用新提交完成。

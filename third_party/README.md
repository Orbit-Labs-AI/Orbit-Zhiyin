# 第三方参考源码

六个开源 agent 的上游仓库以 git submodule 形式放在这里，供[会话格式调研](../docs/research/agent-sessions/README.md)与连接器开发查源码。只作参考，不参与构建，也不运行。

| 目录 | 上游 | 跟踪分支 | 固定提交 | 提交日期 | 最新发布 | 许可 |
| --- | --- | --- | --- | --- | --- | --- |
| `pi` | [earendil-works/pi](https://github.com/earendil-works/pi) | main | `7fbbd5f` | 2026-10-01 | v1.0.0 | MIT |
| `hermes-agent` | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | main | `10c6188` | 2026-10-02 | v2026.9.24 | MIT |
| `deepseek-harness` | [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) | master | `639ed01` | 2026-09-29 | 无 GitHub Release（npm `@deepseek-ai/dsh` 0.2.0-rc.2） | MIT |
| `opencode` | [anomalyco/opencode](https://github.com/anomalyco/opencode) | dev | `1ddb087` | 2026-10-02 | v1.18.34 | MIT |
| `codex` | [openai/codex](https://github.com/openai/codex) | main | `4dd51f4` | 2026-10-02 | rust-v0.160.0 | Apache-2.0 |
| `claude-agent-sdk-python` | [anthropics/claude-agent-sdk-python](https://github.com/anthropics/claude-agent-sdk-python) | main | `bfb895c` | 2026-10-01 | v0.2.163 | MIT |

固定提交是 2026-10-02 各上游默认分支的最新提交（07:11 UTC 用 `git ls-remote` 核对），提交日期按 UTC。Claude Code CLI 不开源；`anthropics/claude-code`（CHANGELOG）与 `anthropics/claude-agent-sdk-typescript` 的许可是 Anthropic 商业条款，不收录为子模块，调研报告直接链接 GitHub。

调研报告的源码链接都固定在上表提交；不收录的两个仓库在报告里固定为 `claude-agent-sdk-typescript@9d8cb9c`、`claude-code@52c7644`。报告初稿基于 2026-10-01 前后的提交，迁移时逐条核对过引用行；迁移过的五份报告在 §0 有「迁移核对」一行，写明两次提交之间与会话有关的变化（DeepSeek Harness 的固定提交没变）。

## 用法

克隆主仓库默认不下载子模块内容，需要时再初始化（全部浅克隆约 900 MB：检出文件约 660 MB，`.git/modules` 约 240 MB）：

```bash
git submodule update --init --depth 1
```

更新到上游最新后，提交新的子模块指针，并把调研报告的链接迁移到新提交、在报告 §0 补「迁移核对」：

```bash
git submodule update --remote --depth 1
```

`MistyHuang03` 的 `feat/plain-language-backend` 分支也有 `third_party/deepseek-harness`（同一路径、URL 与提交），合并时 `.gitmodules` 取并集即可。

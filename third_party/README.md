# 第三方参考源码

六个开源 agent 的上游仓库以 git submodule 形式放在这里，供[会话格式调研](../docs/research/agent-sessions/README.md)与连接器开发查源码。只作参考，不参与构建，也不运行。

| 目录 | 上游 | 跟踪分支 | 固定提交 | 提交日期 | 最新发布 | 许可 |
| --- | --- | --- | --- | --- | --- | --- |
| `pi` | [earendil-works/pi](https://github.com/earendil-works/pi) | main | `7fbbd5f` | 2026-10-01 | v1.0.0 | MIT |
| `hermes-agent` | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | main | `be5e9f7` | 2026-10-01 | v2026.9.24 | MIT |
| `deepseek-harness` | [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) | master | `639ed01` | 2026-09-29 | 无 GitHub Release（npm `@deepseek-ai/dsh` 0.2.0-rc.2） | MIT |
| `opencode` | [anomalyco/opencode](https://github.com/anomalyco/opencode) | dev | `a79ecfe` | 2026-10-01 | v1.18.34 | MIT |
| `codex` | [openai/codex](https://github.com/openai/codex) | main | `cb6da58` | 2026-10-02 | rust-v0.160.0 | Apache-2.0 |
| `claude-agent-sdk-python` | [anthropics/claude-agent-sdk-python](https://github.com/anthropics/claude-agent-sdk-python) | main | `bfb895c` | 2026-10-01 | v0.2.163 | MIT |

固定提交是 2026-10-02 各上游默认分支的最新提交。Claude Code CLI 不开源；`anthropics/claude-code`（CHANGELOG）与 `anthropics/claude-agent-sdk-typescript` 的许可是 Anthropic 商业条款，不收录为子模块，调研报告直接链接 GitHub。

调研报告目前引用的是分析时的提交（pi `88ff80b`、hermes-agent `44a1ce9`、opencode `63cf236`、codex `9552906`、claude-agent-sdk-python `db750b2`），之后会迁移到上表的提交。

## 用法

克隆主仓库默认不下载子模块内容，需要时再初始化（全部浅克隆约 650 MB）：

```bash
git submodule update --init --depth 1
```

更新到上游最新后，提交新的子模块指针，并同步更新调研报告引用的提交：

```bash
git submodule update --remote --depth 1
```

`MistyHuang03` 的 `feat/plain-language-backend` 分支也有 `third_party/deepseek-harness`（同一路径、URL 与提交），合并时 `.gitmodules` 取并集即可。

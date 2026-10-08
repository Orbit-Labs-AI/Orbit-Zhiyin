# 固定版本的第三方参考源码

这些 submodule 用于研究上游会话格式和连接器实现，不是普通 bootstrap 的构建依赖。各项目遵循自己的许可与版权声明，Orbit 的许可证不覆盖它们。

| 目录 | 上游 | 当前树中的固定提交 |
| --- | --- | --- |
| `claude-agent-sdk-python` | [claude-agent-sdk-python](https://github.com/anthropics/claude-agent-sdk-python) | `bfb895c6ef46` |
| `codex` | [codex](https://github.com/openai/codex) | `4dd51f4a5f20` |
| `deepseek-harness` | [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) | `639ed0153972` |
| `hermes-agent` | [hermes-agent](https://github.com/NousResearch/hermes-agent) | `10c6188de188` |
| `opencode` | [opencode](https://github.com/anomalyco/opencode) | `1ddb0873aee5` |
| `pi` | [pi](https://github.com/earendil-works/pi) | `7fbbd5f4a1d9` |

需要研究特定项目时只初始化对应子模块：`git submodule update --init --depth 1 third_party/<目录>`。固定提交以当前 Git 树为准，不等同上游最新发布。

升级引用须有明确研究或兼容需求，核对格式差异、许可证和引用位置，再提交新的 gitlink，并在 TeamHub 更新研究记录；不要为运行 App 自动更新全部上游。研究结论保留采样版本和日期，见 TeamHub 的[Agent 会话格式对比](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/02-%E7%A0%94%E7%A9%B6/Agent%E4%BC%9A%E8%AF%9D%E6%A0%BC%E5%BC%8F/Agent%E4%BC%9A%E8%AF%9D%E6%A0%BC%E5%BC%8F%E5%AF%B9%E6%AF%94.md)。

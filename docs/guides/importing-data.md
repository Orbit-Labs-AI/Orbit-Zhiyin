# 导入会话

Orbit 读取已明确启用的本机 Agent 来源。发现某个 Agent 已安装与允许导入其历史是两件事；检查来源列表不会自动把全部目录作为分析样本。

## 在 App 中导入

1. 在首次引导或设置的数据源页面选择 Agent 和来源目录。
2. 确认本次读取范围后启动导入。源目录保持只读，索引与派生数据写入 Orbit 的数据目录。
3. 查看当前阶段和错误说明。文件数是扫描单位，会话数是解析结果，不要求相等。
4. 导入发布后进入会话轨迹，先核对来源、项目和时间筛选，再阅读概览与人格。

后续同步会复用已处理内容；实际增量粒度取决于来源格式。暂停采集、排除会话与删除数据的区别见[隐私与数据](privacy.md)。

## 支持的来源

| Agent | CLI 标识 | 读取范围与限制 |
| --- | --- | --- |
| Claude Code | `claude_code` | 会话 JSONL 与子代理记录；父子证据取决于实际落盘内容 |
| Codex | `codex` | rollout 与白名单状态元数据；也可桥接 TypeScript staging 归档 |
| DeepSeek Harness | `dsh` | 已适配的事件与压缩记录；未知插件事件保留诊断 |
| pi | `pi` | 消息树、工具调用与可识别的 fork 关系 |
| Hermes | `hermes` | 只读 SQLite 导出；累计用量不冒充逐次请求 |
| OpenCode | `opencode` | 已适配的 SQLite 消息与 part 格式，含更新记录 |
| Kimi Code | `kimi` | 已适配的 wire / session 格式；不同代际 CLI 的格式不保证相同 |

适配与构造测试覆盖不等于所有上游版本都经真实环境验证。查[连接器说明](../modules/data/agent-connectors.md)了解证据范围，报告不支持的格式时提供脱敏的最小记录。

## 使用命令行

从已配置的源码工作区运行；全局参数写在子命令之前：

```sh
uv run orbit discover
uv run orbit --home .local/my-orbit ingest --agent codex --root "$HOME/.codex"
uv run orbit --home .local/my-orbit verify
uv run orbit --home .local/my-orbit report --output .local/my-report
```

运行 `ingest` 即明确启用所写来源。来源根与输出 home 不能互相包含；如果仓库本身位于 `~/.codex/worktrees/`，请把 home 改成该目录之外的位置。小样本可给 `ingest` 增加 `--limit 3`，它限制来源文件数，不表示最近三个会话。

Ctrl+C 可中断 CLI 导入。重新运行相同命令会复用已捕获内容；需要从保留输入重建时使用 `orbit --home <目录> rebuild`。索引模式下，源文件被删除或改写后，原文下钻可能不可用；不要将索引当成独立备份。

更完整的命令见 [CLI 指南](../development/usage.md)，导入阶段见[导入流程](../development/import-pipeline.md)。返回[使用指南](README.md)。

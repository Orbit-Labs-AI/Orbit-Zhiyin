# 本机安装清单

安装清单回答「在用户选择的位置看到了哪些配置和安装文件」。它与会话导入分开，不会自动扫描用户目录，也不会把安装、缓存或配置声明当作实际调用证据。

## 使用方式

从仓库根运行；每条 `scan-inventory` 命令都显式授权一个来源。`--home` 必须位于所有来源目录之外。

```sh
uv run tandem-data --home .tandem scan-inventory --agent codex --root ~/.codex
uv run tandem-data --home .tandem scan-inventory --agent claude_code --root ~/.claude --claude-config ~/.claude.json
uv run tandem-data --home .tandem scan-inventory --agent common --root ~/.agents
uv run tandem-data --home .tandem inventory
```

项目配置用 `--agent project --root /path/to/project`。可传 `--project-id` 关联已有 canonical project；不存在的 ID 会被拒绝。未关联的项目仍可在不限定项目的清单中看到，但不会混入指定项目的分析。项目根在数据目录的上级时，应把 `--home` 放到项目之外。

默认不跟随越出来源目录的符号链接。确需读取共享 Skill 目录时，增加 `--allow-root /path/to/shared-skills`；这只允许扫描器跟随已知配置入口的链接，不会遍历整个新增目录。不要把整个用户主目录作为授权范围。

扫描错误返回退出码 2，并输出结构化诊断；已有的其他有效项仍会发布。`inventory` 仅读取数据库，不触碰来源。`discover` 和会话 `scan` 的行为保持原有语义，不自动启用安装清单。

## 支持范围

| 来源布局 | 读取入口 |
| --- | --- |
| `codex` | `config.toml` 的 MCP、插件声明、Skill 开关；`skills/`；`AGENTS.md`、`AGENTS.override.md`、`rules/`；`hooks.json`；`plugins/cache/<market>/<plugin>/<version>/` 中的插件 manifest、Skills、`.mcp.json`、`hooks/hooks.json`；`automations/<id>/automation.toml` |
| `claude_code` | `settings.json`、`settings.local.json` 的 Hooks、插件开关、MCP；`skills/`、`CLAUDE.md`、`rules/`、`.mcp.json`；`plugins/installed_plugins.json` v2 和同样的插件缓存结构 |
| Claude 全局 MCP | 仅在显式传入 `--claude-config` 后读取该文件的 `mcpServers` 和 `projects.*.mcpServers`；不自动寻找根目录外的 `~/.claude.json` |
| `common` | 所选共享目录的 `AGENTS.md`、`rules/`、`skills/` |
| `project` | 项目根规则文件；`.github/copilot-instructions.md`、`.cursor/rules/`；`.agents/skills/`、`.codex/skills/`、`.codex/rules/`、`.codex/config.toml` 中的 MCP；`.claude/` 配置及根 `.mcp.json` |
| `claude_desktop` | 显式指定会话目录下的 `scheduled-tasks.json`，支持对象中的 `tasks` 数组；其他结构报告 `unsupported_task_layout` |

扫描只支持表中路径及格式，不宣称覆盖整台机器。其他 Agent 配置格式、系统 crontab/launchd、远程安装、插件自定义组件路径和市场目录不是本版的安装事实源。目录读取有深度、文件数量和单文件 2 MiB 上限，触限会报告部分覆盖。插件自定义路径不自动展开；市场中可安装的插件也不算本机已安装。

## 数据含义与隐私

六种 `type` 为 `skill / mcp / hook / plugin / rule / scheduled_task`。每项保留名称、来源配置路径、文件内 locator、内容哈希、可空 `enabled` 和少量白名单元数据。

`evidence` 区分：

- `file`：看到了 Skill 或规则文件。
- `configured`：配置中声明了条目，不保证对应组件实际存在。
- `installed`：Claude 的安装登记表声明了安装。
- `cached`：插件缓存中存在文件；缓存可能来自已禁用或曾安装的插件。

同名配置声明、安装登记和缓存观察分别保留，以便核对来源；`rows` 是观察条数，不能直接当成去重后的插件安装数量。`enabled=null` 表示没有明确开关；此模块不计算配置继承、项目覆盖、运行时生效状态。技能名称默认采用目录名。任务仅保留名称与已知启用状态，不持久化任务正文。Hooks 保留事件类型与索引，不保留命令正文。

配置不进入 L0 原始归档。账号、环境变量值、headers、命令、参数、URL、提示词、规则和 Skill 正文不入库；文件正文只用于生成哈希。凭据文件、`.env`、OAuth 文件和备份目录不会作为输入打开，符号链接到这些文件也会拒绝。JSON/TOML 解析错误只保存错误代码，不保存可能包含凭据的解析器异常原文。

## 快照与分析契约

存储迁移 005 新增 `inventory_scan` 和 `inventory_item`，`user_version=5`，事件契约仍为 v1。扫描沿用单写者锁，并在一个事务中发布完整快照。每次显式扫描产生一个新快照；来源中的删除会在下一次可见清单中消失，旧快照仍保留。会话 L2/L3 重算不删除安装观察。

App 可直接调用：

```python
from pathlib import Path
from tandem_data.inventory import InventoryRequest, read_inventory, scan_inventory
from tandem_data.store import Store

with Store('/path/to/tandem-data') as store:
    result = scan_inventory(store, InventoryRequest('codex', Path('/path/to/codex-home')))

inventory = read_inventory('/path/to/tandem-data')
```

`read_inventory` 不要求会话投影已经建立。原有 `read_analysis` 仍要求会话投影就绪，并在同一读事务中增加 `inventory` 和 `inventory_scans`；后端 `AnalysisInputBundle` 和分析结果也透传清单。`sample_boundary.inventory_scan_ids` 参与内容指纹，扫描改变后不会复用旧分析身份。

- 从未扫描：`inventory=null`，`coverage.inventory.status=unavailable`。
- 支持的范围已扫描为空：清单为 `[]`，相应类别状态为 `available`，条数为 0。
- 配置损坏、权限不足、越界链接、触限：对应类别为 `partial`，诊断列出原因，其他有效观察仍可用。
- 布局没有实现的类别：该类别为 `unavailable`、条数为 null；每个来源单独保留覆盖信息，不用其他来源的成功掩盖它。

时间截止查询选择 `observed_at < until_ts` 的各来源最后一次快照，不读取截止时间之后的配置。全局观察不会因会话／模型筛选消失；指定项目时仅保留全局及关联项目的观察。当前配置、历史快照都只能证明「扫描时看到什么」，不能证明此前某次会话已启用、注入、调用或产生效果。Catalog 链接和调用归因仍是独立工作。

# 本机安装清单

安装清单回答「在用户选择的位置看到了哪些配置和安装文件」。它与会话导入分开，不会自动扫描用户目录，也不会把安装、缓存或配置声明当作实际调用证据。

详细的可执行测试矩阵、通过标准与验证边界见 [安装清单测试与验收](inventory-testing.md)。

此次完整性复核、已修复漏项与证据边界见 [完整性复核记录](inventory-audit.md)。

## 使用方式

从仓库根运行；每条 `scan-inventory` 命令都显式授权一个来源。`--home` 必须位于所有来源目录之外。

```sh
uv run tandem-data --home .tandem scan-inventory --agent codex --root ~/.codex
uv run tandem-data --home .tandem scan-inventory --agent claude_code --root ~/.claude --claude-config ~/.claude.json
uv run tandem-data --home .tandem scan-inventory --agent common --root ~/.agents
uv run tandem-data --home .tandem inventory
```

项目配置用 `--agent project --root /path/to/project`。所有 Agent 布局均可传 `--project-id` 关联已有 canonical project；不存在的 ID 会被拒绝。未关联的项目仍可在不限定项目的清单中看到，但不会混入指定项目的分析。项目根在数据目录的上级时，应把 `--home` 放到项目之外。

默认不跟随越出来源目录的符号链接。确需读取共享 Skill 目录时，增加 `--allow-root /path/to/shared-skills`；这允许扫描器读取已知配置引用和声明的包位置，不会遍历整个新增目录；需要额外发现 Skills 时使用 `--skill-root`。不要把整个用户主目录作为授权范围。

扫描错误返回退出码 2，并输出结构化诊断；已有的其他有效项仍会发布。`inventory` 仅读取数据库，不触碰来源。`discover` 和会话 `scan` 的行为保持原有语义，不自动启用安装清单。

## 支持范围

| 来源布局 | 读取入口 |
| --- | --- |
| `codex` | `config.toml` 的 MCP、插件声明、Skill 开关；`skills/`；`AGENTS.md`、`AGENTS.override.md`、`rules/`；`hooks.json`；`plugins/cache/<market>/<plugin>/<version>/` 中的插件 manifest、Skills、`.mcp.json`、`hooks/hooks.json`；`automations/<id>/automation.toml` |
| `claude_code` | `settings.json`、`settings.local.json` 的 Hooks、插件开关、MCP；`skills/`、`CLAUDE.md`、`rules/`、`.mcp.json`；`plugins/installed_plugins.json` v2、已授权 installPath、插件缓存与 `plugins/synced/` 的组件 |
| Claude 全局 MCP | 仅在显式传入 `--claude-config` 后读取该文件的 `mcpServers` 和 `projects.*.mcpServers`；不自动寻找根目录外的 `~/.claude.json` |
| `dsh` | 全局及 `profiles/*/` 的 `cordis.yml`、`cordis.patch.yml`、`package.json` 中的 `dsh.profile.bundles` 和已授权的 bundle manifest/patch；旧版 `settings.yaml`；`skills/`、`AGENTS.md`；默认 `storages/schedule.json` v1 |
| `pi` | `settings.json` 的 packages、extensions、skills；`extensions/` 入口文件、`skills/`、`AGENTS.md`、`mcp.json` |
| `hermes` | 根目录及 `profiles/*/` 的 `config.yaml`（MCP、插件开关、禁用 Skills）、`skills/`、`AGENTS.md`、`SOUL.md`、`plugins/` 的两层分类 manifest、`hooks/*/HOOK.yaml`、`cron/jobs.json`（对象或历史数组格式） |
| `opencode` | **配置目录**中的 `opencode.json`、`opencode.jsonc`、`config.json`，兼容 v1/v2 MCP、plugin/plugins、skills 与 instructions；`skill/`、`skills/`、`plugin/`、`plugins/`、`AGENTS.md` |
| `kimi` | `config.toml` 的 hooks 和 extra_skill_dirs；`mcp.json`、`skills/`、`AGENTS.md`；`plugins/installed.json` v1 及已授权的 `kimi.plugin.json`；`sessions/*/*/agents/*/cron/*.json` 与同目录 wire 中的 cron 新增／删除记录 |
| `common` | 所选共享目录的 `AGENTS.md`、`rules/`、`skills/` |
| `project` | 项目根规则文件；`.github/copilot-instructions.md`、`.cursor/rules/`；`.agents/skills/`、`.codex/skills/`、`.codex/rules/`、`.codex/config.toml` 中的 MCP；`.claude/` 配置及根 `.mcp.json` |
| `claude_desktop` | Claude 应用数据根的桌面 MCP 配置、extension 安装记录、固定账户层级中的 remoteMcpServersConfig、Cowork 插件及 RPM 组件、Skills；scheduled-tasks.json 兼容 tasks / scheduledTasks；会话 MCP 明确标记为缓存观察 |

扫描只支持表中路径及格式，不宣称覆盖整台机器。七个内置会话 connector 均有扫描适配器；系统 crontab/launchd、远程安装和市场目录不是本版的安装事实源。目录读取有深度、文件数量和单文件 2 MiB 上限，触限会报告部分覆盖。新增适配器声明的本地资源路径仅在已授权目录内展开；远程 URL、glob、未知启动 cwd 和无法解析的引用报告 partial，不发起下载。市场中可安装的插件不算本机已安装。

## 数据含义与隐私

六种 `type` 为 `skill / mcp / hook / plugin / rule / scheduled_task`。每项保留名称、来源配置路径、文件内 locator、内容哈希、可空 `enabled` 和少量白名单元数据。

`evidence` 区分：

- `file`：看到了 Skill 或规则文件。
- `configured`：配置中声明了条目，不保证对应组件实际存在。
- `installed`：Claude 的安装登记表声明了安装。
- `cached`：插件缓存中存在文件；缓存可能来自已禁用或曾安装的插件。

同名配置声明、安装登记和缓存观察分别保留，以便核对来源；`rows` 是观察条数，不能直接当成去重后的插件安装数量。`enabled=null` 表示没有明确开关；此模块不计算配置继承、项目覆盖、运行时生效状态。技能名称优先采用安全解析的 frontmatter name，缺失时采用目录名。发现 SKILL.md 后停止深入辅助目录，排除 .trash。任务仅保留名称与已知启用状态，不持久化任务正文。Hooks 保留事件类型与索引，不保留命令正文。

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

## 七个 connector 的接入注意事项

```sh
uv run tandem-data --home .tandem scan-inventory --agent dsh --root ~/.dsh
uv run tandem-data --home .tandem scan-inventory --agent pi --root ~/.pi/agent
uv run tandem-data --home .tandem scan-inventory --agent hermes --root ~/.hermes
uv run tandem-data --home .tandem scan-inventory --agent opencode --root ~/.config/opencode
uv run tandem-data --home .tandem scan-inventory --agent kimi --root ~/.kimi-code
```

`--root` 始终是显式授权的配置根。OpenCode 会话 connector 的根通常是 `~/.local/share/opencode`，安装扫描应另选 `~/.config/opencode` 或实际 `XDG_CONFIG_HOME` 下的配置目录；不会根据会话根自动读取用户目录。项目内 `.pi/`、`.opencode/`、`.dsh/` 或 `.kimi-code/` 可使用对应 Agent 布局并传 `--project-id`，不必将它们标成全局配置。

- **Pi / OpenCode**：插件／扩展会在运行时注册 Hook 或自行调度任务，缺少统一静态清单。扫描器记录扩展本身，不执行 JS/TS；这两个类别继续返回 unavailable。不能将该状态解释为没有 Hooks 或定时任务。
- **DSH**：记录 Cordis 声明及 profile，不尝试计算完整继承和 patch 生效顺序。`!!js` 仅作为不透明表达式读取并报告 partial；不执行表达式、不启动 Harness。默认 JSON schedule v1 可读取，外部存储根须独立授权；其他后端和动态路径不作为已完成扫描。Hook 桥的相对路径依赖启动 cwd，无法确认时报告 partial。
- **Hermes**：profile 单独保留配置路径。同名插件、MCP 不跨 profile 合并；插件禁用优先于显式启用。Hook manifest 和插件代码不被导入执行。
- **Kimi**：注册表中的安装记录与 managed 目录中的旧残留有区别，只展开注册条目。插件总开关及 MCP capability 的显式禁用被保留。定时任务先读旧版 cron JSON，再按 wire 的 `cron.add` / `cron.delete` 覆盖；会话持久化不证明任务当前正在运行。wire 仅读取既定文件，仍受单文件 2 MiB 上限约束，超限报告 partial，其他会话观察仍保留。除 cron 字段外，wire 内容被丢弃且不归档。

新增 YAML 和 JSONC 解析依赖由根 `uv.lock` 统一锁定。YAML 使用 SafeLoader，拒绝别名、循环及任意对象标签；DSH 的特定 `!!js` 标签只能变成不透明值。解析和遍历均受结构深度、节点数量及文件大小限制。配置中的环境变量／文件插值不展开，凭据目录中的文件即使被引用也不读取。

实现依据为当前检出的上游源文件：

- DSH：`third_party/deepseek-harness/apps/cli/src/profile-boot.ts`、`packages/settings/settings/src/index.ts`、`packages/schedule/schedule/src/storage.ts`、`packages/storage/storage-json/src/format.ts`。
- Pi：`third_party/pi/packages/coding-agent/src/core/settings-manager.ts`、`src/extensions/mcp/config.ts`。
- Hermes：`third_party/hermes-agent/hermes_cli/plugins_discovery.py`、`gateway/hooks.py`、`cron/jobs.py`。
- OpenCode：`third_party/opencode/packages/core/src/config.ts`、`src/config/mcp.ts`、`src/v1/config/config.ts`。
- Kimi：[配置路径](https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/data-locations.html)、[Hooks](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html)、[安装登记源码](https://github.com/MoonshotAI/kimi-code/blob/main/packages/agent-core-v2/src/app/plugin/store.ts)、[只读 cron 合并源码](https://github.com/MoonshotAI/kimi-code/blob/main/apps/vis/server/src/lib/cron-store.ts)。

## 共享目录与 Claude 应用数据根

```sh
uv run tandem-data --home .tandem scan-inventory --agent codex --root ~/.codex --skill-root ~/.agents/skills
uv run tandem-data --home .tandem scan-inventory --agent claude_desktop --root "$HOME/Library/Application Support/Claude"
```

`--skill-root` 可重复使用，明确授权并扫描额外 Skill 根；`--allow-root` 仍用于允许配置引用（DSH 还会在明确授权的安装根下按声明包名查找 manifest），不会遍历整个用户目录。数据 home 不得位于任何授权根之内。

Claude Desktop 的远程连接器来自最新可读账户会话快照，使用 `cached` 证据和原生 `source_observed_at`，不声称是实时账号安装列表。同步插件与插件内联／自定义路径组件已接入，marketplace 中仅可安装的条目不会被计入。

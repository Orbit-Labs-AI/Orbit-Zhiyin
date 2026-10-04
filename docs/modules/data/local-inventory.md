# 本机安装清单

安装清单是显式授权目录的只读观察，供资源详情、重复安装判断与分析覆盖使用。它与会话导入、公共 Catalog、安装账本和实际调用证据分别维护。

## 扫描

```sh
uv run orbit-data --home .local/my-orbit scan-inventory --agent codex --root "$HOME/.codex"
```

会话根与配置根可能不同，例如 OpenCode 的数据目录和配置目录；额外规则/Skill 根也需明确授权。`--skill-root` 用于额外 Skill 根，`--allow-root` 用于配置引用的获准边界。home 不能位于授权来源内。

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

## 证据与隐私

类型包括 skill、mcp、hook、plugin、rule、scheduled_task、command、agent。每条观察保留配置路径、locator、哈希和可空 enabled。`file` 表示文件存在，`configured` 表示配置声明，`installed` 表示安装登记，`cached` 表示缓存观察；它们不能直接相互替代。

不执行插件、Hook、表达式或配置插值。账号、环境变量值、headers、命令、参数、URL、提示词和规则正文不作为库存内容保存；正文只用于受控识别和哈希。凭据与 `.env` 不作为输入，解析错误保留代码而不保存含密钥的异常正文。

## 快照与消费

扫描在事务中发布快照，历史截止读取此前各来源最后一次观察；会话重建不删除库存。未扫描为 unavailable，支持且已知为空为 available，损坏/触限为 partial。扫描 ID 参与分析身份，不能复用不同扫描边界的旧结果。

观察说明扫描时的配置，不证明过去某次会话已启用、注入、调用或受益。全局、项目、profile 和账户缓存分别保留来源，不通过同名或其他来源成功掩盖缺口。

程序接口为 `InventoryRequest`、`scan_inventory`、`read_inventory`；实现位于 [inventory](../../../packages/data/src/orbit_data/inventory/)。验证见[清单测试](inventory-testing.md)。

## command 与 agent 类型

schema 15 将斜杠命令文档和子代理定义独立为 command、agent；旧扫描器以 skill + config.component 保存的记录由迁移 015 转换。目前 claude_code 与 project 布局扫描这两类，其他布局报告 unsupported_by_layout / inventory_layout_incomplete，不能解释为已确认不存在。

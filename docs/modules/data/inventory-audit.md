# 安装清单完整性复核：来源遗漏与修正

## 结论与原因

本次复核由实际漏项触发：Vercel、Cloudflare、Cloudflare Developer Platform 存在于 Claude Desktop 的会话配置快照 `remoteMcpServersConfig`，原扫描器只读取本地 MCP 配置，未读取该来源。原结果不能代表 Claude 的完整工具清单。

已有测试主要证明所实现路径的解析、隐私和存储正确，没有证明来源发现完整。此次增加独立来源样本，并用已授权的本机目录对照；不能以测试通过代替覆盖范围说明。

修正后的 scanner 版本为 `1.2.0`，事件与数据库版本不变。

## 分 connector 检查结果

| 来源 | 确认的问题 | 修正及回归 |
| --- | --- | --- |
| 共用 Skills 读取 | 遍历 `.trash`；进入 Skill 的 scripts 等辅助树导致虚假深度错误；目录名代替 frontmatter 名称；一个越界链接可能影响健康同级目录 | 排除回收站；遇到 `SKILL.md` 即停止向下发现；安全读取 frontmatter name；逐子目录隔离错误 |
| 共用插件读取 | 只识别默认 `skills/` 与 `.mcp.json`，遗漏 manifest 内联与自定义路径；把 sidecar 文件当成版本目录 | 支持内联／路径／数组组件，兼容裸 MCP map；默认位置与 manifest 重复引用同一组件时去重；目录型布局只遍历目录；组件必须留在插件根内 |
| Claude Code | `plugins/synced` 无安装登记，原实现整类遗漏；安装登记可指向 cache 外目录 | 增加同步插件及组件，标注 `account_sync` 和 cached；读取已授权 installPath；不会把 marketplace catalog 当安装 |
| Claude Desktop / Cowork | 未读远程连接器快照、桌面扩展、Cowork 安装记录和 RPM 组件；实际任务字段为 `scheduledTasks` | 限定账户目录层级，读取明确元数据字段；扩展／插件／组件进入清单；兼容 `tasks` 与 `scheduledTasks` |
| Codex | `skills.config.path` 只有声明，没有读取目标；插件自定义组件遗漏；安装 marker 和 automation salt 被当成目录 | 展开已授权路径并保留显式禁用；共享插件解析；忽略非目录 sidecar，仍记录真正缺失的 manifest |
| Pi | 只记录 packages 声明，遗漏已安装包的 Skills；共享目录未显式扫描 | 读取已授权 npm/local/git 包的 `package.json` 与 `pi.skills`；无 manifest Skills 字段时扫描默认目录；保留 disable-all；额外目录通过 `--skill-root` 显式接入 |
| Hermes | 只读 YAML 插件，遗漏 portable `plugin.json` / `mcp.json`；未兼容 hooks 别名 | 扩展 manifest 发现与 portable MCP/Skills；兼容 provides_hooks / hooks；保留禁用传播和 profile 隔离 |
| OpenCode | 普通服务器恰好叫 `servers` 时可能被误判为 v2 容器；timeout-only 元数据可能被当成 MCP | 区分服务器字段与 v2 容器；timeout-only 不产生虚假服务器；项目根仅识别 opencode.json/jsonc，避免读入普通 config.json |
| DSH | 未启用但已安装的依赖未列出；仅查 profile/node_modules，遗漏 CLI 安装目录的 shipped bundle | 记录 profile dependencies 与已安装 manifest；只在额外明确授权的根下按包名查找；静态禁用传递给组件 |
| Kimi | 插件组件引用可能逃出插件根，只要仍在总授权根内就被收录；直接 SKILL.md 引用名称不正确 | 插件内引用增加 containment 校验；直接 SKILL.md 使用共同 Skill 解析；保留 cron 文件／journal 合并与删除语义 |
| 项目入口 | 原 project 布局没有聚合 Pi、OpenCode、DSH、Kimi 项目配置 | 加入已有 `.pi`、`.opencode`、`.dsh`、`.kimi-code` 子目录及根 opencode 配置；不会读无关 generic config.json |

## 云端连接器：观测来源不能伪装为实时安装

Claude 桌面应用可以把云端连接器送入会话，它们不必出现在 `.claude.json`。本模块仍是离线只读采集，不用账号凭据调用云端 API。

- 每个账户／组织目录只采用原生 `lastActivityAt` / `createdAt` 时间最新的可读会话快照，避免把所有历史会话取并集后复活已删除的连接器。
- 元数据仅抽取服务器名称、原生 ID、工具数量和原生观察时间；不持久化工具 schema、提示词、标题、账号内容、URL 或凭据。
- 记录为 `evidence=cached`、`source_kind=latest_readable_account_session`，保留 `source_observed_at`。`enabled` 保持 null。
- MCP coverage 明确为 partial，诊断为 `session_snapshot_is_not_live_inventory`。这些记录证明最近一份本地会话快照里出现过该连接器，不证明它现在仍在账号中启用。
- 有较新空快照时不退回旧非空快照；有坏文件、缺失时间或读取超限时保留诊断，不把其当作已确认的当前空清单。

## 本机复核边界

2026-10-02 使用本分支代码只读复核了本机实际存在的 Claude Code（两套配置）、Claude Desktop、Codex、DSH 与 Pi 根目录，以及明确授权的共享 Skills 和 DSH 安装目录。真实清单与数据库仅保存在 `.local/` 忽略目录，没有提交原始内容。

- Claude Desktop 快照中重新获取到 Vercel、Cloudflare、Cloudflare Developer Platform；Claude Code 同步插件中的 Skills 也已进入清单。
- Codex 插件缓存中可获取 Vercel／Cloudflare 插件及其 Skills；仍标注缓存证据，不推断已启用。
- 原先 Skill 辅助目录、插件 sidecar 和 automation salt 产生的虚假错误已消除。
- DSH 的动态 YAML 表达式和运行时计算存储路径仍有明确诊断；扫描器不会为补全清单而执行 `!!js`。
- 本机没有 Hermes、OpenCode、Kimi 的默认配置根，不能宣称这三家已通过本机实测；它们通过对应上游布局的构造回归验证。

名称去重只用于展示，不是跨账号、跨版本、跨证据层的安装实体合并。不要把“本地配置 + 缓存组件 + 会话快照”的总条数显示成已安装或正在启用的数量。

## 回归与维护

新增 [`test_inventory_completeness.py`](../../../packages/data/tests/test_inventory_completeness.py) 覆盖上述漏项，包括七家共用的 Skill 边界、Vercel/Cloudflare 会话快照、最新空快照、同步插件、自定义 manifest、desktop extension、任务原生键、Pi 包资源、Hermes portable 插件、OpenCode 字段冲突、DSH 已安装依赖与安装根、Kimi containment、共享根授权、sidecar、项目入口及坏元数据隔离。

后续新增或调整 connector 时，至少核对：用户根、项目根、共享目录、安装登记、同步目录、插件组件、缓存／会话证据、动态来源这八个方面。未实现的格式或无法静态确认的范围应明确标注，不仅测试现有路径的 happy path。

来源依据：

- [Claude MCP 的云端连接器投递方式](https://code.claude.com/docs/en/mcp#how-connectors-reach-claude-code)
- [Claude 同步 Skills 与回收站语义](https://code.claude.com/docs/en/skills#skills-synced-from-claudeai)
- [Claude 插件组件的路径与内联格式](https://code.claude.com/docs/en/plugins-reference#component-path-forms)
- 仓库内 upstream：Pi `core/pi-manifest.ts` / `core/package-manager.ts`；Hermes `hermes_cli/agent_plugins.py` / `plugins_manifest.py`；OpenCode `core/src/config/mcp.ts` / `v1/config/mcp.ts`；DSH `app-boot/src/profile-plugins.ts` / `profile-resolution`；Codex `plugin/src/manifest.rs`。

仍不执行云端实时安装列表、动态扩展代码、MCP 握手或 Hook。包内未解析的 glob/复杂资源过滤、远程 bundle 下载和非默认调度后端会保持 partial 或 unknown；本次修正不承诺任意未来 Agent 版本的完全覆盖。

## 本轮验证结果

- 新增完整性回归：24 项通过；原安装清单、契约、权限与分析透传回归继续通过。
- 后端完整测试：1,078 passed（现有 Starlette 弃用警告 1 条）。
- 数据包完整测试：204 passed。
- 锁定依赖同步、Ruff lint、数据包格式检查、全包构建、demo、evaluate、`git diff --check` 均通过。
- evaluate 构造集为 8/8、34/34、12/12；human acceptance 仍为 pending。

以上结论针对本轮代码与已列明的来源。只读真实来源验证补足了合成测试不能证明的“路径是否实际存在”问题，但不会把历史会话快照变成实时云端状态证明。

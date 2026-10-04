# CLI 指南

CLI 适合显式导入、分析、导出与脚本集成。先完成[开发环境](setup.md)，所有命令从仓库根执行。App 使用方法见[用户指南](../guides/README.md)。

## 命令与数据目录

`orbit` 是应用 CLI，`orbit-data` 是数据层工具，`orbit-catalog` 管理独立资源库，`orbit-helper` 启动 App 服务。可用选项以各命令 `--help` 为准。

全局参数放在子命令前，例如 `uv run orbit --home .local/my-orbit analytics`。默认 home 是 `~/Library/Application Support/Orbit`，可用 `ORBIT_HOME` 或 `--home` 覆盖；演示、真实样本和评测分别使用独立目录。

## 示例与报告

```sh
uv run orbit demo
uv run orbit demo --view profile
uv run orbit demo --view bottlenecks
uv run orbit demo --view process
```

默认 `.local/demo/` 保存 Markdown/JSON 报告与 `.local/demo/data/` 的构造数据。运行 `uv run orbit evaluate` 使用独立样本评价，不把评测结果写成用户历史。

## 发现和导入

```sh
uv run orbit discover
uv run orbit --home /absolute/orbit-home ingest --agent codex --root /absolute/authorized-codex-home
uv run orbit --home /absolute/orbit-home verify
uv run orbit --home /absolute/orbit-home rebuild
```

`discover` 只发现，`ingest` 明确启用所写来源。Agent 标识见[导入指南](../guides/importing-data.md)。`--limit N` 限制输入文件，不表示最近 N 个会话；home 与来源根不得互相包含。

进度在 stderr，结构化输出在 stdout；`--no-progress` 关闭进度。取消与重试见[导入流程](import-pipeline.md)。`rebuild` 使用已捕获或索引的输入，不会恢复已经丢失的原文。

## 分析与导出

```sh
uv run orbit --home /absolute/orbit-home analytics --no-text --display-timezone Asia/Shanghai --output .local/report/analytics.json
uv run orbit --home /absolute/orbit-home report --output .local/report
uv run orbit --home /absolute/orbit-home analysis-report --display-timezone Asia/Shanghai --output .local/analysis-report
```

`analytics` 输出特征，`report` 组织画像与建议，`analysis-report` 生成同一组合快照的 JSON/CSV/离线图表。`--no-text` 只跳过文本表示，其他分析仍运行。

用 `--from-ts` / `--until-ts` 选择 UTC 毫秒区间 `[from, until)`，并按命令支持的项目、模型、来源、会话与排除参数缩小范围。未知时间不补入确定窗口；上下文不增加统计分母。

事件预算是子命令前的全局参数：

```sh
uv run orbit --home /absolute/orbit-home --max-events 500000 analytics --no-text
```

默认没有此预算限制；超预算明确失败，不返回伪装完整的部分结果。覆盖状态的解释见[分析指南](../guides/understanding-analysis.md)。

## 证据与历史

```sh
uv run orbit --home /absolute/orbit-home evidence <事件ID> --json
uv run orbit --home /absolute/orbit-home analysis-history --limit 20
uv run orbit --home /absolute/orbit-home analysis-history --run-id <运行ID>
```

只读取所选证据，分享输出前检查隐私。运行历史与事实库存储独立，详见[统计与历史](../modules/analytics/statistics-history.md)。

## 服务与其他工具

`uv run orbit --home <目录> serve --port 8765` 启动报告 API；`pnpm dev --home <目录>` 是同一入口的薄脚本。live UI 使用 [App gateway](setup.md#启动-app-gateway)，两者不要混用。

安装 CLI 的 `install environment` 与 `install ledger` 用于查看，实际写入经 App 预览确认。资源同步与检索用 [orbit-catalog](../../packages/catalog/README.md)；旧报告固定资源核对保留 `catalog-refresh`，不等同当前 App Catalog。

TypeScript staging 通过 `orbit import-connector --connector-home <目录>` 接入，两库分开；见[connector](../../packages/connectors/README.md)。

## 兼容旧数据

旧 MVP 数据库通过显式 `--db <文件>` 读取，保留旧采样约定。不能把旧文件改名为 `orbit.db`，也不能假设旧 ledger 能补出 L0/L1。历史品牌迁移由 [legacy.py](../../packages/data/src/orbit_data/legacy.py)负责，新代码和命令统一用 orbit。

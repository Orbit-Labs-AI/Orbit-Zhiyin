# Tandem 数据契约与预处理

本包提供实际可建库的 SQLite DDL、L0 原始归档、L1 全记录记账、L2 映射、L3 派生、分析读取和 TypeScript connector 归档桥接。设计与字段见 [数据契约](../../docs/contracts/data.md)。无需数据库服务器；Python 3.13 + uv。

从仓库根目录运行：

```sh
uv sync --project packages/data --dev
uv run --project packages/data tandem-data --home .tandem init
uv run --project packages/data tandem-data discover
uv run --project packages/data tandem-data --home .tandem scan --agent codex --root ~/.codex
uv run --project packages/data tandem-data --home .tandem stats
uv run --project packages/data tandem-data --home .tandem verify
uv run --project packages/data tandem-data --home .tandem rebuild
```

`discover` 只列来源；`scan` 明确启用指定根目录。`--limit N` 只用于样本验证，不能声称全量回填。源目录与 `--home` 必须分开。七个内置 agent 名称为 `claude_code / codex / dsh / pi / hermes / opencode / kimi`；未实现的新来源可通过 `capture_stream` 和 `register_mapper` 对接。

TypeScript Codex connector 使用单独的 staging 目录，不能直接写本包的 `tandem.db`：

```sh
node packages/connectors/dist/cli.js ingest --codex-home ~/.codex --data-dir .local/codex-staging
uv run --project packages/data tandem-data --home .tandem import-connector --connector-home .local/codex-staging
```

桥接校验分块哈希并重新解析原始归档，保留 `connector_record_link` 对照。默认源文件已删除也能从 staging 归档导入。macOS App、CLI 和分析后端的接入方式见 [模块化数据入口](../../docs/architecture/data-pipeline.md)。两个 Python 包共用仓库根 `uv.lock`。

分析读取示例：

```python
from tandem_data.analysis_input import AnalysisScope, read_analysis

data = read_analysis(".tandem", AnalysisScope(
    display_timezone="Asia/Shanghai",
    project_ids=None,  # None = 全部；() = 明确选择零个
    include_children=True,
))
print(data["coverage"])
```

验证命令：

```sh
uv run --project packages/data ruff check packages/data/src packages/data/tests
uv run --project packages/data ruff format --check packages/data/src packages/data/tests
uv run --project packages/data pytest packages/data/tests
uv build --project packages/data
git diff --check
```

实际日志、数据库、归档都保留在本机的 `.tandem/`，不提交。测试只使用虚构数据。本包不实现画像、推荐或 LLM 分析，也不采集 Catalog。七个内置 Agent 均支持通过显式 `scan-inventory --agent <agent> --root <配置根>` 接入安装清单，见 [本机安装清单](../../docs/modules/data/local-inventory.md)。

安装清单的详细测试矩阵与验收标准见 [测试方案](../../docs/modules/data/inventory-testing.md)。

## 六类 Agent connector 与 App 模块

新增 connector 的来源差异、架构、存储语义、实测边界和开源依据见 [完整模块说明](../../docs/modules/data/agent-connectors.md)。

```sh
# 仓库根目录：一次运行测试、打包、六家原生样本、本机真实样本和离线查看页
bash scripts/check-data.sh --real --open
```

不读真实数据时省略 `--real`。App 使用 `tandem_data.service.ImportService` 写入，使用 `event_page` / `read_analysis` 只读查询。存储 user_version=5，事件契约仍为 v1；原 v1 数据库自动应用索引迁移。变化文件采用不可变完整快照，未变化文件快速跳过，重算按来源隔离。

## 分析运行记录

`analysis_history.AnalysisHistory` 在独立的 `analysis.sqlite` 保存每次分析运行与不可覆盖的完整结果快照，原始来源和 canonical 事实库不受写入。DDL 位于 `migrations/analysis/`，查询、字段字典与数据边界见[统计分析与完整分析记录](../../docs/modules/analytics/statistics-history.md)。

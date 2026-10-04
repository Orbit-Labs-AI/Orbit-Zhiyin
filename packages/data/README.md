# Orbit Data

`orbit_data` 拥有 canonical 会话库：来源发现与索引、L1 全记录记账、L2 标准事件、L3 派生、安装清单、范围化查询、迁移与完整性验证。画像和推荐属于后端，公共资源目录属于 Catalog。

## 使用

从仓库根安装锁定依赖后，显式选择数据 home 与已授权来源：

```sh
uv sync --locked --all-packages --dev
uv run orbit-data --home .local/my-orbit init
uv run orbit-data discover
uv run orbit-data --home /absolute/orbit-home scan --agent codex --root /absolute/authorized-codex-home
uv run orbit-data --home /absolute/orbit-home stats
uv run orbit-data --home /absolute/orbit-home verify
```

`discover` 不启用导入，`scan` 才启用指定根。来源与 home 不得互相包含；支持标识见[连接器](../../docs/modules/data/agent-connectors.md)。原生扫描主要索引来源，不默认复制全部原文；轨迹和原文可用性见[索引说明](../../docs/modules/data/indexed-trajectories.md)。

## 程序接入

后台写入使用 `Store` 与 `ImportService`，每线程独立连接。只读分析示例：

```python
from orbit_data.analysis_input import AnalysisScope, read_analysis

data = read_analysis('/absolute/orbit-home', AnalysisScope(
    display_timezone='Asia/Shanghai', project_ids=None, include_children=True,
))
print(data['coverage'])
```

空 tuple 表示明确选中零个，None 表示不限制。列表和证据使用分页查询，避免为显示单页加载全量 bundle。库存扫描和分析历史分别见[库存](../../docs/modules/data/local-inventory.md)、[历史](../../docs/modules/analytics/statistics-history.md)。

## Schema 与桥接

DDL 在 `src/orbit_data/migrations/`，当前会话迁移到 015，逻辑契约仍为 v1。改变结构后更新生成字段字典和消费者，见[数据契约](../../docs/contracts/data.md)。analysis/catalog 子目录是独立数据库迁移。

TypeScript producer 写独立 staging，通过 `import-connector --connector-home <目录>` 校验归档后重新映射。两包不共写同一 SQLite，staging L2/L3 不直接作为 canonical。

## 验证

```sh
uv run ruff check packages/data/src packages/data/tests
uv run ruff format --check packages/data/src packages/data/tests
python3 scripts/heavy.py uv run pytest -q packages/data/tests
uv build --package orbit-data
```

构造样本应覆盖记录去向、重放/重复、配对、范围、未知值、迁移和来源只读。真实来源只在明确授权的额外验收中读取，日志、数据库、归档及派生报告不提交。

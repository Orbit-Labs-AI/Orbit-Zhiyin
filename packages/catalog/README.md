# Orbit Catalog

`orbit_catalog` 是本地资源目录：收集允许获取的公开元数据/正文，管理版本、特征与检索索引。它使用独立 `catalog.db`，供资源库与推荐模块消费，不需要读取个人会话。

## 离线开始

从仓库根完成 bootstrap 后：

```sh
uv run orbit-catalog --home .local/catalog init
uv run orbit-catalog --home .local/catalog sync --source orbit-seeds
uv run orbit-catalog --home .local/catalog status
uv run orbit-catalog --home .local/catalog search '排查自动化测试失败' --type skill
uv run orbit-catalog --home .local/catalog verify
```

指定公共来源同步或运行不带来源限制的 `sync` 可能联网；先查看来源设置。随包快照、已完成同步和本地条目按实际版本发布，文档不固定条目数为产品能力。

## 本地语义检索

默认可使用词法和特征检索。E5 向量需要 embeddings 可选依赖、明确的本地 ONNX 模型目录以及当前 home 的编码结果：

```sh
uv sync --locked --all-packages --dev --extra embeddings
uv run --extra embeddings orbit-catalog --home .local/catalog --model-dir /absolute/e5-model embed
uv run --extra embeddings orbit-catalog --home .local/catalog --model-dir /absolute/e5-model search '排查自动化测试失败'
```

模型目录须含 `onnx/model.onnx` 与 `onnx/tokenizer.json`。模型由使用者单独准备并固定 revision；工具不自动下载权重。App gateway 可通过绝对路径 `ORBIT_CATALOG_MODEL_DIR` 配置，显式参数优先，变更后重启服务。

模型不可用、编码失败或尚未索引时返回具体向量状态，保留可用的词法/特征路径。测试中的 ToyHashEncoder 只检查流程，不代表语义质量。

## API 与开发

`orbit-catalog serve` 提供目录服务，App gateway 挂载同一模块。列表、详情、过滤、检索、来源和后台任务见[架构及 API](../../docs/modules/catalog/architecture.md)。Swift 客户端见 [catalog-macos](../catalog-macos/README.md)。

数据迁移在 data 包的 `migrations/catalog/`，不用会话库的迁移号。查询返回来源、许可、版本、分项分数和覆盖；元数据完整度及静态风险不等于效果或安全审计。

```sh
python3 scripts/heavy.py uv run pytest -q packages/catalog/tests
uv build --package orbit-catalog
```

性能基准与本机测量不是普通检查的替代。扩展来源时保留水位、分页失败、原子发布和取消/恢复语义。

## 大规模公共语料

固定快照流式导入、index_only、可恢复向量物化与查询预算见[大规模索引](../../docs/modules/catalog/large-corpus.md)。离线种子、联网同步池和模型向量是不同资产；某个来源默认可同步，不代表已经包含在当前随包种子。

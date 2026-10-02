# Recommendation

当前推荐引擎入口为 `service.recommend`，原画像 API 通过 `legacy.py` 兼容。七类资源接收、契约、召回、排序与限制见 [模块说明](../../../../../docs/modules/recommendation.md)。

从仓库根运行 `uv run pytest -q packages/backend/tests/recommend`，构造验收运行 `uv run python -m evals.recommendation.demo`。

`catalog.py` 管理七类资源输入；`legacy_catalog.py` 与 `resource_fetch.py` 保留原固定目录和显式刷新能力。来源抓取与独立索引的 `tandem_catalog` 已由 packages/catalog workspace 包接入。

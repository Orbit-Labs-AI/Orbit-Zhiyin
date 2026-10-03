# Recommendation

App 使用的推荐引擎是 **engine v2**：`services/routes_recommend.py`（`/v1/recommendations*`）→ `runs.py` → `engine.build_slate`（`recall/multi` 11 路召回 → 加权 RRF → `ranking/gates` → `ranking/rank` → `ranking/slate` → `narrate`）。`service.recommend` 是另一套 service 栈，只服务 `/v1/analytics/recommendations` 与 analytics 展示；原画像 API 通过 `legacy.py` 兼容。两栈关系、路由表、排序公式与常数依据，以及七类资源接收、契约、召回、排序与限制见 [模块说明](../../../../../docs/modules/recommendation/engine.md)。

从仓库根运行 `uv run pytest -q packages/backend/tests/recommend`，构造验收运行 `uv run python -m evals.recommendation.demo`。

`catalog.py` 管理七类资源输入；`legacy_catalog.py` 与 `resource_fetch.py` 保留原固定目录和显式刷新能力。来源抓取与独立索引的 `tandem_catalog` 已由 packages/catalog workspace 包接入。

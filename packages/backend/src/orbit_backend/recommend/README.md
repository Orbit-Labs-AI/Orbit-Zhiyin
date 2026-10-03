# App 推荐实现

App 路径为 `services/routes_recommend.py → runs.py → engine.build_slate`：问题与多路召回、RRF、资格、排序、多样性选择及卡片解释。analytics 的 `service.recommend` 是另一入口，旧报告由 `legacy.py` 兼容。

目录输入、来源同步和索引分别由本模块适配与 `orbit_catalog` 承担；不要把固定旧目录当当前 App 的全部候选。推荐结果保留问题证据、来源、未知上下文、未匹配和效果状态。

修改权重、资格或解释时同步规则版本与范围/反例测试。用户反馈、安装和实际效果各自记录，不用推荐分数证明收益。实现职责和公式解释见[推荐手册](../../../../../docs/modules/recommendation/engine.md)。

从根运行：`python3 scripts/heavy.py uv run pytest -q packages/backend/tests/recommend`。构造演示入口为 `uv run python -m evals.recommendation.demo`；它不证明真实任务收益。

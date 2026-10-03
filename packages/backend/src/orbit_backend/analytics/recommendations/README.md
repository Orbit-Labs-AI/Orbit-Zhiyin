# 分析侧瓶颈建议

本模块将已测量的非语义瓶颈转换为分析侧建议，入口为 `recommend_bottlenecks` 与 `RecommendationPolicy`。它消费同范围事实与覆盖，不调用模型或直接安装资源。

输入缺失、适用条件不明与无候选分别保留；已观察的失败和频次不能直接兑换成实际收益。输出包含信号、依据、适用条件与边界，不反向修改分析事实。

App 卡片使用 `orbit_backend.recommend` 的主栈，本模块不能替代 `/v1/recommendations`。两者关系见[推荐引擎](../../../../../../docs/modules/recommendation/engine.md)。扩展时为策略条件、未知值、空范围和证据对应补构造回归，按[测试指南](../../../../../../docs/development/testing.md)验证。

# 瓶颈诊断与推荐兼容入口

推荐主链路已迁到 [recommend/](../../recommend/README.md)。新的资源格式、七类 JSON 接收、RRF、硬过滤、统一评分与 MMR 说明以该文档为准。

本目录保留以下职责：

- `rules.py`：根据 interaction、respond、cost_time、outcome 的已确认特征输出七类瓶颈与证据；不读取资源正文。
- `policy.py`：可调整的样本、覆盖和触发门槛。
- `diagnosis.py`：按根会话树编排既有规则，绑定筛选范围和特征快照 digest。
- `analyzer.py`：保留 `recommend_bottlenecks` 调用签名，转交 `recommend.service`；显式传入的旧资源列表通过适配器转换。
- `catalog.py`、`ranking.py`：保留上一版目录和低层排序函数的兼容性；新主链路不使用旧排序公式。

七类诊断为：确认纠偏密度、同对象重复强调、失败后同参数重试、同工具失败、同任务/版本/范围验证反复失败、明确验收项的证据缺口、完整请求用量与重试/压缩记录共同出现的上下文压力。

词面候选不能升级为确认事件，未知不能当零，孤立子代理不能跨根会话凑样本。未来报告不能进入过去时间窗口。阈值只是待校准的启发式；推荐始终表示可验证的试用方向，不表示已证明效率收益。

可运行 `python scripts/demo_bottleneck_recommendations.py` 使用纯合成数据查看完整推荐结果。旧 API 路径与 CLI JSON 的 `bottleneck_recommendations` 字段继续保留，输出版本现为 `recommendation-pipeline-v1`。

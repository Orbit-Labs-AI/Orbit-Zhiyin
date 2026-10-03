# 资源目录与检索

`orbit_catalog` 管理资源来源、版本、正文许可、特征、索引与检索。它拥有独立 `catalog.db`，不读取个人会话来构建公共目录；推荐模块提供其需要的范围内特征。

## 发布与存储

来源同步先暂存分页结果和 checkpoint，完整扫描后原子发布。失败、取消或页数预算耗尽不能替换完整旧快照。增量空结果不等于清空来源，水位和删除语义由来源适配器明确处理。

资源保存稳定身份与历史版本，内容哈希支持幂等和重复关系；同名不等于同一资源。概览列、特征与检索分块属于可重建投影。许可不足的内容只保留允许的元数据或链接，不能自动显示为已获取正文。

权威 DDL 在 [catalog 迁移](../../../packages/data/src/orbit_data/migrations/catalog/)，字段字典在 [catalog-v1](../../../packages/data/src/orbit_data/schemas/catalog-v1.schema.json)。

## 查询路径

结构化过滤同时约束词法、特征和语义候选。词法使用 FTS/BM25，语义在指定本地模型空间中计算余弦；多路融合和重排保留 score parts、命中特征、文本片段与来源。列表通过游标分页，检索 top-K 和列表分页不是同一种接口。

内存索引随已发布 generation 更新，数据库读事务和缓存需使用一致版本。正文与 chunk 投影按实现版本重建；不要把旧快照中的每项文本或向量重复物化为平行数据库。

## 本地向量

可选 E5 ONNX 模型从明确的本地目录读取，不自动下载，也不使用远端 embedding API。模型空间身份包含权重/tokenizer 摘要、前缀、池化、维度与运行时，不同空间不能混搜。

编码阶段按模型要求使用浮点计算，当前存储投影通过 `embedding_cache` 按文本哈希复用 fp16 向量。资源只选取受控的概览/正文块编码，不等于全部历史正文都有向量。查询采用分块精确余弦，不宣称 ANN；内存、覆盖和吞吐要分别测量。

缺模型、缺运行时、编码失败和待索引分别报告；可继续词法/特征检索，不能用 ToyHash 或词面哈希冒充 E5 结果。配置与物化命令见 [Catalog README](../../../packages/catalog/README.md)。

## API 分组

| 路径（前缀 `/v1/catalog`） | 用途 |
| --- | --- |
| `/items`、`/items/{id}` | 列表、详情、来源、许可与关系 |
| `/search`、`/facets` | 检索与过滤维度 |
| `/sources`、`/sync`、`/jobs` | 来源配置、后台同步与任务 |
| `/embeddings` | 编码与向量覆盖 |
| `/local` | 通过自检的本地生成条目 |
| `/models`、`/benchmarks` | 规范模型元数据与已解析成绩 |

实际方法、参数、错误和兼容端点以 [api.py](../../../packages/catalog/src/orbit_catalog/api.py)为准。gateway 挂载目录服务后可补充安装状态，不能把 Catalog 记录本身当成本机已安装事实。

## 质量与验证

元数据完整度、来源核对、许可状态和静态风险是不同维度，均不表示效果或安全审计通过。公开来源数量与索引规模不是召回质量指标；测试中的 ToyHash 只验证流程。具体基线见[目录审计](../../audits/catalog-validation.md)与[推荐可靠性审计](../../audits/recommendation-reliability-2026-10-03.md)。

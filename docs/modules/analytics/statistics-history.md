# 统计、词频与分析历史

统计与词频结果保留原始样本身份和覆盖；分析历史将运行状态与结果快照分开保存，支持复查同一输入下怎样得到结论。

## 统计与比较

`analytics/products/statistics.py` 汇总有效数、未知数、均值、分位数、离散程度与样本点。异常值是统计标记，不等于坏日志。相关系数描述关联，不以小样本结果声称因果关系。

比较以会话树为重抽样单位并保持重叠关系，样本不足时仍可给描述性差值但区间不可用。方法、种子、有效样本与覆盖随结果解释，不能只展示一条差值。

## 词频与相近文本

只消费可确认主会话真人正文，清理代码、引用和平台注入。分词、停用词、词典与规则版本参与复现。出现次数、消息支持数、会话支持数是三个不同指标。

词频分母是清理后的词，不是模型 token。相似文本不等于相同任务；共现和近邻有显式规模边界，超限保留状态，不悄悄抽掉样本。时间新颖度使用严格过去数据，见[任务](task.md)。

## 运行与结果存储

独立 `analysis.sqlite` 保存 `analysis_run`、压缩结果快照、section、分页行、可复用会话结果及会话排除信息。完成结果不可覆盖，读回校验长度和哈希；损坏应明确失败，不能偷偷换成重算结果。

canonical 分析按规范 Scope、算法版本和输入指纹复用请求/section/会话树结果。跨会话字段在装配时附加，不能误存在单会话缓存。相关参数、来源、排除项或算法变化都应影响身份，结果携带 freshness。

缓存清理与历史运行保留分开；排除会话改变分析样本，不删除事实。进程中断后仍为 running 的历史行只是未正常完成的记录，不能据此证明进程仍存活。旧 `--db` 模式的指纹和缓存能力不同。

## 查询与维护

```sh
uv run orbit --home .local/my-orbit analysis-history --limit 20
uv run orbit --home .local/my-orbit analysis-history --run-id <运行ID>
```

可按 engine/status 查询，按 pointer 对大数组分页，完整选项见 `--help`。历史 DDL 与字典独立于 canonical：

```sh
uv run python -m orbit_data.schema_export --database analysis --output packages/data/src/orbit_data/schemas/analysis-history-v1.schema.json
```

实现见 [analysis_history.py](../../../packages/data/src/orbit_data/analysis_history.py)、[分析迁移](../../../packages/data/src/orbit_data/migrations/analysis/)与 [analytics](../../../packages/backend/src/orbit_backend/analytics/)。缓存优化必须通过范围、未来信息隔离与结果等价性验证。

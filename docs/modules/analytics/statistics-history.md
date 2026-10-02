# 统计分析与完整分析记录

分析现在直接计算真实分布、分组差异、词频、短语、共现和会话文本相似性，并默认保存每次公开分析运行的完整结果。终端和页面只展示前几项时，历史数据库仍保留完整词表、统计样本和证据引用。

## 能分析什么

| 功能 | 一句话说明 |
| --- | --- |
| 数值分布 | 对消息数、调用数、轮次、日志跨度、Token、消息长度、执行时长和请求时延计算均值、标准差、中位数与分位数。 |
| 离散程度 | 用四分位距和中位绝对偏差说明数据分散程度，避免只看一个平均值。 |
| 异常值位置 | 标出落在四分位距规则之外的样本，并保留会话或调用 ID 供回看。 |
| 项目与来源统计 | 按项目、来源分别统计同一组指标，并显示各自已知与未知样本数。 |
| 两组对比 | 比较两个项目、来源或时间范围的均值、中位数、相对变化和词频变化。 |
| 对比区间 | 按整个会话树重抽样估计均值差的区间，保留重抽样次数、种子和有效会话数。 |
| 指标关联 | 用 Spearman 秩相关描述调用量与消息数、日志跨度及 Token 的关系，样本不足或数值恒定时不给系数。 |
| 真实词频 | 对中文分词和英文词统计出现次数、涉及消息数、涉及会话数及每千词频次。 |
| 词语权重 | 计算每个词的 TF-IDF 均值，帮助区分普遍出现的词和集中于少数消息的词。 |
| 重复短语 | 统计同一句中相邻的二词、三词组合，不跨标点或被删除的停用词拼接。 |
| 词语共现 | 统计高频词在同一消息中共同出现的情况，并给出支持消息和可计算时的关联强度。 |
| 相似会话 | 用本地词级 TF-IDF 和余弦距离寻找相近会话，结果不代表它们属于同一个任务。 |
| 完全重复表达 | 按清理后文本的摘要识别重复消息，并保留每次出现的消息 ID。 |
| 词频变化 | 按日期、项目和来源查看词频，并用每千词频次比较不同规模的文本。 |
| 完整历史 | 每次运行保留请求、时间、环境版本、状态、完整结果和证据，失败与未完成运行也能查询。 |

结果位于 `statistics` 与 `lexical`，同时出现在特征分析和 UI 组合分析中。实现入口是 [`statistics.py`](../../../packages/backend/src/tandem_backend/analytics/products/statistics.py) 与 [`lexical.py`](../../../packages/backend/src/tandem_backend/analytics/products/lexical.py)。

## 统计口径

每个指标保留全部 `samples`，每个样本都有身份、所属会话、项目、来源、数值和证据 ID；未知值保持 null。摘要包含已知数、未知数、均值、样本标准差、中位数、P10／P25／P50／P75／P90／P95／P99、四分位距和中位绝对偏差。

例如 `[1, 2, 3, 4, 10]` 的均值是 4，中位数是 3，P90 是 7.6；最后一个值会被四分位距规则标出，但异常值不等于日志错误。日志跨度、可靠执行时长与未知时间继续分开，不能解释成同一种工作时长。

两组对比使用 1,000 次会话树级 bootstrap，种子固定为 0；同一会话树的多条记录一起抽取，两个范围共享的会话树也保持对应关系。每组不足 5 个有效会话树时仍给描述性差值，但区间状态为 `insufficient_sessions`。95% 区间是已观测样本条件下的近似估计，不纠正缺失数据，也不消除任务难度、时间和项目构成的影响；会话树之间近似独立是方法假设。重抽样的一般方法说明见 [SciPy bootstrap 文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)。

Spearman 只显示相关系数、成对样本数与样本点，不用小样本的渐近 p 值声称“显著”或“导致”。失败会话比例另给 Wilson 参考区间，其分母是有调用且能判定是否出现工具失败的会话；未知状态不会补成成功。相关系数与常数输入的处理参照 [SciPy spearmanr 文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.spearmanr.html)。

## 词频与相近分析口径

只使用来源确认的主会话真人正文，沿用既有清理规则去除引用、代码和注入材料。中文使用固定版本 Jieba 精确分词并关闭 HMM，英文保留常见技术词；文本统一做 NFKC 和大小写归一。停用词、分词版本与词典 SHA-256 随结果保存，截断文本标为部分覆盖。[Jieba 官方说明](https://github.com/fxsjy/jieba)介绍了分词模式和 HMM 开关。

词频同时给出三个数字：出现了几次、出现在哪些消息、出现在哪些会话；同一句重复十次不等于十个会话支持。每个词的全部出现证据和每条消息的词计数都保存在结果里。词频的分母是清理与停用词过滤后保留的词数，不能当作模型 Token 用量。

TF-IDF 均值使用每条消息内的词频比例乘以平滑 IDF，再对有效消息取平均；相似会话则使用子线性词频、平滑 IDF 与 L2 归一化后的余弦相似度。两者用途不同，结果中写明方法；[scikit-learn TF-IDF 文档](https://scikit-learn.org/1.7/modules/feature_extraction.html#tfidf-term-weighting)说明了词频、IDF 与归一化。

- 完整词表和已生成的二词／三词短语不做 Top-N 截断，页面展示前 20／30 项只是显示选择。
- 共现计算限定为当前词频最高的 40 个词，并记录所选词表；共同出现不足 3 条消息时，不给 PMI／NPMI。
- 相似性计算每个会话最多取 3 个近邻，最多处理 2,000 个有词的会话；超限返回 `limit_exceeded`，不默默抽掉会话。
- 清理后没有保留词、时间未知和正文截断分别记录；它们不会被补成零情绪、完整文本或已知时间。

## 每次分析怎样保存

数据目录中的 `analysis.sqlite` 专门保存派生分析，canonical `tandem.db` 和原始来源保持原有职责。旧版 `--db` 模式使用同目录的 `<原文件名>.analysis.sqlite`。

| 表 | 保存什么 |
| --- | --- |
| `analysis_run` | 每次执行的独立 ID、分析类型、开始与结束时间、请求参数、运行环境、状态、结果快照引用或错误。 |
| `analysis_snapshot` | 完整结果的压缩 JSON、SHA-256、字节长度、结果版本和分析摘要。 |

成功结果发布与运行状态更新在同一事务内完成；完成后的运行不能覆盖。重复执行相同计算仍产生新的运行记录，只复用相同内容的快照。读取时检查完整字节数与 SHA-256，损坏时明确失败，不返回伪造或部分结果。

`features`、`products`、`comparison` 和持久数据上的旧 `profile` 入口都会自动记录。范围对比同时保存左右两边的完整结果，上期比较保存完整基期。底层纯函数和无持久存储的内存夹具不写盘；参数尚未通过 API 校验的请求不算一次已开始分析。进程意外退出后未完成的条目保留 `running` 和空结束时间，不能据此判断进程仍然存活。

历史不自动删除。数据库及结果文件仅限当前用户访问；原始日志仍由 L0 管理，结果通过证据 ID 回到原记录。运行请求还记录 Python、后端、数据包、Jieba、NumPy、SciPy 和 scikit-learn 的实际版本。

分析历史 DDL 位于 [`migrations/analysis/001.sql`](../../../packages/data/src/tandem_data/migrations/analysis/001.sql)，不进入 canonical 库的迁移序列；字段字典为 [`analysis-history-v1.schema.json`](../../../packages/data/src/tandem_data/schemas/analysis-history-v1.schema.json)。修改该 DDL 后运行：

```sh
uv run python -m tandem_data.schema_export --database analysis \
  --output packages/data/src/tandem_data/schemas/analysis-history-v1.schema.json
```

## 怎样运行和查回结果

先运行 `bash scripts/bootstrap.sh`。完整构造导入、统计、存档和回读验收：

```sh
uv run python -m evals.analytics.products --synthetic \
  --output .local/analysis-statistics-synthetic
```

真实来源仍通过 `--source AGENT=ROOT` 显式启用，命令和目录边界见[端到端验收](analysis-products.md)。脚本同时核对两次公开调用各自有记录，而且保存的完整结果与 CLI／API 一致；报告还输出完整 `words.csv`。

已有数据库上分析和查看历史：

```sh
uv run tandem --home /实际的数据目录 analysis-report --output .local/statistics-report
uv run tandem --home /实际的数据目录 analysis-history --engine products
uv run tandem --home /实际的数据目录 analysis-history --run-id 运行ID \
  --pointer /lexical/terms --limit 100 --offset 0
uv run tandem --home /实际的数据目录 analysis-history --run-id 运行ID \
  --output .local/saved-analysis.json
```

| API | 功能 |
| --- | --- |
| `GET /v1/analytics/statistics` | 获取完整分布、分组和关联统计，并记录此次分析。 |
| `GET /v1/analytics/lexical` | 获取完整词表、短语、共现、相似性和证据，并记录此次分析。 |
| `POST /v1/analytics/compare` | 提供 `first`、`second` 两个 Scope，比较项目、来源或时间，并保存两边完整结果。 |
| `GET /v1/analytics/runs` | 按分析类型与状态分页查询运行历史。 |
| `GET /v1/analytics/runs/{id}` | 查询一次运行的参数、时间、环境与状态。 |
| `GET /v1/analytics/runs/{id}/result` | 校验并读取完整历史结果。 |
| `GET /v1/analytics/runs/{id}/records?pointer=/lexical/terms` | 分页读取某个结果数组；分页只影响返回，不影响存档。 |

`records` 使用 JSON Pointer，支持 `offset` 和最多 1,000 条的 `limit`；读取历史不会再次运行分析或制造新的分析记录。

## 验证范围

构造测试独立核对词频、消息／会话覆盖、TF-IDF、分位数、标准差、异常值、配对重抽样、常数相关、引文和注入排除，以及不同文本规模下的归一化词频。存储测试覆盖并发执行、完整词表回读、重复运行、不可覆盖、失败记录、损坏快照和字段字典。

本轮还复用了此前已授权导入的真实快照：计算得到 344 个词、480 个短语、746 条共现记录、10 对相似会话和 10 类数值分布，并保存了一次完整分析和一次来源对比。完整结果已逐次读回核验；这些数字描述该快照，不代表全量开发历史或语义准确率。

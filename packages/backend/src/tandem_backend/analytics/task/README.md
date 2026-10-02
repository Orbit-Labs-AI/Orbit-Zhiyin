# task：任务边界与文本表示

- `features.py`：会话内任务分段（`segment_tasks`），只用规则候选与原生任务 ID。
- `representation.py`：本地无监督文本表示，不用标签、不调远程服务。sklearn/scipy 在函数内延迟导入，`import tandem_backend.analytics.service` 不加载它们。

## 文本表示（`representation`）

全量语料上拟合 char 2–4 TF-IDF（`max_features=20000`，sublinear）+ TruncatedSVD（≤32 维，`random_state=0`），用于 DBSCAN 聚类、PCA 坐标和 top terms。坐标只用于可视化，不作时间性结论。

## 时间新颖度（`temporal_novelty`）

`novelty = 1 − max cos(当前会话, 任一严格更早会话)`，裁剪到 [0, 1]。

- 向量：`HashingVectorizer(analyzer="char", ngram_range=(2, 4), n_features=2**20, norm="l2", alternate_sign=False)`。无拟合状态（无 IDF、SVD、词表），因此后加入的会话不会改变更早会话的向量或候选集，天然不泄漏未来数据。
- 只比较时间戳严格更早的会话；同一时间戳互为同侪，不互相计入。无时间戳的会话 `novelty` 为 `null`（`reason="missing_timestamp"`），也不作为别人的更早证据；没有更早会话时为 `null`（`reason="no_earlier_entity"`）。
- 计算：按时间排序后分块（512 行）做稀疏矩阵乘积，只取每行严格更早的前缀列求最大值；向量只算一次，替代原先每个会话各自重新拟合 TF-IDF+SVD（N 次拟合，O(N²)）。

## 版本

`VECTOR_VERSION`：

| 版本 | 变化 |
| --- | --- |
| `char-tfidf-svd-v1` | 新颖度对每个会话用更早前缀重新拟合 TF-IDF+SVD |
| `char-tfidf-svd-v2` | 新颖度改为无拟合的哈希 char 2–4 表示；聚类/坐标/top terms 不变。新颖度数值与 v1 不可直接比较 |

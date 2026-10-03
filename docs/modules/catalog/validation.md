# 推荐目录实测记录

验证日期：2026-10-02；Apple Silicon macOS、Python 3.13、根目录 uv workspace。测试只使用公开资源和构造查询，没有读取本机个人会话。源码入口和复跑命令见[架构与接入文档](architecture.md)。

## 实际构建结果

| 项目 | 结果 |
| --- | ---: |
| 成功同步来源 | 8 个公开来源 + 1 个内置种子来源 |
| active 目录条目 | 53,379 |
| 特征记录 | 218,924 |
| 当前内容分块 | 74,604 |
| 当前模型已索引分块 | 74,604 |
| 待补齐向量 | 0 |
| SQLite / 外键 / FTS / 向量 / 当前版本一致性 | 全部通过 |

公开来源为 Anthropic Skills、Claude 官方插件、OpenAI Plugins、awesome-copilot、官方 MCP Registry、models.dev、LiteLLM 和 SWE-bench。这里的 active 表示来源记录仍在目录中，不表示已经验证效果或可以直接安装。

本地模型为 `intfloat/multilingual-e5-small`，Hub revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`，384 维 ONNX。权重 SHA-256 为 `ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665`。向量空间还绑定分词器、前缀、池化和运行库版本，完整描述保存在数据库中。

数据库与模型保存在本地忽略目录 `.local/catalog/`、`.local/models/`，不进入 Git。分块向量补齐约 583 秒；之后改变来源追溯版本时，重建保留文本哈希对应的向量，没有重新调用模型。

## 运行验证

- 统一 workspace 的根测试：1,114 passed；默认跳过 1 个需本地权重的测试，该测试已另行运行通过。
- `packages/data`：96 passed。
- Connector：typecheck、35 项构造回归、build 通过。
- Swift Package：6 项测试通过，覆盖数据合同、查询编码、HTTP 错误、后台任务和拒绝外部重定向。
- Ruff、data 包格式检查、两个 Python wheel 构建、迁移和字段字典入包、原有 demo / evaluate、diff 检查通过。
- 真实模型集成用例：三条独立英文资源，中文查询分别指向调试、网页无障碍和论文引用检查；Top-1 均正确。该用例验证跨语言通路，不能代表真实目录的总体推荐精度。
- 无模型时，中文“调试”通过显式中英术语展开命中 debugging；结果标记 `not_configured`，不会把词法命中伪装成语义向量或用户画像证据。

## 查询耗时与质量边界

`hybrid-rrf60-mmr80-v2` 在模型已加载后，对 6 条构造查询各重复 3 次，每次允许扫描全部 74,604 个向量：18 次测量的中位数为 **600 ms**，按最近秩计算的 P95 为 **638 ms**。这是本机小样本测量，不是并发压测或性能 SLA。

人工检查中，重复失败查询能找到 Systematic Debugging，无障碍查询能找到 Accessibility Expert。宽泛查询仍可能包含邻近领域的资源，例如“论文引用”会混入 GEO/写作类条目；因此不把这批查询当成生产相关性验收集。当前已验证的是采集一致性、向量覆盖、检索可运行和可解释性；相关性精度需要团队标注的独立任务集，真实改善还需要试用对照。

主干推荐接收层对这些资源保持草稿状态。A7 的问题证据、画像证据和已审查适用条件闸门继续生效，A8 的搜索相关性分数不代表效果概率或改善百分比。

## 产品内语义向量路（2026-10-03，第二轮审计）

### 模型与下载

- 模型：`intfloat/multilingual-e5-small`，revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`，作者在同一提交里发布的 int8 动态量化导出 `onnx/model_qint8_avx512_vnni.onnx`（118,346,824 B，SHA-256 `dd476dd0…2d88`）+ `onnx/tokenizer.json`（17,082,730 B，SHA-256 `0b44a9d7…4c39`）。下载合计 135,429,554 B，磁盘 130 MB。fp32 原版为 470 MB；Xenova 的 `model_int8.onnx` 体积相同（118 MB），因此选模型作者仓库里的版本。
- 下载只在用户同意后进行（`PUT /v1/catalog/embeddings/model {"allow_download": true}`、`ORBIT_CATALOG_MODEL_DOWNLOAD=1` 或 `python -m orbit_catalog model-download --allow`）。文件先写成 `.part`，中断后用 HTTP Range 续传；大小和 SHA-256 都与固定值一致，才移动到正式位置并写 `manifest.json`。本机实测一次完整下载 **66 s**（约 2 MB/s）。
- 自动发现顺序：`<catalog home>/models`、`$ORBIT_HOME/models`、`~/Library/Application Support/Orbit/models`，目录名均为 `multilingual-e5-small`。
- int8 和 fp32 一致性：在种子库的 96 个分块上（平均 513 字符），两版向量逐块余弦的平均值为 **0.9985**，最小值为 **0.9928**。Apple M 系列 CPU 没有 VNNI，int8 速度和 fp32 相当（4 线程下分别为 24.0 / 22.9 ms/块，8 线程下分别为 20.1 / 16.6 ms/块，测试时机器上同时跑着其他任务）。所以选 int8 只是为了下载体积，不是为了速度。

### 种子库嵌入

`seed-import` 后的种子库共有 1,312 个条目、7,879 个分块，其中 2,875 个是需要嵌入的分块（每个条目取概览块加前 3 块）。`python -m orbit_catalog embed` 一次跑完：

| 项目 | 值 |
| --- | --- |
| 编码 / 文本哈希复用 | 2,744 / 82 |
| 耗时 | 245 s（墙钟；同机另有 2 个并行测试/同步任务，平均约 89 ms/块） |
| 进程峰值 RSS | 1.17 GB（ONNX Runtime 会话 + 8 窗口批次） |
| 覆盖率 | 2,875 / 2,875（`vector.status = ready`） |
| 模型加载 | 0.51 s（含对两个文件做 SHA-256） |

网关首次联网同步结束后，后台每次处理 512 个分块（`EMBED_SLICE`），按上面的速度一次约 10–45 s。可以取消；已提交的批次会保留，下次从剩下的分块接着做。进度见 `/v1/catalog/status` 的 `vector.coverage`。

### 检索规模评估（精确余弦，不用 ANN）

用 75,000 × 384 维的随机单位向量（fp16）测试，与真实全量同步的 74,604 个分块同一量级：

| 项目 | 值 |
| --- | --- |
| 从 SQLite 读取矩阵（JOIN + frombuffer，每个 generation 一次，缓存在 CatalogIndex） | 471 ms；常驻 57.6 MB，加载峰值 182.5 MB |
| `blocked_scores`（fp16 分块转 fp32） | 中位数 3.1 ms，P95 5.0 ms |
| fp32 常驻矩阵 | 中位数 1.0 ms（多占 115 MB，不值得） |
| fp16 与 fp32 的余弦误差 | 最大 4.5e-5 |

结论：5 万条目、7.5 万分块的规模下，精确余弦只要几毫秒，不需要 ANN 或分块预筛。矩阵本来就按 generation 缓存。本轮把 `index_embeddings` 改成每次调用只前移一次 generation（原来每 64 块一次），后台嵌入时就不会每批都触发整库索引和矩阵重建。种子库上一次融合查询（含查询编码）耗时 4–41 ms。

### 余弦分布与语义路阈值

对下面 6 个查询，按条目取各分块余弦的最大值。条目名称或 ID 匹配人工正则的算“相关”，其余算“不相关”（不相关组里会混入少量正则没覆盖到的相关条目，所以下面的分离度是偏保守的估计）：

| 查询 | 相关 n | 相关 P5/P50/P95 | 不相关 P5/P50/P95 |
| --- | --- | --- | --- |
| 调试测试反复失败 | 25 | 0.786 / 0.809 / 0.888 | 0.752 / 0.788 / 0.833 |
| postgres database | 28 | 0.819 / 0.852 / 0.888 | 0.768 / 0.795 / 0.819 |
| pdf docx | 22 | 0.807 / 0.830 / 0.853 | 0.774 / 0.799 / 0.829 |
| 代码审查 | 43 | 0.809 / 0.837 / 0.858 | 0.777 / 0.804 / 0.833 |
| 浏览器自动化测试 | 6 | 0.810 / 0.834 / 0.845 | 0.767 / 0.800 / 0.835 |
| deploy to kubernetes | 4 | 0.863 / 0.872 / 0.878 | 0.786 / 0.818 / 0.843 |

所有条目的余弦都为正（最小 0.719）。把 6 个查询合并后，相关组共 128 个，中位数 0.833；不相关组共 7,744 个，中位数 0.801；AUC 为 0.857。现在的绝对门槛是 `SEMANTIC_FLOOR = 0.7` 加 `MIN_TEXT_RELEVANCE = 0.2`，等效余弦约 0.76，会保留 **97.4%** 的不相关条目，实际上没有起到阈值作用。换成绝对阈值 0.84，只能保留 39.8% 的相关条目，同时仍保留 3.0% 的不相关条目。

如果按每个查询自己的分数分布做 z 标准化，(cos − 中位数) / 标准差（同一查询下所有分块中位数为 0.783–0.810，标准差为 0.016–0.026），分离更好：AUC 0.891。取 z ≥ 1.5 时保留 69.5% 的相关条目和 10.6% 的不相关条目；取 z ≥ 2 时分别是 52.3% 和 4.3%。该门槛已在 `search.semantic_gate` 实现（`hybrid-bm25f-zsem-mmr80-v6`）。本机没有模型时，用 `uv run python -m evals.recommendation.semantic_gate` 在按上表分位数构造的余弦总体上对比：绝对门槛保留相关 98.4%、无关 97.1%（AUC 0.849）；按查询 z ≥ 1.5 保留相关 64.1%、无关 5.9%（AUC 0.889），换 3 个随机种子结果一致（无关 5.5–5.7%）。真实模型上的复测待有模型时补做。

### 6 个查询的前 5 名（种子库，int8 E5）

括号里依次是类型和分数。词法、融合列是 0–1 的绝对相关度，语义列是原始余弦。

**调试测试反复失败**（融合 34.1 ms）

| # | 词法 | 语义（余弦） | 融合 |
| --- | --- | --- | --- |
| 1 | 重复失败熔断：同一命令失败 2 次先诊断（hook，0.327） | 重复失败熔断：同一命令失败 2 次先诊断（hook，0.902） | 重复失败熔断：同一命令失败 2 次先诊断（hook，0.753） |
| 2 | — | AGENTS.md：写明所用软件的环境约定（rule，0.898） | AGENTS.md：写明所用软件的环境约定（rule，0.686） |
| 3 | — | 系统化排错 Skill：复现→假设→最小修复（skill，0.892） | 系统化排错 Skill：复现→假设→最小修复（skill，0.666） |
| 4 | — | 纠偏两次后：清空上下文并重述需求（workflow，0.892） | 纠偏两次后：清空上下文并重述需求（workflow，0.639） |
| 5 | — | 完成前自检清单（rule，0.89） | 停用长期未用的组件（guide，0.614） |

**postgres database**（融合 5.0 ms）

| # | 词法 | 语义（余弦） | 融合 |
| --- | --- | --- | --- |
| 1 | supabase-postgres-best-practices（skill，0.335） | postgres（plugin，0.894） | supabase-postgres-best-practices（skill，0.751） |
| 2 | postgres（plugin，0.334） | cloud-sql-postgresql（plugin，0.888） | postgres（plugin，0.72） |
| 3 | database-cloud-optimization-database-architect（subagent，0.304） | supabase-postgres-best-practices（skill，0.888） | database-migrations-database-optimizer（subagent，0.691） |
| 4 | render-deploy（skill，0.282） | alloydb（plugin，0.887） | supabase（plugin，0.695） |
| 5 | azure-naming.instructions（rule，0.223） | cloud-sql-postgresql-observability（plugin，0.882） | cloud-sql-postgresql（plugin，0.665） |

**pdf docx**（融合 4.3 ms）

| # | 词法 | 语义（余弦） | 融合 |
| --- | --- | --- | --- |
| 1 | docx（skill，0.313） | omniverse-realtime-viewer（skill，0.859） | docx（skill，0.639） |
| 2 | Safe Docx（mcp_server，0.28） | omniverse-usd-performance-tuning（skill，0.859） | Safe Docx（mcp_server，0.616） |
| 3 | adobe-create-social-variations（skill，0.309） | xlsx（skill，0.855） | pdf（skill，0.633） |
| 4 | claude-automation-recommender（skill，0.269） | Safe Docx（mcp_server，0.855） | report-to-pdf（skill，0.594） |
| 5 | pdf（skill，0.25） | docx（skill，0.853） | file-conversion（plugin，0.544） |

**代码审查**（融合 40.6 ms）

| # | 词法 | 语义（余弦） | 融合 |
| --- | --- | --- | --- |
| 1 | PR review 最多两轮，只修 P0 / P1（skill，0.391） | 只读审查交给只读子代理（subagent，0.89） | 只读审查交给只读子代理（subagent，0.76） |
| 2 | gh-address-comments（skill，0.378） | Codex 只读任务改用 medium 推理档（guide，0.886） | PR review 最多两轮，只修 P0 / P1（skill，0.724） |
| 3 | project-artifact（skill，0.364） | Doc Co-Authoring（skill，0.875） | 只读命令自动放行（hook，0.635） |
| 4 | 只读审查交给只读子代理（subagent，0.348） | 完成前自检清单（rule，0.871） | code-review（command，0.573） |
| 5 | commit-push-pr（command，0.294） | Humanizer（skill，0.868） | Codex 只读任务改用 medium 推理档（guide，0.599） |

**浏览器自动化测试**（融合 16.6 ms）

| # | 词法 | 语义（余弦） | 融合 |
| --- | --- | --- | --- |
| 1 | webapp-testing（skill，0.286） | Stop hook：没有验证结果不结束（hook，0.871） | codebase-cleanup-test-automator（subagent，0.645） |
| 2 | codebase-cleanup-test-automator（subagent，0.279） | 编辑后自动运行构建命令（hook，0.867） | webapp-testing（skill，0.592） |
| 3 | claude-automation-recommender（skill，0.262） | 长任务改成无人值守的定时检查（workflow，0.866） | 验证阶梯：编译→单测→端到端（workflow，0.592） |
| 4 | playwright（skill，0.224） | 验证阶梯：编译→单测→端到端（workflow，0.862） | playwright（mcp_server，0.556） |
| 5 | io.github.achiya-automation/safari-mcp（mcp_server，0.173） | 完成前自检清单（rule，0.862） | 完成前自检清单（rule，0.591） |

**deploy to kubernetes**（融合 8.0 ms）

| # | 词法 | 语义（余弦） | 融合 |
| --- | --- | --- | --- |
| 1 | kubernetes-manifests.instructions（rule，0.301） | cloud-infrastructure-deployment-engineer（subagent，0.883） | cloud-infrastructure-deployment-engineer（subagent，0.691） |
| 2 | physical-ai-infrastructure-setup-and-resilient-scaling（skill，0.283） | deployment-strategies-deployment-engineer（subagent，0.881） | kubernetes-manifests.instructions（rule，0.679） |
| 3 | cicd-automation-deployment-engineer（subagent，0.206） | cloud-infrastructure-kubernetes-architect（subagent，0.879） | physical-ai-infrastructure-setup-and-resilient-scaling（skill，0.666） |
| 4 | aiq-deploy（skill，0.252） | service-mesh-expert（subagent，0.877） | kubernetes-operations（plugin，0.661） |
| 5 | cloud-infrastructure-deployment-engineer（subagent，0.206） | distributed-debugging-devops-troubleshooter（subagent，0.876） | cloudflare-deploy（skill，0.639） |
观察：

1. 英文查询的语义路能补上词法漏掉的同类条目，例如 postgres → cloud-sql-postgresql、alloydb；kubernetes → kubernetes-architect。
2. 中文查询的语义路明显偏向中文 KB 条目：“浏览器自动化测试”的语义前 5 名全是中文验证类条目，没有 playwright 或 webapp-testing。融合结果仍由词法（中英展开）把它们拉了回来。
3. “pdf docx”在语义路上把 omniverse 排在第 1（0.859），说明短查询在这个模型上的余弦区分度很低。

这些结果说明语义路只能作为补充召回，不能单独作为推荐依据。

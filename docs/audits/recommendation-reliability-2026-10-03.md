# 推荐与资源库可靠性审计（2026-10-03）

> 文档状态：审计快照。正文保留原基线、日期与证据；其中的状态和数字不代表当前版本。现行入口见[文档导航](../README.md)。


本轮以构造会话、固定公共来源快照和独立临时 catalog.db 核查推荐链路，没有读取真实用户会话，也没有向模型发送真实用户内容。结果是可回归的接口与容错修复、可追溯的资源扩容，以及受既有 AI 同意开关控制的小预算建议入口；不构成推荐效果、节省时间或模型质量的实测结论。

## 实际入口与排序

App 使用 `recommend/runs.py → engine.build_slate → recall.multi → ranking/gates → ranking/rank → ranking/slate → narrate`。`/v1/analytics/recommendations` 的 legacy/service 路径另存，不能把它的输出当作 App 新推荐引擎结果。

`recall.multi` 当前 11 路为：

| 路 | 实际来源与边界 |
|---|---|
| kb | 问题证据匹配人工维护的知识库规则 |
| catalog | 公共目录的关键词、特征、remedy 和可选本地向量结果；没有目录时退回随包种子 |
| feature | 画像与资源特征的交集 |
| profile | 有足够会话证据的画像文本查询，单列资料库推荐 |
| hashed_lexical | 哈希词法相似，不是神经语义向量；目录向量 ready 时已有逻辑会跳过 |
| subtract | 已装配置的减法建议 |
| template | 可由模板实例化的方案 |
| model | 模型与推理设置建议 |
| graph | 已知组件的互补关系 |
| generative | 生成工坊任务占位，当前召回映射 rule/hook/skill |
| generic | 少于 10 个主会话时的通用冷启动建议 |

各路分数先经加权 RRF（`k=60`）合并，最多 200 个候选。权重属于尚未拟合的产品设置。进入卡片前仍检查问题/画像证据、来源、兼容、许可、已安装、静音等条件，并排除非正收益或非正效用。排序使用 `value=(benefit×confidence×p_effective×fit)^(1/4)`，扣除成本与风险，再应用个人偏好和曝光衰减。这里的收益/先验/优先级是启发式排序指标，不是实测节省分钟或成功概率。

展示层使用 MMR、问题/类别/来源家族配额、同需求同维度折叠，以及最多 3 张资料库卡。资源库自身检索包含特征、BM25F、人工整理的 remedy 和可选 E5 精确余弦；各路相关度参与融合和 MMR。没有本地模型时明确标为 `not_configured`，不会冒充向量检索。

## 已修复的问题

1. **检索结果丢失来源验证与兼容声明。** `catalog.search` 之前没有返回 `verification`、`language`、声明的 `agent_support`，而推荐端依赖这些字段。本轮贯通字段；没有声明的 agent 列表仍仅表示列出兼容提示，不自动升级为 native。
2. **特征路漏掉风险。** `feature_route` 错从资源 metadata 取风险，实际权威列在 `catalog_item.risk/risk_level`。现在读取权威列，保留高风险等级，避免危险条目被当低风险。
3. **向量编码失败会失去独立检索结果。** 之前只处理模型加载异常，编码或批量预热异常仍可能使整个请求失败。现在单条与批量查询都回退到 BM25/特征检索，并返回明确的 semantic degraded 与 vector unavailable。
4. **公开来源分类过宽。** Microsoft 官方仓库实际同步在 `docs-site/src/data/hooks.json` 上触发 `manifest_not_object`。现在 Hook 的默认文件规则只识别根 `hooks.json` 或 hooks 目录中的 `hooks.json` / `*-hooks.json`；网站数据、依赖清单不会成为资源。确实被识别但格式损坏的清单仍报错。
5. **AI 精排异常和顺序不规范。** 额外异常不再阻断确定性推荐保存；输出只接受原候选 ID、去重并补回漏项，不更改原始 priority/rank。AI 失败保留原顺序与诊断。
6. **推荐设置变更未充分进入缓存。** 之前只把 ai_generate 编入摘要；level 改变可能继续复用旧 run。现在把有效推荐设置一起纳入摘要。
7. **App 没有模型目录接线。** gateway 创建 CatalogService 时不传 model_dir，导致已下载的权重无法通过正常 App 路径启用。本轮增加显式可选的 `ORBIT_CATALOG_MODEL_DIR` 环境变量，构造参数优先；只读本地权重、懒加载，缺文件或可选运行时仍降级，不自动下载。
8. **旧安装不会收到新版离线种子。** 之前只在完全没有种子时导入。本轮按来源 revision 比较，仅导入新增或更新来源；已完成网络同步的来源仍优先，未变来源不会重复发布。特征/分块版本变更在 bootstrap 时一次重建投影，避免旧库与新算法混用。

## 内容、预处理与质量分类

新增可信来源是 [Microsoft 官方 skills 仓库](https://github.com/microsoft/skills)，通过现有 GitHub connector 读取固定树、正文许可和源 blob。实际同步 revision 为 [`ce7edea90860e0c69fa36db164584c87908e09f5`](https://github.com/microsoft/skills/tree/ce7edea90860e0c69fa36db164584c87908e09f5)。同步库形成 275 项，快照经过现有去重与可列出筛选纳入 266 项，没有手工捏造热度、质量评测或有效性数据。

离线 `library-seed.v1.json.gz` 从 **1,277 项增加到 1,543 项**，压缩后 **1,850,805 字节**。新增来源固定版本可在每个资源 URL、commit_sha 与来源记录中追溯；没有安装抓取到的内容。

| 种类 | 原种子 | 本轮种子 |
|---|---:|---:|
| Skill | 400 | 604 |
| Hook | 40 | 56 |
| MCP server | 300 | 305 |
| Plugin | 250 | 263 |
| Command / Prompt | 60 | 78 |
| Rule | 60 | 60 |
| Subagent | 150 | 159 |
| Workflow | 17 | 18 |
| 合计 | 1,277 | 1,543 |

在隔离空库导入离线来源与新版种子后，实测总资源 **1,578 项**、可列出且 canonical 的 active 资源 **1,577 项**、词法分块 **12,848**、特征投影 **12,360**。向量编码目标块 **3,876**；本轮已在隔离本地库完成 **3,685 条唯一向量**，覆盖全部 **3,876 块**，`pending=0`、`status=ready`（正文重复按文本哈希复用向量）。总数还包括随包 Orbit KB / reviewed seeds，不能与单一种子的 1,543 混为一谈。

`features-4` 新增任务阶段（计划、实现、验证、审查、发布）、产物形式（表格、演示稿、文档、图解、Notebook）、实践（测试驱动、证据优先、小步变更）。这些全部标记为文本抽取 `extracted`，有词面证据和权重，不自动视为审核后的 remedy。

`quality` 输出使用 `catalog-quality-v1`：已读取来源、许可声明、正文可用、兼容列表、源版本记录五项等权元数据维度，并返回缺失项。0.8 以上为 documented，0.4 以上为 partial，其余 sparse；阈值是显式产品规则。官方身份单独报告，`effect_status=unmeasured`、`security_status=not_audited` 始终保留。该分数不是效果评测或安全审计；官方身份、GitHub 星数和完整正文都不能证明推荐有效。

新语料使关键词文档频率与 MMR 顺序发生正常变化。构造/固定语料回归保留通用查询应无结果的约束（补充 best/tool/tools 为查询填充词）。中文“容器”新增官方 Infrastructure Engineer 作为合格目标，其原文包含 Docker/容器实践，没有改成接受任意命中。

## 小预算 AI 建议与召回

在既有 AI 同意设置允许且 `recommend.ai_generate=true` 时，推荐 run 最多执行一次 `recommend.expert`，再沿用一次 `rerank.fit`。专家任务由共用 AI TaskSpec/pack/runner/校验/回退路径运行，使用 cheap 模型槽，最多 6 个活跃问题、10 个候选摘要，不自行读取会话或新增外部模型适配器。cheap 槽遵循用户配置；目前没有额外强制低 thinking 的通用 CLI 参数，不宣称强制改变所有 provider 的思考档位。

专家输出最多 3 条 skill/hook/prompt/workflow 建议和 3 个短查询。每条建议必须引用自身输入 problem_id，挂在对应卡的 `expert_advice` 中，并明确 `draft=true`、`effect_status=unmeasured`；找不到可挂卡时保留到诊断。建议不是安装文件。

每个 AI 查询重新调用现有目录，候选必须具有对应问题的 **curated friction**，再经过原有确定性 gates/rank；最多添加 2 张，使用空余卡位并维持问题、维度、类别、家族和标题去重限制，不挤掉原有证据卡。没有合格资源时可返回零条，不把相似度或 AI 猜测升级为有效性证据。

现有真实生成任务包括 `generate.rule`、`generate.glue`、`generate.hook`、`generate.skill`、`generate.subagent`、`generate.command`。UI 可将建议转交生成工坊，其中 workflow 对应 `generate.glue`，当前工坊没有单独 command 选项，prompt 建议映射为 `generate.rule`；后续仍按原有预览、校验与安装流程处理，不因专家建议而自动安装。

## 验证与限制

作用目录 ruff 检查通过。测试使用构造数据：源清单识别、五维质量、额外特征的 extracted 属性、编码失败降级、字段贯通、种子升级与投影版本升级；推荐测试覆盖风险保留、AI 异常、未知/重复精排 ID、专家证据绑定、3 查询预算、curated 门控和设置缓存失效。

本轮曾运行 catalog 全套加推荐相关选集，初轮 315 passed、4 failed、1 skipped；4 个失败均已逐项处理，受影响的 95 项、设置与升级回归 39 项、专家回归 5 项随后通过。完整仓库检查由集成任务统一运行，避免多个 agent 重复执行。共享环境的可选 E5 pytest 初轮因未提供模型目录而跳过；其后本轮用独立环境真实运行 E5，执行下节的完整物化和六条中英构造验证。ToyEncoder 本身只验证向量路语义与降级机制，不代表真实模型召回精度。新增 App 模型目录路径、显式优先级和缺文件降级后，`test_audit_quality.py` 的 9 项通过，Ruff 通过。

## 实际向量库物化与本地查询

按照明确授权，使用 Hugging Face CLI 从原作者 [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3/onnx) 下载固定 revision `614241f622f53c4eeff9890bdc4f31cfecc418b3` 的 `onnx/model.onnx`、`onnx/tokenizer.json`、`onnx/config.json` 和模型卡；其声明许可为 MIT。`hf cache verify` 已校验这 4 个文件，其余权重变体有意不下载。

| 内容 | SHA256 / 版本 |
|---|---|
| ONNX 模型（470,268,510 B） | `ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665` |
| Tokenizer（17,082,730 B） | `0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39` |
| 模型空间 ID | `e5:48cb79be690d33d30f830bfe84225b174686241c30cd99d06115e2d0b392d073` |
| 运行时 | ONNX Runtime 1.30.0、tokenizers 0.23.2、NumPy 2.5.3、huggingface-hub 1.33.0 |

可选依赖安装在忽略目录 `.local/audit-20261003/runtime`；只读复用项目已有 Python 包，未修改共享 `.venv` 或锁文件。`LocalE5Encoder(threads=2)` 使用 CPU provider，关闭 tokenizer 并行；每批 32 块，沿用 `index_embeddings`。模型输出 384 维，masked mean/window mean/L2 归一化，数据库按文本哈希缓存 fp16 向量。

- 模型目录：`.local/audit-20261003/models/multilingual-e5-small/`。
- 已物化目录库：`.local/audit-20261003/vector-catalog/catalog.db`。
- 实际结果：**3,685 条唯一向量 / 3,876 个覆盖块 / 0 个待编码块**，状态 ready；物化阶段约 **88.19 秒**。
- `CatalogStore.verify()`：ok，invalid_vectors、missing_fts、invalid_versions、invalid_blobs 等错误计数均为 0。
- 完整结果及分路分数：`.local/audit-20261003/vector-materialization.json`；运行脚本：同目录 `materialize_vectors.py`。均为公共资源和构造查询，没有真实会话数据。

大目录 6 条中英文查询全部 `vector.status=ready`，覆盖检查均为 `indexed_chunks=eligible_chunks=3876`，semantic 路各返回 100 个候选。本机已加载模型后的单次检索约 116–267 ms，仅为这次本地 smoke 的观测值，不是 SLA。

| 构造查询 | 实际前两项 |
|---|---|
| 排查自动化测试反复失败的原因 | 重复失败熔断、Systematic Debugging |
| 核对论文中的引用是否真实 | 中文表达润色 Skill、zotero |
| 避免运行命令时破坏文件并在失败后停止重试 | 重复失败熔断、PR review 最多两轮 |
| A repeatable process for debugging failed tests and finding the root cause | debugging-toolkit-debugger、systematic-debugging |
| Create a spreadsheet and validate formulas | google-sheets、xlsx |
| Review a pull request for security vulnerabilities | PR Quality Signal Review、security-diff-scan |

另建仅含“测试调试、网页无障碍、论文引用”三篇构造文档的库，六条中英文查询全部 top-1 命中预期，并且 semantic 路 rank-1，作为真实模型跨语言接线验证。这个微型集合没有足够规模证明真实推荐精度；大目录“论文引用”首项偏宽的结果已如实保留，没有为了六条样例调权或宣称全面达标。

App/gateway 启动前可设置 `ORBIT_CATALOG_MODEL_DIR` 为上述模型目录的**绝对路径**；显式传给 CatalogService 的 `model_dir` 或 CLI `--model-dir` 优先。运行 gateway 的 Python 也须装有 embeddings 可选依赖；本轮仅隔离运行时具备这些依赖，不暗中改动用户默认环境。环境变量不改变目录数据库位置：正常 App 仍使用其 `home/catalog.db`，本次物化的校验库也不会自动覆盖用户库。对选定 home 显式运行 `orbit-catalog --home <选定目录> --model-dir <模型绝对路径> embed` 后，才具备该目录的向量索引；只配置模型但未编码时会明确报告 not_indexed。

既有 E5 路仍是本地 fp16 分块精确余弦、每资源概览加前 3 个正文块，不是 ANN；长文后部语义覆盖仍受这个上限约束。专家和精排仍只通过合成输入验证，真实生成模型质量尚未评估。排序权重、先验、质量阈值和抽取词表仍需后续独立标注数据评估，不能把链路通过或六条构造命中解释为真实用户收益。

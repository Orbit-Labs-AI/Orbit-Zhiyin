# 非 Skill 资源扩容与正文暂停记录：2026-10-04

状态：全部新来源已导入；278,870 条概览向量全部覆盖；正文编码按用户要求暂停。本文区分目录条目、完整实现、来源声明与实际运行验证，不以下载数代替活动库计数。

## 正文暂停与续跑

已中断本轮全文 CLI 监督进程，确认四个 worker 全部退出，并暂停 `Orbit 全文向量化检查` 自动任务。SQLite 已提交结果保留，未清空或重建库。暂停时的 SQL 断点为：

- 活动资源 180,367；概览已覆盖 180,367。
- 正文块已覆盖 **627,446 / 3,010,717**；全部块已覆盖 **808,064 / 3,191,990**。
- 模型 `e5:48cb79be690d33d30f830bfe84225b174686241c30cd99d06115e2d0b392d073`，唯一向量 **476,017**。
- 记录位于本地 `.local/catalog-100k/body-pause-checkpoint-20261004.json`，`PAUSED_BY_USER` 明确要求用户再次指示后才恢复正文。自动检查状态为 `PAUSED`。

扩库之后的正文总量会增长。本轮仅运行 `embed --scope overview --workers 4 --threads 2 --batch-size 128 --progress` 补新条目的概览，不恢复 `--scope all`。将来用户要求继续时沿用原模型和全文参数；已提交相同文本向量按哈希复用。

## 实际入库数量

以下为全部来源完成后的 SQL 活动资源计数：

| 类型 | 本轮前 | 本轮后 | 倍数 | 十倍目标 |
|---|---:|---:|---:|---|
| MCP server | 38,445 | **100,701** | **2.62×** | 未达 384,450 |
| Plugin | 264 | **3,551** | **13.45×** | 已达 |
| Hook 条目 | 100 | **1,157** | **11.57×** | 已达 |
| Prompt / command | 2,243 | **25,606** | **11.42×** | 含下述生成参考层后已达 |
| Workflow | 338 | **8,878** | **26.27×** | 已达 |

库内另有 Skill **138,745** 条，以及 rule / subagent / guide / benchmark **232** 条；总计 **278,870** 条，比原库新增 **98,503** 条。正文投影 **3,342,220** 块，活动条目长度截断数 **0**。不把分块、tool、版本和镜像分别算作资源。

## 来源与质量层次

### MCP

使用 [MCPfinder 的官方快照入口](https://mcpfinder.dev/api/v1/snapshot/manifest.json)，固定 2026-10-03T11:54:54Z 的 116,575 行 SQLite 快照。其原始压缩文件 SHA256 为 `86c970ba603f2f9ae155c21de1c853356f3b5cfc40802a84a781f7eae8b24fd5`；来源包括 Official Registry、Glama 和 Smithery。先按已有官方 ID、仓库、真实 endpoint、包名与重复说明去重，再与现库交叉比较。

最终新增 **62,256** 条。**14,731** 条缺少独立身份的 listing 单独留存为发现候选，不进入 server 总数。GitHub 按字母顺序核查了 5,100 个仓库，发现 393 个不可访问且无其他 endpoint 的记录，另合并 5 个改名别名；这些 398 条通过同一个 source 的完整重扫撤回，不另建平行来源。保留 fork 与 archived 的事实标记，不把它们自动等同于无效。

新增记录中 **57,554** 条仍只有 registry 的仓库或 endpoint 声明，没有验证源仓库存活；其余 4,702 条保留本次直接访问证据。抽查顺序不是随机样本，不能把比例外推为全生态可用率。新增部分没有可用工具 schema；属于旧官方条目的工具说明没有被拆成“新 server”。本轮没有足够证据支撑 38.4 万个独立 server，缺口保持明确。

### Plugins

完整扫描 [pluginsmp 公开 API](https://pluginsmp.com/docs) 的 241 页、12,033 条发现记录，再回到原 GitHub 仓库取 manifest。收集到 3,412 份原件，扣除现库的 125 个身份重叠后新增 **3,287**。其中完整收集语料的 3,301 份来自固定 commit 归档，111 份来自带时间、哈希的 GitHub 原文件快照。

排除测试夹具、vendor / examples 等路径，去掉 1,177 份明确镜像和 1,255 份内容、提交或协议变体重复。计入的是读到的 plugin manifest，不是已运行测试的插件包；相邻资源的依赖闭包与实际兼容性尚未逐项验证。

### Hooks 与 workflows

- Hook：扫描 448 个仓库完整快照，161 个仓库提供符合筛选条件的实现；按主实现代码、镜像和适配组合去重，新增 **1,057** 条。包含 **986 个未运行验证的实现、71 个教程或示例实现**，均保存 artifact 层次及出处。另有 239 个配置参考、84 个 SkillMD recipe 候选未计入。原库的 100 条仍含配置事件参考，因此不能把合计 1,157 宣称为同数量的成熟即用工具。
- Workflow：来自 [ScraperNode 固定快照](https://github.com/ScraperNode/awesome-n8n-templates/tree/d50bcb23f189aedb10315a3f119a40c3f61194f4)，8,697 个 n8n JSON 中剔除 116 个结构不合格文件、41 个归一图重复，新增 **8,540**。提取节点类型、触发器、集成、凭据类型与类别；仅验证静态节点和连线，未执行工作流或连接外部服务。

### Prompts 与提示优化

作者及开发者来源新增 **13,369** 条：

| 来源 | 新增候选 | 类型与证据 |
|---|---:|---|
| [PromptSource](https://github.com/bigscience-workshop/promptsource/tree/7dab96a3eeb3717cea633705135ebc488885d709) | 1,475 | 数据任务模板，保留 Jinja 变量、任务元数据与输出表达式 |
| [Fabric](https://github.com/danielmiessler/fabric/tree/ddf1aab968caa9adf90137a6536c768d02b237d6) | 265 | system patterns 与提示优化策略 |
| [Rosehill](https://huggingface.co/datasets/danielrosehill/System-Prompt-Library-030825/tree/6f969b7ce748f63e7201e8045aabbaf522a439d8) | 921 | 作者发布的系统提示；许可声明冲突，保留待核实状态 |
| [PromptSet](https://huggingface.co/datasets/pisterlabs/promptset/tree/a5aa6e9017caf34e44386a64e8b3523c6b67b215) | 10,708 | 从公开程序抽取的参数化、系统与短模板 |

PromptSet 遍历全部 93,142 文件行、118,862 抽取字符串；去除孤立变量、未解析 PLACEHOLDER、普通一次性问题、序列化容器及 literal 包装，按正文与近重复进一步合并。保留有明确任务和命名变量的短模板。分块正文之外，记录 `prompt_type`、`input_variable`、结构化输出、约束、验证、反馈改进及工具使用等特征；这些是文本或来源声明证据，不是效果实验。

另外，从公开 [echohive42 角色模板库](https://github.com/echohive42/10-000-chatbot-prompts/tree/38344b5b252e57d59ee5df776502cd2a82bac46b) 新增 **9,994** 条生成参考模板。原文完整，按分类及正文去重，明确标注 `generated_role_template`、source-declared AI-generated、effect_unmeasured 与 not_expert_verified，独立来源优先级 25，不把它们称为人工或专家验证内容。其占最终 prompt 库 **39.03%**。排除这层时 prompt 总量为 **15,612（6.96×）**；十倍目标是计入该参考层后达成。优先级用于来源合并，不代表已实现独立的生成内容排序惩罚。

所有来源都可追溯，但没有逐条运行或用户收益验证。对于非原始内容许可已核实的资源，使用本地 `index_only`；原始 manifest、完整内容、revision、摘要、去重和失败日志保留在本地忽略目录，不随代码或种子发布。

## 导入支持与验证

BulkConnector 新增 plugin 类型，保留 HTTPS 原始链接、upstream ID、provenance、artifact_kind、manifest、agents 与来源特征。收集来源的特征不能把自己标为 curated 或提高默认权重；非 Skill 不再默认兼容所有 Skill agent。manifest / provenance / 特征条数都有明确边界，错误会显式失败。

复核发现 PromptSource 与 Fabric 的 1,740 条有明确许可模板，详情曾忽略 `metadata.installable=False` 而返回可安装，实际后端却只能链接来源。现优先尊重该禁用声明，允许按许可展示正文，同时准确返回不可安装；原有合法安装行为保持不变。

Catalog 包最终检查 **366 passed、2 个可选 E5 测试 skipped**；导入边界初次定向 26 项、安装展示修复定向 47 项通过。新增的13条测试锁住本轮安装展示问题，没有重复不受影响的全仓测试。运行库完整性核验通过 SQLite quick_check、外键、版本、canonical、FTS 对应关系、向量维度与 blob 存在性；压缩 blob 摘要按既有实现抽查 200 条，不能表述为逐条解压验证所有 blob。

新增概览已完成：`scope=overview`、`status=ready`、`missing_overview_items=0`，**278,870 / 278,870** 条资源均覆盖。当前唯一向量 **574,402**，本轮编码输出 98,385 次。正文覆盖为 **628,344 / 3,342,220**；相同文本可直接复用概览新向量，因此它略高于暂停断点，未运行正文任务。全部块覆盖 **907,474 / 3,642,743**，待覆盖 **2,735,269**。检索仍应显示全块向量 `partial`，不能把概览 `ready` 当作全文完成。

代表性验收使用五类新来源各两组中英文查询，显式按来源及类型过滤，并提供一个相关结构特征；10 组均返回 5 条结果，关键词、特征与语义路均返回候选，没有发生降级。这是查询链路 smoke，不是有人工标注的 precision/recall 测试，不能证明十倍增长带来多少召回收益。首次读取大索引约 11.8 秒，后续示例查询约 0.12–1.42 秒；正文仍暂停，查询使用已有正文与完整概览向量。

本地操作记录在 `.local/catalog-expansion-20261004/`：`baseline.json`、各来源冻结文件与 `source-specs`、逐来源导入进度、`import-audit.json`、`integrity.json`、概览向量结果及检索验收报告。暂停断点仍单独保存在 `.local/catalog-100k/`。

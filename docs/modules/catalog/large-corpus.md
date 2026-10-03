# 十万级公共资源索引

状态：实现与运行约定；维护者 `yhyfhgs`；2026-10-03。全文物化的最终实测结果以本轮审计及本地覆盖率报告为准，不能从下载成功推断向量已经生成。

## 资源与向量的计数

分别记录输入行数、不同内容 SHA-256、不同来源路径、active/canonical 资源数、正文块数、可编码块数、拥有向量的资源数、已编码正文块和唯一向量数。不同资源可能复用相同文本向量；同一资源可以有多个向量。任何一方不能冒充另一方的规模。

本轮主源为 [SkillMD-138K 固定快照](https://huggingface.co/datasets/FayeZC/SkillMD-138K/tree/0d73048abf2fb6ee91f6f9f5ac598d5be8d6bdd7)，包含 138,133 个不同正文 SHA-256、20,556 个仓库。另采集 [MCP 官方目录](https://registry.modelcontextprotocol.io/docs)、[固定版本 Prompts](https://github.com/f/prompts.chat/tree/7d3f248962d1dca209d59e033524bcb86c2b26b8)与 [Copilot Hooks / Workflows](https://github.com/github/awesome-copilot/tree/143a3d976b3c1603cc8932984d5e1f28501cb5fc)。下载的资源不执行，也不自动安装。

数据集 CC-BY-4.0 仅适用于汇编与元数据，原 Skill 保留各自来源许可。`index_only` 正文留在本地用于 FTS 和向量检索，UI/legacy detail 不返回整段正文，发布用种子也排除这些条目。只有独立核实原始内容许可的来源才声明 `licensed`；资源数量和元数据完整度不代表已审核或有效。

## 可复跑导入

使用 Hugging Face CLI 固定 revision 下载原始 Parquet，然后显式转换为 JSONL。转换器仅在准备阶段需要 PyArrow，不增加 App 的强制依赖：

```sh
hf download FayeZC/SkillMD-138K --type dataset \
  --revision 0d73048abf2fb6ee91f6f9f5ac598d5be8d6bdd7 \
  --include '*.parquet' 'README.md' --local-dir /absolute/raw/skillmd
python -m orbit_catalog.sources.bulk /absolute/raw/train.parquet /absolute/raw/skills.jsonl
orbit-catalog --home /absolute/library import-bulk --spec /absolute/skillmd-source.json --progress
```

SourceSpec 示例（路径替换为本机绝对路径）：

```json
{
  "source_id": "skillmd-138k",
  "kind": "bulk",
  "url": "https://huggingface.co/datasets/FayeZC/SkillMD-138K",
  "priority": 35,
  "config": {
    "file": "/absolute/raw/skills.jsonl",
    "revision": "0d73048abf2fb6ee91f6f9f5ac598d5be8d6bdd7",
    "dataset_id": "FayeZC/SkillMD-138K",
    "dataset_license": "CC-BY-4.0",
    "page_size": 500,
    "body_limit": 2000000,
    "embedding_policy": "all",
    "publish_every_pages": 2,
    "max_seconds": 7200
  }
}
```

每条记录独立校验完整 SHA-256；按 JSONL 字节偏移续传，并绑定文件身份。同步中途换文件会报错，不能把两个版本拼成一次完整扫描。导入每两页发布一批，暂停可继续；只有源扫描完整结束才撤销本版未出现的旧条目。bulk 续传不预载旧库全部正文，每批仅查询该批已有记录。

MCP 离线快照使用 `kind=mcp` 和 `config.snapshot_dir`，目录包含 `manifest.json` 与连续的 `page-0000.json` 等原始响应。manifest 必须标记完整扫描；解析器校验分页链、记录数、不同名称、文件哈希和末页无游标，仍复用正常 MCP 解析。超过默认 120 页时应显式提高本轮预算，例如 `max_pages=500`；不能把暂停当完成。

## 两阶段、最终全文覆盖

先保证每条资源都有概览向量，再补齐正文。这是执行顺序，不是降低最终覆盖要求。用户选择了所有正文块，因此第二步必须运行到 `pending=0` 并核对全部正文块覆盖：

```sh
orbit-catalog --home /absolute/library --model-dir /absolute/e5 embed \
  --scope overview --workers 4 --threads 2 --batch-size 128 --progress
orbit-catalog --home /absolute/library --model-dir /absolute/e5 embed \
  --scope all --all-passages --workers 4 --threads 2 --batch-size 128 --progress
orbit-catalog --home /absolute/library verify
```

`--all-passages` 将目录内既有全部正文块设为可编码，并为以后的来源发布和重建保留全量策略。默认的四块均衡采样仅适用于未选择全量的其他目录。`scope=all` 单独使用指“全部已选可编码块”，因此全文任务必须显式设置 `--all-passages` 或来源 `embedding_policy=all`。

SQLite 保存分块、按文本哈希去重的 float16 向量和模型身份。每批提交后才输出进度；重跑复用已保存向量。编码用主键分页；多进程按资源 ID 范围分片，不复制整个正文库。最多四个模型进程，线程数独立配置，默认仍单进程。取消与异常清理有界；`computed` 是本次编码次数，唯一向量数与覆盖率从 SQL 重新统计。

不要把独立 CLI 全文编码和长时间网络同步并行运行：后者持有来源写锁，编码等待超过 30 秒会明确失败，已提交结果仍可续跑。先同步完源，再编码，最后开放检索服务，是批量扩库的标准顺序。

## 检索与排序

关键词、特征和 E5 语义路分别宽召回，再融合、精排与 MMR 多样化。词法精排在有界候选池中检查所有 passage；语义路先按资源聚合其任意数量分块的最高相似度，再取 top-K。不会因同一长文占据很多高分块而遗漏其他资源。

索引结构版本与向量版本分开：向量批次只更新矩阵缓存，不重建类型、Agent 和特征筛选索引；HTTP ETag 与推荐输入摘要同时跟随向量版本更新。推荐 run 的原数据库版本列仍为整数。超过 64 MiB 的矩阵使用文件映射，按块转为 float32 计算精确余弦。十万级构造基准没有证明必须引入 ANN，详见[向量规模审计](../../audits/catalog-vector-scale-2026-10-03.md)。

A8 个性化探索可使用 `index_only` 资源；其 profile 候选先在 SQL 过滤，再选最多 1000 条并与 hybrid 候选合并。返回 `total_scope=eligible_candidate_window` 及候选窗口元数据，明确不是所有资源的精确最终排名。A7 的来源、许可、兼容和问题证据门控仍生效，公共语料不会自动变成可安装的已审核建议。

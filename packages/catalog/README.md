# Orbit Catalog

独立的资源采集、版本、索引与检索包，Python 3.13，公共 import 为 orbit_catalog，CLI 为 orbit-catalog。使用根 uv workspace，数据合同和 DDL 由 packages/data 提供，数据库仍是独立的 catalog.db。

从仓库根运行：

    uv sync --locked --all-packages --dev
    uv run pytest -q packages/catalog/tests
    uv run orbit-catalog --home .local/catalog init
    uv run orbit-catalog --home .local/catalog verify

明确启用来源才执行 sync；默认检查不联网抓取、不下载模型。可选本地 E5 测试需要 --extra embeddings 和 ORBIT_TEST_E5_DIR，未提供权重时如实跳过。

内置资源种子归本包管理，backend 的旧目录 API 读取相同资源；本包运行时不依赖 orbit_backend。与 backend 的组合测试在根 tests/integration/test_catalog_api.py。Swift 客户端在 [catalog-macos](../catalog-macos/README.md)。

完整边界与入口见 [架构](../../docs/modules/catalog/architecture.md)；历史实测与限制见 [验证记录](../../docs/modules/catalog/validation.md)。

## Skill 获取与本地验收

从仓库根运行 `bash scripts/test-skill-catalog.sh --fetch`，显式获取 Anthropic Skills、Claude Plugins、OpenAI Plugins 和 awesome-copilot 四个来源。可重复传入 `--source anthropic-skills` 等参数缩小范围；`--force` 忽略刷新间隔。复测已有数据只需 `bash scripts/test-skill-catalog.sh`，不联网；`--query '测试 debugging'` 修改检索词。脚本使用 uv，若本机 uv 不在 PATH 则使用已经同步好的 Python 3.13 `.venv`。

输出保留在忽略目录 `.local/skill-catalog/`：`skills.raw.json` 保存实际 Skill 内容、版本和来源，`recommend/skills.json` 是推荐端可接收的草稿 envelope，`search.json` 是实际检索结果，`summary.json` 汇总数量与验证状态。获取复用本包已有连接器，不安装抓取到的 Skill，也不读取用户会话。

脚本还用合成轨迹运行推荐入口：`recommendation.json` 展示获取草稿仍被审核条件拦截，`synthetic-baseline.json` 展示现有已审核种子的推荐结果。新抓取资源需要补齐受控 trigger/effect、能力审核、兼容性和试用步骤；不能把抓取成功自动当作可以推荐。来源失败、同步暂停、空目录、接收失败或检索无命中会返回非零退出码。默认不下载模型，不测试 E5 向量检索。

## Schema v3：存储与查询

`catalog.db` 为 schema v3（`user_version=3`）。打开 v1/v2 库时把旧文件改名为 `catalog.db.v2.bak` 后新建；目录是可由 sync 重建的缓存。

- **存储**：正文、来源文档和 raw 只在 `blob` 表存一份，按未压缩内容的 sha256 去重，≥200 B 用 zlib；`item_source` / `item_version` 只存哈希，每个条目保留最近 5 个版本，无引用的 blob 在发布后清理。`chunk_fts` 是 contentless FTS5（`detail=column`），chunk 文本由版本文档与正文按 `CHUNK_VERSION` 确定性重算并 LRU 缓存。向量只存在 `embedding_cache`（float16，按文本哈希复用），每个条目仅概览加前 3 个正文块生成向量。暂存页发布后通过 incremental vacuum 回收。
- **发布**：同一 `(source, native_id)` 的文档与正文哈希未变则只更新 `seen_run`；仅热度变化时只更新展示列，不重建投影。相同 `content_hash` 选出 canonical（官方 > 来源优先级 > 最早出现），其余写 `canonical_of` 和 `item_relation(duplicate)`，不进列表和检索；另记录 `depends`（组件）与 `alternative_to`（同类型同名不同内容）。`risk.py` 由静态规则给出 `risk` 标志与 `risk_level` 0–3，是估计值，不是审计结论。
- **读取**：`CatalogIndex` 是按 `catalog_meta.generation` 惰性重建的内存快照（类型/agent 位图/语言/难度/风险/官方/来源/许可列、特征倒排、chunk→条目映射），资格过滤与 facets 都是 numpy 掩码运算。词法路一次 `bm25(chunk_fts,4,1)` 取 top-K，过滤后不足时 K 翻倍（上限 8000）；语义路在 fp16 矩阵上分块精确余弦（无 ANN）；`match_many` 先批量编码再并行检索。列表使用三组部分索引（updated_at / installs / name_key，含 type 前缀）做 keyset 游标分页，深翻页不退化。
- **本地条目**：`POST /v1/catalog/local` 写入 `local` 来源（存为 `enabled=0`，网络同步不会访问，物化时视为启用），按 `kind + 规范化正文` 哈希幂等，必须带 `self_check.passed=true`，并附 `generic=0` 特征。

### HTTP（`/v1/catalog`）

| 端点 | 说明 |
| --- | --- |
| `GET /items` | 卡片列表；`kind`、`agent`、`exclude` 可重复；`license`、`max_risk`、`origin`、`official`、`source_id`、`include_duplicates`；`sort=updated\|installs\|stars\|name`，`order`，`limit≤100`，`cursor`。返回 `{items, next_cursor, total(仅首页), generation}` |
| `GET /items/{item_id}` | 详情：卡片字段 + `readme`（仅 licensed）、`manifest`、`features`、`versions`、`permissions`、`components`、`related`、`sources`、`install`、`resident_tokens_est`、`scan` |
| `GET /search?q=&kind=&agent=&limit=&prefix=true` | 资源库搜索框：卡片 + `snippet`、`score`、`score_parts` |
| `GET /facets` | 与 `/items` 相同过滤；各维度计数忽略自身过滤 |
| `POST /local`、`DELETE /local/{item_id}` | 本地条目，201 新建 / 200 已存在 / 204 删除 |
| `GET /models`、`/models/{canonical_id}`、`/benchmarks` | 按 `canonical_id` 合并多来源模型；成绩带 `resolved` |
| 保留 | `status`、`sources`、`PUT sources/{id}`、`sync`、`embeddings`、`jobs`、`POST search`、`GET items/detail` |

错误统一为 `HTTPException(status, detail=<snake_code>)`，如 `invalid_query`、`catalog_item_not_found`、`self_check_required`。网关通过 `orbit_catalog.get_service(home/'catalog.db')` 挂载同一实例，并为卡片补 `installed`、为详情补 `scan`（来源模块缺失时为 `null`）。

### 基准

    uv run python benchmarks/catalog_bench.py --items 20000 --seed 7 [--embeddings] [--json out.json] [--check]

确定性合成数据（Zipf 词表含中文二元词、12 类、正文约 6KB、每条 3–8 个特征、5% 内容重复），向量用无模型的 ToyHashEncoder（384 维）。`--check` 仅在 20k 规模断言目标。

## 推荐可靠性审计更新

2026-10-03 增加 Microsoft 官方 skills 来源并扩大随包离线种子至 1,543 项；新版快照按来源 revision 更新旧安装，已完成网络同步的来源仍优先。`features-4` 增加任务阶段、产物和实践维度，bootstrap 会按投影版本一次重建旧特征索引。

卡片与检索响应新增 `quality` 元数据完整度报告（五维证据、缺失项、版本与明确的未评测/未审计状态），检索保留 verification、language、声明支持矩阵。向量加载或编码失败时保留 BM25/特征结果并返回降级诊断。精确条数、来源 revision、测试与边界见 [推荐可靠性审计](../../docs/audits/recommendation-reliability-2026-10-03.md)。

## 在 App 中启用本地语义检索

App/gateway 创建目录服务时默认读取可选环境变量 `ORBIT_CATALOG_MODEL_DIR`。将其设置为包含 `onnx/model.onnx` 与 `onnx/tokenizer.json` 的本地模型目录**绝对路径**，并在启动 gateway 的 Python 环境提供 `embeddings` 可选依赖；无需修改用户数据库来选择模型。构造参数 `model_dir` 和 CLI `--model-dir` 优先于环境变量，修改环境变量后需重新启动服务。

服务只读取本地模型，不自动联网下载。未设置时保持词法/特征检索；权重缺失、运行时不可用或编码失败时回退并报告 `vector.unavailable`。权重可用但所选目录尚未编码时报告 `not_indexed`；向量库按所选 home 独立保存，使用现有 CLI 显式物化：

```sh
orbit-catalog --home /absolute/orbit-home --model-dir /absolute/multilingual-e5-small embed
orbit-catalog --home /absolute/orbit-home --model-dir /absolute/multilingual-e5-small search '排查自动化测试反复失败的原因'
```

本轮已在忽略的 `.local/audit-20261003/vector-catalog/catalog.db` 实际物化 3,685 个唯一向量，覆盖 3,876/3,876 个候选块；模型固定版本、SHA256、独立运行时和查询实测见上述审计记录。该校验库不替换正常 App 的 `home/catalog.db`，模型权重也不随 Git 提交。


## 十万级公共语料

固定快照流式导入、MCP 离线分页、index_only 边界、逐资源到全部正文向量化、并行/断点续跑与排序候选窗口见[十万级公共资源索引](../../docs/modules/catalog/large-corpus.md)。完整资源、词法分块、可编码块、唯一向量与覆盖资源分别计数。

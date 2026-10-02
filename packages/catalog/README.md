# Orbit Catalog

独立的资源采集、版本、索引与检索包，Python 3.13，公共 import 为 tandem_catalog，CLI 为 tandem-catalog。使用根 uv workspace，数据合同和 DDL 由 packages/data 提供，数据库仍是独立的 catalog.db。

从仓库根运行：

    uv sync --locked --all-packages --dev
    uv run pytest -q packages/catalog/tests
    uv run tandem-catalog --home .local/catalog init
    uv run tandem-catalog --home .local/catalog verify

明确启用来源才执行 sync；默认检查不联网抓取、不下载模型。可选本地 E5 测试需要 --extra embeddings 和 TANDEM_TEST_E5_DIR，未提供权重时如实跳过。

内置资源种子归本包管理，backend 的旧目录 API 读取相同资源；本包运行时不依赖 tandem_backend。与 backend 的组合测试在根 tests/integration/test_catalog_api.py。Swift 客户端在 [catalog-macos](../catalog-macos/README.md)。

完整边界与入口见 [架构](../../docs/modules/catalog-architecture.md)；历史实测与限制见 [验证记录](../../docs/modules/catalog-validation.md)。

## Skill 获取与本地验收

从仓库根运行 `bash scripts/test-skill-catalog.sh --fetch`，显式获取 Anthropic Skills、Claude Plugins、OpenAI Plugins 和 awesome-copilot 四个来源。可重复传入 `--source anthropic-skills` 等参数缩小范围；`--force` 忽略刷新间隔。复测已有数据只需 `bash scripts/test-skill-catalog.sh`，不联网；`--query '测试 debugging'` 修改检索词。脚本使用 uv，若本机 uv 不在 PATH 则使用已经同步好的 Python 3.13 `.venv`。

输出保留在忽略目录 `.local/skill-catalog/`：`skills.raw.json` 保存实际 Skill 内容、版本和来源，`recommend/skills.json` 是推荐端可接收的草稿 envelope，`search.json` 是实际检索结果，`summary.json` 汇总数量与验证状态。获取复用本包已有连接器，不安装抓取到的 Skill，也不读取用户会话。

脚本还用合成轨迹运行推荐入口：`recommendation.json` 展示获取草稿仍被审核条件拦截，`synthetic-baseline.json` 展示现有已审核种子的推荐结果。新抓取资源需要补齐受控 trigger/effect、能力审核、兼容性和试用步骤；不能把抓取成功自动当作可以推荐。来源失败、同步暂停、空目录、接收失败或检索无命中会返回非零退出码。默认不下载模型，不测试 E5 向量检索。

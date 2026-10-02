# Tandem Catalog

独立的资源采集、版本、索引与检索包，Python 3.13，公共 import 为 tandem_catalog，CLI 为 tandem-catalog。使用根 uv workspace，数据合同和 DDL 由 packages/data 提供，数据库仍是独立的 catalog.db。

从仓库根运行：

    uv sync --locked --all-packages --dev
    uv run pytest -q packages/catalog/tests
    uv run tandem-catalog --home .local/catalog init
    uv run tandem-catalog --home .local/catalog verify

明确启用来源才执行 sync；默认检查不联网抓取、不下载模型。可选本地 E5 测试需要 --extra embeddings 和 TANDEM_TEST_E5_DIR，未提供权重时如实跳过。

内置资源种子归本包管理，backend 的旧目录 API 读取相同资源；本包运行时不依赖 tandem_backend。与 backend 的组合测试在根 tests/integration/test_catalog_api.py。Swift 客户端在 [catalog-macos](../catalog-macos/README.md)。

完整边界与入口见 [架构](../../docs/modules/catalog-architecture.md)；历史实测与限制见 [验证记录](../../docs/modules/catalog-validation.md)。

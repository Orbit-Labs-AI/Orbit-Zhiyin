# 活跃分支迁移

状态：结构重构的接入指南。基线：main `15a753f`。本次保留运行行为、Python 包名与 CLI，未合入其他开发分支的功能。

| 原位置 | 新位置 |
| --- | --- |
| src/tandem_backend | packages/backend/src/tandem_backend |
| 根 tests 的特征族测试 | packages/backend/tests/analytics、bottleneck |
| 根 tests 的旧行为回归 | packages/backend/tests/regression |
| tests/test_modular_pipeline.py | tests/integration/test_modular_pipeline.py |
| packages/data/tests/data | packages/data/tests |
| docs/design/demo 的 Advance 内容 | prototypes/advance |
| Lite HTML、check-benchmark.cjs | prototypes/lite |
| demo/tests/shoot.mjs | prototypes/advance/tools/shoot.mjs |
| docs/backend/versions | docs/releases/backend |
| docs/backend 的架构与数据流 | docs/architecture |
| docs/backend 的算法说明 | docs/modules |
| docs/plan/analysis-inputs.md、docs/data-contract.md | docs/contracts |
| scripts/benchmark_*.py | benchmarks/analytics |
| scripts/validate_*、verify_semantic_history.py | evals/analytics |
| scripts/check-connectors.sh | scripts/check-data.sh |
| docs/modules/catalog-architecture.md、catalog-validation.md | docs/modules/catalog/architecture.md、validation.md |
| docs/modules/recommendation.md、recommendation-validation.md | docs/modules/recommendation/engine.md、validation.md |
| docs/plans/analysis-audit.md、data-audit.md、backend-gap.md | docs/audits/ |
| docs/design/README.md 的 Logo、Demo、画板章节 | docs/design/brand.md、demo.md、boards.md |
| docs/design/logo/tandem-*（spiral 变体升为主版本） | docs/design/logo/orbit-*，原洛伦茨主标志移到 logo/variants/lorenz/ |

最后五行是 2026-10-02 的文档整理（产品改名 Orbit）。活跃分支 merge 时若遇到这些文件的 rename/modify 冲突，把改动应用到新位置；不要恢复旧路径。

## 合并步骤

1. 在自己的功能分支 merge 更新后的 main，保留合并历史。
2. 遇到 rename/delete 冲突，将功能改动应用到新实现文件；不要在旧目录恢复整份源码。
3. 后端旧 import 入口仍能使用；新增代码优先导入 profiling、recommend、reporting、evaluation 等职责目录。
4. Advance 新页面、外壳与图表仍进入原型的 src；本次没有接收未合入 main 的 UI 代码。
5. Catalog 已进入 packages/catalog，Swift 客户端位于 packages/catalog-macos；使用根 uv.lock，不恢复已删除的 requirements-dev.lock 或平行 uv.lock。
6. JS/TS 依赖从根执行 pnpm install，统一更新根锁；不要恢复包内 pnpm-lock.yaml。
7. 运行 pnpm check；原型改动还需 pnpm check:ui。确认模块接入表的入口、测试与状态。

## 后端实现路径

analysis / feedback / content / portrait / trajectory / bottlenecks → profiling；catalog / recommend / resource_fetch → recommendation；analysis_reports / narrative → reporting；pipeline_eval / reader_eval → evaluation；API / CLI 实现在对应目录内，公开导出保持原入口。

`legacy/` 只放旧库和旧解析兼容。当前仍运行的画像算法进入 profiling，没有因年代较早被当成废弃逻辑删除。

## 后续 App 接入

正式 target 放 apps/desktop，接入同一后端服务和 canonical 数据目录，并补充服务生命周期与原生 UI 测试。本次不建立不可运行的空 App，也不将 HTML 原型伪装成完成的桌面产品。

本次整理期间 main 更新到 `f834616`；新增 recommend 引擎已纳入 packages/backend，保持 `tandem_backend.recommend.*` 公开命名空间。新增推荐工具分别进入 evals/recommendation/demo.py 与 catalog.py。原有 catalog/resource_fetch 薄入口仍可使用。

PR #29 在合并前进入 main，已一并接入：src/tandem_catalog → packages/catalog/src/tandem_catalog；tests/catalog → packages/catalog/tests；跨包 API 用例 → tests/integration/test_catalog_api.py。共享种子 skills.json 归 Catalog 包管理，backend 保留原资源访问 API。

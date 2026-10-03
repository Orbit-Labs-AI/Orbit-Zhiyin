# 测试与验收

状态：当前开发流程；维护：`yhyfhgs`。所有命令从仓库根执行。

## 分类与归属

| 类型 | 位置 | 运行入口 |
| --- | --- | --- |
| Python 模块测试 | packages/backend/tests、packages/data/tests、packages/catalog/tests | uv run pytest -q 对应目录 |
| 历史兼容回归 | backend/tests/regression | 保留原来的行为边界；后续新增测试按所属模块归类 |
| TypeScript 模块测试 | packages/connectors/tests | pnpm --filter @orbit/connectors check |
| 跨包与跨语言 | tests/integration | pnpm check:integration |
| 服务流程 | tests/e2e | 随 check / check:integration 运行 |
| 分析结果等价性 | tests/regression | 随 pnpm check 运行；见下文「性能与等价性」 |
| UI 原型行为 | prototypes/advance/tests | pnpm check:ui |
| 质量评测 | evals；运行时评价在 backend/evaluation | 见 evals/README |
| 推荐偏好与收益 | evals/recommendation、backend/tests/recommend | bash scripts/test-recommend.sh |
| 性能与内存 | benchmarks | 见 benchmarks/README |
| 安装后验证 | scripts/check-installed.sh | pnpm check:installed |

`pnpm check` 分两步运行 Python 测试：先用 pytest-xdist 按 CPU 核数并行跑 `-m "not serial"`，再串行跑 `-m serial`。`serial` 标记只用于依赖真实时钟（心跳、超时、延迟预算）或固定端口的测试，包括 `packages/backend/tests/services` 下的服务流程、缓存延迟、AI 上下文包、通知／遥测以及其余直接断言实际墙钟耗时的性能预算测试。运行耗时取决于本机负载；延迟预算检查须避开同时进行的大规模重放或 Benchmark。其余测试之间不能共享端口、全局目录或固定文件名；新增测试须在 `-n auto` 下连续通过。单独调试某个测试时直接串行运行，不加 `-n`。`pnpm check:integration` 同样并行运行。

`pnpm check` 先构建 TypeScript producer，再运行全部 Python 测试，随后检查原型产物、文档、独立构建与安装。staging 集成缺少产物时失败，不会静默跳过。

安装检查把三个 wheel 安装到临时环境，在仓库外运行 Demo、评价和 CLI；用于发现 editable 安装掩盖的路径或包资源问题。根 Python workspace 不发布为一个额外运行包。

## UI 测试

```sh
pnpm --filter @orbit/prototype-advance exec playwright install chromium
pnpm check:ui
pnpm check:ui --project=mac-14
```

默认使用 Playwright 管理的 Chromium，与 CI 一致；明确需要本机 Chrome 时设置 `PLAYWRIGHT_CHANNEL=chrome`。截图工具位于原型 `tools/shoot.mjs`，截图不等于断言型测试。

## 样本与结果

模块独有构造样本放模块 tests/fixtures；当前 backend 的质量样本供评测工具复用，避免复制。跨模块构造器可以从 data 的验证模块调用。测试和质量评测不自动读取真实历史。

真实数据验收需显式参数，输出放忽略目录 `.local/`。常规 CI 使用构造样本且不联网刷新资源或下载模型。性能评测记录硬件、规模与口径，不将单机耗时当成 App SLA。

## 性能与等价性

分析的性能改动以两件工具对照：`benchmarks/analytics/synthetic.py` 用固定种子生成完全虚构的输入（12 项目、3 来源，含中英请求、纠偏、偏好、反馈、工具失败与重复参数、审批、压缩、中断、模型调用与子代理），也可经公开 ingest 写入临时 `orbit.db`。

- 等价性回归：`uv run pytest -q tests/regression/test_analysis_equivalence.py`。200 会话输入下比较 `analyze_bundle(with_text=False)` 与 `build_products` 的核心 section（overview.counts、sessions 的 features/usage/bottleneck_features、projects、tools、workflow、statistics 样本计数）与金标 `packages/backend/tests/fixtures/analysis-golden-v1.json`。新增字段或 section 不影响断言；删除字段或数值变化会失败。同时断言生成器确定性，且金标不含真实路径或用户名。
- 金标更新：只有结果变化是有意为之时运行 `uv run python tests/regression/test_analysis_equivalence.py --update-golden`，并在 PR 描述中说明原因与差异（哪些 section、哪些数值变化）。不得为让检查通过而放宽断言或重生成金标掩盖回归。
- 分阶段基准：`uv run python -m benchmarks.analytics.full_pipeline --sizes 500 1000 2500 --repeats 3`，可加 `--with-text`、`--canonical`（测量 read_analysis）与 `--profile`。基准不作 CI 硬门槛，结果连同硬件和口径放 `.local/` 或写入 PR 说明。

服务流程验收覆盖 CLI 导入、API 会话与证据、报告一致性和评价隔离；目前尚无原生 App，不能将其称为原生 UI 验收。

Swift 客户端的 6 项测试通过 swift test --package-path packages/catalog-macos 运行，已纳入 pnpm check。Catalog 的本地 E5 权重测试是显式可选集成，默认缺少 ORBIT_TEST_E5_DIR 时跳过；不与必须执行的 staging 桥接测试混淆。

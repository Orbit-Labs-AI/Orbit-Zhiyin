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
| UI ↔ 后端契约 | tests/integration/test_ui_fixture_contract.py | 随 pnpm check；原型 stub 夹具的 key-tree 必须是真实 gateway 响应的子集，已知漂移登记在 KNOWN_DRIFT |
| 真实 gateway + UI 旅程 | scripts/check-app-journey.sh、prototypes/advance/tests/app-journey.spec.mjs | bash scripts/check.sh journey（需 Playwright Chromium；样本由仓库内构造器生成） |
| macOS 宿主 | apps/desktop（Orbit.swift、build.py、server_entry.py）、scripts/check-macos-app.py | JOURNEY_MACOS_APP=1 bash scripts/check.sh journey（构建 Orbit.app 后冒烟）；Python 部分随 pnpm check 做 ruff，Swift 宿主尚无单元测试 |

`pnpm check` 分两步运行 Python 测试：先用 pytest-xdist 按 CPU 核数并行跑 `-m "not serial"`，再串行跑 `-m serial`。`serial` 标记只用于依赖真实时钟（心跳、超时、延迟预算）或固定端口的测试，包括 `packages/backend/tests/services` 下的服务流程、缓存延迟、AI 上下文包、通知／遥测以及其余直接断言实际墙钟耗时的性能预算测试。运行耗时取决于本机负载；延迟预算检查须避开同时进行的大规模重放或 Benchmark。其余测试之间不能共享端口、全局目录或固定文件名；新增测试须在 `-n auto` 下连续通过。单独调试某个测试时直接串行运行，不加 `-n`。`pnpm check:integration` 同样并行运行。

已知跳过项：`pnpm check:ui` 未设 `LIVE_GATEWAY` 时，app-journey、live-r3-gateway、live-s7 与 live-s2 的真实 gateway 冒烟会跳过（脚本结束时打印提示，Playwright 汇总中计入 skipped）；它们由 `bash scripts/check.sh journey` 覆盖。Python 侧的 `xfail(strict=True)` 只用于登记已确认、归属他区的缺陷（如 dsh/kimi/opencode 的请求边界、纠偏词典召回），修复后会以 XPASS 失败提醒删除标记。

跨包测试的共享夹具在 `tests/conftest.py`（仓库根与合成数据写入器的 `sys.path`、`synthetic`、`gateway_harness`），测试文件不再自行注入路径。

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

- 等价性回归：`uv run pytest -q tests/regression/test_analysis_equivalence.py`。两类断言：①真值——`benchmarks.analytics.synthetic.generate_bundle_with_truth` 返回生成器注入的会话、subagent、项目、轮次、人类消息、工具调用与失败、token 总数，分析结果必须逐项相等（与实现无关的 oracle；纠偏信号召回不足以 strict xfail 记录）；②金标——200 会话 `analyze_bundle(with_text=False)` 与 `build_products` 的核心 section 及 30 会话 `with_text=True` 的 text/preferences，金标 `tests/regression/fixtures/analysis-golden-v2.json` 保存 key-tree、sha256、可读 summary 与 truth；`--update-golden` 打印新旧差异。新增字段或 section 不影响断言；删除字段或数值变化会失败。同时断言生成器确定性，且金标不含真实路径或用户名。
- 金标更新：只有结果变化是有意为之时运行 `uv run python tests/regression/test_analysis_equivalence.py --update-golden`，并在 PR 描述中说明原因与差异（哪些 section、哪些数值变化）。不得为让检查通过而放宽断言或重生成金标掩盖回归。
- 分阶段基准：`uv run python -m benchmarks.analytics.full_pipeline --sizes 500 1000 2500 --repeats 3`，可加 `--with-text`、`--canonical`（测量 read_analysis）与 `--profile`。基准不作 CI 硬门槛，结果连同硬件和口径放 `.local/` 或写入 PR 说明。

服务流程验收覆盖 CLI 导入、API 会话与证据、报告一致性和评价隔离。原生 macOS 宿主位于 apps/desktop；上述测试不等同于原生安装包的系统权限、通知和窗口交互验收。

Swift 客户端的 6 项测试通过 swift test --package-path packages/catalog-macos 运行，已纳入 pnpm check。Catalog 的本地 E5 权重测试是显式可选集成，默认缺少 ORBIT_TEST_E5_DIR 时跳过；不与必须执行的 staging 桥接测试混淆。

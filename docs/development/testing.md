# 测试与验收

验证应覆盖本次改变的行为与接口。文档检查、构造测试、UI 行为、质量评测、真实数据和性能基准各回答不同问题；通过其中一种，不代表其余结果已经成立。

## 按改动选择

先完成[开发环境](setup.md)。以下命令从根目录执行；整包测试和构建通过 `scripts/heavy.py` 控制本机负载。

| 改动范围 | 必要入口 |
| --- | --- |
| 纯文档 | `pnpm check:docs`、`git diff --check` |
| backend | `python3 scripts/heavy.py uv run pytest -q packages/backend/tests` |
| data | `python3 scripts/heavy.py uv run pytest -q packages/data/tests`；保留该包格式检查 |
| catalog | `python3 scripts/heavy.py uv run pytest -q packages/catalog/tests` |
| TypeScript connector | `pnpm --filter @orbit/connectors check` |
| UI 源码和行为 | `python3 scripts/heavy.py pnpm check:ui`；同步生成产物 |
| Swift 客户端 | `python3 scripts/heavy.py swift test --package-path packages/catalog-macos` |
| 跨包接口、DDL、依赖/锁文件、构建脚本 | `python3 scripts/heavy.py pnpm check` |
| 桌面打包 | [Mac App 构建与 helper 冒烟](mac-app.md)及相关回归 |

Python 代码另跑相关路径的 `uv run ruff check`；数据包按现有约定执行 `uv run ruff format --check packages/data/src packages/data/tests`。单一失败可直接运行对应测试，避免重复整套检查。当前 `main` 的[项目规则](../../AGENTS.md)是检查范围与并发限制的依据。

`pnpm check:docs` 检查 Markdown 本地链接、唯一锁文件、已退休目录和品牌产物。它不验证远端网页、运行示例命令或判断文档事实；相关内容仍需对照实现。

## 全量与集成

`pnpm check` 构建并检查 TypeScript producer，运行 lint、Python 测试、Swift 客户端测试、原型产物检查、文档检查及 wheel 安装验收。`pnpm check:integration` 构建 producer 后运行跨包和服务流程测试。缺 producer 的桥接测试必须失败，不能静默跳过。

脚本先运行非 `serial` 的 Python 测试，再串行运行依赖真实时钟或固定端口的测试。脚本当前使用 `-n auto`；本机多任务运行时可用 `PYTEST_XDIST_AUTO_NUM_WORKERS=4` 限制自动 worker 数，并通过 heavy 闸门排队。单独调试测试不必并行。

## UI 与原生验证

```sh
pnpm --filter @orbit/prototype-advance exec playwright install chromium
python3 scripts/heavy.py pnpm check:ui
```

默认浏览器是 Playwright Chromium；`PLAYWRIGHT_CHANNEL=chrome` 用于明确需要本机 Chrome 的场景。可以追加 `--project=mac-14` 缩小调试范围。截图用于查看视觉效果，不能替代行为断言。

浏览器测试覆盖 Web UI，helper 冒烟覆盖冻结运行时和接口；菜单栏、权限、通知、窗口生命周期等原生行为仍需对应原生验证。已有原生 App，不应再把服务测试当作整个 App 的验收。

## 数据与效果边界

常规测试使用构造样本，不读取个人历史或下载模型。真实数据需显式参数，结果保存在忽略目录，并记录来源、窗口、排除项、环境和 SHA。可选 E5 集成缺少 `ORBIT_TEST_E5_DIR` 时可跳过；这与必须运行的 connector 桥接不同。

质量评测见 [evals](../../evals/README.md)，性能见 [benchmarks](../../benchmarks/README.md)。分析优化可使用 `tests/regression/test_analysis_equivalence.py` 比较核心结果；仅在有意改变结果时更新金标，并在 PR 解释差异。

## 完成标准

在与最新 `main` 的合并结果上完成所需检查，记录命令和结果。之后只有新改动、失败或具体未解决疑点才补验；不为纯文档改动额外跑 Benchmark、付费模型、原生构建或真实历史导入。

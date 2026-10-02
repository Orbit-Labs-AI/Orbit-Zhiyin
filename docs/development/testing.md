# 测试与验收

状态：当前开发流程；维护：`yhyfhgs`。所有命令从仓库根执行。

## 分类与归属

| 类型 | 位置 | 运行入口 |
| --- | --- | --- |
| Python 模块测试 | packages/backend/tests、packages/data/tests | uv run pytest -q 对应目录 |
| 历史兼容回归 | backend/tests/regression | 保留原来的行为边界；后续新增测试按所属模块归类 |
| TypeScript 模块测试 | packages/connectors/tests | pnpm --filter @tandem/connectors check |
| 跨包与跨语言 | tests/integration | pnpm check:integration |
| 服务流程 | tests/e2e | 随 check / check:integration 运行 |
| UI 原型行为 | prototypes/advance/tests | pnpm check:ui |
| 质量评测 | evals；运行时评价在 backend/evaluation | 见 evals/README |
| 性能与内存 | benchmarks | 见 benchmarks/README |
| 安装后验证 | scripts/check-installed.sh | pnpm check:installed |

`pnpm check` 先构建 TypeScript producer，再运行全部 Python 测试，随后检查原型产物、文档、独立构建与安装。staging 集成缺少产物时失败，不会静默跳过。

安装检查把两个 wheel 安装到临时环境，在仓库外运行 Demo、评价和 CLI；用于发现 editable 安装掩盖的路径或包资源问题。根 Python workspace 不发布为一个额外运行包。

## UI 测试

```sh
pnpm --filter @tandem/prototype-advance exec playwright install chromium
pnpm check:ui
pnpm check:ui --project=mac-14
```

默认使用 Playwright 管理的 Chromium，与 CI 一致；明确需要本机 Chrome 时设置 `PLAYWRIGHT_CHANNEL=chrome`。截图工具位于原型 `tools/shoot.mjs`，截图不等于断言型测试。

## 样本与结果

模块独有构造样本放模块 tests/fixtures；当前 backend 的质量样本供评测工具复用，避免复制。跨模块构造器可以从 data 的验证模块调用。测试和质量评测不自动读取真实历史。

真实数据验收需显式参数，输出放忽略目录 `.local/`。常规 CI 使用构造样本且不联网刷新资源或下载模型。性能评测记录硬件、规模与口径，不将单机耗时当成 App SLA。

服务流程验收覆盖 CLI 导入、API 会话与证据、报告一致性和评价隔离；目前尚无原生 App，不能将其称为原生 UI 验收。

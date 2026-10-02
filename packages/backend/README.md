# Orbit Backend

当前实现：产品编排、本机 API、CLI、画像、特征分析、推荐与报告。Python import 仍为 `tandem_backend`，安装后的命令仍为 `tandem`。

从仓库根执行：

```sh
uv sync --locked --all-packages --dev
uv run tandem demo
uv run pytest -q packages/backend/tests
uv build --package tandem-backend
```

模块测试位于 `tests/`：`analytics/` 与 `bottleneck/` 按特征族组织，`regression/` 保留旧画像、报告和兼容行为的回归。跨 data/backend/TypeScript 的测试属于根目录 `tests/integration/`，运行前必须构建 connector。

会话事实由 `tandem_data` 管理；后端只通过数据读取与导入服务接入，不新增原生日志解析器。旧库显式经 `legacy/` 访问。

职责目录：`application` 组织用例，`api` / `cli` 提供入口，`profiling` 处理画像与要求，`analytics` 保留特征族，`recommend` 管理现有资源匹配，`reporting` 输出报告，`evaluation` 提供运行时评价。根级旧模块仅作兼容导出。整体依赖见 [模块接入表](../../docs/architecture/module-map.md)。

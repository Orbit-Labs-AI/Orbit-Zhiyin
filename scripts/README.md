# 开发与验收入口

- bootstrap.sh：安装根 workspace 的锁定依赖。
- dev.sh：启动当前本机 API。全局 CLI 参数位于 serve 之前，例如先运行 `uv run orbit demo`，再运行 `pnpm dev --home .local/demo/data`；自己的数据目录须已初始化；调整端口可直接 `uv run orbit serve --port 8766`。
- check.sh：本地和 CI 共用的结构、模块、集成、安装验收；`integration` 子命令只跑跨包与服务流程；`journey` 子命令跑真实 gateway + 真实 UI 旅程，`JOURNEY_MACOS_APP=1` 时在 macOS 上再构建 Orbit.app 并做宿主冒烟。
- check-ui.sh：Lite 检查和 Advance Playwright，可追加 --project=mac-14。未设 `LIVE_GATEWAY` 时，依赖真实 gateway 的用例会跳过，结束时打印明确提示。
- check-app-journey.sh：真实 gateway（本 checkout 的后端、临时 HOME）+ 新构建的 Advance 页面跑 `app-journey.spec.mjs`；样本由 `orbit_data.validation.fixtures` 与合成 Codex 生成，截图与报告写入 `.local/journey-shots`；`JOURNEY_GATEWAY` 可复用已运行的 gateway（如 Orbit.app 内的 orbit-helper）。
- check-macos-app.py：对已构建的 Orbit.app 冻结 orbit-helper 做无 GUI 冒烟（端口握手、令牌、/app、导入后分析、SIGTERM）；先运行 `uv run python apps/desktop/build.py`。
- check-installed.sh：构建 wheel 并在仓库外的临时环境验证安装。
- check-data.sh：数据包构造验收；真实来源仅在显式参数启用时读取。
- [check-preference.sh](check-preference.sh)：Preference／Instruction 构造回归；指定 `--db` 后追加只读本地快照诊断，参数与输出见 [Preference 本地验证](../docs/modules/analytics/preference.md#本地验证脚本)。
- heavy.py：重负载命令的全机闸门（默认 2 个并发，`HEAVY_NAME=merge HEAVY_SLOTS=1` 用于串行合并），规则见根 `AGENTS.md`「合并门槛与本机并行」。
- check-repository.py：只看 git 跟踪文件，核对文档本地链接、唯一 workspace 锁、旧目录残留，以及 docs 下文档是否能从 docs/README.md 导航到达。
- check-benchmark.sh：对 `.local/backend-nine-hour` 下的本地数据运行时间切分推荐基准（`evals.benchmark.local`），需显式准备数据。
- check-feature-diagnostics.sh：本地特征诊断（`evals.analytics.local_diagnostics`），只读显式指定的数据。
- test-recommend.sh：无真实日志复现推荐偏好反事实与条件收益（`evals.recommendation.validation`），附推荐入口耗时与内存观察。
- test-local-codex-recommend.sh：显式调用时只读导入本机 Codex 会话并跑推荐（`evals.recommendation.local_codex`）。
- test-skill-catalog.sh：离线复用已抓取的 Skills 目录做冒烟，`--fetch` 才联网刷新（`evals.recommendation.skills`）。
- validate_analysis_products.py：兼容的薄入口，转交 `evals.analytics.products` 完成构造或显式授权的本地 session 组合验收。

业务逻辑放 packages，性能逻辑放 benchmarks，质量及真实数据验收放 evals。项目专属构建和截图工具随原型维护，根脚本只组织入口。

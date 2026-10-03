# 开发与验收入口

- bootstrap.sh：安装根 workspace 的锁定依赖。
- dev.sh：启动当前本机 API。全局 CLI 参数位于 serve 之前，例如先运行 `uv run orbit demo`，再运行 `pnpm dev --home .local/demo/data`；自己的数据目录须已初始化；调整端口可直接 `uv run orbit serve --port 8766`。
- check.sh：本地和 CI 共用的结构、模块、集成、安装验收；integration 子命令只跑跨包与服务流程。
- check-ui.sh：Lite 检查和 Advance Playwright，可追加 --project=mac-14。
- check-installed.sh：构建 wheel 并在仓库外的临时环境验证安装。
- check-data.sh：数据包构造验收；真实来源仅在显式参数启用时读取。
- [check-preference.sh](check-preference.sh)：Preference／Instruction 构造回归；指定 `--db` 后追加只读本地快照诊断，参数与输出见 [Preference 本地验证](../docs/modules/analytics/preference.md#本地验证脚本)。
- check-repository.py：核对文档本地链接、唯一 workspace 锁与旧目录残留。
- validate_analysis_products.py：兼容的薄入口，转交 `evals.analytics.products` 完成构造或显式授权的本地 session 组合验收。

业务逻辑放 packages，性能逻辑放 benchmarks，质量及真实数据验收放 evals。项目专属构建和截图工具随原型维护，根脚本只组织入口。

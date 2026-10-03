# 仓库脚本入口

根脚本只组织启动、构建和验证，业务逻辑留在 packages，质量与性能分别留在 evals/benchmarks。

| 入口 | 职责 |
| --- | --- |
| `bootstrap.sh` | 安装根 workspace 的锁定 Python / pnpm 依赖 |
| `dev.sh` | `orbit serve` 的薄入口，`--home` 位于 serve 前 |
| `check.sh` | 完整或 integration 验证，先准备 TypeScript producer |
| `check-ui.sh` | Lite 检查与 Advance Playwright |
| `check-installed.sh` | wheel 构建及仓库外安装验收 |
| `check-repository.py` | 文档链接、锁文件归属、退休目录与品牌产物 |
| `check-data.sh` | 数据层构造验收；显式参数才读真实来源 |
| `check-preference.sh` | 偏好/指令构造回归，可显式增加快照诊断 |
| `validate_analysis_products.py` | 转交 evals 的组合分析验收 |
| `check-macos-app.py` | 冻结 helper 的独立 home 冒烟 |
| `heavy.py` | 本机重负载并发闸门，避免多个任务争用资源 |
| `orbit-rename.py` | 历史命名迁移；`--check` 只检查残留 |

命令、范围与停止条件见[测试指南](../docs/development/testing.md)。不要因脚本存在就对每次改动全部运行；也不要静默跳过本次必需的契约或构建检查。

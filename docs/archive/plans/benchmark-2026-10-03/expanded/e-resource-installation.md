---
added: 2026-10-03
---

# E-资源与安装闭环

> 历史来源：本页为2026-10-01 至 10-03 的历史方案，2026-10-07 从团队 Vault 迁入。原位置：`项目/Orbit/benchmark/后续扩展/E-资源与安装闭环.md`。正文与原有日期、结论保留，仅整理导航和空白；私人会话定位不公开。本文中的“当前”、TODO、测试数量和执行命令仅对原文基线成立，本次没有重新验证，也不自动形成任务或授权。现行入口：[源码文档](<../../../../../evals/README.md>)。

[总入口](<overview.md>) · [共同协议](<protocol.md>) · 执行：S5

目标：覆盖检索、兼容性、生成物、安装和实际触发。找得到资源不代表推荐有效；装进配置也不代表 Agent 已加载。每层分别验收。

| ID | 优先级 | 实验 / 样本 | 指标与判定 | 入口或缺口 |
| --- | --- | --- | --- | --- |
| E01 | P1 | 冻结目录和独立 query 金标；词法 / 向量 / 混合检索比较 | Recall@K、MRR、NDCG@K；无相关项查询、重复项、过期项 | `packages/catalog/tests/test_retrieval.py` / query；真实相关性标签待补 |
| E02 | P0 | Agent、版本、权限、依赖、网络、已安装状态的组合 | 可执行候选精度、正确拒绝 / needs_context；缺信息不能放行 | `evals.recommendation.catalog`、recommend gates / family_contracts |
| E03 | P0 | allow / hook / rule / Skill 的构造正反例 | Schema / lint 通过率、危险误放数、合理命令误拦数、重复 / 冲突检出 | 现有 install / risk / evaluation 工具；不执行不可信历史命令 |
| E04 | P0 | 每个支持 Agent × action × 空 / 已有 / 手改 / 非法配置 | 预览 diff=实际差异，撤销字节恢复，重复安装无变化，未知键保留 | `install_roundtrip`、`packages/backend/tests/install/` |
| E05 | P0 | 预览后配置改变、并发写入、用户改标记块、符号链接 | 过期 digest 拒绝、冲突可解释、避免覆盖用户改动；恢复后完整性 | install lifecycle / stacked_revert / symlink_targets 等测试 |
| E06 | P1 | 受控 Agent 启动后核实配置加载与 Skill description 触发 | 加载确认率、应触发 TPR / 不应触发 FPR、错误 Agent 触发数 | 安装成功标志不足；真实 Agent 集成需要独立沙箱与授权 |
| E07 | P1 | 推荐→预览→安装→实际触发→效果记录→撤销 | 各阶段完成率、失败定位、动作 / 版本 / 证据可追溯率 | 跨模块闭环；收益复用 A 的执行，不把触发次数当效果 |

## 样本与隔离

E01 建议 30–50 个独立查询起步，覆盖精确名称、场景描述、中英文、无匹配、近似但不兼容资源。人工相关性标签与 B04 共用；检索调参使用 dev 子集，test 子集保留。目录版本、正文摘要和去重规则固定，不能刷新目录后沿用旧标签。

E03/E04 先使用临时目录和仓库提供的显式配置路径 / 夹具。禁止改写真实 `~/.codex`、`~/.claude` 或其他 Agent 配置；不要为了评测重设用户的全局 HOME / CODEX_HOME。每个 run 的安装根、数据库、端口和撤销日志独立。

安装门禁要求指定夹具全部满足契约；不支持的落点要明确 unmappable / unsupported。用户已经改过的内容，正确行为可能是拒绝自动撤销并解释冲突，不能为获得“100%恢复”覆盖用户新内容。

E06 建议每个 Skill 先准备 20 个应触发与 20 个不应触发样本，动作正文固定；真实加载和触发由日志证实。模型选择不由词面匹配模拟结果代替。先人工检查沙箱、输入和工具，再启动外部执行器。

## 可复用命令

```sh
uv run --locked pytest -q packages/catalog/tests/test_retrieval.py packages/catalog/tests/test_query.py
uv run --locked pytest -q packages/backend/tests/install
uv run --locked tandem eval run --suite install_roundtrip --no-store --json .local/benchmark/s5-install-01.json
```

目录 envelope 验证入口为 `uv run --locked python -m evals.recommendation.catalog /path/to/catalog-directory --agent codex`，参数是包含各资源族 JSON envelope 的目录，不是单个 JSON 文件。只读验证指定内容；不自动联网刷新、下载 embedding、安装真实资源。真实性与网络资源的快照工作需另有明确输入。

## 交付与边界

交付检索金标统计、兼容性矩阵、生成物误放 / 误拦表、安装往返与冲突记录、加载 / 触发证据。B 负责“是否选对”，E 负责“候选能否正确执行”；不各建一份资源目录。真实安装与长期收益未测时原样报告，不能把 E04 的构造通过写成 E06/E07 完成。

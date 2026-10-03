# 历史技能学习评测

执行协议见 [开发预登记](../../docs/plans/history-skill-learning.md)，候选划分在 [protocol.json](protocol.json)。数据集、原始轨迹、答案、密钥和派生数据库只保存在外部本地目录，不进入仓库。

## 隔离与计量

- `study.py` 仅准备预登记的 split；test 必须持有 freeze 记录，代码、协议和任务族都与冻结值一致。历史已暴露的四族禁止充当新 held-out test。
- 任务容器无网络、无宿主机目录挂载；个性化文件通过只读 Docker volume 提供。上游预装 Skills 从所有 arm 的环境中删除。
- `runtime.py` 为每次运行创建全新 Pi 配置，Kimi K3 max，禁用 ambient skills、上下文文件和扩展自动发现。只有显式指定的工具扩展能够操作容器。隐藏验证器在 Pi 退出后才复制进去。
- 每次尝试保存代码副本、模型配置、任务与环境摘要、完整事件、产物及 verifier 日志。运行目录不得覆盖。凭据在 Pi 退出后删除。
- tokens 仅累加 `message_end` 的 input/output/cacheRead/cacheWrite；`agent_end` 不重复计数。失败请求或缺失 usage 记为 unknown，保留 known subtotal。JUnit 用于真实参数化 case 数，原始 reward 和 CTRF 同时保留；有 skipped case 不报告成功。
- 注入、成功读取 Skill、实际执行方法分开记录。读取事件不证明方法被采用，actual usage 需要工具轨迹证据。

## 开发流程

从固定上游提交稀疏获取 history / validation；不要预先获取 test 内容。在仓库根使用外部 `STUDY_ROOT`、`BENCH_SOURCE`：

```bash
python3 scripts/heavy.py uv run python -m evals.skill_learning.study prepare \
  --root "$STUDY_ROOT" --source "$BENCH_SOURCE" \
  --families court-form-filling --split validation
python3 scripts/heavy.py uv run python -m evals.skill_learning.study build --root "$STUDY_ROOT"
python3 scripts/heavy.py uv run python -m evals.skill_learning.development audit \
  --root "$STUDY_ROOT" --tasks court-form-filling-4
```

空白产物应失败，参考解应通过。人工核对 validation prompt 与 verifier 后，在对应 reliability 目录写 `manual-review.json`，记录 `prompt_consistent`、覆盖范围和局限；未通过此门槛不能运行付费 headroom 对照。官方参考解有额外依赖时，`--references` 可声明仅供 reference control 使用的文件和来源；这些文件不进入模型运行。

`development headroom` 配对运行 vanilla 与人工参考 intervention，每次最多两个 worker；`development run` 用于 history 和 validation 的指定 arm。其命令拒绝 test。运行前应记录余额与 provider；不要在配对组间静默切换 provider。

单元检查不调用模型、不需要 Docker：

```bash
uv run pytest -q evals/skill_learning/tests
```

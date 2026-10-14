# Orbit 历史技能学习与隔离评测

状态：未完成。PR #94 已撤回，替代的 PR #99 于 2026-10-14 关闭、未合并，因为 Orbit·知音停止开发；起点：`5ce95c83`；目标：用可追溯的通用推荐改进验证 held-out 效果。

## 实验边界

- 原 run-003 / run-004 的 24 个已暴露实例只用于开发诊断，不再计为最终 held-out test。
- 所有新实例在查看内容前确定 split；仅训练与 validation 能进入迭代输入。
- 先对 validation 做 vanilla 与 reference intervention 的 headroom 检验，再决定正式任务族。
- Kimi K3 max、Pi memory off；相同任务三组共享模型、镜像、工具、超时和 verifier。
- 最终 test 前冻结代码提交、全部 prompt、split、intervention、参数和运行顺序。此后不使用 test 反馈改动实现或筛题。
- 全部失败、超时、中断、未知 token 和费用均保留；不能通过重试到成功或选择性报告取得优势。

## 阶段与验收

1. 前 2 小时：history→analytics→候选→评分→阈值→去重→兼容→选择→注入→激活→使用的完整漏斗、根因复现和小 validation。
2. 第 3–5 小时：以 validation 为反馈进行 1–2 次通用算法迭代；记录 history 数量、候选类型、阈值、top-k、去重、兼容、trigger 与 skill/bundle 消融。
3. validation 改善后冻结并运行一次正式 test，完整保留三组结果。
4. 跑通数据、分析、推荐端到端及涉及模块检查，提交 ready-for-review PR。

## 必交付证据

- `RESULT_REPORT`：逐实例 ID、任务摘要、family、split、verifier、成功率与配对比较。
- `TOKEN_REPORT`：online/adaptation tokens、tokens/success、费用和缺失计量。
- `POSITIVE_REPORT`：改善案例及推荐到使用的证据链。
- `NEGATIVE_REPORT`：失败、退化、未触发与无效干预。
- `INJECTION_REPORT`：各级候选数、类型、score、来源证据、保留或淘汰原因、最终资产和 runtime 证据。

运行原始数据放在本地忽略目录与外置盘；仓库只保留代码、构造测试、协议和汇总报告。结果是否支持 ours 优于对照组，由冻结后的实测决定。

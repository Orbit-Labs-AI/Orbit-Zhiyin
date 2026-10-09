# Orbit 路线图

状态：草案，待 MVP 确认成员核对。

本页记录 Orbit 做过什么、正在做什么、接下来可能做什么，截至 2026-10-09。范围变化走项目确认程序，MVP 范围由 `yhyfhgs`、`MistyHuang03`、`genius-FXC` 三方确认。

## 已走过的阶段

| 日期 | 阶段 | 主要产出 | 资料 |
| --- | --- | --- | --- |
| 10-01 | 黑客松启动 | 资料总览、12 步开发拆解、Lite／Advanced 前端交互流程、Agent 本地轨迹数据调研、轨迹建模方案 | [资料总览](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/03-%E5%8D%8F%E4%BD%9C/%E9%BB%91%E5%AE%A2%E6%9D%BE/%E5%A4%A7%E5%AE%B6%E5%A5%BD%EF%BC%8C%E8%BF%99%E9%87%8C%E6%98%AFHackathon.md) · [后端-处理流程](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/04-%E6%A8%A1%E5%9D%97%E8%AE%BE%E8%AE%A1/%E6%80%BB%E4%BD%93%E6%9E%B6%E6%9E%84/%E5%90%8E%E7%AB%AF-%E5%A4%84%E7%90%86%E6%B5%81%E7%A8%8B.md) · [前端-交互流程](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/04-%E6%A8%A1%E5%9D%97%E8%AE%BE%E8%AE%A1/%E5%89%8D%E7%AB%AF%E4%B8%8E%E4%BA%A4%E4%BA%92/%E5%89%8D%E7%AB%AF-%E4%BA%A4%E4%BA%92%E6%B5%81%E7%A8%8B.md) |
| 10-01～10-02 | 后端 MVP | 只读 Codex JSONL → 统一事件 → SQLite → 证据分析 → 中文结果与 skill 建议；后端 v0.1 到 v0.13.6，测试 12 项增到 351 项 | [后端版本记录](<../releases/README.md>) · [MVP 计划](<../archive/backend-mvp-plan.md>) |
| 10-02 | 功能映射与分工 | 309 条前端功能映射到 161 个后端 feature，三人分工，定下 M1–M3 | [feature-map](<../archive/plans/feature-map.md>) |
| 10-02 | 分析模块 | 8 个特征族的定义与可认领 TODO；4 族实现与验收；Instruction、Preference／Task 验收 | [分析模块分类](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/04-%E6%A8%A1%E5%9D%97%E8%AE%BE%E8%AE%A1/%E5%88%86%E6%9E%90%E6%A8%A1%E5%9D%97/%E5%88%86%E6%9E%90%E6%A8%A1%E5%9D%97%E5%88%86%E7%B1%BB.md) · [实现与验收](<../audits/feature-families-2026-10-02/cost-time.md>) |
| 10-02～10-03 | 真实数据验证与可靠性审计 | 用 1,895 个真实会话检验能否还原 UI；数据、分析、推荐、导入与集成审计 | [审计与验证记录](<../audits/README.md>) |
| 10-03 | 评测方案 | 12 任务 A/B 精简方案与 8 类 60 项扩展规划；仓库内的过去到未来推荐 Benchmark 与 artificial benchmark | [评测方案](<../archive/plans/benchmark-2026-10-03/paired-proposal.md>) · [后续扩展](<../archive/plans/benchmark-2026-10-03/expanded/README.md>) |
| 10-03 | 界面试用 | 25 条使用观察与截图 | [界面试用反馈](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/01-%E4%BA%A7%E5%93%81/%E7%95%8C%E9%9D%A2%E8%AF%95%E7%94%A8%E5%8F%8D%E9%A6%88.md) |
| 10-04 | 桌面 0.0.4 发布 | 导入、隐私脱敏、分析、推荐、平台与界面错误态排查修复（PR #101） | [版本记录](<../releases/README.md>) |
| 10-05 | 更名 | 组织与项目更名为 Orbit Labs（PR #105–#107） | [版本记录](<../releases/README.md>) |

## 黑客松里程碑（2026-10-02 定）

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| M1 | 跑通真实数据最小闭环 | 待确认 |
| M2 | Advance 主要页面接上真实数据，AI 功能 MVP | 待确认 |
| M3 | 评测与路演 | 待确认 |

来源为 [feature-map](<../archive/plans/feature-map.md>)；10-02 的[真实数据验证](<../archive/plans/real-data-validation.md>)显示 42 个 UI 功能组中 8 个符合、10 个部分符合，可作为判断 M1、M2 完成度的参考。

## 进行中

**历史技能学习与隔离评测**（[计划](<history-skill-learning.md>) · [PR #99](https://github.com/Orbit-Labs-AI/Orbit/pull/99)，待人工审核，勿自动合并）

- 目标：用可追溯的通用推荐改进，验证在 held-out 任务上的效果。
- 隔离：原 run-003／run-004 的 24 个已暴露实例只用于开发诊断；新实例在看内容前先划分，只有训练集和 validation 进入迭代。
- 选族：先在 validation 上做 headroom 检验（候选 6 个族），入选条件是提高成功率，或成功率不降且 online tokens 至少减少 10%。
- 运行条件：Kimi K3 max、Pi memory off、任务无网络；vanilla、ours、llm 三组共用模型、镜像、工具、超时和 verifier。
- 阶段：打通漏斗并复现根因 → 1～2 次通用算法迭代与消融 → 冻结后只跑一次正式 test → 端到端检查并提交待审核 PR；失败、超时和中断全部保留。
- 交付：RESULT、TOKEN、POSITIVE、NEGATIVE、INJECTION 五份报告。撤回前的旧结果已从 `main` 移除，不作为现行结论。

**待处理**：[Issue #104](https://github.com/Orbit-Labs-AI/Orbit/issues/104) AI 报告的纠正计数改用与页面一致的规则；[界面试用反馈](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/01-%E4%BA%A7%E5%93%81/%E7%95%8C%E9%9D%A2%E8%AF%95%E7%94%A8%E5%8F%8D%E9%A6%88.md)尚未逐条分诊。分配见[任务看板](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E5%9B%A2%E9%98%9F/%E4%BB%BB%E5%8A%A1%E7%9C%8B%E6%9D%BF.md)。

## 待决定的方向

[后续方向与决策](<README.md>)列出来源覆盖、分析可信度、推荐效用、原生交付和社区扩展五个方向，以及新提案要写清的内容；这些方向都不代表已承诺的范围或日期。团队早期的畅想和讨论时要先回答的问题见[后续方向与验证问题](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/01-%E4%BA%A7%E5%93%81/%E5%90%8E%E7%BB%AD%E6%96%B9%E5%90%91%E4%B8%8E%E9%AA%8C%E8%AF%81%E9%97%AE%E9%A2%98.md)。

## 下一阶段里程碑

由 `yhyfhgs` 与 MVP 确认成员商定后填写；每个里程碑写清完成标准，任务拆到[任务看板](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E5%9B%A2%E9%98%9F/%E4%BB%BB%E5%8A%A1%E7%9C%8B%E6%9D%BF.md)。

| 里程碑 | 目标与完成标准 | 负责人 | 目标日期 | 状态 |
| --- | --- | --- | --- | --- |
| 待填写 |  |  |  |  |

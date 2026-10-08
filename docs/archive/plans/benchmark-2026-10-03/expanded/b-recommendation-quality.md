---
added: 2026-10-03
---

# B-推荐质量

> 本页是 2026-10-01 至 10-03 的历史方案，文中的“当前”、TODO、测试数量和命令只对当时成立。现行入口：[评测](<../../../../../evals/README.md>)。

[总入口](<overview.md>) · [共同协议](<protocol.md>) · 执行：S2

目标：区分“推荐看起来相关”和“推荐的动作确实有用”，同时评价不干预是否更好。B01–B03 需要真实 action sweep；B04–B06 是互补诊断。

| ID | 优先级 | 实验 / 对照 | 指标与判定 | 当前入口 / 缺口 |
| --- | --- | --- | --- | --- |
| B01 | P0 | 对冻结的每个 plausible action 和 no_intervention 执行相同未来任务 | Regret@1，Top-1 距事后最优效用的差 | `evals.benchmark.score` 已有；必须完整 action sweep |
| B02 | P0 | 同一 sweep 评价冻结 Top-K，主 K=3 | Regret@K、oracle gap、候选集合覆盖；不把事后最优当线上选择能力 | 现有评分含 Top-K；超出候选数时如实报告 |
| B03 | P0 | Top-1 与不干预比较，纳入无需推荐 / 推荐有害样本 | Harm、无需干预时误触发、零推荐比例 | 现有质量评分；另报每个有害案例与证据 |
| B04 | P1 | 独立人工标注 query / problem 与资源相关性，再评排序 | Precision@3、Recall@K、NDCG@K、问题覆盖率、兼容通过率 | `evals.recommendation.replay` / `validation` 是起点；真实标签待补 |
| B05 | P1 | 解释—历史证据—特征—资源动作逐条核对 | 有效引用率、支持该结论的比例、条件遗漏率、严重夸大数 | pipeline / recommendation 测试可复用；语义支持需人工 |
| B06 | P2 | 去重后的曝光—预览—采纳—实际启用—撤销链路 | 各层分母、采纳 / 不适用 / 撤销率、按规则与 surface 分组 | 依赖真实曝光记录；点击和采纳不等于效用 |

## 固定效用与不干预

对一个冻结 sample，`Y(a)` 是同一批未来任务在 10k 等共同预算内的成功率。`a*` 是冻结动作集内事后最优动作；效用平局优先 no_intervention。

- `Regret@1 = Y(a*) − Y(Top1)`。
- `Regret@K = Y(a*) − max(Y(a), a 属于冻结 TopK)`，仅表示候选集合包含了多好的动作。
- Harm 报告被选动作效用低于不干预的样本比例，并补充差值；严格沿用评分器字段口径。
- 无需干预误触发：在 no_intervention 已是最优的样本中，仍选择干预的比例；分母为 0 时为 null。

任何候选动作缺执行、结果未知或环境不一致，oracle / Regret 都保持 unproven，不能只在跑过的赢家之间算“最优”。不得运行后删除效果差的动作。当前默认四个审阅 Skill 的结论只覆盖该目录，不能推广成全网 Skill 排名。

## 标签与已有入口

构造回放检查可用：

```sh
uv run --locked python -m evals.recommendation.replay
uv run --locked python -m evals.recommendation.validation --output .local/benchmark/s2-validation-01
```

这两条命令验证既有回放和构造预期，不执行 B01–B03 的真实任务。人工标签至少区分相关、可执行、预计有用、实际有效；只标了相关性就只算相关性指标。B04 的检索金标与 E01 共用，S5 负责目录端，S2 负责排序决策端，避免重复造标签。

B06 需要稳定曝光 ID 和时间窗；按独立曝光 / 用户 / 规则说明去重方式，不能用按钮点击次数扩大分母。安装失败、未触发和用户主动撤销分别记原因。

## 交付与边界

提交 action_sweep 的执行记录、按样本的效用矩阵、Regret / Harm 表、解释核验表与缺失清单。S2 不修改冻结 Top-K、候选集或收益函数；若确有协议问题，交 S0 修订新研究。A/B 有相同动作也按统一运行登记表领取，不能自行重复跑、再择优保留。

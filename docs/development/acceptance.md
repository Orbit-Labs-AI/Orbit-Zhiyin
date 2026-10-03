# 先验这条链路

后端已能把本地 Codex 记录整理成可回看的证据，独立生成用户画像与瓶颈案卷，再推荐同时匹配两者的资源。CLI 直接展示完整链路，无需接入前端。

在仓库根目录运行：

```sh
.venv/bin/orbit demo --output .local/demo
.venv/bin/orbit demo --output .local/demo --view profile
.venv/bin/orbit demo --output .local/demo --view bottlenecks
.venv/bin/orbit demo --output .local/demo --view process
.venv/bin/orbit evaluate --output .local/evaluation.json
```

先看终端的画像与瓶颈，再看推荐。`profile / bottlenecks / process` 的 JSON 与 Markdown 保存中间副产品，`report.md` 解释最后的建议。可运行 `orbit --db .local/demo/demo.sqlite evidence <证据ID>` 回看原记录。demo 使用虚构数据；自己的记录按 [README](../../README.md) 导入。真实数据与派生报告都留在 `.local/`。

验收时看四件事：

1. 画像能否独立说明任务场景、明确要求与协作过程，统计能否回到原记录。计数不应变成没有依据的人格或效率分数。
2. 瓶颈是否还原同一任务的要求、交付与后续反馈，是否说明缺什么材料。
3. 建议是否同时有画像、卡点和适用资源。输入没有 skill 名称时仍能推导；代码协作、数学讲解、文档写作可通过 `--scene` 分别查看，证据不够时暂不推荐。
4. 读者能否复述重点、依据与下一步，事实和必要条件是否保留。用 [读者对照](../modules/evaluation/reader-review.md) 记录这部分评价。

当前技术验收包括 351 项测试、8 个文字对照、34 个开发场景和 12 个措辞回归场景，均已通过。CI 使用 Python 3.11，本机使用 3.12。独立安装验收需使用最终版本重新跑 CLI，不能用旧版本结果代替。

这些自动案例已经用于修规则，属于回归检查。它们不能证明中文足够自然、用户满意，或推荐的 skill 已有收益。读者评分保持待填写，资源效果保持未测。

想理解推导，先看 [画像说明](../modules/analytics/profiling.md)；继续开发时看 [版本报告](../releases/backend/v0.13.6.md)，再按需要查 [架构](../architecture/backend.md) 与 [数字的含义](../modules/analytics/modeling.md)。

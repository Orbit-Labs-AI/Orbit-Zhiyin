# Orbit 历史技能学习与隔离评测

状态：实施中；起点：`5ce95c83`；目标：用可追溯的通用推荐改进验证 held-out 效果。

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

## 推荐漏斗接口

`GET /v1/recommendations/runs/{run_id}/funnel` 返回该次推荐的诊断记录；旧 run 返回 `status=not_recorded` 与 `funnel=null`。记录保存在现有 `rec_run.diagnostics` 中，不新增 DDL。

- history 项是分析输入的会话数量和 data revision；原始捕获完整性需要由导入验证报告补齐，不能仅凭会话数断言无损。
- analytics 保留问题状态、分母、Wilson 下界及会话证据；召回保留各路数量、原始分数、融合上限和被截断的 ID。
- Catalog `MatchRequest.audit=true` 额外返回 `filter_audit`，说明检索前的类型、Agent、语言、来源与证据过滤。未计算相关性时 score 为 null；每级最多返回 1,000 个被过滤 ID，超出部分明确记录 `omitted_ids`。
- 引擎按评分、兼容、阈值、画像重叠、去重、最终选择记录每个候选的去向。兼容与其他 gate 原本同时计算；漏斗拆分是同一组逻辑条件的展示，不改变执行行为或推荐名额。
- AI 补充候选后的选择及持久化截断另记一层；卡片被压缩或超出保留上限时，漏斗仍保留其来源证据。
- Pi injection、activation、actual usage 由执行器观测，后端未见运行日志时保持 `not_observed`，不能算作 0 或成功。

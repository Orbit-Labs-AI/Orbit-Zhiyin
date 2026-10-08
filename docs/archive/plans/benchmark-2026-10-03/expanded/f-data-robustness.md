---
added: 2026-10-03
---

# F-数据完整性与鲁棒性

> 本页是 2026-10-01 至 10-03 的历史方案，文中的“当前”、TODO、测试数量和命令只对当时成立。现行入口：[评测](<../../../../../evals/README.md>)。

[总入口](<overview.md>) · [共同协议](<protocol.md>) · 执行：S6

目标：保证评测的输入可信、范围正确、来源不被改变。此类多数属于必须通过的工程门禁，不用于宣传“提升多少”。

| ID | 优先级 | 实验 / 样本 | 指标与判定 | 入口或缺口 |
| --- | --- | --- | --- | --- |
| F01 | P0 | 各 connector 原生构造记录 → staging → canonical → 查询 | L0/L1 记账、外键、字段 / 单位、未知类型保留、桥接一致 | connector / data integrity / mapping 测试；TS producer 先构建 |
| F02 | P0 | 同源全量 / 分批 / 无变化重扫 / 顺序变化 / 镜像文件 | logical digest 等价、changed=0、事件与 Token 不重复 | `robustness_native`、incremental / dedup / resume 测试 |
| F03 | P0 | 时间 / 项目 / Agent / root scope、子代理、空范围、迟到标注 | 范围隔离、身份与图端点、证据时间可见性；跨范围污染=0 | `robustness`、scope / canonical boundaries 测试 |
| F04 | P0 | 坏 JSON、截断尾行、未知类型、追加 / 改写 / 删除文件 | 无静默丢弃、partial / changed / missing 正确、恢复后事实一致 | `robustness_faults`；来源不可恢复时如实降级 |
| F05 | P0 | 多导入任务、重复请求、取消 / 崩溃 / 重启、缓存过期 | 无混写 / 脏发布 / 错复用，恢复完整性、失败可见性 | parallel_import / appdb / service supervision / cache 测试 |
| F06 | P0 | 合成密钥、用户名路径、推理、工具全文、取消勾选、未授权来源 | 上下文包及发送端敏感命中=0，未授权输入不进入请求 | `privacy` suite、privacy_rules / security 测试；只用合成秘密 |
| F07 | P1 | 历史 / 资源正文携带指令、伪造证据或冲突身份 | 不把输入当系统指令、不越权、不接收外部伪证据；失败闭合 | 构造注入与证据校验；缺少攻击夹具时补小样本，不执行危险命令 |
| F08 | P0 | AI 调用缓存、重试、超时、失败、取消和多级子调用 | 调用 / Token 账本可追溯、不漏 / 不重复、未知保留；失败不伪装成功 | `ai_ledger`、AI service / usage 相关测试；供应商实测另报 |

## 数据设计与真值

基础数据使用仓库构造器，包含多来源、主 / 子 / review 会话、长工具输出、模型调用、重复参数和失败。人工写出的独立 manifest / 不变量作为真值，不以导入后的行数反向生成预期行数。

目录源路径可能参与 canonical 身份，比较 logical digest 时必须遵守“同一源树”条件；不能把重定位带来的合法身份差异当算法回归。允许忽略的过程字段事先登记，不能看到 diff 后批量删除字段。

来源只读；评测输出写独立新目录。需要真实原生文件的 `robustness_native` 不是单读数据库即可完成，S0 须明确授权已索引文件清单并核验运行前后哈希，不扩大到未启用来源。

## 可复用命令

```sh
pnpm --filter @tandem/connectors build
uv run --locked pytest -q packages/data/tests tests/integration
.venv/bin/python -m evals.analytics.robustness_faults --output .local/benchmark/s6-faults-01
uv run --locked tandem eval run --suite privacy --suite ai_ledger --no-store --json .local/benchmark/s6-suites-01.json
```

已授权已有快照后再运行：

```sh
.venv/bin/python -m evals.analytics.robustness --home /path/to/canonical --output .local/benchmark/s6-robustness-01
.venv/bin/python -m evals.analytics.robustness_native --home /path/to/canonical --output .local/benchmark/s6-native-01
```

这些命令优先验证完整性；规模和墙钟由 S7 统一计时。大量回归会竞争 CPU / I/O，不能与 S7 同机重叠后还把延迟当独占结果。

## 交付与完成条件

交付每个扰动的预期 / 实际 / 差异、来源前后摘要、未知 / 跳过 / 错误计数和恢复记录。F06/F07 共享报告只保留合成样本，不输出真实密钥或原始聊天。关键门禁失败时保留失败并阻止依赖它的 headline，不通过忽略未知记录、补零或静默跳测获得绿灯。

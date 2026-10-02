# 分析与推荐鲁棒性验收

从仓库根使用现有 `.venv` 运行，无需 `uv`。真实输入必须明确提供已有 canonical 数据库目录；所有产物写入新的、忽略的 `.local` 子目录。这些工具不调用模型、不安装或执行 Skill。

```sh
.venv/bin/python -m evals.analytics.robustness --home .local/backend-nine-hour/p0-data --output .local/robustness/run-01
.venv/bin/python -m evals.analytics.robustness_native --home .local/backend-nine-hour/p0-data --output .local/robustness/native-01
.venv/bin/python -m evals.analytics.robustness_faults --output .local/robustness/faults-01
.venv/bin/python -m evals.analytics.robustness_scale --home .local/backend-nine-hour/p0-data --output .local/robustness/scale-01
```

第一条默认以快照最新记录为截止点选取七天；`--from-ts / --until-ts` 可固定 UTC 毫秒范围。原生重建默认使用数据库已启用来源中已索引的文件清单，不扩大来源；未提供截止点时分析整个重建快照。需要比较同一个七天窗口时，两条命令应显式使用同一对时间参数。

每个案例保存八个特征族和每个 Skill 的 `diagnostics.json / diagnostics.txt`、推荐及关系校验；原生案例另存导入与数据库完整性结果。零推荐保持零推荐，缺失环境保持 `needs_context`，历史日志中的效用保持未测量。输出不成功时返回非零，不以已完成的部分案例代表整个运行成功。

## 验收依据

| 级别 | 案例 | 固定预期 |
| --- | --- | --- |
| P0 | 重试注入 | 独立构造失败种子，再增加三个成功重试：已确认重试恰好增加 3，失败数保持不变；推荐信号引用新增证据 |
| P0 | 失败消融 | 删除已知失败调用及其起止事件后，失败计数归零；真人消息、Token、项目和偏好不变 |
| P0 | 顺序与字段 | 反转输入数组、增加无关界面字段、复制相同 canonical 记录，不改变事实或推荐；相同身份的冲突记录显式报错 |
| P0 | 关系校验 | 每种身份按自己的粒度验证：事件来源、真人分母、任务归属边、图端点、推荐信号和证据、时间可见性、Token 守恒 |
| P1 | 全量与增量 | 同一文件清单倒序一次导入、正序分三批导入，各原始／映射／派生逻辑层和分析事实一致 |
| P1 | 幂等 | 相同文件再次导入，changed=0，各逻辑层不变；不修改来源 |
| P1 | 范围与上下文 | 单项目、单主会话、纯子代理、空选择；分析固定时分别改变权限、工具、安装状态及偏好 |
| P2 | 损坏与变化 | 未知类型保留 unknown 事件；坏 JSON 行保留 unparsed；未完成尾行保留在 L0，完成后能重新投影；mtime 变化不制造新事实 |
| P2 | 规模 | 按 20、100、全部原生会话请求，报告实际读入的主／子／review 会话、事件、耗时与进程内存峰值 |
| P3 | 重复稳定性 | 相同输入重复五次（可设 5–10 次），比较事实摘要、推荐摘要与关系校验 |

受控重试写入独立构造 root，且事件明确标记 `fixture_source`；它验证分析计数，不代表真实执行结果或 Skill 收益。关系校验对构造事件明确豁免原生来源回查，其余真实证据仍必须存在 canonical `record_event` 映射。不会把文件数、会话数、任务数混成一个单调漏斗。

全量与增量比较只排除两项预先声明的过程字段：`sessions[].coverage.source_scans.scans[].scanned_at` 与 `indexed_files`。前者是最近扫描的时间，后者是最近一批文件数；原值在差异报告中保留。其他覆盖状态、数量、证据与事实均参与比较。可用原命令加 `--reuse-imports` 对已重建的两个数据库重新分析；会核对原选择范围及全部源文件哈希，不重新导入。

canonical 输入是生产方已按范围重建的快照。改变它的时间、模型、effort 或项目范围时，应重新调用 `CanonicalStore.analysis_bundle(new_scope)`，不能只过滤旧事件、继续使用旧的 L3 元数据。相同身份的重复行只计一次；冲突行不会被任意挑选。任务接口保留“验证 → 产物版本 → 所属产物”的版本关系，不沿共享产物拉入其他任务。

## 人工与环境限制

规则扰动、构造标签和程序自身的输出不能充当独立人工真值。真实语义精度仍需独立人员标注 20–50 个主会话，先固定任务边界、纠正目标、偏好作用域和瓶颈证据，再评估准确率与覆盖率。标注缺失时明确记录待完成，不把其他自动检查通过说成算法精度通过。

完整仓库验收继续执行 [测试指南](testing.md) 中的 `pnpm check`。本地 HTTP 测试需要绑定临时回环端口；Swift XCTest 依赖完整测试环境。这些条件不应通过静默跳过测试来隐藏。推荐的未来效用需要任务开始前 checkpoint 与配对执行，详见后续推荐 Benchmark。

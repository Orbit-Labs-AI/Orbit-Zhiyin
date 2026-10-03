# Orbit 后端深度排查修复

日期：2026-10-04。维护者：`yhyfhgs`。原排查基线为 `e17bcdfe`；修复从最新主线 `5ce95c83` 开始，分支为 `fix/backend-audit-findings`。本轮沿现有服务、数据库和队列修复 12 个已复现问题，没有新增数据表或模型执行通道。

## 修复与回归

| 原报告 | 修复后的行为 | 回归位置 |
| --- | --- | --- |
| B01 特征范围 | 公共画像和搜索入口合并持久排除及默认来源选择；保留显式空选择；画像缓存和资源库 ETag 随隐私范围变化 | [特征可靠性](../../packages/backend/tests/features/test_audit_reliability.py) |
| B02 Hook 脱敏 | 原始 Hook 经统一脱敏后进入派生状态；旧 checkpoint 无新事件也清理；通知写入、SSE 与历史展示均遮蔽凭据 | [Hook](../../packages/backend/tests/realtime/test_realtime_hooks.py)、[通知](../../packages/backend/tests/platform/test_notify.py) |
| B03 清除遗漏 | 清除包含 Hook 事件、轮转历史、checkpoint 与状态文件；存储统计列出实时采集记录 | [清除](../../packages/backend/tests/settings_data/test_wipe.py) |
| B04 AI 日预算 | 每次调用前按单次预算上限预留，所有引擎队列共享预留，实际用量记账后释放；schema 重试同样受控；显式 override 保留 | [AI runner](../../packages/backend/tests/ai/test_runner.py) |
| B05 取消与重试 | 重试等待可被取消打断，每轮发送前重查取消；各轮网络请求共用一个总超时 | [引擎](../../packages/backend/tests/ai/test_engines.py) |
| B06 增量特征 | 签名覆盖特征值和参与计算的工具元数据，发现行数及结束时间不变的修正；版本标记淘汰旧物化与画像缓存 | [特征可靠性](../../packages/backend/tests/features/test_audit_reliability.py) |
| B07 并发构建 | 画像请求等待进行中的物化，不再把部分特征保存为当前版本 | [特征可靠性](../../packages/backend/tests/features/test_audit_reliability.py) |
| B08 安装回滚 | 文件替换前登记撤销信息，目录 fsync 失败时也撤销当前目标；返回无法回滚的目标编号 | [文件应用](../../packages/backend/tests/install/test_applier.py) |
| B09 通知开关 | 通知器通过真实 PlatformSettings 接口读取 flags.notifications | [平台控制](../../packages/backend/tests/platform/test_audit_controls.py) |
| B10 设置竞争 | 用同一锁覆盖读取、补丁合并、数据库提交与内存更新，两个字段的并发修改都保留 | [平台控制](../../packages/backend/tests/platform/test_audit_controls.py) |
| B11 效果范围 | 只有输入覆盖跟踪人群和已结束观察窗口才刷新安装效果；局部筛选或裁剪数据不覆盖完整历史评价 | [效果跟踪](../../packages/backend/tests/recommend/test_rec_outcomes.py) |
| B12 SSE 恢复 | 旧游标高于本进程最大编号时发送重新同步事件并重放当前数据；空流重新同步期间到达的事件也保留 | [事件恢复](../../packages/backend/tests/services/test_event_resume.py) |

## 验证

新增回归使用临时目录、构造数据库、线程同步和模拟引擎/网络。测试不导入真实会话、不调用付费模型、不向原生通知中心发送通知。安装测试在构造配置上注入 fsync 异常，同时验证新建和修改文件的撤销。

定向检查通过：特征 95 项；Hook、清除与通知 23 项；AI 控制 72 项；安装 35 项；平台控制及事件恢复 16 项；推荐效果 21 项。这些分组有交叠，不相加作为独立测试总量。

后端整包最终验证通过：非 serial 用例 3,345 项（`-n 4`），serial 用例 60 项，共 3,405 项。首轮检查发现存储项顺序和资源库 ETag 测试替身两处接入问题，修正后相关模块 92 项复验通过，随后非 serial 整包重跑通过。新增 28 项参数化展开后的回归用例，后端 lint、文档链接和 `git diff --check` 通过。

按当前 AGENTS 的合并门槛，本轮只修改后端实现、其测试和文档，整包测试经 `scripts/heavy.py` 闸门运行；未重复运行无改动的连接器、Swift、UI 和安装包验收。实际命令如下：

```sh
python3 scripts/heavy.py .venv/bin/python -m pytest -q -n 4 -m "not serial" packages/backend/tests
python3 scripts/heavy.py .venv/bin/python -m pytest -q -m serial packages/backend/tests
.venv/bin/ruff check packages/backend/src packages/backend/tests
.venv/bin/python scripts/check-repository.py
git diff --check
```

## 行为边界

预算预留使用现有单次调用预算，是 Orbit 进程内的调用准入控制；实际计价与引擎执行上限仍取决于引擎报告和能力，不能据此宣称服务商账单绝对不会超出估算。缓存命中不产生模型调用，因此不占新的调用预留。

被筛选或被裁剪的页面数据不再更新全局跟踪结果，旧的完整评价保留，直到有覆盖跟踪范围的新数据可用。原生通知显示、真实模型质量和跨进程使用同一数据目录的场景不由这些构造回归证明。

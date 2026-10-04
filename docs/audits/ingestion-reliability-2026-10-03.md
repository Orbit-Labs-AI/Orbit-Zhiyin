# Orbit 会话导入可靠性审计（2026-10-03）

> 文档状态：审计快照。正文保留原基线、日期与证据；其中的状态和数字不代表当前版本。现行入口见[文档导航](../README.md)。


本轮检查 canonical 数据链、七类 Agent mapper、Codex staging connector 和 App 导入日志。阅读仓库实现与构造样本，并执行仅文件元数据的本机发现盘点，不读取真实聊天正文；下表说明当前实现的协议覆盖，不代表已对本机所有已安装版本完成真实数据验收。

## 模块与证据链

`discovery.inputs` 限定已启用来源的文件 → `ImportService` / `parallel` 建立 L1 索引 → `scheduler` / `Store.rebuild` 映射 L2 事件 → `reduce` 形成 L3 会话、轮次、工具调用、模型调用、项目与特征。DDL 权威仍是 `packages/data/src/orbit_data/migrations/`，当前 schema 14；本轮不新增数据库或 DDL。

- L0/L1：`source_file`、`source_revision`、`raw_record`、`record_location`、`file_record` 保留来源身份、版本、行位置和哈希；未知类型进入 unknown/unparsed 记账。
- L2：`event` 与 `record_event` 保留标准事件和来源证据关系，非正文附加字段进入 attrs/ext；正文和脱敏遵循现有契约。
- L3：`session`、`turn`、`tool_call`、`tool_call_event`、`tool_call_file`、`model_call`、`usage_snapshot`、`session_feature` 等由已映射事件派生。未知状态/用量不强行填成功或零。
- TypeScript `packages/connectors` 是 Codex 归档 staging；通过 `bridge` 校验和重新解析进入 canonical 库，不能直接当作 canonical 数据库。

## Agent 覆盖矩阵

| Agent | 当前读取范围 | prompt / response / tool / 日志映射 | 主要边界 |
|---|---|---|---|
| Claude Code | `projects/**/*.jsonl`、subagent meta、custom title；来源发现包含多账户目录及桌面本地 agent 目录 | user/assistant 文本和 reasoning、tool_use/result、SDK result、系统消息、hook、压缩、文件与队列事件、子代理结果 | 特定 UI 记录显式 ignored；未识别类型留 unknown；不读取认证与无关应用日志 |
| Codex | sessions / archived_sessions JSONL 或 zstd、最高版本 state index、title index、import ledger；本轮补根目录内 index 指向的 rollout | response_item、event_msg、工具调用/结果、推理、轮次、权限、分支和子代理元数据；镜像/分支通过证据归并 | index 仅补已启用根目录内的 rollout；不越界读取，也不能从 metadata 恢复缺失正文 |
| DSH | `sessions/**/session*.jsonl[.zstd]`，最新代为 transcript、旧代保留为 legacy | user/system/developer、assistant message/attempt、流片段、tool call/result、request context、retry、结束与控制事件 | 按代选择与折叠有明确记账；不能恢复未写入 session 的进程输出 |
| pi | `sessions/**/*.jsonl` | message、toolCall/toolResult、bashExecution、模型设置、压缩/branch summary、usage、错误/中断 | fork 复制须验证父路径和条目；图片与媒体依赖原始来源而非重新解码全文 |
| Hermes | `state.db`、`profiles/*/state.db`；sessions/messages/model usage/system prompts 表 | 用户/助手内容、tool_calls、工具结果、reasoning、system prompt、rewind/压缩及用量 | 工具结果仅凭显式 exit_code/success/error 判断状态；任意纯文本不猜成功 |
| OpenCode | `opencode*.db`；session/message/part/session_message 表 | V1 message+part、V2 session_message、文本/推理、工具/结果、shell、subtask、压缩和错误 | 存在 V2 时同会话 V1 是显式 ignored；本轮修复 malformed tool 连带丢掉同条正常回答的问题 |
| Kimi | session index、`sessions/*/*/agents/*/wire.jsonl` | wire metadata、append message/loop、text/think、tool call/result、usage、turn prompt/结束、配置 | 保留 agent scope；usage.record 与 step.end 避免重复计数；index 不授予额外路径权限 |

当前 canonical 原生 mapper 未包含 Gemini CLI、Copilot CLI 或 Cursor；HTML 示例中出现其图标或示例会话，不代表这些来源已有原生导入支持。不能把七类覆盖说成本机所有 Agent 全覆盖。

## 本轮修复

1. **Codex index 指向的根内 rollout 漏发现。** Python 原路径只扫描固定目录，TS 已有 index pointer 补扫。现在 Python 只读 `threads.rollout_path`，补充根内文件、去重，拒绝越界和文件符号链接。损坏 index 不阻塞普通目录发现，index 本身仍进入正常捕获失败记账。
2. **短暂读取竞态只能等待下一次完整扫描。** 串行和并行 capture 现在对来源变化、SQLite BUSY/LOCKED、EAGAIN/EINTR/ESTALE 最多额外重试一次，重试重新读取而不复用旧 worker 快照。持续失败仍保留旧事实、报告失败；权限或无效格式不会盲重试。已有 worker 失败降级、投影回滚与下次扫描恢复保持不变。
3. **逐文件详情被 SSE 节流覆盖。** capture 回调增加 relative path、captured/unchanged/failed、attempts；retry 使用独立阶段。App 在 SSE 合并之前写入已有旋转日志：逐文件写入有变化的成功、失败与重试，阶段变化单独记录；未变化文件只在最终 summary 汇总。字段允许列表排除正文和异常 message。中断也输出 summary。
4. **工具 JSON 标量结果变为空文本。** 通用 `text_content` 原先将 `0`、`false` 等标量丢为 `""`；现在保留 JSON 文本，包含嵌套 content/list 的标量。缺失值仍保留缺失语义。
5. **OpenCode V2 一个异常工具块使正常文本/其他工具整条映射失败。** 现在按 block 处理，错误工具块产生 unknown 并保存原 block；正常回答、有效工具及其结果继续映射。助手字符串/单块 content 不再在二次工具遍历中触发 `.get` 错误。mapper version 升至 1.5.2，避免把旧投影误当作当前映射结果。

6. **恢复补采把 worker 启动失败当作成功派发。** `JobService.submit` 会返回 failed job 而不抛异常；恢复采集和后台补采现在识别该结果，保留 catch_up_pending，并沿用失败退避后重试。即使 sync_mode=off，也会继续完成用户明确要求的恢复补采；失败派发不再返回“正在补采”的 job id。
7. **安装后的 inventory 刷新失败无提示。** 安装文件成功但刷新任务派发立即失败时，现在返回 `inventory_refresh_failed` warning，保留真实的安装成功状态。

## 验证

- 新增 `packages/data/tests/test_ingestion_recovery.py`：根内 indexed discovery 与越界拒绝、损坏 index 降级、串行/并行单次重试和持续失败、标量结果、OpenCode 相邻内容保留、多来源同名文件/相同 native id 的身份隔离和重建幂等。
- data 定向链路回归：此前 capture/discovery 改动的 80 项通过；后续 mapper 改动连同 mapping completeness 和 reducer derivation 的 27 项通过。
- 新增 `packages/backend/tests/services/test_import_audit_log.py`：SSE 合并不丢逐文件日志、unchanged 汇总、正文排除与三类重试文案；连同既有 import pipeline 共 11 项通过。
- 后续补采与安装补充回归：collection 10 项通过，install wiring 12 项通过；包括手动模式、连续派发失败、故障退避和 worker 恢复后的补采。
- 最终仓库全量检查由集成任务运行；这里不重复已通过且未受后续改动影响的测试。

## 仍然明确存在的边界

- **索引不是备份。** 原生链默认不复制整段会话，来源删除、改写或无法验证哈希时，查询会明确显示不可用；TS staging 的旧归档兼容是另一个显式入口。
- **完整导入仅针对已启用根目录和已落盘的允许格式。** 未落盘 response、Agent 内部未记录的 reasoning、远端历史、独立进程调试日志、认证数据、任意附件文件和加密正文均不能声称已采齐或可恢复。未知原生类型有证据索引不等于已有语义映射。
- **本轮没有读取真实会话，不能宣称本机零遗漏。** 各 Agent 的新版本字段、损坏日志、缺失会话和自定义安装位置仍须通过允许列表发现结果、unknown/unparsed、capture_errors 与来源状态对照确认。
- 多来源同名路径/相同 native id 已用构造样本验证隔离；同一来源下 Hermes 多 profile / OpenCode 多 channel 如复用了原生 session id，当前身份主要依赖 source+native id，仍可能需要进一步按数据库命名空间区分，不能无证据假设它们一定是副本。本轮未改变该兼容语义。
- 自动重试有界；持续变化文件等待下一次用户重试/监测轮次。旋转日志有固定保留上限，不是无限历史审计数据库。

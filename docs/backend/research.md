# 先借鉴哪些项目

这份记录把“看过源码或文档”和“已经用上”分开。来源核对时间为 2026-10-02；未做真实效果测试的资源不会写成已证实有效。

| 项目 | 核对了什么 | 本次取舍 |
| --- | --- | --- |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness/tree/639ed015397290b3745d163aafe02ffee4aa3f84/packages/client/ui-trajectory) | 轨迹类型、事件到视图的转换、会话边界与调用展示 | 源码以 submodule 固定。借鉴“耐久事件与展示投影分开”，后端暂不移植整套 UI |
| [agentsview](https://github.com/kenn-io/agentsview/blob/ff20a6ec197d17cac3367043eaeea65f9a5c09e3/internal/parser/codex.go) | Codex 事件、消息镜像、父会话重放过滤 | 用作解析参考。已有的 Go 界面不是本次必须依赖的服务 |
| [Codex](https://github.com/openai/codex) | 官方协议目录，以及授权本地日志的实际字段 | 以本机实际格式验证；角色、模型与行号保留，不凭名字猜字段含义 |
| [Humanizer-zh](https://github.com/op7418/Humanizer-zh/blob/f4518a8eab97b8bfebc66a89d34320a89bef6930/SKILL.md) | 中文编辑范围、事实保留和文体适配约束 | 进入试用目录；效果未测 |
| [Humanizer](https://github.com/blader/humanizer/blob/225a6f39ac85f76ee48dbad772ea4abe4ed6c9d8/SKILL.md) | 英文写作中模板表达的检查方法 | 作为英文候选，不默认给中文任务推荐 |
| [Doc Co-Authoring](https://github.com/anthropics/skills/blob/8a1541c4a3ffa5a20a5a91de0dcf3f0bab1d1ef4/skills/doc-coauthoring/SKILL.md) | 背景梳理、结构修改与读者测试三阶段 | 对说明反复修改的场景提供试用；先只建议读者测试，避免套用全部沟通步骤 |
| [Systematic Debugging](https://github.com/obra/superpowers/blob/8ca22dba9a94f28898bbce59f2537ff4d87c747d/skills/systematic-debugging/SKILL.md) | 复现、收集证据、定位原因、修改后验证 | 对有对应协作要求的重复失败候选提供试用；不把预期失败测试直接算作浪费 |

## 为什么暂时只保留这些依赖

流式 JSONL 能避免一次把全部日志展开。SQLite 能支持本地查询、原子更新和证据回看；当前样本规模没有要求引入第二套存储。FastAPI 只承担接口和参数校验。后端的数学计算都能用标准库复现。

三份设计文档提到的 Polars、DuckDB、Parquet、NetworkX、PM4Py、Perfetto、OpenTelemetry、向量表示和高级模型会继续核对，但不因它们出现在方案里就全部装上。第一版实际暴露的问题是语义误判，增加存储或图算法不能解决它。

后续调研覆盖用量工具、代理、skill 生态、MCP、hooks、workflow 和评价框架。每项新增技术必须说明解决哪个实际问题、如何与现有基线对比。

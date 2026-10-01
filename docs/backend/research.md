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
| [AGENTS.md](https://github.com/agentsmd/agents.md/blob/d001185d792eb6402a58e4cbef1c228b309ec25d/README.md) | 项目工作规则的公开格式 | 保留为规则来源；需要明确项目约束证据才有推荐理由 |
| [Claude Code Plugins Directory](https://github.com/anthropics/claude-plugins-official/blob/ab024cdcfa7ca80be204acd4907656ba5a968589/README.md) | 官方与社区插件的目录边界 | 用于理解插件组合，不在首版实现安装器 |
| [MCP Reference Servers](https://github.com/modelcontextprotocol/servers/blob/f46d9578190b476b3501923ea8977d899e8db2cb/README.md) | 工具与数据接入示例 | 数据来源扩大后可作适配参考；本地 JSONL 不需要先接 MCP |
| [Claude Code Hooks Mastery](https://github.com/disler/claude-code-hooks-mastery/blob/052ad1cbd5aeb1ec4a1def22012d1293c6225625/README.md) | hooks 生命周期及事件示例 | 适合未来补采执行信息；当前已有日志，不加后台采集进程 |
| [SWE-bench](https://github.com/SWE-bench/SWE-bench/blob/02e7a74ffd0b707aab73d203fe87bdc7c76afc8e/README.md) | 真实软件问题与可运行验收 | 借鉴固定任务和同一验收；代码修复分数不作为中文可读性排名 |
| [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI/blob/fd48ea6840f5572deb53aeb5657740937ac9daaa/README.md) | 多种 CLI 和模型服务的适配接口 | 用于研究获取边界；首版直接读本地记录，避免引入代理依赖 |
| [ccusage Codex guide](https://github.com/ccusage/ccusage/blob/main/docs/guide/codex/index.md) | 会话与归档来源、模型上下文、父会话重放和未知信息的边界 | 借鉴读取边界；本版不估算费用，避免用未知模型或价格给出错误成本 |

v0.3 的获取命令已通过 GitHub 官方 API 核对上述 10 个资源来源；另外 3 个解析与轨迹项目此前已直接读过源码。获取时核对 Git blob 哈希，同时保存 SHA-256 便于重现。来源版本确定与实际效果确定是两件事：所有候选的收益仍未测。

## 为什么暂时只保留这些依赖

流式 JSONL 能避免一次把全部日志展开。SQLite 能支持本地查询、原子更新和证据回看；当前样本规模没有要求引入第二套存储。FastAPI 只承担接口和参数校验。后端的数学计算都能用标准库复现。

三份设计文档提到的 Polars、DuckDB、Parquet、NetworkX、PM4Py、Perfetto、OpenTelemetry、向量表示和高级模型会继续核对，但不因它们出现在方案里就全部装上。第一版实际暴露的问题是语义误判，增加存储或图算法不能解决它。

## 分析技术的取舍

| 官方资料 | 它能解决什么 | 当前为什么不增加依赖 |
| --- | --- | --- |
| [Polars Lazy API](https://docs.pola.rs/user-guide/concepts/lazy-api/) | 延迟执行、提前过滤和选择列，减少批量计算开销 | 当前实际错误主要是对象、否定和场景误判；先解决输入含义 |
| [DuckDB JSON](https://duckdb.org/docs/current/data/json/overview) | 对 JSON 做 SQL 查询，自动识别部分格式与结构 | Codex 角色、消息镜像与来源排除仍需定制读取；当前 SQLite 查询足够 |
| [PM4Py DFG API](https://pm4py-source.readthedocs.io/en/stable/pm4py.html) | 从事件日志发现直接相继的活动关系 | 相继发生不等于原因；首版已有明确的调用与修改候选，暂不引入完整流程挖掘 |
| [NetworkX DAG longest path](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.dag.dag_longest_path.html) | 对已知的有向无环依赖图计算最长路径 | 现有日志没有充分的依赖标签，不能用时间戳顺序冒充因果边 |
| [Perfetto Trace Processor](https://perfetto.dev/docs/analysis/trace-processor) | 统一轨迹格式与 SQL 分析，也能支持时间线核对 | 借鉴事件与分析视图分开；本次先提供本地事件接口，不加第二套运行服务 |
| [OpenTelemetry Trace API](https://opentelemetry.io/docs/specs/otel/trace/api/) | 标准化 span、父关系与链接 | 适合以后主动采集；不能补出已有日志里缺失的调用关系 |

这些判断是本项目根据实际样本规模与错误作出的取舍，不是对工具效果的否定。出现明确的批量查询或主动采集需求时，再按同一数据与验收比较。

## 评价参考什么

[G-Eval](https://arxiv.org/abs/2303.16634) 提供按标准检查生成文本的研究参考，也讨论评判模型偏好自己生成文本的问题。[MT-Bench / Chatbot Arena 论文](https://arxiv.org/abs/2306.05685) 进一步讨论位置、篇幅、自我偏好等偏差。这意味着不能只让生成报告的模型自评一个总分，就声称读者会满意。

本版先把可核对的事实、推荐条件和明显表达问题单独检查。主次、读者背景、中文语感通过读者复述与对照来评价；对照时隐藏版本名字，改变展示顺序。当前没有真实读者评价或资源收益标签，相关字段保持待确认。

| 官方资料 | 本次借鉴 | 为什么只借流程 |
| --- | --- | --- |
| [Inspect Scorers](https://inspect.aisi.org.uk/scorers.html) | 区分案例目标、输出、检查器和汇总指标 | 目前的字面事实与规则能用本地模块完成，不需要整套模型运行框架 |
| [Langfuse Annotation Queues](https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues) | 专门保存读者评分与评语，并据此校准自动评价 | 先生成本地材料与空白表，没有多人在线标注需求 |
| [Phoenix Datasets](https://arize.com/docs/phoenix/datasets-and-experiments/concepts-datasets) | 固定输入、参考信息和版本，再比较实验 | 本版用内容哈希冻结案例；增加平台不能替代真实阅读判断 |

以上是本项目对现有功能规模的取舍。`reader_eval.py` 已实现材料冻结、顺序互换与标注汇总，尚未取得实际读者标签。

# 后端-处理流程

> 历史来源：本页为2026-10-01 至 10-03 的历史方案，2026-10-07 从团队 Vault 迁入。原位置：`项目/Orbit/后端-处理流程.md`。正文与原有日期、结论保留，仅整理导航和空白；私人会话定位不公开。本文中的“当前”、TODO、测试数量和执行命令仅对原文基线成立，本次没有重新验证，也不自动形成任务或授权。现行入口：[源码文档](<../../../README.md>)。

1. 获取不同agent的本地session记录
	1. 可以参考额度统计以及Proxy反代的开源项目如何对接各种agent以及他们的数据库
2. 数据处理-标准化+存储
	1. 分类
		1. 分项目
		2. ~~分Agent~~
		3. 分模型
	2.
3. 分析模块
	1. 参考dsh的轨迹可视化——加入到hackthon的项目中直接看源码
	2. 数学建模参考[Agent 历史轨迹的个性化建模与瓶颈分析方案](<../../../research/trajectory-modeling/original-modeling-proposal.md>) 和 [Agent轨迹与个性化建模方案](<../../../research/trajectory-modeling/personalization-proposal.md>)，数据处理与分析参考 [agent轨迹数据处理方向与分析工具](<../../../research/trajectory-modeling/processing-methods.md>)，但是可能过于繁杂，先选择最简单必要的方式入手，之后慢慢迭代，达到效果后停止。
4. 前端交互导向

5. 获取github和互联网上的skills、plugins、mcp、hook以及workflow经验
	1. 规则和Prompts
	2. Skills
	3. Plugins插件
	4. MCP接入——有哪些软件
	5. Hooks脚本
	6. Model+Thinking的Benchmark成绩
	7. Workflows经验
6. 索引数据库管理-数据标准化+存储
7. 推荐模块
8. 一键安装模块和内容
9. 前端交互

10. evaluation
	1. 简单测试案例：说人话

11. AI辅助分析
12. AI辅助推荐+AI生成式推荐

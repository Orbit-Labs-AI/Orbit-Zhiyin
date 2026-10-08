# 后端-处理流程

> 本页是 2026-10-01 至 10-03 的历史方案，文中的“当前”、TODO、测试数量和命令只对当时成立。现行入口：[文档导航](<../../../README.md>)。

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
	2. 数学建模参考[Agent 历史轨迹的个性化建模与瓶颈分析方案](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/02-%E7%A0%94%E7%A9%B6/%E8%BD%A8%E8%BF%B9%E5%BB%BA%E6%A8%A1/Agent%20%E5%8E%86%E5%8F%B2%E8%BD%A8%E8%BF%B9%E7%9A%84%E4%B8%AA%E6%80%A7%E5%8C%96%E5%BB%BA%E6%A8%A1%E4%B8%8E%E7%93%B6%E9%A2%88%E5%88%86%E6%9E%90%E6%96%B9%E6%A1%88.md) 和 [Agent轨迹与个性化建模方案](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/02-%E7%A0%94%E7%A9%B6/%E8%BD%A8%E8%BF%B9%E5%BB%BA%E6%A8%A1/Agent%E8%BD%A8%E8%BF%B9%E4%B8%8E%E4%B8%AA%E6%80%A7%E5%8C%96%E5%BB%BA%E6%A8%A1%E6%96%B9%E6%A1%88.md)，数据处理与分析参考 [agent轨迹数据处理方向与分析工具](https://github.com/Orbit-Labs-AI/team-hub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/02-%E7%A0%94%E7%A9%B6/%E8%BD%A8%E8%BF%B9%E5%BB%BA%E6%A8%A1/agent%E8%BD%A8%E8%BF%B9%E6%95%B0%E6%8D%AE%E5%A4%84%E7%90%86%E6%96%B9%E5%90%91%E4%B8%8E%E5%88%86%E6%9E%90%E5%B7%A5%E5%85%B7.md)，但是可能过于繁杂，先选择最简单必要的方式入手，之后慢慢迭代，达到效果后停止。
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

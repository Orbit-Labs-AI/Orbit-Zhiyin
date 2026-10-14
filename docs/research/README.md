# 研究资料

本区是代码直接依据的开发调研：外部源码、日志格式和平台规范的有日期快照，供修改连接器、原生壳或依赖时核对。它们不是 Orbit 的当前能力清单；上游产品、日志格式和链接可能已变化，据此修改代码或作新决策前，核对固定 revision 与当前来源。

- [Agent 会话格式研究](agent-sessions/README.md)：六家 Agent 落盘形态的源码级对比与单家分析，是连接器的依据
- [Apple macOS 指南对照：Orbit 原生壳与 UI](apple-macos-guidelines.md)
- [先借鉴哪些项目](backend-research.md)

竞品与选型、Agent 本地数据的资料调研和轨迹建模属于产品与方法研究，在 TeamHub 的 [Orbit 研究](https://github.com/Orbit-Labs-AI/TeamHub/blob/main/%E9%A1%B9%E7%9B%AE/Orbit/README.md#研究)维护：[竞品分析](https://github.com/Orbit-Labs-AI/TeamHub/blob/main/Archive/%E9%A1%B9%E7%9B%AE/Orbit/03-%E7%A0%94%E7%A9%B6/%E7%AB%9E%E5%93%81%E5%88%86%E6%9E%90.md)、[调研总结](https://github.com/Orbit-Labs-AI/TeamHub/blob/main/Archive/%E9%A1%B9%E7%9B%AE/Orbit/03-%E7%A0%94%E7%A9%B6/%E8%B0%83%E7%A0%94%E6%80%BB%E7%BB%93.md)、[Magpie 与 Langfuse 对比](https://github.com/Orbit-Labs-AI/TeamHub/blob/main/Archive/%E9%A1%B9%E7%9B%AE/Orbit/03-%E7%A0%94%E7%A9%B6/Magpie%E4%B8%8ELangfuse%E8%B0%83%E7%A0%94%E5%AF%B9%E6%AF%94.md)、[十类 Agent 本地轨迹调研](https://github.com/Orbit-Labs-AI/TeamHub/blob/main/Archive/%E9%A1%B9%E7%9B%AE/Orbit/03-%E7%A0%94%E7%A9%B6/%E4%B8%BB%E6%B5%81Agent%E6%9C%AC%E5%9C%B0%E8%BD%A8%E8%BF%B9%E6%95%B0%E6%8D%AE%E8%B0%83%E7%A0%94%E6%8A%A5%E5%91%8A.md)、[轨迹与个性化建模](https://github.com/Orbit-Labs-AI/TeamHub/blob/main/Archive/%E9%A1%B9%E7%9B%AE/Orbit/03-%E7%A0%94%E7%A9%B6/%E8%BD%A8%E8%BF%B9%E5%BB%BA%E6%A8%A1/Agent%E8%BD%A8%E8%BF%B9%E4%B8%8E%E4%B8%AA%E6%80%A7%E5%8C%96%E5%BB%BA%E6%A8%A1%E6%96%B9%E6%A1%88.md)。

每次新研究应记录问题、官方来源或源码版本、观察与推断的区别，以及对 Orbit 的适用边界。既有研究不通过改写时间来假装重新核验。实现入口见[连接器](../modules/data/agent-connectors.md)。返回[文档首页](../README.md)。

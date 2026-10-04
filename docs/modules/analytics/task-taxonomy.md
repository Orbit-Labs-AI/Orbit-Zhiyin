# 任务领域分类

分类只处理确认来自主会话真人的当前请求，返回可解释的多标签候选。它服务任务分布和项目/会话展示，不参与四轴人格打分，也不表示技能水平或兴趣强度。

## 稳定标识

父类与细分类通过 parent_id 关联，前缀不必相同。现有六个兼容父类和细分如下；权威定义在 [taxonomy.py](../../../packages/backend/src/orbit_backend/analytics/task/taxonomy.py)。

| 父类 | 细分 ID 与中文标签 |
| --- | --- |
| software 软件工程 | `software.frontend` 前端开发；`software.backend_api` 后端与 API；`software.testing_debugging` 测试与调试；`software.devops` 部署与运维；`software.database` 数据库工程；`software.architecture` 架构与重构；`software.automation` 脚本与自动化；`software.security` 软件安全；`software.ai_engineering` AI 应用与代理 |
| data_analysis 数据工作 | `data.engineering` 数据获取与清洗；`data.statistics` 统计与数据分析；`data.visualization` 数据可视化；`data.machine_learning` 机器学习与特征工程 |
| writing 写作与文档 | `writing.technical` 技术文档；`writing.research` 研究与学术写作；`writing.content` 内容与通用报告；`writing.translation` 翻译与本地化 |
| design 设计 | `design.ux_ui` 界面与交互设计；`design.visual` 视觉与平面设计；`design.presentation` 演示与排版设计 |
| mathematics 数学 | `math.linear_algebra` 代数与线性代数；`math.calculus` 微积分与分析；`math.probability` 概率与统计理论；`math.discrete` 离散数学与优化理论 |
| education 教育与学习 | `education.lesson_design` 课程与教学设计；`education.tutoring` 知识讲解与辅导；`education.assessment` 作业与学业评测 |

## 规则与输出

去除引用、代码、平台包装和重放后，按当前句的动作、具体短语和上下文词分类。否定、假设、过去状态和偏好声明不直接当作当前任务；歧义词需要上下文，裸技术词列表不够。

每个标签保留规则、术语、上下文、事件和任务身份。按任务去重，同一任务可有多个标签，类别之和可大于任务数。未知不强分“其他”；缺失正文和截断另报覆盖。

分类版本变化可能改变统计，即使稳定 ID 不变也不能直接比较旧分布。构造语料与反例验证规则，真实准确率需要独立标注。任务边界见[Task](task.md)，机器实现和语料随包维护。

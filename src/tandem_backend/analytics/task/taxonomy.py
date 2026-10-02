"""Versioned, deliberately small bilingual vocabularies; labels are rule candidates."""

TAXONOMY_VERSION = "task-taxonomy-v1"
DOMAINS = {
    "software": r"代码|后端|前端|函数|接口|脚本|程序|\b(?:code|api|backend|frontend|python|typescript|bug)\b",
    "mathematics": r"数学|定理|证明|积分|微分|矩阵|\b(?:math|theorem|proof|calculus)\b",
    "data_analysis": r"数据分析|数据集|统计|聚类|特征|\b(?:analytics|dataset|statistics|clustering)\b",
    "writing": r"文档|报告|文章|讲义|教程|\b(?:document|report|readme|essay|tutorial)\b",
    "design": r"界面|排版|配色|海报|\b(?:design|layout|poster|ui)\b",
}
TASK_TYPES = {
    "research": r"调研|检索|搜索|查找|\b(?:research|search|investigate)\b",
    "create": r"编写|撰写|创建|生成|实现|开发|(?:^|请|再|然后|现在)写|\b(?:write|create|implement|build)\b",
    "modify": r"修改|改写|调整|重构|完善|\b(?:modify|revise|refactor|update)\b",
    "debug": r"修复|排查|调试|\b(?:fix|debug|troubleshoot)\b",
    "test": r"测试|验证|验收|\b(?:test|verify|validate)\b",
    "explain": r"解释|讲解|说明|推导|证明|\b(?:explain|derive|prove)\b",
    "translate": r"翻译|\btranslate\b",
    "summarize": r"总结|概括|归纳|\bsummari[sz]e\b",
}

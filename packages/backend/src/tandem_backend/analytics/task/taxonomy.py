"""Auditable bilingual domain rules; labels are observations, never personality scores."""

import re

TAXONOMY_VERSION = "task-taxonomy-v2.2"
DOMAIN_LABELS = {
    "software": "软件工程", "mathematics": "数学", "data_analysis": "数据工作",
    "writing": "写作与文档", "design": "设计", "education": "教育与学习",
}
# Broad labels remain API-compatible. Ambiguous words (matrix, test, report, UI,
# proof) are not sufficient to establish a specialized subdomain by themselves.
DOMAINS = {
    # v2.2: everyday repository/tooling vocabulary (audit B8: PR/依赖/Swift/review requests had no domain).
    "software": r"代码|后端|前端|函数|接口|脚本|程序|软件|仓库|分支|依赖|编译|解析器|按钮|登录页|代码审查"
                r"|特性开关|特征开关|功能开关"
                r"|模块|重构|构建"
                r"|\b(?:code|api|backend|frontend|python|typescript|bug)\b"
                # ASCII-only boundaries: \b fails between CJK and Latin ("这个PR合并").
                r"|(?<![A-Za-z0-9])(?:javascript|git|commits?|prs?|pull\s+requests?|merge\s+requests?"
                r"|repo(?:sitory)?|branch(?:es)?|dependenc(?:y|ies)|compile[rsd]?|swift(?:ui)?|rust|kotlin"
                r"|java|node(?:\.js)?|npm|pnpm|diff|ci|parser|build|feature\s+flags?)(?![A-Za-z0-9])",
    "mathematics": r"数学|定理|积分|微分(?!谱|截面)|线性代数|\b(?:mathematics|math|theorem|calculus)\b",
    # Bare 特征 is ambiguous (特征开关 = feature flag); 特征工程/特征提取 stay in data.machine_learning.
    "data_analysis": r"数据分析|数据集|统计|聚类|\b(?:analytics|dataset|statistics|clustering)\b",
    "writing": r"文档|报告|文章|讲义|教程|\b(?:document|report|readme|essay|tutorial)\b",
    "design": r"界面|排版|配色|海报|\b(?:design|layout|poster|ui)\b",
    "education": r"批改|作业|试卷|学号|讲义|\b(?:grading|homework|exam)\b",
}

_SOFTWARE_CONTEXT = r"代码|程序|软件|接口|前端|后端|函数|构建|测试用例|\b(?:code|software|api|frontend|backend|function|build|unit\s+tests?|regression)\b"
_MATH_CONTEXT = r"数学|代数|定理|推导|行列式|特征值|求逆|\b(?:math|algebra|theorem|eigenvalues?|determinant|inverse)\b"


def _rule(label, parent, direct, contextual=None, context=None):
    return {"label": label, "parent_id": parent, "direct": direct,
            "contextual": contextual, "context": context}


DOMAIN_DETAILS = {
    "software.frontend": _rule("前端开发", "software", r"前端|响应式页面|浏览器组件|\b(?:frontend|front-end|svelte|next\.js|css|html)\b", r"\b(?:react|vue)\b", r"组件|网页|页面|前端|\b(?:component|page|frontend|front-end|app)\b"),
    "software.backend_api": _rule("后端与 API", "software", r"后端|接口|服务端|\b(?:backend|back-end|api|restful|graphql|fastapi|django|webhook|endpoint)\b"),
    "software.testing_debugging": _rule("测试与调试", "software", r"调试|排查.{0,8}(?:错误|崩溃|异常)|单元测试|集成测试|回归测试|端到端测试|测试用例|\b(?:pytest|jest|vitest|debug|debugging|unit\s+tests?|integration\s+tests?|regression\s+tests?|end-to-end\s+tests?)\b", r"修复|测试|\b(?:test|tests|fix|bug)\b", _SOFTWARE_CONTEXT),
    "software.devops": _rule("部署与运维", "software", r"持续集成|持续交付|部署|容器编排|服务器运维|\b(?:devops|docker|kubernetes|k8s|ci/cd|github\s+actions|deployment|deploy)\b"),
    "software.database": _rule("数据库工程", "software", r"数据库|数据表迁移|查询索引|\b(?:database|sql|sqlite|postgres(?:ql)?|mysql|redis)\b"),
    "software.architecture": _rule("架构与重构", "software", r"软件架构|系统架构|模块拆分|依赖注入|\b(?:refactor(?:ing)?|microservices?|software\s+architecture)\b", r"重构|架构|\barchitecture\b", _SOFTWARE_CONTEXT),
    "software.automation": _rule("脚本与自动化", "software", r"脚本|命令行|批处理|\b(?:script|scripting|cli|powershell|bash|shell\s+script)\b", r"自动化|\bautomation\b", _SOFTWARE_CONTEXT),
    "software.security": _rule("软件安全", "software", r"安全漏洞|身份认证|权限控制|密钥管理|\b(?:authentication|authorization|vulnerability|oauth|xss|csrf)\b", r"安全|\bsecurity\b", _SOFTWARE_CONTEXT),
    "software.ai_engineering": _rule("AI 应用与代理", "software", r"智能体|子代理|大模型|提示词|向量检索|\b(?:llm|agentic|ai\s+agents?)\b", r"\b(?:rag|mcp|prompt|agents?)\b", r"软件|代码|模型|工具|协议|智能体|子代理|\b(?:ai|llm|model|server|client|retrieval|tool|vector)\b"),
    "data.engineering": _rule("数据获取与清洗", "data_analysis", r"数据清洗|数据采集|数据获取|数据管道|数据导入|数据抽取|数据仓库|\b(?:etl|data\s+(?:pipeline|ingestion|cleaning|warehouse)|web\s+scraping)\b"),
    "data.statistics": _rule("统计与数据分析", "data_analysis", r"数据分析|统计分析|描述统计|统计.{0,10}(?:个数|数量|时间|次数)|聚合|分组统计|\b(?:analytics|data\s+analysis|statistical\s+analysis|descriptive\s+statistics|aggregation)\b"),
    "data.visualization": _rule("数据可视化", "data_analysis", r"数据可视化|散点图|柱状图|折线图|热力图|直方图|转移矩阵|\b(?:data\s+visuali[sz]ation|scatter\s*plot|histogram|heatmap|bar\s+chart|line\s+chart|transition\s+matrix)\b"),
    "data.machine_learning": _rule("机器学习与特征工程", "data_analysis", r"机器学习|特征工程|特征提取|模型训练|聚类|分类器|回归模型|降维|\b(?:machine\s+learning|feature\s+(?:engineering|extraction)|clustering|classifier|regression\s+model|pca)\b"),
    "writing.technical": _rule("技术文档", "writing", r"技术文档|接口文档|开发文档|使用说明|安装指南|教程|\b(?:readme|technical\s+(?:documentation|writing)|api\s+docs?|tutorial|installation\s+guide)\b"),
    "writing.research": _rule("研究与学术写作", "writing", r"论文|文献综述|研究报告|学术写作|\b(?:research\s+paper|literature\s+review|academic\s+writing|thesis|dissertation)\b"),
    "writing.content": _rule("内容与通用报告", "writing", r"报告|文章|文案|博客|\b(?:report|essay|copywriting|blog|article)\b"),
    "writing.translation": _rule("翻译与本地化", "writing", r"翻译|本地化|\b(?:translat(?:e|ion)|locali[sz]ation)\b"),
    "design.ux_ui": _rule("界面与交互设计", "design", r"交互设计|界面设计|界面配色|用户流程|交互原型|\b(?:ui\s+design|ux|wireframe|user\s+flow|interaction\s+design)\b", r"\bui\b|界面", r"设计|配色|布局|交互|\b(?:design|color|layout|interaction)\b"),
    "design.visual": _rule("视觉与平面设计", "design", r"海报|图标|标志设计|配色方案|插画|品牌视觉|\b(?:poster|logo|illustration|graphic\s+design|color\s+palette)\b"),
    "design.presentation": _rule("演示与排版设计", "design", r"幻灯片|演示文稿|演示设计|排版|\b(?:slide\s+deck|presentation\s+design|powerpoint|typography|typesetting)\b"),
    "math.linear_algebra": _rule("代数与线性代数", "mathematics", r"线性代数|特征值|行列式|矩阵求逆|多项式|方程组|\b(?:linear\s+algebra|eigenvalues?|determinant|polynomial|matrix\s+inverse)\b", r"矩阵|\bmatrix\b", _MATH_CONTEXT),
    "math.calculus": _rule("微积分与分析", "mathematics", r"微积分|积分|微分(?!谱|截面)|数学极限|导数|\b(?:calculus|integral|differentiat(?:ion|e)|derivative)\b"),
    "math.probability": _rule("概率与统计理论", "mathematics", r"概率论|概率分布|贝叶斯定理|随机变量|\b(?:probability\s+(?:theory|distribution)|bayes\s+theorem|random\s+variable)\b"),
    "math.discrete": _rule("离散数学与优化理论", "mathematics", r"离散数学|图论|组合数学|数论|凸优化|\b(?:discrete\s+math|graph\s+theory|number\s+theory|combinatorics|convex\s+optimization)\b"),
    "education.lesson_design": _rule("课程与教学设计", "education", r"教案|教学设计|课程大纲|讲义|\b(?:lesson\s+plan|curriculum|syllabus|lecture\s+notes)\b"),
    "education.tutoring": _rule("知识讲解与辅导", "education", r"辅导|教学|给学生讲解|初学者|\b(?:tutor(?:ing)?|teach|beginner|student\s+explanation)\b"),
    "education.assessment": _rule("作业与学业评测", "education", r"批改|作业|试卷|试题|学号|\b(?:grading|homework|exam|quiz)\b"),
}

TASK_TYPES = {
    "research": r"调研|检索|搜索|查找|\b(?:research|search|investigate)\b",
    # "build" is a noun in "why the build fails": only the imperative / "build a|me|new ..." form creates.
    "create": r"编写|撰写|创建|生成|实现|开发|增加|添加|新增|(?:^|请|再|然后|现在)写|(?:请|帮我|需要你|希望你)\s*(?:给|为)[^，,。.!！？?\n]{1,24}写"
              r"|\b(?:write|create|implement|add)\b|^(?:please\s+)?build\b|\bbuild\s+(?:a|an|me|us|new|out|up)\b",
    "modify": r"修改|改写|调整|重构|完善|优化|去除|删除|\b(?:modify|revise|refactor|update|remove|delete|optimi[sz]e)\b",
    "debug": r"修复|排查|调试|\b(?:fix|debug|troubleshoot)\b",
    "test": r"测试(?!字段|数据|报告|题|卷|成绩|分数|用例|结果)|验证|验收|\b(?:tests?(?!\s+(?:report|results?|data|cases?|scores?)\b)|verify|validate)\b",
    "explain": r"解释|讲解|说明|介绍(?!信)|推导|证明|\b(?:explain|describe|introduce|derive|prove)\b",
    "analyze": r"分析|统计|可视化|\b(?:analy[sz]e|visuali[sz]e|count)\b",
    "design": r"设计|\bdesign\b",
    "translate": r"翻译|\btranslate\b",
    "summarize": r"总结|概括|归纳|\bsummari[sz]e\b",
    "grade": r"批改|评分|\b(?:grade|grading)\b",
    "publish": r"上传|发布|部署|\b(?:upload|publish|deploy)\b",
    "review": r"审查|评审|审阅|代码审查|\b(?:review|code\s+review)\b",
    "configure": r"配置|安装|设置(?!了)|\b(?:configure|install|set\s+up|setup)\b",
    "git": r"提交代码|合并(?:分支|代码|PR)|(?:PR|分支).{0,4}合并|推送(?:到|代码)?|变基|\b(?:commit|merge|push|rebase|cherry-pick)\b",
}


def domain_matches(clause):
    """Return broad IDs and detailed rule evidence for a retained request clause.

    A hit is binary per label and task. Repetition does not increase a score.
    Contextual short/ambiguous terms require an independent domain anchor.
    """
    details = []
    for identifier, rule in DOMAIN_DETAILS.items():
        direct = list(re.finditer(rule["direct"], clause, re.I))
        contextual = (list(re.finditer(rule["contextual"], clause, re.I))
                      if rule["contextual"] else [])
        context = re.search(rule["context"], clause, re.I) if rule["context"] else None
        matches = direct or (contextual if context else [])
        if not matches:
            continue
        details.append({"id": identifier, "label": rule["label"],
                        "parent_id": rule["parent_id"], "parent_label": DOMAIN_LABELS[rule["parent_id"]],
                        "rule_id": f"{TAXONOMY_VERSION}:{identifier}",
                        "matched_terms": sorted({match.group(0) for match in matches}),
                        "match_basis": "specific_phrase" if direct else "term_with_context",
                        "context_term": context.group(0) if context and not direct else None})
    parents = {d["parent_id"] for d in details}
    parents.update(label for label, pattern in DOMAINS.items() if re.search(pattern, clause, re.I))
    return sorted(parents), details

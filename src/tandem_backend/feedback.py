"""Identify the target of a requirement before treating it as profile evidence.

'Short code' is a code requirement, not a preference for short answers.
Signals describe observations; repeat requests do not establish stable personality.
"""

import re
from dataclasses import asdict, dataclass, field

from .content import merge_length_contracts
from .models import Event

RULES = {
    "clarity": ("把说明讲清楚", r"说人话|易读|易懂|简洁直接|逻辑清晰|通俗|讲清楚|直观|朴素|看不懂|没看懂|难理解|明确思路"),
    "brevity": ("说明简洁些", r"简洁|简短|不要啰嗦|太长|精简|少[一一点]*细节|(?:一|两|三|\d+)段话|\d+字(?:以内|内)"),
    "grounding": ("说明判断依据", r"(?:给出|附上|提供|列出).{0,6}(?:证据|来源|出处)|注明.{0,6}(?:来源|出处)|引用来源|说明.{0,6}依据|有依据|不要编|真实性|不要想当然|不要猜|核对事实"),
    "actionability": ("把要求落实为结果", r"直接[修做改]|跑通|可运行|具体步骤|怎么[做用]|实现|继续执行"),
    "autonomy": ("减少反复确认", r"不要[再]*问|直接完成|自主.{0,4}(?:完成|执行|处理|推进|决定)|不用[再]*确认|不[用需要]*[再]*问我"),
    "planning": ("先理清方案", r"先[想讲说给]*[一一下]*方案|先规划|先[做给]*计划|思考规划|分步"),
    "verification": ("完成后检查", r"测试|验收|跑通|检查.{0,10}(?:代码|运行|结果)|验证.{0,10}(?:代码|运行|结果)"),
    "scope": ("保持范围集中", r"先做最[小简]|不要[再]*[增扩]|只[改做]|MVP|最小.{0,6}(?:版本|范围|原型)|不要重构"),
}
WRITING = re.compile(r"说人话|说明|讲清楚|解释|回答|表达|报告|文档|文章|语言|教程|注释|讲义|证明|思路|方案|策略|解答|读者|学生")
CODE = re.compile(r"代码|函数|模块|架构|重构|bootstrap|脚本|算法|实现|字段|参数|属性|变量|文件名|命名")
VISUAL = re.compile(r"画图|绘图|图像|图片|坐标|图表|界面|pdf.*高度|窗口|颜色|字体|看不清楚|排版|换行|居中|页面", re.I)
LANGUAGE = r"(?:英文|英语|English|中文|汉语)"
LANGUAGE_VERBS = r"(?:用|使用|写|改成|改为|输出|生成|提供|翻译成|翻译为|给出)"
LANGUAGE_QUANTITY = r"\s*(?:一(?:份|篇|个|段|版|套)\s*)?"
SCENE_LABELS = {"math_explanation": "数学讲解", "developer_report": "开发说明与报告",
                "document": "文档写作", "coding": "代码协作", "conversation": "一般对话"}


def is_followup(text: str) -> bool:
    """Carry task context only for a short, explicit continuation in the same session."""
    continuation = re.search(r"^(?:好的?[，。\s]*)?(?:继续|再|更|这|上一|补|精简|没看懂|看不懂|请再|请继续|请改|改成)", text.strip())
    revision = re.search(r"把(?:语言|说明|正文).{0,8}改|我觉得.{0,10}(?:增加|补充|修改|调整)", text)
    return len(text) < 160 and bool(continuation or (revision and WRITING.search(text)))


def reader_context(text: str, event_id: str) -> list[dict]:
    """Task readers are explicit requirements, not claims about the user's identity."""
    rules = [("first_year_student", "大一学生", r"大一学生|大学一年级|大学新生"),
             ("beginner", "初学者", r"初学者|零基础(?:的读者|的人)?|入门读者"),
             ("developer", "项目开发者", r"(?:给|让|面向|读者是).{0,8}(?:开发者|工程师)|开发者易读"),
             ("general_reader", "非专业读者", r"非专业读者|普通读者|不了解背景的读者")]
    readers = []
    for key, label, pattern in rules:
        match = re.search(pattern, text)
        if not match:
            continue
        prefix = text[max(0, match.start() - 12):match.start()]
        if re.search(r"不是|并非|不要面向|不针对|不用面向", prefix):
            continue
        # A mentioned person's background alone does not define the requested reader.
        if not WRITING.search(text) or not re.search(r"给|让|面向|读者|讲|写|解释", text):
            continue
        readers.append({"id": key, "label": label, "evidence_id": event_id,
                        "quote": _quote(text, match.start(), match.end())})
    return readers


def scene_of(text: str) -> str:
    if re.search(r"数学|定理|证明|推导|不动点|微分|积分|矩阵|数分|SPADE", text, re.I):
        return "math_explanation"
    if re.search(r"报告|项目进度|完成度|README|开发说明", text, re.I):
        return "developer_report"
    if re.search(r"文档|文章|讲义|教程|方案", text):
        return "document"
    if re.search(r"代码|函数|测试|bug|运行|实现|后端|算法|架构|模块|接口", text, re.I):
        return "coding"
    return "conversation"


def _clean(text: str) -> str:
    # Filenames may contain '精简版' or '验证'; they are not semantic observations.
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", lambda m: "文档" if re.search(r"\.(?:md|tex|docx)\b", m[1]) else "文件", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"[“\"][^”\"]*[”\"]", "", text)
    text = re.sub(r"(?:C\+\+|C|Python|JavaScript|Matlab|编程)\s*语言", "编程代码", text, flags=re.I)
    return text


def _context_text(text: str) -> str:
    """A filename can identify a subject, but never establishes a writing preference."""
    return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)


def _writing_target(text: str, start: int, end: int) -> bool:
    # Do not borrow '教程' from the next clause to interpret '代码保持简洁'.
    delimiters = "，,。；;\n"
    left = max(text.rfind(c, 0, start) for c in delimiters) + 1
    rights = [text.find(c, end) for c in delimiters if text.find(c, end) >= 0]
    right = min(rights) if rights else len(text)
    local = text[max(left, start - 32):min(right, end + 24)]
    if VISUAL.search(local) and not re.search(r"解释|正文|句子|表达|说明|语言", local):
        return False
    if CODE.search(local) and not re.search(r"解释|说明|注释|语言|讲清楚|回答|教程", local):
        return False
    if text[start:end] == "精简" and re.search(r"小节|题目|\d+道题", local):
        return False
    context = text[max(0, start - 80):min(len(text), end + 60)]
    if VISUAL.search(context) and not re.search(r"解释|正文|句子|表达|说明|语言", local):
        return False
    if len(text) < 100 and not CODE.search(text) and not VISUAL.search(text):
        return True  # A short direct reply implicitly refers to the explanation.
    return bool(WRITING.search(local)) or bool(WRITING.search(context)) or text[start:end] in ("说人话", "看不懂", "没看懂", "不要啰嗦")


def explicit_language(text: str) -> str | None:
    """The language of a user's message can differ from the requested deliverable."""
    text = _clean(text)
    text = re.sub(r"(?:不要|别|不用|不是让你)\s*" + LANGUAGE_VERBS + "?" + LANGUAGE_QUANTITY + LANGUAGE, "", text, flags=re.I)
    explicit = list(re.finditer(LANGUAGE_VERBS + LANGUAGE_QUANTITY + LANGUAGE + "|" + LANGUAGE + r"(?:版|版本|的?(?:回答|报告|解释|文档))", text, re.I))
    explicit = [m for m in explicit if not re.match(r"\s*(?:API|SDK|字段|单词|术语|字样)", text[m.end():], re.I)]
    if explicit:
        return "zh" if re.search(r"中文|汉语", explicit[-1][0]) else "en"
    return None


def language_of(text: str) -> str:
    return explicit_language(text) or ("zh" if re.search(r"[\u4e00-\u9fff]", _clean(text)) else "en")


def _requirement_target(text: str, match: re.Match, dimension: str) -> bool:
    """Separate an instruction from a negated instruction or a discussion topic."""
    left = max(text.rfind(c, 0, match.start()) for c in "，,。；;\n") + 1
    prefix = text[max(left, match.start() - 24):match.start()]
    after = text[match.end():match.end() + 16]
    if re.search(r"(?:不要|不用|无需|不必|别|并非|不是)[^，。；;\n]{0,6}$", prefix):
        return False
    topic = bool(re.search(r"解释|介绍|科普|概念|定义|是什么|分析|怎么|如何", prefix))
    execution = bool(re.search(r"(?:请|先|再|然后|接着|并|直接|帮我|需要|要|务必|记得|完成后|最后|做|进行|执行|运行|跑|补充|添加|增加|编写|写|加入)[^，。；;\n]{0,8}$", prefix))
    if dimension == "actionability" and match[0] == "实现":
        if re.match(r"原理|机制|方式|方法|过程|细节", after) or topic:
            return False
        if not execution and match.start() != left:
            return False
    if dimension == "verification":
        if topic or (match[0] == "测试" and re.match(r"驱动|数据|集|结果|报告|范围|覆盖|失败|成功|为什么|如何|的(?:概念|定义|原理)", after)):
            return False
        if not execution and match.start() != left:
            return False
    if dimension == "scope" and match[0].upper() == "MVP":
        if topic or re.match(r"\s*(?:是什么|是啥|的?(?:概念|含义|意思))", after):
            return False
    return True


def _quote(text: str, start: int, end: int) -> str:
    # Keep whole clauses, and remove noisy link targets from the preview.
    boundaries = "。！？；\n"
    left = max([text.rfind(c, 0, start) for c in boundaries]) + 1
    rights = [text.find(c, end) for c in boundaries if text.find(c, end) >= 0]
    right = min(rights) + 1 if rights else len(text)
    sentence = text[left:right].strip()
    if len(sentence) <= 240:
        return sentence
    return text[max(left, start - 70):min(right, end + 120)].strip() + "…"


@dataclass
class Signal:
    dimension: str
    label: str
    category: str
    event_id: str
    session_id: str
    turn_id: str | None
    timestamp: str | None
    quote: str
    target: str = "workflow"
    scene: str = "conversation"
    rule_version: str = "rules-v6"
    readers: list[dict] = field(default_factory=list)
    output_contract: dict | None = None
    output_contracts: list[dict] = field(default_factory=list)
    language: str = "zh"
    language_evidence_id: str | None = None
    language_basis: str = "message_language"

    def to_dict(self) -> dict:
        return asdict(self)


def task_contexts(events: list[Event]) -> dict[str, dict]:
    """Resolve task context without changing the original normalized events."""
    current: dict[str, dict] = {}
    by_event = {}
    for event in sorted(events, key=lambda e: (e.session_id, e.ordinal)):
        if event.kind != "user_message":
            continue
        text = _clean(event.text)
        scene = scene_of(_context_text(event.text))
        readers = reader_context(text, event.id)
        requested_language = explicit_language(text)
        language = requested_language or language_of(text)
        language_evidence_id = event.id
        language_basis = "explicit_request" if requested_language else "message_language"
        if is_followup(text) and event.session_id in current:
            previous = current[event.session_id]
            if scene in ("conversation", previous["scene"]):
                scene = previous["scene"]
                readers = readers or previous["readers"]
                language = requested_language or previous["language"]
                if not requested_language:
                    language_evidence_id = previous["language_evidence_id"]
                    language_basis = previous["language_basis"]
        context = {"scene": scene, "readers": readers, "language": language,
                   "language_evidence_id": language_evidence_id, "language_basis": language_basis}
        current[event.session_id] = context
        by_event[event.id] = context
    return by_event


def signals(events: list[Event], context_by_id: dict | None = None) -> list[Signal]:
    output = []
    context_by_id = task_contexts(events) if context_by_id is None else context_by_id
    for event in sorted(events, key=lambda e: (e.session_id, e.ordinal)):
        if event.kind != "user_message":
            continue
        text = _clean(event.text)
        text = re.sub(r"(?:不是|并非|没有|不算)[^，。；\n]{0,10}(?:看不懂|不满意|太长)", "", text)
        context = context_by_id[event.id]
        for dimension, (label, pattern) in RULES.items():
            matches = list(re.finditer(pattern, text, re.I))
            matches = [m for m in matches if _requirement_target(text, m, dimension)]
            if dimension in ("clarity", "brevity"):
                matches = [m for m in matches if _writing_target(text, m.start(), m.end())]
            if not matches:
                continue
            candidates = []
            for match in matches:
                left = max(text.rfind(c, 0, match.start()) for c in "，,。；;\n") + 1
                ends = [text.find(c, match.end()) for c in "，,。；;\n" if text.find(c, match.end()) >= 0]
                clause = text[left:min(ends) if ends else len(text)]
                category = "request"
                if dimension in ("clarity", "brevity", "grounding") and re.search(r"看不懂|没看懂|不满意|(?:你|这[次份段]|还是|又).{0,10}太长", clause):
                    category = "correction"
                elif dimension in ("clarity", "brevity", "grounding") and re.search(r"继续修改|据此改进|改写|重写|上一[版轮]|你刚才|更[加]*.{0,5}(?:直观|朴素|易读)", clause):
                    category = "refinement"
                candidates.append((category, match))
            # One event supports each dimension once; choose its strongest feedback
            # rather than letting an opening request hide a later explicit correction.
            rank = {"request": 0, "refinement": 1, "correction": 2}
            category, match = max(candidates, key=lambda item: rank[item[0]])
            quote = _quote(text, match.start(), match.end())
            contracts = merge_length_contracts(text, [(m.start(), m.end()) for m in matches]) if dimension == "brevity" else []
            primary_contract = next((c for c in contracts if c["char_limit"] is not None), contracts[0] if contracts else None)
            output.append(Signal(dimension, label, category, event.id, event.session_id,
                                 event.turn_id, event.timestamp, quote,
                                 "communication" if dimension in ("clarity", "brevity", "grounding") else "workflow",
                                 context["scene"], readers=context["readers"],
                                 output_contract=primary_contract, output_contracts=contracts,
                                 language=context["language"], language_evidence_id=context["language_evidence_id"],
                                 language_basis=context["language_basis"]))
    return output

"""Identify the target of a requirement before treating it as profile evidence.

'Short code' is a code requirement, not a preference for short answers.
Signals describe observations; repeat requests do not establish stable personality.
"""

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote, urlsplit

from .content import UPPER_BOUND_PATTERN, merge_length_contracts
from .models import Event

RULES = {
    "clarity": ("把说明讲清楚", r"说人话|易读|易懂|简洁直接|逻辑清晰|通俗|讲清楚|直观|朴素|看不懂|没看懂|难理解|明确思路"),
    "brevity": ("说明简洁些", r"简洁|简短|不要啰嗦|太长|精简|少[一一点]*细节|(?:一|两|三|\d+)段话|" + UPPER_BOUND_PATTERN),
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
LANGUAGE_VERBS = r"(?:使用|用|写|改成|改为|输出|生成|提供|翻译成|翻译为|给出|给我|保留)"
LANGUAGE_QUANTITY = r"\s*(?:一(?:份|篇|个|段|版|套)\s*)?"
NEGATION = r"(?:不要|不用|无需|不必|(?<!分)(?<!特)别|不需要|不是让你|并非|不是)"
NEW_TOPIC = re.compile(r"新(?:的)?(?:数学)?(?:任务|定理|问题|主题|报告|文档|接口|教程|证明)|另(?:外)?一个(?:任务|问题|主题|定理|项目)|换(?:一个|个)(?:任务|主题)|下一(?:道|个)(?:题|问题)")
SCENE_LABELS = {"math_explanation": "数学讲解", "developer_report": "开发说明与报告",
                "document": "文档写作", "coding": "代码协作", "conversation": "一般对话"}


def starts_new_subject(text: str) -> bool:
    """A different subject breaks continuity; a new example/version can refine it."""
    if NEW_TOPIC.search(text):
        return True
    for match in re.finditer(r'另(?:外)?一个|新的', text):
        following = text[match.end():]
        if re.match(r'例子|版本|角度|表述|方式|方法|比喻|解释|说法|思路', following):
            continue
        left = max(text.rfind(c, 0, match.start()) for c in '，,。；;\n') + 1
        prefix = text[left:match.start()]
        if re.search(r'用|采用|借助|举|换成|改用|给出', prefix):
            continue
        if re.match(r'[\u4e00-\u9fffA-Za-z]', following):
            return True
    return False


def is_followup(text: str) -> bool:
    """A new subject must not become a revision merely because it says '没看懂'."""
    if starts_new_subject(text):
        return False
    direct_reference = re.search(r"你(?:刚才|之前|这次|写的)|上一版|这份(?:文档|报告|讲义)|听完之后修改|修改回复", text)
    continuation = re.search(r"^(?:好的?[，。\s]*)?(?:继续|再|更|这|上一|补|精简|没看懂|看不懂|请再|请继续|请改|改成)", text.strip())
    revision = re.search(r"把(?:语言|说明|正文).{0,8}改|我觉得.{0,10}(?:增加|补充|修改|调整)", text)
    reexplain = re.search(r"(?:没看懂|看不懂|不清楚).{0,12}再(?:解释|讲|说明)", text)
    return bool(direct_reference) or (len(text) < 160 and bool(continuation or reexplain or (revision and WRITING.search(text))))


def clarification_question(text: str) -> bool:
    """Recognize short requests for a choice, not every question in an answer."""
    return len(text) <= 400 and bool(re.search(r'[?？]\s*$', text)) and bool(re.search(
        r'想看|希望用|你(?:想|希望|选择)|请(?:选择|确认|提供)|还是|which|would you prefer', text, re.I))


def answers_clarification(event: Event, previous_reply: str) -> bool:
    """Native callbacks or a literal offered choice can continue the same task."""
    if starts_new_subject(event.text):
        return False
    if event.details.get('input_format') == 'question_reply':
        return True
    answer = _clean(event.text).strip().rstrip('。.!！')
    answer = re.sub(r'^(?:继续用|就用|请用|用|选择|我选|选)\s*', '', answer)
    return clarification_question(previous_reply) and 2 <= len(answer) <= 60 and answer in previous_reply


def same_artifact_reference(request: str, delivery: str) -> bool:
    """An explicit file reference can confirm continuity across imperfect scene labels.

    Compare path suffixes without reading the referenced files. Distinct directories
    with the same basename do not match when both references contain directories.
    """
    def references(text):
        paths = []
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            try:
                path = unquote(urlsplit(target).path)
            except ValueError:
                continue
            path = re.sub(r":\d+$", "", path)
            if re.search(r"\.(?:md|tex|docx)$", path, re.I):
                paths.append(tuple(part for part in path.split("/") if part not in ("", ".")))
        return paths
    for first in references(request):
        for second in references(delivery):
            size = min(len(first), len(second))
            if size and first[-size:] == second[-size:]:
                return True
    return False


def reader_context(text: str, event_id: str) -> list[dict]:
    return reader_constraints(text, event_id)[0]


def reader_constraints(text: str, event_id: str) -> tuple[list[dict], set[str]]:
    """Task readers are explicit requirements, not claims about the user's identity."""
    rules = [("first_year_student", "大一学生", r"大一学生|大学一年级|大学新生"),
             ("beginner", "初学者", r"初学者|零基础(?:的读者|的人)?|入门读者"),
             ("developer", "项目开发者", r"开发者|工程师"),
             ("general_reader", "非专业读者", r"非专业读者|普通读者|不了解背景的读者")]
    readers, excluded = {}, set()
    for key, label, pattern in rules:
        for match in re.finditer(pattern, text):
            left = max(text.rfind(c, 0, match.start()) for c in "，,。；;\n") + 1
            prefix = text[max(left, match.start() - 16):match.start()]
            if re.search(NEGATION + r"[^，。；;\n]{0,10}$|不针对[^，。；;\n]{0,8}$", prefix):
                readers.pop(key, None)
                excluded.add(key)
                continue
            # A mentioned person's background alone does not define the requested reader.
            cue = list(re.finditer(r'给|让|面向|供|适合|为|读者(?:是|为|包括|[:：])|受众(?:是|为|包括|[:：])', prefix))
            governed = False
            if cue:
                between = prefix[cue[-1].end():]
                # A shared cue can govern coordinated audiences. An intervening
                # action such as "分析" ends that scope before the subject.
                names = '|'.join(pattern for _, _, pattern in rules)
                between = re.sub(names, '', between)
                governed = bool(re.fullmatch(r'(?:\s|、|和|与|及|或|以及|刚入门的|没有基础的)*', between))
            if not WRITING.search(text) or not (governed or text[match.end():].startswith('易读')):
                continue
            readers[key] = {"id": key, "label": label, "evidence_id": event_id,
                            "quote": _quote(text, match.start(), match.end())}
            excluded.discard(key)
    return list(readers.values()), excluded


def scene_of(text: str) -> str:
    # The deliverable's intent outranks an incidental subject such as matrices.
    # For mixed requests, prefer the first explicit action rather than relabeling
    # the entire task from a later mention of a tool or optional report.
    report = re.search(r"(?:编写|写|生成|修改|改写|整理|提供|输出)[^，,。；;\n]{0,36}(?:报告|README|开发说明)", text, re.I)
    coding = re.search(r"(?:实现|编写|修改|调试|重构|修复|运行|测试)[^，,。；;\n]{0,24}(?:代码|函数|程序|脚本|接口|模块|后端)|(?:代码|程序|脚本)[^，,。；;\n]{0,20}(?:实现|调试|修复|运行|测试)", text, re.I)
    if report and (not coding or report.start() <= coding.start()):
        return "developer_report"
    if coding:
        return "coding"
    if re.search(r"数学|定理|证明|推导|不动点|微分|积分|矩阵|数分|SPADE", text, re.I):
        return "math_explanation"
    if re.search(r"报告|项目进度|完成度|README|开发说明", text, re.I):
        return "developer_report"
    if re.search(r"文档|文章|讲义|教程|方案|大纲|试卷|试题", text):
        return "document"
    if re.search(r"代码|函数|测试(?!题|卷|成绩|分数)|bug|运行|实现|后端|算法|架构|模块|接口", text, re.I):
        return "coding"
    return "conversation"


def _clean(text: str) -> str:
    # Filenames may contain '精简版' or '验证'; they are not semantic observations.
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", lambda m: "文档" if re.search(r"\.(?:md|tex|docx)\b", m[1]) else "文件", text)
    original = text

    def quoted(match):
        term = next(group for group in match.groups() if group is not None)
        prefix = original[max(0, match.start() - 24):match.start()]
        following = original[match.end():match.end() + 24]
        directive = re.search(r"(?:(?:要求|需要|希望|喜欢|倾向|偏好|必须)[^，,。；;\n]{0,8}|(?:保持|用|写得|采用|做到|遵循|面向|给|按)\s*)$", prefix)
        known = any(re.search(pattern, term, re.I) for _, pattern in RULES.values()) or re.search(
            r"英文|英语|English|中文|汉语|初学者|大一学生|普通读者|开发者", term, re.I)
        example = re.search(r"^(?:这句|这个词|作为|当作|做一个|做为|字样|命名|的例子)", following.lstrip())
        artifact = re.search(r"\.[a-z]{1,8}\b|[/\\(){}=]", term, re.I)
        return term if len(term) <= 24 and directive and known and not example and not artifact else ""

    text = re.sub(r"“([^”\n]*)”|\"([^\"\n]*)\"|'([^'\n]*)'|`([^`\n]*)`", quoted, text)
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


def language_constraints(text: str) -> tuple[str | None, set[str]]:
    """The language of a user's message can differ from the requested deliverable."""
    text = _clean(text)
    explicit = list(re.finditer(LANGUAGE_VERBS + LANGUAGE_QUANTITY + LANGUAGE + "|" + LANGUAGE + r"(?:版本|版|的?(?:回答|报告|解释|文档))", text, re.I))
    explicit = [m for m in explicit if not re.match(r"\s*(?:API|SDK|字段|单词|术语|字样)", text[m.end():], re.I)]
    requested, forbidden = None, set()
    for match in explicit:
        language = "zh" if re.search(r"中文|汉语", match[0]) else "en"
        left = max(text.rfind(c, 0, match.start()) for c in "，,。；;\n") + 1
        prefix = text[max(left, match.start() - 24):match.start()]
        after = text[match.end():match.end() + 24]
        # A language can be the subject of a question rather than the output
        # language. Keep the latest governing action local to this clause.
        governors = list(re.finditer(r"介绍|解释|比较|分析|讨论|了解|什么|如何|怎么|用|写|输出|生成|提供|给出|给我|改成|改为|翻译成|翻译为|保留", prefix))
        topic = bool(governors and re.fullmatch(r"介绍|解释|比较|分析|讨论|了解|什么|如何|怎么", governors[-1][0]))
        if topic or re.match(r"\s*(?:是什么|是什么意思|是啥|的?(?:概念|含义|意思|定义)|已经|已(?:经)?(?:完成|写完))", after):
            continue
        # Contrastive coordination opens a new directive: the first '不要'
        # must not govern the later '而使用中文' as well.
        connectors = list(re.finditer(r"而(?:且|是|要)?|但(?:是|要)?|同时|并(?:且)?", prefix))
        if connectors:
            prefix = prefix[connectors[-1].end():]
        if re.search(NEGATION + r"[^，。；;\n]{0,8}$", prefix):
            forbidden.add(language)
            if requested == language:
                requested = None
        else:
            requested = language
            forbidden.discard(language)
    return requested, forbidden


def explicit_language(text: str) -> str | None:
    return language_constraints(text)[0]


def language_of(text: str) -> str:
    requested, forbidden = language_constraints(text)
    fallback = "zh" if re.search(r"[\u4e00-\u9fff]", _clean(text)) else "en"
    return requested or (fallback if fallback not in forbidden else "unknown")


def _requirement_target(text: str, match: re.Match, dimension: str) -> bool:
    """Separate an instruction from a negated instruction or a discussion topic."""
    left = max(text.rfind(c, 0, match.start()) for c in "，,。；;\n") + 1
    prefix = text[max(left, match.start() - 24):match.start()]
    after = text[match.end():match.end() + 16]
    if dimension == "brevity" and re.search(r"(?:取消|撤销|去掉|移除)[^，,。；;\n]{0,12}$", prefix):
        return False
    if dimension == "brevity" and re.fullmatch(r"(?:一|两|三|\d+)段话", match[0]):
        output = re.search(r"(?:用|以|写成|分成|压缩成|控制在|限制为|回答|回复|摘要|概述)[^，,。；;\n]{0,6}$", prefix)
        if not output and not re.match(r"\s*(?:就好|即可|以内|足够)", after):
            return False
    if dimension == "brevity" and match[0] == "太长" and re.search(r"(?:不要|不用|无需|不必|别|不需要)[^，。；;\n]{0,4}$", prefix):
        return True  # '不要太长' requests brevity; it does not reject brevity.
    if re.search(NEGATION + r"[^，。；;\n]{0,6}$", prefix):
        return False
    # The nearest governing cue distinguishes '请解释实现' from '先解释再实现'.
    cues = list(re.finditer(r"解释|介绍|科普|概念|定义|是什么|分析|怎么|如何|确认|是否|能否|阅读|查看|看看|描述|讨论|了解|请|先|再|然后|接着|并|直接|帮我|需要|要|务必|记得|完成后|最后|做|进行|执行|运行|跑|补充|添加|增加|编写|写|加入", prefix))
    topic = bool(cues and re.fullmatch(r"解释|介绍|科普|概念|定义|是什么|分析|怎么|如何|确认|是否|能否|阅读|查看|看看|描述|讨论|了解", cues[-1][0]))
    execution = bool(cues and not topic and len(prefix[cues[-1].end():]) <= 8)
    if not execution and dimension in ("actionability", "verification") and re.match(
        r"(?:已经|已|正在|完成|结束|了|过|通过|成功|失败|是|可以|需要|耗时)", after):
        return False
    if dimension == "actionability" and match[0] not in ("具体步骤", "怎么做", "怎么用"):
        if topic or re.match(r"性(?:的)?(?:含义|意思|定义|概念)|(?:的)?(?:含义|意思|定义|概念)|程序(?:的)?(?:定义|概念|是什么)", after):
            return False
    if dimension == "actionability" and match[0] == "实现":
        if re.match(r"原理|机制|方式|方法|过程|细节", after) or topic:
            return False
        if not execution and match.start() != left:
            return False
    if dimension == "verification":
        if topic or (match[0] == "测试" and re.match(r"题|卷|成绩|分数|工具|框架|日志|环境|版本|状态|计划|方案|驱动|数据|集|结果|报告|范围|覆盖|失败|成功|为什么|如何|的(?:概念|定义|原理)", after)):
            return False
        imperative_object = (match[0].startswith(("检查", "验证")) and len(match[0]) > 2) or (
            match[0] == "测试" and bool(re.match(r"一下|一遍|这(?:段|个|些)|那(?:段|个|些)|所有|全部|每个", after)))
        if not execution and not imperative_object:
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
    rule_version: str = "rules-v13"
    readers: list[dict] = field(default_factory=list)
    output_contract: dict | None = None
    output_contracts: list[dict] = field(default_factory=list)
    language: str = "zh"
    language_evidence_id: str | None = None
    language_basis: str = "message_language"
    task_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def task_contexts(events: list[Event]) -> dict[str, dict]:
    """Resolve task context without changing the original normalized events."""
    current: dict[str, dict] = {}
    deliveries = {}
    delivery_ordinals = {}
    by_event = {}
    for event in sorted(events, key=lambda e: (e.session_id, e.ordinal)):
        if event.kind == "assistant_message" and event.details.get("phase") not in ("commentary", "analysis"):
            deliveries[event.session_id] = event.text
            delivery_ordinals[event.session_id] = event.ordinal
        if event.kind != "user_message":
            continue
        text = _clean(event.text)
        scene = scene_of(_context_text(event.text))
        readers, excluded_readers = reader_constraints(text, event.id)
        requested_language, forbidden = language_constraints(text)
        language = requested_language or language_of(text)
        language_evidence_id = event.id
        language_basis = "explicit_request" if requested_language else "message_language"
        task_id = event.id
        previous = current.get(event.session_id)
        supplement = bool(previous and event.turn_id is not None and event.turn_id == previous["turn_id"] and
                          delivery_ordinals.get(event.session_id, -1) < previous["request_ordinal"] and not starts_new_subject(text))
        continuation = supplement or is_followup(text) or answers_clarification(event, deliveries.get(event.session_id, ''))
        if continuation and event.session_id in current:
            previous = current[event.session_id]
            compatible = supplement or scene in ("conversation", previous["scene"]) or (
                previous["scene"] == "document" and scene in ("math_explanation", "developer_report")) or same_artifact_reference(
                    event.text, deliveries.get(event.session_id, ""))
            if compatible:
                scene = previous["scene"] if scene == "conversation" or (supplement and previous["scene"] != "conversation") else scene
                task_id = previous["task_id"]
                readers = readers or [r for r in previous["readers"] if r["id"] not in excluded_readers]
                if not requested_language and previous["language"] not in forbidden:
                    language = previous["language"]
                    language_evidence_id = previous["language_evidence_id"]
                    language_basis = previous["language_basis"]
        context = {"scene": scene, "readers": readers, "language": language,
                   "language_evidence_id": language_evidence_id, "language_basis": language_basis, "task_id": task_id,
                   "turn_id": event.turn_id, "request_ordinal": event.ordinal}
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
                negative_constraint = dimension == "brevity" and match[0] == "太长" and re.search(
                    r"(?:不要|不用|无需|不必|别|不需要)[^，。；;\n]{0,4}太长", clause)
                if not negative_constraint and dimension in ("clarity", "brevity", "grounding") and re.search(r"看不懂|没看懂|不满意|(?:你|这[次份段]|还是|又).{0,10}太长", clause):
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
                                 language_basis=context["language_basis"], task_id=context["task_id"]))
    return output

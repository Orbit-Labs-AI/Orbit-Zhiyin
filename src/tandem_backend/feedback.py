"""Identify the target of a requirement before treating it as profile evidence.

'Short code' is a code requirement, not a preference for short answers.
Signals describe observations; repeat requests do not establish stable personality.
"""

import re
from dataclasses import asdict, dataclass

from .models import Event

RULES = {
    "clarity": ("把说明讲清楚", r"说人话|易读|易懂|简洁直接|逻辑清晰|通俗|讲清楚|直观|朴素|看不懂|没看懂|难理解|明确思路"),
    "brevity": ("说明简洁些", r"简洁|简短|不要啰嗦|太长|精简|少[一一点]*细节"),
    "grounding": ("说明判断依据", r"证据|有依据|不要编|来源|真实性|不要想当然|不要猜|核对事实"),
    "actionability": ("把要求落实为结果", r"直接[修做改]|跑通|可运行|具体步骤|怎么[做用]|实现|继续执行"),
    "autonomy": ("减少反复确认", r"不要[再]*问|直接完成|自主|不用[再]*确认|不[用需要]*[再]*问我"),
    "planning": ("先理清方案", r"先[想讲说给]*[一一下]*方案|先规划|先[做给]*计划|思考规划|分步"),
    "verification": ("完成后检查", r"测试|验收|跑通|检查.{0,10}(?:代码|运行|结果)|验证.{0,10}(?:代码|运行|结果)"),
    "scope": ("保持范围集中", r"先做最[小简]|不要[再]*[增扩]|只[改做]|MVP|最小.{0,6}(?:版本|范围|原型)|不要重构"),
}
WRITING = re.compile(r"说人话|说明|讲清楚|解释|回答|表达|报告|文档|文章|语言|教程|注释|讲义|证明|思路|方案|策略|解答|读者|学生")
CODE = re.compile(r"代码|函数|模块|架构|重构|bootstrap|脚本|算法|实现")
VISUAL = re.compile(r"画图|绘图|图像|图片|坐标|图表|界面|pdf.*高度|窗口|颜色|字体|看不清楚|排版|换行|居中|页面", re.I)


def scene_of(text: str) -> str:
    if re.search(r"数学|定理|证明|推导|不动点|微分|积分|矩阵|数分|SPADE", text, re.I):
        return "math_explanation"
    if re.search(r"报告|项目进度|完成度|README|开发者|后端|架构", text, re.I):
        return "developer_report"
    if re.search(r"文档|文章|讲义|教程|方案", text):
        return "document"
    if re.search(r"代码|函数|测试|bug|运行|实现", text, re.I):
        return "coding"
    return "conversation"


def _clean(text: str) -> str:
    # Filenames may contain '精简版' or '验证'; they are not semantic observations.
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", lambda m: "文档" if re.search(r"\.(?:md|tex|docx)\b", m[1]) else "文件", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"[“\"][^”\"]*[”\"]", "", text)
    text = re.sub(r"(?:C\+\+|C|Python|JavaScript|Matlab|编程)\s*语言", "编程代码", text, flags=re.I)
    return text


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
    if len(text) < 100 and not CODE.search(text) and not VISUAL.search(text):
        return True  # A short direct reply implicitly refers to the explanation.
    return bool(WRITING.search(local)) or bool(WRITING.search(context)) or text[start:end] in ("说人话", "看不懂", "没看懂", "不要啰嗦")


def language_of(text: str) -> str:
    if re.search(r"英文|英语|English", text, re.I):
        return "en"
    return "zh" if re.search(r"[\u4e00-\u9fff]", text) else "en"


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
    rule_version: str = "rules-v2"

    def to_dict(self) -> dict:
        return asdict(self)


def signals(events: list[Event]) -> list[Signal]:
    output = []
    for event in events:
        if event.kind != "user_message":
            continue
        text = _clean(event.text)
        text = re.sub(r"(?:不是|并非|没有|不算)[^，。；\n]{0,10}(?:看不懂|不满意|太长)", "", text)
        for dimension, (label, pattern) in RULES.items():
            matches = list(re.finditer(pattern, text, re.I))
            if dimension in ("clarity", "brevity"):
                matches = [m for m in matches if _writing_target(text, m.start(), m.end())]
            if not matches:
                continue
            match = matches[0]
            quote = _quote(text, match.start(), match.end())
            left = max(text.rfind(c, 0, match.start()) for c in "，,。；;\n") + 1
            ends = [text.find(c, match.end()) for c in "，,。；;\n" if text.find(c, match.end()) >= 0]
            clause = text[left:min(ends) if ends else len(text)]
            category = "request"
            if dimension in ("clarity", "brevity", "grounding") and re.search(r"看不懂|没看懂|不满意|(?:你|这[次份段]|还是|又).{0,10}太长", clause):
                category = "correction"
            elif dimension in ("clarity", "brevity", "grounding") and re.search(r"继续修改|据此改进|改写|重写|上一[版轮]|你刚才|更[加]*.{0,5}(?:直观|朴素|易读)", text):
                category = "refinement"
            output.append(Signal(dimension, label, category, event.id, event.session_id,
                                 event.turn_id, event.timestamp, quote,
                                 "communication" if dimension in ("clarity", "brevity", "grounding") else "workflow",
                                 scene_of(text)))
    return output

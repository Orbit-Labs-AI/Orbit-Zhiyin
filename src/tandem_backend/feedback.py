"""Conservative observed-language signals, with evidence rather than personality labels."""

import re
from dataclasses import asdict, dataclass

from .models import Event

# These rules came from ordinary writing/workflow concepts, not the user's held-out feedback.
RULES = {
    "clarity": ("表达容易理解", r"说人话|易读|简洁直接|逻辑清晰|通俗|讲清楚|直观|看不懂|没看懂|难理解"),
    "brevity": ("控制篇幅", r"简洁|简短|不要啰嗦|太长|精简|少[一一点]*细节"),
    "grounding": ("说明依据", r"严谨|验证|证据|有依据|不要编|来源|真实性"),
    "actionability": ("给出可执行的下一步", r"直接[修做改]|跑通|可运行|具体步骤|怎么[做用]|实现|继续执行"),
    "autonomy": ("减少反复确认", r"不要[再]*问|直接完成|自主|不用[再]*确认|不[用需要]*[再]*问我"),
    "planning": ("先理清方案", r"先[想讲说]*[一一下]*方案|先规划|先[做给]*计划|思考规划|分步"),
    "verification": ("完成后检查", r"测试|检查|验收|验证|可运行"),
    "scope": ("保持范围集中", r"先做最[小简]|不要[再]*[增扩]|只[改做]|MVP|最小|范围"),
}
NEGATIVE = re.compile(r"看不懂|没看懂|难理解|不满意|太[长复杂]|不是[我这]?[的要]?意思|不要啰嗦|不对|错了")
POSITIVE = re.compile(r"^(?:对[，,。]|可以[，,。]|就这样|很好|满意|没问题)")


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
    rule_version: str = "rules-v1"

    def to_dict(self) -> dict:
        return asdict(self)


def signals(events: list[Event]) -> list[Signal]:
    output = []
    for event in events:
        if event.kind != "user_message":
            continue
        text = event.text
        # Negated/quoted phrases must not become negative observations.
        text = re.sub(r"[“\"][^”\"]*[”\"]", "", text)
        text = re.sub(r"(?:不是|并非|没有|不算)[^，。；\n]{0,10}(?:看不懂|不满意|太长)", "", text)
        category = "correction" if NEGATIVE.search(text) else "request"
        if POSITIVE.search(text):
            category = "acceptance"
        for dimension, (label, pattern) in RULES.items():
            match = re.search(pattern, text, re.I)
            if match:
                start, end = max(0, match.start() - 45), min(len(text), match.end() + 75)
                output.append(Signal(dimension, label, category, event.id, event.session_id,
                                     event.turn_id, event.timestamp, text[start:end]))
    return output

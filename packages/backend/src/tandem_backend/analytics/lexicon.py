"""Mixed Chinese/English lexical rules for corrections and explicit emotion (experimental).

Every rule has an id so a hit can carry per-rule evidence. Recall/precision are measured
on the synthetic labelled set in ``tests/analytics/test_lexicon_labelled.py``; they are
lexical candidates, not annotated ground truth (EV-02 still pending).
"""

from __future__ import annotations

import re

LEXICON_VERSION = "zh-en-lexicon-v1"

# Conditional / example / reported speech: the statement is not the user's own verdict.
HYPOTHETICAL = re.compile(
    r"如果|假如|假设|比如|例如|举例|示例|万一|\b(?:if|suppose|e\.g\.|for example|example)\b", re.I
)

# Corrections beyond the clause-initial markers in interaction.rules.CORRECTION.
CORRECTION_RULES: tuple[tuple[str, str], ...] = (
    (
        "repeat_failure",
        r"还是(?:不行|不对|报错|失败|有问题|没(?:好|修好|解决))|又(?:错|报错|失败|坏)了|怎么又"
        r"|\bstill (?:broken|failing|fails|wrong|not (?:working|fixed)|doesn'?t work|the same (?:error|issue))\b"
        r"|\b(?:same|this) (?:error|issue|problem) again\b",
    ),
    (
        "change_approach",
        r"(?:换|试试|改用)(?:个|一个|一种|别的)(?:方法|思路|方案|方式|做法)|换(?:方法|思路|方案|方式|做法)"
        r"|\b(?:try|use|take) (?:a )?(?:different|another|other) (?:approach|way|method|strategy)\b",
    ),
    (
        "not_what_asked",
        r"不是我(?:要|想要|想)的|不是这个意思|我(?:刚才|之前|已经)?说(?:过|了)(?:要|不要|别)?"
        r"|(?:理解|搞|弄|改)错了|改坏了|弄坏了"
        r"|\bnot what I (?:asked|wanted|said|meant)\b|\bthat'?s not (?:right|it|what I)\b"
        r"|\bI (?:said|told you|asked you)\b|\byou (?:broke|misunderstood|ignored|missed)\b",
    ),
    (
        "scope_constraint",
        r"(?:别|不要|不许|不准)(?:再)?(?:动|改|碰|删)(?:其他|别的|无关|其它)"
        r"|(?:别|不要)再(?:改|用|加|动)"
        r"|\b(?:don'?t|do not|stop) (?:touch|chang|modif|edit|delet|add)\w*"
        r"(?: (?:any )?(?:other|unrelated|the other|those|that|it|anything))\b",
    ),
    (
        "rework",
        r"(?:撤销|回滚|撤回|还原)(?:你|刚才|刚刚|之前|这次|上一步|上次)"
        r"|\b(?:revert|undo|roll ?back) (?:that|this|it|your|the (?:last )?change)\w*",
    ),
)
CORRECTION_EXTRA = re.compile(
    "|".join(f"(?P<{rule}>{pattern})" for rule, pattern in CORRECTION_RULES), re.I
)
# Loose prefilter equivalent for callers that screen messages before full parsing.
CORRECTION_EXTRA_HINT = re.compile(
    r"还是|又|怎么|换|试|不是|说|错|坏|别|不要|不许|不准|撤|回滚|还原"
    r"|still|again|different|another|not what|not right|said|told|broke|misunderstood"
    r"|ignored|missed|touch|chang|modif|edit|delet|revert|undo|roll",
    re.I,
)


def correction_hits(text: str) -> list[dict]:
    """Per-rule hits of the extra correction lexicon; quotes must already be removed."""
    if not text or HYPOTHETICAL.search(text):
        return []
    return [
        {"rule": match.lastgroup, "term": match.group(0).strip()}
        for match in CORRECTION_EXTRA.finditer(text)
    ]


# Explicit emotion: short exclamations / first-person statements, searched per clause.
NEGATIVE_EMOTION = re.compile(
    r"烦死了|好烦|真烦|太烦|崩溃了?|无语|气死|受不了|心累|太慢了|浪费(?:我的)?时间|离谱|服了"
    r"|\b(?:ugh|argh|wtf|ffs)\b|\bcome on\b|\b(?:so|really|very|this is|that'?s) "
    r"(?:annoying|frustrating|ridiculous|painful|useless)\b"
    r"|\bI'?m (?:so |really |getting )?(?:annoyed|frustrated|tired of|sick of|fed up)\b"
    r"|\bwaste of (?:my )?time\b",
    re.I,
)
POSITIVE_EMOTION = re.compile(
    r"太好了|太棒了?|完美|好棒|漂亮|真不错|干得(?:好|漂亮)|\b(?:nice|great(?: job| work)?|perfect"
    r"|awesome|excellent|love it|well done|good job|amazing|thanks? a lot|thank you so much)\b",
    re.I,
)
# A negation right before a cue flips or voids it ("不完美", "not great").
NEGATED = re.compile(r"(?:不|没|没有|并不|不太|not|n't|never)\s?$", re.I)
# Positive cues only count in short exclamation-like clauses ("完美！", "great job"),
# not inside instructions ("完美地实现这个功能并补充测试").
POSITIVE_CLAUSE_CHARS, POSITIVE_CLAUSE_WORDS = 12, 6
_CJK = re.compile(r"[\u3400-\u9fff]")


def _cue(pattern: re.Pattern, clause: str) -> bool:
    for match in pattern.finditer(clause):
        if not NEGATED.search(clause[max(0, match.start() - 4) : match.start()]):
            return True
    return False


def emotion_cues(clause: str) -> tuple[bool, bool]:
    """(positive, negative) cue presence for one clause; hypothetical text has none."""
    if HYPOTHETICAL.search(clause):
        return False, False
    short = (
        len(clause) <= POSITIVE_CLAUSE_CHARS
        if _CJK.search(clause)
        else len(clause.split()) <= POSITIVE_CLAUSE_WORDS
    )
    positive = short and _cue(POSITIVE_EMOTION, clause)
    return positive, _cue(NEGATIVE_EMOTION, clause)

"""Mixed Chinese/English lexical rules for corrections and explicit emotion (experimental).

Every rule has an id so a hit can carry per-rule evidence. Recall/precision are measured
on the synthetic labelled set in ``tests/analytics/test_lexicon_labelled.py``; they are
lexical candidates, not annotated ground truth (EV-02 still pending).
"""

from __future__ import annotations

import re

LEXICON_VERSION = "zh-en-lexicon-v3"

# Conditional / example / reported speech: the statement is not the user's own verdict.
HYPOTHETICAL = re.compile(
    r"如果|假如|假设|比如|例如|举例|示例|万一|\b(?:if|suppose|e\.g\.|for example|example)\b", re.I
)

# Corrections beyond the clause-initial markers in interaction.rules.CORRECTION. The single
# verdict built on these rules is ``interaction.rules.correction_verdict``; rules listed in
# ``RESULT_FEEDBACK_RULES`` report the outcome of the agent's work ("还是不行，测试依然失败")
# rather than redirect it, and only count as a correction together with another rule.
CORRECTION_RULES: tuple[tuple[str, str], ...] = (
    (
        "repeat_failure",
        r"(?:还是|依然|仍然|仍旧)(?:不行|不对|报错|失败|有问题|没(?:好|修好|解决))|又(?:错|报错|失败|坏)了|怎么又"
        r"|\bstill (?:broken|failing|fails|wrong|not (?:working|fixed)|doesn'?t work|the same (?:error|issue))\b"
        r"|\b(?:same|this) (?:error|issue|problem) again\b",
    ),
    (
        "change_approach",
        r"(?:换|试试|改用)(?:个|一个|一种|种|别的)[^，。！？；,.!?;\s]{0,6}?"
        r"(?:方法|思路|方案|方式|做法|例子|说法|解释|角度|写法)"
        r"|换(?:方法|思路|方案|方式|做法)"
        r"|\b(?:try|use|take) (?:a )?(?:different|another|other) (?:approach|way|method|strategy)\b",
    ),
    (
        "not_what_asked",
        r"不是我(?:要|想要|想)的|不是这个意思|我(?:刚才|之前|已经)?说(?:过|了)(?:要|不要|别)?"
        r"|(?:理解|搞|弄|改)错了|改坏了|弄坏了|不是让你"
        r"|(?:方向|思路|路子|做法|方案)(?:错了|不对)(?![吗么嘛？?])"
        r"|我的意思是|我是说|\bwhat I meant\b|\bI meant\b"
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
        r"(?:撤销|回滚|撤回|还原)(?:你|刚才|刚刚|之前|这次|这个|上一步|上次)"
        # Clause-final or deferring rollback ("先回滚再说", "回滚吧"); "回滚脚本" is a noun.
        r"|(?:撤销|回滚|撤回|还原)(?:掉|一下)?(?=$|[，。！；,;!\s]|吧|再说)"
        r"|\b(?:revert|undo|roll ?back) (?:that|this|it|your|the (?:last )?change)\w*",
    ),
    (
        # Short whole-clause rejections ("错了", "重来", "不行，重来", "不是这样的"). Bounded on
        # both sides so "哪里错了？", "算错了吗" or "这样不行的话" do not fire; a question mark
        # after the term is a question, not a verdict.
        "short_rejection",
        r"(?:^|(?<=[，。！；,;!\s]))(?:(?:你|这|这个|又)?(?:错了|弄错了)|重来|重新来|不行"
        r"|不是这样(?:的|子)?)(?=$|[，。！；,;!\s])"
        r"|^\s*(?:no,? )?not like that\b",
    ),
    (
        # Clause-initial pushback carried over from the former ``ai.pack.is_correction``
        # (zh) and ``uiview.a4a6_sentiment.EXTRA_CORRECTION``: "这不对，", "不是，先跑测试",
        # "不是删掉，是注释掉", "别再跑全量了", "别用子代理", "用 pnpm 不是 npm", "没看懂，".
        "zh_pushback",
        r"(?:^|(?<=[，。！；,;!\s]))(?:这|这样|你说的|说的)?不对(?=$|[，。！；,;!\s])"
        r"|^不是(?:[，,]|[^，。！？,.!?]{1,12}[，,]\s*(?:而是|是|要|应该))"
        r"|不是.{0,6}而是"
        r"|(?:^|(?<=[，。！；,;!\s]))(?:这)?不是这(?:样|个)(?!.{0,6}[吗么嘛？?])"
        r"|(?:^|(?<=[，。！；,;!\s]))(?:你)?(?:别|不要)(?:再\S|用)"
        r"|用\s?\S.{0,20}?(?<!是)不是\s?\S"
        r"|(?:^|(?<=[，。！；,;!\s]))(?:我)?(?:没|看不|听不)(?:看|听)?懂(?:你的意思)?(?=$|[，。！；,;!\s])",
    ),
    (
        "en_pushback",
        r"\bthat'?s (?:just |still )?wrong\b|\byou misunderstood\b|\bi told you (?:not )?to\b",
    ),
    (
        "overdone",
        r"(?:不要|不用|别|没必要)(?:那么|这么|过度)|过度(?:修复|设计|优化)|太(?:复杂|啰嗦|冗长)了"
        r"|\btoo (?:verbose|complicated|complex|long|much)\b|\bover-?engineer\w*",
    ),
)
CORRECTION_EXTRA = re.compile(
    "|".join(f"(?P<{rule}>{pattern})" for rule, pattern in CORRECTION_RULES), re.I
)
RESULT_FEEDBACK_RULES = frozenset({"repeat_failure"})
# English pushback only counts at the start of a sentence ("No, use X", "That's wrong",
# "Wrong file", "Still failing"): mid-sentence "wrong" is mostly a request about an object
# ("fix the wrong import", "what's wrong with this test"). Moved from ``ai.pack``.
_EN_LEAD = r"^(?:(?:no|nope|hmm+|ugh|wait|actually|stop)[,.!\s]+)?"
SENTENCE_RULES: tuple[tuple[str, re.Pattern], ...] = (
    ("en_pushback", re.compile(
        r"^(?:(?:no|nope|hmm+|ugh|wait|actually|again)[,.!\s]+)?"
        r"(?:no|nope)\b(?=[\s,.!]|$)(?!\s+(?:problem|worries|thanks|rush|idea|need)\b)"
        rf"|{_EN_LEAD}(?:that'?s|this is|it'?s|you'?re|you are)\s+(?:still\s+)?"
        r"(?:not right|not correct|wrong|incorrect|not it|not what)"
        rf"|{_EN_LEAD}(?:wrong|incorrect)\b(?!\s+with)"
        rf"|{_EN_LEAD}(?:i said|i meant|i asked (?:you )?(?:to|for))\b"
        rf"|{_EN_LEAD}(?:don'?t do that|you (?:did|got) (?:it|that) wrong|you broke)"
        rf"|{_EN_LEAD}stop (?:doing|chang|modif|edit|touch|add|delet|rewrit|remov)\w*"
        rf"|{_EN_LEAD}(?:please )?(?:don'?t|do not) (?:touch|change|modify|edit|delete|remove)\b"
        rf"|{_EN_LEAD}use \S+ instead of\b", re.I)),
    ("repeat_failure", re.compile(
        rf"{_EN_LEAD}still (?:wrong|broken|failing|not working|doesn'?t work)\b", re.I)),
)
_SENTENCES = re.compile(r"(?<=[.!?。！？;；])\s*|\n+")
# Loose prefilter equivalent for callers that screen messages before full parsing.
CORRECTION_EXTRA_HINT = re.compile(
    r"还是|又|怎么|换|试|不是|说|错|坏|别|不要|不用|没必要|过度|太|不许|不准|撤|回滚|还原|意思|重来|重新来|不行"
    r"|not like that|still|again|different|another|not what|not right|said|told|broke|misunderstood|meant|too |over"
    r"|ignored|missed|touch|chang|modif|edit|delet|revert|undo|roll"
    r"|对|依然|仍|懂|用|让你|方向|思路|例子|no|wrong|correct|not it|asked|stop|don|instead",
    re.I,
)


def correction_hits(text: str) -> list[dict]:
    """Per-rule hits of the extra correction lexicon; quotes must already be removed."""
    if not text or HYPOTHETICAL.search(text):
        return []
    hits = [
        {"rule": match.lastgroup, "term": match.group(0).strip()}
        for match in CORRECTION_EXTRA.finditer(text)
    ]
    for part in _SENTENCES.split(text):
        part = part.strip()
        for rule, pattern in SENTENCE_RULES:
            if part and (match := pattern.match(part)):
                hits.append({"rule": rule, "term": match.group(0).strip()})
    return hits


# Explicit emotion: short exclamations / first-person statements, searched per clause.
NEGATIVE_EMOTION = re.compile(
    r"烦死了|好烦|真烦|太烦|崩溃了?|无语|气死|受不了|心累|太慢了|浪费(?:我的)?时间|离谱|服了"
    # Giving up / exasperated repetition. "算了" only clause-final ("算了一下" is arithmetic);
    # "第几次" only with a closing 了 ("第几次迭代" is a neutral question).
    r"|算了吧?(?=$|[，,。！!；;\s~～])|怎么又(?:错|失败|报错|坏|不行)|又(?:错|失败|报错)了"
    r"|第(?:几|[0-9一二三四五六七八九十]+)(?:次|遍)了"
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

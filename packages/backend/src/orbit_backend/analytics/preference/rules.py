"""Explicit preference cues, not a learned personality or an implicit ranking."""

import re


def ascii_word(alternatives: str) -> str:
    """ASCII keywords bounded by non-ASCII-word characters.

    Python's ``\\b`` treats CJK characters as word characters, so ``以后用pytest`` has no
    boundary between ``用`` and ``p`` and ``\\bpytest\\b`` never matches. Mixed CJK/ASCII
    writing is the common case for Chinese users, so ASCII words are bounded only by
    ASCII letters/digits/underscore.
    """
    return rf"(?<![A-Za-z0-9_])(?:{alternatives})(?![A-Za-z0-9_])"


W = ascii_word
EXPLICIT = re.compile(rf"我(?:更|不)?(?:喜欢|偏好|倾向)|{W(r"I (?:prefer|like|don't like)")}|以后|今后|从现在起|始终|默认|{W('from now on|always|by default')}", re.I)
PROJECT = re.compile(rf"这个项目|本项目|该项目|{W('this project')}", re.I)
TASK = re.compile(rf"这次|本次|这个任务|当前任务|{W('this task|this time')}", re.I)
GLOBAL = re.compile(rf"所有项目|任何项目|所有任务|一般情况下|无论.{{0,12}}都|{W('all projects|all tasks|in general')}", re.I)
CHANGE = re.compile(rf"改用|改成|改为|不再|撤销|取消之前|收回|{W('switch to|instead|revoke|no longer')}", re.I)
REVOKE = re.compile(rf"撤销|取消之前|收回|{W('revoke')}", re.I)
# "if " must be a word ("elif ", "motif " are not reported speech).
REPORTED = re.compile(rf"(?:例如|比如|假如|假设|如果|示例|他说|她说|用户说|文档说|原文|翻译这句|{W('for example|if|he says|she says|translate')}\s?)", re.I)
DIMENSIONS = {
    "language": {"zh": rf"中文|汉语|{W('Chinese')}", "en": rf"英文|英语|{W('English')}"},
    "detail": {"brief": rf"简短|简洁|精简|{W('brief|concise')}", "detailed": rf"详细|详尽|{W('detailed')}"},
    "format": {"table": rf"表格|{W('table')}", "list": rf"列表|分点|{W('bullets?|list')}",
               "markdown": W("markdown"), "json": W("json")},
    "tool": {"pytest": W("pytest"), "git": W("git"), "bash": W("bash")},
    "collaboration": {"plan_first": rf"先规划|先.{{0,4}}计划|{W('plan first')}",
                      "act_directly": rf"直接执行|直接完成|不用.{{0,3}}确认|不要.{{0,3}}问我|{W('act directly|without asking')}"},
}
# Whether one value replaces the others. Only single-valued dimensions are exclusive: an
# answer has one language and one level of detail, but a user can prefer git *and* pytest,
# or tables *and* JSON. A revise on a non-exclusive dimension never supersedes other values.
EXCLUSIVE = {"language": True, "detail": True, "format": False, "tool": False,
             "collaboration": False}
# A tool name alone ("以后 git diff 要简洁") names an artifact, not a tool choice; a tool
# preference needs a usage verb right before the tool name.
TOOL_USE = re.compile(rf"(?:用|使用|采用|改用|换用|换成|改成|改为|通过|{W('use|using|with|switch to|run')})\s*$", re.I)


def preference_values(statement):
    values = []
    for kind, vocabulary in DIMENSIONS.items():
        for value, pattern in vocabulary.items():
            for match in re.finditer(pattern, statement, re.I):
                prefix = statement[max(0, match.start() - 16):match.start()]
                if kind == "tool" and not TOOL_USE.search(prefix):
                    continue
                # Revocation of a preference is a history operation, not "avoid the value".
                polarity = "avoid" if not REVOKE.search(statement) and re.search(
                    r"(?:不要|不用|不再|不喜欢|不偏好|不倾向|避免|别用|do not use|don't like|avoid)\s*(?:使用|用)?\s*$", prefix, re.I) else "prefer"
                # "Short code" describes the artifact, not the speaker's answer preference.
                if kind == "detail" and re.search(r"(?:代码|函数|变量|code|function)", statement, re.I) and not re.search(r"回答|说明|解释|回复|answer|explanation", statement, re.I):
                    continue
                values.append((kind, value, polarity))
                break
    return values

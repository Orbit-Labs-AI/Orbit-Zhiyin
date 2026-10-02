"""Explicit preference cues, not a learned personality or an implicit ranking."""

import re

EXPLICIT = re.compile(r"我(?:更|不)?(?:喜欢|偏好|倾向)|\bI (?:prefer|like|don't like)\b|以后|今后|从现在起|始终|默认|\b(?:from now on|always|by default)\b", re.I)
PROJECT = re.compile(r"这个项目|本项目|该项目|\bthis project\b", re.I)
TASK = re.compile(r"这次|本次|这个任务|当前任务|\b(?:this task|this time)\b", re.I)
GLOBAL = re.compile(r"所有项目|任何项目|所有任务|一般情况下|无论.{0,12}都|\b(?:all projects|all tasks|in general)\b", re.I)
CHANGE = re.compile(r"改用|改成|改为|不再|撤销|取消之前|收回|\b(?:switch to|instead|revoke|no longer)\b", re.I)
REVOKE = re.compile(r"撤销|取消之前|收回|\brevoke\b", re.I)
REPORTED = re.compile(r"(?:例如|比如|假如|假设|如果|示例|他说|她说|用户说|文档说|原文|翻译这句|for example|if |he says|she says|translate)", re.I)
DIMENSIONS = {
    "language": {"zh": r"中文|汉语|\bChinese\b", "en": r"英文|英语|\bEnglish\b"},
    "detail": {"brief": r"简短|简洁|精简|\b(?:brief|concise)\b", "detailed": r"详细|详尽|\bdetailed\b"},
    "format": {"table": r"表格|\btable\b", "list": r"列表|分点|\b(?:bullet|list)\b", "markdown": r"\bmarkdown\b", "json": r"\bjson\b"},
    "tool": {"pytest": r"\bpytest\b", "git": r"\bgit\b", "bash": r"\bbash\b"},
    "collaboration": {"plan_first": r"先规划|先.{0,4}计划|\bplan first\b",
                      "act_directly": r"直接执行|直接完成|不用.{0,3}确认|不要.{0,3}问我|\b(?:act directly|without asking)\b"},
}


def preference_values(statement):
    values = []
    for kind, vocabulary in DIMENSIONS.items():
        for value, pattern in vocabulary.items():
            for match in re.finditer(pattern, statement, re.I):
                prefix = statement[max(0, match.start() - 16):match.start()]
                # Revocation of a preference is a history operation, not "avoid the value".
                polarity = "avoid" if not REVOKE.search(statement) and re.search(
                    r"(?:不要|不用|不再|不喜欢|不偏好|不倾向|避免|别用|do not use|don't like|avoid)\s*(?:使用|用)?\s*$", prefix, re.I) else "prefer"
                # "Short code" describes the artifact, not the speaker's answer preference.
                if kind == "detail" and re.search(r"(?:代码|函数|变量|code|function)", statement, re.I) and not re.search(r"回答|说明|解释|回复|answer|explanation", statement, re.I):
                    continue
                values.append((kind, value, polarity))
                break
    return values

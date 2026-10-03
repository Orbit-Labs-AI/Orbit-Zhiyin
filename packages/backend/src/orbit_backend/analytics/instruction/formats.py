"""Concrete format arguments owned by the task-local Instruction extractor."""

import re

FORMAT_VALUES = {
    "table": r"表格|\btable\b",
    "list": r"列表|分点|\b(?:list|bullets?)\b",
    "json": r"\bjson\b",
    "markdown": r"\bmarkdown\b",
}
FORMAT_NAMES = set(FORMAT_VALUES) | {"command_only"}
_CONTENT = re.compile(r"比较|解释|介绍|解析|描述|关于|\b(?:compare|explain|describe|about)\b", re.I)
_ALTERNATIVE = re.compile(r"或者|或|\bor\b", re.I)


def format_arguments(request):
    """Normalize the matched format request, excluding what it asks to describe."""
    request = _CONTENT.split(request, maxsplit=1)[0]
    values = sorted(name for name, pattern in FORMAT_VALUES.items()
                    if re.search(pattern, request, re.I))
    return {"format_values": values or None,
            "format_relation": "alternative" if len(values) > 1 and _ALTERNATIVE.search(request)
            else "combined" if len(values) > 1 else "single" if values else "unknown"}

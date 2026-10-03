"""Conservative lexical observations, never inferred permissions or personality."""

import re
from collections import Counter

from ...models import stable_id
from ..semantic_cascade import observation_for
from .formats import format_arguments
from .structure import file_pattern
from .text import instruction_text

INSTRUCTION_VERSION = "instruction-v1.3-zh-lexicon"
FIELDS = (
    "requested_autonomy", "execution_order", "verification_requirements",
    "allowed_scope", "prohibited_actions", "acceptance_criteria",
    "format_requirements", "tool_requirements",
)
# These rules deliberately support explicit surface forms, not arbitrary semantics.
RULES = {
    "requested_autonomy": (
        ("ask_first", r"先(?:征求|询问)(?:我|用户)|等(?:我|用户)(?:的)?确认(?:后|再)|未经(?:我|用户)(?:的)?确认|(?:ask me|wait for my (?:approval|confirmation))\b"),
        ("explicit", r"(?:无需|不必|不用)(?:再)?(?:询问|确认)|(?:你可以|允许你|授权你)(?:直接)?(?:自行|自主)|(?:^|[，,]\s*)(?:请)?(?:直接|自行|自主)(?:完成|执行|处理|修改|实现)|\b(?:proceed autonomously|without asking me)\b"),
        ("scoped", r"(?:^|[，,]\s*)(?:请)?(?:只(?:能|允许)?|仅)(?:修改|编辑|处理|读取|检查)|\bonly (?:modify|edit|read|change)\b"),
    ),
    "execution_order": (
        ("plan_first", r"先(?:给出?|提供|写|制定)?(?:计划|方案|规划)|先(?:出|列|做|拟)(?:个|一个|一份)?(?:计划|方案|规划|大纲)|(?:制定|撰写|给出?)(?:一份|一个|个)?(?:详细的?)?(?:计划|规划)|\b(?:plan first|first (?:make|write|provide) (?:a )?plan|(?:make|write|propose|draft|outline) (?:a |the )?plan)\b"),
        ("discuss_first", r"先(?:讨论|沟通|分析|调研|研究|评估|梳理)|\b(?:discuss first|first discuss)\b"),
        ("execute_first", r"(?:^|[，,]\s*)(?:请)?直接(?:开始)?(?:执行|实现|修改|改|动手|做)|\b(?:execute first|start implementing)\b"),
    ),
    "verification_requirements": (
        ("requested", r"(?:运行|执行|跑|补充|补齐|添加|完成|通过|检查|验证|确保).{0,28}(?:测试|检查|构建|单测|pytest|ruff|lint|mypy|typecheck|build|(?<![A-Za-z])tests?(?![A-Za-z]))|\b(?:run|add|write|pass|check|verify)\b.{0,35}\b(?:tests?|pytest|ruff|lint|build|typecheck)\b"
                      r"|(?:仔细|认真|再次|重新)(?:检查|核对|确认|验证|复查)|(?:检查|核对|验证|复查|自测)(?:一下|一遍)?(?:是否|有没有|无误|正确)|确保.{0,24}(?:正确|无误|一致|可运行|能运行|能跑|没有?问题)"
                      r"|\b(?:double[- ]check|make sure .{0,30}\b(?:works?|pass(?:es)?|correct)|verify (?:that|the|it))\b"),
    ),
    "allowed_scope": (
        ("restricted", r"(?:^|[，,]\s*)(?:请)?(?:只(?:能|允许)?|仅(?:限)?)(?:修改|编辑|处理|读取|检查|操作)|(?:^|[，,]\s*)(?:现在)?(?:允许|可以)(?:修改|编辑|读取|处理)|\b(?:only (?:modify|edit|read|change)|you may (?:modify|edit|read))\b"),
    ),
    "prohibited_actions": (
        # v1.3: colloquial imperatives 别/不许/不准/千万不要/切勿 (别人/别的/别处 are nouns).
        ("prohibited", r"(?:^|[，,]\s*)(?:请|你)?(?:千万|一定)?(?:不要|别(?![人的处名称])|禁止|不得|不能|不可|严禁|不许|不准|切勿)|(?:^|[，,]\s*)(?:please )?(?:do not|don't|never)\b"),
    ),
    "acceptance_criteria": (
        ("criterion", r"^(?:验收(?:标准|条件|要求)|完成标准)\s*(?:是|为|[:：])|\bacceptance criteria\s*:"),
    ),
    "format_requirements": (
        ("format", r"(?:请用|使用|(?:^|(?<=[，,]))\s*用|输出为|写成|以(?![前后上下及便免为]|往)).{0,10}(?:表格|列表|JSON|Markdown|分点)|\b(?:output|return|format).{0,24}\b(?:json|markdown|table|list)\b"),
    ),
    "tool_requirements": (
        ("tool", r"(?:使用|调用|用)\s*(?:[\w.]*MCP|pytest|git|bash|ruff|skill|npm|pnpm|yarn|uv|cargo|docker)\b|\buse\s+(?:pytest|git|bash|ruff|[\w.]*mcp|skill|npm|pnpm|yarn|uv|cargo|docker)\b"),
    ),
}
RULES = {field: [(value, re.compile(pattern, re.I)) for value, pattern in rules]
         for field, rules in RULES.items()}
REPORTING = re.compile(
    r"^(?:[-*+]\s+|\d+[.)、]\s*)?(?:示例|例子|例如|比如|举例|引用|日志|文档中|他说|她说|"
    r"我(?:之前|昨天|曾经)|请?(?:解释|翻译|分析).{0,12}(?:这句话|含义)|"
    r"(?:example|quote|the log|he said|she said|translate|explain the phrase)\b)", re.I)
NEGATIVE = re.compile(r"不要|别(?![人的处名称])|不许|不准|切勿|禁止|不得|不能|不可|无需|不必|不用|不需要|没有要求|\b(?:do not|don't|never|not required)\b", re.I)
CONDITION = re.compile(r"如果|除非|只有|若|等.{0,12}确认|确认后|通过后|\b(?:if|unless|when|after|before|until)\b", re.I)
ACTIONS = (
    ("modify", re.compile(r"修改|编辑|\b(?:modify|edit|change)\b", re.I)),
    ("test", re.compile(r"测试|pytest|\btests?\b", re.I)),
    ("push", re.compile(r"推送|\bpush\b", re.I)),
    ("commit", re.compile(r"提交|\bcommit\b", re.I)),
    ("deploy", re.compile(r"部署|\bdeploy\b", re.I)),
    ("check", re.compile(r"检查|\bcheck\b", re.I)),
    ("process", re.compile(r"处理|\bprocess\b", re.I)),
    ("operate", re.compile(r"操作|\boperate\b", re.I)),
    ("read", re.compile(r"读取|\bread\b", re.I)),
)


def _clauses(text):
    # A dot inside a path must not split a filename.
    text = re.sub(r"(?m)^\s*(?:[-*+]\s+|\d+[.)、]\s*)", "", text)
    for part in re.split(r"[。；;！!？?\n]+|\.(?=\s|$)", text):
        part = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)", "", part).strip()
        if part and not REPORTING.search(part):
            # Independent commands separated by a comma have independent polarity.
            boundary = re.compile(
                r"[，,]\s*(?=(?:请|不要|禁止|只(?:能)?修改|仅修改|先|使用|直接|运行|验收标准|"
                r"等(?:我|用户)|如果|除非|只有|若|然后|"
                r"please\b|do not\b|run\b|use\b|wait\b|if\b|unless\b|when\b|then\b))", re.I)
            start = 0
            for match in boundary.finditer(part):
                # A leading condition keeps its dependent command. A later
                # condition starts a new command, never qualifying the prior one.
                preceding = part[start:match.start()]
                if not CONDITION.search(file_pattern().sub("", preceding)):
                    yield preceding
                    start = match.end()
            yield part[start:]


def _request_prefix(clause, start):
    """Reject narrative/metalinguistic prefixes before a matched directive."""
    prefix = re.split(r"[，,]", clause[:start])[-1].strip()
    if CONDITION.search(prefix):
        return True
    return bool(re.fullmatch(
        r"(?:(?:请你?|你(?:要|需要|得|应该|必须)|一定要|千万|必须|务必|需要你?|记得要?|然后|再|并且|并|还要|提交前|"
        r"修改后|改完(?:之?后)?|做完(?:之?后)?|完成(?:之?后)|执行后|确认后|最后|先|现在)\s*)*|"
        r"(?:(?:please|you must|you should|then|first)\s*)*", prefix, re.I))


def extract_instruction_constraints(messages, *, main_ids):
    """Return one observation per confirmed human message in an explicit main set.

    Empty fields are unknown (None), not a claim that no requirement exists.
    Canonical replay duplicates are excluded here as well as by the engine selector.
    """
    records, seen = [], set()
    lookup = {(e["session_uid"], e["event_uid"]): e for e in messages}
    for event in sorted(messages, key=lambda e: (e["session_uid"], e["seq"], e["event_uid"])):
        attrs = event.get("attrs", {})
        identity = (event["session_uid"], event["event_uid"])
        if (identity in seen or event["kind"] != "message.user"
                or event["session_uid"] not in main_ids
                or event.get("actor") not in ("human", "user") or attrs.get("origin") != "human"
                or attrs.get("replayed_from") or attrs.get("duplicate_of")):
            continue
        seen.add(identity)
        text = instruction_text(event.get("text"))
        constraints, matched = [], set()
        for clause in _clauses(text):
            targets = sorted({m[0] for m in file_pattern().finditer(clause)})
            # Filenames such as if.py are objects, not linguistic conditions.
            match_text = file_pattern().sub(lambda m: " " * len(m[0]), clause)
            condition = clause if CONDITION.search(match_text) else None
            for feature, rules in RULES.items():
                for value, pattern in rules:
                    match = pattern.search(match_text)
                    if match is None or not _request_prefix(clause, match.start()):
                        continue
                    # Negated checks/format/tool requests are prohibitions, never positives.
                    if feature == "verification_requirements" and RULES["acceptance_criteria"][0][1].search(clause):
                        continue
                    if feature in ("requested_autonomy", "execution_order") and NEGATIVE.search(clause[:match.start()]):
                        continue
                    if feature in ("verification_requirements", "format_requirements", "tool_requirements"):
                        if NEGATIVE.search(clause[:match.end()]):
                            continue
                    if feature == "requested_autonomy" and value == "explicit" and condition:
                        continue
                    key = (feature, value, clause)
                    if key in matched:
                        continue
                    matched.add(key)
                    constraints.append({
                        "constraint_uid": stable_id(INSTRUCTION_VERSION, *identity, *key),
                        "feature": feature, "value": value, "text": clause,
                        "event_uid": event["event_uid"], "session_uid": event["session_uid"],
                        "task_id": attrs.get("task_id"), "seq": event["seq"], "ts": event.get("ts"),
                        "targets": targets or None, "condition": condition,
                        "action": next((name for name, rule in ACTIONS if rule.search(match_text)), None),
                        "source": "confirmed_human_text", "method": "explicit_lexical_rule",
                        **(format_arguments(match.group()) if feature == "format_requirements" else {}),
                    })
        semantic = observation_for(event, lookup)
        for item in (semantic or {}).get("controls", []):
            arguments = dict(item["arguments"])
            existing = next((c for c in constraints if c["feature"] == item["feature"]
                             and c["value"] == item["value"] and item["quote"] in c["text"]
                             and c["condition"] == item["condition"]), None)
            if existing:
                if arguments["response_form"] in (existing.get("format_values") or []):
                    arguments["response_form"] = None
                if not any(arguments.values()):
                    continue
            constraints.append({
                "constraint_uid": stable_id("semantic-control-v1", *identity, item),
                "feature": item["feature"], "value": item["value"], "text": item["quote"],
                "event_uid": event["event_uid"], "session_uid": event["session_uid"],
                "task_id": attrs.get("task_id"), "seq": event["seq"], "ts": event.get("ts"),
                "targets": item["targets"] or None, "condition": item["condition"], "action": None,
                "source": "semantic_model", "method": "bounded_semantic_parser",
                "available_at": semantic["available_at"], "arguments": arguments,
                "confidence": {"tier": "inferred", "calibrated_probability": None},
                "evidence_event_uids": semantic["evidence_event_uids"],
                **({"format_values": [arguments["response_form"]] if arguments["response_form"] else None,
                    "format_relation": "single" if arguments["response_form"] else "unknown",
                    "detail_value": arguments["detail"]} if item["feature"] == "format_requirements" else {}),
            })
        reasons = []
        if event.get("text") is None:
            reasons.append("text_unavailable")
        elif not text:
            reasons.append("no_direct_text")
        elif not constraints:
            reasons.append("no_explicit_signal")
        if event.get("text_truncated"):
            reasons.append("text_truncated")
        records.append({
            "event_uid": event["event_uid"], "session_uid": event["session_uid"],
            "task_id": attrs.get("task_id"), "seq": event["seq"], "ts": event.get("ts"),
            "status": "partial" if event.get("text_truncated") else
            "inferred" if constraints and all(c["source"] == "semantic_model" for c in constraints)
            else "observed" if constraints else "unknown",
            "unknown_reasons": reasons, "constraints": constraints,
            "features": {name: [c for c in constraints if c["feature"] == name] or None for name in FIELDS},
            "supersedes_instruction_ids": list(attrs.get("supersedes_instruction_ids") or []),
            **({"semantic_source": {"model": semantic["model"], "input_digest": semantic["input_digest"],
                                    "available_at": semantic["available_at"]}} if semantic else {}),
        })
    return records


def summarize_control_patterns(instructions, scope=None, *, source_available=True):
    """Message-grain observations within Scope; never a personality or current-policy score."""
    if not source_available:
        return {"status": "unavailable", "message_n": None, "effective_n": 0, "unknown_n": None,
                "features": None, "denominator": "confirmed human messages in selected main sessions"}
    rows = [r for r in instructions if scope is None or scope.contains(r.get("ts"))]
    features = {}
    for name in FIELDS:
        known = [r for r in rows if r["features"][name]]
        values = Counter(value for r in known for value in {c["value"] for c in r["features"][name]})
        features[name] = {
            "effective_n": len(known), "unknown_n": len(rows) - len(known),
            "message_rate": len(known) / len(rows) if rows else None,
            "values": dict(sorted(values.items())),
        }
    effective = sum(bool(r["constraints"]) for r in rows)
    inferred = [r for r in rows if any(c.get("source") == "semantic_model" for c in r["constraints"])]
    quality = {"explicit_messages": sum(any(c.get("source") == "confirmed_human_text" for c in r["constraints"]) for r in rows),
               "inferred_messages": len(inferred), "calibrated_probability": None}
    return {"status": "partial", "message_n": len(rows), "effective_n": effective,
            "unknown_n": len(rows) - effective,
            "truncated_n": sum("text_truncated" in r["unknown_reasons"] for r in rows),
            "time_unknown_n": sum(r.get("ts") is None for r in rows), "features": features,
            "denominator": "confirmed human messages in selected main sessions",
            "semantics": "explicit and model inferred observations, not resolved active instructions" if inferred
            else "observed requests, not resolved active instructions",
            **({"evidence_quality": quality} if inferred else {})}

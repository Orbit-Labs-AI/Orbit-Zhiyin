"""Closed vocabulary of the signal layer: kinds, problem mapping and rule versions.

The mapping mirrors ``docs/plans/analysis-module.md`` §2.4 and is the only place the
backend encodes ``signal.kind → problem.type``. Thresholds change ``RULES_VERSION``.
"""

import re

RULES_VERSION = "signals-v1.0"

EDIT_KINDS = frozenset({"file.edit", "file.write", "file.change"})

# opportunity = which sessions form the AN-06 denominator for this kind.
SIGNAL_KINDS: dict[str, dict] = {
    "correction": {"unit": "message", "friction_type": "misunderstood_request",
                   "problem_type": "misunderstood_request", "opportunity": "human",
                   "stage": "MVP", "basis": "proxy"},
    "frustration": {"unit": "session", "friction_type": "misunderstood_request",
                    "problem_type": "misunderstood_request", "opportunity": "human",
                    "stage": "v1", "basis": "proxy"},
    "retry_loop": {"unit": "turn", "friction_type": "tool_env_failure",
                   "problem_type": "tool_env_failure", "opportunity": "tools",
                   "stage": "MVP", "basis": "measured"},
    "missing_verification": {"unit": "session", "friction_type": "buggy_output",
                             "problem_type": "missing_verification", "opportunity": "edits",
                             "stage": "MVP", "basis": "measured"},
    "would_prompt": {"unit": "session", "friction_type": "permission_friction",
                     "problem_type": "permission_friction", "opportunity": "shell",
                     "stage": "MVP", "basis": "measured"},
    "permission_denied": {"unit": "session", "friction_type": "permission_friction",
                          "problem_type": "permission_friction", "opportunity": "human",
                          "stage": "MVP", "basis": "measured"},
    "risky_command": {"unit": "session", "friction_type": "other",
                      "problem_type": "unsafe_operation", "opportunity": "human",
                      "stage": "MVP", "basis": "proxy"},
    "interruption": {"unit": "turn", "friction_type": "process_overhead",
                     "problem_type": None, "opportunity": "human",
                     "stage": "MVP", "basis": "measured"},
}

PROBLEM_TYPES: dict[str, dict] = {
    "repeated_instruction": {"min_sessions": 2, "remedies": ["rule", "hook", "prompt"]},
    "communication_gap": {"min_sessions": 3, "remedies": ["skill", "rule", "output_style"]},
    "repeated_workflow": {"min_sessions": 3, "remedies": ["skill", "plugin", "subagent"]},
    "missing_verification": {"min_sessions": 3, "remedies": ["rule", "hook", "subagent"]},
    "tool_env_failure": {"min_sessions": 3, "remedies": ["hook", "skill", "rule"]},
    "permission_friction": {"min_sessions": 3, "remedies": ["permission_rule", "builtin", "hook"]},
    "context_loss": {"min_sessions": 3, "remedies": ["rule", "skill", "workflow"]},
    "parallel_conflict": {"min_sessions": 2, "remedies": ["workflow"]},
    "quota_interrupt": {"min_sessions": 3, "remedies": ["model", "workflow"]},
    "process_overhead": {"min_sessions": 3, "remedies": ["subagent", "plugin", "rule"]},
    "unsafe_operation": {"min_sessions": 1, "remedies": ["hook", "permission_rule"]},
    "misunderstood_request": {"min_sessions": 3, "remedies": ["prompt", "workflow"]},
}

WILSON_LO_MIN = 0.05
SCOPES = ("all", "project", "source")

CORRECTION_CHARS = (5, 200)
FRUSTRATION = re.compile(
    r"算了|别弄了|怎么又|又错了|第几次|烦死|好烦|seriously|again\?!|\bugh\b", re.I)

# Read-only shell heads (契约 §4.2 command.readonly); compared on the normalized head.
READONLY_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "pwd", "wc", "rg", "grep", "find", "tree", "stat", "file",
    "which", "echo", "du", "df", "env", "date", "git status", "git log", "git diff",
    "git show", "git branch", "git rev-parse", "git ls-files",
})

# DT-13 destructive command families; matched on command head and argument text.
RISKY_COMMANDS: tuple[tuple[str, re.Pattern], ...] = (
    ("rm_recursive_force", re.compile(r"\brm\s+(?:-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-r\s+-f|-f\s+-r)", re.I)),
    ("git_push_force", re.compile(r"\bgit\s+push\b.*(?:--force\b|\s-f\b|--force-with-lease)", re.I)),
    ("git_reset_hard", re.compile(r"\bgit\s+reset\s+--hard\b", re.I)),
    ("git_clean_force", re.compile(r"\bgit\s+clean\s+-[a-z]*f", re.I)),
    ("sql_drop", re.compile(r"\bdrop\s+(?:table|database|schema)\b", re.I)),
    ("disk_format", re.compile(r"\b(?:mkfs(?:\.\w+)?|dd\s+if=)", re.I)),
    ("chmod_recursive_777", re.compile(r"\bchmod\s+-R\s+0?777\b", re.I)),
)

MOMENT_KINDS = ("goal", "correction", "failure_streak", "verify_pass", "compaction", "end")
MAX_MOMENTS = 8
OUTCOMES = ("completed", "partial", "failed", "abandoned", "unknown")
OUTCOME_BASES = ("explicit_feedback", "verify_pass", "verify_fail", "facet", "structural",
                 "unknown")

FIELDS = {
    "signals_summary": {"family": "signals", "unit": "session",
                        "meaning": "每类 signal 在该根会话树的次数；null = 证据不可用，0 = 有覆盖且未出现",
                        "rules_version": RULES_VERSION},
    "outcome": {"family": "signals", "unit": "session", "values": list(OUTCOMES),
                "meaning": "AN-19 合成结果；取不到证据时为 unknown"},
    "outcome_basis": {"family": "signals", "unit": "session", "values": list(OUTCOME_BASES)},
    "verify_ran": {"family": "signals", "unit": "session",
                   "meaning": "存在已执行验证（validation_runs 非空）；调用不可用为 null"},
    "verify_pass": {"family": "signals", "unit": "session",
                    "meaning": "最后一次已执行验证为 passed；无验证为 null"},
    "verify_candidate": {"family": "signals", "unit": "session", "basis": "proxy",
                         "meaning": "只命中 command_head 的验证候选数"},
    "verify_requested": {"family": "signals", "unit": "session",
                         "meaning": "真人约束中提出验证要求；无指令记录为 null"},
    "autonomy_steps": {"family": "signals", "unit": "session",
                       "meaning": "含真人消息轮次的观测步数（工具调用 + 最终交付）中位数"},
}

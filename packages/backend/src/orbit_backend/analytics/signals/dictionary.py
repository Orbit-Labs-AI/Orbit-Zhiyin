"""Closed vocabulary of the signal layer: kinds, problem mapping and rule versions.

The mapping mirrors ``docs/plans/analysis-module.md`` §2.4 and is the only place the
backend encodes ``signal.kind → problem.type``. Thresholds change ``RULES_VERSION``.
"""

import re

from ..common import MIN_STATUS_COVERAGE
from ..interaction.rules import CORRECTION_CHARS as _CORRECTION_CHARS
from ..lexicon import POSITIVE_CLAUSE_CHARS, POSITIVE_CLAUSE_WORDS

RULES_VERSION = "signals-v1.3"  # 1.3: edits include calls whose file_ops write a file

EDIT_KINDS = frozenset({"file.edit", "file.write", "file.change"})
# ``tool_call_file.op`` values that change a file (``unknown`` = a path was only named).
WRITE_OPS = frozenset({"add", "update", "delete", "move"})


def is_edit_call(call: dict) -> bool:
    """An edit tool, or any call (e.g. a shell ``apply_patch``) whose reported file
    operations (``file_ops`` from ``tool_call_file``) write a file."""
    if call.get("kind") in EDIT_KINDS:
        return True
    return any(isinstance(f, dict) and f.get("op") in WRITE_OPS
               for f in call.get("file_ops") or ())

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

# Problem upgrade gate: ``sessions >= min_sessions`` and ``wilson_lo(sessions, denom) >
# WILSON_LO_MIN``. The previous 0.05 had no source and made rare-but-important types
# unreachable (wilson_lo(1/20)=0.009, (3/60)=0.017, (5/100)=0.022: only shares above ~15%
# could ever upgrade). A problem is a repeated behaviour, not a prevalence claim, so the
# repeat requirement lives in ``min_sessions`` and the Wilson bound only asks that the
# 95% interval excludes zero. A type may set ``wilson_lo_min`` to a measured background
# rate once real-distribution calibration exists; none is calibrated yet.
WILSON_LO_MIN = 0.0
SCOPES = ("all", "project", "source")

# Direct characters of a correction candidate: defined once with the verdict in
# ``interaction.rules`` (re-exported here for the threshold table).
CORRECTION_CHARS = _CORRECTION_CHARS
# Frustration reuses ``analytics.lexicon.emotion_cues`` (negation/hypothetical aware);
# a short-correction streak is "two consecutive corrections of at most this many chars".
FRUSTRATION_STREAK_CHARS = 40

# Read-only shell heads (契约 §4.2 command.readonly); compared on the normalized head of
# every segment. A head alone is not enough: the argument checks below reject the forms
# of these programs that write or execute (``find -delete``, ``git branch -D``,
# ``echo x > f``, ``env FOO=1 cmd``).
READONLY_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "pwd", "wc", "rg", "grep", "find", "tree", "stat", "file",
    "which", "echo", "du", "df", "env", "date", "git status", "git log", "git diff",
    "git show", "git branch", "git rev-parse", "git ls-files",
})
# Segments that only change shell state; they neither read nor write project files.
STATE_ONLY_COMMANDS = frozenset({"cd", "pushd", "popd"})
# find(1) actions that delete, run commands or write files.
FIND_WRITE_ACTIONS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint",
                                "-fprint0", "-fprintf", "-fls"})
# git-branch(1) options that create, delete, rename, copy or re-track branches.
GIT_BRANCH_WRITE = frozenset({"-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy",
                              "-f", "--force", "-u", "--set-upstream-to", "--unset-upstream",
                              "--edit-description", "-t", "--track", "--no-track"})
# With one of these a positional argument is a pattern/commit filter, not a new branch name.
GIT_BRANCH_LIST = frozenset({"-l", "--list", "--contains", "--no-contains", "--merged",
                             "--no-merged", "--points-at"})
# Output redirections that write a file (``2>&1``/``>&`` duplicate descriptors instead).
WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>"})

# DT-13 destructive command families.
# rm: recursive + force only counts when a target is the filesystem root, the home
# directory, a parent directory, a top-level absolute directory or a wildcard outside the
# usual regenerable build/cache directories (``rm -rf node_modules`` is routine cleanup).
RM_DANGEROUS_TARGETS = frozenset({"/", "~", "$HOME", "${HOME}", ".."})
RM_REGENERABLE_DIRS = frozenset({"node_modules", "dist", "build", ".venv", "__pycache__", "target",
                                 ".cache"})
# SQL DROP only counts when it reaches a database client (argument, pipe or heredoc);
# writing a migration file that contains DROP is not executing it.
SQL_CLIENTS = frozenset({"sqlite3", "psql", "mysql", "mariadb", "duckdb", "sqlcmd",
                         "clickhouse-client"})
SQL_DROP = re.compile(r"\bdrop\s+(?:table|database|schema)\b", re.I)
# Remaining families are matched on the full command text.
RISKY_COMMANDS: tuple[tuple[str, re.Pattern], ...] = (
    ("git_push_force", re.compile(r"\bgit\s+push\b.*(?:--force\b|\s-f\b|--force-with-lease)", re.I)),
    ("git_reset_hard", re.compile(r"\bgit\s+reset\s+--hard\b", re.I)),
    ("git_clean_force", re.compile(r"\bgit\s+clean\s+-[a-z]*f", re.I)),
    ("disk_format", re.compile(r"\b(?:mkfs(?:\.\w+)?|dd\s+if=)", re.I)),
    ("chmod_recursive_777", re.compile(r"\bchmod\s+-R\s+0?777\b", re.I)),
)

MOMENT_KINDS = ("goal", "correction", "failure_streak", "verify_pass", "compaction", "end")
MAX_MOMENTS = 8
# retry_loop: a same-argument retry chain of at least this many calls with at least this many
# failed results (``detect_retry_loop``).
RETRY_LOOP_MIN_CHAIN = 3
RETRY_LOOP_MIN_FAILURES = 3
# Problem ``weekly`` frequency: occurrences in the last N weeks before the reference time / N.
WEEKLY_WINDOW_WEEKS = 4

PRODUCT_DEFAULT = "产品默认，未校准（无真实分布或标注集依据）"
# Every numeric threshold of the signal layer and the lexical rules it reuses, with its source.
# ``calibrated`` is True only when the value comes from a measured distribution or a cited
# method; everything else is an explicit, uncalibrated product default (audit B11).
THRESHOLDS: dict[str, dict] = {
    "correction_chars": {
        "value": CORRECTION_CHARS, "calibrated": False, "where": "interaction.rules.CORRECTION_CHARS",
        "source": PRODUCT_DEFAULT + "；2 = 最短中文否定（「错了」「不对」），200 沿用原 ai.pack 上限"},
    "frustration_streak_chars": {
        "value": FRUSTRATION_STREAK_CHARS, "calibrated": False, "where": "detectors.detect_frustration",
        "source": PRODUCT_DEFAULT + "；连续两条 ≤40 字的纠偏/结果反馈"},
    "retry_loop_min_chain": {
        "value": RETRY_LOOP_MIN_CHAIN, "calibrated": False, "where": "detectors.detect_retry_loop",
        "source": PRODUCT_DEFAULT},
    "retry_loop_min_failures": {
        "value": RETRY_LOOP_MIN_FAILURES, "calibrated": False, "where": "detectors.detect_retry_loop",
        "source": PRODUCT_DEFAULT},
    "max_moments": {
        "value": MAX_MOMENTS, "calibrated": False, "where": "moments.key_moments",
        "source": PRODUCT_DEFAULT + "；会话详情时间线的展示预算"},
    "weekly_window_weeks": {
        "value": WEEKLY_WINDOW_WEEKS, "calibrated": False, "where": "problems.upgrade_problems",
        "source": PRODUCT_DEFAULT},
    "problem_min_sessions": {
        "value": {k: v["min_sessions"] for k, v in PROBLEM_TYPES.items()}, "calibrated": False,
        "where": "PROBLEM_TYPES[*].min_sessions",
        "source": PRODUCT_DEFAULT + "；unsafe_operation=1 因单次即需提示"},
    "wilson_lo_min": {
        "value": WILSON_LO_MIN, "calibrated": True, "where": "problems.upgrade_problems",
        "source": "95% Wilson 得分区间（Wilson 1927，z=1.96）下界 > 0，即区间不含 0；不设背景率"},
    "min_status_coverage": {
        "value": MIN_STATUS_COVERAGE, "calibrated": False, "where": "common.MIN_STATUS_COVERAGE",
        "source": PRODUCT_DEFAULT + "；已知状态不足一半时失败率不具代表性"},
    "positive_clause_chars_words": {
        "value": (POSITIVE_CLAUSE_CHARS, POSITIVE_CLAUSE_WORDS), "calibrated": False,
        "where": "lexicon.emotion_cues", "source": PRODUCT_DEFAULT + "；正向情绪只认短感叹子句"},
}
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
    "problem_upgrade": {"family": "signals", "unit": "problem", "rules_version": RULES_VERSION,
                        "meaning": "sessions ≥ PROBLEM_TYPES.min_sessions 且 wilson_lo(sessions, denom) > "
                                   "wilson_lo_min（默认 0，即 95% 区间不含 0）；重复门槛由 min_sessions 承担，"
                                   "未用无来源的流行率阈值，基线阈值待真实分布校准后按类型设置"},
    "autonomy_steps": {"family": "signals", "unit": "session",
                       "meaning": "含真人消息轮次的观测步数（工具调用 + 最终交付）中位数"},
}

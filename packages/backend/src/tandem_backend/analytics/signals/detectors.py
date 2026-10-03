"""AN-05 detector adapters: family facts of one root session tree → ``signal`` rows.

Each detector is a pure function ``detect_<kind>(view) -> list[signal] | None``:
``None`` means the evidence is unavailable (legacy or missing dataset) and must not be
counted as zero; ``[]`` means the evidence was observed and nothing fired. One signal is
emitted per ``(session, kind, key)``; ``value`` keeps the number of occurrences.
"""

import json
import re
import shlex
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from ...models import stable_id
from ...privacy import direct_user_text
from ...profiling.bottlenecks import _expected_failure
from ..common import clauses, human
from ..context import AnalysisContext
from ..interaction.rules import QUOTED, correction_kind, correction_terms
from ..lexicon import emotion_cues
from .dictionary import (
    EDIT_KINDS,
    FIND_WRITE_ACTIONS,
    FRUSTRATION_STREAK_CHARS,
    GIT_BRANCH_LIST,
    GIT_BRANCH_WRITE,
    READONLY_COMMANDS,
    RETRY_LOOP_MIN_CHAIN,
    RETRY_LOOP_MIN_FAILURES,
    RISKY_COMMANDS,
    RM_DANGEROUS_TARGETS,
    RM_REGENERABLE_DIRS,
    RULES_VERSION,
    SIGNAL_KINDS,
    SQL_CLIENTS,
    SQL_DROP,
    STATE_ONLY_COMMANDS,
    WRITE_REDIRECTS,
)

Record = dict[str, Any]


@dataclass
class SessionView:
    """Everything the detectors may read for one root session tree."""

    session: Record
    member_ids: list[str]
    main_ids: set[str]
    events: list[Record] | None
    calls: list[Record] | None
    retry_links: list[Record] | None
    validation_runs: list[Record] | None
    validation_candidates: list[Record] | None
    turns: list[Record] | None
    supported_kinds: set[str] | None
    inventory: list[Record] | None
    instruction_records: list[Record] | None = None
    context_events: list[Record] = field(default_factory=list)
    families: Record = field(default_factory=dict)

    @property
    def session_uid(self) -> str:
        return self.session["session_uid"]

    @property
    def legacy(self) -> bool:
        return self.supported_kinds is not None


def build_views(context: AnalysisContext, result: Record | None = None) -> list[SessionView]:
    """One view per non-agent root row, reusing family results already in ``result``."""
    rows = {r["session_uid"]: r for r in (result or {}).get("sessions", [])}
    bundle, scope = context.bundle, context.scope
    views = []
    for s in context.sessions:
        if s.get("kind") in ("subagent", "workflow_agent"):
            continue
        sid = s["session_uid"]
        included = {sid} | (context.children[sid] if scope.include_children else set())
        members = sorted(included)
        row = rows.get(sid)
        families = row["bottleneck_features"] if row else context.families(included)
        respond, outcome = families["respond"], families["outcome"]
        events = None if bundle.events is None else [
            e for m in members
            for e in sorted(context.event_groups.get(m, []), key=lambda e: (e["seq"], e["event_uid"]))]
        turns = None if bundle.turns is None else [t for t in bundle.turns if t["session_uid"] in included]
        instruction = (row or {}).get("instruction") or {}
        views.append(SessionView(
            session=s, member_ids=members, main_ids=context.main_ids, events=events,
            calls=respond.get("tool_sequence"), retry_links=respond.get("retry_links"),
            validation_runs=outcome.get("validation_runs"),
            validation_candidates=outcome.get("validation_candidates"), turns=turns,
            supported_kinds=context.supported_kinds, inventory=bundle.inventory,
            instruction_records=instruction.get("records"), families=families,
            context_events=[e for m in members for e in context.context_groups.get(m, [])]))
    return views


# ---------------------------------------------------------------- helpers


def _signal(view: SessionView, kind: str, key: str, occurrences: list[Record], *,
            problem_type: str | None = None, basis: str | None = None,
            evidence: Record | None = None) -> Record:
    spec, first = SIGNAL_KINDS[kind], occurrences[0]
    anchor = first.get("event_uid") or first.get("call_uid")
    return {"signal_id": stable_id(view.session_uid, kind, anchor),
            "session_uid": view.session_uid, "member_session_uid": first["session_uid"],
            "kind": kind, "key": key, "unit": spec["unit"], "value": len(occurrences),
            "friction_type": spec["friction_type"],
            "problem_type": problem_type if problem_type is not None else spec["problem_type"],
            "rules_version": RULES_VERSION, "basis": basis or spec["basis"],
            "event_uid": first.get("event_uid"), "call_uid": first.get("call_uid"),
            "seq": first.get("seq"), "ts": first.get("ts"),
            "occurrences": occurrences, "evidence": evidence or {}}


def _event_occurrence(e: Record, **extra) -> Record:
    return {"session_uid": e["session_uid"], "event_uid": e["event_uid"], "call_uid": None,
            "seq": e.get("seq"), "ts": e.get("ts"), **extra}


def _call_occurrence(c: Record, **extra) -> Record:
    return {"session_uid": c["session_uid"], "event_uid": c.get("call_event_uid"),
            "call_uid": c["call_uid"], "seq": c.get("seq"), "ts": c.get("started_at"), **extra}


def _human_messages(view: SessionView) -> list[Record]:
    return [e for e in view.events or [] if human(e, view.main_ids)
            and not e.get("attrs", {}).get("replayed_from")
            and not e.get("attrs", {}).get("duplicate_of")]


def normalized_head(call: Record) -> str | None:
    """``git status`` keeps its subcommand; other commands keep the program name."""
    head = (call.get("command_head") or "").strip().lower()
    if not head:
        return None
    parts = head.split()
    program = PurePosixPath(parts[0]).name
    if program == "git" and len(parts) > 1:
        return f"git {parts[1]}"
    return program


def call_text(call: Record) -> str:
    """Command head plus argument text for vocabulary checks; never leaves this module."""
    parts = [call.get("command_head") or "", call.get("command") or ""]
    args = call.get("arguments", call.get("input"))
    if isinstance(args, dict):
        args = args.get("command") or args.get("cmd") or json.dumps(args, ensure_ascii=False)
    if isinstance(args, list):
        args = " ".join(str(a) for a in args)
    if isinstance(args, str):
        parts.append(args)
    return " ".join(p for p in parts if p)


def call_files(call: Record) -> list[str]:
    files = call.get("files") or []
    if isinstance(files, str):
        try:
            files = json.loads(files)
        except ValueError:
            files = [files]
    return [f if isinstance(f, str) else str(f.get("path", "")) for f in files if f]


def _command_value(value) -> str | None:
    if isinstance(value, dict):
        return _command_value(value.get("command", value.get("cmd")))
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        if len(value) == 3 and PurePosixPath(value[0]).name in ("sh", "bash", "zsh") \
                and value[1] in ("-c", "-lc", "-ic"):
            return value[2]
        return shlex.join(value)
    return value if isinstance(value, str) and value.strip() else None


def command_line(call: Record, event: Record | None = None) -> str:
    """Full command text: L3 arguments, else the ``tool.call`` event input, else the head.

    L3 rows only keep ``command_head`` (program + subcommand) and an argv digest, so the
    arguments that decide read-only / destructive live in the call event's ``attrs.input``.
    """
    attrs = (event or {}).get("attrs") or {}
    for value in (call.get("command"), call.get("arguments", call.get("input")), attrs.get("input"),
                  attrs.get("arguments")):
        text = _command_value(value)
        if text:
            return text
    return call.get("command_head") or ""


def command_pipelines(text: str) -> list[list[list[str]]]:
    """``a | b && c`` → ``[[a, b], [c]]`` with quoting respected; newlines separate commands."""
    lexer = shlex.shlex(text.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        tokens = text.split()
    pipelines, segments, current = [], [], []
    for token in tokens:
        if token in ("&&", "||", ";", "&", ";;", "|", "|&"):
            if current:
                segments.append(current)
            current = []
            if token not in ("|", "|&") and segments:
                pipelines.append(segments)
                segments = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    if segments:
        pipelines.append(segments)
    return pipelines


def _program(segment: list[str]) -> tuple[str, list[str]]:
    """Strip ``sudo`` and leading ``NAME=value`` assignments; return (program, args)."""
    i = 0
    while i < len(segment) and (segment[i] == "sudo" or re.fullmatch(r"[A-Za-z_]\w*=.*", segment[i])):
        i += 1
    if i >= len(segment):
        return "", []
    return PurePosixPath(segment[i]).name.lower(), segment[i + 1:]


def _segment_readonly(segment: list[str]) -> bool | None:
    """True read-only, False writes/executes, None neutral (``cd``)."""
    if any("$(" in t or "`" in t for t in segment):
        return False  # command substitution runs an unknown command
    for i, token in enumerate(segment):
        if token in WRITE_REDIRECTS and (i + 1 >= len(segment) or segment[i + 1] != "/dev/null"):
            return False
    program, args = _program(segment)
    if program in STATE_ONLY_COMMANDS:
        return None
    head = f"git {args[0].lower()}" if program == "git" and args else program
    if head not in READONLY_COMMANDS:
        return False
    if program == "find":
        return not FIND_WRITE_ACTIONS & set(args)
    if head == "git branch":
        rest = args[1:]
        positional = [a for a in rest if not a.startswith("-")]
        return not GIT_BRANCH_WRITE & set(rest) and (not positional or bool(GIT_BRANCH_LIST & set(rest)))
    if program == "env":
        # env with only options/assignments prints the environment; anything else runs a command.
        return all(a.startswith("-") or re.fullmatch(r"[A-Za-z_]\w*=.*", a) for a in args)
    return True


def is_readonly_command(text: str) -> bool:
    """Every segment is a read-only command (state-only ``cd`` segments are neutral)."""
    if "$(" in text or "`" in text or "<(" in text:
        return False  # command/process substitution runs an unknown command
    verdicts = [_segment_readonly(seg) for pipe in command_pipelines(text) for seg in pipe]
    real = [v for v in verdicts if v is not None]
    return bool(real) and all(real)


def _rm_target_dangerous(target: str) -> bool:
    t = target.rstrip("/") or "/"
    if t in RM_DANGEROUS_TARGETS or all(part == ".." for part in t.split("/")):
        return True
    path = PurePosixPath(t)
    if path.is_absolute() and len(path.parts) <= 2:  # "/", "/usr", "/etc" ...
        return True
    return any(ch in t for ch in "*?[") and not set(path.parts) & RM_REGENERABLE_DIRS


def _rm_recursive_force(args: list[str]) -> bool:
    recursive = force = False
    targets, options = [], True
    for a in args:
        if options and a == "--":
            options = False
        elif options and a.startswith("--"):
            recursive |= a == "--recursive"
            force |= a == "--force"
        elif options and a.startswith("-") and len(a) > 1:
            recursive |= bool(set(a[1:]) & {"r", "R"})
            force |= "f" in a[1:]
        else:
            targets.append(a)
    return recursive and force and any(_rm_target_dangerous(t) for t in targets)


_HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\1\b", re.S)


def _sql_drop_executed(text: str) -> bool:
    if not SQL_DROP.search(text):
        return False
    for pipeline in command_pipelines(_HEREDOC.sub(" ", text)):
        programs = [_program(seg) for seg in pipeline]
        if any(p in SQL_CLIENTS for p, _ in programs) and any(
                SQL_DROP.search(" ".join([p, *args])) for p, args in programs):
            return True
    # heredoc bodies fed to a client: ``sqlite3 db <<EOF ... DROP TABLE ... EOF``
    for match in _HEREDOC.finditer(text):
        line = text[:match.start()].rsplit("\n", 1)[-1]
        if SQL_DROP.search(match.group(2)) and any(
                _program(seg)[0] in SQL_CLIENTS for pipe in command_pipelines(line) for seg in pipe):
            return True
    return False


def risky_family(text: str) -> str | None:
    """DT-13 family of one command line, or None."""
    for pipeline in command_pipelines(text):
        for segment in pipeline:
            program, args = _program(segment)
            if program == "rm" and _rm_recursive_force(args):
                return "rm_recursive_force"
    if _sql_drop_executed(text):
        return "sql_drop"
    for family, pattern in RISKY_COMMANDS:
        if pattern.search(text):
            return family
    return None


def allowed_heads(inventory: list[Record] | None) -> set[str] | None:
    """Installed allow rules such as ``Bash(ls:*)``; ``None`` when inventory is unknown."""
    if inventory is None:
        return None
    heads = set()
    for item in inventory:
        config = item.get("config") or {}
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except ValueError:
                continue
        rules = (config.get("permissions") or {}).get("allow") or config.get("allow") or []
        for rule in rules if isinstance(rules, list) else []:
            match = re.match(r"Bash\(([^):*]+)", str(rule))
            if match:
                normalized = normalized_head({"command_head": match.group(1)})
                if normalized:
                    heads.add(normalized)
    return heads


def _order(row: Record) -> tuple:
    return (row.get("seq") if row.get("seq") is not None else -1, row.get("call_uid") or "")


# ---------------------------------------------------------------- AN-05.1


def detect_correction(view: SessionView) -> list[Record] | None:
    """Lexical correction proxy between assistant replies: ``interaction.rules.correction_kind``
    is ``correction`` (its ``CORRECTION_CHARS`` gate included); result feedback alone
    ("还是不行，测试依然失败") is not a correction."""
    if view.events is None:
        return None
    responded, occurrences = set(), []
    for e in view.events:
        if e["kind"] in ("message.assistant", "tool.call"):
            responded.add(e["session_uid"])
            continue
        if not human(e, view.main_ids) or e.get("attrs", {}).get("replayed_from") \
                or e.get("attrs", {}).get("duplicate_of") or e["session_uid"] not in responded:
            continue
        raw = e.get("text") or ""
        if correction_kind(raw) == "correction":
            occurrences.append(_event_occurrence(e, terms=correction_terms(raw),
                                                 chars=len(direct_user_text(raw))))
    return [_signal(view, "correction", "correction:session", occurrences,
                    problem_type="misunderstood_request")] if occurrences else []


def detect_frustration(view: SessionView) -> list[Record] | None:
    """v1 lexical proxy: a negative emotion cue (``lexicon.emotion_cues``) or two short
    corrections in a row. Quoted material never counts."""
    if view.events is None:
        return None
    hits, streak = [], []
    for e in _human_messages(view):
        text = direct_user_text(e.get("text") or "")
        if any(emotion_cues(c)[1] for c in clauses(QUOTED.sub("", text))):
            hits.append(_event_occurrence(e, reason="emotion_cue"))
            streak = []
            continue
        # A short streak of corrections or "still failing" result feedback both count.
        if len(text) <= FRUSTRATION_STREAK_CHARS and correction_kind(text):
            streak.append(e)
            if len(streak) == 2:
                hits.append(_event_occurrence(e, reason="short_correction_streak"))
                streak = []
        else:
            streak = []
    return [_signal(view, "frustration", "frustration:session", hits)] if hits else []


# ---------------------------------------------------------------- AN-05.2


def _expected_failure_context(view: SessionView, call: Record) -> bool:
    humans = [e for e in _human_messages(view) if e["session_uid"] == call["session_uid"]]
    if call.get("turn_uid"):
        texts = [e.get("text") or "" for e in humans if e.get("turn_uid") == call["turn_uid"]]
    else:
        before = [e for e in humans if call.get("seq") is not None and e["seq"] < call["seq"]]
        texts = [before[-1].get("text") or ""] if before else []
    return bool(texts) and _expected_failure("\n".join(texts))


def detect_retry_loop(view: SessionView) -> list[Record] | None:
    """Adapter over ``respond.retry_links``: a same-argument chain of ``RETRY_LOOP_MIN_CHAIN``
    calls with ``RETRY_LOOP_MIN_FAILURES`` failures (see ``dictionary.THRESHOLDS``)."""
    if view.calls is None or view.retry_links is None:
        return None
    by_uid = {c["call_uid"]: c for c in view.calls}
    eligible, unresolved = {}, 0
    for link in view.retry_links:
        a, b = by_uid.get(link["from_call_uid"]), by_uid.get(link["to_call_uid"])
        same_turn = bool(a and b and a.get("turn_uid") and a.get("turn_uid") == b.get("turn_uid"))
        missing = set(link.get("missing") or [])
        identity = "task_identity" not in missing or same_turn
        if (link.get("same_arguments") is True and identity
                and not missing & {"status_scope", "argument_digest_identity"}):
            eligible[link["from_call_uid"]] = link["to_call_uid"]
        elif link.get("same_arguments") is not False:
            unresolved += 1
    targets = set(eligible.values())
    groups, expected = defaultdict(list), 0
    for start in sorted(set(eligible) - targets, key=lambda uid: _order(by_uid[uid])):
        chain = [start]
        while chain[-1] in eligible and eligible[chain[-1]] not in chain:
            chain.append(eligible[chain[-1]])
        calls = [by_uid[uid] for uid in chain]
        failures = sum(c.get("tool_result_status") == "failed" for c in calls)
        if len(chain) < RETRY_LOOP_MIN_CHAIN or failures < RETRY_LOOP_MIN_FAILURES:
            continue
        if _expected_failure_context(view, calls[0]):
            expected += 1
            continue
        head = normalized_head(calls[0]) or calls[0].get("name_raw") or "unknown"
        groups[head].append(_call_occurrence(calls[0], chain=chain, failures=failures))
    if not groups and unresolved:
        return None
    return [_signal(view, "retry_loop", f"retry_loop:{head}", occ,
                    evidence={"expected_failure_chains": expected})
            for head, occ in sorted(groups.items())]


def detect_missing_verification(view: SessionView) -> list[Record] | None:
    """Last edit with no executed validation before the session ends."""
    if view.calls is None or view.validation_runs is None or view.legacy:
        return None
    edits = [c for c in view.calls if c.get("kind") in EDIT_KINDS
             and c.get("tool_result_status") != "rejected"]
    if not edits:
        return []
    if any(c.get("seq") is None for c in edits):
        return None
    last = max(edits, key=lambda c: (c.get("started_at") or 0, _order(c)))

    def after(row_session, row_seq, row_ts):
        if row_session == last["session_uid"]:
            return row_seq is not None and row_seq > last["seq"]
        return row_ts is not None and last.get("started_at") is not None and row_ts > last["started_at"]

    by_uid = {c["call_uid"]: c for c in view.calls}
    runs = [r for r in view.validation_runs
            if after(r["session_uid"], r.get("seq"), (by_uid.get(r["call_uid"]) or {}).get("started_at"))]
    if runs:
        return []
    pending = [v for v in view.validation_candidates or []
               if (c := by_uid.get(v["call_uid"])) and after(c["session_uid"], c.get("seq"), c.get("started_at"))]
    if pending:
        return None
    exts = Counter(PurePosixPath(f).suffix.lstrip(".").lower() or None
                   for c in edits for f in call_files(c))
    exts.pop(None, None)
    sub = sorted(exts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if exts else "project"
    return [_signal(view, "missing_verification", f"missing_verification:{sub}",
                    [_call_occurrence(last)], evidence={"edit_calls": len(edits)})]


def _call_events(view: SessionView) -> dict[str, Record]:
    return {e["event_uid"]: e for e in view.events or [] if e["kind"] == "tool.call"}


def _prompted(call: Record) -> bool:
    return call.get("approval") is not None or call.get("approval_wait_ms") is not None


def detect_would_prompt(view: SessionView) -> list[Record] | None:
    """Read-only shell commands that actually waited for an approval prompt.

    Evidence is the call-level ``approval`` / ``approval_wait_ms`` the reducer copies from
    ``permission.request/decision`` events, not a session permission mode (no connector
    records one). Without any approval data for the session the answer is unknown.
    """
    if view.calls is None:
        return None
    events = _call_events(view)
    readonly = [c for c in view.calls if c.get("kind") == "shell" and not c.get("is_wrapper")
                and is_readonly_command(command_line(c, events.get(c.get("call_event_uid"))))]
    if not readonly:
        return []
    observed = any(_prompted(c) for c in view.calls) or any(
        e["kind"] in ("permission.request", "permission.decision") for e in view.events or [])
    if not observed:
        return None
    allowed = allowed_heads(view.inventory)
    hits = [c for c in sorted(readonly, key=_order) if _prompted(c)
            and (allowed is None or normalized_head(c) not in allowed)]
    if not hits:
        return []
    return [_signal(view, "would_prompt", "would_prompt:readonly_shell",
                    [_call_occurrence(c, head=normalized_head(c), approval=c.get("approval"),
                                      approval_wait_ms=c.get("approval_wait_ms")) for c in hits],
                    basis="measured",
                    evidence={"allow_rules": "unavailable" if allowed is None else sorted(allowed)})]


def detect_permission_denied(view: SessionView) -> list[Record] | None:
    events_known = view.events is not None and (
        view.supported_kinds is None or any(k.startswith("permission.") for k in view.supported_kinds))
    calls_known = view.calls is not None and any("approval" in c for c in view.calls)
    if not events_known and not calls_known:
        return None
    groups, covered = defaultdict(list), set()
    for c in sorted(view.calls or [], key=_order):
        if str(c.get("approval") or "").lower() in ("declined", "denied", "deny"):
            covered |= {c["call_uid"], c.get("native_call_id"), c.get("call_event_uid")}
            groups[normalized_head(c) or c.get("name_raw") or "unknown"].append(_call_occurrence(c))
    for e in view.events or [] if events_known else []:
        attrs = e.get("attrs", {})
        if e["kind"] != "permission.decision" or str(attrs.get("decision") or "").lower() not in ("deny", "denied"):
            continue
        if {attrs.get("call_uid"), e.get("call_id")} & (covered - {None}):
            continue
        family = normalized_head({"command_head": attrs.get("command_head")}) or attrs.get("tool") or "unknown"
        groups[family].append(_event_occurrence(e))
    return [_signal(view, "permission_denied", f"permission_denied:{family}", occ)
            for family, occ in sorted(groups.items())]


def detect_risky_command(view: SessionView) -> list[Record] | None:
    """DT-13 destructive commands on the full command line (targets and clients checked)."""
    if view.calls is None:
        return None
    events = _call_events(view)
    groups = defaultdict(list)
    for c in sorted(view.calls, key=_order):
        if c.get("kind") != "shell":
            continue
        family = risky_family(command_line(c, events.get(c.get("call_event_uid"))))
        if family:
            groups[family].append(_call_occurrence(c))
    return [_signal(view, "risky_command", f"risky_command:{family}", occ)
            for family, occ in sorted(groups.items())]


def detect_interruption(view: SessionView) -> list[Record] | None:
    """``turn.status = interrupted`` or legacy ``turn.interrupted``; who interrupted is not inferred."""
    events_known = view.events is not None and (
        view.supported_kinds is None or "turn.interrupted" in view.supported_kinds)
    if view.turns is None and not events_known:
        return None
    hits, seen = [], set()
    for t in sorted(view.turns or [], key=lambda t: (t["session_uid"], t.get("idx", 0))):
        if t.get("status") == "interrupted":
            seen.add(t["turn_uid"])
            hits.append({"session_uid": t["session_uid"], "event_uid": t.get("last_event_uid"),
                         "call_uid": None, "seq": None, "ts": t.get("ended_at"),
                         "turn_uid": t["turn_uid"]})
    for e in view.events or [] if events_known else []:
        if e["kind"] == "turn.interrupted" and (not e.get("turn_uid") or e["turn_uid"] not in seen):
            seen.add(e.get("turn_uid"))
            hits.append(_event_occurrence(e, turn_uid=e.get("turn_uid")))
    return [_signal(view, "interruption", "interruption:turn", hits)] if hits else []


DETECTORS = {
    "correction": detect_correction,
    "frustration": detect_frustration,
    "retry_loop": detect_retry_loop,
    "missing_verification": detect_missing_verification,
    "would_prompt": detect_would_prompt,
    "permission_denied": detect_permission_denied,
    "risky_command": detect_risky_command,
    "interruption": detect_interruption,
}


def detect_all(view: SessionView) -> dict[str, list[Record] | None]:
    return {kind: detector(view) for kind, detector in DETECTORS.items()}


def opportunities(view: SessionView) -> dict[str, bool | None]:
    """Which AN-06 denominators this session belongs to; ``None`` when unknown."""
    calls = view.calls
    return {
        "human": None if view.events is None else bool(_human_messages(view)),
        "tools": None if calls is None else bool(calls),
        "shell": None if calls is None else any(c.get("kind") == "shell" for c in calls),
        "edits": None if calls is None else any(c.get("kind") in EDIT_KINDS for c in calls),
    }

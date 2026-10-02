"""AN-05 detector adapters: family facts of one root session tree → ``signal`` rows.

Each detector is a pure function ``detect_<kind>(view) -> list[signal] | None``:
``None`` means the evidence is unavailable (legacy or missing dataset) and must not be
counted as zero; ``[]`` means the evidence was observed and nothing fired. One signal is
emitted per ``(session, kind, key)``; ``value`` keeps the number of occurrences.
"""

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from ...models import stable_id
from ...privacy import direct_user_text
from ...profiling.bottlenecks import _expected_failure
from ..common import human
from ..context import AnalysisContext
from ..interaction.rules import correction_terms
from .dictionary import (
    CORRECTION_CHARS,
    EDIT_KINDS,
    FRUSTRATION,
    READONLY_COMMANDS,
    RISKY_COMMANDS,
    RULES_VERSION,
    SIGNAL_KINDS,
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


def permission_mode(session: Record) -> str | None:
    meta = session.get("meta") or {}
    return (session.get("permission_mode") or (session.get("attrs") or {}).get("permission_mode")
            or (meta.get("attrs") or {}).get("permission_mode"))


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
    """Lexical correction proxy between assistant replies (5–200 direct characters)."""
    if view.events is None:
        return None
    responded, groups = set(), defaultdict(list)
    for e in view.events:
        if e["kind"] in ("message.assistant", "tool.call"):
            responded.add(e["session_uid"])
            continue
        if not human(e, view.main_ids) or e.get("attrs", {}).get("replayed_from") \
                or e.get("attrs", {}).get("duplicate_of") or e["session_uid"] not in responded:
            continue
        text = direct_user_text(e.get("text") or "")
        if not CORRECTION_CHARS[0] <= len(text) <= CORRECTION_CHARS[1]:
            continue
        terms = correction_terms(text)
        if terms:
            dimension = (e.get("attrs", {}).get("interaction") or {}).get("dimension")
            groups[dimension].append(_event_occurrence(e, terms=terms, chars=len(text)))
    return [_signal(view, "correction", f"correction:{dim or 'none'}", occ,
                    problem_type="repeated_instruction" if dim else "misunderstood_request",
                    evidence={"dimension": dim})
            for dim, occ in sorted(groups.items(), key=lambda kv: kv[0] or "")]


def detect_frustration(view: SessionView) -> list[Record] | None:
    """v1 lexical proxy: frustration vocabulary or two short corrections in a row."""
    if view.events is None:
        return None
    hits, streak = [], []
    for e in _human_messages(view):
        text = direct_user_text(e.get("text") or "")
        if FRUSTRATION.search(text):
            hits.append(_event_occurrence(e, reason="vocabulary"))
            streak = []
            continue
        if len(text) <= 40 and correction_terms(text):
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
    """Adapter over ``respond.retry_links``: ≥2 same-argument links in one turn, ≥3 failures."""
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
        if len(chain) < 3 or failures < 3:
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


def detect_would_prompt(view: SessionView) -> list[Record] | None:
    """Read-only shell commands that still need approval under ``default`` mode."""
    if view.calls is None:
        return None
    readonly = [c for c in view.calls if c.get("kind") == "shell" and not c.get("is_wrapper")
                and normalized_head(c) in READONLY_COMMANDS]
    if not readonly:
        return []
    mode = permission_mode(view.session)
    if mode is None:
        return None
    if mode != "default":
        return []
    allowed = allowed_heads(view.inventory)
    hits = [c for c in sorted(readonly, key=_order) if allowed is None or normalized_head(c) not in allowed]
    if not hits:
        return []
    return [_signal(view, "would_prompt", "would_prompt:readonly_shell",
                    [_call_occurrence(c, head=normalized_head(c)) for c in hits],
                    basis="proxy" if allowed is None else "measured",
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
    """DT-13 destructive command vocabulary (MVP); path and mode checks are v1."""
    if view.calls is None:
        return None
    groups = defaultdict(list)
    for c in sorted(view.calls, key=_order):
        if c.get("kind") != "shell":
            continue
        text = call_text(c)
        for family, pattern in RISKY_COMMANDS:
            if pattern.search(text):
                groups[family].append(_call_occurrence(c))
                break
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

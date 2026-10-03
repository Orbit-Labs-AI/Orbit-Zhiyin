"""Data carried from the orbit.db tail into the classifier (AN-13)."""

from __future__ import annotations

from dataclasses import dataclass, field

STATES = ("awaiting_approval", "failing", "running", "just_finished", "idle")
FLAGS = ("awaiting_approval", "failing", "context_pressure")


@dataclass(frozen=True)
class TailEvent:
    ts: int | None
    kind: str
    actor: str
    call_id: str | None = None


@dataclass(frozen=True)
class TailCall:
    call_uid: str
    name: str
    command_head: str | None = None
    argument_digest: str | None = None
    status: str = "unknown"
    error_class: str | None = None
    exit_code: int | None = None
    started_at: int | None = None
    ended_at: int | None = None


@dataclass
class SessionTail:
    session_uid: str
    agent: str | None = None
    native_id: str | None = None  # the agent's own session id (hook events key)
    project_id: str | None = None
    project: str | None = None
    title: str | None = None
    status: str = "unknown"
    started_at: int | None = None
    ended_at: int | None = None
    last_event_ts: int | None = None
    last_actor: str | None = None
    events: list[TailEvent] = field(default_factory=list)  # oldest first
    calls: list[TailCall] = field(default_factory=list)  # oldest first
    pending_permission: dict | None = None  # {ts, command}
    usage: dict | None = None  # {used_tokens, model}


@dataclass
class SessionState:
    session_uid: str
    state: str
    since: int
    flags: set[str] = field(default_factory=set)
    finished_at: int | None = None
    current_tool: dict | None = None
    context: dict | None = None
    failure: dict | None = None
    approval: dict | None = None

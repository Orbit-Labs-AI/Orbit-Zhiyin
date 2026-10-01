"""Small shared data contracts. Unknown values stay None, never become zero."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256


def stable_id(*parts: object) -> str:
    return sha256("\0".join(str(x) for x in parts).encode()).hexdigest()[:24]


def utc_time(value: object) -> str | None:
    """Accept native seconds/ms or ISO timestamps; reject invalid clocks."""
    try:
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            seconds = value / 1000 if value > 100_000_000_000 else value
            dt = datetime.fromtimestamp(seconds, timezone.utc)
        elif isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return None  # The local timezone is not evidence of the source clock.
        else:
            return None
        return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    except (ValueError, OverflowError, OSError):
        return None


@dataclass
class Session:
    id: str
    project_id: str
    project: str
    cwd: str
    source_file: str
    model: str = "unknown"
    title: str = "未命名会话"
    started_at: str | None = None
    parent_id: str | None = None
    source_kind: str = "user"
    cli_version: str = "unknown"


@dataclass
class Event:
    id: str
    session_id: str
    ordinal: int
    kind: str
    timestamp: str | None
    model: str = "unknown"
    turn_id: str | None = None
    text: str = ""
    call_id: str | None = None
    tool: str | None = None
    status: str | None = None
    duration_ms: float | None = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParsedSession:
    session: Session | None
    events: list[Event] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    skipped_reason: str | None = None


@dataclass
class ImportSummary:
    files_seen: int = 0
    imported: int = 0
    unchanged: int = 0
    skipped: int = 0
    events: int = 0
    warning_count: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    sample_policy: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

"""Scope normalization and the ``t.session`` filter shared by profile / linked / search."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass

KEYS = ("project_ids", "agent_ids", "source_ids", "from_ts", "until_ts", "root_session_uids",
        "excluded_session_uids", "include_children")


def normalize(scope=None) -> dict:
    if scope is None:
        raw: dict = {}
    elif is_dataclass(scope):
        raw = asdict(scope)
    else:
        raw = dict(scope)
    # AI/UI use singular project and millisecond-window names; normalize once.
    for alias, canonical in (("start_ms", "from_ts"), ("end_ms", "until_ts"),
                             ("session_uids", "root_session_uids")):
        if canonical not in raw and alias in raw:
            raw[canonical] = raw[alias]
    if "project_ids" not in raw and raw.get("project_id") is not None:
        raw["project_ids"] = [raw["project_id"]]
    out: dict = {}
    for key in KEYS:
        value = raw.get(key)
        if isinstance(value, (list, tuple, set)):
            value = sorted(str(v) for v in value)
        if key == "excluded_session_uids" and not value:
            value = None
        if key == "include_children":
            value = True if value is None else bool(value)
        if value is not None:
            out[key] = value
    return out


def session_where(scope=None) -> tuple[str, list]:
    """SQL condition over alias ``s`` (``t.session``) plus its parameters."""
    s = normalize(scope)
    clauses: list[str] = []
    params: list = []

    def within(column: str, values: list, negate: bool = False) -> None:
        if not values:
            clauses.append("1" if negate else "0")
            return
        marks = ",".join("?" * len(values))
        clauses.append(f"{column} {'NOT IN' if negate else 'IN'} ({marks})")
        params.extend(values)

    if not s.get("include_children", True):
        clauses.append("s.kind = 'main'")
    if s.get("project_ids") is not None:
        within("s.project_id", s["project_ids"])
    if s.get("source_ids") is not None:
        within("s.source_id", s["source_ids"])
    if s.get("agent_ids") == []:
        clauses.append("0")
    elif s.get("agent_ids") is not None:
        marks = ",".join("?" * len(s["agent_ids"]))
        clauses.append(f"s.source_id IN (SELECT source_id FROM t.source WHERE agent IN ({marks}))")
        params.extend(s["agent_ids"])
    if s.get("root_session_uids") is not None:
        within("s.root_uid", s["root_session_uids"])
    if s.get("excluded_session_uids"):
        within("s.session_uid", s["excluded_session_uids"], negate=True)
    if s.get("from_ts") is not None:
        clauses.append("s.started_at >= ?")
        params.append(s["from_ts"])
    if s.get("until_ts") is not None:
        clauses.append("s.started_at < ?")
        params.append(s["until_ts"])
    return (" AND ".join(clauses) or "1"), params


def scope_hash(scope=None) -> str:
    from ..services.snapshots import scope_hash as digest

    return digest(normalize(scope))

"""Bounded event payloads for ``/v1/sessions/{id}/events`` and ``/v1/evidence/{id}``.

A single tool.result can hold megabytes of output (16 MB seen on real logs), so list pages
and evidence lookups cap ``text`` and long ``details`` strings. A capped event says so
explicitly: ``truncated`` + ``truncated_fields`` and ``text_range {offset, length, total}``;
the rest of the text is fetched by range (``/v1/evidence/{id}?text_offset=&max_chars=``).
This is response shaping only; ``details.text_truncated`` still means the source itself
was cut at import time.
"""

from __future__ import annotations

from typing import Any

LIST_MAX_CHARS = 8_000
EVIDENCE_MAX_CHARS = 64_000
RANGE_MAX_CHARS = 4_000_000


def _cap(value: Any, limit: int, path: str, fields: list[str]) -> Any:
    if isinstance(value, str):
        if len(value) > limit:
            fields.append(path)
            return value[:limit]
        return value
    if isinstance(value, dict):
        return {k: _cap(v, limit, f"{path}.{k}", fields) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap(v, limit, f"{path}[{i}]", fields) for i, v in enumerate(value)]
    return value


def cap_event(event: dict, max_chars: int, text_offset: int = 0) -> dict:
    """Return ``event`` with ``text[text_offset:text_offset + max_chars]`` and capped details."""
    text = event.get("text") or ""
    total = len(text)
    start = min(text_offset, total)
    piece = text[start:start + max_chars]
    fields: list[str] = []
    if start > 0 or start + len(piece) < total:
        fields.append("text")
    details = _cap(event.get("details") or {}, max_chars, "details", fields)
    return {**event, "text": piece, "details": details, "truncated": bool(fields),
            "truncated_fields": fields,
            "text_range": {"offset": start, "length": len(piece), "total": total}}

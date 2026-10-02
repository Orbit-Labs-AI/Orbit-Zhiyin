"""Content-addressed storage for large strings inside ``event.ext``.

The logical event contract is unchanged: writers pass ordinary ``ext`` JSON and readers
receive it back byte-for-byte. Physically, every string of at least ``THRESHOLD`` UTF-8
bytes is stored once in ``content_blob`` (zstd, keyed by the sha256 of its UTF-8) and its
position in ``ext`` holds ``{"$blob": <sha256>, "len": <chars>}``.

Since v9 the same store also holds large ``event.text`` of non-message kinds (tool output and
the like): the column then holds ``TEXT_MARK + sha256`` (65 characters). Message and title
text stays inline because full-text search and analysis read it directly. A non-message text
that natively starts with ``TEXT_MARK`` is stored with one extra leading mark. Readers call
:func:`restore_text` (or :func:`restore_row`) to get the logical text back.

A reference is recognised only by that exact two-key shape with a 64-hex digest. Native
dicts that happen to have that shape, or are exactly ``{"$lit": ...}``, are stored wrapped as
``{"$lit": {...}}`` so every logical value round-trips. Writers always pass logical ``ext``
(callers copying stored rows restore them first). ``content_blob.refs`` is maintained by
triggers on ``event``; unreferenced blobs are removed by :func:`collect_garbage`.
"""

from __future__ import annotations

import hashlib
import json
import re

import zstandard as zstd

from tandem_data.contract import canonical

THRESHOLD = 4096
# Kinds whose text stays inline (full-text search, titles, writing measurements).
INLINE_TEXT_KINDS = frozenset({"message.user", "message.assistant", "session.title"})
TEXT_THRESHOLD = 1024
# U+FDD0 is a Unicode noncharacter; it does not occur in ordinary text.
TEXT_MARK = "\ufdd0"
# Same predicate as the event_text_blob_* triggers in migration 009.
TEXT_REFERENCE_SQL = (
    "kind NOT IN ('message.user','message.assistant','session.title') AND length(text)=65 "
    "AND substr(text,1,1)=char(64976) AND substr(text,2,1)<>char(64976)"
)
MARKER = "$blob"
LITERAL = "$lit"
_HEX = re.compile(r"[0-9a-f]{64}")
_LEVEL = 3


def is_reference(value) -> bool:
    return (
        isinstance(value, dict)
        and len(value) == 2
        and isinstance(value.get(MARKER), str)
        and isinstance(value.get("len"), int)
        and _HEX.fullmatch(value[MARKER]) is not None
    )


def _has_table(connection) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='content_blob'"
        ).fetchone()
    )


def pack_json(connection, ext: str) -> str:
    """Return stored ``ext`` JSON for logical ``ext`` JSON, writing any new blobs."""
    if not isinstance(ext, str):
        return ext
    # A string of THRESHOLD UTF-8 bytes has at least THRESHOLD/4 characters.
    if len(ext) < THRESHOLD // 4 and f'"{MARKER}"' not in ext and f'"{LITERAL}"' not in ext:
        return ext
    if not _has_table(connection):
        return ext  # Pre-v8 stores keep inline payloads and are never restored.
    pending: dict[str, bytes] = {}
    changed = [False]
    packed = _pack(json.loads(ext), pending, changed)
    if not changed[0]:
        return ext
    compressor = None
    for digest, raw in pending.items():
        compressor = _store_blob(connection, raw, digest, compressor)
    return canonical(packed)


def _store_blob(connection, raw: bytes, digest: str, compressor=None):
    if connection.execute("SELECT 1 FROM content_blob WHERE sha256=?", (digest,)).fetchone():
        return compressor
    compressor = compressor or zstd.ZstdCompressor(level=_LEVEL)
    connection.execute(
        "INSERT INTO content_blob(sha256,codec,raw_len,data) VALUES(?,?,?,?)",
        (digest, "zstd", len(raw), compressor.compress(raw)),
    )
    return compressor


def pack_text(connection, kind, text):
    """Return stored ``event.text`` for logical text, writing a blob when it is large."""
    if text is None or kind in INLINE_TEXT_KINDS:
        return text
    if text.startswith(TEXT_MARK):
        return TEXT_MARK + text
    if len(text) * 4 < TEXT_THRESHOLD:
        return text
    raw = text.encode()
    if len(raw) < TEXT_THRESHOLD or not _has_table(connection):
        return text
    digest = hashlib.sha256(raw).hexdigest()
    _store_blob(connection, raw, digest)
    return TEXT_MARK + digest


def restore_text(connection, kind, text, cache: dict | None = None):
    """Inverse of :func:`pack_text`."""
    if not text or text[0] != TEXT_MARK or kind in INLINE_TEXT_KINDS:
        return text
    if text[1:2] == TEXT_MARK:
        return text[1:]
    return _fetch(connection, text[1:], {} if cache is None else cache)


def restore_row(connection, row, cache: dict | None = None) -> dict:
    """``dict(row)`` of an ``event`` row with its logical text."""
    event = dict(row)
    text = event.get("text")
    if text and text[0] == TEXT_MARK:
        event["text"] = restore_text(connection, event["kind"], text, cache)
    return event


def _fetch(connection, digest: str, cache: dict) -> str:
    if digest not in cache:
        row = connection.execute(
            "SELECT codec,raw_len,data FROM content_blob WHERE sha256=?", (digest,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Dangling content_blob reference {digest}")
        cache[digest] = _decode(row[0], row[1], row[2], digest)
    return cache[digest]


def _pack(value, pending, changed):
    if isinstance(value, str):
        if len(value) * 4 < THRESHOLD:
            return value
        raw = value.encode()
        if len(raw) < THRESHOLD:
            return value
        digest = hashlib.sha256(raw).hexdigest()
        pending.setdefault(digest, raw)
        changed[0] = True
        return {MARKER: digest, "len": len(value)}
    if isinstance(value, dict):
        packed = {key: _pack(item, pending, changed) for key, item in value.items()}
        if is_reference(value) or list(value) == [LITERAL]:
            changed[0] = True
            return {LITERAL: packed}
        return packed
    if isinstance(value, list):
        return [_pack(item, pending, changed) for item in value]
    return value


def pack_row(connection, table: str, values: dict) -> dict:
    """Storage hook for ``store.insert``/``insert_rows``: only ``event.ext``/``text`` change."""
    if table != "event":
        return values
    if isinstance(values.get("ext"), str):
        stored = pack_json(connection, values["ext"])
        if stored is not values["ext"]:
            values = {**values, "ext": stored}
    text = values.get("text")
    if text is not None:
        stored = pack_text(connection, values.get("kind"), text)
        if stored is not text:
            values = {**values, "text": stored}
    return values


def restore(connection, value, cache: dict | None = None):
    """Inverse of packing for a decoded ``ext`` value."""
    if isinstance(value, dict):
        if is_reference(value):
            return _fetch(connection, value[MARKER], {} if cache is None else cache)
        if list(value) == [LITERAL] and isinstance(value[LITERAL], dict):
            value = value[LITERAL]  # Escaped native dict: restore its members only.
        return {key: restore(connection, item, cache) for key, item in value.items()}
    if isinstance(value, list):
        return [restore(connection, item, cache) for item in value]
    return value


def restore_json(connection, ext: str):
    value = json.loads(ext)
    return restore(connection, value) if f'"{MARKER}"' in ext or f'"{LITERAL}"' in ext else value


def _decode(codec, raw_len, data, digest=None) -> str:
    if codec != "zstd":
        raise ValueError(f"Unsupported content_blob codec {codec}")
    raw = zstd.ZstdDecompressor().decompress(data, max_output_size=raw_len)
    if len(raw) != raw_len or (digest and hashlib.sha256(raw).hexdigest() != digest):
        raise ValueError("content_blob digest mismatch")
    return raw.decode()


def collect_garbage(connection) -> int:
    """Delete blobs no event references. Safe to call outside an import transaction."""
    if not _has_table(connection):
        return 0
    return connection.execute("DELETE FROM content_blob WHERE refs=0").rowcount


def verify(connection) -> dict:
    """Recount every reference and check every blob's digest and length."""
    if not _has_table(connection):
        return {"blobs": 0, "references": 0}
    counted = dict(
        connection.execute(
            "SELECT t.value, COUNT(*) FROM event e, json_tree(e.ext) t "
            "WHERE instr(e.ext, '\"$blob\"') AND t.key='$blob' AND t.type='text' "
            "AND length(t.value)=64 AND t.path NOT LIKE '%.\"$lit\"' GROUP BY t.value"
        )
    )
    for digest, count in connection.execute(
        f"SELECT substr(text,2), COUNT(*) FROM event WHERE {TEXT_REFERENCE_SQL} GROUP BY 1"
    ):
        counted[digest] = counted.get(digest, 0) + count
    blobs = 0
    for digest, codec, raw_len, data, refs in connection.execute(
        "SELECT sha256,codec,raw_len,data,refs FROM content_blob"
    ):
        blobs += 1
        if refs != counted.pop(digest, 0):
            raise ValueError("content_blob reference count disagrees with event.ext")
        _decode(codec, raw_len, data, digest)
    if counted:
        raise ValueError("event.ext references missing content_blob rows")
    references = connection.execute("SELECT COALESCE(SUM(refs),0) FROM content_blob").fetchone()[0]
    return {"blobs": blobs, "references": references}

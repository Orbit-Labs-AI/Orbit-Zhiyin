"""Content-addressed storage for large strings inside ``event.ext``.

The logical event contract is unchanged: writers pass ordinary ``ext`` JSON and readers
receive it back byte-for-byte. Physically, every string of at least ``THRESHOLD`` UTF-8
bytes is stored once in ``content_blob`` (zstd, keyed by the sha256 of its UTF-8) and its
position in ``ext`` holds ``{"$blob": <sha256>, "len": <chars>}``. ``event.text`` stays
inline because full-text search and analysis read it directly.

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
        if connection.execute("SELECT 1 FROM content_blob WHERE sha256=?", (digest,)).fetchone():
            continue
        compressor = compressor or zstd.ZstdCompressor(level=_LEVEL)
        connection.execute(
            "INSERT INTO content_blob(sha256,codec,raw_len,data) VALUES(?,?,?,?)",
            (digest, "zstd", len(raw), compressor.compress(raw)),
        )
    return canonical(packed)


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
    """Storage hook for ``store.insert``/``insert_rows``: only ``event.ext`` is affected."""
    if table != "event" or not isinstance(values.get("ext"), str):
        return values
    stored = pack_json(connection, values["ext"])
    return values if stored is values["ext"] else {**values, "ext": stored}


def restore(connection, value, cache: dict | None = None):
    """Inverse of packing for a decoded ``ext`` value."""
    if isinstance(value, dict):
        if is_reference(value):
            digest = value[MARKER]
            cache = {} if cache is None else cache
            if digest not in cache:
                row = connection.execute(
                    "SELECT codec,raw_len,data FROM content_blob WHERE sha256=?", (digest,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"Dangling content_blob reference {digest}")
                cache[digest] = _decode(row[0], row[1], row[2], digest)
            return cache[digest]
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

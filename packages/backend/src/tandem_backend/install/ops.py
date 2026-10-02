"""Pure format operations on one install Target: units, select, render, unrender.

Nothing here touches the filesystem. ``render`` turns the current file bytes into the
bytes we would write (so the preview diff *is* the write diff); ``unrender`` reverses a
previous render at unit level using the ``applied`` record, so an undo still works after
the agent rewrote unrelated keys or the user edited outside our block.

Actions: ``merge_json`` (pointer-addressed JSON merge), ``md_block`` / ``toml_block``
(marker-delimited blocks), ``create_file``; ``run_command`` / ``clipboard`` / ``tutorial``
never write and always render ``noop``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import tomllib
from typing import Any

from .errors import OpConflict

MAX_FILE_BYTES = 32 * 1024 * 1024
WRITE_ACTIONS = ("merge_json", "md_block", "toml_block", "create_file")
_ABSENT = {"__absent__": True}


def sha256(data: bytes | None) -> str:
    return "absent" if data is None else "sha256:" + hashlib.sha256(data).hexdigest()


def _canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _text(data: bytes | None) -> str:
    return "" if data is None else data.decode("utf-8")


def _check_size(data: bytes | None) -> None:
    if data is not None and len(data) > MAX_FILE_BYTES:
        raise OpConflict("file_too_large", detail={"bytes": len(data)})


# ---------------------------------------------------------------------------- JSON


def parse_pointer(pointer: str | None) -> list[str]:
    if not pointer:
        return []
    if not pointer.startswith("/"):
        raise OpConflict("bad_pointer", detail={"pointer": pointer})
    return [p.replace("~1", "/").replace("~0", "~") for p in pointer[1:].split("/")]


def _join_pointer(parts: list[str]) -> str:
    return "".join("/" + p.replace("~", "~0").replace("/", "~1") for p in parts)


def _load_json(current: bytes | None) -> Any:
    if current is None or not current.strip():
        return {}
    try:
        return json.loads(current)
    except (ValueError, UnicodeDecodeError) as exc:
        raise OpConflict("parse_error", str(exc)) from None


def _get(data: Any, parts: list[str]) -> Any:
    node = data
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return _ABSENT
    return node


def _json_style(current: bytes | None) -> tuple[str | int, bool]:
    """Indent (2/4/tab, default 2) and whether the file ends with a newline."""
    text = _text(current)
    indent: str | int = 2
    for line in text.splitlines()[1:]:
        if line.strip():
            lead = line[: len(line) - len(line.lstrip())]
            if lead.startswith("\t"):
                indent = "\t"
            elif lead:
                indent = len(lead)
            break
    return indent, (text.endswith("\n") if text else True)


def _dump_json(data: Any, current: bytes | None) -> bytes:
    indent, newline = _json_style(current)
    out = json.dumps(data, indent=indent, ensure_ascii=False)
    return (out + ("\n" if newline else "")).encode()


def _ensure_container(data: dict, parts: list[str], leaf: type) -> tuple[Any, list[str]]:
    """Walk to ``parts`` creating missing dicts (and the leaf as ``leaf``)."""
    created: list[str] = []
    node: Any = data
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if isinstance(node, list):
            if not part.isdigit() or int(part) >= len(node):
                raise OpConflict("container_type", detail={"pointer": _join_pointer(parts[: i + 1])})
            node = node[int(part)]
            continue
        if not isinstance(node, dict):
            raise OpConflict("container_type", detail={"pointer": _join_pointer(parts[:i])})
        if part not in node:
            node[part] = leaf() if last else {}
            created.append(_join_pointer(parts[: i + 1]))
        node = node[part]
    return node, created


def _deny_conflict(data: Any, pointer: str, values: list) -> None:
    if pointer != "/permissions/allow":
        return
    perms = data.get("permissions") if isinstance(data, dict) else None
    if not isinstance(perms, dict):
        return
    for other in ("deny", "ask"):
        clash = [v for v in values if v in (perms.get(other) or [])]
        if clash:
            raise OpConflict("deny_conflict", detail={"list": other, "values": clash})


def _render_json(target: dict, current: bytes | None) -> dict:
    data = _load_json(current)
    if not isinstance(data, dict):
        raise OpConflict("container_type", detail={"pointer": ""})
    pointer = target.get("pointer") or ""
    parts = parse_pointer(pointer)
    content = target.get("content")
    applied: dict[str, Any] = {"kind": "merge_json", "pointer": pointer, "previous": {},
                               "created_paths": [], "created_file": current is None}
    if isinstance(content, list):
        existing = _get(data, parts)
        if existing is not _ABSENT and not isinstance(existing, list):
            raise OpConflict("container_type", detail={"pointer": pointer})
        _deny_conflict(data, pointer, content)
        have = {_canon(v) for v in (existing if isinstance(existing, list) else [])}
        added = []
        for value in content:
            key = _canon(value)
            if key not in have:
                have.add(key)
                added.append(value)
        applied["added"] = added
        if added:
            node, created = _ensure_container(data, parts, list)
            node.extend(copy.deepcopy(added))
            applied["created_paths"] = created
    elif isinstance(content, dict):
        existing = _get(data, parts)
        if existing is not _ABSENT and not isinstance(existing, dict):
            raise OpConflict("container_type", detail={"pointer": pointer})
        base = existing if isinstance(existing, dict) else {}
        if (len(parts) >= 2 and parts[-2] == "mcpServers" and existing is not _ABSENT
                and any(_canon(base.get(k, _ABSENT)) != _canon(v) for k, v in content.items())):
            # A same-name server we would partially overwrite is someone else's: refuse,
            # like Codex's ``toml_table_exists``, instead of merging args/env together.
            raise OpConflict("mcp_exists", detail={"pointer": pointer})
        added_map: dict[str, Any] = {}
        for key, value in content.items():
            if key not in base:
                added_map[key] = value
            elif _canon(base[key]) == _canon(value):
                continue
            elif target.get("write_mode") == "set":
                added_map[key] = value
                applied["previous"][key] = copy.deepcopy(base[key])
            else:
                raise OpConflict("key_exists_different",
                                 detail={"pointer": _join_pointer([*parts, key])})
        for key in added_map:
            applied["previous"].setdefault(key, dict(_ABSENT))
        applied["added"] = added_map
        if added_map:
            node, created = _ensure_container(data, parts, dict)
            node.update(copy.deepcopy(added_map))
            applied["created_paths"] = created
    else:
        raise OpConflict("bad_content", detail={"action": "merge_json"})
    if not applied["added"]:
        return {"new": current if current is not None else b"", "status": "noop", "applied": applied}
    return {"new": _dump_json(data, current), "status": "create" if current is None else "modify",
            "applied": applied}


def _drop_empty_created(data: dict, created_paths: list[str]) -> None:
    for pointer in reversed(created_paths):
        parts = parse_pointer(pointer)
        parent = _get(data, parts[:-1])
        if isinstance(parent, dict) and parts[-1] in parent and parent[parts[-1]] in ({}, []):
            del parent[parts[-1]]


def _unrender_json(applied: dict, current: bytes, known: list | None = None,
                   inherit: dict | None = None) -> dict:
    """``known``: list items that are not the user's (pre-install baseline plus other active
    installs' items); with it, a missing item of ours next to an unknown item is a user edit."""
    data = _load_json(current)
    parts = parse_pointer(applied.get("pointer"))
    node = _get(data, parts)
    added = applied.get("added")
    changed = False
    if isinstance(added, list):
        if isinstance(node, list):
            missing = False
            for value in added:
                key = _canon(value)
                for i, item in enumerate(node):
                    if _canon(item) == key:
                        del node[i]
                        changed = True
                        break
                else:
                    missing = True
            if missing and known is not None:
                ours = {_canon(v) for v in added}
                other = {_canon(v) for v in known}
                if any(_canon(i) not in other and _canon(i) not in ours for i in node):
                    # our item is gone but an item nobody installed appeared: an edit
                    return {"status": "modified", "new": None, "delete": False}
    else:
        previous = applied.get("previous") or {}
        if isinstance(node, dict):
            for key, value in (added or {}).items():
                prev = previous.get(key, _ABSENT)
                if key not in node:
                    if prev != _ABSENT:  # our value was removed, but the old one too
                        return {"status": "modified", "new": None, "delete": False}
                    continue
                cur = _canon(node[key])
                if cur == _canon(value):
                    if prev == _ABSENT:
                        del node[key]
                    else:
                        node[key] = copy.deepcopy(prev)
                    changed = True
                elif prev == _ABSENT or cur != _canon(prev):
                    return {"status": "modified", "new": None, "delete": False}
    if not changed:
        return {"status": "already_reverted", "new": None, "delete": False}
    _drop_empty_created(data, applied.get("created_paths") or [])
    inherit = inherit or {}
    _drop_empty_created(data, inherit.get("created_paths") or [])
    if (applied.get("created_file") or inherit.get("created_file")) and data == {}:
        return {"status": "reverted", "new": None, "delete": True}
    return {"status": "reverted", "new": _dump_json(data, current), "delete": False}


def _json_guard(target: dict, data: bytes | None) -> str:
    if data is None:
        return "absent"
    try:
        node = _get(_load_json(data), parse_pointer(target.get("pointer")))
    except OpConflict:
        return sha256(data)  # unparsable: fall back to the whole file
    return "absent" if node is _ABSENT else "sha256:" + hashlib.sha256(_canon(node)).hexdigest()


# --------------------------------------------------------------------------- blocks


def _markers(action: str, block_id: str) -> tuple[str, str]:
    bid = block_id.removeprefix("tandem:")
    if action == "toml_block":
        return f"# >>> tandem:{bid} >>>", f"# <<< tandem:{bid} <<<"
    return f"<!-- tandem:{bid} begin -->", f"<!-- tandem:{bid} end -->"


def _block_text(action: str, block_id: str, body: str) -> str:
    begin, end = _markers(action, block_id)
    return f"{begin}\n{body.strip(chr(10))}\n{end}\n"


def _find_block(text: str, action: str, block_id: str) -> tuple[int, int] | None:
    begin, end = _markers(action, block_id)
    m = re.search(rf"^{re.escape(begin)}\n.*?^{re.escape(end)}[ \t]*(?:\n|\Z)", text,
                  re.MULTILINE | re.DOTALL)
    return (m.start(), m.end()) if m else None


def _toml_headers(body: str) -> list[list[str]]:
    out = []
    for m in re.finditer(r"^\s*\[(?!\[)([^\]]+)\]", body, re.MULTILINE):
        keys = re.findall(r'"([^"]*)"|\'([^\']*)\'|([A-Za-z0-9_-]+)', m.group(1))
        out.append([a or b or c for a, b, c in keys])
    return out


def _render_block(target: dict, current: bytes | None) -> dict:
    action, block_id = target["action"], target.get("block_id") or ""
    if not block_id:
        raise OpConflict("bad_content", detail={"reason": "block_id required"})
    body = target.get("content")
    if not isinstance(body, str):
        raise OpConflict("bad_content", detail={"action": action})
    block = _block_text(action, block_id, body)
    text = _text(current)
    applied = {"kind": action, "block_id": block_id, "created_file": current is None,
               "block_sha256": sha256(block.encode()), "sep": "", "block": block}
    found = _find_block(text, action, block_id)
    if found:
        existing = text[found[0]:found[1]]
        if existing.rstrip("\n") == block.rstrip("\n"):
            return {"new": current or b"", "status": "noop", "applied": applied}
        raise OpConflict("block_exists_different", detail={"block_id": block_id})
    top = action == "toml_block" and target.get("position") == "top"
    if top:  # root keys (Codex ``notify``) must precede every table
        sep = "\n" if text.strip() else ""
        applied.update(position="top", sep=sep)
        new = block + sep + text
        try:
            tomllib.loads(new)
        except tomllib.TOMLDecodeError as exc:
            raise OpConflict("toml_invalid", str(exc)) from None
        return {"new": new.encode(), "status": "create" if current is None else "modify", "applied": applied}
    if action == "toml_block":
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise OpConflict("parse_error", str(exc)) from None
        for path in _toml_headers(body):
            node: Any = parsed
            for key in path:
                node = node.get(key, _ABSENT) if isinstance(node, dict) else _ABSENT
            if node is not _ABSENT:
                raise OpConflict("toml_table_exists", detail={"table": ".".join(path)})
        first = next((ln.strip() for ln in body.splitlines()
                      if ln.strip() and not ln.strip().startswith("#")), "")
        if not first.startswith("[") and re.search(r"^\s*\[", text, re.MULTILINE):
            # bare keys appended after a table would silently join that table
            raise OpConflict("toml_invalid", detail={"reason": "bare keys after a table"})
    sep = ""
    if text:
        if not text.endswith("\n"):
            sep += "\n"
        if text.strip() and not (text + sep).endswith("\n\n"):
            sep += "\n"
    applied["sep"] = sep
    new = text + sep + block
    if action == "toml_block":
        try:
            tomllib.loads(new)
        except tomllib.TOMLDecodeError as exc:
            raise OpConflict("toml_invalid", str(exc)) from None
    return {"new": new.encode(), "status": "create" if current is None else "modify",
            "applied": applied}


def _unrender_block(applied: dict, current: bytes, inherit: dict | None = None) -> dict:
    action, block_id = applied["kind"], applied["block_id"]
    text = _text(current)
    found = _find_block(text, action, block_id)
    if not found:
        return {"status": "already_reverted", "new": None, "delete": False}
    start, end = found
    if sha256(text[start:end].encode()) != applied.get("block_sha256"):
        return {"status": "modified", "new": None, "delete": False}
    sep = applied.get("sep") or ""
    if applied.get("position") == "top":
        if sep and text[end:].startswith(sep):
            end += len(sep)
    elif sep and text[:start].endswith(sep):
        start -= len(sep)
    new = text[:start] + text[end:]
    if (applied.get("created_file") or (inherit or {}).get("created_file")) and not new.strip():
        return {"status": "reverted", "new": None, "delete": True}
    return {"status": "reverted", "new": new.encode(), "delete": False}


# ---------------------------------------------------------------------- dispatchers


def _content_bytes(target: dict) -> bytes:
    content = target.get("content")
    if isinstance(content, bytes):
        return content
    if not isinstance(content, str):
        raise OpConflict("bad_content", detail={"action": "create_file"})
    return content.encode()


def render(target: dict, current: bytes | None) -> dict:
    """Pure: bytes we would write. ``{'new','status','applied','ai_lines'}``."""
    _check_size(current)
    action = target.get("action")
    if action == "merge_json":
        out = _render_json(target, current)
    elif action in ("md_block", "toml_block"):
        out = _render_block(target, current)
    elif action == "create_file":
        body = _content_bytes(target)
        applied = {"kind": "create_file", "sha256": sha256(body), "created": True,
                   "mode": target.get("file_mode")}
        if current is None:
            out = {"new": body, "status": "create", "applied": applied}
        elif current == body:
            applied.update(created=False, preexisting_identical=True)
            out = {"new": current, "status": "noop", "applied": applied}
        else:
            raise OpConflict("file_exists_different", detail={"path": target.get("display")})
    else:  # run_command / clipboard / tutorial: shown, never written
        out = {"new": current, "status": "noop", "applied": {"kind": action}}
    out["ai_lines"] = _ai_lines(target, out["new"]) if out["status"] != "noop" else []
    return out


def _ai_lines(target: dict, new: bytes | None) -> list[int]:
    """1-based lines of ``new`` whose text came from AI slots (``target['ai_text']``)."""
    marks = {ln.strip() for t in target.get("ai_text") or [] for ln in str(t).splitlines()
             if ln.strip()}
    if not marks or new is None:
        return []
    return [i for i, ln in enumerate(_text(new).splitlines(), 1) if ln.strip() in marks]


def unrender(applied: dict, target: dict, current: bytes | None, *, known: list | None = None,
             inherit: dict | None = None) -> dict:
    """Reverse ``applied`` on ``current``: ``{'status','new','delete'}``.

    status: reverted | already_reverted | modified (our unit was edited; leave the file) |
    missing (file is gone). ``inherit`` carries ``created_file`` / ``created_paths`` of
    earlier, already-reverted installs that created this file, so whichever install is
    reverted last removes the file once nothing but empty tandem containers remain.
    """
    kind = applied.get("kind") or target.get("action")
    if current is None:
        created = applied.get("created_file") or applied.get("created")
        return {"status": "already_reverted" if created else "missing", "new": None,
                "delete": False}
    _check_size(current)
    if kind == "merge_json":
        return _unrender_json(applied, current, known, inherit)
    if kind in ("md_block", "toml_block"):
        return _unrender_block(applied, current, inherit)
    if kind == "create_file":
        if sha256(current) == applied.get("sha256"):
            return {"status": "reverted", "new": None, "delete": bool(applied.get("created"))}
        return {"status": "modified", "new": None, "delete": False}
    return {"status": "already_reverted", "new": None, "delete": False}


def reconstruct(applied: dict, base: bytes | None) -> bytes | None:
    """Best-effort re-creation of what we wrote on top of ``base`` (for 3-way diffs)."""
    kind = applied.get("kind")
    try:
        if kind == "merge_json":
            t = {"action": "merge_json", "pointer": applied.get("pointer"),
                 "content": applied.get("added"), "write_mode": "set"}
            return _render_json(t, base)["new"]
        if kind == "toml_block" and applied.get("position") == "top" and applied.get("block") is not None:
            return (applied["block"] + (applied.get("sep") or "") + _text(base)).encode()
        if kind in ("md_block", "toml_block") and applied.get("block") is not None:
            return (_text(base) + (applied.get("sep") or "") + applied["block"]).encode()
    except OpConflict:
        return None
    return None


def guard_hash(target: dict, data: bytes | None) -> str:
    """merge_json: canonical hash of the container at ``pointer``; else whole-file hash."""
    _check_size(data)
    if target.get("action") == "merge_json":
        return _json_guard(target, data)
    return sha256(data)


# ----------------------------------------------------------------- units / select


_LIST_ITEM = re.compile(r"^([-*+]|\d+[.)])\s")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _md_units(text: str) -> list[dict]:
    """Paragraphs, headings, top-level list items and whole fenced blocks as units.

    ``tight`` marks a unit that followed the previous one without a blank line, so two
    adjacent list items are re-joined with a single newline. Fences are never split.
    """
    units: list[dict] = []
    cur: list[str] = []
    tight = False
    saw_blank = True
    fence: str | None = None

    def flush() -> None:
        nonlocal cur
        if cur:
            units.append({"text": "\n".join(cur), "tight": tight and bool(units),
                          "item": bool(_LIST_ITEM.match(cur[0]))})
            cur = []

    def start(line: str) -> None:
        nonlocal tight, saw_blank
        flush()
        tight, saw_blank = not saw_blank, False
        cur.append(line)

    for line in text.split("\n"):
        if fence:
            cur.append(line)
            if line.strip().startswith(fence):
                fence = None
                if _FENCE.match(cur[0]):
                    flush()
            continue
        m = _FENCE.match(line)
        if m:
            fence = m.group(1)
            if cur and _LIST_ITEM.match(cur[0]) and line[:1] in (" ", "\t"):
                cur.append(line)
            else:
                start(line)
            continue
        if not line.strip():
            flush()
            saw_blank = True
            continue
        if not cur or _LIST_ITEM.match(line) or line.startswith("#"):
            start(line)
        else:
            cur.append(line)
        if line.startswith("#"):
            flush()
    flush()
    return units


def _md_join(units: list[dict]) -> str:
    out = ""
    for i, u in enumerate(units):
        if i:
            out += "\n" if (u["tight"] and u["item"] and units[i - 1]["item"]) else "\n\n"
        out += u["text"]
    return out


def _label(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False,
                                                           separators=(",", ":"))
    return text if len(text) <= 120 else text[:117] + "..."


def units(target: dict) -> list[dict]:
    action, content = target.get("action"), target.get("content")
    if action == "merge_json" and isinstance(content, list):
        return [{"id": f"u{i}", "label": _label(v), "kind": "array_item"}
                for i, v in enumerate(content)]
    if action == "merge_json" and isinstance(content, dict):
        return [{"id": f"u{i}", "label": _label({k: v}), "kind": "key"}
                for i, (k, v) in enumerate(content.items())]
    if action == "md_block" and isinstance(content, str):
        return [{"id": f"u{i}", "label": _label(u["text"].split("\n", 1)[0]), "kind": "paragraph"}
                for i, u in enumerate(_md_units(content))]
    if action == "create_file":
        return [{"id": "u0", "label": target.get("display") or "file", "kind": "file"}]
    if isinstance(content, dict) and "argv" in content:
        return [{"id": "u0", "label": " ".join(content["argv"]), "kind": "block"}]
    return [{"id": "u0", "label": target.get("display") or str(action), "kind": "block"}]


def select(target: dict, unit_ids: list[str] | None) -> dict:
    """Copy of ``target`` keeping only the chosen units (``None`` = all)."""
    out = copy.deepcopy(target)
    if unit_ids is None:
        return out
    chosen = set(unit_ids)
    if not chosen:
        raise OpConflict("empty_selection", detail={"idx": target.get("idx")})
    action, content = target.get("action"), target.get("content")
    if action == "merge_json" and isinstance(content, list):
        out["content"] = [v for i, v in enumerate(content) if f"u{i}" in chosen]
        keep = len(out["content"])
    elif action == "merge_json" and isinstance(content, dict):
        out["content"] = {k: v for i, (k, v) in enumerate(content.items()) if f"u{i}" in chosen}
        keep = len(out["content"])
    elif action == "md_block" and isinstance(content, str):
        picked = [u for i, u in enumerate(_md_units(content)) if f"u{i}" in chosen]
        out["content"] = _md_join(picked)
        keep = len(picked)
    else:
        keep = 1 if "u0" in chosen else 0
    if not keep:
        raise OpConflict("empty_selection", detail={"idx": target.get("idx")})
    return out

"""Pairwise relations between candidates (RC-03.1): duplicates, conflicts, complements.

Pure rules over Cand dicts (as stored in rec_candidate.card); no model calls.
`links` = {kb_id, pairs_with, conflicts_with, content_hash} is written by the engine.
"""

import re
from itertools import combinations

_ALLOW = re.compile(r'"((?:Bash|Read|Edit|Write|WebFetch)\([^"]*\))"')
LADDER_TYPES = {"missing_verification"}


def _id(c: dict) -> str:
    return c.get("candidate_id") or c["rec_key"]


def _links(c: dict) -> dict:
    if c.get("links"):
        return c["links"]
    kb = c.get("kb") or {}
    remedy = kb.get("remedy") or kb
    return {"kb_id": kb.get("id"), "pairs_with": remedy.get("pairs_with") or [],
            "conflicts_with": remedy.get("conflicts_with") or [], "content_hash": None}


def _problem(c: dict) -> tuple[str | None, str | None, str | None]:
    p = c.get("problem") or {}
    return p.get("problem_id") or c.get("problem_id"), p.get("type") or c.get("problem_type"), p.get("key")


def _names(c: dict) -> set[str]:
    links = _links(c)
    return {c["rec_key"], *([links["kb_id"]] if links.get("kb_id") else [])}


def _allows(c: dict) -> list[str]:
    lines = (c.get("ui") or {}).get("file") or c.get("file") or []
    return [m.group(1) for line, mark in lines if mark != " " for m in _ALLOW.finditer(line)]


RULE_KINDS, ENFORCE_KINDS = {"rule", "prompt"}, {"hook", "permission_rule"}
PRIORITY = ("conflicts", "duplicates", "complements")


def _resource(c: dict) -> set[str]:
    """Resource ids a card installs: its source item and, for KB cards, the catalog item it wraps."""
    source = c.get("source") or {}
    item, origin = source.get("item_id"), source.get("origin")
    ref = source.get("catalog_ref") or (c.get("kb") or {}).get("catalog_ref")
    ids = {f"{origin}:{item}"} if item else set()
    if ref:
        ids.add(f"catalog:{ref}")
    if origin == "catalog" and item:
        ids.add(f"catalog:{item}")
    return ids


def _pair(a: dict, b: dict) -> tuple[str, str] | None:
    """At most one relation per pair: conflicts > duplicates > complements."""
    _, ta, ka = _problem(a)
    _, _, kb_ = _problem(b)
    la, lb = _links(a), _links(b)
    same_key = bool(ka) and ka == kb_
    kinds = {a.get("kind"), b.get("kind")}
    enforce_pair = bool(kinds & RULE_KINDS) and bool(kinds & ENFORCE_KINDS) and len(kinds) == 2
    paired = bool(set(la.get("pairs_with") or []) & _names(b) or set(lb.get("pairs_with") or []) & _names(a))
    found: dict[str, str] = {}
    if set(la.get("conflicts_with") or []) & _names(b) or set(lb.get("conflicts_with") or []) & _names(a):
        found["conflicts"] = "知识库标注两者冲突"
    elif same_key and enforce_pair and not paired:  # a curated pairing outranks the heuristic
        if ta in LADDER_TYPES:
            found["complements"] = "验证阶梯：规则写清单，hook 兜底"
        else:
            found["conflicts"] = "同一约束不要同时写进规则与 hook，保留 hook"
    if same_key and a.get("kind") == b.get("kind"):
        found["duplicates"] = "同一问题的同类方案，保留一张"
    elif _resource(a) & _resource(b):
        found["duplicates"] = "指向同一资源"
    elif la.get("content_hash") and la.get("content_hash") == lb.get("content_hash"):
        found["duplicates"] = "内容相同"
    if paired:
        found.setdefault("complements", "知识库建议搭配使用")
    elif same_key and kinds == {"rule", "workflow"}:
        found.setdefault("complements", "验证阶梯：规则 + 工作流")
    return next(((rel, found[rel]) for rel in PRIORITY if rel in found), None)


def relations(cands: list[dict], deny: list[str] | None = None) -> list[dict]:
    """[{a, b, relation, reason}]; `deny` = installed permissions.deny entries (b = 'inventory')."""
    seen, out = set(), []
    for a, b in combinations(cands, 2):
        if _id(a) == _id(b):
            continue
        found = _pair(a, b)
        key = frozenset((_id(a), _id(b)))
        if found and key not in seen:
            seen.add(key)
            out.append({"a": _id(a), "b": _id(b), "relation": found[0], "reason": found[1]})
    for c in cands:
        if c.get("kind") != "permission_rule" or not deny:
            continue
        hit = [p for p in _allows(c) if any(p.startswith(d.rstrip("*)").rstrip(":")) for d in deny)]
        if hit:
            out.append({"a": _id(c), "b": "inventory", "relation": "conflicts",
                        "reason": f"与已有 deny 规则冲突：{hit[0]}"})
    return out

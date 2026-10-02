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


def _pair(a: dict, b: dict) -> list[tuple[str, str]]:
    out = []
    pa, ta, ka = _problem(a)
    pb, tb, kb_ = _problem(b)
    la, lb = _links(a), _links(b)
    item_a, item_b = (a.get("source") or {}).get("item_id"), (b.get("source") or {}).get("item_id")
    if pa and pa == pb and a.get("kind") == b.get("kind"):
        out.append(("duplicates", "同一问题的同类方案，保留一张"))
    elif item_a and item_a == item_b:
        out.append(("duplicates", "指向同一资源"))
    elif la.get("content_hash") and la.get("content_hash") == lb.get("content_hash"):
        out.append(("duplicates", "内容相同"))
    if set(la.get("conflicts_with") or []) & _names(b) or set(lb.get("conflicts_with") or []) & _names(a):
        out.append(("conflicts", "知识库标注两者冲突"))
    same_problem = (pa and pa == pb) or (ka and ka == kb_ and ta == tb)
    kinds = {a.get("kind"), b.get("kind")}
    if same_problem and kinds == {"rule", "hook"}:
        if ta in LADDER_TYPES:
            out.append(("complements", "验证阶梯：规则写清单，hook 兜底"))
        else:
            out.append(("conflicts", "同一约束不要同时写进规则与 hook，保留 hook"))
    if set(la.get("pairs_with") or []) & _names(b) or set(lb.get("pairs_with") or []) & _names(a):
        out.append(("complements", "知识库建议搭配使用"))
    elif same_problem and kinds == {"rule", "workflow"}:
        out.append(("complements", "验证阶梯：规则 + 工作流"))
    return out


def relations(cands: list[dict], deny: list[str] | None = None) -> list[dict]:
    """[{a, b, relation, reason}]; `deny` = installed permissions.deny entries (b = 'inventory')."""
    seen, out = set(), []
    for a, b in combinations(cands, 2):
        if _id(a) == _id(b):
            continue
        for relation, reason in _pair(a, b):
            key = (_id(a), _id(b), relation)
            if key not in seen:
                seen.add(key)
                out.append({"a": _id(a), "b": _id(b), "relation": relation, "reason": reason})
    for c in cands:
        if c.get("kind") != "permission_rule" or not deny:
            continue
        hit = [p for p in _allows(c) if any(p.startswith(d.rstrip("*)").rstrip(":")) for d in deny)]
        if hit:
            out.append({"a": _id(c), "b": "inventory", "relation": "conflicts",
                        "reason": f"与已有 deny 规则冲突：{hit[0]}"})
    return out

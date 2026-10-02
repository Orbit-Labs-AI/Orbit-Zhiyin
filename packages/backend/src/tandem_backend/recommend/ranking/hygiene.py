"""Slate hygiene: catalog-only filler, cross-route duplicates and template-variable leaks.

- A catalog card without a problem or evidence session is ``basis: catalog_only``: it
  only shows in the「资料库推荐」bucket (≤ ``LIBRARY_CAP``, below evidence-backed cards),
  and is dropped when nothing in the profile overlaps it.
- One remedy reached through several recall routes (``kb:x``, ``template:x``,
  ``catalog:kb:x``) or under the same title keeps a single card.
- ``{var}`` slots left in user-visible text are filled from problem vars / facts or replaced
  with a generic phrase, so no card ever shows a raw placeholder.
"""

from __future__ import annotations

import re

LIBRARY_CAP = 3
LIBRARY_LABEL = "资料库推荐"
_SLOT = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
_NORM = re.compile(r"[\s\W_]+", re.U)
GENERIC = {"software": "常用工具", "build_command": "构建命令", "instruction": "反复提出的要求",
           "name": "该配置", "project": "当前项目", "heads": "常用只读命令", "sequence": "固定步骤",
           "targets": "目标文件", "platforms": "相关平台", "files_examples": "相关文件"}
TEXT_FIELDS = ("title", "summary", "explain", "ui", "trial", "track", "file")


def catalog_only(raw: dict) -> bool:
    """A catalog card standing on no problem and no evidence session."""
    if (raw.get("source") or {}).get("origin") != "catalog" or raw.get("problem"):
        return False
    return not (raw.get("evidence") or {}).get("session_uids")


def profile_overlap(raw: dict) -> bool:
    """Profile / feature routes matched something of the user's profile."""
    routes = raw.get("routes") or {}
    return bool("profile" in routes or ((raw.get("feature_overlap") or {}).get("matched")))


def remedy_id(cand: dict) -> str | None:
    kb_id = (cand.get("links") or {}).get("kb_id")
    if kb_id:
        return kb_id
    item = (cand.get("source") or {}).get("item_id") or ""
    return item[3:] if item.startswith("kb:") else None


def norm_title(title) -> str:
    return _NORM.sub("", str(title or "")).lower()


def _strength(cand: dict) -> tuple:
    evidence = len((cand.get("evidence") or {}).get("session_uids") or ())
    return (cand.get("basis") not in ("catalog_only", "generic"), bool(cand.get("problem")), evidence,
            (cand.get("score") or {}).get("priority", 0.), (cand.get("score") or {}).get("utility", 0.))


def dedupe(cands: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep the strongest card per remedy rule / normalized title; losers get ``excluded``."""
    kept: list[dict] = []
    owner: dict[str, dict] = {}
    dropped: list[dict] = []
    for cand in sorted(cands, key=_strength, reverse=True):
        keys = [k for k in (f"rule:{remedy_id(cand)}" if remedy_id(cand) else None,
                            f"title:{norm_title(cand.get('title'))}" if norm_title(cand.get("title")) else None) if k]
        winner = next((owner[k] for k in keys if k in owner), None)
        if winner is not None:
            cand["excluded"] = f"duplicate:{winner['rec_key']}"
            dropped.append(cand)
            continue
        for k in keys:
            owner[k] = cand
        kept.append(cand)
    order = {id(c): i for i, c in enumerate(cands)}
    return sorted(kept, key=lambda c: order[id(c)]), dropped


def slot_values(raws: list[dict], inputs: dict) -> dict:
    """Run-wide fallbacks for ``{var}``: every problem's vars, then facts."""
    values: dict = {}
    for raw in raws:
        for k, v in ((raw.get("problem") or {}).get("vars") or {}).items():
            if isinstance(v, (str, int, float)) and str(v):
                values.setdefault(k, v)
    failures = ((inputs.get("facts") or {}).get("failures_by_software") or [])
    if failures and isinstance(failures, list) and isinstance(failures[0], dict) and failures[0].get("software"):
        values.setdefault("software", failures[0]["software"])
    return values


def fill(obj, values: dict):
    """Replace ``{var}`` slots in every string of ``obj`` (code braces such as JSON stay)."""
    if isinstance(obj, str):
        return _SLOT.sub(lambda m: str(values.get(m.group(1), GENERIC.get(m.group(1), "相关项"))), obj)
    if isinstance(obj, list):
        return [fill(x, values) for x in obj]
    if isinstance(obj, tuple):
        return tuple(fill(x, values) for x in obj)
    if isinstance(obj, dict):
        return {k: fill(v, values) for k, v in obj.items()}
    return obj


def scrub(cand: dict, values: dict) -> None:
    own = {k: v for k, v in ((cand.get("problem") or {}).get("vars") or {}).items()
           if isinstance(v, (str, int, float)) and str(v)}
    merged = {**values, **own}
    for field in TEXT_FIELDS:
        if cand.get(field) is not None:
            cand[field] = fill(cand[field], merged)

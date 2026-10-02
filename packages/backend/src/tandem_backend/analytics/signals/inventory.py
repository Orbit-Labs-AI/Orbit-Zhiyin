"""AN-11 inventory facts: installed-but-unused items and resident token overhead.

These are facts, not problems: RC-07 consumes them directly (``match_basis =
inventory_fact``). Items that cannot be observed through tool-call names (hooks,
rules, scheduled tasks) are ``not_matchable`` and never counted as unused.
"""

from collections import defaultdict
from typing import Any

from ..context import AnalysisContext
from ..stats import median

Record = dict[str, Any]

MATCHABLE = ("skill", "mcp", "plugin")


def _norm(value) -> str:
    return str(value or "").strip().lower()


def _uses(item: Record, call: Record) -> bool:
    name, kind = _norm(item.get("name")), item.get("type")
    if not name:
        return False
    if kind == "skill":
        return _norm(call.get("skill")) == name or (
            call.get("kind") == "skill" and name in _norm(call.get("name_raw")))
    if kind == "mcp":
        return _norm(call.get("mcp_server")) == name or _norm(call.get("name_raw")).startswith(
            f"mcp__{name}__")
    if kind == "plugin":
        return _norm(call.get("plugin")) == name or f"{name}:" in _norm(call.get("skill")) \
            or f"plugin_{name}_" in _norm(call.get("name_raw"))
    return False


def installed_unused(inventory: list[Record] | None, calls: list[Record] | None) -> Record:
    """Inventory items × call names in the selected window."""
    if inventory is None or calls is None:
        return {"status": "unavailable", "items": None, "installed_unused": None,
                "unused_n": None, "matchable_n": None}
    items = []
    for item in sorted(inventory, key=lambda i: (i.get("type") or "", _norm(i.get("name")))):
        if item.get("enabled") == 0 or item.get("enabled") is False:
            continue
        if item.get("type") not in MATCHABLE:
            items.append({**_brief(item), "status": "not_matchable", "used_calls": None})
            continue
        used = sum(_uses(item, c) for c in calls)
        items.append({**_brief(item), "status": "used" if used else "unused", "used_calls": used})
    unused = [i for i in items if i["status"] == "unused"]
    return {"status": "available", "items": items, "installed_unused": unused,
            "unused_n": len(unused), "matchable_n": sum(i["status"] != "not_matchable" for i in items),
            "basis": "measured"}


def _brief(item: Record) -> Record:
    return {k: item.get(k) for k in ("inv_id", "type", "name", "evidence", "config_path")}


def first_request_tokens(context: AnalysisContext) -> dict[str, int | None] | None:
    """``input_tokens`` of the first model request per main session (resident overhead proxy)."""
    if context.model_calls is None:
        return None
    by_session = defaultdict(list)
    for m in context.model_calls:
        by_session[m["session_uid"]].append(m)
    out = {}
    for sid in sorted(context.main_ids):
        rows = sorted(by_session.get(sid, []), key=lambda m: (m.get("ts") is None, m.get("ts") or 0,
                                                               m.get("call_uid") or ""))
        tokens = rows[0].get("input_tokens") if rows else None
        out[sid] = tokens if isinstance(tokens, int) and not isinstance(tokens, bool) else None
    return out


def resident_tokens_median(context: AnalysisContext) -> Record:
    tokens = first_request_tokens(context)
    values = None if tokens is None else [v for v in tokens.values() if v is not None]
    return {**median(values, basis="estimated"), "unit": "tokens",
            "meaning": "每个主会话首个模型请求的 input_tokens 中位数；近似常驻上下文开销"}


def inventory_facts(context: AnalysisContext, calls: list[Record] | None) -> Record:
    return {"installed_unused": installed_unused(context.bundle.inventory, calls),
            "resident_tokens_median": resident_tokens_median(context)}

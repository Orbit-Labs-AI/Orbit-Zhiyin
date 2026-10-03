"""Route ④: graph and co-occurrence around what the user already has installed.

KB ``pairs_with`` edges propose complements of installed remedies; tag Jaccard
against the installed set re-scores the candidate pool. Complements carry
``match_basis="complement"`` so the slate keeps (at most one of) them next to
problem-driven cards instead of suppressing them as generic.
"""

from .kb_route import from_rule


def installed_keys(inputs: dict, memory: dict) -> set[str]:
    keys = {f"catalog:{item['catalog_item_id']}" for item in inputs.get("inventory") or () if item.get("catalog_item_id")}
    keys |= {key for key, state in (memory.get("state") or {}).items() if state.get("status") == "installed"}
    return keys


def _kb_ids(keys) -> set[str]:
    return {key[3:].partition("@")[0] for key in keys if key.startswith("kb:")}


def recall(rules, inputs: dict, memory: dict, pool: dict[str, dict]) -> tuple[list, dict]:
    """Return (rows, payload); ``pool`` is the merged payload of earlier routes (read only)."""
    installed = installed_keys(inputs, memory)
    by_id = {rule.id: rule for rule in rules}
    muted = set(memory.get("muted_kb_rules") or ())
    installed_ids = _kb_ids(installed)
    scores: dict[str, float] = {}
    payload: dict[str, dict] = {}
    for rule_id in sorted(installed_ids):
        for target in by_id[rule_id].remedy.pairs_with if rule_id in by_id else ():
            key = f"kb:{target}"
            if target in installed_ids or target in muted or by_id[target].predicate:
                continue
            scores[key] = max(scores.get(key, 0), .6)
            if key not in pool:
                payload[key] = from_rule(by_id[target], None, inputs, rec_key=key, match_basis="complement")
                payload[key]["explain_hints"]["reason_template"] = f"与已安装的「{by_id[rule_id].title}」搭配使用。"
    tags: set[str] = set()
    for key in installed:
        if key in pool:
            tags |= set(pool[key]["tags"])
        elif key.startswith("kb:") and key[3:].partition("@")[0] in by_id:
            tags |= set(by_id[key[3:].partition("@")[0]].tags)
    if tags:
        for key, cand in pool.items():
            if key in installed or not cand["tags"]:
                continue
            union = tags | set(cand["tags"])
            jaccard = len(tags & set(cand["tags"])) / len(union)
            if jaccard > .1:
                scores[key] = max(scores.get(key, 0), round(jaccard, 6))
    return sorted(scores.items(), key=lambda row: (-row[1], row[0])), payload

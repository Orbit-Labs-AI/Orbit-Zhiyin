"""Profile → catalog items by vocabulary overlap (RC-09 ``feature_overlap`` primitive).

Items are never materialized in the user id space: profile ids are expanded into
``item_feature`` (feature, value) conditions and summed on ``feature_lookup``.
"""

from __future__ import annotations

from .vocab import to_catalog_pairs

TYPE_ALIAS = {"mcp": "mcp_server"}
TOP_IDS, BATCH = 64, 200


def match_items(svc, profile: dict, *, kinds=None, k: int = 50, agent=None) -> list[dict]:
    hub = svc.hub
    if "c" not in hub.attached() or not hub.has("c", "item_feature"):
        return []
    pairs: dict[tuple[str, str], tuple[float, str]] = {}
    ranked = sorted(profile.get("vector", {}).items(), key=lambda kv: (-kv[1], kv[0]))
    for fid, w in ranked[:TOP_IDS]:
        for pair in to_catalog_pairs(fid):
            if pair not in pairs or pairs[pair][0] < w:
                pairs[pair] = (w, fid)
    total = sum(w for w, _ in pairs.values())
    if not total:
        return []
    filters, extra = ["i.status = 'active'"], []
    if kinds:
        types = sorted({TYPE_ALIAS.get(kind, kind) for kind in kinds})
        filters.append(f"i.type IN ({','.join('?' * len(types))})")
        extra.extend(types)
    if agent:
        filters.append("i.agents LIKE ?")
        extra.append(f'%"{agent}"%')
    hits: dict[str, dict[tuple[str, str], float]] = {}
    keys = list(pairs)
    with hub.read() as db:
        for i in range(0, len(keys), BATCH):
            part = keys[i:i + BATCH]
            values = ",".join("(?, ?)" for _ in part)
            sql = (f"SELECT f.item_id, f.feature, f.value, MAX(f.weight) FROM c.item_feature f "
                   f"JOIN c.catalog_item i ON i.item_id = f.item_id "
                   f"WHERE (f.feature, f.value) IN (VALUES {values}) AND {' AND '.join(filters)} "
                   f"GROUP BY f.item_id, f.feature, f.value")
            args = [x for pair in part for x in pair] + extra
            for item_id, feature, value, weight in db.execute(sql, args):
                hits.setdefault(item_id, {})[(feature, value)] = weight
    out = []
    for item_id, matched in hits.items():
        score = sum(pairs[p][0] * min(weight, 1.0) for p, weight in matched.items()) / total
        out.append({"item_id": item_id, "score": round(score, 6),
                    "parts": {"feature_overlap": round(score, 6)},
                    "matched": sorted(({"id": pairs[p][1], "feature": p[0], "value": p[1],
                                        "w": pairs[p][0]} for p in matched),
                                      key=lambda m: (-m["w"], m["feature"], m["value"]))})
    out.sort(key=lambda r: (-r["score"], r["item_id"]))
    return out[:k]

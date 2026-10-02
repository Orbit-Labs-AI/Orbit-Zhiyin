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
    keys = list(pairs)
    scores: dict[str, float] = {}
    with hub.read() as db:
        for i in range(0, len(keys), BATCH):
            part = keys[i:i + BATCH]
            values = ",".join("(?, ?, ?)" for _ in part)
            sql = (f"WITH q(feature, value, w) AS (VALUES {values}), "
                   f"hit AS (SELECT f.item_id, q.w * MIN(MAX(f.weight), 1.0) s FROM q "
                   f"JOIN c.item_feature f ON f.feature = q.feature AND f.value = q.value "
                   f"GROUP BY f.item_id, f.feature, f.value) "
                   f"SELECT hit.item_id, SUM(hit.s) FROM hit JOIN c.catalog_item i "
                   f"ON i.item_id = hit.item_id WHERE {' AND '.join(filters)} "
                   f"GROUP BY hit.item_id")
            args = [x for pair in part for x in (*pair, pairs[pair][0])] + extra
            for item_id, score in db.execute(sql, args):
                scores[item_id] = scores.get(item_id, 0.0) + score
        top = sorted(scores, key=lambda item: (-scores[item], item))[:k]
        matched: dict[str, list] = {item: [] for item in top}
        for i in range(0, len(top), 500):
            part = top[i:i + 500]
            for item_id, feature, value in db.execute(
                    f"SELECT DISTINCT item_id, feature, value FROM c.item_feature "
                    f"WHERE item_id IN ({','.join('?' * len(part))})", part):
                if (feature, value) in pairs:
                    w, fid = pairs[(feature, value)]
                    matched[item_id].append({"id": fid, "feature": feature, "value": value,
                                             "w": w})
    out = []
    for item_id in top:
        score = round(scores[item_id] / total, 6)
        out.append({"item_id": item_id, "score": score, "parts": {"feature_overlap": score},
                    "matched": sorted(matched[item_id],
                                      key=lambda m: (-m["w"], m["feature"], m["value"]))})
    return out

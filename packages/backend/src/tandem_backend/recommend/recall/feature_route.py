"""Route ③b: profile × catalog features (RC-09 ``feature_overlap``) via the features module.

``features.profile(scope, signals=…)`` folds the active problems in as
``friction:<type>`` signals, ``features.match_items`` sums vocabulary overlap
against catalog ``item_feature``. Item metadata comes from the CatalogService
store; an item whose matched features include an active problem's friction is
tied to that problem, the rest stand on the profile.
"""

import json

from .catalog_route import TYPE_KIND, from_item

K = 20


def signals(problems: list[dict]) -> list[dict]:
    return [{"id": f"friction:{p['type']}", "weight": round(max(.3, min(1., p["wilson_lo"] * 2)), 4),
             "n": int(p["sessions"])} for p in problems if p["status"] == "active"]


def legacy_profile(profile: dict) -> dict:
    """features.profile body → the dict shape catalog_route / rank read (tags, evidence, langs)."""
    tags = {e["id"].split(":", 1)[-1]: e["weight"] for e in profile.get("tags") or ()}
    evidence = {e["id"].split(":", 1)[-1]: e.get("sessions", 0) for e in profile.get("tags") or ()}
    by_ns = lambda ns: [e["id"].split(":", 1)[1] for e in profile.get("tags") or () if e.get("ns") == ns]  # noqa: E731
    return {"tags": tags, "evidence_sessions": evidence, "languages": by_ns("lang"),
            "tools": by_ns("tool"), "frameworks": by_ns("fw"), "vector": profile.get("vector") or {}}


def _items(catalog, ids: list[str]) -> dict[str, dict]:
    with catalog.store.connect(True) as conn:
        rows = conn.execute("SELECT * FROM catalog_item WHERE status='active' AND item_id IN "
                            "(SELECT value FROM json_each(?))", (json.dumps(ids),)).fetchall()
    out = {}
    for row in rows:
        kind = TYPE_KIND.get(row["type"])
        if not kind:
            continue
        meta = json.loads(row["metadata"] or "{}")
        out[row["item_id"]] = {"item_id": row["item_id"], "kind": kind, "name": row["name"],
                               "summary": row["summary"] or "", "url": row["url"],
                               "agents": json.loads(row["agents"] or "[]"), "license": row["license"],
                               "difficulty": row["difficulty"], "risk": meta.get("risk") or [],
                               "content_hash": row["content_hash"], "version_id": row["latest_version"],
                               "verified": True}
    return out


def recall(problems: list[dict], inputs: dict, features, catalog, *, agent: str | None = None,
           meta: dict | None = None) -> tuple[list[tuple[str, float]], dict[str, dict]]:
    meta = meta if meta is not None else {}
    profile = features.profile(inputs.get("scope"), signals=signals(problems) or None)
    meta["feature_profile"] = profile
    if catalog is None:
        return [], {}
    matches = features.match_items(profile, agent=agent, k=K)
    if not matches:
        return [], {}
    items = _items(catalog, [m["item_id"] for m in matches])
    by_type = {p["type"]: p for p in problems if p["status"] == "active"}
    rows, payload = [], {}
    for match in matches:
        item = items.get(match["item_id"])
        if item is None:
            continue
        item["tags"] = sorted({m["value"] for m in match.get("matched") or () if m["feature"] != "friction"})
        problem = next((by_type[m["value"]] for m in match.get("matched") or ()
                        if m["feature"] == "friction" and m["value"] in by_type), None)
        cand = from_item(item, problem, inputs, match_basis="catalog_feature" if problem else "profile")
        cand["feature_overlap"] = {"score": match["score"],
                                   "matched": [m["id"] for m in match.get("matched") or ()][:10]}
        rows.append((cand["rec_key"], float(match["score"]) + 1e-6))
        payload[cand["rec_key"]] = cand
    return rows, payload

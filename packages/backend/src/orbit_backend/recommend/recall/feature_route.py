"""Route ③b: profile × catalog features (RC-09 ``feature_overlap``) via the features module.

``features.profile(scope, signals=…)`` folds the active problems in as
``friction:<type>`` signals, ``features.match_items`` sums vocabulary overlap
against catalog ``item_feature``. Item metadata comes from the CatalogService
store; an item whose matched features include an active problem's friction is
tied to that problem, the rest stand on the profile.
"""

import json

from .catalog_route import TYPE_KIND, VERIFIED, from_item, item_support

K = 20
# Profile-only matches (no friction) need real overlap: a share of the profile weight, more than
# one matched feature or one specific feature (framework, MCP, skill, domain, software …), and a
# matched feature seen in enough sessions. Generic namespaces alone (a language, ``tool:browser``,
# a shell command) match half the catalog.
GENERIC_NS = {"tool", "cmd", "cmdfam", "cmdcls", "lang", "ftype", "agent"}
MIN_PROFILE_SCORE, MIN_PROFILE_SESSIONS = .08, 3


def _sessions_by_id(profile: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    entries = list(profile.get("tags") or ())
    for group in (profile.get("groups") or {}).values():
        entries += list(group or ())
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id"):
            out[entry["id"]] = max(out.get(entry["id"], 0), int(entry.get("sessions") or 0))
    return out


def precise(match: dict, sessions: dict[str, int]) -> bool:
    """A profile-only match worth showing (see GENERIC_NS / MIN_PROFILE_*)."""
    matched = [m for m in match.get("matched") or () if m.get("feature") != "friction"]
    ids = {m["id"] for m in matched}
    specific = [i for i in ids if i.split(":", 1)[0] not in GENERIC_NS]
    if not specific and (len(ids) < 2 or float(match.get("score") or 0) < MIN_PROFILE_SCORE):
        return False
    return max((sessions.get(i, 0) for i in ids), default=0) >= MIN_PROFILE_SESSIONS


def signals(problems: list[dict]) -> list[dict]:
    return [{"id": f"friction:{p['type']}", "weight": round(max(.3, min(1., p["wilson_lo"] * 2)), 4),
             "n": int(p["sessions"])} for p in problems if p["status"] == "active"]


def legacy_profile(profile: dict) -> dict:
    """features.profile body → the dict shape catalog_route / rank read (tags, evidence, langs)."""
    tags = {e["id"].split(":", 1)[-1]: e["weight"] for e in profile.get("tags") or ()}
    evidence = {e["id"].split(":", 1)[-1]: e.get("sessions", 0) for e in profile.get("tags") or ()}
    entries = list(profile.get("tags") or ())
    for group in (profile.get("groups") or {}).values():
        entries.extend(group or ())
    by_ns = lambda ns: sorted({e["id"].split(":", 1)[1] for e in entries if e.get("ns") in ns})  # noqa: E731
    return {"tags": tags, "evidence_sessions": evidence, "languages": by_ns({"lang"}),
            "tools": by_ns({"tool"}), "software": by_ns({"cmd", "sw"}),
            "frameworks": by_ns({"fw"}), "vector": profile.get("vector") or {}}


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
                               "verified": row["verification"] in VERIFIED if "verification" in row.keys() else False,
                               "support": item_support(row["metadata"])}
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
    sessions = _sessions_by_id(profile)
    rows, payload = [], {}
    dropped = 0
    for match in matches:
        item = items.get(match["item_id"])
        if item is None:
            continue
        item["tags"] = sorted({m["value"] for m in match.get("matched") or () if m["feature"] != "friction"})
        problem = next((by_type[m["value"]] for m in match.get("matched") or ()
                        if m["feature"] == "friction" and m["value"] in by_type), None)
        if problem is None and not precise(match, sessions):
            dropped += 1
            continue
        cand = from_item(item, problem, inputs, match_basis="catalog_feature" if problem else "profile")
        cand["feature_overlap"] = {"score": match["score"],
                                   "matched": [m["id"] for m in match.get("matched") or ()][:10]}
        rows.append((cand["rec_key"], float(match["score"]) + 1e-6))
        payload[cand["rec_key"]] = cand
    meta["feature_dropped"] = dropped
    return rows, payload

"""User feature profile: tf-idf weighted vocabulary ids over the sessions in a scope.

The 128-d centroid is a deterministic signed feature hash (not a semantic embedding);
``hash_vector`` lets the item side compute the same thing from its own ids.
"""

from __future__ import annotations

import hashlib
import math
import time
from array import array

from .scope import normalize, session_where
from .vocab import NAMESPACES, VOCAB_VERSION, label, split

DIM = 128
TAG_LIMIT, TAG_PER_NS, VECTOR_LIMIT, GROUP_LIMIT = 24, 6, 256, 10


def hash_vector(pairs) -> list[float]:
    vec = [0.0] * DIM
    for fid, weight in pairs:
        h = int.from_bytes(hashlib.blake2b(fid.encode(), digest_size=8).digest(), "big")
        vec[h % DIM] += weight if (h >> 32) & 1 else -weight
    length = math.sqrt(sum(v * v for v in vec))
    return [v / length for v in vec] if length else vec


def pack(vec: list[float] | None) -> bytes | None:
    return array("f", vec).tobytes() if vec else None


def unpack(blob: bytes | None) -> list[float] | None:
    if not blob:
        return None
    out = array("f")
    out.frombytes(blob)
    return out.tolist()


def build_profile(svc, scope=None, signals=None, include=()) -> dict:
    started = time.perf_counter()
    where, params = session_where(scope)
    if "t" not in svc.hub.attached():
        stats, rows, with_features = (0, None, None), [], 0
    else:
        with svc.hub.read() as db:
            stats = db.execute(f"SELECT COUNT(*), MIN(s.started_at), MAX(s.started_at) "
                               f"FROM t.session s WHERE {where}", params).fetchone()
            rows = db.execute(
                f"SELECT v.name, SUM(f.n) n, COUNT(*) sess FROM sess_feat f "
                f"JOIN t.session s ON s.session_uid = f.session_uid "
                f"JOIN feat_vocab v ON v.fid = f.fid WHERE {where} GROUP BY f.fid",
                params).fetchall()
            with_features = db.execute(
                f"SELECT COUNT(DISTINCT f.session_uid) FROM sess_feat f JOIN t.session s "
                f"ON s.session_uid = f.session_uid WHERE {where}", params).fetchone()[0]
    n_sessions = stats[0] or 0
    raw = {}
    for name, n, sess in rows:
        idf = math.log((n_sessions + 1) / (sess + 0.5))
        raw[name] = (max(0.05, (1 + math.log(n)) * idf), n, sess)
    top = max((w for w, _, _ in raw.values()), default=1.0) or 1.0
    entries = {name: {"id": name, "ns": split(name)[0], "label": label(name),
                      "weight": round(w / top, 4), "n": n, "sessions": sess,
                      "share": round(sess / n_sessions, 4) if n_sessions else 0.0}
               for name, (w, n, sess) in raw.items()}
    for signal in signals or ():
        fid = signal["id"]
        weight = max(0.0, min(1.0, float(signal.get("weight", 1.0))))
        entry = entries.setdefault(fid, {"id": fid, "ns": split(fid)[0], "label": label(fid),
                                         "weight": 0.0, "n": 0, "sessions": 0, "share": 0.0})
        entry["weight"] = max(entry["weight"], round(weight, 4))
        entry["n"] += int(signal.get("n", 0))
        entry["signal"] = True
    ranked = sorted(entries.values(), key=lambda e: (-e["weight"], -e["n"], e["id"]))
    tags, per_ns = [], {}
    for entry in ranked:
        if len(tags) >= TAG_LIMIT:
            break
        if per_ns.get(entry["ns"], 0) < TAG_PER_NS:
            per_ns[entry["ns"]] = per_ns.get(entry["ns"], 0) + 1
            tags.append(entry)
    groups: dict[str, list] = {}
    for entry in ranked:
        bucket = groups.setdefault(entry["ns"], [])
        if len(bucket) < GROUP_LIMIT:
            bucket.append(entry)
    vector = {e["id"]: e["weight"] for e in ranked[:VECTOR_LIMIT]}
    centroid = hash_vector(vector.items()) if vector else None
    return {
        "scope": normalize(scope),
        "n_sessions": n_sessions,
        "built_at": int(time.time() * 1000),
        "tags": tags,
        "vector": vector,
        "groups": {ns: groups[ns] for ns in NAMESPACES if ns in groups},
        "coverage": {"sessions": n_sessions, "with_features": with_features,
                     "first_ts": stats[1], "last_ts": stats[2]},
        "centroid": centroid,
        "vocab": VOCAB_VERSION,
        "build_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def evidence(svc, body: dict, per_tag: int = 5) -> dict:
    """Recent session uids behind each of the top 10 tags (not cached)."""
    if "t" not in svc.hub.attached():
        return {}
    where, params = session_where(body.get("scope"))
    out = {}
    with svc.hub.read() as db:
        for tag in body["tags"][:10]:
            out[tag["id"]] = [row[0] for row in db.execute(
                f"SELECT f.session_uid FROM sess_feat f JOIN t.session s "
                f"ON s.session_uid = f.session_uid WHERE f.fid = "
                f"(SELECT fid FROM feat_vocab WHERE name = ?) AND {where} "
                f"ORDER BY s.started_at DESC LIMIT ?", [tag["id"], *params, per_tag])]
    return out

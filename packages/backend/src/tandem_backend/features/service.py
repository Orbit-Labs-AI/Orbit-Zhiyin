"""FeatureService: profile cache, item matching, and the linked-inventory / search entry
points. Reads go through ``QueryHub``; writes only through ``AppDB.write()``."""

from __future__ import annotations

import gzip
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from .. import platform
from . import sessfeat
from .hub import QueryHub
from .linked import compute_linked
from .match import match_items
from .profile import build_profile, evidence, pack, unpack
from .scope import normalize
from .search import search as run_search
from .vocab import VOCAB_VERSION, vocab_table

LRU_SIZE, KEEP_SCOPES = 16, 8


class FeatureService:
    def __init__(self, home: Path, appdb, revisions: Callable[[], dict]):
        self.home = Path(home)
        self.appdb = appdb
        self.revisions = revisions
        self.hub = QueryHub(self.home, appdb.path)
        self.lock = threading.Lock()
        self.materialize_lock = threading.Lock()
        self.fid_cache: dict[str, int] = {}
        self.lru: OrderedDict[tuple, dict] = OrderedDict()
        self.building: dict[tuple, threading.Thread] = {}

    # revisions -----------------------------------------------------------------
    def data_rev(self) -> int:
        return int(self.revisions().get("data_rev") or 0)

    def catalog_rev(self) -> str:
        if "c" not in self.hub.attached() or not self.hub.has("c", "catalog_meta"):
            return "0"
        with self.hub.read() as db:
            row = db.execute("SELECT value FROM c.catalog_meta WHERE key = 'generation'").fetchone()
        return str(row[0]) if row else "0"

    def revs(self) -> dict:
        rev = self.revisions()
        return {"data": int(rev.get("data_rev") or 0), "inventory": int(rev.get("inventory_rev") or 0),
                "catalog": self.catalog_rev(), "vocab": VOCAB_VERSION}

    def etag(self) -> str:
        """Revision tag for conditional GETs of profile / linked (see routes_features)."""
        revs = self.revs()
        return (f"{revs['data']}.{revs['inventory']}.{revs['catalog']}."
                f"{platform.rev_token('features.profile')}")

    # profile -------------------------------------------------------------------
    def profile(self, scope=None, *, signals=None, include=(), refresh=False) -> dict:
        with platform.timed("features.profile"):
            return self._profile(scope, signals, include, refresh)

    def _key(self, scope, signals) -> tuple[str, tuple]:
        from ..services.snapshots import scope_hash

        params = {"signals": sorted((s["id"], s.get("weight"), s.get("n")) for s in signals)} \
            if signals else None
        digest = scope_hash(normalize(scope), params)
        revs = self.revs()
        return digest, (digest, revs["data"], revs["inventory"], revs["catalog"], revs["vocab"])

    def _profile(self, scope, signals, include, refresh) -> dict:
        digest, key = self._key(scope, signals)
        body, state = (None, "miss") if refresh else self._cached(key)
        if body is None and not refresh:
            old = self._latest(digest)
            if old is not None:
                body, state = old, "stale"
                self._rebuild_async(key, scope, signals)
        if body is None:
            body = self._build(key, scope, signals)
        out = dict(body, scope_hash=digest, cache=state,
                   revs=dict(zip(("data", "inventory", "catalog", "vocab"), key[1:], strict=True)))
        if state == "stale":
            out["revs"] = body.get("revs", out["revs"])
        if "evidence" in include:
            out["evidence"] = evidence(self, body)
        return out

    def _cached(self, key: tuple) -> tuple[dict | None, str]:
        with self.lock:
            if key in self.lru:
                self.lru.move_to_end(key)
                return self.lru[key], "hit"
        with self.hub.read() as db:
            row = db.execute("SELECT body, centroid FROM feat_profile WHERE scope_hash = ? AND "
                             "data_rev = ? AND inventory_rev = ? AND catalog_rev = ? AND vocab = ?",
                             key).fetchone()
        if row is None:
            return None, "miss"
        body = self._decode(row)
        self._remember(key, body)
        with self.appdb.write() as db:
            db.execute("UPDATE feat_profile SET accessed_at = ? WHERE scope_hash = ? AND "
                       "data_rev = ? AND inventory_rev = ? AND catalog_rev = ? AND vocab = ?",
                       (int(time.time() * 1000), *key))
        return body, "hit"

    def _latest(self, digest: str) -> dict | None:
        with self.hub.read() as db:
            row = db.execute("SELECT body, centroid FROM feat_profile WHERE scope_hash = ? "
                             "ORDER BY computed_at DESC LIMIT 1", (digest,)).fetchone()
        return self._decode(row) if row else None

    @staticmethod
    def _decode(row) -> dict:
        body = json.loads(gzip.decompress(row[0]))
        body["centroid"] = unpack(row[1])
        return body

    def _remember(self, key: tuple, body: dict) -> None:
        with self.lock:
            self.lru[key] = body
            self.lru.move_to_end(key)
            while len(self.lru) > LRU_SIZE:
                self.lru.popitem(last=False)

    def _build(self, key: tuple, scope, signals) -> dict:
        if sessfeat.stale(self):
            sessfeat.materialize(self)
        body = build_profile(self, scope, signals)
        body["revs"] = dict(zip(("data", "inventory", "catalog", "vocab"), key[1:], strict=True))
        stored = {k: v for k, v in body.items() if k != "centroid"}
        now = int(time.time() * 1000)
        with self.appdb.write() as db:
            db.execute("DELETE FROM feat_profile WHERE scope_hash = ?", (key[0],))
            db.execute("INSERT INTO feat_profile VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (*key, json.dumps(body["scope"], sort_keys=True),
                        gzip.compress(json.dumps(stored, ensure_ascii=False).encode()),
                        pack(body["centroid"]), body["n_sessions"], now,
                        int(body["build_ms"]), now))
            db.execute("DELETE FROM feat_profile WHERE scope_hash NOT IN (SELECT scope_hash FROM "
                       "feat_profile GROUP BY scope_hash ORDER BY MAX(accessed_at) DESC LIMIT ?)",
                       (KEEP_SCOPES,))
        with self.lock:
            for old in [k for k in self.lru if k[0] == key[0]]:
                del self.lru[old]
        self._remember(key, body)
        return body

    def _rebuild_async(self, key: tuple, scope, signals) -> None:
        with self.lock:
            if key in self.building and self.building[key].is_alive():
                return

            def run():
                try:
                    self._build(key, scope, signals)
                    platform.bump_rev("features.profile")  # clients holding the stale body refetch
                finally:
                    with self.lock:
                        self.building.pop(key, None)

            thread = threading.Thread(target=run, name="feat-profile", daemon=True)
            self.building[key] = thread
        thread.start()

    def wait_idle(self, timeout: float | None = None) -> None:
        with self.lock:
            threads = list(self.building.values())
        for thread in threads:
            thread.join(timeout)

    # matching / vocab ----------------------------------------------------------
    def match(self, profile: dict, **kw) -> list[dict]:
        return match_items(self, profile, **kw)

    def vocab(self) -> dict:
        return vocab_table()

    # linked inventory and search ------------------------------------------------
    def _write(self, fn) -> None:
        with self.appdb.write() as db:
            fn(db)

    def linked_inventory(self, scope=None, **filters) -> dict:
        s = normalize(scope)
        revs = self.revs()
        agent = list(s["agent_ids"]) if s.get("agent_ids") else None  # every listed agent
        with self.hub.read() as db:
            result = compute_linked(db, revs=revs, project_ids=s.get("project_ids"),
                                    agent=agent, write=self._write)
        wanted_type, wanted_status = filters.get("type"), filters.get("status")
        if wanted_type or wanted_status:
            result = dict(result, items=[
                item for item in result.get("items", [])
                if (not wanted_type or item.get("type") == wanted_type)
                and (not wanted_status or item.get("status") == wanted_status)])
        return result

    def search(self, q: str, kinds=None, scope=None, limit: int = 20,
               session_cover: bool = False) -> dict:
        result = run_search(self.home, q, kinds=kinds, scope=normalize(scope), limit=limit,
                            session_cover=session_cover,
                            data_rev=self.data_rev(), tandem_db=self.home / "tandem.db",
                            catalog_db=self.home / "catalog.db", app_db=self.appdb.path,
                            linked=self.linked_inventory)  # search's own bounded pool
        platform.record("features.search", result["took_ms"], partial=bool(result["partial"]))
        for source in result["partial"]:
            platform.record("features.search.partial", source=source)
        return result

    def close(self) -> None:
        self.wait_idle(5)
        self.hub.close()

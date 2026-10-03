"""Immutable in-memory snapshot of filter columns, feature postings and chunk ownership.

Eligibility becomes a boolean mask over active items instead of per-row SQL subqueries.
The store rebuilds the snapshot lazily when ``catalog_meta.generation`` moves.
"""

import json
import threading
from typing import get_args

import numpy as np

from .contracts import MatchRequest, ResourceType

KINDS = list(get_args(ResourceType))
KIND_CODE = {kind: code for code, kind in enumerate(KINDS)}
VERIFIED = ("repository_and_skill_read", "repository_and_source_read")
MAX_AGENTS = 64


class CatalogIndex:
    def __init__(self, generation: int):
        self.generation = generation
        self._matrices = {}
        self._lock = threading.Lock()

    @classmethod
    def build(cls, conn, generation: int) -> "CatalogIndex":
        self = cls(generation)
        rows = conn.execute("SELECT item_id,type,canonical_of,listable,difficulty,agents,language,official,risk_level,"
                            "origin,verification,content_hash,license FROM catalog_item WHERE status='active' "
                            "ORDER BY item_id").fetchall()
        self.ids = [r["item_id"] for r in rows]
        self.pos = {item_id: i for i, item_id in enumerate(self.ids)}
        self.content_hash = [r["content_hash"] for r in rows]
        self.kind = np.array([KIND_CODE.get(r["type"], -1) for r in rows], dtype=np.int8)
        self.canonical = np.array([r["canonical_of"] is None for r in rows], dtype=bool)
        self.listable = np.array([r["listable"] for r in rows], dtype=bool)
        self.difficulty = np.array([r["difficulty"] for r in rows], dtype=np.int8)
        self.official = np.array([r["official"] for r in rows], dtype=bool)
        self.risk_level = np.array([r["risk_level"] for r in rows], dtype=np.int8)
        self.local = np.array([r["origin"] == "local" for r in rows], dtype=bool)
        self.verified = np.array([r["verification"] in VERIFIED for r in rows], dtype=bool)
        self.licenses = sorted({r["license"] or "" for r in rows})
        codes = {value: code for code, value in enumerate(self.licenses)}
        self.license = np.array([codes[r["license"] or ""] for r in rows], dtype=np.int32)
        self.agent_bits, self.lang_codes = {}, {}
        agent_mask = np.zeros(len(rows), dtype=np.uint64)
        language = np.zeros(len(rows), dtype=np.int16)
        for i, row in enumerate(rows):
            bits = 0
            for agent in json.loads(row["agents"]):
                if agent not in self.agent_bits and len(self.agent_bits) < MAX_AGENTS:
                    self.agent_bits[agent] = len(self.agent_bits)
                if agent in self.agent_bits:
                    bits |= 1 << self.agent_bits[agent]
            agent_mask[i] = bits
            language[i] = self.lang_codes.setdefault(row["language"], len(self.lang_codes))
        self.agent_mask, self.language = agent_mask, language
        self.lang_any = language == self.lang_codes.get("any", -1)
        # One effective posting per (item, key): curated rows win, otherwise the larger weight.
        best, keys = {}, [set() for _ in rows]
        for item_id, feature, value, weight, origin in conn.execute(
                "SELECT item_id,feature,value,weight,origin FROM item_feature"):
            i = self.pos.get(item_id)
            if i is None:
                continue
            postings = best.setdefault((feature, value), {})
            curated = origin == "curated"
            old = postings.get(i)
            if old is None or (curated and not old[1]) or (curated == old[1] and weight > old[0]):
                postings[i] = (weight, curated)
            keys[i].add((feature, value))
        self.item_keys = [frozenset(k) for k in keys]
        self.postings = {key: (np.fromiter(p.keys(), dtype=np.int32, count=len(p)),
                               np.array([w for w, _ in p.values()], dtype=np.float32),
                               np.array([c for _, c in p.values()], dtype=bool)) for key, p in best.items()}
        chunk_rows = conn.execute("SELECT chunk_rowid,item_id,ordinal,embed FROM resource_chunk").fetchall()
        size = max((r[0] for r in chunk_rows), default=-1) + 1
        self.chunk_item = np.full(size, -1, dtype=np.int32)
        self.chunk_ordinal = np.zeros(size, dtype=np.int32)
        embed = []
        for rowid, item_id, ordinal, flag in chunk_rows:
            i = self.pos.get(item_id, -1)
            self.chunk_item[rowid] = i
            self.chunk_ordinal[rowid] = ordinal
            if flag and i >= 0:
                embed.append(i)
        self.embed_items = np.array(embed, dtype=np.int32)
        return self

    def __len__(self):
        return len(self.ids)

    def items_of(self, rowids: np.ndarray) -> np.ndarray:
        rowids = np.asarray(rowids, dtype=np.int64)
        result = np.full(len(rowids), -1, dtype=np.int32)
        valid = (rowids >= 0) & (rowids < len(self.chunk_item))
        result[valid] = self.chunk_item[rowids[valid]]
        return result

    def curated(self, key) -> np.ndarray:
        result = np.zeros(len(self.ids), dtype=bool)
        if key in self.postings:
            idx, _, curated = self.postings[key]
            result[idx[curated]] = True
        return result

    def mask(self, request: MatchRequest, conn=None, *, audit: list | None = None) -> np.ndarray:
        previous = np.ones(len(self), dtype=bool) if audit is not None else None

        def observe(stage):
            nonlocal previous
            if audit is None:
                return
            removed = np.flatnonzero(previous & ~mask)
            audit.append({"stage": stage, "input_count": int(previous.sum()),
                          "kept_count": int(mask.sum()), "rejected_count": len(removed),
                          "kept_types": {k: int((mask & (self.kind == code)).sum())
                                         for k, code in KIND_CODE.items() if (mask & (self.kind == code)).any()},
                          "rejected_types": {k: int((self.kind[removed] == code).sum())
                                             for k, code in KIND_CODE.items() if (self.kind[removed] == code).any()},
                          "rejected_ids": [self.ids[i] for i in removed[:1000]],
                          "omitted_ids": max(0, len(removed) - 1000), "score": None})
            previous = mask.copy()

        mask = self.canonical & (self.difficulty <= request.max_difficulty)
        observe("canonical_and_difficulty")
        if request.types:
            mask &= np.isin(self.kind, [KIND_CODE[t] for t in request.types])
        observe("requested_types")
        for item_id in request.excluded_ids:
            if item_id in self.pos:
                mask[self.pos[item_id]] = False
        observe("excluded_ids")
        if request.agents:
            bits = 0
            for agent in request.agents:
                if agent in self.agent_bits:
                    bits |= 1 << self.agent_bits[agent]
            compatible = (self.agent_mask & np.uint64(bits)) != 0
            if request.purpose == "library":
                compatible |= self.agent_mask == 0
            mask &= compatible
        observe("agents_listed")
        if request.language:
            codes = [self.lang_codes[v] for v in request.language.split("_or_") if v in self.lang_codes]
            mask &= self.lang_any | np.isin(self.language, codes)
        observe("language")
        if request.source_ids:
            allowed = np.zeros(len(self.ids), dtype=bool)
            for (item_id,) in conn.execute(
                    "SELECT DISTINCT s.item_id FROM item_source s JOIN catalog_source c USING(source_id) WHERE "
                    "s.status='active' AND (c.enabled=1 OR c.source_id='local') AND s.source_id IN (SELECT value FROM json_each(?))",
                    (json.dumps(request.source_ids),)):
                if item_id in self.pos:
                    allowed[self.pos[item_id]] = True
            mask &= allowed
        observe("source")
        if request.purpose == "recommendation":
            mask &= self.verified & self.curated(("friction", request.problem_type)) & self.curated(("scene", request.scene))
            dimensions = np.zeros(len(self.ids), dtype=bool)
            for feature in request.features:
                if feature.feature == "dimension":
                    dimensions |= self.curated(("dimension", feature.value))
            mask &= dimensions
        observe("recommendation_evidence")
        return mask

    def matrix(self, conn, model_id: str, dimensions: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(fp16[n, d] vectors, owning item index[n], chunk_rowid[n]) for embed chunks of active items."""
        with self._lock:
            if model_id not in self._matrices:
                rows = conn.execute("SELECT c.chunk_rowid,e.vector FROM resource_chunk c JOIN embedding_cache e "
                                    "ON e.model_key=(SELECT model_key FROM embedding_model WHERE model_id=?) AND e.text_hash=c.text_hash WHERE c.embed=1 ORDER BY c.chunk_rowid",
                                    (model_id,)).fetchall()
                vectors = np.frombuffer(b"".join(r[1] for r in rows), dtype="<f2").reshape(len(rows), dimensions)
                rowids = np.array([r[0] for r in rows], dtype=np.int64)
                owners = self.items_of(rowids)
                keep = owners >= 0
                self._matrices[model_id] = (np.ascontiguousarray(vectors[keep]), owners[keep], rowids[keep])
            return self._matrices[model_id]

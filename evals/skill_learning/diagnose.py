"""Replay captured recommendation inputs against copied databases, without model calls.

Use a consistent app.db/orbit.db/catalog.db snapshot (including WAL checkpointing).
The compatibility counterfactual is diagnostic only; it never installs assets.
"""

from __future__ import annotations

import argparse
import copy
import sqlite3
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orbit_backend.features.hub import QueryHub
from orbit_backend.features.match import match_items
from orbit_backend.features.profile import build_profile
from orbit_backend.recommend.engine import build_slate
from orbit_backend.recommend.ranking import hygiene
from orbit_backend.recommend.ranking import slate as slate_policy
from orbit_backend.recommend.store import memory
from orbit_catalog.search import search
from orbit_catalog.store import CatalogStore

from .study import command, digest, read, save


def replay(home: Path, inputs_path: Path, output: Path, *, ablations: bool = False) -> dict:
    inputs = read(inputs_path)
    conn = sqlite3.connect(home / "app.db")
    conn.row_factory = sqlite3.Row
    created = conn.execute("SELECT max(created_at) FROM rec_run").fetchone()[0] or 0
    mem = memory(conn, created, {"ai_generate": False})
    conn.close()
    hub = QueryHub(home, home / "app.db")
    svc = SimpleNamespace(hub=hub)
    catalog_store = CatalogStore(home / "catalog.db")

    class Features:
        def __init__(self, relax=False):
            self.relax = relax

        def profile(self, scope, **kwargs):
            return build_profile(svc, scope, **kwargs)

        def match_items(self, profile, **kwargs):
            if self.relax:
                kwargs["agent"] = None
            return match_items(svc, profile, **kwargs)

    class Catalog:
        store = catalog_store

        def __init__(self, relax=False):
            self.relax = relax

        def match(self, request):
            if self.relax:
                request = request.model_copy(update={"agents": []})
            return search(self.store, request)

    try:
        profile = build_profile(svc, inputs["scope"])
        feature_matches = {str(agent): match_items(svc, profile, agent=agent, k=1000)
                           for agent in ("pi", "codex", None)}
        result = {"inputs_sha256": digest(inputs_path), "source_home": str(home),
                  "code_commit": command(["git", "rev-parse", "HEAD"]),
                  "profile": profile, "feature_filter_probe": feature_matches,
                  "feature_probe_limit": 1000, "replays": {}}
        variants = [("unchanged_selection", {}), ("agent_filter_counterfactual", {"relax_agent": True})]
        if ablations:
            variants += [("dedup_disabled", {"dedup": False}),
                         ("per_problem_3", {"per_problem": 3}),
                         ("global_top_1", {"limit": 1}), ("global_top_3", {"limit": 3}),
                         ("global_top_10", {"limit": 10}),
                         ("agent_relaxed_per_problem_3", {"relax_agent": True, "per_problem": 3})]
        select = slate_policy.select
        for name, options in variants:
            # These local counterfactuals diagnose an already exposed development snapshot.
            # They never persist policy changes or install a recommendation.
            with ExitStack() as stack:
                if "per_problem" in options:
                    stack.enter_context(patch.object(slate_policy, "PER_PROBLEM", options["per_problem"]))
                if options.get("dedup") is False:
                    stack.enter_context(patch.object(hygiene, "dedupe", lambda cards: (cards, [])))
                if "limit" in options:
                    chosen_limit = options["limit"]
                    stack.enter_context(patch.object(slate_policy, "select",
                                                     lambda cards, limit, chosen=chosen_limit: select(cards, limit=chosen)))
                relax = options.get("relax_agent", False)
                slate = build_slate(copy.deepcopy(inputs), copy.deepcopy(mem),
                                    catalog=Catalog(relax), features=Features(relax))
                slate["counterfactual_options"] = options
                result["replays"][name] = slate
        save(output, result)
        return {name: {"selected_types": dict(Counter(c["kind"] for c in slate["candidates"] if c.get("rank"))),
                       "stages": [{k: s[k] for k in ("stage", "input_count", "kept_count", "rejected_count")}
                                  for s in slate["funnel"]["stages"]]}
                for name, slate in result["replays"].items()}
    finally:
        hub.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ablations", action="store_true")
    args = parser.parse_args()
    import json
    print(json.dumps(replay(args.home, args.inputs, args.output, ablations=args.ablations), ensure_ascii=False))


if __name__ == "__main__":
    main()

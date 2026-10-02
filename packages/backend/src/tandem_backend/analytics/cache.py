"""Small per-process cache keyed by published data and the complete analysis scope."""

import json
import threading
from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict


class AnalyticsCache:
    def __init__(self, capacity=4):
        self.capacity = capacity
        self.lock = threading.Lock()
        self.values = OrderedDict()

    def read(self, store, scope, with_text=False, *, with_recommendations=False):
        from .service import analyze_store
        if not hasattr(store, "home"):
            # Legacy readers keep their public call contract and default recommendations.
            return analyze_store(store, scope, with_text)
        with store.connect() as db:
            revision = db.execute("SELECT MAX(run_id) FROM projection_run").fetchone()[0]
            inventory = db.execute("SELECT MAX(scan_id) FROM inventory_scan").fetchone()[0]
        key = (revision, inventory, json.dumps(asdict(scope), sort_keys=True), with_text, with_recommendations)
        # Serialize cache misses, so simultaneous page requests do not repeat CPU-heavy work.
        with self.lock:
            hit = key in self.values
            if not hit:
                value = analyze_store(store, scope, with_text, with_recommendations=with_recommendations)
                self.values[key] = value
                while len(self.values) > self.capacity:
                    self.values.popitem(last=False)
            self.values.move_to_end(key)
            result = deepcopy(self.values[key])
        if hit:
            from .history import recorded

            return recorded(store, "features", {"scope": asdict(scope), "with_text": with_text,
                            "with_recommendations": with_recommendations, "cache_hit": True}, lambda: result)
        return result

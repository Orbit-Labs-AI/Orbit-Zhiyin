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

    def read(self, store, scope, with_text=False):
        from .service import analyze_store
        if not hasattr(store, "home"):
            return analyze_store(store, scope, with_text)
        with store.connect() as db:
            revision = db.execute("SELECT MAX(run_id) FROM projection_run").fetchone()[0]
            inventory = db.execute("SELECT MAX(scan_id) FROM inventory_scan").fetchone()[0]
        key = (revision, inventory, json.dumps(asdict(scope), sort_keys=True), with_text)
        # Serialize cache misses, so simultaneous page requests do not repeat CPU-heavy work.
        with self.lock:
            if key not in self.values:
                value = analyze_store(store, scope, with_text, with_recommendations=False)
                self.values[key] = value
                while len(self.values) > self.capacity:
                    self.values.popitem(last=False)
            self.values.move_to_end(key)
            return deepcopy(self.values[key])

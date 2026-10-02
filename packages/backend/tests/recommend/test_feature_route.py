"""Feature route (RC-09 feature_overlap): features.profile/match_items wired into recall_all."""

import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

from test_recall_multi import READONLY, make

from tandem_backend.recommend.recall import feature_route
from tandem_backend.recommend.recall.multi import recall_all


class FakeStore:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE catalog_item (item_id TEXT, type TEXT, name TEXT, summary TEXT, url TEXT,"
                         " agents TEXT, license TEXT, difficulty INTEGER, metadata TEXT, content_hash TEXT,"
                         " latest_version TEXT, status TEXT)")
            for item_id, type_ in (("fix-perm", "skill"), ("py-style", "rule"), ("gone", "skill")):
                conn.execute("INSERT INTO catalog_item VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (item_id, type_, item_id.upper(), "s", None, json.dumps(["claude_code"]), "MIT", 2,
                              json.dumps({"risk": []}), "h-" + item_id, "v1",
                              "removed" if item_id == "gone" else "active"))

    @contextmanager
    def connect(self, readonly=False):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


class FakeFeatures:
    def __init__(self):
        self.calls = []

    def profile(self, scope=None, signals=None):
        self.calls.append(("profile", scope, signals))
        return {"tags": [{"id": "lang:python", "ns": "lang", "weight": 1.0, "sessions": 9},
                         {"id": "tool:bash", "ns": "tool", "weight": .5, "sessions": 4}],
                "vector": {"lang:python": 1.0, "friction:permission_friction": .8}, "n_sessions": 30}

    def match_items(self, profile, kinds=None, agent=None, k=50):
        self.calls.append(("match", agent, k))
        return [{"item_id": "fix-perm", "score": .7, "matched": [
                    {"id": "friction:permission_friction", "feature": "friction", "value": "permission_friction"}]},
                {"item_id": "py-style", "score": .4, "matched": [
                    {"id": "lang:python", "feature": "language", "value": "python"}]},
                {"item_id": "gone", "score": .3, "matched": []}]


def test_feature_route_ties_friction_matches_to_problems(tmp_path):
    features = FakeFeatures()
    catalog = SimpleNamespace(store=FakeStore(tmp_path / "c.db"))
    result = recall_all(make(facts=READONLY), {}, catalog=catalog, features=features)
    kind, scope, signals = features.calls[0]
    assert scope == "all" and signals[0]["id"] == "friction:permission_friction" and signals[0]["n"] == 12
    assert features.calls[1] == ("match", "claude_code", feature_route.K)
    assert result["routes"]["feature"] == 2  # removed item dropped
    by_key = {c["rec_key"]: c for c in result["candidates"]}
    perm, style = by_key["catalog:fix-perm"], by_key["catalog:py-style"]
    assert perm["problem"]["type"] == "permission_friction" and perm["match_basis"] == "catalog_feature"
    assert perm["feature_overlap"]["matched"] == ["friction:permission_friction"]
    assert style["problem"] is None and style["match_basis"] == "profile" and style["tags"] == ["python"]
    assert result["profile"]["tags"] == {"python": 1.0, "bash": .5}
    assert result["profile"]["languages"] == ["python"] and result["profile"]["evidence_sessions"]["python"] == 9


def test_features_failure_is_a_diagnostic():
    class Broken:
        def profile(self, *a, **kw):
            raise RuntimeError("FeatureService 未绑定")

    result = recall_all(make(facts=READONLY), {}, features=Broken())
    assert any(d["source"] == "feature" and d["status"] == "failed" for d in result["diagnostics"])
    assert result["candidates"]  # other routes unaffected


def test_features_shaped_inputs_profile_is_adapted():
    profile = FakeFeatures().profile()
    result = recall_all(make(facts=READONLY, profile=profile), {})
    assert result["profile"]["tags"]["python"] == 1.0
    assert not any(d["source"] == "catalog" and d["status"] == "failed" for d in result["diagnostics"])

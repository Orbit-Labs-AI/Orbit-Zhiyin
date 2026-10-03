"""Feature route (RC-09 feature_overlap): features.profile/match_items wired into recall_all."""

import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

from test_recall_multi import READONLY, make

from orbit_backend.recommend.recall import feature_route
from orbit_backend.recommend.recall.multi import recall_all


class FakeStore:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE catalog_item (item_id TEXT, type TEXT, name TEXT, summary TEXT, url TEXT,"
                         " agents TEXT, license TEXT, difficulty INTEGER, metadata TEXT, content_hash TEXT,"
                         " latest_version TEXT, status TEXT, risk TEXT, risk_level INTEGER, language TEXT)")
            for item_id, type_ in (("fix-perm", "skill"), ("py-style", "rule"), ("gone", "skill")):
                conn.execute("INSERT INTO catalog_item VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (item_id, type_, item_id.upper(), "s", None, json.dumps(["claude_code"]), "MIT", 2,
                              json.dumps({"risk": []}), "h-" + item_id, "v1",
                              "removed" if item_id == "gone" else "active", json.dumps(["runs_command"]), 3, "any"))

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
                    {"id": "lang:python", "feature": "language", "value": "python"},
                    {"id": "tool:bash", "feature": "tool_kind", "value": "bash"}]},
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
    assert perm["risk"]["level"] == "high" and "runs_command" in perm["risk"]["flags"]
    assert perm["feature_overlap"]["matched"] == ["friction:permission_friction"]
    assert style["problem"] is None and style["match_basis"] == "profile" and style["tags"] == ["bash", "python"]
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


def test_profile_only_matches_need_real_overlap():
    sessions = {"lang:python": 9, "tool:browser": 40, "fw:react": 2, "sw:wrangler": 5}
    one_generic = {"score": .03, "matched": [{"id": "tool:browser", "feature": "tool_kind", "value": "browser"}]}
    assert not feature_route.precise(one_generic, sessions)
    two_generic = {"score": .12, "matched": [{"id": "tool:browser", "feature": "tool_kind", "value": "browser"},
                                             {"id": "lang:python", "feature": "language", "value": "python"}]}
    assert feature_route.precise(two_generic, sessions)
    assert not feature_route.precise({**two_generic, "score": .03}, sessions)
    specific = {"score": .02, "matched": [{"id": "sw:wrangler", "feature": "software", "value": "wrangler"}]}
    assert feature_route.precise(specific, sessions)
    thin = {"score": .5, "matched": [{"id": "fw:react", "feature": "framework", "value": "react"}]}
    assert not feature_route.precise(thin, sessions)  # seen in too few sessions


def _cand(i, plugin, basis="profile", kind="rule"):
    return {"rec_key": f"catalog:{plugin}-{i}", "kind": kind, "dim": "rule", "basis": basis,
            "source": {"origin": "catalog",
                       "item_id": f"skill:github.com:42:plugins/{plugin}/skills/s{i}/SKILL.md"},
            "score": {"priority": 10 - i * .1, "utility": .1 - i * .001}, "tags": [f"t{i}"]}


def test_one_plugin_family_never_fills_the_slate():
    from orbit_backend.recommend.ranking import hygiene, slate

    assert hygiene.family(_cand(0, "bio")) == "github.com:42:plugins/bio"
    assert hygiene.family({"source": {"origin": "kb", "item_id": "x"}}) is None
    chosen = slate.select([_cand(i, "bio") for i in range(5)] + [_cand(9, "web")])
    families = [hygiene.family(c) for c in chosen]
    assert families.count("github.com:42:plugins/bio") == slate.FAMILY_CAP and "github.com:42:plugins/web" in families
    shelf = slate.select([_cand(i, "bio", basis="catalog_only") for i in range(3)] + [_cand(7, "web", "catalog_only")])
    assert [hygiene.family(c) for c in shelf] == ["github.com:42:plugins/bio", "github.com:42:plugins/web"]

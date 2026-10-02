from tandem_backend.recommend.relations import relations


def c(key, kind, pid="p1", ptype="tool_env_failure", **kw):
    return {"rec_key": key, "kind": kind, "problem": {"problem_id": pid, "type": ptype, "key": ptype},
            "source": {}, "links": kw.pop("links", {})} | kw


def rels(cands, **kw):
    return {(r["a"], r["b"], r["relation"]) for r in relations(cands, **kw)}


def test_duplicates():
    assert ("a", "b", "duplicates") in rels([c("a", "skill"), c("b", "skill")])
    same_item = [c("a", "skill", "p1", source={"item_id": "x"}), c("b", "plugin", "p2", source={"item_id": "x"})]
    assert ("a", "b", "duplicates") in rels(same_item)
    same_hash = [c("a", "skill", "p1", links={"content_hash": "h"}), c("b", "mcp", "p2", links={"content_hash": "h"})]
    assert ("a", "b", "duplicates") in rels(same_hash)
    assert not rels([c("a", "skill", "p1"), c("b", "hook", "p2")])


def test_candidate_id_preferred():
    out = relations([c("a", "skill", candidate_id="c1"), c("b", "skill", candidate_id="c2")])
    assert out[0]["a"] == "c1" and out[0]["b"] == "c2"


def test_conflicts():
    kb = [c("kb:a", "hook", "p1", links={"kb_id": "a", "conflicts_with": ["b"]}),
          c("kb:b", "skill", "p2", links={"kb_id": "b"})]
    assert ("kb:a", "kb:b", "conflicts") in rels(kb)
    rule_hook = relations([c("r", "rule"), c("h", "hook")])
    assert rule_hook == [{"a": "r", "b": "h", "relation": "conflicts",
                          "reason": "同一约束不要同时写进规则与 hook，保留 hook"}]
    allow = c("perm", "permission_rule", ui={"file": [['      "Bash(git push --force:*)",', "+"]]})
    assert ("perm", "inventory", "conflicts") in rels([allow], deny=["Bash(git push:*)"])
    assert not rels([allow], deny=["Bash(rm:*)"])


def test_complements():
    ladder = [c("r", "rule", ptype="missing_verification"), c("h", "hook", ptype="missing_verification")]
    assert rels(ladder) == {("r", "h", "complements")}
    assert ("r", "w", "complements") in rels([c("r", "rule"), c("w", "workflow")])
    paired = [c("kb:a", "skill", "p1", links={"kb_id": "a", "pairs_with": ["b"]}),
              c("kb:b", "mcp", "p2", links={"kb_id": "b"})]
    assert rels(paired) == {("kb:a", "kb:b", "complements")}

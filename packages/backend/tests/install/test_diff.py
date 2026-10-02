import json

from tandem_backend.install import cost, ops
from tandem_backend.install.diff import line_diff, three_way


def test_new_file_all_added_with_ai_lines():
    d = line_diff("", "a\nb\nc\n", ai_lines={2})
    assert [r["op"] for r in d["lines"]] == ["+", "ai", "+"]
    assert [r["n"] for r in d["lines"]] == [1, 2, 3]
    assert d["adds"] == 3 and d["dels"] == 0


def test_modified_lines_and_context_gaps():
    before = "\n".join(f"l{i}" for i in range(20))
    after = before.replace("l10", "L10")
    d = line_diff(before, after, context=1)
    ops_ = [r["op"] for r in d["lines"]]
    assert ops_ == [" ", " ", "-", "+", " ", " "]
    assert d["lines"][0].get("gap") and d["lines"][-1].get("gap")
    assert d["lines"][3] == {"n": 11, "op": "+", "text": "L10"}
    assert d["adds"] == 1 and d["dels"] == 1


def test_preview_diff_equals_written_bytes():
    cur = (json.dumps({"permissions": {"allow": ["a"]}, "x": 1}, indent=2) + "\n").encode()
    t = {"action": "merge_json", "pointer": "/permissions/allow", "content": ["b", "c"],
         "ai_text": ['"c"']}
    r = ops.render(t, cur)
    d = line_diff(cur.decode(), r["new"].decode(), context=None, ai_lines=set(r["ai_lines"]))
    after = [x["text"] for x in d["lines"] if x["op"] != "-"]
    before = [x["text"] for x in d["lines"] if x["op"] in (" ", "-")]
    assert after == r["new"].decode().splitlines()
    assert before == cur.decode().splitlines()
    assert any(x["op"] == "ai" for x in d["lines"])


def test_three_way_sides():
    out = three_way("a\n", "a\nours\n", "a\nmine\n")
    assert {r["side"] for r in out["lines"]} == {"ours", "current"}
    assert any(r["text"] == "mine" and r["op"] == "+" for r in out["current"])


def test_cost_estimate():
    skill_md = "---\nname: demo\ndescription: does things\nallowed: x\n---\n" + "body " * 40
    spec = {"kind": "skill"}
    targets = [
        {"idx": 0, "action": "create_file", "path": "/h/.claude/skills/demo/SKILL.md",
         "content": skill_md},
        {"idx": 1, "action": "create_file", "path": "/h/.claude/skills/demo/ref.md",
         "content": "x" * 400},
        {"idx": 2, "mappable": False},
    ]
    est = cost.estimate(spec, targets)
    assert est["basis"] == "estimate" and len(est["parts"]) == 2
    assert est["resident_tokens"] == cost.tokens("name: demo\ndescription: does things")
    assert est["trigger_tokens"] == cost.tokens("body " * 40)
    assert cost.tokens("中文") == 2 and cost.tokens("abcd") == 1
    mcp = cost.estimate({"kind": "mcp"}, [{"idx": 0, "action": "merge_json"}])
    assert mcp["resident_tokens"] == 400 and mcp["parts"][0]["note"] == "tool schema unknown"
    rule = cost.estimate({"kind": "rule"}, [{"idx": 0, "action": "md_block", "content": "abcd"}])
    assert rule["resident_tokens"] == 1
    hook = cost.estimate({"kind": "hook"}, [{"idx": 0, "action": "merge_json", "content": []}])
    assert hook["resident_tokens"] == hook["trigger_tokens"] == 0

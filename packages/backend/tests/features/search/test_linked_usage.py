from conftest import DAY, NOW

from orbit_backend.features import linked
from orbit_backend.features.linked import compute_linked, estimate_tokens

REVS = {"data": 1, "inventory": 1, "catalog": "1"}


def run(world, read_text=lambda _p: None, revs=REVS, **kw):
    linked.clear_cache()
    return {i["inv_id"]: i for i in compute_linked(
        world.connection(), revs=revs, now_ms=NOW, write=world.write, read_text=read_text,
        **kw)["items"]}


def seed(world, first_session_days=100):
    world.session("old", started=NOW - first_session_days * DAY)
    world.session("a", source="s-claude", started=NOW - 5 * DAY)
    world.session("b", source="s-codex", started=NOW - 5 * DAY)


def test_skill_and_mcp_usage_with_agent_attribution(world):
    seed(world)
    world.call("a", skill="pdf-tools", started=NOW - 5 * DAY)
    world.call("a", skill="plugin-x:pdf-tools", started=NOW - 40 * DAY, status="error")
    world.call("b", skill="pdf-tools", started=NOW - 2 * DAY)
    world.call("a", mcp="playwright", started=NOW - 1 * DAY)
    world.inventory("claude_code", [{"inv_id": "s", "type": "skill", "name": "pdf-tools"},
                                    {"inv_id": "m", "type": "mcp", "name": "Playwright"}])
    world.inventory("common", [{"inv_id": "cs", "type": "skill", "name": "pdf_tools"}])
    items = run(world)
    usage = items["s"]["usage"]
    assert (usage["calls_total"], usage["calls_30d"], usage["calls_90d"]) == (2, 1, 2)
    assert usage["error_rate"] == 0.5 and usage["last_used_at"] == NOW - 5 * DAY
    assert usage["attributable"] and usage["basis"] == "tool_call.skill"
    assert items["cs"]["usage"]["calls_total"] == 3  # common layer sums every agent
    assert items["m"]["usage"]["calls_total"] == 1 and items["m"]["status"] == "active"


def test_hook_is_unknown_usage_never_zero(world):
    seed(world)
    world.message("a", None, kind="hook.run", actor="hook")
    world.inventory("claude_code", [{"inv_id": "h", "type": "hook", "name": "PreToolUse:0"},
                                    {"inv_id": "p", "type": "plugin", "name": "kit@m"}])
    result = compute_linked(world.connection(), revs=REVS, now_ms=NOW,
                            read_text=lambda _p: None)
    items = {i["inv_id"]: i for i in result["items"]}
    assert items["h"]["status"] == "unknown_usage" and items["h"]["usage"]["calls_total"] is None
    assert items["p"]["status"] == "unknown_usage"
    assert result["summary"]["hook_runs_by_agent"] == {"claude_code": 1}
    assert result["summary"]["unknown_usage"] == 2


def test_unused_boundaries(world):
    seed(world)
    world.call("a", skill="recent", started=NOW - 80 * DAY)
    world.call("a", skill="stale", started=NOW - 95 * DAY)
    world.inventory("claude_code", [
        {"inv_id": "never", "type": "skill", "name": "never"},
        {"inv_id": "recent", "type": "skill", "name": "recent"},
        {"inv_id": "stale", "type": "skill", "name": "stale"},
        {"inv_id": "off", "type": "skill", "name": "never", "enabled": 0},
    ])
    items = run(world)
    assert items["never"]["status"] == "unused" and items["never"]["unused_days"] == 100
    assert items["recent"]["status"] == "active"
    assert items["stale"]["status"] == "unused" and items["stale"]["unused_days"] == 95
    assert items["off"]["status"] == "disabled"


def test_short_data_span_is_not_unused(world):
    seed(world, first_session_days=20)
    world.call("a", skill="other", started=NOW - 5 * DAY)
    world.inventory("claude_code", [{"inv_id": "never", "type": "skill", "name": "never"}])
    assert run(world)["never"]["status"] == "insufficient_history"


def test_unused_needs_the_full_90_day_window(world):
    """UT-09: 60 days of history cannot prove "no call in 90 days" (old rule: >= 30 days)."""
    seed(world, first_session_days=60)
    world.call("a", skill="other", started=NOW - 5 * DAY)
    world.inventory("claude_code", [{"inv_id": "never", "type": "skill", "name": "never"}])
    linked.clear_cache()
    result = compute_linked(world.connection(), revs=REVS, now_ms=NOW, write=world.write,
                            read_text=lambda _p: None)
    item = result["items"][0]
    assert item["status"] == "insufficient_history" and item["unused_days"] is None
    assert result["summary"]["insufficient_history"] == 1 and result["summary"]["unused"] == 0
    assert result["summary"]["by_type"]["skill"]["insufficient_history"] == 1


def test_result_cache_rolls_over_with_the_day(world):
    """Same revisions, 10 days later: calls_30d must move (cache key carries the day)."""
    seed(world)
    world.call("a", skill="pdf-tools", started=NOW - 25 * DAY)
    world.inventory("claude_code", [{"inv_id": "s", "type": "skill", "name": "pdf-tools"}])
    linked.clear_cache()

    def usage(now):
        return compute_linked(world.connection(), revs=REVS, now_ms=now,
                              read_text=lambda _p: None)["items"][0]["usage"]

    assert usage(NOW)["calls_30d"] == 1  # 25 days ago
    assert usage(NOW + 10 * DAY)["calls_30d"] == 0  # now 35 days ago, no clear_cache


def test_multi_agent_filter_keeps_every_agent(world):
    seed(world)
    world.inventory("claude_code", [{"inv_id": "cc", "type": "skill", "name": "a"}])
    world.inventory("codex", [{"inv_id": "cx", "type": "skill", "name": "b"}])
    world.inventory("gemini", [{"inv_id": "gm", "type": "skill", "name": "c"}])
    assert set(run(world, agent=["claude_code", "codex"])) == {"cc", "cx"}
    assert set(run(world, agent="codex")) == {"cx"}
    assert set(run(world)) == {"cc", "cx", "gm"}


def test_resident_tokens_cached_by_content_hash(world):
    seed(world)
    reads = []

    def read_text(path):
        reads.append(path)
        return "---\nname: x\ndescription: 中文说明\n---\nFirst paragraph here.\n\nSecond long body " * 1

    world.inventory("claude_code", [
        {"inv_id": "s", "type": "skill", "name": "x", "content_hash": "same"},
        {"inv_id": "r", "type": "rule", "name": "AGENTS.md", "content_hash": "rule-h"},
        {"inv_id": "m", "type": "mcp", "name": "srv"},
    ])
    items = run(world, read_text=read_text)
    assert items["s"]["resident"]["basis"] == "skill_frontmatter"
    assert items["r"]["resident"]["basis"] == "file_bytes_estimate"
    assert 0 < items["s"]["resident"]["tokens_est"] < items["r"]["resident"]["tokens_est"]
    assert items["m"]["resident"] == {"tokens_est": None, "basis": "unknown"}
    assert len(reads) == 2
    assert world.a.execute("SELECT COUNT(*) FROM inv_size").fetchone()[0] == 2
    items = run(world, read_text=read_text)
    assert len(reads) == 2 and items["s"]["resident"]["tokens_est"] > 0


def test_skill_resident_is_name_and_description_only():
    from orbit_backend.features.linked import resident_text

    header = "\n".join(f"  - pattern{i}/**" for i in range(40))
    text = (f"---\nname: pdf-tools\ndescription: >\n  Read and fill PDF forms.\n  Use for PDFs.\n"
            f"metadata:\n  pathPatterns:\n{header}\n---\n" + "Long body paragraph. " * 500)
    resident = resident_text("skill", text)
    assert resident == "pdf-tools: Read and fill PDF forms. Use for PDFs."
    assert estimate_tokens(resident) < 30
    assert resident_text("skill", "no header\n\nbody") == "no header"
    assert resident_text("rule", text) == text


def test_older_size_basis_is_remeasured(world):
    seed(world)
    world.inventory("claude_code", [{"inv_id": "s", "type": "skill", "name": "x", "content_hash": "old"}])
    world.a.execute("INSERT INTO inv_size VALUES ('old', 2681, 'file_bytes_estimate', 0)")
    world.a.commit()
    items = run(world, read_text=lambda path: "---\nname: x\ndescription: short\n---\nbody")
    assert items["s"]["resident"]["basis"] == "skill_frontmatter" and items["s"]["resident"]["tokens_est"] < 10


def test_unreadable_and_token_estimate():
    assert estimate_tokens("abcdefghi") == 3
    assert estimate_tokens("中文") == 3


def test_unreadable_basis(world):
    world.inventory("claude_code", [{"inv_id": "s", "type": "skill", "name": "x"}])
    assert run(world)["s"]["resident"] == {"tokens_est": None, "basis": "unreadable"}


def test_agent_without_skill_attribution_is_unknown_not_unused(world):
    seed(world)
    world.call("a", skill="claude-only", started=NOW - 5 * DAY)  # Claude attributes skills
    world.call("b", started=NOW - 2 * DAY)  # Codex calls never carry tool_call.skill
    world.inventory("codex", [{"inv_id": "cx", "type": "skill", "name": "codex-skill"}])
    world.inventory("claude_code", [{"inv_id": "cc", "type": "skill", "name": "never"}])
    items = run(world)
    assert items["cx"]["status"] == "unknown_usage" and items["cx"]["unused_days"] is None
    assert items["cx"]["usage"]["attributable"] is False
    assert items["cx"]["usage"]["basis"] == "usage_unavailable"
    assert items["cc"]["status"] == "unused"


def test_usage_aggregate_is_cached_in_app_db_per_data_rev(world):
    from importlib.resources import files

    world.a.executescript(files("orbit_backend.appdb").joinpath("schema/features.sql")
                          .read_text(encoding="utf-8"))
    seed(world)
    world.call("a", skill="pdf-tools", started=NOW - 5 * DAY)
    world.call("a", mcp="playwright", started=NOW - 1 * DAY, status="error")
    world.inventory("claude_code", [{"inv_id": "s", "type": "skill", "name": "pdf-tools"},
                                    {"inv_id": "m", "type": "mcp", "name": "playwright"}])
    first = run(world)
    assert world.a.execute("SELECT count(*) FROM inv_usage").fetchone()[0] == 1
    world.call("a", skill="pdf-tools", started=NOW - 2 * DAY)  # same data rev: served from app.db
    cached = run(world)
    assert cached["s"]["usage"] == first["s"]["usage"] and cached["m"]["usage"] == first["m"]["usage"]
    assert cached["m"]["usage"]["error_rate"] == 1.0
    fresh = run(world, revs={**REVS, "data": 2})
    assert fresh["s"]["usage"]["calls_total"] == 2
    assert world.a.execute("SELECT data_rev FROM inv_usage").fetchall() == [("2",)]

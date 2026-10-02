from conftest import DAY, NOW

from tandem_backend.features import linked
from tandem_backend.features.linked import compute_linked, estimate_tokens

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
    assert run(world)["never"]["status"] == "active"


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
    assert items["s"]["resident"]["basis"] == "file_bytes_estimate"
    assert 0 < items["s"]["resident"]["tokens_est"] < items["r"]["resident"]["tokens_est"]
    assert items["m"]["resident"] == {"tokens_est": None, "basis": "unknown"}
    assert len(reads) == 2
    assert world.a.execute("SELECT COUNT(*) FROM inv_size").fetchone()[0] == 2
    items = run(world, read_text=read_text)
    assert len(reads) == 2 and items["s"]["resident"]["tokens_est"] > 0


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

    world.a.executescript(files("tandem_backend.appdb").joinpath("schema/features.sql")
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

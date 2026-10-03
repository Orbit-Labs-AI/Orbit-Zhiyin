from datetime import UTC

from orbit_backend.analytics.interaction import correction_terms
from orbit_backend.uiview import moments, trajectory

from .l1_builder import *  # noqa: F403 - pytest fixtures
from .l1_builder import MIN, T0, handwritten_cc


def call(t, cmd="wrangler deploy", err=True, uid=None, status=None):
    return {"t": t, "name": "Bash", "cmd": cmd, "err": err, "tool_kind": "shell",
            "status": status or ("failed" if err else "success"), "event_uid": uid or f"c{t}"}


def test_handwritten_session_moments(l1):
    handwritten_cc(l1)
    body = trajectory.build_detail(l1.db, "cc-fix", tz=UTC)
    found = body["trajectory"]["moments"]
    rules = [m["rule"] for m in found]
    assert len(found) <= 6
    assert rules.count("failure_streak") == 1
    streak = next(m for m in found if m["rule"] == "failure_streak")
    assert streak["t"] == 7.0  # the third consecutive failure
    texts = [r[0] for r in l1.db.execute(
        "SELECT text FROM event WHERE session_uid='cc-fix' AND kind='message.user' ORDER BY seq")]
    assert rules.count("lexical_correction") == sum(bool(correction_terms(t)) for t in texts) == 2
    assert rules.count("compaction") == 1 and rules.count("goal") == 1
    assert rules.count("validation_command") == 1
    uids = {e["event_uid"] for e in body["trajectory"]["events"]} | {
        m["event_uid"] for m in body["trajectory"]["marks"]}
    assert all(m["event_uid"] in uids for m in found)
    assert [m["t"] for m in found] == sorted(m["t"] for m in found)
    assert [m["n"] for m in found] == list(range(1, len(found) + 1))
    assert all(m["alert"] == (m["rule"] in ("failure_streak", "lexical_correction"))
               for m in found)
    assert not {"偏离", "放弃"} & {m["label"][-2:] for m in found}


def test_streak_rules():
    two = [call(1), call(2)]
    assert moments.failure_streaks(two) == []
    broken = [call(1), call(2), call(3, err=False, status="success"), call(4)]
    assert moments.failure_streaks(broken) == []
    other_cmd = [call(1), call(2), call(3, cmd="npm i")]
    assert moments.failure_streaks(other_cmd) == []
    five = [call(i) for i in range(1, 6)]
    streaks = moments.failure_streaks(five)
    assert len(streaks) == 1 and streaks[0]["n"] == 5 and streaks[0]["third"]["t"] == 3
    twice = [call(1), call(2), call(3), call(4, err=False), call(5), call(6), call(7)]
    assert [s["third"]["t"] for s in moments.failure_streaks(twice)] == [3, 7]


def test_cap_keeps_priorities():
    users = [{"t": float(i), "txt": "不对，重来", "corr": True, "event_uid": f"u{i}"}
             for i in range(8)]
    calls = [call(10), call(11), call(12)]
    found = moments.detect(users, calls, [{"t": 20.0, "event_uid": "k"}])
    assert len(found) == 6
    rules = [m["rule"] for m in found]
    assert rules[0] == "goal" and "failure_streak" in rules
    assert "compaction" not in rules  # lowest priority drops first


def test_no_humans_no_goal():
    assert moments.detect([], [], []) == []
    assert moments.is_validation(call(1, cmd="pytest -q", err=False))
    assert not moments.is_validation(call(1, cmd="pytest -q", err=True))
    assert not moments.is_validation(call(1, cmd="git push", err=False))


def test_validation_moment_takes_last_passing_check(l1):
    l1.session("v", started=T0)
    l1.user("v", T0, "跑一下测试")
    l1.call("v", T0 + MIN, head="pytest -q", status="success")
    l1.call("v", T0 + 2 * MIN, head="ruff check", status="success")
    found = trajectory.build_detail(l1.db, "v", tz=UTC)["trajectory"]["moments"]
    checks = [m for m in found if m["rule"] == "validation_command"]
    assert len(checks) == 1 and checks[0]["t"] == 2.0


def test_validation_moment_uses_the_facts_command_rule():
    """One source for "is this a validation command": the key-moment rule, the facts rows and
    the persona's V axis all call ``facts.is_validation_command`` (no word-match regex)."""
    from orbit_backend.uiview import facts
    assert not hasattr(moments, "VALIDATION_RE")
    for cmd in ("pytest -q", "pnpm test", "cargo test", "make check", "tsc --noEmit",
                "cd build", "ls test/", "git diff --check", "docker build .", "check-in notes"):
        assert moments.is_validation(call(1, cmd=cmd, err=False)) \
            == facts.is_validation_command(cmd), cmd
    assert not moments.is_validation(call(1, cmd="cd build", err=False))
    assert not moments.is_validation(call(1, cmd="git diff --check", err=False))

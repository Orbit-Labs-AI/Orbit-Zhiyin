"""AN-05 detector adapters: every kind has a positive, a negative and a null (unknown) case."""

import pytest
from signal_fixtures import Session, analyze, bundle, detected, retry_session

from tandem_backend.analytics.signals.dictionary import RULES_VERSION, SIGNAL_KINDS
from tandem_backend.models import stable_id


def keys(rows):
    return None if rows is None else [(r["key"], r["value"]) for r in rows]


def chat(sid, *texts, **kw):
    s = Session(sid, **kw)
    s.user("请帮我写一个解析日志的函数")
    s.reply()
    for text in texts:
        s.user(text)
        s.reply()
    return s


# ---------------------------------------------------------------- correction


def test_correction_positive_negative_and_unavailable():
    found = detected([chat("a", "不对，我说的是用 Python 写")])["correction"]
    assert keys(found) == [("correction:session", 1)]
    sig = found[0]
    assert sig["unit"] == "message" and sig["basis"] == "proxy"
    assert sig["problem_type"] == "misunderstood_request"
    assert sig["friction_type"] == "misunderstood_request"
    assert sig["rules_version"] == RULES_VERSION
    assert sig["signal_id"] == stable_id("a", "correction", sig["event_uid"])
    assert detected([chat("b", "谢谢，继续下一步吧")])["correction"] == []
    assert detected([chat("c", "不对，我说的是用 Python 写")], events=False)["correction"] is None


@pytest.mark.parametrize("text", ["错了", "不对", "重来", "不行，重来", "不是这样的"])
def test_short_corrections_reach_the_detector(text):
    # CORRECTION_CHARS lower bound is 2: the commonest Chinese rejections are 2-5 chars.
    assert keys(detected([chat("a", text)])["correction"]) == [("correction:session", 1)]


@pytest.mark.parametrize("text", ["哪里错了？", "好", "算了一下复杂度"])
def test_short_non_corrections_stay_silent(text):
    assert detected([chat("a", text)])["correction"] == []


def test_unproduced_dimension_attr_no_longer_splits_corrections():
    # ``attrs.interaction.dimension`` had no producer (audit C14); the branch was removed, so
    # the attribute neither renames the key nor maps to repeated_instruction.
    s = Session("a")
    s.user("请写报告")
    s.reply()
    s.user("不对，改成表格形式", interaction={"dimension": "format"})
    found = detected([s])["correction"]
    assert keys(found) == [("correction:session", 1)]
    assert found[0]["problem_type"] == "misunderstood_request"


@pytest.mark.parametrize("text", ["还是不行，测试依然失败", "still failing with the same error"])
def test_result_feedback_is_not_a_correction_signal(text):
    assert detected([chat("a", text)])["correction"] == []


def test_two_short_result_feedbacks_still_form_a_frustration_streak():
    s = Session("a")
    s.user("修一下登录测试")
    s.reply()
    s.user("还是不行")
    s.reply()
    s.user("依然失败")
    assert [o["reason"] for o in detected([s])["frustration"][0]["occurrences"]] == [
        "short_correction_streak"]


def test_correction_before_any_reply_is_not_counted():
    s = Session("a")
    s.user("不对，我说的是重新写一个版本")
    assert detected([s])["correction"] == []


# ---------------------------------------------------------------- frustration (v1)


def test_frustration_positive_negative_and_unavailable():
    assert keys(detected([chat("a", "算了，怎么又错了")])["frustration"]) == [("frustration:session", 1)]
    assert detected([chat("b", "很好，继续")])["frustration"] == []
    assert detected([chat("c", "算了")], events=False)["frustration"] is None


# ---------------------------------------------------------------- retry_loop


def test_retry_loop_adapts_confirmed_same_argument_chain():
    found = detected([retry_session("a")])["retry_loop"]
    assert keys(found) == [("retry_loop:pytest", 1)]
    occ = found[0]["occurrences"][0]
    assert occ["failures"] == 3 and occ["chain"] == ["a-c0", "a-c1", "a-c2"]
    assert found[0]["call_uid"] == "a-c0" and found[0]["unit"] == "turn"
    assert found[0]["problem_type"] == "tool_env_failure"


def test_retry_loop_negatives():
    assert detected([retry_session("a", n=2)])["retry_loop"] == []
    s = Session("b")
    s.user("请修复测试")
    s.tool("pytest", digest="d1")
    s.tool("pytest", digest="d2")
    s.tool("pytest", digest="d3")
    assert detected([s])["retry_loop"] == []


def test_expected_failure_tests_do_not_produce_retry_loop():
    s = Session("a")
    s.user("这些是负例测试，预期失败，请连续运行三次确认")
    for _ in range(3):
        s.tool("pytest")
    found = detected([s])["retry_loop"]
    assert found == []


def test_retry_loop_unknown_without_identity_or_calls():
    s = Session("a")
    s.user("请修复测试")
    for _ in range(3):
        s.tool("pytest", digest=None)
    assert detected([s])["retry_loop"] is None
    plain = Session("b")
    plain.user("你好")
    assert detected([plain], tool_calls=False)["retry_loop"] is None


# ---------------------------------------------------------------- missing_verification


def edit_session(sid, *after, legacy_head=None):
    s = Session(sid)
    s.user("请修改解析器")
    s.tool(None, kind="file.edit", status="success", digest="e", scope="tool", files=["src/a.py"])
    for head, status, complete in after:
        s.tool(head, status=status, complete=complete)
    s.reply()
    return s


def test_missing_verification_positive_negative_and_unknown():
    found = detected([edit_session("a")])["missing_verification"]
    assert keys(found) == [("missing_verification:py", 1)]
    assert found[0]["problem_type"] == "missing_verification"
    assert detected([edit_session("b", ("pytest", "success", True))])["missing_verification"] == []
    no_edit = Session("c")
    no_edit.user("看看代码")
    no_edit.tool("ls", status="success")
    assert detected([no_edit])["missing_verification"] == []
    # Legacy ledgers cannot confirm executed validation: unknown, not "missing".
    assert detected([edit_session("d")], legacy=True)["missing_verification"] is None
    # An unconfirmed validation candidate after the edit is unknown, not missing.
    candidate = edit_session("e", ("pnpm test", "success", False))
    assert detected([candidate])["missing_verification"] is None


# ---------------------------------------------------------------- would_prompt


def shell_session(sid, head="ls", **meta):
    s = Session(sid, **meta)
    s.user("列出目录")
    s.tool(head, status="success")
    return s


def connector_shell(sid, command, *, approval=None, wait=None, extra_calls=()):
    """Real L3 shape: command_head is the program only; argv lives in the tool.call event input."""
    s = Session(sid)
    s.user("看看目录")
    for cmd, appr, w in ((command, approval, wait), *extra_calls):
        head = cmd.split()[0] if not cmd.startswith("git ") else " ".join(cmd.split()[:2])
        s.tool(head, status="success", approval=appr, approval_wait_ms=w)
        s.events[-2]["attrs"]["input"] = {"command": cmd}
    return s


def test_would_prompt_uses_call_approval_without_permission_mode():
    found = detected([connector_shell("a", "ls -la src", approval="approved", wait=4200)])["would_prompt"]
    assert keys(found) == [("would_prompt:readonly_shell", 1)]
    assert found[0]["basis"] == "measured" and found[0]["problem_type"] == "permission_friction"
    assert found[0]["occurrences"][0]["approval_wait_ms"] == 4200
    # An allow rule for the head already removes the prompt: no friction left to fix.
    allow = [{"inv_id": "r1", "type": "rule", "name": "settings",
              "config": {"permissions": {"allow": ["Bash(ls:*)"]}}}]
    assert detected([connector_shell("b", "ls -la", approval="approved")], inventory=allow)["would_prompt"] == []
    # Approval data exists for the session but the read-only command was not prompted.
    quiet = connector_shell("c", "ls", extra_calls=(("pnpm install", "approved", 900),))
    assert detected([quiet])["would_prompt"] == []
    # Prompted commands that are not read-only are not friction to allow-list.
    assert detected([connector_shell("d", "find . -delete", approval="approved")])["would_prompt"] == []
    # No approval data at all: unknown, not zero.
    assert detected([connector_shell("e", "ls -la")])["would_prompt"] is None


@pytest.mark.parametrize("command,readonly", [
    ("ls -la", True), ("find . -name '*.py'", True), ("git branch -a", True), ("git branch", True),
    ("git branch --list 'feat/*'", True), ("echo hi", True), ("echo hi >/dev/null", True), ("env", True),
    ("cd repo && git status", True), ("rg foo | head -5", True),
    ("find . -name x -delete", False), ("find . -exec rm {} ;", False), ("git branch -D old", False),
    ("git branch new-feature", False), ("echo x > out.txt", False), ("echo x >> log", False),
    ("env FOO=1 make", False), ("cat list | xargs rm", False), ("ls $(pwd)", False),
])
def test_readonly_command_rejects_writing_forms(command, readonly):
    from tandem_backend.analytics.signals.detectors import is_readonly_command
    assert is_readonly_command(command) is readonly


def test_permission_denied_positive_negative_and_unknown():
    s = Session("a")
    s.user("清理构建目录")
    s.tool("rm build", status="rejected", approval="declined")
    found = detected([s])["permission_denied"]
    assert keys(found) == [("permission_denied:rm", 1)]
    e = Session("b")
    e.user("推送")
    e.event("permission.decision", decision="deny", command_head="git push")
    assert keys(detected([e])["permission_denied"]) == [("permission_denied:git push", 1)]
    assert detected([shell_session("c")])["permission_denied"] == []
    legacy = shell_session("d")
    for c in legacy.calls:
        c.pop("approval")
    assert detected([legacy], legacy=True)["permission_denied"] is None


# ---------------------------------------------------------------- risky_command


@pytest.mark.parametrize("head,family", [
    ("rm -rf /", "rm_recursive_force"), ("git push --force origin main", "git_push_force"),
    ("git reset --hard HEAD~1", "git_reset_hard"), ("psql -c 'DROP TABLE users'", "sql_drop"),
])
def test_risky_command_vocabulary(head, family):
    found = detected([shell_session("a", head=head)])["risky_command"]
    assert keys(found) == [(f"risky_command:{family}", 1)]
    assert found[0]["problem_type"] == "unsafe_operation"


@pytest.mark.parametrize("command,family", [
    ("rm -rf ~", "rm_recursive_force"), ("rm -rf $HOME", "rm_recursive_force"),
    ("rm -rf ..", "rm_recursive_force"), ("rm --recursive --force /", "rm_recursive_force"),
    ("rm -r -f *", "rm_recursive_force"), ("sudo rm -Rf /usr", "rm_recursive_force"),
    ("sqlite3 x.db 'DROP TABLE tmp'", "sql_drop"), ("echo 'drop table x' | psql", "sql_drop"),
    ("sqlite3 app.db <<EOF\nDROP TABLE t;\nEOF", "sql_drop"),
    ("rm -rf node_modules", None), ("rm -rf dist build .venv", None), ("rm -rf build/*", None),
    ("rm -rf __pycache__ target .cache", None), ("rm -rf ./tmp/out", None), ("rm build.log", None),
    ("cat <<EOF > m.sql\nDROP TABLE x;\nEOF", None), ("rg 'drop table' migrations", None),
])
def test_risky_command_targets_and_clients(command, family):
    # Real connector shape: arguments only exist in the tool.call event input.
    found = detected([connector_shell("a", command)])["risky_command"]
    assert keys(found) == ([] if family is None else [(f"risky_command:{family}", 1)])


def test_risky_command_negative_and_unknown():
    assert detected([shell_session("a", head="rm build.log")])["risky_command"] == []
    plain = Session("b")
    plain.user("你好")
    assert detected([plain], tool_calls=False)["risky_command"] is None


# ---------------------------------------------------------------- interruption


def test_interruption_positive_negative_and_unknown():
    s = chat("a")
    s.interrupt()
    found = detected([s])["interruption"]
    assert keys(found) == [("interruption:turn", 1)]
    assert found[0]["problem_type"] is None and found[0]["unit"] == "turn"
    legacy = chat("b")
    legacy.event("turn.interrupted")
    assert keys(detected([legacy], turns=False)["interruption"]) == [("interruption:turn", 1)]
    assert detected([chat("c")])["interruption"] == []
    assert detected([chat("d")], turns=False, events=False)["interruption"] is None


# ---------------------------------------------------------------- layer contract


def test_every_kind_is_in_the_dictionary_and_summary_keeps_null():
    _, _, layer = analyze(bundle([chat("a")], events=False, tool_calls=False))
    summary = layer.facts["a"]["signals_summary"]
    assert set(summary) == set(SIGNAL_KINDS)
    assert summary["correction"] is None and summary["retry_loop"] is None
    _, _, layer = analyze(bundle([retry_session("b")]))
    assert layer.facts["b"]["signals_summary"]["retry_loop"] == 1
    assert layer.facts["b"]["signals_summary"]["risky_command"] == 0


def test_signal_ids_are_stable_across_recomputation():
    sessions = [retry_session("a"), chat("b", "不对，我说的是另一个文件")]
    first = analyze(bundle(sessions))[2].signals
    second = analyze(bundle(sessions))[2].signals
    assert [s["signal_id"] for s in first] == [s["signal_id"] for s in second]
    assert len({s["signal_id"] for s in first}) == len(first)


def test_threshold_table_names_a_source_for_every_value():
    from tandem_backend.analytics.common import MIN_STATUS_COVERAGE
    from tandem_backend.analytics.interaction.rules import CORRECTION_CHARS
    from tandem_backend.analytics.signals import dictionary as D

    for name, row in D.THRESHOLDS.items():
        assert row["source"] and row["where"] and isinstance(row["calibrated"], bool), name
    # The table reports the values the code actually uses.
    assert D.THRESHOLDS["correction_chars"]["value"] == CORRECTION_CHARS == (2, 200)
    assert D.THRESHOLDS["min_status_coverage"]["value"] == MIN_STATUS_COVERAGE
    assert D.THRESHOLDS["retry_loop_min_chain"]["value"] == D.RETRY_LOOP_MIN_CHAIN
    assert D.THRESHOLDS["weekly_window_weeks"]["value"] == D.WEEKLY_WINDOW_WEEKS
    assert [k for k, r in D.THRESHOLDS.items() if r["calibrated"]] == ["wilson_lo_min"]

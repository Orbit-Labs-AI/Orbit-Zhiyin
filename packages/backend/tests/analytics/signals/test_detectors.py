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
    assert keys(found) == [("correction:none", 1)]
    sig = found[0]
    assert sig["unit"] == "message" and sig["basis"] == "proxy"
    assert sig["problem_type"] == "misunderstood_request"
    assert sig["friction_type"] == "misunderstood_request"
    assert sig["rules_version"] == RULES_VERSION
    assert sig["signal_id"] == stable_id("a", "correction", sig["event_uid"])
    assert detected([chat("b", "谢谢，继续下一步吧")])["correction"] == []
    assert detected([chat("c", "不对，我说的是用 Python 写")], events=False)["correction"] is None


def test_correction_dimension_maps_to_repeated_instruction():
    s = Session("a")
    s.user("请写报告")
    s.reply()
    s.user("不对，改成表格形式", interaction={"dimension": "format"})
    found = detected([s])["correction"]
    assert keys(found) == [("correction:format", 1)]
    assert found[0]["problem_type"] == "repeated_instruction"


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


def test_would_prompt_positive_negative_and_unknown():
    found = detected([shell_session("a", permission_mode="default")])["would_prompt"]
    assert keys(found) == [("would_prompt:readonly_shell", 1)]
    assert found[0]["basis"] == "proxy"  # inventory unknown: allow rules cannot be checked
    assert found[0]["problem_type"] == "permission_friction"
    allow = [{"inv_id": "r1", "type": "rule", "name": "settings",
              "config": {"permissions": {"allow": ["Bash(ls:*)"]}}}]
    assert detected([shell_session("b", permission_mode="default")], inventory=allow)["would_prompt"] == []
    covered = detected([shell_session("b2", head="cat", permission_mode="default")], inventory=allow)
    assert covered["would_prompt"][0]["basis"] == "measured"
    assert detected([shell_session("c", permission_mode="acceptEdits")])["would_prompt"] == []
    assert detected([shell_session("d", head="pnpm", permission_mode="default")])["would_prompt"] == []
    assert detected([shell_session("e")])["would_prompt"] is None


# ---------------------------------------------------------------- permission_denied


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
    ("rm -rf build", "rm_recursive_force"), ("git push --force origin main", "git_push_force"),
    ("git reset --hard HEAD~1", "git_reset_hard"), ("psql -c 'DROP TABLE users'", "sql_drop"),
])
def test_risky_command_vocabulary(head, family):
    found = detected([shell_session("a", head=head)])["risky_command"]
    assert keys(found) == [(f"risky_command:{family}", 1)]
    assert found[0]["problem_type"] == "unsafe_operation"


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

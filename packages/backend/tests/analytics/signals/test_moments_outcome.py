"""AN-19 outcome synthesizer, AN-09 key moments and AN-02 session fact extensions."""

from signal_fixtures import Session, analyze, bundle

from tandem_backend.analytics.context import AnalysisContext
from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.signals import build_signal_layer
from tandem_backend.analytics.signals.dictionary import MAX_MOMENTS


def layer_of(*sessions, **kw):
    facets = kw.pop("facets", None)
    return analyze(bundle(list(sessions), **kw), facets=facets)[2]


def outcome(session, **kw):
    out = layer_of(session, **kw).outcomes[session.sid]
    return out["outcome"], out["basis"]


def delivered(sid, *feedback):
    s = Session(sid)
    s.user("请写一份周报")
    s.reply("周报如下……")
    for text in feedback:
        s.user(text)
    return s


def verified(sid, status):
    s = Session(sid)
    s.user("请修复解析器")
    s.tool(None, kind="file.edit", status="success", digest="e", scope="tool", files=["a.py"])
    s.tool("pytest", status=status)
    s.reply()
    return s


# ---------------------------------------------------------------- AN-19


def test_explicit_feedback_layer():
    assert outcome(delivered("a", "可以了，谢谢")) == ("completed", "explicit_feedback")
    assert outcome(delivered("b", "这个不对，需要返工")) == ("partial", "explicit_feedback")


def test_verification_layer():
    assert outcome(verified("a", "success")) == ("completed", "verify_pass")
    assert outcome(verified("b", "failed")) == ("failed", "verify_fail")


def test_explicit_feedback_outranks_verification():
    s = verified("a", "failed")
    s.user("可以了，谢谢")
    assert outcome(s) == ("completed", "explicit_feedback")


def test_correction_after_verify_pass_is_not_completed():
    s = verified("a", "success")
    s.user("不对，我说的是另一个解析器")
    assert outcome(s) == ("partial", "explicit_feedback")
    lexical = verified("b", "success")
    lexical.user("我说的是另一个解析器")  # correction proxy without feedback wording
    assert outcome(lexical)[0] != "completed"


def test_structural_layer_only_supplies_abandoned():
    s = delivered("a")
    s.user("再补充一个图表")
    s.interrupt()
    assert outcome(s) == ("abandoned", "structural")
    assert outcome(delivered("b")) == ("unknown", "unknown")


def test_facet_mapping_and_missing_events():
    assert outcome(delivered("a"), facets={"a": "mostly_achieved"}) == ("completed", "facet")
    assert outcome(delivered("b"), facets={"b": "not_achieved"}) == ("partial", "facet")
    assert outcome(delivered("c"), facets={"c": "unclear"}) == ("unknown", "unknown")
    layer = layer_of(delivered("d", "可以了，谢谢"), events=False)
    assert layer.outcomes["d"]["outcome"] == "unknown"
    assert layer.outcomes["d"]["reason"] == "events_unavailable"


def phaseless(sid, *feedback, turns=True):
    """Claude/Kimi shape: assistant messages carry no ``attrs.phase``."""
    s = Session(sid)
    s.user("请写一份周报")
    s.reply("我先看一下数据", phase=False)
    s.tool("rg report", status="success", digest="r")
    s.reply("周报如下……", phase=False)
    for text in feedback:
        s.user(text)
    if not turns:
        for e in s.events:
            e["turn_uid"] = None
    return s


def test_final_delivery_without_phase_is_last_assistant_of_turn():
    from tandem_backend.analytics.common import final_assistant_uids
    from tandem_backend.analytics.outcome_subjective.extraction import collect_deliveries

    for turns in (True, False):
        s = phaseless("a", turns=turns)
        assert final_assistant_uids(s.events) == {("a", "a-e4")}  # not the "先看一下" message
        assert [d["delivery_event_uid"] for d in collect_deliveries(s.events, {"a"})] == ["a-e4"]
    # Codex labels still win: commentary is never a delivery even when it is last.
    codex = Session("c")
    codex.user("请写一份周报")
    codex.reply("周报如下……")
    codex.reply("顺便说明一下", final=False)
    assert final_assistant_uids(codex.events) == {("c", "c-e1")}


def test_explicit_feedback_layer_without_phase():
    assert outcome(phaseless("a", "可以了，谢谢")) == ("completed", "explicit_feedback")
    assert outcome(phaseless("b", "这个不对，需要返工")) == ("partial", "explicit_feedback")
    assert outcome(phaseless("c", "可以了，谢谢", turns=False)) == ("completed", "explicit_feedback")


def test_structural_not_abandoned_when_assistant_answers_correction_without_phase():
    s = phaseless("a", "我说的是月报")  # correction proxy, no feedback wording
    assert outcome(s) == ("abandoned", "structural")  # session really ends on the correction
    s.reply("好的，月报如下……", phase=False)
    assert outcome(s) != ("abandoned", "structural")


def test_autonomy_steps_count_final_without_phase():
    s = phaseless("a")
    # one tool call + one final delivery; the intermediate message is not a step
    assert layer_of(s).facts["a"]["autonomy_steps"] == 2


# ---------------------------------------------------------------- AN-02


def test_session_fact_extensions():
    s = Session("a")
    s.user("请修复解析器")
    s.tool("rg parse", status="success", digest="r")
    s.tool(None, kind="file.edit", status="success", digest="e", scope="tool", files=["a.py"])
    s.tool("pytest", status="success")
    s.reply()
    facts = layer_of(s).facts["a"]
    assert facts["outcome"] == "completed" and facts["outcome_basis"] == "verify_pass"
    assert facts["verify_ran"] is True and facts["verify_pass"] is True
    assert facts["verify_candidate"] == 0
    assert facts["autonomy_steps"] == 4  # three tool calls + one final delivery
    assert facts["signals_summary"]["missing_verification"] == 0
    assert facts["verify_requested"] in (True, False)


def test_session_facts_keep_unknown_as_null():
    s = delivered("a")
    layer = layer_of(s, events=False, tool_calls=False)
    facts = layer.facts["a"]
    assert facts["verify_ran"] is None and facts["verify_pass"] is None
    assert facts["autonomy_steps"] is None
    assert facts["opportunities"] == {"human": None, "tools": None, "shell": None, "edits": None}
    # Without an analyze_context result there are no instruction records: unknown, not False.
    b = bundle([delivered("b")])
    context = AnalysisContext.select(b, Scope())
    assert build_signal_layer(context).facts["b"]["verify_requested"] is None


# ---------------------------------------------------------------- AN-09


def rich_session(sid="a"):
    s = Session(sid)
    s.user("请修复失败的测试")
    s.reply("先看看", final=False)
    s.user("不对，我说的是集成测试")
    for _ in range(3):
        s.tool("pytest")
    s.event("context.compaction")
    s.tool(None, kind="file.edit", status="success", digest="e", scope="tool", files=["t.py"])
    s.tool("pytest", status="success", digest="d9")
    s.reply()
    return s


def test_rule_moments_are_numbered_and_ordered():
    moments = layer_of(rich_session()).moments["a"]
    assert moments["status"] == "available"
    kinds = [m["kind"] for m in moments["moments"]]
    assert kinds == ["goal", "correction", "failure_streak", "compaction", "verify_pass", "end"]
    assert [m["index"] for m in moments["moments"]] == list(range(1, 7))
    assert all(m["origin"] == "rule" for m in moments["moments"])
    assert "集成测试" not in "".join(m["label"] for m in moments["moments"])  # no user text
    assert moments["moments"][-1]["label"] == "会话结束（结果：完成）"
    streak = moments["moments"][2]
    assert streak["signal_id"] and streak["call_uid"] == "a-c0"


def test_moments_are_deduplicated_capped_and_stable():
    s = Session("a")
    s.user("请写一个函数")
    for i in range(12):
        s.reply("改好了", final=False)
        s.user(f"不对，我说的是第 {i} 个版本")
    s.reply()
    first = layer_of(s).moments["a"]
    assert first["total_n"] == 14
    kept = first["moments"]
    assert len(kept) == MAX_MOMENTS
    assert kept[0]["kind"] == "goal" and kept[-1]["kind"] == "end"
    assert len({m["moment_id"] for m in kept}) == len(kept)
    again = layer_of(s).moments["a"]["moments"]
    assert [m["moment_id"] for m in again] == [m["moment_id"] for m in kept]


def test_moments_unavailable_without_events():
    assert layer_of(delivered("a"), events=False).moments["a"] == {
        "status": "unavailable", "moments": None, "total_n": None}

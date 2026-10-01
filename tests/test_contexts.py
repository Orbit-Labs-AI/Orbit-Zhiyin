"""Task context must constrain the profile, bottleneck, and recommended trial."""

from fastapi.testclient import TestClient

from tandem_backend.analysis import analyze
from tandem_backend.api import create_app
from tandem_backend.feedback import reader_context, signals, task_contexts
from tandem_backend.models import Event, ParsedSession, Session
from tandem_backend.narrative import explain, markdown
from tandem_backend.recommend import recommend
from tandem_backend.store import Store


def event(sid, ordinal, text, kind="user_message"):
    return Event(f"{sid}-{ordinal}", sid, ordinal, kind, "2026-01-01T00:00:00.000+00:00", text=text)


def sample_store(path):
    store = Store(path)
    conversations = {
        "math": [event("math", 1, "给大一学生讲这个定理，解释要直观。"),
                 event("math", 2, "先考虑映射的性质。", "assistant_message"),
                 event("math", 3, "没看懂，再讲直观些。")],
        "code": [event("code", 1, "代码里加简洁注释，再测试。"),
                 event("code", 2, "已加注释。", "assistant_message")],
    }
    for sid, events in conversations.items():
        store.save(ParsedSession(Session(sid, sid, sid, "/fictional/" + sid, sid), events), "1", "test")
    return store


def test_followup_inherits_task_reader_with_original_evidence_reference():
    events = [event("s", 1, "给大一学生解释这个定理，思路讲清楚。"),
              event("s", 2, "没看懂，再直观些。")]
    contexts = task_contexts(events)
    assert contexts["s-2"]["scene"] == "math_explanation"
    assert contexts["s-2"]["readers"][0]["evidence_id"] == "s-1"
    result = signals(events)
    assert result[-1].scene == "math_explanation"
    assert result[-1].readers[0]["label"] == "大一学生"


def test_new_topic_or_session_does_not_inherit_old_reader():
    events = [event("a", 1, "给大一学生解释这个定理。"),
              event("a", 2, "帮我安排明天的旅行。"),
              event("b", 1, "没看懂，再解释一下。")]
    contexts = task_contexts(events)
    assert contexts["a-2"]["scene"] == "conversation"
    assert contexts["a-2"]["readers"] == []
    assert contexts["b-1"]["scene"] == "conversation"
    assert contexts["b-1"]["readers"] == []
    assert reader_context("我不是大一学生，请解释这个定理。", "e") == []


def test_profile_keeps_comment_brevity_separate_from_math_requirements(tmp_path):
    analysis = analyze(sample_store(tmp_path / "data.sqlite"))
    contexts = {c["scene"]: c for c in analysis["contexts"]}
    math = contexts["math_explanation"]
    code = contexts["coding"]
    assert {p["dimension"] for p in math["preferences"]} == {"clarity"}
    assert {p["dimension"] for p in code["preferences"]} >= {"brevity", "verification"}
    assert math["user_messages"] == 2 and math["user_sessions"] == 1
    assert all(p["denominator"] == 1 for p in math["preferences"])
    assert math["readers"][0]["id"] == "first_year_student"


def test_recommendation_uses_same_task_context_and_cannot_relabel_scene(tmp_path):
    data = analyze(sample_store(tmp_path / "data.sqlite"))
    recs = recommend(data)
    assert [r["resource_id"] for r in recs] == ["doc-coauthoring"]
    assert recs[0]["scene"] == "math_explanation"
    assert recs[0]["readers"][0]["evidence_id"] == "math-1"
    assert "数学讲解" in recs[0]["reason"]
    assert recommend(data, scene="developer_report") == []
    absent_context = {**data, "contexts": [{**c, "preferences": []} for c in data["contexts"]]}
    assert recommend(absent_context) == []


def test_scene_filter_preserves_task_result_and_resolves_followup_before_filter(tmp_path):
    store = sample_store(tmp_path / "data.sqlite")
    math = analyze(store, scene="math_explanation")
    assert math["counts"]["sessions"] == 1
    assert math["counts"]["user_messages"] == 2
    assert math["counts"]["events"] == 3
    assert math["bottlenecks"][0]["evidence_ids"] == ["math-3", "math-2"]
    with TestClient(create_app(store.path)) as client:
        assert client.get("/v1/analysis?scene=math_explanation").json()["details"]["counts"]["events"] == 3
        assert client.get("/v1/analysis?scene=unknown").status_code == 422


def test_plain_report_mentions_reader_and_preserves_conditional_recommendation(tmp_path):
    data = analyze(sample_store(tmp_path / "data.sqlite"))
    result = explain(data, recommend(data))
    output = markdown(result)
    assert "大一学生" in output and "数学讲解" in output
    assert "不能单凭它断定上一版失败" in output
    assert "已证明有效" not in output
    assert result["findings"][0]["scene"] == "math_explanation"

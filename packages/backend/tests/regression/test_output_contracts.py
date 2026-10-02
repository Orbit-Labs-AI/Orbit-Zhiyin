import json
from pathlib import Path

from tandem_backend.analysis import analyze
from tandem_backend.content import length_contract, measure_length, visible_text
from tandem_backend.feedback import signals
from tandem_backend.models import Event, ParsedSession, Session
from tandem_backend.pipeline_eval import pipeline_benchmark
from tandem_backend.recommend import recommend
from tandem_backend.store import Store


def test_summary_budget_does_not_constrain_the_requested_full_proof():
    text = "先用简短摘要讲清楚定理，后面给完整证明，不省略条件。"
    start = text.index("简短")
    contract = length_contract(text, start, start + 2)
    assert contract["surface"] == "summary"
    assert contract["requires_full_body"] is True
    body = "摘要：定理的条件必须同时成立。\n\n## 完整证明\n" + "保留必要推导。" * 800
    measured = measure_length(body, contract)
    assert measured["chars"] < 30
    assert measured["quality"] == "summary_before_heading"


def test_first_layer_measurement_preserves_code_and_rejects_unclosed_hiding():
    plain, quality = visible_text("主要发现。\n<details><summary>细节</summary>" + "日志。" * 1000 + "</details>")
    assert plain == "主要发现。\n细节" and quality == "first_layer"
    unbalanced, quality = visible_text("主要发现。\n<details>必须展示的正文。")
    assert "必须展示的正文" in unbalanced and quality == "unbalanced_details"
    literal = "```html\n<details>这是代码里的字面值。</details>\n```"
    assert visible_text(literal)[0] == literal
    nested = "结论。<DETAILS>外部<details>内部</details></DETAILS>"
    assert visible_text(nested)[0] == "结论。"


def test_numeric_limit_has_to_describe_writing_not_a_schema_field():
    text = "报告控制在100字以内，讲清楚结果。"
    observed = signals([Event("e", "s", 1, "user_message", None, text=text)])
    requirement = next(s for s in observed if s.dimension == "brevity")
    assert requirement.output_contract["char_limit"] == 100
    text = "name字段控制在100字符以内，别改其他代码。"
    observed = signals([Event("e", "s", 1, "user_message", None, text=text)])
    assert not any(s.dimension == "brevity" for s in observed)


def test_visible_overload_respects_explicit_limit_and_records_measurement(tmp_path):
    store = Store(tmp_path / "data.sqlite")
    events = [Event("u", "s", 1, "user_message", None, text="报告控制在100字以内，说明简洁。"),
              Event("a", "s", 2, "assistant_message", None, text="这里展开每一个细节。" * 20)]
    store.save(ParsedSession(Session("s", "p", "p", "/fictional/p", "s"), events), "1", "test")
    data = analyze(store)
    finding = data["bottlenecks"][0]
    assert finding["measurement"]["threshold"] == 100
    assert finding["measurement"]["threshold_basis"] == "requested_limit"
    assert recommend(data)[0]["resource_id"] == "humanizer-zh"


def test_new_probe_has_no_feedback_path_to_history():
    path = Path(__file__).parents[2] / "src/tandem_backend/data/pipeline_probe_cases.json"
    result = pipeline_benchmark(path)
    assert result["cases"] == 12 and result["correct"] == 12
    assert result["history_updated"] is False
    payload = json.loads(path.read_text())
    assert payload["split"] == "fresh_probe_after_v0.5"


def test_scene_filter_preserves_referenced_reply_from_a_different_initial_label(tmp_path):
    store = Store(tmp_path / "data.sqlite")
    events = [Event("u1", "s", 1, "user_message", None, text="请写这份讲义。"),
              Event("a1", "s", 2, "assistant_message", None, text="讲义已保存。"),
              Event("u2", "s", 3, "user_message", None, text="数学证明没看懂，再解释一下。")]
    store.save(ParsedSession(Session("s", "p", "p", "/fictional/p", "s"), events), "1", "test")
    data = analyze(store, scene="math_explanation")
    assert data["counts"]["user_messages"] == 1
    assert data["counts"]["events"] == 1
    assert data["bottlenecks"][0]["evidence_ids"] == ["u2", "a1"]
    assert recommend(data)[0]["resource_id"] == "doc-coauthoring"


def test_visual_followup_is_not_a_writing_revision():
    observed = signals([Event("e", "s", 1, "user_message", None, text="请在图表中标出对应位置，更加直观些。")])
    assert not any(s.target == "communication" for s in observed)

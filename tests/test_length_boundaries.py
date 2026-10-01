"""Measure all explicit surfaces, including data omitted from the display prefix."""

from tandem_backend.analysis import analyze
from tandem_backend.content import measure_length, visible_text
from tandem_backend.feedback import signals
from tandem_backend.models import Event, ParsedSession, Session
from tandem_backend.pipeline_eval import _write_case
from tandem_backend.store import Store, import_codex


def test_later_numeric_clause_keeps_the_abstract_surface_and_explicit_cap(tmp_path):
    home = tmp_path / "codex"
    _write_case(home, "abstract_bound", [
        {"kind": "user", "text": "摘要要简短，控制在100字以内，正文给完整证明。"},
        {"kind": "assistant", "text": "摘要：" + "说明" * 80 + "\n\n## 完整证明\n" + "证明步骤" * 800},
    ])
    store = Store(tmp_path / "evaluation.sqlite")
    import_codex(store, home)
    findings = [b for b in analyze(store)["bottlenecks"] if b["type"] == "long_response"]
    assert len(findings) == 1
    assert findings[0]["measurement"]["surface"] == "summary"
    assert findings[0]["measurement"]["threshold"] == 100
    assert findings[0]["measurement"]["chars"] == 163


def test_separate_surfaces_keep_both_bounds_and_explicit_replacement():
    event = Event("e", "s", 1, "user_message", None,
                  text="摘要100字以内，正文200字以内。")
    signal = next(s for s in signals([event]) if s.dimension == "brevity")
    assert {c["surface"]: c["char_limit"] for c in signal.output_contracts} == {"summary": 100, "reply": 200}
    event.text = "摘要100字以内，改成200字以内。"
    signal = next(s for s in signals([event]) if s.dimension == "brevity")
    assert signal.output_contracts[0]["char_limit"] == 200


def test_full_measurement_detects_visible_suffix_after_truncated_balanced_details(tmp_path):
    text = "结论。\n<details>" + "资料" * 5500 + "</details>\n" + "正文" * 2500
    retained = text[:12000]
    lower = measure_length(retained, {"surface": "reply"}, len(text))
    assert lower["chars"] < 1500
    assert lower["complete"] is False and lower["quality"] == "truncated_lower_bound"
    home = tmp_path / "codex"
    _write_case(home, "visible_suffix", [
        {"kind": "user", "text": "回答简短些，控制在1500字以内。"},
        {"kind": "assistant", "text": text},
    ])
    store = Store(tmp_path / "evaluation.sqlite")
    import_codex(store, home)
    finding = next(b for b in analyze(store)["bottlenecks"] if b["type"] == "long_response")
    assert finding["measurement"]["chars"] == 5005
    assert finding["measurement"]["complete"] is True
    assert finding["measurement"]["source"] == "normalized_full_message"


def test_partial_measurement_abstains_when_lower_bound_does_not_exceed_limit(tmp_path):
    store = Store(tmp_path / "partial.sqlite")
    events = [Event("u", "s", 1, "user_message", None, text="回答控制在100字以内。"),
              Event("a", "s", 2, "assistant_message", None, text="短说明<details>资料</details>",
                    details={"original_chars": 15000})]
    store.save(ParsedSession(Session("s", "p", "p", "/fictional/p", "s"), events), "1", "test")
    data = analyze(store)
    assert data["bottlenecks"] == []
    assert data["data_gaps"][0]["code"] == "reply_length_incomplete"


def test_details_summary_is_visible_and_open_details_are_expanded():
    collapsed, _ = visible_text("结论<details><summary>展开阅读</summary>" + "隐藏" * 100 + "</details>")
    assert collapsed == "结论展开阅读"
    expanded, _ = visible_text("结论<details open><summary>完整证明</summary>必要推导</details>")
    assert expanded == "结论完整证明必要推导"
    malformed, quality = visible_text("</details>不能隐藏<details>")
    assert "不能隐藏" in malformed and quality == "unbalanced_details"


def test_fence_variants_keep_literal_details_visible():
    for literal in ("~~~~html\n<details>字面量</details>\n~~~~~",
                    "````html\n<details>字面量</details>\n````",
                    "```html\n<details>字面量</details>"):
        visible, _ = visible_text(literal)
        assert visible == literal

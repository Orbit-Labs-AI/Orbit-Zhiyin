"""Quoted examples in Markdown fences cannot serve as the user's own feedback."""

import pytest

from tandem_backend.analysis import analyze
from tandem_backend.content import visible_text
from tandem_backend.privacy import direct_user_text
from tandem_backend.store import Store, import_codex


@pytest.mark.parametrize("opening,closing,newline", [
    ("~~~", "~~~", "\n"),
    ("````markdown", "````", "\n"),
    ("  ~~~~~text", "  ~~~~~~", "\r\n"),
    ("```text", "", "\n"),
])
def test_variable_width_and_unclosed_fences_cannot_create_feedback(tmp_path, opening, closing, newline):
    import json

    prompt = newline.join(["请分析这个示例：", opening, "没看懂，请说人话，回答不要超过10字。", closing])
    assert direct_user_text(prompt) == "请分析这个示例："
    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    rows = [
        {"type": "session_meta", "payload": {"id": "fence", "source": "cli", "cwd": "/fictional/project"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": prompt}},
    ]
    (home / "sessions" / "fence.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    store = Store(tmp_path / "evaluation.sqlite")
    import_codex(store, home)
    assert analyze(store)["preferences"] == []


def test_shorter_fence_does_not_close_a_longer_fence_and_direct_requests_survive():
    prompt = "请解释原理。\n````\n```\n看不懂，请说人话。\n````\n回答简短些。"
    assert direct_user_text(prompt) == "请解释原理。\n回答简短些。"
    # Code displayed to a reader is still content; removing quotes from profile
    # evidence must not hide rendered code or its literal HTML from length checks.
    code = "~~~\n<details>\n正文\n</details>\n~~~"
    assert code in visible_text(code)[0]

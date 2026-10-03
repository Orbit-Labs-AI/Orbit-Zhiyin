"""A6 高频词 (word cloud): tokenizing, stop words, redaction and code filtering, aggregation."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from tandem_backend.privacy_rules import rules
from tandem_backend.uiview import a6_terms as T
from tandem_backend.uiview.a4a6_sentiment import semantic_text

UTC = ZoneInfo("UTC")
DAY = 86_400_000
CONFIG = rules.default_config()


def w(text):
    return T.words(text, CONFIG)


def test_mixed_chinese_english_words():
    out = w("帮我修复登录页面的bug，然后部署到 staging 再跑 pytest")
    assert {"修复", "登录", "页面", "部署", "bug", "staging", "pytest"} <= set(out)
    # stop words (zh + en) and single characters never appear
    assert not {"帮我", "然后", "的", "再", "到"} & set(out)
    assert w("Please Refactor THE Parser") == ["refactor", "parser"]  # English is case-folded


def test_stop_words_numbers_and_short_words():
    assert w("the and of to is it 我们 这个 一下 可以") == []
    assert w("12345 3.14 2026-10-03 100% 第 1 步") == []
    assert w("a b c x 好") == []
    assert w("ok yes thanks") == []


def test_code_urls_paths_and_identifiers_dropped():
    text = ("部署 https://example.com/a?b=1 和 www.foo.org 以及 /usr/local/bin/tool 、 ./src/app.ts 、"
            " C:\\\\Users\\\\x 还有 foo_bar fooBar FooBarBaz obj.method() --force -v a::b x=1 v0.0.1 h264")
    out = w(text)
    for bad in ("https", "example", "com", "www", "foo", "org", "usr", "local", "bin", "tool", "src", "app",
                "ts", "bar", "foobar", "foobarbaz", "obj", "method", "force", "v0", "h264", "users"):
        assert bad not in out, bad
    assert out == ["部署"]  # 和 / 以及 / 还有 are stop words


def test_inline_code_and_fences_never_counted():
    raw = "把 `useMemo` 换掉\n\n```python\nimport numpy\nprint(numpy)\n```\n> 引用的抱怨 很生气\n\n再检查样式"
    out = w(semantic_text(raw))
    assert "usememo" not in out and "numpy" not in out and "import" not in out and "print" not in out
    assert "生气" not in out  # block quote is not the speaker's own words
    assert {"换掉", "检查", "样式"} <= set(out)


def test_secrets_and_redaction_placeholders_dropped(monkeypatch):
    monkeypatch.setattr(rules, "user_names", lambda: ["alicechen"])
    text = ("token sk-abcdefghijklmnop1234 api_key=hunter2hunter2 Bearer abcdefghijklmnopqrstu "
            "ghp_abcdefghijklmnopqrstuvwxyz 0123456789abcdef0123 邮箱 alice@example.com "
            "主机 10.0.0.8 build.internal 电话 13800138000 用户 alicechen 目录 /Users/alicechen/work")
    out = w(text)
    joined = " ".join(out)
    for bad in ("sk", "abcdefghijklmnop", "hunter2", "ghp", "alice", "alicechen", "example", "internal",
                "13800138000", "email", "host", "phone", "user", "密钥", "隐藏", "work"):
        assert bad not in out and bad not in joined.split(), bad
    assert {"token", "邮箱", "主机", "电话", "用户", "目录"} <= set(out)


def test_custom_rule_placeholder_is_not_a_word():
    config = {"enabled": {**CONFIG["enabled"]}, "custom": [{"id": "c1", "pattern": "项目代号\\S+",
                                                            "replacement": "[代号]", "enabled": True}]}
    assert T.words("项目代号蓝鲸 今天上线", config) == ["今天", "上线"]


def _m(uid, sess, ts, text):
    return {"event_uid": uid, "session_uid": sess, "seq": 0, "ts": ts, "raw": text, "text": semantic_text(text)}


def test_build_terms_counts_days_share_and_order():
    sessions = {"a": {"started_at": 0}, "b": {"started_at": 0}}
    humans = [_m("1", "a", 0, "提交 代码 提交"), _m("2", "b", DAY, "提交 测试"), _m("3", "b", 2 * DAY, "测试"),
              _m("4", "a", None, "代码")]  # no ts: falls back to session start (day 0)
    body = T.build_terms(humans, sessions, UTC, config=CONFIG)
    items = body["items"]
    assert [i["term"] for i in items] == ["提交", "测试", "代码"]
    sub, test, code = items
    assert (sub["count"], sub["days"], sub["sessions"]) == (3, 2, 2)
    assert (test["count"], test["days"]) == (2, 2)
    assert (code["count"], code["days"]) == (2, 1)  # tie on count: more days first
    assert body["n_tokens"] == 7 and body["n_messages"] == 4
    assert sub["share"] == pytest.approx(3 / 7, abs=1e-4)


def test_build_terms_template_counts_once_and_limit():
    long = "请按照仓库规范整理提交信息并推送到远端分支然后通知审核人查看这一次改动的全部内容谢谢"
    assert len(long) >= T.TEMPLATE_MIN_CHARS
    humans = [_m(str(i), "a", 0, long) for i in range(5)] + [_m("x", "a", 0, "推送")]
    by = {i["term"]: i for i in T.build_terms(humans, {"a": {"started_at": 0}}, UTC, config=CONFIG)["items"]}
    assert by["推送"]["count"] == 2  # template once + the short message
    many = [_m(str(i), "a", 0, "alpha" + chr(97 + i % 26) + chr(97 + (i // 26) % 26)) for i in range(100)]
    assert len(T.build_terms(many, {"a": {"started_at": 0}}, UTC, limit=10, config=CONFIG)["items"]) == 10


def test_build_terms_empty():
    body = T.build_terms([], {}, UTC, config=CONFIG)
    assert body["items"] == [] and body["n_messages"] == 0 and body["n_tokens"] == 0
    only_noise = [_m("1", "a", 0, "```\ncode\n```"), _m("2", "a", 0, "https://x.y/z 123")]
    assert T.build_terms(only_noise, {"a": {"started_at": 0}}, UTC, config=CONFIG)["items"] == []

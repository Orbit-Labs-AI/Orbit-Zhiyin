"""a4a6-B13: synthetic labelled zh/en set for the correction and emotion lexicons.

Targets (synthetic, not EV-02 annotation): correction recall >= 0.85 and precision >= 0.9;
emotion recall >= 0.8 with no label on neutral/hypothetical text.
"""

import pytest

from tandem_backend.analytics.interaction.rules import correction_terms
from tandem_backend.analytics.lexicon import correction_hits
from tandem_backend.analytics.products.feedback import classify_emotion
from tandem_backend.uiview.sessions import is_correction

CORRECTIONS = [
    "this is still broken, try a different approach",
    "don't touch other files",
    "not what I asked",
    "still failing with the same error",
    "you broke the login page",
    "I said use pnpm, not npm",
    "revert that change please",
    "that's not right, the button should be blue",
    "same error again",
    "stop changing the config",
    "do not modify unrelated tests",
    "use another approach, this one is too slow",
    "还是报错",
    "又失败了，看一下日志",
    "换个思路，别用正则",
    "不是我要的效果",
    "别动其他文件",
    "不要再改样式了",
    "你理解错了，我要的是表格",
    "撤销刚才的修改",
    "改坏了，首页打不开",
    "怎么又是这个问题",
    "我说过不要用 any 类型",
    "这不是这个意思",
    "不对，应该先读配置",
    "还是没解决",
    "回滚你刚才的提交",
    "换一种方案试试",
    "搞错了，是另一个仓库",
    "wrong, try again",
    "我的意思是统一用 github 账号",
    "不要那么复杂，一段话就够",
    "请不要过度修复",
    "this is too verbose, shorten it",
    # short rejections (audit B1: previously below CORRECTION_CHARS and unmatched)
    "错了",
    "重来",
    "不行，重来",
    "不是这样的",
    "你错了，是另一个文件",
    "not like that",
]
NOT_CORRECTIONS = [
    "请修复登录测试",
    "add a dark mode toggle",
    "测试方法要覆盖边界情况",
    "如果还是报错就换个思路",
    "for example: don't touch other files",
    "这个函数不对称",
    "不要输出错误答案",
    "请解释 wrong 的含义",
    "please write unit tests for the parser",
    "继续",
    "看一下这个日志",
    "how do I change the theme?",
    "帮我写一个回滚脚本",
    "list the different approaches to caching",
    "我想要一个更快的版本",
    "说明一下这个模块的作用",
    "run the build",
    "把按钮改成蓝色",
    "整理一下文档结构",
    "thanks, now add the export button",
    "意思是什么？",
    "请把复杂度分析写进文档",
    "哪里错了？",
    "这次不行的话下周再说",
    "重来一遍的成本有多高？",
    "算了一下复杂度是O(n)",
    "这个功能第几次迭代了",
]

POSITIVE = ["太好了", "完美！", "Perfect, thanks!", "great job", "干得漂亮", "awesome, ship it",
            "我很满意。", "nice"]
NEGATIVE = ["烦死了，又错了", "ugh this is so frustrating", "I'm really annoyed", "无语",
            "太慢了，浪费时间", "this is ridiculous", "我很失望。", "受不了了",
            "算了，怎么又错了", "算了吧", "第三次了", "怎么又失败"]
NEUTRAL_OR_NONE = ["完美地实现这个功能并补充文档说明和测试用例", "not great", "我不太满意",
                   "如果很烦就跳过", "请翻译：太好了", "great, what about the tests?",
                   "make the output look perfect in dark mode and light mode and print",
                   "帮我写一个接口", "算了一下复杂度是O(n)", "这个功能第几次迭代了",
                   "seriously good result", "第几次调用会触发缓存？"]


def test_correction_recall_and_precision_on_labelled_set():
    tp = sum(bool(correction_terms(t)) for t in CORRECTIONS)
    fp = sum(bool(correction_terms(t)) for t in NOT_CORRECTIONS)
    recall, precision = tp / len(CORRECTIONS), tp / (tp + fp)
    missed = [t for t in CORRECTIONS if not correction_terms(t)]
    false = [t for t in NOT_CORRECTIONS if correction_terms(t)]
    assert recall >= 0.85, missed
    assert precision >= 0.9, false


@pytest.mark.parametrize("text", CORRECTIONS)
def test_uiview_prefilter_never_hides_a_lexicon_hit(text):
    assert is_correction(text) == bool(correction_terms(text))


def test_hits_carry_rule_ids():
    rules = {hit["rule"] for t in CORRECTIONS for hit in correction_hits(t)}
    assert {"repeat_failure", "change_approach", "not_what_asked", "scope_constraint",
            "rework", "overdone"} <= rules


def test_emotion_recall_without_labelling_neutral_text():
    pos = [t for t in POSITIVE if classify_emotion(t) == "positive"]
    neg = [t for t in NEGATIVE if classify_emotion(t) == "negative"]
    assert len(pos) / len(POSITIVE) >= 0.8, set(POSITIVE) - set(pos)
    assert len(neg) / len(NEGATIVE) >= 0.8, set(NEGATIVE) - set(neg)
    assert [t for t in NEUTRAL_OR_NONE if classify_emotion(t) not in (None, "neutral")] == []


def test_frustration_detector_reuses_emotion_lexicon_without_false_hits():
    from signal_fixtures import Session, detected

    def chat(sid, text):
        s = Session(sid)
        s.user("请帮我写一个解析日志的函数")
        s.reply()
        s.user(text)
        s.reply()
        return s

    for i, text in enumerate(["算了，怎么又错了", "烦死了", "第三次了，还是不行"]):
        assert detected([chat(f"p{i}", text)])["frustration"], text
    for i, text in enumerate(["算了一下复杂度是O(n)", "这个功能第几次迭代了", "seriously good result",
                              "如果很烦就跳过", "请翻译“烦死了”"]):
        assert detected([chat(f"n{i}", text)])["frustration"] == [], text

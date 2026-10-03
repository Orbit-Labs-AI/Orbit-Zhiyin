"""Regression set for the single correction definition (``pack.is_correction``).

Constructed messages in the style of real coding-agent sessions (no real user text). Each label
was assigned by reading the message as a human: True = the user pushes back on what the agent
did or understood. Labels were written before running the rule; when the rule disagrees the
sample stays and counts as an error — the gate is precision >= 0.9 (a correction rate that
over-counts is the headline friction metric) with recall reported and floored.
"""

from __future__ import annotations

import pytest

from tandem_backend.ai.pack import is_correction
from tandem_backend.ai.tasks_v1 import feedback_rule

LABELS: list[tuple[str, bool]] = [
    # --- zh corrections
    ("不对，应该改 utils.py 而不是 main.py", True),
    ("不是这样的，我要的是增量更新", True),
    ("错了，端口是 8080", True),
    ("我说的是测试环境，不是生产", True),
    ("别再改 README 了", True),
    ("不是我要的效果", True),
    ("你理解错了，我要删除的是缓存目录", True),
    ("搞错了，这个函数不该动", True),
    ("还是不行，同样的报错", True),
    ("不是让你重写整个文件", True),
    ("不对不对，回滚刚才的修改", True),
    ("不是这个文件", True),
    ("又改错地方了，不对", True),
    ("别再加注释了", True),
    ("错了，用 pnpm 不是 npm", True),
    ("不是，先跑测试再提交", True),
    ("我说的是只改样式", True),
    ("这不对，接口返回的是数组", True),
    ("你搞错了，变量名是 userId", True),
    ("还是不行，页面还是白屏", True),
    ("不对，这个 bug 在后端", True),
    ("不是这样写的，参考 src/api.ts 的写法", True),
    ("理解错了，我只是想看看日志", True),
    ("别再跑全量测试了，只跑这个文件", True),
    ("不是删掉，是注释掉", True),
    # --- en corrections
    ("No, use the existing helper instead", True),
    ("That's wrong, the timeout is in seconds", True),
    ("Wrong file. I meant config/dev.yaml", True),
    ("Not what I asked for, revert it", True),
    ("You misunderstood, I only want the CLI change", True),
    ("I said don't touch the tests", True),
    ("Nope, that breaks the build", True),
    ("Still failing with the same error", True),
    ("That's not what I meant", True),
    ("No. Keep the old API", True),
    ("Hmm, that's not right, the list should be sorted", True),
    ("Don't do that, we need the lock file", True),
    ("Still not working after your change", True),
    ("Actually no, put it in the service layer", True),
    ("You got it wrong, the flag is --dry-run", True),
    ("I meant the staging bucket", True),
    ("This is wrong. Use UTC everywhere", True),
    ("Thanks, but that's not what I wanted", True),
    ("Looks fine. No, wait, the import is still missing", True),
    ("I told you not to change the schema", True),
    ("Wrong, it should return 404", True),
    ("Incorrect, the default is false", True),
    ("Stop doing full rewrites, just patch the function", True),
    ("You broke the login page", True),
    ("I asked you to add a test, not rewrite the module", True),
    # --- zh non-corrections
    ("帮我把这个函数改成异步的", False),
    ("好的，继续", False),
    ("谢谢，完美", False),
    ("这不是一个好主意吗？你觉得呢", False),
    ("跑一下测试", False),
    ("看看这个报错是什么原因：TypeError: x is not a function", False),
    ("加一个 --verbose 参数", False),
    ("可以，提交吧", False),
    ("这个函数为什么返回的不是整数？", False),
    ("帮我查一下对应的配置", False),
    ("继续", False),
    ("把日志级别调成 debug", False),
    ("这个问题是不是和缓存有关", False),
    ("写一个脚本统计每天的提交数", False),
    ("不错，再优化一下性能", False),
    ("顺便更新一下文档", False),
    ("把这个类拆成两个文件", False),
    ("对，就是这样", False),
    ("先别急着提交，等我看一下", False),
    ("这段代码是谁写的？", False),
    ("解释一下这个正则", False),
    ("帮我在 README 里加上安装说明", False),
    ("用 TypeScript 重写这个模块", False),
    ("现在有多少个测试没通过", False),
    ("这个接口不是很稳定，加个重试吧", False),
    # --- en non-corrections
    ("What's wrong with this test?", False),
    ("Fix the wrong import in utils.py", False),
    ("Try again", False),
    ("continue", False),
    ("Thanks, looks good", False),
    ("Can you add logging to the retry loop?", False),
    ("Run the linter and fix what it reports", False),
    ("Why does this return the wrong value for negative inputs?", False),
    ("No problem, take your time", False),
    ("Please add a unit test for the parser", False),
    ("Is something wrong with the CI config?", False),
    ("LGTM, ship it", False),
    ("Refactor this into smaller functions", False),
    ("The build is failing on main, can you look?", False),
    ("Keep going", False),
    ("Explain what this migration does", False),
    ("Let's also update the changelog", False),
    ("Great, now do the same for the other endpoint", False),
    ("Find where we handle the wrong-password case", False),
    ("Is there anything wrong in my approach here?", False),
    ("Make sure no tests are skipped", False),
    ("Check if the date parsing handles wrong formats", False),
    ("Add a check that the user is not an admin", False),
    ("Write a script that reports wrong timestamps", False),
    ("Perfect, thanks!", False),
    ("Can you summarize what changed?", False),
    ("Go on", False),
    ("Bump the version to 1.2.0", False),
    ("Where is the config loaded?", False),
    ("Remove the unused imports", False),
]


def _scores():
    tp = sum(1 for t, y in LABELS if y and is_correction(t))
    fp = sum(1 for t, y in LABELS if not y and is_correction(t))
    fn = sum(1 for t, y in LABELS if y and not is_correction(t))
    return tp, fp, fn


def test_label_set_size_and_balance():
    assert len(LABELS) >= 100
    zh = sum(1 for t, _ in LABELS if any("一" <= c <= "鿿" for c in t))
    assert zh >= 40 and len(LABELS) - zh >= 40
    assert 0.35 <= sum(y for _, y in LABELS) / len(LABELS) <= 0.65


def test_correction_precision_and_recall(capsys):
    tp, fp, fn = _scores()
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    with capsys.disabled():
        print(f"\nis_correction on {len(LABELS)} labelled messages: precision={precision:.3f} recall={recall:.3f}")
    assert precision >= 0.9
    assert recall >= 0.8


@pytest.mark.parametrize("text", ["What's wrong with this test?", "Fix the wrong import in utils.py",
                                  "Is something wrong with the CI config?", "No problem, take your time"])
def test_english_mid_sentence_wrong_is_not_a_correction(text):
    assert not is_correction(text)


def test_feedback_rule_reuses_is_correction_and_does_not_blanket_misunderstood():
    for text, _ in LABELS:
        rule = feedback_rule({"signal_id": "s", "text": text})
        assert rule["is_correction"] == is_correction(text)
    misread = feedback_rule({"signal_id": "s", "text": "你理解错了，我要删除的是缓存目录"})
    assert misread["friction_type"] == "misunderstood_request"
    approach = feedback_rule({"signal_id": "s", "text": "还是不行，同样的报错"})
    assert approach["is_correction"] and approach["friction_type"] == "other"
    assert feedback_rule({"signal_id": "s", "text": "跑一下测试"})["friction_type"] == "none"

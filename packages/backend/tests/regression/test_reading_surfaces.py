"""Judge displayed text while retaining fact checks and contextual trial limits."""

from orbit_backend.evaluation import evaluate_text
from orbit_backend.recommend import trial_method


def test_link_destinations_and_collapsed_details_do_not_count_as_first_layer_overload():
    text = '已整理 8 个会话。[回看来源](https://example.test/' + 'x' * 3000 + ')\n\n'
    text += '<details>\n<summary>计算细节</summary>\n' + '计算过程。' * 600 + '\n</details>'
    result = evaluate_text(text, 'profile', ['8 个会话'])
    assert result['checks_passed']
    assert result['first_layer']['chars'] < 80
    assert result['human_acceptance'] == 'pending'


def test_visible_code_and_unbalanced_details_cannot_hide_overload_or_false_claims():
    text = '说明。\n~~~\n<details>\n' + '可见代码。' * 200 + '\n</details>\n~~~'
    assert 'detail_overload' in {i['code'] for i in evaluate_text(text, 'profile')['issues']}
    unbalanced = '已整理。<details>' + '正文。' * 400
    result = evaluate_text(unbalanced, 'profile')
    assert result['first_layer']['quality'] == 'unbalanced_details'
    assert not result['checks_passed']
    hidden_claim = '可以试用。<details><summary>细节</summary>安装一定会提升效果。</details>'
    assert 'unverified_certainty' in {i['code'] for i in evaluate_text(hidden_claim, 'recommendation')['issues']}


def test_trial_questions_use_task_readers_without_inventing_their_background():
    resource = {'id': 'doc-coauthoring', 'trial': '默认试读方法。'}
    math = trial_method(resource, {'scene': 'math_explanation', 'readers': [{'label': '大一学生'}]})
    assert '大一学生' in math and '证明思路' in math and '必要事实' in math
    report = trial_method(resource, {'scene': 'developer_report', 'readers': []})
    assert '目标读者' in report and '当前限制' in report and '大一学生' not in report
    assert trial_method(resource, {'scene': 'coding'}) == resource['trial']

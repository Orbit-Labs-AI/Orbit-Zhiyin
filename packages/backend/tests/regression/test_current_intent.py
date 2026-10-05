"""Current coordinated instructions supersede removed or rejected constraints."""

import pytest
from test_supplemental_requirements import run

from orbit_backend.models import Event
from orbit_backend.profiling.feedback import language_constraints, scene_of, signals
from orbit_backend.recommend import recommend


@pytest.mark.parametrize('request_text', [
    '不要使用英文而使用中文回答，回答不超过100字。',
    '不要使用英文而要用中文回答，回答不超过100字。',
    '别写英文版但请提供中文版，回答不超过100字。',
])
def test_positive_coordinated_language_directive_enables_chinese_resource(tmp_path, request_text):
    _, data = run(tmp_path, [('user', request_text), ('assistant', '说明' * 80)])
    assert data['bottlenecks'][0]['language'] == 'zh'
    assert {r['resource_id'] for r in recommend(data)} == {'humanizer-zh'}


def test_coordination_retains_a_new_negation_and_supports_the_reverse_language_choice():
    assert language_constraints('不要使用英文而不要使用中文。') == (None, {'en', 'zh'})
    assert language_constraints('不要使用中文而使用英文回答。') == ('en', {'zh'})


def test_body_before_delivery_link_is_available_for_review(tmp_path):
    _, data = run(tmp_path, [('user', '请写通俗易懂的项目报告。'),
                           ('assistant', '# 项目报告\n\n这是提供的报告正文，包含完成情况、已知限制和下一步要验证的问题。'),
                           ('assistant', '已保存 [报告](report.md)。')])
    assert data['data_gaps'] == []


def test_earlier_excerpt_is_not_upgraded_to_a_full_body(tmp_path):
    _, data = run(tmp_path, [('user', '请写通俗易懂的项目报告。'),
                           ('assistant', '以下节选：\n# 项目报告\n\n这里只给出一小段摘要，不是报告正文，仍需原文才能完整核对。'),
                           ('assistant', '已保存 [报告](report.md)。')])
    assert {g['code'] for g in data['data_gaps']} == {'artifact_body_missing'}


@pytest.mark.parametrize('cancellation', [
    '取消字数限制，请详细回答。', '请去掉100字上限，详细回答。', '不再限制字数，请详细回答。',
    '取消100字以内的限制，请详细回答。',
])
def test_cancelled_limit_cannot_produce_a_bottleneck_or_recommendation(tmp_path, cancellation):
    _, data = run(tmp_path, [('user', '回答不超过100字。'), ('mirror', cancellation),
                           ('assistant', '这是按新的要求展开的详细说明。' * 40)])
    assert data['bottlenecks'] == []
    assert recommend(data) == []


def test_cancelling_summary_limit_keeps_the_body_limit(tmp_path):
    _, data = run(tmp_path, [('user', '摘要不超过10字、正文不超过20字。'),
                           ('mirror', '取消摘要字数限制。'),
                           ('assistant', '甲' * 40 + '\n\n## 正文\n' + '乙' * 30)])
    assert len(data['bottlenecks']) == 1
    assert data['bottlenecks'][0]['measurement']['surface'] == 'body'
    assert data['bottlenecks'][0]['measurement']['threshold'] == 20


def test_discussing_cancellation_does_not_cancel_a_pending_limit(tmp_path):
    _, data = run(tmp_path, [('user', '回答不超过100字。'),
                           ('mirror', '请解释取消字数限制的意思。'), ('assistant', '说明' * 80)])
    assert data['bottlenecks'][0]['measurement']['threshold'] == 100


def test_negated_cancellation_preserves_the_original_limit(tmp_path):
    _, data = run(tmp_path, [('user', '回答不超过100字。'),
                           ('mirror', '不要取消字数限制。'), ('assistant', '说明' * 80)])
    assert data['bottlenecks'][0]['measurement']['threshold'] == 100


def test_educational_test_questions_do_not_supply_software_verification_evidence():
    text = '整理语文测试题，写成一份大纲。'
    observed = signals([Event('u', 's', 1, 'user_message', None, text=text)])
    assert not any(s.dimension == 'verification' for s in observed)
    assert scene_of(text) == 'document'
    assert scene_of('请运行单元测试。') == 'coding'

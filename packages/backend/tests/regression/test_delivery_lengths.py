"""Length contracts concern the requested output, not quoted source paragraphs."""

import pytest
from test_supplemental_requirements import run

from orbit_backend.models import Event
from orbit_backend.profiling.feedback import signals
from orbit_backend.recommend import recommend


@pytest.mark.parametrize("request_text", ["请分析这三段话的逻辑。", "请解释下面两段话的区别。"])
def test_source_paragraph_count_does_not_trigger_brevity_or_recommendation(tmp_path, request_text):
    _, data = run(tmp_path, [('user', request_text), ('assistant', '这是针对原文逻辑展开的必要分析。' * 300)])
    assert not any(p['dimension'] == 'brevity' for p in data['preferences'])
    assert data['bottlenecks'] == []
    assert recommend(data) == []


@pytest.mark.parametrize("request_text", ["请用三段话说明。", "回复分成两段话。", "三段话就好。"])
def test_explicit_output_paragraph_count_is_a_requirement(request_text):
    observed = signals([Event('u', 's', 1, 'user_message', None, text=request_text)])
    assert any(s.dimension == 'brevity' for s in observed)


def test_enumerated_caps_bind_to_separate_targets_and_pass_valid_body(tmp_path):
    request = '摘要不超过100字、正文不超过500字。'
    observed = signals([Event('u', 's', 1, 'user_message', None, text=request)])
    contract = next(s for s in observed if s.dimension == 'brevity')
    assert {c['surface']: c['char_limit'] for c in contract.output_contracts} == {'summary': 100, 'body': 500}
    _, data = run(tmp_path, [('user', request), ('assistant', '甲' * 80 + '\n\n## 正文\n' + '乙' * 500)])
    assert data['bottlenecks'] == [] and data['data_gaps'] == []


def test_body_overflow_does_not_use_summary_cap(tmp_path):
    _, data = run(tmp_path, [('user', '摘要不超过100字、正文不超过500字。'),
                           ('assistant', '甲' * 80 + '\n\n## 正文\n' + '乙' * 600)])
    assert len(data['bottlenecks']) == 1
    assert data['bottlenecks'][0]['measurement']['surface'] == 'body'
    assert data['bottlenecks'][0]['measurement']['chars'] == 600
    assert data['bottlenecks'][0]['measurement']['threshold'] == 500


def test_unmarked_body_remains_unknown(tmp_path):
    _, data = run(tmp_path, [('user', '摘要不超过100字、正文不超过500字。'),
                           ('assistant', '这份回复没有标出摘要与正文的分界。')])
    assert data['bottlenecks'] == []
    assert '正文分界' in data['data_gaps'][0]['message']


@pytest.mark.parametrize('first,second,expected', [(80, 80, True), (60, 40, False)])
def test_multiple_reply_fragments_share_one_cap_without_counting_synthetic_boundaries(tmp_path, first, second, expected):
    store, data = run(tmp_path, [('user', '回答不超过100字。'),
                               ('assistant', '甲' * first), ('assistant', '乙' * second)])
    assert bool(data['bottlenecks']) is expected
    if expected:
        finding = data['bottlenecks'][0]
        assert finding['measurement']['chars'] == first + second
        assert len(finding['evidence_ids']) == 3
        assert set(finding['evidence_ids']) <= {event.id for event in store.events()}
        assert recommend(data)[0]['resource_id'] == 'humanizer-zh'


def test_new_request_starts_a_new_delivery_budget(tmp_path):
    _, data = run(tmp_path, [('user', '回答不超过100字。'), ('assistant', '甲' * 80),
                           ('user', '新任务：回答不超过100字。'), ('assistant', '乙' * 80)])
    assert data['bottlenecks'] == []


def test_complete_fragment_statistics_survive_display_truncation(tmp_path):
    _, data = run(tmp_path, [('user', '回答不超过100字。'),
                           ('assistant', '甲' * 13000), ('assistant', '乙' * 80)])
    assert len(data['bottlenecks']) == 1
    assert data['bottlenecks'][0]['measurement']['chars'] == 13080
    assert data['bottlenecks'][0]['measurement']['complete'] is True


def test_body_can_start_in_a_later_delivery_fragment(tmp_path):
    _, data = run(tmp_path, [('user', '摘要不超过100字、正文不超过500字。'),
                           ('assistant', '甲' * 80), ('assistant', '## 正文\n' + '乙' * 500)])
    assert data['bottlenecks'] == [] and data['data_gaps'] == []

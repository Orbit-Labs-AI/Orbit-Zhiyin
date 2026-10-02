"""Distributive bounds apply independently, while collective wording stays scoped."""

import pytest
from test_supplemental_requirements import run

from tandem_backend.feedback import signals
from tandem_backend.models import Event


@pytest.mark.parametrize('request_text', [
    '摘要和正文各不超过10字。', '摘要与正文分别最多10字。',
    '摘要、正文均控制在10字以内。', '开头及正文各10字以内。', '摘要和正文各自不超过10字。',
])
def test_one_distributive_bound_creates_two_independent_contracts(request_text):
    observed = signals([Event('u', 's', 1, 'user_message', None, text=request_text)])
    signal = next(s for s in observed if s.dimension == 'brevity')
    assert {c['surface']: c['char_limit'] for c in signal.output_contracts} == {'summary': 10, 'body': 10}


@pytest.mark.parametrize('summary,body,surface', [('甲' * 20, '乙' * 2, 'summary'), ('甲' * 2, '乙' * 20, 'body')])
def test_a_violation_on_either_named_surface_is_detected(tmp_path, summary, body, surface):
    _, data = run(tmp_path, [('user', '摘要和正文各不超过10字。'),
                           ('assistant', summary + '\n\n## 正文\n' + body)])
    assert len(data['bottlenecks']) == 1
    assert data['bottlenecks'][0]['measurement']['surface'] == surface


def test_collective_wording_does_not_invent_two_limits():
    observed = signals([Event('u', 's', 1, 'user_message', None, text='摘要和正文合计不超过30字。')])
    contracts = next(s for s in observed if s.dimension == 'brevity').output_contracts
    assert len(contracts) == 1 and contracts[0]['surface'] == 'reply'


def test_compound_words_do_not_supply_a_negative_instruction():
    event = Event('u', 's', 1, 'user_message', None, text='请写特别通俗的说明。')
    assert {s.dimension for s in signals([event])} == {'clarity'}
    event.text = '别写通俗版说明，保留技术术语。'
    assert not any(s.dimension == 'clarity' for s in signals([event]))

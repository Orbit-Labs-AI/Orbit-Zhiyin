"""Subject changes cannot create revisions against an unrelated earlier answer."""

import pytest

from orbit_backend.analysis import analyze
from orbit_backend.feedback import task_contexts
from orbit_backend.models import Event
from orbit_backend.pipeline_eval import _write_case
from orbit_backend.store import Store, import_codex


@pytest.mark.parametrize('followup', [
    '没看懂另一个公式，请直观解释。', '没看懂另一个协议，请讲清楚。',
    '新的算子没看懂，请直观说明。', '请再解释另外一个概念，讲清楚。',
])
def test_explicit_other_subject_starts_its_own_task(tmp_path, followup):
    home = tmp_path / 'codex'
    _write_case(home, 'subjects', [
        {'kind': 'user', 'text': '给大一学生用英文解释这个定理。'},
        {'kind': 'assistant', 'text': 'An explanation of the first theorem.'},
        {'kind': 'user', 'text': followup},
    ])
    store = Store(tmp_path / 'data.sqlite')
    import_codex(store, home)
    users = [e for e in store.events() if e.kind == 'user_message']
    contexts = task_contexts(store.events())
    assert contexts[users[-1].id]['task_id'] != contexts[users[0].id]['task_id']
    assert contexts[users[-1].id]['language'] == 'zh'
    assert contexts[users[-1].id]['readers'] == []
    assert analyze(store)['bottlenecks'] == []


@pytest.mark.parametrize('followup', [
    '没看懂，请给另一个例子。', '没看懂，请再用另一个公式解释这个定理。',
    '请再给新的版本，把思路讲清楚。', '没看懂，采用新的方法再解释。',
])
def test_an_alternative_explanation_can_keep_the_same_subject(followup):
    events = [Event('initial', 's', 1, 'user_message', None, text='给大一学生解释这个定理。'),
              Event('response', 's', 2, 'assistant_message', None, text='首先说明映射的性质。'),
              Event('followup', 's', 3, 'user_message', None, text=followup)]
    contexts = task_contexts(events)
    assert contexts['followup']['task_id'] == 'initial'

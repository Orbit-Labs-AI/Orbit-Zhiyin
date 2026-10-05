"""Reference-driven, fictional comparison chains are audited before real runs."""

import pytest

from orbit_backend.evaluation.pipeline import _write_case
from orbit_backend.models import Event
from orbit_backend.profiling.analysis import analyze
from orbit_backend.profiling.trajectory import comparison_signal, response_observation
from orbit_backend.store import Store, import_codex


def audit(tmp_path, ending, original='证明先检查条件。然后构造辅助函数。最后得到结论。', revised='先检查条件，再借助辅助函数得到结论。'):
    home = tmp_path / 'codex'
    _write_case(home, 'revision_chain', [
        {'kind': 'user', 'text': '给大一学生解释这个定理，把思路讲清楚。'},
        {'kind': 'assistant', 'text': original},
        {'kind': 'user', 'text': '没看懂，换个直观的例子。'},
        {'kind': 'assistant', 'text': revised},
    ] + ([{'kind': 'user', 'text': ending}] if ending else []))
    store = Store(tmp_path / 'audit.sqlite')
    import_codex(store, home)
    data = analyze(store)
    return store, data['profile']['preference_audit']


def test_complete_chain_carries_features_and_an_observed_relative_judgment(tmp_path):
    store, result = audit(tmp_path, '这一版比上一版更清楚。')
    assert result['revision_chains'] == result['complete_response_pairs'] == result['observed_comparisons'] == 1
    pair = result['pairs'][0]
    assert pair['ready_for_annotation'] and not pair['eligible_for_training']
    assert pair['human_label'] is None and pair['necessary_facts_equivalent'] is None
    assert pair['effect_status'] == 'unmeasured'
    assert pair['original']['features']['first_layer_chars'] > pair['revised']['features']['first_layer_chars']
    assert pair['location'] == 'answer_to_user_revision'
    assert set(pair['evidence_ids']) <= {e.id for e in store.events()}


@pytest.mark.parametrize('ending', ['继续。', '很好，继续下一步。', None])
def test_continuation_and_silence_do_not_supply_a_preference_label(tmp_path, ending):
    _, result = audit(tmp_path, ending)
    assert result['observed_comparisons'] == result['ready_for_annotation'] == 0
    assert result['learned_preference'] is None and result['preference_weights'] is None


def test_another_task_cannot_become_the_pair_followup(tmp_path):
    store, result = audit(tmp_path, '新任务：这一版比上一版更清楚，请解释另一个定理。')
    pair = result['pairs'][0]
    last_user = max((e for e in store.events() if e.kind == 'user_message'), key=lambda e: e.ordinal)
    assert pair['next_input_relation'] == 'new_task'
    assert pair['followup_event_id'] is None and last_user.id not in pair['evidence_ids']
    assert result['observed_comparisons'] == 0


def test_file_delivery_notes_are_not_substituted_for_response_bodies(tmp_path):
    _, result = audit(tmp_path, '这一版比上一版更清楚。', original='已保存 [讲义](notes.md)。', revised='已更新 [讲义](notes.md)。')
    assert result['observed_comparisons'] == 1 and result['complete_response_pairs'] == 0
    assert result['ready_for_annotation'] == 0
    assert result['pairs'][0]['original']['features'] is None


def test_truncation_and_unbalanced_display_keep_features_unknown():
    event = Event('e', 's', 1, 'assistant_message', None, text='短片段', details={'original_chars': 20_000})
    assert response_observation([event])['features'] is None
    event.details = {}
    event.text = '<details>可见边界不完整'
    assert response_observation([event])['features'] is None
    assert response_observation([])['features'] is None


@pytest.mark.parametrize('text', [
    '这一版没有比上一版更清楚。', '这一版比上一版更清楚吗？',
    '请写“这一版比上一版更清楚”这句话。', '请解释这一版比上一版更清楚的含义。',
])
def test_negated_quoted_questioned_and_requested_comparisons_are_not_approval(text):
    assert comparison_signal(Event('u', 's', 1, 'user_message', None, text=text)) is None


def test_a_relative_judgment_can_prefer_the_original_response(tmp_path):
    _, result = audit(tmp_path, '上一版比这一版更清楚。')
    assert result['pairs'][0]['observed_comparison'] == 'original_preferred'


@pytest.mark.parametrize('answer', ['生活例子。', '继续用生活例子。', 'callback'])
def test_clarification_exchange_is_not_a_completed_rewrite(tmp_path, answer):
    if answer == 'callback':
        from test_question_replies import callback
        answer = callback('生活例子。', '想看生活例子还是图示？')
    home = tmp_path / 'codex'
    _write_case(home, 'clarification_chain', [
        {'kind': 'user', 'text': '请给初学者解释程序，把思路讲清楚。'},
        {'kind': 'assistant', 'text': '程序按变换规则处理输入。'},
        {'kind': 'user', 'text': '没看懂，换个例子。'},
        {'kind': 'assistant', 'text': '想看生活例子还是图示？'},
        {'kind': 'user', 'text': answer},
        {'kind': 'assistant', 'text': '程序收到3个苹果，逐个装盒；每装一个，剩余数量减一，到零停止。'},
        {'kind': 'user', 'text': '这一版比上一版更清楚。'},
    ])
    store = Store(tmp_path / 'data.sqlite')
    import_codex(store, home)
    events = {e.id: e for e in store.events()}
    pair = analyze(store)['profile']['preference_audit']['pairs'][0]
    assert pair['observed_comparison'] == 'revised_preferred'
    assert len(pair['clarification_event_ids']) == 2
    assert all(eid in events for eid in pair['clarification_event_ids'])
    assert '3个苹果' in events[pair['revised']['evidence_ids'][0]].text
    assert len(pair['revised']['evidence_ids']) == 1


def test_unanswered_clarification_is_not_a_complete_response_pair(tmp_path):
    _, result = audit(tmp_path, None, revised='你想看生活例子还是图示？')
    assert result['complete_response_pairs'] == 0
    assert result['pairs'][0]['revised']['content_status'] == 'clarification_pending'


def test_new_subject_after_clarification_is_not_absorbed_into_the_old_task(tmp_path):
    _, result = audit(tmp_path, '新任务：请解释另一个定理。', revised='你想看生活例子还是图示？')
    pair = result['pairs'][0]
    assert pair['next_input_relation'] == 'new_task'
    assert pair['observed_comparison'] is None and not pair['clarification_event_ids']

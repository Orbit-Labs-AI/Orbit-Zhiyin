"""A condition, clarification, and subject cannot supply the wrong evidence."""

import pytest
from test_question_replies import callback

from orbit_backend.analysis import analyze
from orbit_backend.feedback import reader_context
from orbit_backend.models import Event
from orbit_backend.pipeline_eval import _write_case
from orbit_backend.store import Store, import_codex
from orbit_backend.trajectory import comparison_signal


@pytest.mark.parametrize('text', ['如果这一版比上一版更清楚，就采用它。', '假如这一版比上一版更清楚，就继续。',
                                 '若新版比上一版更清楚，才接受。', '希望这一版比上一版更清楚。'])
def test_conditional_or_aspirational_comparison_is_not_a_judgment(text):
    assert comparison_signal(Event('u', 's', 1, 'user_message', None, text=text)) is None


def test_a_clarification_answer_can_supply_requirements_without_creating_another_revision(tmp_path):
    home = tmp_path / 'codex'
    _write_case(home, 'clarification_requirements', [
        {'kind': 'user', 'text': '请给初学者解释这个证明，把思路讲清楚。'},
        {'kind': 'assistant', 'text': '证明依据假设推出结论。'},
        {'kind': 'user', 'text': '没看懂，换个例子。'},
        {'kind': 'assistant', 'text': '想看生活例子还是图示？'},
        {'kind': 'user', 'text': callback('更直观的生活例子。')},
        {'kind': 'assistant', 'text': '从三个苹果开始，逐个装盒，到零时停止。'},
        {'kind': 'user', 'text': '这一版比上一版更清楚。'},
    ])
    store = Store(tmp_path / 'data.sqlite')
    import_codex(store, home)
    data = analyze(store)
    assert len(data['bottlenecks']) == 1
    assert data['profile']['preference_audit']['revision_chains'] == 1
    assert data['profile']['preference_audit']['observed_comparisons'] == 1
    assert next(p for p in data['profile']['observations'] if p['dimension'] == 'clarity')['messages'] == 3


@pytest.mark.parametrize('text,expected', [
    ('请面向普通读者分析初学者的常见问题。', {'general_reader'}),
    ('请面向初学者介绍普通读者的阅读习惯。', {'beginner'}),
    ('请面向普通读者分析开发者的协作方式。', {'general_reader'}),
    ('请给初学者和普通读者写通俗教程。', {'beginner', 'general_reader'}),
    ('请介绍初学者和开发者的常见问题。', set()),
    ('请写开发者易读的报告。', {'developer'}),
])
def test_reader_cue_governs_an_audience_without_borrowing_a_subject(text, expected):
    assert {r['id'] for r in reader_context(text, 'u')} == expected


@pytest.mark.parametrize('text,direction', [
    ('我希望采用这一版因为这一版比上一版更清楚。', 'revised_preferred'),
    ('我期望保留旧版因为上一版比这一版更清楚。', 'original_preferred'),
    ('我希望这一版比上一版更清楚，因为修改很多。', None),
])
def test_aspiration_is_scoped_to_its_predicate(text, direction):
    assert comparison_signal(Event('u', 's', 1, 'user_message', None, text=text)) == direction


def test_a_long_reader_list_preserves_the_single_governing_cue():
    readers = reader_context('请面向大学一年级、零基础的人、项目开发者以及不了解背景的读者写教程。', 'u')
    assert {r['id'] for r in readers} == {'first_year_student', 'beginner', 'developer', 'general_reader'}
    assert {r['evidence_id'] for r in readers} == {'u'}

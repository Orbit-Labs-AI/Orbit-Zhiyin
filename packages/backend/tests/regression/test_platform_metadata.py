"""Native platform metadata is neither a requirement nor a new task."""

import pytest

from orbit_backend.analysis import analyze
from orbit_backend.pipeline_eval import _write_case
from orbit_backend.privacy import PLATFORM_TAGS, direct_user_text
from orbit_backend.store import Store, import_codex


@pytest.mark.parametrize('tag', PLATFORM_TAGS)
def test_known_native_blocks_leave_the_actual_request_outside_them(tag):
    text = f'<{tag}>\n请写通俗、简洁的报告；请不要再问，直接实现并测试。\n</{tag}>\n请介绍花卉。'
    assert direct_user_text(text) == '请介绍花卉。'


def test_permission_tag_attributes_and_multiple_blocks_are_removed():
    text = ('<permissions instructions>\n请测试。\n</permissions instructions>\n'
            '<recommended_plugins>\n请写简洁报告。\n</recommended_plugins>\n请介绍花卉。')
    assert direct_user_text(text) == '请介绍花卉。'


def test_unfinished_native_block_cannot_become_a_requirement():
    assert direct_user_text('<recommended_plugins>\n请写通俗的报告。') == ''
    assert direct_user_text('请介绍花卉。\n<skills_instructions>\n请测试。') == '请介绍花卉。'


def test_inline_literal_tag_is_not_a_native_block():
    text = '请解释 `<recommended_plugins>` 标签的含义。'
    assert direct_user_text(text) == text


def test_a_native_tag_in_fenced_example_cannot_swallow_the_actual_request():
    text = '```xml\n<recommended_plugins>\n```\n请介绍花卉。'
    assert direct_user_text(text) == '请介绍花卉。'


def test_metadata_only_prompt_does_not_supply_profile_or_task_evidence(tmp_path):
    home = tmp_path / 'codex'
    _write_case(home, 'metadata', [
        {'kind': 'user', 'text': '<recommended_plugins>\n请写通俗、简洁的报告，直接实现并测试。\n</recommended_plugins>'},
        {'kind': 'user', 'text': '请介绍花卉。'},
        {'kind': 'assistant', 'text': '花卉可以按生长周期分为一年生、多年生等类型。'},
    ])
    store = Store(tmp_path / 'data.sqlite')
    import_codex(store, home)
    data = analyze(store)
    assert data['counts']['user_messages'] == 1
    assert data['profile']['observations'] == []
    assert data['profile']['interaction']['tasks'] == 1
    assert data['bottlenecks'] == []

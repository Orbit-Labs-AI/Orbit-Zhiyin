"""Display semantics for untitled sessions and structured context records."""

from tandem_backend.presentation import event_display, session_display


def test_native_title_and_fallback_provenance_remain_distinct():
    base = {'session_uid': 'session_1234567890', 'native_id': 'native-123', 'agent': 'codex', 'kind': 'main', 'title': None}
    prompt = session_display({**base, 'first_prompt': '修复登录错误\n并保留现有设置'})
    assert prompt['title'] is None
    assert prompt['display_title'] == '修复登录错误 并保留现有设置'
    assert prompt['display_title_source'] == 'first_message'
    native = session_display({**base, 'title': '自定义名字', 'first_prompt': '其他文字'})
    assert native['display_title'] == '自定义名字'
    assert native['display_title_source'] == 'native_title'
    workflow = session_display({**base, 'kind': 'workflow_agent', 'workflow_label': '整理导入逻辑'})
    assert workflow['display_title'] == '整理导入逻辑'
    assert workflow['display_title_source'] == 'workflow_label'
    identity = session_display(base)
    assert identity['display_title'] == 'Codex · 会话 · native-123'
    assert identity['display_title_source'] == 'identity'


def test_structured_context_is_explained_without_inventing_text():
    display = event_display({'kind': 'context.inject', 'attrs': {}, 'text': None,
        'ext': {'attachment': {'type': 'total_tokens_reminder', 'totalTokens': 100}}})
    assert display['title'] == '用量提醒'
    assert display['body'] is None
    assert '没有独立的文本正文' in display['summary']
    assert display['fields']['totalTokens'] == 100


def test_published_attachment_text_and_environment_fields_are_visible():
    display = event_display({'kind': 'context.inject', 'attrs': {}, 'text': None,
        'ext': {'attachment': {'type': 'file', 'filename': '/fictional/README.md',
                              'content': {'file': {'content': '已脱敏的文件预览'}}}}})
    assert display['body'] == '已脱敏的文件预览'
    assert display['fields']['filename'] == '/fictional/README.md'
    environment = event_display({'kind': 'context.inject', 'attrs': {},
        'ext': {'attachment': {'type': 'environment', 'snapshot': {'workingDirectory': '/fictional/project', 'shell': 'zsh'}}}})
    assert environment['title'] == '环境信息'
    assert environment['fields']['workingDirectory'] == '/fictional/project'


def test_stream_provenance_is_not_presented_as_an_empty_chat_message():
    display = event_display({'kind': 'context.inject', 'attrs': {'context_type': 'stream_provenance'}})
    assert display['title'] == '流式记录索引'
    assert display['category'] == 'context'
    assert display['body'] is None
    assert '原始证据' in display['summary']

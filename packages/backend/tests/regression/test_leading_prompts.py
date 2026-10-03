"""Requests may precede their marker; model filtering must keep their evidence."""

import json

import pytest

from orbit_backend.analysis import analyze
from orbit_backend.store import Store, import_codex


def message(role, text):
    return {'type': 'response_item', 'payload': {'type': 'message', 'role': role,
            'channel': 'final' if role == 'assistant' else None, 'content': text}}


def write_home(tmp_path, rows):
    home = tmp_path / 'codex'
    (home / 'sessions').mkdir(parents=True)
    first = {'type': 'session_meta', 'payload': {'id': 'leading', 'cwd': '/fictional/project', 'source': 'cli'}}
    (home / 'sessions' / 'leading.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in [first] + rows))
    return home


@pytest.mark.parametrize('with_start,with_id', [(True, True), (False, True), (False, False)])
def test_request_before_context_is_included_in_model_filtered_profile(tmp_path, with_start, with_id):
    rows = [message('user', '请写通俗易懂的文档。')]
    if with_start:
        rows.append({'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 't'}})
    context = {'model': 'new-model', **({'turn_id': 't'} if with_id else {})}
    rows += [{'type': 'turn_context', 'payload': context}, message('assistant', '文档说明操作的目的与步骤。')]
    store = Store(tmp_path / 'data.sqlite')
    import_codex(store, write_home(tmp_path, rows))
    data = analyze(store, model='new-model')
    assert data['counts']['user_messages'] == 1
    assert data['profile']['observations'][0]['dimension'] == 'clarity'


def test_a_new_leading_prompt_does_not_keep_the_previous_turn_model(tmp_path):
    rows = [
        {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'old'}},
        {'type': 'turn_context', 'payload': {'turn_id': 'old', 'model': 'old-model'}},
        message('user', '写英文教程。'), message('assistant', 'The original tutorial.'),
        message('user', '新任务：请写通俗易懂的中文文档。'),
        {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'new'}},
        {'type': 'turn_context', 'payload': {'turn_id': 'new', 'model': 'new-model'}},
        {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': '新任务：请写通俗易懂的中文文档。'}},
        message('assistant', '文档说明目的与步骤。'),
    ]
    store = Store(tmp_path / 'data.sqlite')
    import_codex(store, write_home(tmp_path, rows))
    users = [e for e in store.events() if e.kind == 'user_message']
    assert [(e.turn_id, e.model) for e in users] == [('old', 'old-model'), ('new', 'new-model')]
    assert analyze(store, model='new-model')['counts']['user_messages'] == 1
    assert analyze(store, model='old-model')['counts']['user_messages'] == 1


def test_a_replied_request_is_not_rebound_by_a_later_context(tmp_path):
    rows = [message('user', '请解释旧任务。'), message('assistant', '旧任务的答复。'),
            {'type': 'turn_context', 'payload': {'turn_id': 'later', 'model': 'later-model'}}]
    store = Store(tmp_path / 'data.sqlite')
    import_codex(store, write_home(tmp_path, rows))
    assert analyze(store, model='later-model')['counts']['user_messages'] == 0


def test_snapshot_does_not_borrow_model_from_a_future_context(tmp_path):
    rows = [message('user', '请写通俗文档。'),
            {'type': 'turn_context', 'payload': {'turn_id': 'future', 'model': 'future-model'}}]
    home = write_home(tmp_path, rows)
    source = home / 'sessions' / 'leading.jsonl'
    envelopes = [json.loads(line) for line in source.read_text().splitlines()]
    for index, row in enumerate(envelopes):
        row['timestamp'] = f'2026-01-01T00:00:0{index}Z'
    source.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in envelopes))
    store = Store(tmp_path / 'data.sqlite')
    import_codex(store, home, before='2026-01-01T00:00:01Z')
    assert analyze(store, model='future-model')['counts']['user_messages'] == 0
    assert next(e for e in store.events() if e.kind == 'user_message').model == 'unknown'

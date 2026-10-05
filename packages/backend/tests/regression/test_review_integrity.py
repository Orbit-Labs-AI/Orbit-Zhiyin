"""Public-format and synthetic evidence boundaries, independent of local history."""

import io
import json
import re

import pytest
from test_leading_prompts import message, write_home
from test_supplemental_requirements import run

from orbit_backend.cli import demo_home, main
from orbit_backend.legacy import codex
from orbit_backend.privacy import direct_user_text
from orbit_backend.profiling.analysis import analyze
from orbit_backend.profiling.bottlenecks import unexplained_terms
from orbit_backend.recommend import recommend
from orbit_backend.reporting.analysis_reports import (
    bottlenecks_markdown,
    process_markdown,
    profile_markdown,
)
from orbit_backend.reporting.narrative import explain, markdown
from orbit_backend.store import Store, import_codex


@pytest.mark.parametrize('narrowing', [{'exclude_sessions': {'demo-0'}}, {'before': '2025-12-31T00:00:00Z'}])
def test_explicit_policy_reset_cannot_preserve_excluded_rows_on_interruption(tmp_path, monkeypatch, narrowing):
    home = demo_home(tmp_path / 'codex')
    store = Store(tmp_path / 'data.sqlite')
    import_codex(store, home)

    def unavailable(*args, **kwargs):
        raise OSError('unavailable')

    monkeypatch.setattr('orbit_backend.legacy.store.parse_rollout', unavailable)
    with pytest.raises(OSError):
        import_codex(store, home, reset_sample_policy=True, **narrowing)
    assert store.counts()['sessions'] == 0


def test_oversized_record_is_drained_in_bounded_chunks_and_keeps_physical_line_numbers(monkeypatch):
    monkeypatch.setattr(codex, 'MAX_LINE', 8)

    class CheckedStream(io.BytesIO):
        def readline(self, size=-1):
            assert size == 9  # No unbounded read can allocate the rejected record.
            return super().readline(size)

    stream = CheckedStream(b'good\n' + b'x' * 100 + b'\nnext\nlast')
    assert list(codex.bounded_lines(stream)) == [(1, b'good\n'), (2, None), (3, b'next\n'), (4, b'last')]


def test_oversized_record_does_not_hide_a_later_valid_request(tmp_path, monkeypatch):
    monkeypatch.setattr(codex, 'MAX_LINE', 256)
    home = write_home(tmp_path, [message('user', 'x' * 700), message('user', '请介绍花卉。')])
    parsed = codex.parse_rollout(home / 'sessions' / 'leading.jsonl')
    assert [e.text for e in parsed.events] == ['请介绍花卉。']
    assert parsed.events[0].ordinal == 3
    assert parsed.warnings == [{'line': 2, 'code': 'oversized_line'}]


@pytest.mark.parametrize('future_context', [False, True])
def test_uncontextualized_new_turn_does_not_inherit_the_previous_model(tmp_path, future_context):
    rows = [
        {'type': 'event_msg', 'timestamp': '2026-01-01T00:00:01Z', 'payload': {'type': 'task_started', 'turn_id': 'old'}},
        {'type': 'turn_context', 'timestamp': '2026-01-01T00:00:02Z', 'payload': {'turn_id': 'old', 'model': 'old-model'}},
        {**message('user', '旧请求。'), 'timestamp': '2026-01-01T00:00:03Z'},
        {**message('assistant', '旧答复。'), 'timestamp': '2026-01-01T00:00:04Z'},
        {**message('user', '请写通俗的文档。'), 'timestamp': '2026-01-01T00:00:05Z'},
        {'type': 'event_msg', 'timestamp': '2026-01-01T00:00:06Z', 'payload': {'type': 'task_started', 'turn_id': 'new'}},
    ]
    if future_context:
        rows += [{'type': 'turn_context', 'timestamp': '2026-01-01T00:00:09Z', 'payload': {'turn_id': 'new', 'model': 'future-model'}}]
    home = write_home(tmp_path, rows)
    path = home / 'sessions' / 'leading.jsonl'
    path.write_text(path.read_text().replace('"type": "session_meta",', '"timestamp": "2026-01-01T00:00:00Z", "type": "session_meta",'))
    store = Store(tmp_path / 'data.sqlite')
    import_codex(store, home, before='2026-01-01T00:00:06Z')
    users = [e for e in store.events() if e.kind == 'user_message']
    assert [(e.turn_id, e.model) for e in users] == [('old', 'old-model'), ('new', 'unknown')]


@pytest.mark.parametrize('text', ['请解释 <INSTRUCTIONS> 标签是什么意思。', '请解释 `<INSTRUCTIONS>` 标签是什么意思。'])
def test_literal_instruction_tag_is_a_user_request(text):
    assert direct_user_text(text) == text


def test_defined_repeated_terms_are_not_counted_as_distinct_unexplained_concepts(tmp_path):
    text = 'KL 表示两种概率分布之间的差异。之后讨论 KL、KL 和 KL。'
    assert unexplained_terms(text) == []
    assert unexplained_terms('KL，KL，KL，KL。') == ['KL']
    _, data = run(tmp_path, [('user', '请用通俗的语言解释。'), ('assistant', text)])
    assert data['bottlenecks'] == [] and recommend(data) == []


def test_repair_evidence_exposes_same_argument_digests_without_retaining_arguments(tmp_path):
    home = demo_home(tmp_path / 'codex')
    store = Store(tmp_path / 'data.sqlite')
    import_codex(store, home)
    finding = next(f for f in analyze(store)['bottlenecks'] if f['type'] == 'repeated_tool_failure')
    by_id = {e.id: e for e in store.events()}
    calls = [by_id[eid] for eid in finding['evidence_ids'] if by_id[eid].kind == 'tool_call']
    assert len(calls) == 3 and len({e.details['argument_digest'] for e in calls}) == 1
    assert all('arguments' not in e.details and not e.text for e in calls)


def test_a_missing_artifact_body_is_visible_without_inventing_a_bottleneck(tmp_path):
    _, data = run(tmp_path, [('user', '请写通俗的文档。'), ('assistant', '已保存 [文档](/fictional/doc.md)。')])
    assert data['bottlenecks'] == [] and recommend(data) == []
    assert data['bottleneck_details'][0]['type'] == 'data_gap'
    assert len(data['bottleneck_details'][0]['sequence']) == 2
    assert '材料缺口' in bottlenecks_markdown(data) and '未识别到完整正文' in bottlenecks_markdown(data)


def test_reports_support_relative_routes_and_a_custom_server_without_fixed_port(tmp_path):
    store, data = run(tmp_path, [('user', '请写通俗的文档。'), ('assistant', '原说明。'), ('user', '没看懂，请给个例子。')])
    result = explain(data, recommend(data))
    for render, value in [(profile_markdown, data), (bottlenecks_markdown, data), (process_markdown, data), (markdown, result)]:
        assert '8765' not in render(value)
        assert '/v1/evidence/' in render(value)
        assert 'http://127.0.0.1:8766/v1/evidence/' in render(value, 'http://127.0.0.1:8766/v1/evidence')


def test_cli_evidence_snapshots_are_offline_and_reruns_remove_only_owned_stale_files(tmp_path, capsys):
    target = tmp_path / 'demo with spaces'
    main(['demo', '--output', str(target)])
    capsys.readouterr()
    for path in target.glob('*.md'):
        for link in re.findall(r'\[证据\]\(<([^>]+)>\)', path.read_text()):
            from pathlib import Path
            snapshot = Path(link)
            assert snapshot.exists() and json.loads(snapshot.read_text())['id'] == snapshot.name
    old = target / 'evidence' / ('f' * 24)
    old.write_text('{}')
    unrelated = target / 'evidence' / 'my-note.txt'
    unrelated.write_text('keep')
    main(['demo', '--output', str(target)])
    assert not old.exists() and unrelated.read_text() == 'keep'
    profile = json.loads((target / 'profile.json').read_text())
    assert all((target / 'evidence' / eid).exists() for p in profile['preference_audit']['pairs'] for eid in p['evidence_ids'])

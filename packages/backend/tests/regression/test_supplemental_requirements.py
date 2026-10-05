"""Supplemental requests are preserved until delivery; marked bodies are not absent."""

import json

from orbit_backend.evaluation.pipeline import evidence_checks
from orbit_backend.profiling.analysis import analyze
from orbit_backend.recommend import recommend
from orbit_backend.reporting.narrative import explain
from orbit_backend.store import Store, import_codex


def run(tmp_path, steps):
    home = tmp_path / 'codex'
    (home / 'sessions').mkdir(parents=True)
    rows = [
        {'type': 'session_meta', 'payload': {'id': 'supplement', 'source': 'cli', 'cwd': '/fictional/project'}},
        {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn'}},
        {'type': 'turn_context', 'payload': {'turn_id': 'turn', 'model': 'test-model'}},
    ]
    for kind, text in steps:
        if kind == 'mirror':
            rows.append({'type': 'event_msg', 'payload': {'type': 'user_message', 'message': text}})
        else:
            rows.append({'type': 'response_item', 'payload': {'type': 'message', 'role': kind,
                         'channel': 'final' if kind == 'assistant' else None, 'content': text}})
    (home / 'sessions' / 'supplement.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
    store = Store(tmp_path / 'evaluation.sqlite')
    import_codex(store, home)
    return store, analyze(store)


def test_mirror_only_supplement_keeps_prior_limit_scene_reader_and_evidence(tmp_path):
    store, data = run(tmp_path, [
        ('user', '给开发者写项目报告，回答简洁，控制在10字以内。'),
        ('mirror', '另外请注明来源。'),
        ('assistant', '这是一段明显超过十个字的项目报告说明。'),
    ])
    assert data['counts']['user_messages'] == 2
    finding = data['bottlenecks'][0]
    assert finding['type'] == 'long_response' and finding['measurement']['threshold'] == 10
    assert finding['scene'] == 'developer_report'
    assert len(finding['profile_evidence_ids']) == 2
    assert {r['id'] for r in finding['readers']} == {'developer'}
    recs = recommend(data)
    assert recs[0]['resource_id'] == 'humanizer-zh'
    assert all(evidence_checks(store, data, recs).values())


def test_completed_reply_ends_pending_requirement_accumulation(tmp_path):
    _, data = run(tmp_path, [
        ('user', '回答控制在10字以内。'), ('assistant', '简短回答。'),
        ('mirror', '另外请注明来源。'), ('assistant', '这次只需要核对来源，并没有继续限定篇幅。' * 10),
    ])
    assert data['bottlenecks'] == []


def test_explicit_new_task_and_replacement_do_not_keep_old_cap(tmp_path):
    _, data = run(tmp_path, [
        ('user', '回答控制在10字以内。'), ('mirror', '回答改为100字以内。'),
        ('assistant', '这段说明已经超过十个字，但仍然少于一百字。'),
    ])
    assert data['bottlenecks'] == []


def test_new_task_in_same_turn_still_breaks_pending_requirements(tmp_path):
    _, data = run(tmp_path, [
        ('user', '回答控制在10字以内。'), ('mirror', '新任务：请写一份完整文档。'),
        ('assistant', '这个新任务的文档需要保留充分内容。' * 30),
    ])
    assert data['bottlenecks'] == []


def test_delivery_with_embedded_body_can_be_reviewed_without_missing_body_gap(tmp_path):
    _, data = run(tmp_path, [
        ('user', '写项目报告，说明通俗易懂。'),
        ('assistant', '已写入 [报告](report.md)。\n\n# 项目报告\n\n导入和分析已经连通。这里给出正文说明以及下一步需要验证的限制。'),
    ])
    assert data['data_gaps'] == []
    assert '对应文档正文' not in explain(data)['next_step']


def test_explicit_fenced_body_is_present_but_delivery_notes_are_not_body(tmp_path):
    _, data = run(tmp_path, [
        ('user', '请写通俗易懂的文档。'),
        ('assistant', '已保存 [文档](document.md)。\n\n```markdown\n# 文档\n这是提供的正文。\n```'),
    ])
    assert data['data_gaps'] == []


def test_embedded_body_detection_survives_retention_cap_without_claiming_full_retention(tmp_path):
    _, data = run(tmp_path, [
        ('user', '请写通俗易懂的文档。'),
        ('assistant', '已写入 [文档](document.md)。\n' + '交付情况说明。' * 2000 + '\n以下正文：\n这是正文内容。'),
    ])
    assert {g['code'] for g in data['data_gaps']} == {'artifact_body_truncated'}
    assert '保留内容已截断' in explain(data)['next_step']


def test_verification_notes_and_excerpt_do_not_falsely_confirm_a_document_body(tmp_path):
    _, data = run(tmp_path, [
        ('user', '请写通俗易懂的文档。'),
        ('assistant', '已保存 [文档](document.md)。\n\n## 验证\n\n运行检查通过，这只是交付说明，没有包含正文。'),
    ])
    assert {g['code'] for g in data['data_gaps']} == {'artifact_body_missing'}


def test_later_response_body_fills_same_delivery_gap(tmp_path):
    _, data = run(tmp_path, [
        ('user', '请写通俗易懂的项目报告。'),
        ('assistant', '已保存 [报告](report.md)。'),
        ('assistant', '# 项目报告\n\n导入与分析已经连通。这里提供正文说明、已知限制和下一步验证方法。'),
    ])
    assert data['data_gaps'] == []
    assert '对应文档正文' not in explain(data)['next_step']


def test_new_request_cannot_fill_an_earlier_delivery_gap(tmp_path):
    _, data = run(tmp_path, [
        ('user', '请写通俗易懂的项目报告。'),
        ('assistant', '已保存 [报告](report.md)。'),
        ('user', '新任务：请写另一份文档。'),
        ('assistant', '# 文档\n\n这份文档属于另一个任务，不能用来证明前一份报告的正文已经包含在日志中。'),
    ])
    assert {g['code'] for g in data['data_gaps']} == {'artifact_body_missing'}


def test_later_excerpt_does_not_fill_delivery_gap(tmp_path):
    _, data = run(tmp_path, [
        ('user', '请写通俗易懂的文档。'), ('assistant', '已保存 [文档](document.md)。'),
        ('assistant', '以下是节选：\n# 文档\n\n这里仅摘录一小段内容，不应据此声称已经保留完整文档。'),
    ])
    assert {g['code'] for g in data['data_gaps']} == {'artifact_body_missing'}


def test_truncated_later_body_changes_missing_gap_to_truncated(tmp_path):
    _, data = run(tmp_path, [
        ('user', '请写通俗易懂的文档。'), ('assistant', '已保存 [文档](document.md)。'),
        ('assistant', '以下正文：\n' + '这是文档需要核对的正文内容。' * 2000),
    ])
    assert {g['code'] for g in data['data_gaps']} == {'artifact_body_truncated'}

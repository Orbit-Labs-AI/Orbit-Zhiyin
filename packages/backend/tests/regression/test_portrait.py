"""Generic fictional tasks check intermediate products before real-sample inspection."""

import json

import pytest

from orbit_backend.cli import main
from orbit_backend.evaluation.pipeline import _write_case
from orbit_backend.profiling.analysis import analyze
from orbit_backend.recommend import recommend
from orbit_backend.reporting.analysis_reports import (
    bottlenecks_markdown,
    cli_summary,
    process_markdown,
    profile_markdown,
)
from orbit_backend.store import Store, import_codex


def fixture_store(tmp_path):
    store = Store(tmp_path / 'tasks.sqlite')
    first = [
        {'kind': 'user', 'text': '请给初学者写一份教程，把思路讲清楚。'},
        {'kind': 'assistant', 'text': '教程按输入、变换和输出的顺序介绍程序。'},
        {'kind': 'user', 'text': '没看懂，换个直观的例子。'},
        {'kind': 'assistant', 'text': '把程序想成按步骤处理一箱苹果：先数清数量，再装进小盒。'},
        {'kind': 'user', 'text': '新任务：写项目报告，先给方案，说明判断依据。'},
        {'kind': 'tool', 'tool': 'exec_command', 'arguments': '{"cmd":"check-fictional-project"}', 'output': '{"exit_code":0}'},
        {'kind': 'assistant', 'text': '计划是先核对输入，再核对结果；检查已通过，来源见项目记录。'},
    ]
    second = [{'kind': 'user', 'text': '请用通俗的语言写这份文档。'},
              {'kind': 'assistant', 'text': '这份文档说明目的、使用方式和已知限制。'}]
    for sid, steps in [('first', first), ('second', second)]:
        home = tmp_path / sid
        _write_case(home, sid, steps)
        import_codex(store, home)
    return store


def test_profile_counts_tasks_messages_and_sessions_without_repetition_inflation(tmp_path):
    data = analyze(fixture_store(tmp_path))
    observation = next(p for p in data['profile']['observations'] if p['dimension'] == 'clarity')
    assert (observation['sessions'], observation['tasks'], observation['messages']) == (2, 2, 3)
    assert observation['categories'] == {'request': 2, 'correction': 1}
    assert len(observation['evidence_ids']) == 3
    assert len(observation['examples']) == 2
    assert data['profile']['stability'] == 'unverified'


def test_interaction_statistics_describe_recorded_steps_not_a_persona_score(tmp_path):
    interaction = analyze(fixture_store(tmp_path))['profile']['interaction']
    assert interaction['tasks'] == 3 and interaction['user_messages'] == 4
    assert interaction['multi_request_tasks'] == 1 and interaction['median_requests_per_task'] == 1
    assert interaction['tool_calls_after_request'] == 1 and interaction['final_messages_after_request'] == 4
    assert interaction['recorded_steps_per_request'] == 1.25
    assert 'efficiency_score' not in interaction and 'personality_score' not in interaction


def test_diagnostic_sequence_preserves_initial_request_reply_and_feedback(tmp_path):
    store = fixture_store(tmp_path)
    data = analyze(store)
    dossier = data['bottleneck_details'][0]
    assert dossier['type'] == 'explanation_revision'
    assert [e['kind'] for e in dossier['sequence']] == ['user_message', 'assistant_message', 'user_message']
    assert dossier['sequence'][0]['text'] == '请给初学者写一份教程，把思路讲清楚。'
    assert dossier['sequence'][-1]['text'] == '没看懂，换个直观的例子。'
    assert dossier['causal_status'] == 'unverified' and dossier['time_saved'] is None
    assert {e['event_id'] for e in dossier['sequence']} <= {e.id for e in store.events()}


def test_profile_and_diagnostics_exist_without_a_catalog_or_desired_skill(tmp_path):
    store = fixture_store(tmp_path)
    data = analyze(store)
    frozen = json.dumps([data['profile'], data['bottleneck_details']], sort_keys=True)
    assert recommend(data, catalog=[]) == []
    recs = recommend(data)
    assert {r['resource_id'] for r in recs} == {'doc-coauthoring'}
    assert all('说人话' not in e.text and 'skill' not in e.text for e in store.events())
    assert json.dumps([data['profile'], data['bottleneck_details']], sort_keys=True) == frozen
    for render in (profile_markdown, bottlenecks_markdown, process_markdown):
        assert 'Doc Coauthoring' not in render(data)
    assert recommend({**data, 'preferences': []}) == []
    assert recommend({**data, 'bottlenecks': []}) == []


def test_source_line_and_extraction_can_be_traced_through_normalization(tmp_path):
    store = fixture_store(tmp_path)
    normalized = analyze(store)['normalization']
    events = {e.id: e for e in store.events()}
    assert sum(normalized['event_counts'].values()) == len(events)
    assert any(e['extracted_signals'] for e in normalized['examples'])
    for preview in normalized['examples']:
        original = events[preview['event_id']]
        assert preview['line'] == original.ordinal
        assert preview['source_type'] == 'response_item'
        assert preview['source_subtype'] == 'message'
        assert len(preview['text']) <= 400
        assert all(s['task_id'] for s in preview['extracted_signals'])


def test_empty_profile_is_readable_and_has_no_made_up_denominator(tmp_path):
    data = analyze(Store(tmp_path / 'empty.sqlite'))
    assert data['profile']['interaction']['recorded_steps_per_request'] is None
    text = profile_markdown(data)
    assert 'None' not in text and '暂无可统计的任务' in text
    assert '暂不推荐' in cli_summary(data, [])


def test_cli_exposes_intermediate_products_in_the_terminal(tmp_path, capsys):
    target = tmp_path / 'demo'
    main(['demo', '--output', str(target)])
    summary = capsys.readouterr().out
    assert all(label in summary for label in ('1. 数据与标准化', '2. 用户画像', '3. 瓶颈分析', '4. 推荐'))
    for name in ('profile', 'bottlenecks', 'process', 'report'):
        assert (target / f'{name}.md').exists()
    assert (target / 'profile.json').exists() and (target / 'bottlenecks.json').exists()
    main(['demo', '--output', str(target), '--view', 'bottlenecks'])
    assert '发生顺序' in capsys.readouterr().out
    main(['demo', '--output', str(target), '--view', 'profile'])
    profile_text = capsys.readouterr().out
    assert '协作怎么推进' in profile_text and '<details>' not in profile_text


def test_cli_evidence_needs_no_server_and_rejects_missing_ids(tmp_path, capsys):
    store = fixture_store(tmp_path)
    event = next(e for e in store.events() if e.kind == 'user_message')
    main(['--db', str(store.path), 'evidence', event.id])
    assert event.text in capsys.readouterr().out
    main(['--db', str(store.path), 'evidence', event.id, '--json'])
    assert json.loads(capsys.readouterr().out)['id'] == event.id
    with pytest.raises(SystemExit) as error:
        main(['--db', str(store.path), 'evidence', 'missing'])
    assert error.value.code == 2


def test_profile_headline_follows_coverage_instead_of_a_demo_dimension(tmp_path):
    store = Store(tmp_path / 'workflow.sqlite')
    home = tmp_path / 'workflow'
    _write_case(home, 'workflow', [{'kind': 'user', 'text': '直接实现功能，完成后运行单元测试。'}])
    import_codex(store, home)
    profile = analyze(store)['profile']
    assert '把说明讲清楚' not in profile['headline']
    assert profile['observations'][0]['dimension'] == 'actionability'


def _dims(text):
    from orbit_backend.models import Event
    from orbit_backend.profiling.feedback import signals

    return {s.dimension for s in signals([Event("e", "s", 1, "user_message", None, text=text)])}


@pytest.mark.parametrize(("text", "dimension"), [
    ("Please keep it concise.", "brevity"),
    ("Plan first, then implement the parser.", "planning"),
    ("After the change, run the tests.", "verification"),
    ("Make sure all tests pass before you finish.", "verification"),
    ("Explain it in plain English.", "clarity"),
    ("Just do it, no need to ask me.", "autonomy"),
])
def test_english_requests_hit_the_same_dimensions(text, dimension):
    assert dimension in _dims(text)


@pytest.mark.parametrize(("text", "dimension"), [
    ("We were discussing tests in the meeting.", "verification"),
    ("How do I run the tests?", "verification"),
    ("Do not run the tests yet.", "verification"),
    ("The README is long but fine.", "brevity"),
])
def test_english_discussion_or_negation_is_not_a_requirement(text, dimension):
    assert dimension not in _dims(text)


def test_signals_carry_bumped_rule_version():
    from orbit_backend.models import Event
    from orbit_backend.profiling.feedback import signals

    [signal] = signals([Event("e", "s", 1, "user_message", None, text="Please keep it concise.")])
    assert signal.rule_version == "rules-v14"


def test_unexplained_terms_use_generic_shapes_not_one_corpus():
    from orbit_backend.profiling.bottlenecks import unexplained_terms

    # Common engineering acronyms are not jargon; JS in a front-end reply is ordinary.
    assert unexplained_terms("用 JS 调 API 返回 JSON，再在 UI 和 CLI 里显示。") == []
    # Undefined acronyms and subscripted symbols are flagged; a nearby definition clears one.
    assert unexplained_terms("用 POMDP 和 KL 约束 z_u 与 RLHF。") == ["POMDP", "KL", "z_u", "RLHF"]
    assert unexplained_terms("POMDP（部分可观测马尔可夫决策过程）用于规划，KL 约束。") == ["KL"]
    # Lower-case terms are only flagged when the caller configures them.
    assert unexplained_terms("embedding 很好") == []
    assert unexplained_terms("embedding 很好", glossary=("embedding",)) == ["embedding"]


def test_scene_of_has_no_course_or_project_names():
    from orbit_backend.profiling.feedback import scene_of

    assert scene_of("帮我看看 SPADE 的进度") != "math_explanation"
    assert scene_of("请证明这个定理") == "math_explanation"
    assert scene_of("Write a proof of the theorem") == "math_explanation"

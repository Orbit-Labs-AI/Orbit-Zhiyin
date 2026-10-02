"""Independent profile and diagnostic products, built before resource matching.

The definitions are observable counts and task-scoped requirements. There are no
persona weights, desired resource names, or thresholds fitted to a user's corpus.
"""

from collections import Counter, defaultdict
from statistics import median

from .models import Event, stable_id


def profile(preferences: list[dict], contexts: list[dict], observed: list,
            events: list[Event], context_by_id: dict) -> dict:
    """Describe requirements and interaction structure without claiming personality."""
    observations = []
    for preference in preferences:
        items = [s for s in observed if s.dimension == preference['dimension']]
        tasks = {(s.session_id, s.task_id) for s in items}
        examples, seen = [], set()
        for signal in items:
            key = (signal.session_id, signal.task_id)
            if key not in seen:
                examples.append(signal.to_dict())
                seen.add(key)
            if len(examples) == 3:
                break
        observations.append({
            **{k: preference[k] for k in ('dimension', 'label', 'target', 'sessions', 'projects', 'denominator')},
            'tasks': len(tasks), 'messages': len(items), 'categories': dict(Counter(s.category for s in items)),
            'statement': f"{preference['sessions']} 个会话、{len(tasks)} 个任务中提出过“{preference['label']}”。",
            'evidence_ids': list(dict.fromkeys(s.event_id for s in items)), 'examples': examples,
            'interpretation': '本次任务的明确要求；跨任务是否稳定仍需观察。',
        })
    task_rows, active = {}, {}
    for event in sorted(events, key=lambda e: (e.session_id, e.ordinal)):
        if event.kind == 'user_message':
            context = context_by_id[event.id]
            key = (event.session_id, context['task_id'])
            active[event.session_id] = key
            row = task_rows.setdefault(key, {'task_id': context['task_id'], 'session_id': event.session_id,
                                             'requests': 0, 'tool_calls': 0, 'responses': 0, 'evidence_ids': []})
            row['requests'] += 1
            if len(row['evidence_ids']) < 3:
                row['evidence_ids'].append(event.id)
        elif event.session_id in active:
            row = task_rows[active[event.session_id]]
            if event.kind == 'tool_call':
                row['tool_calls'] += 1
            elif event.kind == 'assistant_message' and event.details.get('phase') not in ('commentary', 'analysis'):
                row['responses'] += 1
    requests = sum(row['requests'] for row in task_rows.values())
    calls = sum(row['tool_calls'] for row in task_rows.values())
    responses = sum(row['responses'] for row in task_rows.values())
    interaction = {
        'tasks': len(task_rows), 'user_messages': requests, 'tool_calls_after_request': calls,
        'final_messages_after_request': responses,
        'recorded_steps_per_request': round((calls + responses) / requests, 2) if requests else None,
        'multi_request_tasks': sum(row['requests'] > 1 for row in task_rows.values()),
        'median_requests_per_task': median(row['requests'] for row in task_rows.values()) if task_rows else None,
        'examples': sorted(task_rows.values(), key=lambda row: (-row['requests'], row['task_id']))[:3],
        'meaning': '步骤指日志中的工具调用与非进度回复；任务边界由上下文规则识别。次数不能证明自主能力、效率或满意度。',
    }
    # Prefer the most widely observed requirement, not a desired demo outcome.
    # Coverage orders the display; it does not measure importance or personality.
    leading = observations[0] if observations else None
    headline = leading['statement'] if leading else '这批记录还没有可识别的明确协作要求。'
    return {
        'basis': 'task_requirements_and_observed_interactions', 'stability': 'unverified',
        'headline': headline, 'observations': observations, 'interaction': interaction,
        'communication': [p for p in preferences if p['target'] == 'communication'],
        'workflow': [p for p in preferences if p['target'] == 'workflow'], 'contexts': contexts,
        'method': {'unit': 'unique_session_and_task', 'development_basis': 'public_task_definitions_and_synthetic_cases',
                   'meaning': '计数描述这批任务；同一会话重复要求不增加会话支持数。场景可能重叠，不能相加当总会话数。'},
    }


def diagnostic_details(findings: list[dict], gaps: list[dict], events: list[Event], contexts: dict | None = None) -> list[dict]:
    """Show the requirement/delivery/follow-up sequence separately from any skill."""
    by_id = {event.id: event for event in events}
    output = []
    for finding in findings:
        ids = list(dict.fromkeys([finding.get('task_id')] + finding['evidence_ids']))
        sequence = sorted((by_id[eid] for eid in ids if eid in by_id), key=lambda event: event.ordinal)
        related_gaps = [g for g in gaps if g['response_event_id'] in finding['evidence_ids']]
        missing = [g['message'] for g in related_gaps]
        if finding.get('response_content') == 'artifact_delivery' and not missing:
            missing.append('日志只有文件交付说明，需要原文件核对正文。')
        if finding.get('response_content') == 'embedded_body_truncated' and not missing:
            missing.append('正文留存有截断，需要全文才能完成核对。')
        missing.append('修改是否改善理解、耗时是否减少，需要同任务的结果与读者反馈。')
        output.append({
            'id': finding['id'], 'type': finding['type'], 'scene': finding['scene'],
            'status': finding['status'], 'observed': finding['reason'],
            'profile_dimensions': finding['dimensions'],
            'profile_evidence_ids': finding['profile_evidence_ids'], 'evidence_ids': [e.id for e in sequence],
            'sequence': [event_preview(event) for event in sequence], 'missing_evidence': missing,
            'causal_status': 'unverified', 'time_saved': None,
        })
    covered = {eid for finding in findings for eid in finding['evidence_ids']}
    for gap in gaps:
        if gap['response_event_id'] in covered:
            continue
        ids = [gap['request_event_id'], gap['response_event_id']]
        sequence = sorted((by_id[eid] for eid in ids if eid in by_id), key=lambda e: e.ordinal)
        context = (contexts or {}).get(gap['request_event_id'], {})
        output.append({'id': stable_id('data_gap', *ids, gap['code']), 'type': 'data_gap', 'code': gap['code'],
                       'scene': context.get('scene', 'conversation'), 'status': 'evidence_gap',
                       'observed': gap['message'], 'profile_dimensions': [], 'profile_evidence_ids': [ids[0]],
                       'evidence_ids': ids, 'sequence': [event_preview(e) for e in sequence],
                       'missing_evidence': [gap['message']], 'causal_status': 'unverified', 'time_saved': None})
    return output


def event_preview(event: Event) -> dict:
    return {'event_id': event.id, 'session_id': event.session_id, 'line': event.ordinal,
            'kind': event.kind, 'timestamp': event.timestamp, 'model': event.model,
            'source_type': event.details.get('source_type'), 'source_subtype': event.details.get('source_subtype'),
            'input_format': event.details.get('input_format'), 'text': event.text[:400],
            'text_truncated': len(event.text) > 400 or event.details.get('original_chars', len(event.text)) > 400}


def normalization(events: list[Event], observed: list, policies: list[dict], findings: list[dict]) -> dict:
    """Expose source-to-event-to-signal transformations, with bounded examples."""
    by_event = defaultdict(list)
    for signal in observed:
        by_event[signal.event_id].append({k: signal.to_dict()[k] for k in (
            'dimension', 'category', 'target', 'scene', 'task_id', 'rule_version', 'output_contracts')})
    candidates = [eid for b in findings for eid in [b.get('task_id')] + b['evidence_ids']]
    candidates += [signal.event_id for signal in observed]
    wanted = list(dict.fromkeys(eid for eid in candidates if eid))[:8]
    lookup = {event.id: event for event in events}
    examples = [{**event_preview(lookup[eid]), 'extracted_signals': by_event[eid]}
                for eid in wanted if eid in lookup]
    return {'format': 'codex_jsonl_to_event', 'sample_policies': policies,
            'event_counts': dict(Counter(event.kind for event in events)), 'examples': examples,
            'rules': ['只采用用户会话与固定快照内的记录。', '用户消息与界面镜像按同一轮、角色、内容去重。',
                      '平台环境、插件清单、引用与附件指令不作为用户要求。', '模型来自轮次上下文，工作目录用于分组。',
                      '来源类型、行号和证据 ID 保留，工具输出只留状态与必要统计。']}

"""Audit revision chains before trying to learn a preference or an effect.

This module receives generic task events, not a desired skill or evaluation label.
It reports comparison candidates; silence/continuation never supplies approval.
"""

import re
from collections import defaultdict

from .bottlenecks import DELIVERY_SEPARATOR, combine_response, delivery_content
from .content import visible_text
from .feedback import answers_clarification, clarification_question, starts_new_subject
from .models import Event


def response_observation(parts: list[Event]) -> dict:
    """Counts describe the retained reply; file-delivery notes are not its body."""
    if not parts:
        return {'content_status': 'missing', 'features': None, 'evidence_ids': []}
    response = combine_response(parts)
    status = delivery_content(response)
    truncated = response.details.get('original_chars', len(response.text)) > len(response.text)
    output = {'content_status': status, 'evidence_ids': [e.id for e in parts], 'features': None,
              'model': response.model}
    if status != 'message' or truncated:
        output['unavailable_reason'] = '需要完整回复正文，交付说明或截断片段不足以比较风格。'
        return output
    text, quality = visible_text(response.text.replace(DELIVERY_SEPARATOR, '\n\n'))
    if quality == 'unbalanced_details':
        output['unavailable_reason'] = '可见范围缺少完整边界。'
        return output
    sentences = [s.strip() for s in re.split(r'[。！？.!?\n]+', text) if s.strip()]
    output['features'] = {'first_layer_chars': len(text), 'sentence_units': len(sentences),
                          'mean_unit_chars': round(sum(len(s) for s in sentences) / len(sentences), 2) if sentences else None}
    output['feature_meaning'] = '句子单位按终止符与换行分段；只描述形式，不评分读者理解或事实正确性。'
    return output


def comparison_signal(event: Event | None) -> str | None:
    """Require an explicit relative judgment, not a generic 'OK' or 'continue'."""
    if not event or starts_new_subject(event.text):
        return None
    text = re.sub(r'“[^”\n]*”|"[^"\n]*"|`[^`\n]*`', '', event.text)
    for clause in re.split(r'[，,。；;\n]', text):
        if re.search(r'是否|是不是|[?？]|没有|并非|未|不|如果|假如|若|倘|要是|希望|期望', clause):
            continue
        if re.match(r'\s*(?:请|解释|介绍|讨论|假设|例如)', clause):
            continue
        if re.search(r'(?:这一版|这版|现在这版|新版).{0,8}比(?:上一版|之前|原来).{0,6}更(?:清楚|好懂|易懂|直观)', clause):
            return 'revised_preferred'
        if re.search(r'(?:上一版|旧版|原来那版).{0,8}比(?:这一版|这版|新版).{0,6}更(?:清楚|好懂|易懂|直观)', clause):
            return 'original_preferred'
    return None


def audit_revisions(findings: list[dict], events: list[Event], contexts: dict) -> dict:
    """Keep an original/revision/follow-up chain inside one task, including gaps."""
    lookup = {e.id: e for e in events}
    sessions = defaultdict(list)
    for event in sorted(events, key=lambda e: (e.session_id, e.ordinal)):
        sessions[event.session_id].append(event)
    pairs = []
    for finding in findings:
        if finding['type'] != 'explanation_revision':
            continue
        feedback = max((lookup[eid] for eid in finding['profile_evidence_ids']), key=lambda e: e.ordinal)
        original_parts = sorted((lookup[eid] for eid in finding['evidence_ids'] if lookup[eid].kind == 'assistant_message'), key=lambda e: e.ordinal)
        revised_parts, next_user, clarification_ids = [], None, []
        for event in sessions[feedback.session_id]:
            if event.ordinal <= feedback.ordinal:
                continue
            if event.kind == 'user_message':
                same_task = contexts[event.id]['task_id'] == finding['task_id']
                previous_reply = revised_parts[-1].text if revised_parts else ''
                # A callback can answer a tool-based question without a final
                # assistant message. A delivered rewrite followed by feedback
                # stays a follow-up; it must not be discarded as clarification.
                awaiting_choice = not revised_parts or clarification_question(previous_reply)
                if same_task and awaiting_choice and answers_clarification(event, previous_reply) and not comparison_signal(event):
                    clarification_ids.extend([part.id for part in revised_parts] + [event.id])
                    revised_parts = []
                    continue
                next_user = event
                break
            if event.kind == 'assistant_message' and event.details.get('phase') not in ('analysis', 'commentary'):
                revised_parts.append(event)
        original, revised = response_observation(original_parts), response_observation(revised_parts)
        if len(revised_parts) == 1 and clarification_question(revised_parts[0].text):
            revised = {**revised, 'content_status': 'clarification_pending', 'features': None,
                       'unavailable_reason': '只找到追问，尚未找到改写正文。'}
        same_task = bool(next_user and contexts[next_user.id]['task_id'] == finding['task_id'])
        direction = comparison_signal(next_user) if same_task else None
        complete = original['features'] is not None and revised['features'] is not None
        ids = list(dict.fromkeys([finding['task_id']] + original['evidence_ids'] + [feedback.id] +
                                clarification_ids + revised['evidence_ids'] + ([next_user.id] if same_task else [])))
        pairs.append({'bottleneck_id': finding['id'], 'scene': finding['scene'], 'task_id': finding['task_id'],
                      'location': 'answer_to_user_revision', 'original': original, 'revised': revised,
                      'revision_event_id': feedback.id, 'followup_event_id': next_user.id if same_task else None,
                      'clarification_event_ids': clarification_ids,
                      'next_input_relation': 'same_task' if same_task else 'new_task' if next_user else 'missing',
                      'observed_comparison': direction, 'human_label': None,
                      'ready_for_annotation': bool(complete and direction), 'eligible_for_training': False,
                      'necessary_facts_equivalent': None, 'effect_status': 'unmeasured', 'evidence_ids': ids,
                      'model_changed': bool(revised_parts and original['model'] != revised['model'])})
    return {'pairs': pairs, 'revision_chains': len(pairs),
            'complete_response_pairs': sum(p['original']['features'] is not None and p['revised']['features'] is not None for p in pairs),
            'observed_comparisons': sum(p['observed_comparison'] is not None for p in pairs),
            'ready_for_annotation': sum(p['ready_for_annotation'] for p in pairs),
            'learned_preference': None, 'preference_weights': None,
            'meaning': '相对判断是待人工核验的候选标签；继续、沉默和结束会话不视为满意。未拟合偏好分布或收益。'}

"""Readable intermediate products. They require analysis, never a resource catalog."""

from .feedback import RULES, SCENE_LABELS


def _link(eid: str, base: str) -> str:
    return f'[证据](<{base.rstrip("/")}/{eid}>)'


def profile_markdown(data: dict, evidence_base: str = '/v1/evidence') -> str:
    profile = data['profile']
    lines = ['# 你的协作画像', '', profile['headline'], '',
             '下面分别看任务、明确要求和协作过程。它们描述这批历史，不直接给你定型。', '',
             '## 主要做哪些任务', '', '| 场景 | 会话 | 用户消息 | 明确的读者要求 |', '| --- | ---: | ---: | --- |']
    for context in sorted(profile['contexts'], key=lambda c: -c['user_messages']):
        readers = '、'.join(r['label'] for r in context['readers']) or '未明确'
        lines.append(f"| {context['label']} | {context['user_sessions']} | {context['user_messages']} | {readers} |")
    lines += ['', '一个会话可以包含多个场景，会话列不能相加。一般对话是尚未细分的消息，不代表都是闲聊。', '',
              '## 你明确要求过什么', '']
    for observation in profile['observations']:
        lines += [f"### {observation['label']}", '', observation['statement'] +
                  f"覆盖 {observation['projects']} 个工作目录组；全样本为 {observation['denominator']} 个有用户输入的会话。", '']
        lines += ['<details>', '<summary>查看原始要求</summary>', '']
        for example in observation['examples'][:2]:
            scene = SCENE_LABELS.get(example['scene'], example['scene'])
            lines += [f"{scene} · {_link(example['event_id'], evidence_base)}", '', '> ' + example['quote'].replace('\n', '\n> '), '']
        lines += ['</details>', '']
    interaction = profile['interaction']
    lines += ['## 协作怎么推进', '']
    if not interaction['tasks']:
        lines += ['暂无可统计的任务。', '']
    else:
        lines += [
              f"按当前上下文规则识别出 {interaction['tasks']} 个任务，其中 {interaction['multi_request_tasks']} 个收到过多条用户消息。每个任务的用户消息中位数为 {interaction['median_requests_per_task']}。", '',
              f"日志里，每条用户消息平均对应 {interaction['recorded_steps_per_request']} 次工具调用或非进度回复。这个比例描述记录密度，不能据此判断自主能力或效率。", '']
    lines += [
              '任务边界是规则判断，可通过 profile.json 的任务示例核对。后续可按项目、模型或场景分别读取。', '',
              '画像不需要先指定想要哪个 skill；推荐模块之后再消费这些要求和具体卡点。', '']
    audit = profile['preference_audit']
    lines += ['## 改写之后是否更合意', '',
              f"找到 {audit['revision_chains']} 条修改链，其中 {audit['complete_response_pairs']} 条留有前后完整回复，{audit['observed_comparisons']} 条有明确的相对评价。", '',
              '这些材料先用于回看与标注；没有相对评价时，不能把继续任务或沉默当作满意。目前没有训练长期偏好或估算资源收益。', '']
    return '\n'.join(lines)


def bottlenecks_markdown(data: dict, evidence_base: str = '/v1/evidence') -> str:
    dossiers = data['bottleneck_details']
    missing = sum(d['type'] == 'data_gap' for d in dossiers)
    lines = ['# 哪些地方值得回看', '', f"这批记录有 {len(dossiers) - missing} 处候选或修改记录，另有 {missing} 处材料缺口。先还原发生顺序，再判断原因。", '']
    if not dossiers:
        lines += ['现有规则没有找到能关联要求与交付的具体卡点；失败次数或缺少反馈都不足以单独下结论。', '']
    candidates = [d for d in dossiers if d['type'] != 'data_gap']
    for dossier in candidates[:3]:
        label = SCENE_LABELS.get(dossier['scene'], dossier['scene'])
        lines += ['## ' + label, '', dossier['observed'], '', '发生顺序：', '']
        for item in dossier['sequence']:
            role = {'user_message': '你的要求', 'assistant_message': 'Agent 回复', 'tool_result': '工具结果'}.get(item['kind'], item['kind'])
            lines += [f"**{role}** · {_link(item['event_id'], evidence_base)}", '',
                      '> ' + (item['text'] or '正文未留存；通过证据接口查看状态与统计。').replace('\n', '\n> '), '']
        lines += ['还需要核对：', ''] + ['- ' + missing for missing in dossier['missing_evidence']] + ['']
        pair = next((p for p in data['profile']['preference_audit']['pairs'] if p['bottleneck_id'] == dossier['id']), None)
        if pair:
            content_label = {'message': '对话回复已留存', 'missing': '没有找到改写回复',
                             'artifact_delivery': '只有文件交付说明', 'embedded_body': '附有正文，完整性需核对',
                             'embedded_body_truncated': '正文被截断'}.get(pair['revised']['content_status'], '需核对')
            direction_label = {'revised_preferred': '用户明确说新版更易懂', 'original_preferred': '用户明确说旧版更易懂'}.get(pair['observed_comparison'], '暂无')
            lines += ['后续链路：修改要求发生在回复之后。', '',
                      f"改写回复：{content_label}；明确的前后相对评价：{direction_label}。", '',
                      '完整元数据与前后回复计数见 profile.json 的 preference_audit。相对评价仍需人工核验，不能直接说明改写有效。', '']
    if len(candidates) > 3:
        lines += [f'其余 {len(candidates) - 3} 处的完整顺序见 bottlenecks.json。', '']
    if missing:
        lines += ['## 哪些材料还不足', '',
                  f'{missing} 处交付无法仅凭日志核对。下面展示前三处；完整记录见 bottlenecks.json。', '']
        for gap in [d for d in dossiers if d['type'] == 'data_gap'][:3]:
            lines += [gap['observed'] + ' · ' + '、'.join(_link(eid, evidence_base) for eid in gap['evidence_ids']), '']
    return '\n'.join(lines)


def process_markdown(data: dict, evidence_base: str = '/v1/evidence') -> str:
    counts = data['counts']
    lines = ['# 从数据到判断', '',
             f"本次采用 {counts['sessions']} 个会话、{counts['events']} 条统一事件。每条判断可回到来源类型、行号和原始用户要求。", '',
             '流程：本地记录 → 统一事件 → 按任务提取要求 → 画像与交付核对 → 资源匹配。', '',
             '## 标准化做了什么', ''] + ['- ' + rule for rule in data['normalization']['rules']]
    lines += ['', '## 一条记录如何参与分析', '']
    for example in data['normalization']['examples'][:4]:
        lines += [f"来源 `{example['source_type']}/{example['source_subtype']}`，第 {example['line']} 行 → `{example['kind']}` · {_link(example['event_id'], evidence_base)}", '',
                  '> ' + (example['text'] or '仅保留必要元数据。').replace('\n', '\n> '), '']
        if example['extracted_signals']:
            descriptions = [f"{RULES[s['dimension']][0]}（{SCENE_LABELS.get(s['scene'], s['scene'])}）" for s in example['extracted_signals']]
            lines += ['提取为：' + '、'.join(descriptions) + '。', '']
        else:
            lines += ['这条记录用于还原交付，不增加用户偏好计数。', '']
    lines += ['画像按不同会话和任务聚合；瓶颈核对同一任务的要求、交付与后续反馈。两者先独立生成，之后才与资源目录匹配。', '',
              '已看过的真实样本只用于运行核对，不能再作为独立测试集。规则检查使用构造案例；主观可读性仍需真实读者。', '']
    return '\n'.join(lines)


def cli_summary(data: dict, recommendations: list[dict]) -> str:
    """A compact inspection order; matching never replaces the intermediate products."""
    counts, profile = data['counts'], data['profile']
    lines = ['1. 数据与标准化',
             f"   {counts['sessions']} 个会话 → {counts['events']} 条事件；按 {counts['projects']} 个工作目录组整理。",
             '2. 用户画像', '   ' + profile['headline']]
    for observation in profile['observations'][1:3]:
        lines.append('   ' + observation['statement'])
    contexts = sorted(profile['contexts'], key=lambda c: -c['user_messages'])[:3]
    if contexts:
        lines.append('   场景：' + '、'.join(f"{c['label']} {c['user_messages']} 条用户消息" for c in contexts) + '。')
        if any(c['scene'] == 'conversation' for c in contexts):
            lines.append('   一般对话是当前规则尚未细分的消息。')
    lines += ['3. 瓶颈分析']
    if data['bottleneck_details']:
        for dossier in data['bottleneck_details'][:3]:
            lines.append(f"   {SCENE_LABELS.get(dossier['scene'], dossier['scene'])}：{dossier['observed']}")
        lines.append('   这是需要回看的记录；具体原因与修改收益仍需核对。')
    else:
        lines.append('   尚未找到要求与交付都可回看的具体卡点，暂不据此下结论。')
    lines += ['4. 推荐']
    if recommendations:
        for rec in recommendations[:3]:
            lines.append(f"   {rec['name']}：{rec['reason']}")
        lines.append('   来源已固定版本；实际改善效果尚未测量。')
    else:
        lines.append('   证据或适用资源不足，暂不推荐。')
    return '\n'.join(lines)

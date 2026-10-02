/* ============ simulated events ============ */
function simEvent(k) {
  const eventAgent = { done: 'cc', waiting: 'cx', stuck: 'cx', ctx: 'cc' }[k];
  if (eventAgent && !sourceEnabled({ a: eventAgent })) { toast(agent(eventAgent).name + ' 的数据源已停用，不会产生提醒'); return; }
  if (S.paused && k !== 'newsrc') { toast('采集已暂停，不会产生事件', { act: '恢复采集', onAct: () => { S.paused = false; render(); } }); return; }
  if (k === 'idle') { S.sim = 'idle'; S.attn.clear(); S.hud.open = false; render(); toast('已切换为空闲：没有运行中的会话，悬浮组件自动隐身'); return; }
  if (k === 'running') { S.sim = 'running'; S.attn.clear(); render(); toast('已恢复为有会话运行中'); return; }
  const ch = S.notif[k] || [1, 1, 1]; const banner = !!ch[0] && !S.hud.mute; const ambient = !!ch[1] || !!ch[2];
  const N = {
    done: { t: '会话完成 · Hackathon', b: 'Claude Code · 42 分钟 · 186 步 · 推送了 2 个提交', a1: '查看轨迹', on1: () => ACT.hudTraj(), a2: '稍后' },
    waiting: { t: 'Codex 等你确认', b: 'team-hub · 请求执行 git push origin collab', a1: '在终端中处理', on1: () => ACT.hudGo({ dataset: { v: 'waiting' } }), a2: '稍后' },
    stuck: { t: '同一命令连续失败 4 次', b: 'Codex · Surge 规则 · python gen_rules.py --publish。可能是 CDN token 过期', a1: '查看原因', on1: () => { S.pop = true; render(); }, a2: '忽略 1 小时', on2: () => ACT.popIgnore({ dataset: { k: 'stuck' } }) },
    ctx: { t: '上下文即将压缩（78%）', b: 'Claude Code · latentskill · 建议先让 Agent 总结进度再继续', a1: '复制提示语', on1: () => ACT.hudTip() },
    weekly: { t: '每周报告已生成', b: '9 月第 4 周：' + sel({ range: 7, noExtra: true }).length + ' 个会话 · 人格 ' + (personaNow().ok ? personaNow().code : '—') + ' 没有变化', a1: '查看报告', on1: () => openReport() }
  };
  if (k === 'newsrc') {
    if (S.extraSrc.some((x) => /cursor/i.test(x.name))) { toast('Cursor 已经添加过了'); return; }
    notify({ t: '发现新的数据来源', b: 'Cursor 的会话数据库：~/Library/Application Support/Cursor', a1: '添加', on1: () => { S.extraSrc.push({ name: 'Cursor', path: '~/Library/Application Support/Cursor/User/workspaceStorage', fmt: 'sqlite', n: 37 }); render(); toast('已添加 Cursor，正在索引 37 个会话（示例）'); }, a2: '忽略', force: true });
    return;
  }
  if (ambient) {
    if (k === 'done') { S.sim = 'done'; clearTimeout(SIMT); SIMT = setTimeout(() => { if (S.sim === 'done') { S.sim = 'running'; render(); } }, 8000); }
    else if (k === 'waiting') S.sim = 'waiting';
    else if (k === 'stuck') { S.attn.add('stuck'); S.sim = 'stuck'; }
    else if (k === 'ctx') { S.attn.add('ctx'); if (S.sim !== 'stuck') S.sim = 'ctx'; }
    render();
  }
  if (banner) notify(N[k]);
  if (!banner && !ambient) toast('「' + N[k].t + '」的所有提醒渠道都已关闭');
  else if (!banner) toast(S.hud.mute ? '提醒已暂停，只更新了菜单栏与悬浮组件' : '这类事件的横幅已在通知设置中关闭');
}
MENUS.demo = () => [{ h: '模拟事件（会触发通知、菜单栏与悬浮组件）' }, { t: '会话完成', v: () => simEvent('done') }, { t: '有会话等你确认', v: () => simEvent('waiting') }, { t: '同一命令连续失败', v: () => simEvent('stuck') }, { t: '上下文即将压缩', v: () => simEvent('ctx') }, { t: '每周报告已生成', v: () => simEvent('weekly') }, { t: '发现新的数据来源', v: () => simEvent('newsrc') }, { sep: 1 }, { t: '空闲（没有运行中的会话）', on: S.sim === 'idle', v: () => simEvent('idle') }, { t: '有会话运行中', on: S.sim !== 'idle', v: () => simEvent('running') }, { sep: 1 }, { t: '播放首次启动', v: () => openOnboarding(0) }, { t: '播放人格揭晓', v: () => openReveal() }, { t: '问本地 Agent', v: () => openAsk('overview') }, { sep: 1 }, { t: '关于这个 Demo', v: () => openAbout() }, { t: '重置演示数据', v: () => resetDemo() }];


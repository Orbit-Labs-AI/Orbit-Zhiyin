/* ============ simulated events ============
   Two ambient channels, driven by the notification matrix (settings › 通知) independently (BUG-40):
     S.sim     = menu-bar badge (column 菜单栏角标)        S.hudSim = floating HUD (column 悬浮组件)
   S.simBase is the resting state ('running' | 'idle') both channels fall back to once an alert is cleared or a「完成」
   has been shown for 8 s (BUG-41). S.attn (the panel's「需要关注」list) is kept whenever either channel got the event. */
const SIM_CH = { sim: 2, hudSim: 1 };
function simChanOn(c, k) { const ch = S.notif[k] || [1, 1, 1]; return !!ch[SIM_CH[c]] && !(c === 'hudSim' && S.hud.mute); }
/* the latest event a channel received is what it shows; once something is cleared the channel re-derives its state from
   what is still open — failing command, context, an unanswered confirmation — else rests (BUG-74 / BUG-41) */
S.waitOpen = S.waitOpen || false;
// a finished session shows on the badge for 8 s by default (as published); the matrix can turn the column off
S.notif.done = [1, 1, 1];
function simSettle(force) {
  Object.keys(SIM_CH).forEach((c) => {
    if (!force && S[c] === 'done') return;
    S[c] = S.attn.has('stuck') && simChanOn(c, 'stuck') ? 'stuck' : S.attn.has('ctx') && simChanOn(c, 'ctx') ? 'ctx' : S.waitOpen && simChanOn(c, 'waiting') ? 'waiting' : S.simBase;
  });
}
function simIdle() { return S.simBase === 'idle' || S.sim === 'idle'; }
/* an event that was handled (「去处理」,「查看」) leaves every channel that still shows it */
function simClear(kind) { if (kind === 'waiting') S.waitOpen = false; Object.keys(SIM_CH).forEach((c) => { if (S[c] === kind) S[c] = S.simBase; }); simSettle(); }
// live mode: the realtime snapshot (98-live-ops.js) drives S.simBase / S.attn / S.waitOpen; nothing is simulated
const simOff = () => typeof LV !== 'undefined' && LV.live;
function simEvent(k) {
  if (simOff()) { toast('实时模式不模拟事件：菜单栏、悬浮组件与通知跟随本机的会话'); return; }
  const eventAgent = { done: 'cc', waiting: 'cx', stuck: 'cx', ctx: 'cc' }[k];
  if (eventAgent && !sourceEnabled({ a: eventAgent })) { toast(agent(eventAgent).name + ' 的数据源已停用，不会产生提醒'); return; }
  if (S.paused && k !== 'newsrc') { toast('采集已暂停，不会产生事件', { act: '恢复采集', onAct: () => { S.paused = false; render(); } }); return; }
  if (k === 'idle' || k === 'running') {
    S.simBase = k; S.attn.clear(); S.waitOpen = false; clearTimeout(SIMT); simSettle(true); if (k === 'idle') S.hud.open = false; render();
    toast(k === 'idle' ? '已切换为空闲：没有运行中的会话，悬浮组件自动隐身' : '已恢复为有会话运行中'); return;
  }
  const ch = S.notif[k] || [1, 1, 1]; const banner = !!ch[0] && !S.hud.mute;
  const toHud = simChanOn('hudSim', k), toBadge = simChanOn('sim', k); const ambient = toHud || toBadge;
  const doneS = BYID[DONE_ID];
  const N = {
    done: { t: '会话完成 · ' + PJI[doneS.p].name, b: agent(doneS.a).name + ' · ' + dur(doneS.dur) + ' · ' + doneS.tools + ' 步 · 推送了 2 个提交', a1: '查看轨迹', on1: () => ACT.hudTraj(), a2: '稍后' },
    waiting: { t: 'Codex 等你确认', b: 'team-hub · 请求执行 git push origin collab', a1: '在终端中处理', on1: () => ACT.hudGo({ dataset: { v: 'waiting' } }), a2: '稍后' },
    stuck: { t: '同一命令连续失败 4 次', b: 'Codex · Surge 规则 · python gen_rules.py --publish。可能是 CDN token 过期', a1: '查看原因', on1: () => { S.pop = true; render(); }, a2: '忽略 1 小时', on2: () => ACT.popIgnore({ dataset: { k: 'stuck' } }) },
    ctx: { t: '上下文即将压缩（78%）', b: 'Claude Code · latentskill · 建议先让 Agent 总结进度再继续', a1: '复制提示语', on1: () => ACT.hudTip() },
    weekly: { t: '每周报告已生成', b: '9 月第 4 周：' + sel({ range: 7, noExtra: true }).length + ' 个会话 · 人格 ' + (personaNow().ok ? personaNow().code : '—') + ' 没有变化', a1: '查看报告', on1: () => openReport() }
  };
  if (k === 'newsrc') {
    // the example source is one Orbit has a session connector for (Hermes Agent, orbit_data MAPPERS), not Cursor (D9)
    const has = () => S.extraSrc.some((x) => /hermes/i.test(x.name));
    if (has()) { toast('Hermes Agent 已经添加过了'); return; }
    // two banners can be open at once: the second「添加」must not add it again (BUG-43)
    notify({ t: '发现新的数据来源', b: 'Hermes Agent 的会话数据库：~/.hermes/state.db', a1: '添加', on1: () => { if (has()) { toast('Hermes Agent 已经添加过了'); return; } S.extraSrc.push({ name: 'Hermes Agent', path: '~/.hermes/state.db', fmt: 'sqlite', n: 37 }); render(); toast('已添加 Hermes Agent，正在索引 37 个会话（示例）'); }, a2: '忽略', force: true });
    return;
  }
  if (ambient) {
    const set = (v) => { if (toHud) S.hudSim = v; if (toBadge) S.sim = v; };
    if (k === 'done') { set('done'); clearTimeout(SIMT); SIMT = setTimeout(() => { simClear('done'); render(); }, 8000); }
    else if (k === 'waiting') { S.waitOpen = true; set('waiting'); }
    else if (k === 'stuck') { S.attn.add('stuck'); set('stuck'); }
    else if (k === 'ctx') { S.attn.add('ctx'); set('ctx'); }
    render();
  }
  if (banner) notify(N[k]);
  if (!banner && !ambient) toast(S.hud.mute && (ch[0] || ch[1]) ? '提醒已暂停：横幅与悬浮组件都没有打扰你' : '「' + N[k].t + '」的所有提醒渠道都已关闭');
  else if (!banner) toast(S.hud.mute ? '提醒已暂停，只更新了菜单栏角标' : '这类事件的横幅已在通知设置中关闭');
}
const simMenu = () => [{ h: '模拟事件（会触发通知、菜单栏与悬浮组件）' }, { t: '会话完成', v: () => simEvent('done') }, { t: '有会话等你确认', v: () => simEvent('waiting') }, { t: '同一命令连续失败', v: () => simEvent('stuck') }, { t: '上下文即将压缩', v: () => simEvent('ctx') }, { t: '每周报告已生成', v: () => simEvent('weekly') }, { t: '发现新的数据来源', v: () => simEvent('newsrc') }, { sep: 1 }, { t: '空闲（没有运行中的会话）', on: S.simBase === 'idle', v: () => simEvent('idle') }, { t: '有会话运行中', on: S.simBase !== 'idle', v: () => simEvent('running') }, { sep: 1 }, { t: '播放首次启动', v: () => openOnboarding(0) }, { t: '播放人格揭晓', v: () => openReveal() }, { t: '问本地 Agent', v: () => openAsk('overview') }, { sep: 1 }, { t: '关于这个 Demo', v: () => openAbout() }, { t: '重置演示数据', v: () => resetDemo() }];
// live mode keeps only the replays that do not invent session events
MENUS.demo = () => (simOff() ? [{ t: '播放首次启动', v: () => openOnboarding(0) }, { t: '播放人格揭晓', v: () => openReveal() }, { t: '问本地 Agent', v: () => openAsk('overview') }, { sep: 1 }, { t: '关于 Orbit', v: () => openAbout() }] : simMenu());

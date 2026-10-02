/* ============ menu bar panel ============ */
/* Shared "live" bits (used by the panel, the HUD and the desktop widgets):
   - DONE_ID: the session the simulated「会话完成」event refers to (a finished Claude Code session, not the running one),
     so「查看」after the event opens a session that is really complete (BUG-42).
   - S.simBase ('running' | 'idle'): the resting state the demo returns to after an alert is cleared (BUG-41);
     S.hudSim: the state the HUD shows, separate from S.sim (menu-bar badge) so the notification matrix's two columns
     work independently (BUG-40). Both are set in 70-sim.js.
   - ctxBar(): the context-usage bar with the compaction threshold (the panel's clearest small chart, reused as is). */
const DONE_ID = FEAT_ID;
S.simBase = S.simBase || 'running'; S.hudSim = S.hudSim || S.sim; S.attn = S.attn || new Set();
S.wgSize = S.wgSize || store.get('wgSize', 'm');
function ctxBar(pct, opt) {
  opt = opt || {}; const th = opt.th == null ? 80 : opt.th;
  return '<div class="ctxbar' + (opt.cls ? ' ' + opt.cls : '') + '" role="img" aria-label="上下文已用 ' + pct + '%，' + th + '% 时压缩">' +
    '<div class="ctxbar-h"><span>' + (opt.label || '上下文') + ' <b class="mono">' + pct + '%</b></span><span class="mono">' + th + '% 压缩</span></div>' +
    '<div class="ctxbar-t"><span class="ctxbar-f' + (pct >= th - 5 ? ' warn' : '') + '" style="width:' + clamp(pct, 0, 100) + '%"></span><span class="ctxbar-th" style="left:' + th + '%"></span></div></div>';
}
function liveSession() { const s = BYID[LIVE_ID]; return s && !simIdle() && sourceEnabled(s) && !S.excluded.has(s.id) ? s : null; }
function popLiveCard() {
  const s = liveSession(); if (!s) return '';
  return '<div class="sec col" style="gap:6px"><div class="row"><span class="dot live" style="background:var(--a1)"></span><b style="font-size:13px">Claude Code</b><span class="cap">· Hackathon</span><span style="flex:1"></span><span class="mono" style="font-size:12px" data-live>' + liveElapsed() + '</span></div><div style="font-size:13px;font-weight:600">' + esc(s.title) + '</div><div class="row cap" style="font-size:12px;min-width:0"><span class="aib">进行中</span><span class="mono" data-hudtool style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + HUD_TOOLS[HUD_T % HUD_TOOLS.length] + '</span><span style="flex:1"></span><span class="mono" style="font-size:11px">工具 <b data-livetools>' + S.live.tools + '</b></span></div>' +
    ctxBar(S.live.ctx) +
    '<div class="row" style="margin-top:4px"><button type="button" class="btn sm" data-act="popTraj">查看轨迹</button><button type="button" class="btn sm gh" data-act="hudMute">' + (S.hud.mute ? '恢复提醒' : '暂停提醒') + '</button></div></div>';
}
/* the panel hangs 6px under the menu bar with its right edge aligned to the Tandem status item */
function popPlace() {
  const el = $('#pop'); if (el.hidden) return;
  const g = $('.mbar [data-act="pop"]'); const d = desk.getBoundingClientRect();
  if (g) { const r = g.getBoundingClientRect(); el.style.right = Math.max(8, Math.round(d.right - r.right)) + 'px'; }
  el.style.top = (MB_H + 6) + 'px';
}
/* a metric with its 30-day baseline underneath: ▲ / ▼ + the baseline value; `goodDown` colours a rise red and a drop green */
function popMetric(label, v, base, fmtv, goodDown) {
  const up = v > base + 1e-9, same = Math.abs(v - base) < 1e-9;
  const col = same ? 'var(--ink-3)' : (up === !!goodDown) ? 'var(--crit)' : 'var(--good)';
  return '<span class="col" style="gap:0"><span class="cap" style="font-size:11px">' + label + '</span><b class="mono" style="font-size:15px">' + fmtv(v) + '</b><span class="mono cap pm-base" style="font-size:10px"><span style="color:' + col + '">' + (same ? '＝' : up ? '▲' : '▼') + '</span> 均 ' + fmtv(base) + '</span></span>';
}
function renderPop() {
  const el = $('#pop'); el.hidden = false; popPlace();
  const p = personaNow();
  const available = ALL.filter((s) => sourceEnabled(s) && !S.excluded.has(s.id));
  const attn = new Set([...S.attn].filter((k) => sourceEnabled({ a: k === 'stuck' ? 'cx' : 'cc' })));
  const today = available.filter((s) => s.d === 120 && (!simIdle() || !s.live));
  const liveMin = (Date.now() - S.live.t0) / 60000;
  const head = (title, meta, badge) => '<div class="row" style="padding:12px 14px 10px"><div style="flex:1;min-width:0"><div class="row" style="gap:6px"><b style="font-size:13px">' + title + '</b>' + (badge || '') + '</div><div class="mono cap" style="font-size:11px">' + meta + '</div></div><button type="button" class="ib" data-act="openSettings" data-tab="notify" aria-label="通知设置">' + ic('settings', 15) + '</button></div>';
  const foot = '<div class="sec row" style="background:var(--sunken)">' + (p.ok ? glyphSVG(p, 30) : '') + '<div style="flex:1;min-width:0"><b class="mono" style="letter-spacing:.04em">' + (p.ok ? p.code : '—') + '</b> <span style="font-size:13px">' + (p.ok ? p.zh : '样本不足') + '</span></div><button type="button" class="btn sm p" data-act="popOpen">打开 Tandem <span class="mono" style="opacity:.7;font-size:11px">' + kb('⌥0') + '</span></button></div>';
  // last 7 days: one column per day, count on top, today in ink (the orange stays reserved for Claude), weekday underneath
  const days = []; for (let d = 114; d <= 120; d++) days.push([d, available.filter((s) => s.d === d && !(s.live && simIdle())).length]);
  const mx = Math.max(1, ...days.map((x) => x[1]));
  const avg7 = sum(days, (x) => x[1]) / 7;
  const week = '<div class="sec"><div class="row" style="justify-content:space-between"><span class="eb">近 7 天</span><span class="mono cap" style="font-size:11px">日均 ' + f1(avg7) + ' · 今天 ' + today.length + '</span></div><div class="pwk" role="img" aria-label="近 7 天每天的会话数">' + days.map((x) => '<span class="pwk-c' + (x[0] === 120 ? ' today' : '') + '" data-tip="' + md(x[0]) + ' 周' + WD[wd(x[0])] + '：' + x[1] + ' 个会话' + (x[0] === 120 ? '（今天）' : '') + '"><b class="mono">' + x[1] + '</b><i style="height:' + Math.max(3, x[1] / mx * 30).toFixed(1) + 'px"></i><span class="mono cap">' + (x[0] === 120 ? '今' : WD[wd(x[0])]) + '</span></span>').join('') + '</div></div>';
  const top = recTop('menubar')[0];
  const rec = top ? '<div class="sec row" style="gap:10px"><span style="width:28px;height:28px;flex:none;border-radius:7px;background:var(--sunken);display:grid;place-items:center">' + ic(top.icon, 15) + '</span><div style="flex:1;min-width:0"><div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(top.title) + '</div><div class="cap" style="font-size:11px">本周最值得做 · ' + top.gain + '</div></div><button type="button" class="btn sm" data-act="popRec" data-id="' + top.id + '">预览</button></div>' : '';
  const doneS = BYID[DONE_ID];
  const doneBadge = S.sim === 'done' && doneS ? '<button type="button" class="bdg" data-act="popSess" data-id="' + DONE_ID + '" style="background:var(--good-bg);color:var(--good);border:0" data-tip="' + esc(doneS.title) + '">刚刚完成 1 个</button>' : '';
  const cxRow = (lbl) => sourceEnabled({ a: 'cx' }) ? (S.sim === 'waiting' ? '<div class="sec col" style="gap:6px;background:var(--warn-bg)"><div class="row"><span style="width:9px;height:9px;border-radius:2px;background:var(--warn-m)"></span><b style="font-size:13px">Codex · team-hub</b><span style="flex:1"></span><span class="cap" style="font-size:11px">等你确认 · 2 分钟</span></div><div class="mono" style="font-size:12px;padding:6px 8px;border-radius:6px;background:var(--surface)">git push origin collab</div><div class="row" style="flex-wrap:wrap"><button type="button" class="btn sm p" data-act="hudGo" data-v="waiting">在终端中处理</button><span class="cap" style="font-size:11px">Tandem 不会代你批准</span></div></div>' : '<button type="button" class="sec row" data-act="popSess" data-id="sess-1001-0903" style="width:100%;border:0;border-top:1px solid var(--hair);background:none;text-align:left;font-size:12px"><span class="dot" style="background:var(--a2)"></span><span style="flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">Codex · team-hub · 同步 collab 并审核日报</span><span class="mono cap" style="font-size:11px">09:03 · 12m ✓</span></button>') : '';
  let html;
  if (S.paused) {
    html = head('采集已暂停', '不会产生事件，也不会更新统计') + '<div class="sec row"><span style="flex:1;font-size:13px;color:var(--ink-2)">恢复后会补齐暂停期间的会话。</span><button type="button" class="btn sm p" data-act="setPause">恢复采集</button></div>' + foot;
  } else if (attn.size) {
    html = head('需要关注', '10 月 1 日 周四', '<span class="bdg" style="background:var(--crit-bg);color:var(--crit)">' + attn.size + ' 件事</span>') +
      (attn.has('stuck') ? '<div class="sec col" style="gap:6px"><div class="row">' + ic('alert', 15, 'color:var(--crit)') + '<b style="font-size:13px">同一命令连续失败 4 次</b></div><div class="cap" style="font-size:12px">Codex · Surge 规则 · 15:02 开始</div><div class="mono" style="font-size:12px;padding:6px 8px;border-radius:6px;background:var(--sunken)">python gen_rules.py --publish</div><div style="font-size:12px;color:var(--ink-2)">可能原因：CDN token 过期（4 次输出里 3 次是 401）</div><div class="row" style="flex-wrap:wrap"><button type="button" class="btn sm p" data-act="popTerm">在终端中处理</button><button type="button" class="btn sm" data-act="popStuckSess">打开会话</button><button type="button" class="btn sm gh" data-act="popIgnore" data-k="stuck">忽略 1 小时</button></div></div>' : '') +
      (attn.has('ctx') ? '<div class="sec col" style="gap:6px"><div class="row">' + ic('gauge', 15, 'color:var(--warn)') + '<b style="font-size:13px">上下文即将压缩</b><span style="flex:1"></span><b class="mono" style="color:var(--warn)">78%</b></div><div class="cap" style="font-size:12px">Claude Code · latentskill · 审阅第 3 节</div>' + ctxBar(78) + '<div class="row" style="flex-wrap:wrap"><button type="button" class="btn sm p" data-act="hudTip">复制「先总结进度」提示语</button><button type="button" class="btn sm gh" data-act="popIgnore" data-k="ctx">忽略</button></div></div>' : '') +
      popLiveCard() + foot;
  } else if (simIdle()) {
    const y = available.filter((s) => s.d === 119); const ys = stats(y);
    const base = stats(sel({ range: 30, noExtra: true }));
    const byDay = {}; sel({ range: 30, noExtra: true }).forEach((s) => { byDay[s.d] = (byDay[s.d] || 0) + 1; });
    const perDay = Object.keys(byDay).length ? sum(Object.values(byDay), (v) => v) / Object.keys(byDay).length : 0;
    html = head('今天', '10 月 1 日 周四 · 还没有会话', doneBadge) + '<div class="sec col" style="gap:8px"><div class="row" style="justify-content:space-between"><b style="font-size:13px">昨天 · 9 月 30 日</b><span class="mono cap" style="font-size:11px">' + y.length + ' 会话 · ' + dur(sum(y, (s) => s.dur)) + '</span></div><div class="row" style="gap:18px;align-items:flex-start">' +
      popMetric('摩擦率', ys.fric, base.fric, (v) => f1(v) + '%', true) + popMetric('纠偏', ys.corr, base.n ? base.corr / base.n * Math.max(1, perDay) : 0, (v) => f1(v), true) + popMetric('完成率', ys.ok, base.ok, (v) => Math.round(v) + '%', false) +
      '</div><div class="cap" style="font-size:11px">基线 = 近 30 天均值' + (y.length ? '' : '；昨天没有会话') + '</div></div>' + week +
      '<div class="sec row" style="align-items:flex-start;gap:8px;background:var(--ai-bg)"><span class="aib" style="background:var(--surface)">AI</span><span style="font-size:12px;line-height:1.5;color:var(--ink-2)"><b style="color:var(--ink-1)">开始之前</b>：今天 Hackathon 的任务较大。先写好完成条件，你过去这样做时纠偏少了约 30%。</span></div>' + foot;
  } else {
    html = head('今天', '10 月 1 日 周四 · ' + today.length + ' 会话 · ' + dur(sum(today, (s) => s.live ? liveMin : s.dur)), doneBadge) + popLiveCard() + cxRow() + week + rec + foot;
  }
  el.innerHTML = html;
}
Object.assign(ACT, {
  popOpen: () => { S.pop = false; S.winGone = false; render(); },
  popTraj: () => { S.pop = false; ACT.openSession({ dataset: { id: LIVE_ID } }); },
  // jumping out of the panel closes it (BUG-82)
  popRec: (el) => { S.pop = false; ACT.openRec(el); },
  popSess: (el) => { S.pop = false; ACT.openSession(el); },
  popTerm: () => toast('已切换到对应的终端标签页（演示）'),
  popStuckSess: () => { const s = ALL.filter((x) => sourceEnabled(x) && x.p === 'surge' && x.a === 'cx' && !x.live).sort((a, b) => b.d - a.d)[0] || ALL.filter((x) => sourceEnabled(x) && x.p === 'surge').pop(); S.pop = false; if (s) { S.sess.sel = s.id; S.sess.mode = 'single'; } go('sessions'); },
  // clearing one item falls back to the other open item, else to the resting state (BUG-74 / BUG-41)
  popIgnore: (el) => { S.attn.delete(el.dataset.k); simSettle(); render(); toast(el.dataset.k === 'stuck' ? '已忽略 1 小时' : '已忽略'); }
});

/* ============ desktop widgets (desktop layer: under the window, never push it; hidden in full screen) ============
   Three sizes (S.wgSize, settings › 通用 or the widget's own ⋯ menu), all in the same 364px column:
     s  = the two squares (persona, today)
     m  = + this week (stacked daily bars by agent) + the top recommendation            (as published)
     l  = + the running session (context bar) + 7-day friction / completion trend */
const WG_SIZES = [['s', '小'], ['m', '中'], ['l', '大']];
function wgPair() { return typeof LV !== 'undefined' && LV.live ? [AG[0] ? AG[0].id : null, AG[1] ? AG[1].id : null] : ['cc', 'cx']; }
const wgC = (k) => (k && AGI[k] ? AGI[k].c : 'var(--h2)');
const wgN = (k) => (k && AGI[k] ? AGI[k].short : '—');
// The native widgets panel (?surface=widgets) always shows them: opening it from the menu is the request, whatever the
// in-window setting (S.widgets follows the window width there and would leave the panel blank).
const WG_SURFACE = /[?&]surface=widgets(&|$)/.test(location.search || '');
function renderWidgets() {
  const w = $('#widgets'); const on = WG_SURFACE || (S.widgets && !S.win.full);
  w.hidden = !on; if (!on) { w.innerHTML = ''; return; }
  const size = S.wgSize || 'm';
  const p = personaNow();
  const W7 = win(7); const L7 = sel({ range: 7, noExtra: true }), P7 = sel({ win: [W7[0] - 7, W7[1] - 7], noExtra: true });
  const s7 = stats(L7), sp = stats(P7);
  const T = popDay(); const today = ALL.filter((s) => s.d === T && S.agents.has(s.a) && sourceEnabled(s) && !S.excluded.has(s.id) && !(s.live && simIdle()));
  const live = liveSession();
  const liveMin = (Date.now() - S.live.t0) / 60000;
  // the two stacked agents: Claude Code / Codex in the demo; live = the two agents with the most sessions (AG is ordered by count)
  const K = wgPair(); const days = []; for (let d = W7[0]; d <= W7[1]; d++) { const xs = L7.filter((s) => s.d === d); days.push([d, xs.filter((s) => s.a === K[0]).length, xs.filter((s) => s.a === K[1]).length, xs.filter((s) => s.a !== K[0] && s.a !== K[1]).length]); }
  const mx = Math.max(1, ...days.map((x) => x[1] + x[2] + x[3]));
  const recs = visibleRecs().filter((r) => !S.installed.has(r.id)); const top = recs[0];
  const delta = sp.n ? Math.round((s7.n - sp.n) / sp.n * 100) : 0;
  const fricD = s7.fric - sp.fric;
  const menu = '<span class="wg-menu"><button type="button" class="ib" data-act="wgMenu" aria-label="小组件尺寸" data-tip="小组件尺寸">' + ic('more', 14) + '</button></span>';
  // stacked bars: 1px gaps between segments, only the top segment rounded (S-V06); weekday under each column, count on top
  const col = (x) => {
    const segs = [[x[3], 'var(--h2)'], [x[2], wgC(K[1])], [x[1], wgC(K[0])]].filter((s) => s[0]);
    const tot = x[1] + x[2] + x[3];
    return '<span class="wg-col" data-tip="' + md(x[0]) + ' 周' + WD[wd(x[0])] + '：' + wgN(K[0]) + ' ' + x[1] + ' · ' + wgN(K[1]) + ' ' + x[2] + ' · 其他 ' + x[3] + '"><b class="mono">' + (tot || '') + '</b><span class="wg-stack">' + segs.map((s) => '<i style="height:' + Math.max(3, s[0] / mx * 56).toFixed(1) + 'px;background:' + s[1] + '"></i>').join('') + '</span><span class="mono cap">' + WD[wd(x[0])] + '</span></span>';
  };
  // today by hour: one cell per hour, height = sessions started in that hour, colour = the first agent seen (fills the square)
  const byH = []; for (let h = 0; h < 24; h++) byH.push(today.filter((s) => s.h === h));
  const dayStrip = '<span class="wg-day" role="img" aria-label="今天每小时开始的会话数"><span class="wg-day-b">' + byH.map((xs, h) => '<i' + (xs.length ? ' class="on" style="height:' + (4 + Math.min(3, xs.length) * 4) + 'px;background:' + agent(xs[0].a).c + '"' : '') + ' data-tip="' + String(h).padStart(2, '0') + ':00 · ' + xs.length + ' 个会话"></i>').join('') + '</span><span class="wg-day-x mono"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></span></span>';
  const squares = '<div class="wg-row"><button type="button" class="wg sq" data-act="wgGo" data-r="persona"><span class="lbl">协作人格</span>' + (p.ok ? glyphSVG(p, 56) : '') + '<span><span class="tcode" style="display:block;font-size:26px;line-height:1;letter-spacing:.02em">' + (p.ok ? p.code : '—') + '</span><span style="font-size:12px;color:var(--ink-2)">' + (p.ok ? p.zh + ' · 置信度' + p.conf : '样本不足') + '</span></span></button>' +
    '<button type="button" class="wg sq" data-act="wgGo" data-r="sessions"><span class="lbl">今日</span><span><span class="mono" style="display:block;font-size:34px;font-weight:600;line-height:1">' + today.length + '</span><span style="font-size:12px;color:var(--ink-2)">会话 · ' + dur(sum(today, (s) => s.live ? liveMin : s.dur)) + '</span></span>' + dayStrip + '<span class="row" style="font-size:11px;gap:6px">' + (!live ? '<span class="cap">没有运行中的会话</span>' : '<span class="dot live" style="background:' + agent(live.a).c + '"></span>' + (S.numOnly ? '1 个运行中' : esc(sessProjName(live)) + ' · <span class="mono" data-live>' + liveElapsed() + '</span>')) + '</span></button></div>';
  const week = '<button type="button" class="wg wk" data-act="wgGo" data-r="overview"><span class="col" style="gap:4px;min-width:0"><span class="lbl">本周</span><span class="mono" style="font-size:34px;font-weight:600;line-height:1">' + s7.n + '</span><span style="font-size:12px;color:var(--ink-2)">会话 · <span class="mono" style="color:var(--ink-3)">' + (delta >= 0 ? '▲ ' : '▼ ') + Math.abs(delta) + '%</span></span><span style="font-size:12px;color:var(--ink-2)">摩擦率 <b class="mono">' + f1(s7.fric) + '%</b> <span class="mono" style="white-space:nowrap;color:' + (Math.abs(fricD) < 0.05 ? 'var(--ink-3)' : fricD < 0 ? 'var(--good)' : 'var(--crit)') + '">' + (Math.abs(fricD) < 0.05 ? '＝' : fricD < 0 ? '▼' : '▲') + f1(Math.abs(fricD)) + 'pt</span><span class="cap"> vs 上周</span></span></span><span class="col" style="gap:5px;min-width:0"><span class="wg-week" role="img" aria-label="近 7 天每天的会话数，按 Agent 堆叠">' + days.map(col).join('') + '</span><span class="row cap" style="font-size:10px;gap:6px">' + K.filter((k) => k).map((k) => '<span class="row" style="gap:3px"><i class="dot" style="width:6px;height:6px;background:' + wgC(k) + '"></i>' + esc(wgN(k)) + '</span>').join('') + '<span class="row" style="gap:3px"><i class="dot" style="width:6px;height:6px;background:var(--h2)"></i>其他</span></span></span></button>';
  const rec = top ? '<button type="button" class="wg" data-act="wgRec" data-id="' + top.id + '" style="display:flex;flex-direction:column;gap:6px;align-items:flex-start"><span class="lbl">本周最值得做</span><span style="font-size:15px;font-weight:600;line-height:1.35">' + esc(top.title) + '</span><span class="cap">' + top.type + ' · ' + LEVELS[top.lvl] + ' · ' + top.gain + '</span><span class="row" style="width:100%;justify-content:space-between;margin-top:4px"><span class="cap">还有 ' + Math.max(0, recs.length - 1) + ' 条建议</span><span class="btn sm">预览</span></span></button>' : '';
  // large: the running session with its context bar, then two 7-day sparklines against the previous week
  let big = '';
  if (size === 'l') {
    const byDay = (L, d0, fn) => { const o = []; for (let d = d0; d < d0 + 7; d++) { const xs = L.filter((s) => s.d === d); o.push(xs.length ? fn(stats(xs)) : null); } return o; };
    const fr = byDay(L7, W7[0], (st) => st.fric), ok = byDay(L7, W7[0], (st) => st.ok);
    const trend = (label, vals, cur, prev, fmtv, goodDown) => { const same = Math.abs(cur - prev) < 0.05, up = cur > prev; const colr = same ? 'var(--ink-3)' : (up === !!goodDown) ? 'var(--crit)' : 'var(--good)';
      return '<span class="wg-trend"><span class="lbl">' + label + '</span><span class="row" style="gap:8px;align-items:baseline"><b class="mono" style="font-size:20px;font-weight:600">' + fmtv(cur) + '</b><span class="mono" style="font-size:11px;color:' + colr + '">' + (same ? '＝' : up ? '▲' : '▼') + ' 上周 ' + fmtv(prev) + '</span></span>' + VZ.spark(vals.map((v) => v == null ? 0 : v), { w: 150, h: 24, label: label + '，近 7 天每天的值' }) + '</span>'; };
    big = (live ? '<button type="button" class="wg" data-act="wgLive" style="display:flex;flex-direction:column;gap:8px;align-items:stretch;text-align:left"><span class="row"><span class="dot live" style="background:' + agent(live.a).c + '"></span><span class="lbl" style="flex:1">运行中 · ' + esc(agent(live.a).name) + '</span><span class="mono" style="font-size:12px" data-live>' + liveElapsed() + '</span></span><span style="font-size:14px;font-weight:600;line-height:1.35">' + (S.numOnly ? '1 个运行中的会话' : esc(live.title)) + '</span>' + ctxBar(S.live.ctx) + '<span class="row cap" style="font-size:11px;gap:10px"><span>工具 <b class="mono" data-livetools>' + S.live.tools + '</b></span><span class="mono" data-hudtool style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + HUD_TOOLS[HUD_T % HUD_TOOLS.length] + '</span></span></button>' : '') +
      '<button type="button" class="wg" data-act="wgGo" data-r="overview" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;text-align:left">' + trend('摩擦率', fr, s7.fric, sp.fric, (v) => f1(v) + '%', true) + trend('完成率', ok, s7.ok, sp.ok, (v) => Math.round(v) + '%', false) + '</button>';
  }
  w.innerHTML = menu + squares + (size === 's' ? '' : week + big + rec);
  w.dataset.size = size;
}
Object.assign(ACT, {
  wgGo: (el) => go(el.dataset.r),
  wgRec: (el) => ACT.openRec(el),
  wgLive: () => ACT.openSession({ dataset: { id: LIVE_ID } }),
  wgSize: (el) => { S.wgSize = el.dataset.v; store.set('wgSize', S.wgSize); render(); },
  wgMenu: (el) => openDD(el, [{ h: '小组件尺寸' }].concat(WG_SIZES.map((x) => ({ t: x[1], on: (S.wgSize || 'm') === x[0], v: x[0] }))), (v) => ACT.wgSize({ dataset: { v } }))
});

/* ============ live binding (slice 8): surfaces · 菜单栏面板 · HUD · 桌面小组件 · A3 会话操作 · A4 调用明细 · 导出 ============
   Nothing gets a new layout: the polished panel / HUD / widgets / pages render as in the demo, only their data source changes.
   - Surfaces (any mode): /app?surface=panel|hud|widgets renders only that component (body.native.surface-<x>, transparent),
     reports its height with resizeSurface and sends navigation to the main window with openMain{route}.
   - realtime (/v1/analytics/realtime + stream) drives S.simBase / S.attn / S.waitOpen → simSettle, S.live.{t0, ctx, tools},
     HUD_TOOLS, liveBuckets(); the hook functions of 60 / 61 / 62 (popDate, hudSess, hudOther, …) name the real sessions.
     Without the realtime route nothing runs: the HUD stays hidden and the panel shows the calm state (no demo session).
   - panel: /v1/shell/popover (date, today, opening line, top rec, attention); week bars and yesterday come from the spine.
   - A3: 在 X 中继续 → /resume, 更多 › 不计入分析 / 恢复 → /exclude, 在 Finder 中显示日志 / 在原始日志中打开 → /source_location
     → reveal; A4: an expanded tool row lists its real calls (/v1/analytics/tool_calls).
   - export: report .md, share card .png → ORBIT.native.request('save'); a missing route → honest toast. */
const TLO = { started: false, off: false, d: null, doneUid: null, tc: {}, share: null };
const TLO_REASON = { test: '测试会话', private: '隐私', duplicate: '重复', other: '其他' };
const tloAg = (s) => agent(LV.agentOf(s && s.agent).id);
const tloCmd = (s) => (s.approval && s.approval.command) || s.current_tool || '—';
const tloWait = (s) => Math.max(1, Math.round(((s.approval && s.approval.wait_s) || s.running_s || 0) / 60));
const tloMD = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); const d = m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : new Date(); return (d.getUTCMonth() + 1) + ' 月 ' + d.getUTCDate() + ' 日 周' + '日一二三四五六'[d.getUTCDay()]; };
function tloRes(path, query) { const r = TL.resource(path, { query: query || null }); if (r.dirty && !r.loading) TL.load(r); return r; }
// realtime session → a row the demo renderers can name (agent colour / name, project, title)
function tloRow(s) {
  if (!s) return null;
  return { id: s.session_uid, a: LV.agentOf(s.agent).id, p: s.project_id || '_none', pname: s.project || '—', title: s.title || '（无标题）', live: true,
    dur: Math.round((s.running_s || 0) / 60), tools: ((s.lanes && s.lanes.tool) || []).length, rt: s };
}
// open a session in the main window (from a surface: openMain)
function tloOpen(uid) {
  if (!uid) return;
  S.pop = false; S.hud.open = false;
  if (ORBIT.native.surface) { ORBIT.native.post('openMain', { route: 'sessions/' + uid }); return; }
  if (BYID[uid]) { S.sess.sel = uid; S.sess.mode = 'single'; }
  go('sessions');
}

/* ---------- surfaces: ?surface=panel | hud | widgets ---------- */
const HUD_PAD = { t: 8, x: 12, b: 16 };   // HUD surface padding = room for the pill / card shadow (0 4px 12px)
(function surfaces() {
  const sf = ORBIT.native.surface; if (!sf) return;
  document.body.classList.add('native', 'surface', 'surface-' + sf);
  document.documentElement.classList.add('surface');
  const keep = { panel: '#pop', hud: '#hud', widgets: '#widgets' }[sf];
  const st = document.createElement('style');
  st.textContent = 'html.surface,body.surface,body.surface .desk{background:transparent!important;overflow:hidden;height:auto}' +
    'body.surface .desk>.wall,body.surface #mbar,body.surface #win,body.surface #set,body.surface .desk>:is(#pop,#hud,#widgets):not(' + keep + '){display:none!important}' +
    'body.surface ' + keep + '{position:relative!important;inset:auto!important;left:auto!important;right:auto!important;top:auto!important;bottom:auto!important;margin:0}' +
    'body.surface-panel #pop{width:100%;max-height:none;border-radius:12px;animation:none}' +
    // the panel is exactly the HUD box: the padding holds the whole shadow (8 top, 12 sides, 16 bottom), so the window edge never
    // clips it into a grey rectangle around the pill (F22); the shadow is a tighter version of the in-window one for that reason
    'body.surface-hud #hud{align-items:flex-end!important;flex-direction:column!important;padding:' + HUD_PAD.t + 'px ' + HUD_PAD.x + 'px ' + HUD_PAD.b + 'px}' +
    'body.surface-hud #hud>:is(.pill,.hcard){box-shadow:0 4px 12px rgba(0,0,0,.26),inset 0 0 0 .5px rgba(255,255,255,.12)}' +
    // intrinsic widths (not viewport-relative): the reported width must not shrink with the panel it resizes
    // 496 + 2*12 = 520 = the widest HUD panel Orbit.swift allows (resizeSurface clamps the width to 120…520)
    'body.surface-hud #hud>.pill{width:max-content;max-width:' + (520 - 2 * HUD_PAD.x) + 'px}body.surface-hud .hcard{width:380px}' +
    // widgets: the 8px padding (+ 8 below, see report) holds a 0 2px 8px card shadow; the in-window 0 10px 30px would be
    // clipped by the panel edge into the same faint rectangle as the HUD's (F22)
    'body.surface-widgets #widgets{width:364px;padding:8px}body.surface-widgets #widgets .wg{box-shadow:0 2px 8px rgba(0,0,0,.14),0 0 0 .5px var(--wg-edge)}';
  document.head.appendChild(st);
  S.winGone = true; S.pop = sf === 'panel'; S.widgets = sf === 'widgets'; S.hud.show = sf === 'hud';
  const el = () => $(keep);
  let lastH = 0, lastW = 0;
  // the HUD also reports the pill / card width: its NSPanel shrinks to it, so no wide transparent margin takes other windows'
  // clicks. Trade-off: the padding that holds the shadow (8 top, 12 sides, 16 bottom) is still part of the panel and takes
  // clicks meant for windows underneath; that thin band is the price of drawing the shadow without clipping it (F22)
  function report() {
    const e = el(); if (!e) return;
    const r = e.getBoundingClientRect();
    // HUD: #hud's own box (its padding already holds the shadow); widgets: + 8 below for the last card's shadow
    const h = Math.ceil(e.hidden ? 0 : r.height + (sf === 'widgets' ? 8 : 0));
    let w = 0;
    if (sf === 'hud' && !e.hidden) w = Math.ceil(Math.max(0, ...Array.from(e.children).map((k) => k.getBoundingClientRect().width)) + 2 * HUD_PAD.x);
    if (h !== lastH || w !== lastW) { lastH = h; lastW = w; ORBIT.native.post('resizeSurface', w ? { height: h, width: w } : { height: h }); }
  }
  hudPlace = function () { /* the host window is the position */ };
  popPlace = function () { /* the NSPopover is the position */ };
  const base = render;
  render = function () {
    S.winGone = true;
    if (sf === 'panel') { S.pop = true; renderPop(); }
    else if (sf === 'hud') { S.hud.show = true; renderHud(); }
    else { S.widgets = true; S.win.full = false; renderWidgets(); }
    requestAnimationFrame(report);
  };
  render.base = base;
  // navigation leaves the surface: the main window opens (orbit:command route) and this surface stays as it is
  const openMain = (route) => { ORBIT.native.post('openMain', route ? { route } : {}); return false; };
  go = function (route) { openMain(route); };
  openSettings = function (tab) { openMain('settings' + (tab ? '/' + tab : '')); };
  ACT.openSession = (e) => openMain('sessions/' + e.dataset.id);
  ACT.openRec = (e) => openMain('recs/' + e.dataset.id);
  ACT.popOpen = () => openMain(null);
  if (typeof ResizeObserver === 'function') new ResizeObserver(report).observe(el());
})();
// main window: deep routes sent by a surface (openMain → orbit:command {cmd:'route', route:'sessions/<uid>' | 'recs/<id>'}).
// Plain pages and settings/<tab> are LVN.command's (95-live-native.js): handling them here too ran go() twice and, across
// editions, the second go() undid the edition switch.
if (!ORBIT.native.surface) ORBIT.native.onCommand((c) => {
  if (c.cmd !== 'route' || !c.route) return;
  const m = /^(sessions|recs)\/(.+)$/.exec(c.route);
  if (!m) return;
  S.pop = false; S.winGone = false;
  if (m[1] === 'sessions') tloOpen(m[2]);
  else if (RECI[m[2]]) ACT.openRec({ dataset: { id: m[2] } }); else go('recs');
});

if (LV.live) {
  if (typeof TLS_KIND !== 'undefined') TLS_KIND.done.push('just_finished');   // realtime's finished session → 完成 channel
  S.simBase = 'idle'; S.sim = 'idle'; S.hudSim = 'idle';                       // nothing runs until the snapshot says so

  /* ---------- realtime → the demo's ambient state ---------- */
  function tloStart() {
    if (TLO.started) return; TLO.started = true;
    TL.ops.realtime().then(() => TL.ops.startStream(), (e) => {
      if (e && (e.status === 404 || e.status === 501)) { TLO.off = true; render(); return; }   // no realtime route: stay calm
      setTimeout(() => { TLO.started = false; tloStart(); }, 15000);
    });
  }
  function tloApply() {
    if (TLO.off || !TL.ops.rt) { TLO.d = null; return; }
    const d = TLO.d = TL.ops.derive();
    // collection paused: realtime answers status paused / reason collection_paused with no sessions → the panel, HUD and
    // widgets show 采集已暂停 with 恢复采集 (setPause → POST /v1/platform/collection/resume)
    const rt = TL.ops.rt; const paused = rt.reason === 'collection_paused' || d.paused;
    if (paused) { TLO.paused = true; S.paused = true; }
    else if (TLO.paused) { TLO.paused = false; if (TL.collection !== 'paused') S.paused = false; }
    S.simBase = d.active.length ? 'running' : 'idle';
    if (d.failing.length) S.attn.add('stuck'); else S.attn.delete('stuck');
    if (d.ctx.length) S.attn.add('ctx'); else S.attn.delete('ctx');
    S.waitOpen = d.waiting.length > 0;
    if (d.finished.length) TLO.doneUid = d.finished[0].session_uid;
    simSettle();
    HUD_TOOLS.length = 0; HUD_TOOLS.push(d.primary ? (d.primary.current_tool || '—') : '—');
  }
  const H = OrbitLive.ops;
  ['t0', 'ctx', 'tools'].forEach((k) => {
    let v = S.live[k];
    Object.defineProperty(S.live, k, {
      configurable: true, enumerable: true, set: (x) => { v = x; },
      get: () => {
        const p = TLO.d && TLO.d.primary; if (!p) return k === 't0' ? Date.now() : k === 'ctx' ? null : 0;
        if (k === 't0') return p.since || v;
        if (k === 'ctx') return H.rtCtxPct(p); // null = unknown (ctxBar shows 「—」), never a made-up 0%
        return ((p.lanes && p.lanes.tool) || []).length;
      }
    });
  });
  liveSession = function () { const p = TLO.d && TLO.d.primary; return p && !S.paused ? tloRow(p) : null; };
  hudSess = function () { return tloRow(TLO.d && TLO.d.primary) || { a: '—', pname: '—', title: '—' }; };
  liveBuckets = function (minutes, bucketSec) {
    const p = TLO.d && TLO.d.primary; const b = H.rtBuckets(p, Date.now(), minutes, bucketSec);
    return { b, n: b.length, from: 0, now: minutes };
  };
  const tloCtxBar = ctxBar;
  ctxBar = function (pct, opt) { const p = TLO.d && TLO.d.primary; if (p && (!opt || opt.th == null)) opt = Object.assign({}, opt, { th: H.rtCtxTh(p) }); return tloCtxBar(pct, opt); };

  /* ---------- menu-bar panel: /v1/shell/popover + realtime ---------- */
  const POP = '/v1/shell/popover';
  // read only while the panel is shown (main window or the menubar surface); the widgets use the snapshot and the spine
  const popData = () => { if (!S.pop && ORBIT.native.surface !== 'panel') { const r = TL.resource(POP); return r.data || null; } const r = tloRes(POP); return r.data || null; };
  const todayIso = () => lvToday();
  popDate = function () { const d = popData(); return tloMD((d && d.today && d.today.date) || todayIso()); };
  popYest = function () { const d = popData(); const iso = d && d.yesterday && d.yesterday.date; if (iso) return tloMD(iso).replace(/ 周.$/, ''); const t = lvUtc(todayIso()) - 864e5; return tloMD(new Date(t).toISOString()).replace(/ 周.$/, ''); };
  popOpening = function () {
    const d = popData(); const o = d && d.opening; const t = o && (typeof o === 'string' ? o : o.text || o.line || o.body); if (!t) return '';
    // AI 徽标与紫色底只给模型写的句子；/v1/shell/popover 的开场提示是规则模板（basis: rule），标「规则」
    const ai = o.basis === 'ai' || o.source === 'ai';
    return '<div class="sec row" data-tl="opening" data-basis="' + (ai ? 'ai' : 'rule') + '" style="align-items:flex-start;gap:8px' + (ai ? ';background:var(--ai-bg)' : '') + '">' + (ai ? '<span class="aib" style="background:var(--surface)">AI</span>' : '<span class="bdg" title="按最近的问题与纠偏数据套用规则生成，未调用模型">规则</span>') + '<span style="font-size:12px;line-height:1.5;color:var(--ink-2)">' + (o.title ? '<b style="color:var(--ink-1)">' + esc(o.title) + '</b>：' : '') + esc(t) + '</span></div>';
  };
  popLiveCard = function () {
    const d = TLO.d; const s = d && d.primary; if (!s || S.paused) return '';
    const ag = tloAg(s);
    return '<div class="sec col" style="gap:6px" data-tl="rt-live"><div class="row"><span class="dot live" style="background:' + ag.c + '"></span><b style="font-size:13px">' + esc(ag.name) + '</b><span class="cap">· ' + esc(s.project || '—') + '</span><span style="flex:1"></span><span class="mono" style="font-size:12px" data-live>' + liveElapsed() + '</span></div><div style="font-size:13px;font-weight:600">' + esc(s.title || '（无标题）') + '</div><div class="row cap" style="font-size:12px;min-width:0"><span class="aib">进行中</span><span class="mono" data-hudtool style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(HUD_TOOLS[0] || '—') + '</span><span style="flex:1"></span><span class="mono" style="font-size:11px">工具 <b data-livetools>' + S.live.tools + '</b></span></div>' +
      ctxBar(S.live.ctx) +
      '<div class="row" style="margin-top:4px"><button type="button" class="btn sm" data-act="popTraj">查看轨迹</button><button type="button" class="btn sm gh" data-act="hudMute">' + (S.hud.mute ? '恢复提醒' : '暂停提醒') + '</button></div></div>';
  };
  const secOf = (sel) => { const b = $('#pop ' + sel); return b ? b.closest('.sec') : null; };
  const rtState = (s) => s.state === 'just_finished' ? '刚刚完成 ✓' : s.state === 'failing' ? '连续失败' : s.state === 'awaiting_approval' ? '等你确认' : '运行中 ' + Math.round((s.running_s || 0) / 60) + 'm';
  const otherRow = (s) => { const ag = tloAg(s);
    return '<button type="button" class="sec row" data-act="tloSess" data-id="' + esc(s.session_uid) + '" data-tl="rt-other" style="width:100%;border:0;border-top:1px solid var(--hair);background:none;text-align:left;font-size:12px"><span class="dot" style="background:' + ag.c + '"></span><span style="flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(ag.short + ' · ' + (s.project || '—') + ' · ' + (s.title || '（无标题）')) + '</span><span class="mono cap" style="font-size:11px">' + rtState(s) + '</span></button>'; };
  const recSec = (r) => '<div class="sec row" data-tl="pop-rec" style="gap:10px"><span style="width:28px;height:28px;flex:none;border-radius:7px;background:var(--sunken);display:grid;place-items:center">' + ic('spark', 15) + '</span><div style="flex:1;min-width:0"><div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(r.title || '—') + '</div><div class="cap" style="font-size:11px">本周最值得做' + (r.gain ? ' · ' + esc(r.gain) : '') + '</div></div><button type="button" class="btn sm" data-act="popRec" data-id="' + esc(r.candidate_id || '') + '">预览</button></div>';
  const tloPopBase = renderPop;
  // 今日会话 for the panel and the widget alike: the popover's full-table count (shell main_where, the client's day) is the
  // authority; realtime sessions_started only comes from the ≤200 most recent tails, so it may only raise a stale popover count
  const todaySessions = (pv, d) => {
    const a = pv && pv.today && pv.today.sessions != null ? pv.today.sessions : null;
    const b = d && d.today && d.today.sessions_started != null ? d.today.sessions_started : null;
    return a == null ? b : b == null ? a : Math.max(a, b);
  };
  renderPop = function () {
    tloPopBase();
    const d = TLO.d; const pv = popData();
    const meta = $('#pop .mono.cap');
    if (meta && pv && pv.today && !S.paused && !S.attn.size) {
      const t = pv.today; const n = todaySessions(pv, d);
      meta.textContent = popDate() + ' · ' + (n ? TLU.num(n) + ' 会话' + (t.duration_s ? ' · ' + dur(Math.round(t.duration_s / 60)) : '') : dataBusy() ? busyMeta() : '还没有会话');
    }
    // the top recommendation: the menubar slate (97-live-recs recTop('menubar')); without one, the popover's top_rec
    if (!$('#pop [data-act="popRec"]') && pv && pv.top_rec && pv.top_rec.title && !S.paused && !S.attn.size && !simIdle()) { const f = $('#pop .sec:last-child'); if (f) f.insertAdjacentHTML('beforebegin', recSec(pv.top_rec)); }
    // the demo's「另一个会话」row → the next live session (or the one that just finished)
    const other = $('#pop [data-act="popSess"][data-id="sess-1001-0903"]');
    if (other) { const s = d && (d.others.find((x) => x.state === 'running') || d.finished[0]); if (s) other.outerHTML = otherRow(s); else other.remove(); }
    const cxs = secOf('[data-act="hudGo"][data-v="waiting"]');
    const w = d && d.waiting[0];
    if (cxs && !w) cxs.remove();
    else if (cxs && w) {
      cxs.setAttribute('data-tl', 'rt-waiting');
      cxs.innerHTML = '<div class="row"><span style="width:9px;height:9px;border-radius:2px;background:var(--warn-m)"></span><b style="font-size:13px">' + esc(tloAg(w).name + ' · ' + (w.project || '—')) + '</b><span style="flex:1"></span><span class="cap" style="font-size:11px">等你确认 · ' + tloWait(w) + ' 分钟</span></div><div class="mono" style="font-size:12px;padding:6px 8px;border-radius:6px;background:var(--surface)">' + esc(tloCmd(w)) + '</div><div class="row" style="flex-wrap:wrap"><button type="button" class="btn sm p" data-act="hudGo" data-v="waiting">在终端中处理</button><span class="cap" style="font-size:11px">Orbit 不会代你批准</span></div>';
    }
    const f = d && d.failing[0]; const stuck = secOf('[data-act="popStuckSess"]');
    if (stuck && !f) stuck.remove();
    else if (stuck && f) {
      const fx = f.failure || {}; const ag = tloAg(f);
      stuck.setAttribute('data-tl', 'rt-failing');
      stuck.innerHTML = '<div class="row">' + ic('alert', 15, 'color:var(--crit)') + '<b style="font-size:13px">同一命令连续失败 ' + TLU.num(fx.n) + ' 次</b></div><div class="cap" style="font-size:12px">' + esc(ag.short + ' · ' + (f.project || '—')) + ' · ' + TLU.hm(f.since) + ' 开始</div><div class="mono" style="font-size:12px;padding:6px 8px;border-radius:6px;background:var(--sunken)">' + esc(fx.command_head || f.current_tool || '—') + '</div>' + (fx.cause_hint ? '<div style="font-size:12px;color:var(--ink-2)">可能原因：' + esc(fx.cause_hint) + '</div>' : '') + '<div class="row" style="flex-wrap:wrap"><button type="button" class="btn sm p" data-act="popTerm">在终端中处理</button><button type="button" class="btn sm" data-act="tloSess" data-id="' + esc(f.session_uid) + '">打开会话</button><button type="button" class="btn sm gh" data-act="popIgnore" data-k="stuck">忽略 1 小时</button></div>';
    }
    const c = d && d.ctx[0]; const cs = secOf('[data-act="popIgnore"][data-k="ctx"]');
    if (cs && !c) cs.remove();
    else if (cs && c) {
      const pct = H.rtCtxPct(c);
      cs.setAttribute('data-tl', 'rt-ctx');
      cs.innerHTML = '<div class="row">' + ic('gauge', 15, 'color:var(--warn)') + '<b style="font-size:13px">上下文即将压缩</b><span style="flex:1"></span><b class="mono" style="color:var(--warn)">' + (pct == null ? '—' : pct + '%') + '</b></div><div class="cap" style="font-size:12px">' + esc(tloAg(c).name + ' · ' + (c.project || '—') + ' · ' + (c.title || '')) + '</div>' + tloCtxBar(pct, { th: H.rtCtxTh(c) }) + '<div class="row" style="flex-wrap:wrap"><button type="button" class="btn sm p" data-act="hudTip">复制「先总结进度」提示语</button><button type="button" class="btn sm gh" data-act="popIgnore" data-k="ctx">忽略</button></div>';
    }
    const done = $('#pop [data-act="popSess"][data-id="' + DONE_ID + '"]');
    if (done) { if (TLO.doneUid) { const s = d && d.finished[0]; done.dataset.act = 'tloSess'; done.dataset.id = TLO.doneUid; done.dataset.tip = s && s.title || '刚刚完成的会话'; } else done.remove(); }
  };

  /* ---------- HUD ---------- */
  hudOther = function () {
    const d = TLO.d; const xs = d ? d.others.concat(d.finished).slice(0, 3) : []; if (!xs.length) return '';
    return '<div class="col" style="gap:6px"><span style="font-size:11px;color:var(--hud-ink-3)">另外 ' + xs.length + ' 个会话</span>' + xs.map((s) => {
      const a = tloAg(s); const act = s.state === 'awaiting_approval' ? '<button type="button" class="hb" data-act="hudGo" data-v="waiting">去处理</button>' : s.state === 'failing' ? '<button type="button" class="hb" data-act="hudGo" data-v="stuck">查看原因</button>' : '<button type="button" class="hg" data-act="tloSess" data-id="' + esc(s.session_uid) + '">打开轨迹</button>';
      const st = s.state === 'awaiting_approval' ? ' · <span style="color:#f3b843">等你确认 ' + tloWait(s) + ' 分钟</span>' : s.state === 'failing' ? ' · <span style="color:#ff7d74">连续失败</span>' : s.state === 'just_finished' ? ' · 刚刚完成' : ' · 进行中';
      return '<div class="row" style="font-size:12px"><span class="dot" style="background:' + a.c + '"></span><span style="flex:1;min-width:0">' + esc(a.short + ' · ' + (s.project || '—')) + st + '</span>' + act + '</div>';
    }).join('') + '</div>';
  };
  hudPlus = function () { const n = TLO.d ? TLO.d.others.length : 0; return n ? '<span class="mono" style="font-size:11px;color:var(--hud-ink-3)" data-tip="另有 ' + n + ' 个会话在进行">+' + n + '</span>' : ''; };
  const tloPill = hudPill;
  hudPill = function () {
    const d = TLO.d; const st = S.hudSim;
    if (d && st === 'stuck' && d.failing[0]) { const s = d.failing[0]; return ic('alert', 16, 'color:#ff7d74') + '<b>同一命令失败 ' + TLU.num((s.failure || {}).n) + ' 次</b><span style="color:var(--hud-ink-3);font-size:12px">' + esc(tloAg(s).short + ' · ' + (s.project || '—')) + '</span><button type="button" class="hb" data-act="hudGo" data-v="stuck">查看原因</button>'; }
    if (d && st === 'waiting' && d.waiting[0]) { const s = d.waiting[0]; return '<span style="width:10px;height:10px;border-radius:2px;background:#f3b843;flex:none"></span><b>' + esc(tloAg(s).short) + '</b><span style="color:var(--hud-ink-2)">请求执行 ' + esc(tloCmd(s)) + '</span><button type="button" class="hb" data-act="hudGo" data-v="waiting">去处理</button>'; }
    if (d && st === 'done' && d.finished[0]) { const s = d.finished[0]; return ic('okc', 16, 'color:#5dd08a') + '<b>完成</b><span style="color:var(--hud-ink-2)">' + esc(s.project || s.title || '') + '</span><button type="button" class="hb" data-act="hudTraj">查看</button>'; }
    if (d && st === 'ctx' && d.ctx[0]) { const s = d.ctx[0]; return ic('gauge', 16, 'color:#f3b843') + '<b>上下文 ' + (H.rtCtxPct(s) == null ? '—' : H.rtCtxPct(s) + '%') + '</b><span style="color:var(--hud-ink-2)">' + esc(s.project || '—') + ' 即将压缩</span><button type="button" class="hb" data-act="hudTip">复制提示语</button>'; }
    return d && d.primary ? tloPill().replace(/<span data-hudtool([^>]*)>[^<]*<\/span>/, (m, a) => '<span data-hudtool' + a + '>' + esc(HUD_TOOLS[0] || '—') + '</span>') : '';
  };
  const tloHud = renderHud;
  const pausedPill = () => '<div class="pill" id="hudPill" role="button" tabindex="0" aria-expanded="false" aria-label="悬浮组件" data-tl="rt-paused"><span class="dot" style="width:9px;height:9px;background:var(--hud-ink-3)"></span><b>采集已暂停</b><span style="color:var(--hud-ink-2)">不会产生事件，也不会更新统计</span><button type="button" class="hb" data-act="setPause">恢复采集</button></div>';
  renderHud = function () {
    const d = TLO.d;
    if (S.paused && S.hud.show && LV.state !== 'connecting') {
      const h = $('#hud'); S.hud.open = false; h.hidden = false; h.innerHTML = pausedPill();
      if (!ORBIT.native.surface) hudPlace();
      return;
    }
    if (!d || !d.primary && !(S.hudSim === 'done' && d.finished[0])) {
      const h = $('#hud');
      // the HUD surface (its own NSPanel, shown by default) keeps the pill in its calm form instead of an empty window
      if (ORBIT.native.surface === 'hud' && S.hud.show && LV.state !== 'connecting') {
        S.hud.open = false; h.hidden = false;
        h.innerHTML = '<div class="pill" id="hudPill" role="button" tabindex="0" aria-expanded="false" aria-label="悬浮组件" data-tl="rt-calm"><span class="dot" style="width:9px;height:9px;background:var(--hud-ink-3)"></span><b>Orbit</b><span style="color:var(--hud-ink-2)">' + (TLO.off ? '实时状态暂不可用' : '没有进行中的会话') + '</span><button type="button" class="hg" data-act="popOpen">打开 Orbit</button></div>';
        return;
      }
      h.hidden = true; h.innerHTML = ''; return;
    }
    if (!d.primary && S.hud.open) S.hud.open = false;
    tloHud();
    const c = $('#hud .hcard'); if (c) c.setAttribute('data-tl', 'rt-hud');
  };

  /* ---------- desktop widgets: today from the snapshot ---------- */
  const tloWg = renderWidgets;
  renderWidgets = function () {
    tloWg();
    const d = TLO.d; const pv = TL.resource(POP).data || null;
    const sq = $('#widgets [data-act="wgGo"][data-r="sessions"]'); if (!sq) return;
    if (S.paused) {
      const row = sq.closest('.wg-row');
      if (row && !$('#widgets [data-tl="rt-paused"]')) row.insertAdjacentHTML('beforebegin', '<button type="button" class="wg" data-act="setPause" data-tl="rt-paused" style="display:flex;align-items:center;gap:10px;text-align:left"><span class="col" style="gap:2px;flex:1;min-width:0"><span class="lbl">采集已暂停</span><span style="font-size:12px;color:var(--ink-2)">不会产生事件，也不会更新统计</span></span><span class="btn sm p">恢复采集</span></button>');
    }
    const n = todaySessions(pv, d);
    const big = sq.querySelector('.mono'); if (big && n != null) big.textContent = TLU.num(n);
    const sub = big && big.nextElementSibling; if (sub && d && d.today) sub.textContent = '会话 · 今天已结束 ' + TLU.num(d.today.sessions_finished);
  };

  /* ---------- actions on live sessions ---------- */
  const wrap = (name, fn) => { const base = ACT[name]; ACT[name] = (el, ev) => fn(base, el, ev); };
  const sessOf = (k) => { const d = TLO.d; return d ? (k === 'stuck' ? d.failing[0] : k === 'ctx' ? d.ctx[0] : k === 'waiting' ? d.waiting[0] : null) : null; };
  ACT.popTraj = () => { const p = TLO.d && TLO.d.primary; if (p) tloOpen(p.session_uid); };
  ACT.wgLive = () => { const p = TLO.d && TLO.d.primary; if (p) tloOpen(p.session_uid); };
  ACT.popStuckSess = () => { const s = sessOf('stuck'); if (s) tloOpen(s.session_uid); };
  ACT.hudTraj = () => {
    const d = TLO.d; S.hud.open = false;
    const done = (S.hudSim === 'done' || S.sim === 'done') && TLO.doneUid; if (done) simClear('done');
    tloOpen(done ? TLO.doneUid : d && d.primary && d.primary.session_uid);
  };
  ACT.popTerm = () => { const s = sessOf('stuck'); toast(s ? '到 ' + tloAg(s).name + ' 所在的终端里处理；Orbit 不会代你执行命令' : '没有需要处理的命令'); };
  wrap('hudGo', (base, el, ev) => {
    const s = sessOf(el.dataset.v); if (!s || el.dataset.v !== 'waiting') return base(el, ev);
    simClear('waiting'); render(); toast('到 ' + tloAg(s).name + ' 所在的终端里确认「' + tloCmd(s) + '」；批准仍由你完成');
  });
  wrap('popIgnore', (base, el, ev) => {
    const s = sessOf(el.dataset.k); if (!s) return base(el, ev);
    TL.ops.dismiss(s.session_uid, 3600).catch((e) => { if (!TL.unavailable(e)) toast('忽略失败：' + (e.message || e.code)); });
    base(el, ev);
  });
  wrap('popRec', (base, el, ev) => { if (RECI[el.dataset.id]) return base(el, ev); S.pop = false; go('recs'); });
  ACT.tloSess = (el) => tloOpen(el.dataset.id);

  /* ---------- A3: excluded sessions stay listed (as in the demo), resume / exclude / raw log on the gateway ---------- */
  const tloHydrate = LV.hydrate;
  LV.hydrate = function (spine) {
    const rows = spine.rows || []; const ex = rows.filter((r) => r.excluded);
    tloHydrate(Object.assign({}, spine, { rows: rows.map((r) => (r.excluded ? Object.assign({}, r, { excluded: false }) : r)) }));
    LV.excluded = ex;
    S.excluded = new Set(ex.map((r) => r.id).filter((id) => BYID[id]));
  };
  const opErr = (what) => (e) => toast(TL.unavailable(e) ? '本地服务暂不支持' + what : what + '失败：' + (e.message || e.code));
  const selS = () => BYID[S.sess.sel];
  ACT.resume = () => {
    const s = selS(); if (!s) return; const ag = agent(s.a);
    TL.ops.resume(s.id).then((d) => {
      const c = (d.commands || [])[0];
      if (!d.available || !c) { toast(H.RESUME_OFF[d.disabled_reason] || '暂时不能继续这个会话'); return; }
      openModal(modalHead('在 ' + esc(ag.name) + ' 中继续这个会话', '复制后到终端运行；Orbit 不会执行任何命令') + '<div class="mb col" data-tl="resume"><div class="row" style="padding:10px 12px;border-radius:9px;background:var(--sunken);border:1px solid var(--line)"><span class="mono" style="flex:1;font-size:12.5px;word-break:break-all">' + esc(c.shell) + '</span><button type="button" class="btn sm" data-act="copyCmd" data-v="' + esc(c.shell) + '">复制</button></div>' + (c.verified === false ? '<p class="cap" style="margin:0">' + esc(c.note || '参数待验证') + '</p>' : '') + '</div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>');
    }, opErr('生成继续命令'));
  };
  function tloLocate() {
    const s = selS(); if (!s) return;
    TL.ops.locate(s.id).then((d) => {
      const f = (d.files || []).find((x) => x.exists) || (d.files || [])[0];
      if (!f) { toast('没有找到原始记录'); return; }
      if (!f.exists) { toast('原始日志已不存在：' + f.path); return; }
      ORBIT.native.request('reveal', { path: f.path });
      if (ORBIT.native.hasHost()) toast('已在 Finder 中显示：' + f.path);
    }, opErr('定位原始日志'));
  }
  ACT.tlOpenLog = tloLocate;
  function tloExclude(uid, reason) {
    TL.ops.exclude(uid, reason).then(() => { S.excluded.add(uid); render(); toast('已从统计中排除这个会话，所有页面已重算；它仍留在列表里，可随时恢复'); }, opErr('排除会话'));
  }
  function tloInclude(uid) { TL.ops.include(uid).then(() => { S.excluded.delete(uid); render(); toast('已重新计入分析'); }, opErr('恢复计入分析')); }
  ACT.sessMore = (el) => {
    const s = selS(); if (!s) return;
    openDD(el, [{ t: '复制会话 ID', v: () => copyText(s.id, '会话 ID') }, { t: '在 Finder 中显示日志', v: tloLocate }, { sep: 1 },
      S.excluded.has(s.id) ? { t: '重新计入分析', v: () => tloInclude(s.id) } : { t: '标记为不计入分析', v: () => setTimeout(() => openDD(el, [{ h: '不计入分析的原因' }].concat(Object.keys(TLO_REASON).map((k) => ({ t: TLO_REASON[k], v: k }))), (reason) => tloExclude(s.id, reason)), 0) }], (v) => v());
  };
  TL.on('event', (ev) => { if (ev.name === 'exclusions.changed') LV.loadSpine(); });

  /* ---------- A4: an expanded tool row lists its real calls ---------- */
  const ST_OK = { success: 1, completed: 1, ok: 1 };
  function tloCalls(name, failOnly) {
    const k = name + '|' + (failOnly ? 'failed' : 'all');
    let t = TLO.tc[k];
    if (!t) {
      t = TLO.tc[k] = { items: null, err: null, more: false, cursor: null, busy: true };
      const w = win(S.range);
      TL.ops.toolCalls({ name, status: failOnly ? 'failed' : 'all', limit: 20, from_ts: DAY0 + w[0] * 86400000 }).then((d) => { t.items = d.items || []; t.more = !!d.has_more; t.cursor = d.next_cursor || null; },
        (e) => { t.err = e; t.items = []; }).then(() => { t.busy = false; if (S.route === 'tools') render(); });
    }
    return t;
  }
  function callRow(c) {
    const s = BYID[c.session_uid]; const ok = ST_OK[c.status]; const t = c.started_at ? new Date(c.started_at) : null;
    const dur = c.duration_ms != null ? c.duration_ms / 1000 : null;
    return '<div class="row mono tt-call" data-tl="call"><span style="color:var(--ink-3)">' + (t ? (t.getMonth() + 1) + '/' + t.getDate() + ' ' + String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0') : '—') + '</span><span class="tt-cmd">' + esc(c.args_summary || c.command_head || (c.files || []).join(' ') || c.name || '—') + '</span><span style="color:' + (ok ? 'var(--good)' : 'var(--crit)') + ';min-width:38px">' + (ok ? 'ok' : c.exit_code != null ? 'exit ' + c.exit_code : esc(c.status || '—')) + '</span><span style="color:var(--ink-3);min-width:46px;text-align:right">' + (dur == null ? '—' : (dur < 10 ? f1(dur) : Math.round(dur)) + ' s') + '</span>' + (s ? '<button type="button" class="lnk" data-act="openSession" data-id="' + esc(s.id) + '" style="font-family:var(--font-sans)">在轨迹中查看 →</button>' : '') + '</div>';
  }
  RENDER_HOOKS.push((m) => {
    if (S.route !== 'tools' || !S.tools || !S.tools.open) return;
    const td = m.querySelector('tr.tt-open td'); if (!td) return;
    /* slice 3 already renders (and caches) this row's calls; only tag its markup, never refetch or overwrite */
    const lv = td.querySelector('[data-lv="tool-calls"]');
    if (lv) { lv.setAttribute('data-tl', 'tool-calls'); lv.querySelectorAll('.tt-call').forEach((r) => r.setAttribute('data-tl', 'call')); return; }
    const t = tloCalls(S.tools.open, !!S.tools.failOnly);
    const body = t.busy ? '<div class="cap" style="padding:6px 0" data-tl="calls-pending">正在读取调用明细…</div>' : t.err ? '<div class="cap" style="padding:6px 0" data-tl="calls-na">' + (TL.unavailable(t.err) ? '本地服务暂不提供调用明细' : '读取调用明细失败') + '</div>' : !t.items.length ? '<div class="cap" style="padding:6px 0" data-tl="calls-na">这段时间没有调用记录</div>' : t.items.map(callRow).join('') + (t.more ? '<span class="cap" style="font-size:11px">只显示最近 20 次</span>' : '');
    td.innerHTML = '<div class="col" style="gap:3px;padding:4px 0 6px" data-tl="tool-calls">' + body + '</div>';
  });
  TL.on('event', (ev) => { if (/^data\b/.test(ev.name)) TLO.tc = {}; });

  /* ---------- export: report .md · share card .png ---------- */
  const unavailable = (what) => (e) => toast(TL.unavailable(e) ? '本地服务暂不支持导出' + what + '，请更新 Orbit 后再试' : '导出' + what + '失败：' + ((e && (e.message || e.code)) || ''));
  const exportFoot = (act, label) => '<div class="mf"><span class="cap" style="margin-right:auto;font-size:11px">由本机服务生成 · 只含统计，不含对话原文</span><button type="button" class="btn" data-act="closeModal">关闭</button><button type="button" class="btn" data-act="repCopy">' + ic('copy', 13) + '复制</button><button type="button" class="btn p" data-act="' + act + '">' + ic('down', 13) + label + '</button></div>';
  // B18: every export carries the scope the screen shows — range, the enabled agents and the project filter
  // (S.project; '_none' = sessions without a project has no backend filter and is dropped)
  function tloExportScope() {
    const sc = lvScope(); const pj = S.project && S.project !== '_none' ? S.project : null;
    return { report: Object.assign({}, sc, { projects: pj ? [pj] : null }) };
  }
  TLO.exportScope = tloExportScope;
  // H4: the sheet opens on the keystroke and fills when the gateway answers. /v1/export/report waits up to 3 s for sections
  // a filter change has just invalidated, so opening only after the response looked like ⇧⌘E did nothing. TLO.repSeq drops
  // an answer that arrives after the sheet was closed, replaced or re-requested.
  const repSheet = () => modalHead('导出报告', rangeLabel() + ' · ' + winLabel() + ' · 跟随主窗口的筛选') + '<div class="mb" style="display:flex;flex-wrap:wrap;gap:16px"><div class="col" style="gap:8px;width:150px;flex:none"><span class="eb">包含</span>' + REP_SECS.map((x) => '<label class="row" style="font-size:13px"><input type="checkbox" data-chg="repSec" data-k="' + x[0] + '"' + (S.rep.has(x[0]) ? ' checked' : '') + ' style="accent-color:var(--ink-1)">' + x[1] + '</label>').join('') + '<span class="eb" style="margin-top:8px">格式</span><span style="font-size:13px">Markdown</span></div><textarea readonly id="repText" data-tl="report-pending" aria-label="报告内容" aria-busy="true" style="flex:1;min-width:min(260px,100%);min-height:340px;font:12px/1.55 var(--font-mono);border:1px solid var(--line);border-radius:9px;padding:10px 12px;background:var(--surface);color:var(--ink-1);resize:vertical">正在生成报告…</textarea></div>' + exportFoot('repSave', '保存 .md');
  const repBusy = (on) => { $$('#modal [data-act="repSave"], #modal [data-act="repCopy"]').forEach((b) => { b.disabled = on; }); const t = $('#repText'); if (t) { t.dataset.tl = on ? 'report-pending' : 'report'; t.setAttribute('aria-busy', String(on)); } };
  TLO.repSeq = 0;
  function tloReport(first) {
    const seq = ++TLO.repSeq;
    if (first) { CUR.report = ''; openModal(repSheet(), 'wide'); MODAL_KEY = 'report'; }
    repBusy(true);
    const mine = () => seq === TLO.repSeq && MODAL_KEY === 'report';
    return TL.ops.report(S.rep, tloExportScope().report).then((d) => {
      if (!mine()) return;
      CUR.report = d.markdown || '';
      const t = $('#repText'); if (t) t.value = CUR.report;
      repBusy(false);
    }, (e) => { if (!mine()) return; closeModal(); throw e; });
  }
  openReport = function () { tloReport(true).catch(unavailable('报告')); };
  wrap('repSec', (base, el) => { const k = el.dataset.k; if (el.checked) S.rep.add(k); else S.rep.delete(k); tloReport(false).catch(unavailable('报告')); });
  ACT.repSave = () => expSave('orbit-report-' + expStamp() + '.md', 'text/markdown', { text: CUR.report || '' });
  // share card: one gateway card per time span (POST /v1/export/share_card, period = that span, same Agent / project
  // filters as the persona page). Each card shows what the gateway computed for its window — code, axis values (so the
  // flower's proportions), type copy, quote and stats; label / date / day ring come from the spine. A span the gateway
  // refuses shows its reason in the sheet; every span refused → the sheet closes with the reason; gateway unavailable →
  // the persona the app computed for that window (slice 1).
  TLO.shareBy = {};
  const tloSpanState = shareSpanState;
  function liveSpan(k, d) {
    const sp = sharePersona(k); const c = d.copy || {}; const t = TYPES[d.code] || [];
    const v = Object.assign({}, d.v || {}); (d.axes || []).forEach((a) => { if (v[a.k] == null && a.value != null) v[a.k] = a.value; });
    const n = ((d.stats || []).find((s) => s.label === '会话') || {}).value;
    sp.p = { ok: true, classified: true, code: d.code, zh: d.type_name || t[0] || '', en: c.en || t[1] || '', line: c.line || t[2] || '', v, axes: d.axes || [], n: n != null ? n : sp.p.n };
    sp.q = c.quote && c.quote.length === 2 ? c.quote : SHAREQ[d.code] || null;
    sp.stats = (d.stats || []).slice(0, 4).map((s) => [s.value == null ? '—' : TLU.num(s.value), s.label]);
    if (d.period_label && !/^\d{4}-\d{2}$/.test(d.period_label)) sp.label = d.period_label;
    if (d.span && d.span.tag) sp.tag = [d.span.tag, d.span.tag_en || ''];
    if (Array.isArray(d.window) && d.window.length === 2) sp.range = spanRange(new Date(d.window[0] + 'T00:00:00Z'), new Date(d.window[1] + 'T00:00:00Z'));
    sp.disclaimer = d.disclaimer || ''; sp.live = true;
    return sp;
  }
  shareSpanState = function (k) {
    const e = TLO.shareBy[k];
    if (!e || e.state === 'pending') return { state: 'pending', sp: null };
    if (e.state === 'ok') return { state: 'ok', sp: liveSpan(k, e.d) };
    if (e.state === 'local') return tloSpanState(k);
    return { state: 'blocked', sp: null, reason: e.reason };
  };
  function shareFetch(k, seq, tries) {
    const sc = LV.scope();
    return TL.send('POST', '/v1/export/share_card', { hide_numbers: false, theme: S.shareDark ? 'dark' : 'light', save: false,
      period: String(k), agents: sc.agents || null, project: sc.project || null,
      scope: { display_timezone: TL_TZ || 'UTC' } }).then((r) => r.data).then((d) => {
      if (seq !== TLO.shareSeq) return;
      if (d.freshness === 'computing' && tries < 3) return new Promise((res) => setTimeout(res, 1200)).then(() => shareFetch(k, seq, tries + 1));
      TLO.shareBy[k] = d.freshness === 'computing' ? { state: 'blocked', reason: '协作画像正在计算，稍后再试' }
        : !d.eligible ? { state: 'blocked', reason: H.BLOCKED[d.blocked_reason] || '暂时不能生成分享卡' } : { state: 'ok', d };
    }, (e) => {
      if (seq !== TLO.shareSeq) return;
      TLO.shareBy[k] = TL.unavailable(e) ? { state: 'blocked', reason: '本地服务暂不支持生成分享卡，暂时不能生成分享卡' }
        : { state: 'blocked', reason: '生成分享卡失败：' + (e.message || e.code) };
    });
  }
  openShare = function () {
    // H4: ⇧⌘S answers at once — a pending sheet the gateway's answers fill (or close, with the reason as a toast)
    const seq = TLO.shareSeq = (TLO.shareSeq || 0) + 1; TLO.shareBy = {}; TLO.sharePicked = false;
    const ks = shareSpans(); ks.forEach((k) => { TLO.shareBy[k] = { state: 'pending' }; });
    S.shareSpan = null; S.shareSpan = shareKey();
    shareSheet(); MODAL_KEY = 'share-pending';
    const mine = () => seq === TLO.shareSeq && (MODAL_KEY === 'share-pending' || MODAL_KEY === 'share') && !!$('#shareBody');
    const settle = () => {
      if (!mine()) return;
      const sts = ks.map((k) => [k, shareSpanState(k)]); const ok = sts.filter((x) => x[1].state === 'ok');
      if (sts.every((x) => x[1].state === 'blocked')) { closeModal(); toast(sts.find((x) => x[0] === S.shareSpan)[1].reason || '暂时不能生成分享卡'); return; }
      // the span the sheet opened on was refused and the user has not picked one: show the first card that came back
      if (!TLO.sharePicked && shareSpanState(S.shareSpan).state === 'blocked' && ok.length) S.shareSpan = ok[0][0];
      if (ok.length) MODAL_KEY = 'share';
      shareRefresh();
    };
    // the span on screen first, then the others
    [S.shareSpan].concat(ks.filter((k) => k !== S.shareSpan)).forEach((k) => { shareFetch(k, seq, 0).then(settle); });
  };
  wrap('shareSpan', (base, el, ev) => { TLO.sharePicked = true; return base(el, ev); });

  const tloRender = render;
  render = function () { tloApply(); tloRender(); };
  tloStart();
}

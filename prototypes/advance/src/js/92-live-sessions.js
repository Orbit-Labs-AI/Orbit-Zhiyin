/* ============ live A3 sessions (slice 2) ============
   Live mode only swaps the data under the polished A3 page (42-a3-sessions.js); every component, class and animation stays.
   - traj(s): GET /v1/uiview/sessions/{uid}?tz= once per session (LRU 30), mapped to the demo's trajectory shape
     (lanes / phases / moments / ctx / comps / users). Until it arrives the page shows the timeline skeleton.
   - 7 stats, model, cwd and the takeaway card read the same detail response; mood stays "—" until G2.
   - list barcodes read the real tick positions from GET /v1/uiview/sessions (rows[].ticks); unknown → an empty barcode.
   - search: local title match at once, then GET /v1/uiview/sessions?q= (message text) adds the server's hits (debounced).
   - compare: default B from /{uid}/suggest_b, phase shares from /compare; both timelines read their own details.
   - message text: GET /v1/sessions/{uid}/events?limit=200 only when 查看全文 is opened (paged by offset).
   A3 ops (exclude / resume / locate) stay with 98-live-ops.js. */
(function () {
  if (!LV.live) return;
  const DETAIL = LV.lru(30); const CMP = LV.lru(30); const MSGS = LV.lru(30); const TICKS = new Map();
  const LVS = { detail: DETAIL, cmp: CMP, msgs: MSGS, ticks: TICKS, search: null, phReady: null, lvSess: null, suggest: {} };
  window.LVS = LVS;
  const tzq = () => ({ tz: TL_TZ || 'UTC' });
  const dpath = (uid) => '/v1/uiview/sessions/' + encodeURIComponent(uid);
  const entry = (s) => LV.detail(DETAIL, s.id, dpath(s.id), { query: tzq() });
  const peek = (s) => (s && DETAIL.get(s.id)) || null;

  /* ---------- detail → demo trajectory shape ---------- */
  const LANE = { user: 'user', agent: 'reply', reply: 'reply', sub: 'sub', read: 'read', edit: 'edit', bash: 'bash', web: 'web' };
  function mapTraj(s, d) {
    const t = (d && d.trajectory) || {}; const T = Math.max(+t.T || 0, 0.05);
    const ev = [];
    (t.events || []).forEach((x) => {
      const lane = LANE[x.lane]; if (!lane) return;
      const e = { lane, t: +x.t || 0, w: +x.w || 0, uid: x.event_uid || null, seq: x.seq };
      if (lane === 'user') { e.mood = x.mood != null ? x.mood : null; e.corr = !!x.corr; e.txt = x.txt || ''; }
      else if (lane === 'reply') e.txt = 'Agent 回复' + (e.w ? ' · ' + Math.max(1, Math.round(e.w * 60)) + ' 秒' : '');
      else if (lane === 'sub') { e.txt = x.txt || '子代理'; if (!e.w) e.w = Math.max(0.05, T * 0.02); }
      else { e.cmd = x.cmd || x.name || '—'; e.res = x.res || x.status || null; e.err = !!x.err; }
      if (x.err) e.err = true;
      ev.push(e);
    });
    ev.sort((a, b) => a.t - b.t);
    ev.forEach((e, i) => { e.id = 'e' + i; });
    let ui = 0; const users = ev.filter((e) => e.lane === 'user').map((e) => { e.idx = ui++; return [e.t, e.mood, e.corr, e.txt]; });
    const phases = (t.phases || []).map((p) => { const a = [+p.t || 0, +p.t2 || 0, p.label || p.phase || '']; a.inferred = p.inferred !== false; return a; });
    const moments = (t.moments || []).map((m) => [+m.t || 0, m.label || '', m.detail || '', !!m.alert]);
    let ctx = (t.ctx || []).filter((c) => Array.isArray(c) && c.length >= 2).map((c) => [+c[0], +c[1]]);
    const hasCtx = ctx.length > 0; if (!hasCtx) ctx = [[0, 0]];
    const comps = ctx.map((c, i) => i > 0 && c[1] < ctx[i - 1][1] - 20 ? i : -1).filter((i) => i > 0);
    return { T, ev, phases, ctx, moments, users, comps, live: true, state: 'ready', hasCtx, stats: (d && d.stats7) || {}, header: (d && d.header) || {}, insight: (d && d.insight) || null };
  }
  function skeleton(s, state) {
    const T = Math.max(s && s.dur ? +s.dur : 1, 0.05);
    return { T, ev: [], phases: [], ctx: [[0, 0]], moments: [], users: [], comps: [], live: true, state, hasCtx: false, stats: {}, header: {}, insight: null };
  }
  const EMPTY = skeleton(null, 'none');
  // eslint-disable-next-line no-func-assign
  traj = function (s) {
    if (!s) return EMPTY;
    const e = entry(s);
    if (e.state === 'ready') { if (!e.tr || e.trFor !== e.data) { e.tr = mapTraj(s, e.data); e.trFor = e.data; } return e.tr; }
    const k = e.state === 'error' ? 'error' : 'pending';
    if (!e.sk || e.sk.state !== k) e.sk = skeleton(s, k);
    return e.sk;
  };

  /* ---------- hooks: header band, 7 stats, takeaway, today, search ---------- */
  const num = (v) => TLU.num ? TLU.num(v) : String(v);
  Object.assign(A3H, {
    todayD: () => LASTDAY,
    dayLabel: (d) => (d === LASTDAY ? '今天 · ' : d === LASTDAY - 1 ? '昨天 · ' : '') + mdz(d) + ' 周' + WD[wd(d)],
    qMatch: (s, q) => {
      const p = PJI[s.p]; const ag = agent(s.a);
      if (s.title.toLowerCase().includes(q) || (p && p.name.toLowerCase().includes(q)) || (ag && ag.name.toLowerCase().includes(q))) return true;
      return !!(LVS.search && LVS.search.q === q && LVS.search.ids && LVS.search.ids.has(s.id));
    },
    model: (s) => { const h = (peek(s) && peek(s).data && peek(s).data.header) || {}; const m = h.model || s.model; const ef = h.effort || s.effort; return m ? esc(m) + (ef ? ' · ' + esc(ef) : '') : '—'; },
    path: (s) => { const h = (peek(s) && peek(s).data && peek(s).data.header) || {}; const p = PJI[s.p]; return h.cwd || (p && p.path && p.path !== '—' ? p.path : '—'); },
    steps: (s) => { const st = traj(s).stats; return st.steps != null ? num(st.steps) : s.steps != null ? num(s.steps) : '—'; },
    ctxPeak: (s, tr) => { const st = tr.stats; return st.ctx_peak != null ? Math.round(st.ctx_peak) + '%' : tr.hasCtx ? Math.round(Math.max(...tr.ctx.map((c) => c[1]))) + '%' : '—'; },
    tok: (s) => { const st = traj(s).stats; const v = st.tok != null ? st.tok : s.tok; return !v ? '—' : v >= 1e6 ? f1(v / 1e6) + 'M' : v >= 1e3 ? Math.round(v / 1e3) + 'K' : String(v); },
    summary: (s, tr, def) => tr.state === 'pending' ? '正在载入轨迹…' : tr.state === 'error' ? '轨迹暂不可用：这个会话的详情没有返回' : def,
    inspExtra: (s, e) => e && (e.lane === 'user' || e.lane === 'reply') ? '<button type="button" class="btn sm gh" data-act="lvsMsgs" data-uid="' + esc(e.uid || '') + '">查看全文</button>' : '',
    insight: (s) => {
      const tr = traj(s);
      if (tr.state === 'pending') return { text: '正在载入…', actions: [] };
      const x = tr.insight; if (!x || !x.text) return { text: '暂无启示', actions: [] };
      return { text: x.text, actions: (x.actions || []).map((a) => ({ label: a.label, id: a.rec_id || a.problem_type || '', act: 'lvsRule' })) };
    },
    phasePct: (x, side) => {
      const a = BYID[S.sess.sel], b = BYID[S.sess.cmp]; const c = a && b ? cmpEntry(a, b) : null;
      const list = c && c.state === 'ready' && c.data && c.data.phase_pct && c.data.phase_pct[side];
      if (list) return list.map((p) => [esc(p.label || p.phase), p.pct != null ? p.pct : 0]);
      // per-label shares from the session's own phases (repeated labels merged), until /compare answers
      const t = traj(x); const m = {}; t.phases.forEach((p) => { m[p[2]] = (m[p[2]] || 0) + (p[1] - p[0]); });
      return Object.keys(m).map((k) => [esc(k), Math.round(m[k] / t.T * 100)]);
    }
  });
  function cmpEntry(a, b) { return LV.detail(CMP, a.id + '|' + b.id, '/v1/uiview/sessions/compare', { query: Object.assign({ a: a.id, b: b.id }, tzq()) }); }

  /* ---------- list barcodes: real tick positions ---------- */
  LV.feed('sessions', (sc) => [{ name: 'list', path: '/v1/uiview/sessions', query: { range: sc.range || 0, agents: sc.agents ? sc.agents.join(',') : null, limit: 200, tz: sc.tz || 'UTC' } }],
    (d) => { ((d.list && d.list.rows) || []).forEach((r) => { if (r && r.id && r.ticks) TICKS.set(r.id, r.ticks); }); });
  // eslint-disable-next-line no-func-assign
  barcode = function (s, w) {
    const tk = TICKS.get(s.id); const f = s.live ? 0.62 : 1; let d = '', e = '';
    if (tk) {
      (tk.t || []).slice(0, 400).forEach((x) => { d += 'M' + (x * w * f).toFixed(1) + ' 1V7'; });
      (tk.e || []).slice(0, 60).forEach((x) => { e += 'M' + (x * w * f).toFixed(1) + ' 0V8'; });
    }
    return '<svg width="100%" height="8" viewBox="0 0 ' + w + ' 8" preserveAspectRatio="none" aria-hidden="true" style="display:block"' + (tk ? '' : ' data-lv="na"') + '><path d="' + (d || 'M0 0') + '" stroke="var(--ink-4)" stroke-width="1.4"/><path d="' + (e || 'M0 0') + '" stroke="var(--vz-err)" stroke-width="2"/></svg>';
  };

  /* ---------- region hooks (42-a3-sessions.js sessNorm / regions): entry from other surfaces, playhead to the real end,
     pending markers, and the signatures that make a detail / search arrival refresh exactly the regions reading it ---------- */
  A3H.pre = () => { if (S.lvSess && S.lvSess !== LVS.lvSess) { LVS.lvSess = S.lvSess; if (BYID[S.lvSess]) { S.sess.sel = S.lvSess; S.sess.mode = 'single'; } } };
  // the playhead was parked at the skeleton's end while the detail loaded: move it to the real end once
  A3H.post = (s) => { if (!s) return; const tr = traj(s); if (tr.state === 'ready' && LVS.phReady !== s.id) { LVS.phReady = s.id; if (!S.sess.playing) { S.sess.ph = tr.T; S.sess.view = null; S.sess.zoom = 1; } } };
  A3H.sumAttr = (s, tr) => (tr.state === 'ready' ? '' : ' data-lv="' + (tr.state === 'error' ? 'error' : 'pending') + '"' + (tr.state === 'pending' ? ' aria-busy="true"' : ''));
  const esig = (e) => (e ? e.state + ':' + lvId(e.data) : '-');
  A3H.detSig = () => {
    const ids = [S.sess.sel]; if (S.sess.mode === 'cmp' && S.sess.cmp) ids.push(S.sess.cmp, S.sess.sel + '|' + S.sess.cmp);
    return ids.map((k, i) => esig(i < 2 ? DETAIL.get(k) : CMP.get(k))).join(',');
  };
  A3H.listSig = () => (LVS.search ? LVS.search.q + ':' + LVS.search.state : '');

  /* ---------- search: server hits (message text) on top of the local title match ---------- */
  let qTimer = null; let qSeq = 0;
  function serverSearch(q) {
    clearTimeout(qTimer);
    if (!q) { LVS.search = null; return; }
    if (LVS.search && LVS.search.q === q) return;
    qTimer = setTimeout(() => {
      const my = ++qSeq;
      LVS.search = { q, ids: null, state: 'pending' };
      TL.get('/v1/uiview/sessions', { query: Object.assign({ q, limit: 200 }, tzq()) }).then((res) => {
        if (my !== qSeq) return;
        const rows = (res.data && res.data.rows) || [];
        rows.forEach((r) => { if (r && r.id && r.ticks) TICKS.set(r.id, r.ticks); });
        LVS.search = { q, ids: new Set(rows.map((r) => r.id)), state: 'ready', partial: !!(res.data && res.data.meta && res.data.meta.search_partial) };
      }, () => { if (my === qSeq) LVS.search = { q, ids: null, state: 'error' }; }).then(() => { if (my === qSeq && S.route === 'sessions') updSessList(); });
    }, 250);
  }
  const baseQ = ACT.sessQ;
  ACT.sessQ = function (el, e) { baseQ(el, e); serverSearch(S.sess.q.trim().toLowerCase()); };

  /* ---------- compare: default B from suggest_b ---------- */
  const baseMode = ACT.sessMode;
  ACT.sessMode = function (el) {
    const toCmp = el.dataset.v === 'cmp' && !S.sess.cmp; const a = S.sess.sel;
    baseMode(el);
    if (!toCmp || !a) return;
    const local = S.sess.cmp;   // the demo's same-project pick stays until the server answers
    const apply = (b) => { if (S.sess.mode !== 'cmp' || S.sess.sel !== a || !b || b === a || !BYID[b]) return; if (S.sess.cmp !== b) { S.sess.cmp = b; S.sess.turn = 'A'; render(); } };
    if (LVS.suggest[a] !== undefined) { apply(LVS.suggest[a]); return; }
    TL.get(dpath(a) + '/suggest_b', { query: tzq() }).then((res) => { const b = res.data && res.data.b; LVS.suggest[a] = b || null; apply(b); },
      () => { LVS.suggest[a] = local || null; });
  };

  /* ---------- takeaway actions ---------- */
  ACT.lvsRule = (el) => {
    const id = el.dataset.id;
    let info = null; try { info = typeof instInfo === 'function' ? instInfo(id) : null; } catch (e) { info = null; }
    if (info) openInstall(id); else { go('recs'); toast('已转到建议页：相关规则会出现在这里'); }
  };

  /* ---------- message text: /v1/sessions/{uid}/events, paged, only when opened ---------- */
  const MSG_KIND = { user_message: '你', assistant_message: 'Agent' };
  function msgLoad(uid, m) {
    if (m.loading || m.done) return Promise.resolve(m);
    m.loading = true;
    return TL.get('/v1/sessions/' + encodeURIComponent(uid) + '/events', { query: { limit: 200, offset: m.offset } }).then((res) => {
      const d = res.data || {}; const items = d.items || [];
      items.forEach((x) => { if (MSG_KIND[x.kind] && (x.text || '').trim()) m.items.push(x); });
      m.offset += items.length; m.total = d.total != null ? d.total : m.offset;
      m.done = !items.length || m.offset >= m.total; m.error = null;
    }, (err) => { m.error = err; }).then(() => { m.loading = false; return m; });
  }
  // round 3: list pages cap text at 8000 chars (truncated + text_range); the rest is read by range from /v1/evidence
  const REST_CHARS = 64000;
  function msgRest(x) { const r = x.text_range; if (!x.truncated || !r || (x.truncated_fields && x.truncated_fields.indexOf('text') < 0)) return 0; return Math.max(0, (r.total || 0) - (r.offset || 0) - (r.length || 0)); }
  function msgTrunc(s, x) {
    if (x.restErr) return ' <span class="cap" data-lv="trunc-error">· ' + esc(x.restErr) + '</span>';
    const left = msgRest(x); if (!left) return '';
    if (x.restLoading) return ' <span class="cap" data-lv="trunc-loading">· 正在载入其余 ' + fmt(left) + ' 字…</span>';
    return ' <button type="button" class="lnk cap" data-lv="trunc" data-act="lvsMsgRest" data-uid="' + esc(s.id) + '" data-ev="' + esc(x.id) + '" title="已显示 ' + fmt((x.text_range.offset || 0) + (x.text_range.length || 0)) + ' / ' + fmt(x.text_range.total) + ' 字">已截断 · 展开全文</button>';
  }
  function msgHtml(s, m, focus) {
    if (m.error && !m.items.length) return '<div class="cap" data-lv="error" style="padding:12px 0">消息原文暂不可用（' + esc((m.error && (m.error.code || m.error.message)) || '请求失败') + '）</div>';
    if (!m.items.length && (m.loading || !m.done)) return LV.pend(160);
    if (!m.items.length) return '<div class="cap" data-lv="na" style="padding:12px 0">这个会话没有可显示的消息原文</div>';
    const rows = m.items.map((x) => {
      const ts = x.timestamp ? new Date(x.timestamp) : null; const at = ts && !isNaN(ts) ? hm(ts.getHours(), ts.getMinutes()) : '—';
      return '<div class="tl-kv lvs-msg' + (x.id === focus ? ' on' : '') + '" data-ev="' + esc(x.id) + '" style="grid-template-columns:96px minmax(0,1fr);gap:10px;align-items:flex-start;padding:8px 0;border-top:1px solid var(--hair)' + (x.id === focus ? ';background:var(--sunken)' : '') + '"><span class="k mono">' + at + ' · ' + MSG_KIND[x.kind] + '</span><span class="v" style="white-space:pre-wrap;word-break:break-word">' + esc(x.text) + msgTrunc(s, x) + (x.details && x.details.text_truncated ? ' <span class="cap">…（原文已截断）</span>' : '') + '</span></div>';
    }).join('');
    const more = !m.done ? '<button type="button" class="tl-more" data-act="lvsMsgsMore" data-uid="' + esc(s.id) + '">已载入 ' + m.offset + ' / ' + m.total + ' 个事件<b>加载更多</b></button>' : '';
    return '<div class="col" style="gap:0;max-height:56vh;overflow:auto">' + rows + '</div>' + more;
  }
  function msgDraw(s, focus) {
    const box = $('#lvsMsgBox'); if (!box || box.dataset.uid !== s.id) return;
    const m = MSGS.get(s.id); const sc0 = box.firstElementChild; const top = sc0 ? sc0.scrollTop : 0; box.innerHTML = msgHtml(s, m, focus); if (!focus && box.firstElementChild) box.firstElementChild.scrollTop = top;
    const on = focus && box.querySelector('.lvs-msg.on'); if (on && on.scrollIntoView) on.scrollIntoView({ block: 'nearest' });
  }
  ACT.lvsMsgs = (el) => {
    const s = BYID[S.sess.sel]; if (!s) return; const focus = (el && el.dataset.uid) || null;
    let m = MSGS.get(s.id); if (!m) m = MSGS.set(s.id, { items: [], offset: 0, total: 0, done: false, loading: false, error: null });
    if (m.error) { m.error = null; m.done = false; }
    openModal(modalHead('消息原文 · ' + esc(s.title), agent(s.a).name + ' · ' + mdz(s.d) + ' ' + hm(s.h, s.mi) + ' · 只读，按需分页载入') + '<div class="mb col"><div id="lvsMsgBox" data-uid="' + esc(s.id) + '">' + msgHtml(s, m, focus) + '</div></div><div class="mf"><button type="button" class="btn" data-act="closeModal">关闭</button></div>');
    const need = !m.done && (!m.items.length || (focus && !m.items.some((x) => x.id === focus)));
    if (need) msgLoad(s.id, m).then(() => msgDraw(s, focus));
  };
  ACT.lvsMsgRest = (el) => {
    const s = BYID[el.dataset.uid]; const m = s && MSGS.get(s.id); const x = m && m.items.find((it) => it.id === el.dataset.ev);
    if (!x || x.restLoading || !msgRest(x)) return;
    const r = x.text_range; const off = (r.offset || 0) + (r.length || 0);
    x.restLoading = true; msgDraw(s, null);
    TL.get('/v1/evidence/' + encodeURIComponent(x.id), { query: { text_offset: off, max_chars: REST_CHARS } }).then((res) => {
      const d = res.data || {}; const piece = typeof d.text === 'string' ? d.text : ''; const dr = d.text_range || {};
      x.text = (x.text || '') + piece;
      x.text_range = { offset: r.offset || 0, length: (r.length || 0) + piece.length, total: dr.total != null ? dr.total : r.total };
      if (!piece) x.text_range.total = x.text_range.offset + x.text_range.length;   // nothing more to read: stop offering it
    }, (err) => { x.restErr = err && (err.status === 404 || err.code === 'not_found') ? '其余原文已不在本地数据中' : '展开失败（' + ((err && (err.code || err.message)) || '请求失败') + '）'; })
      .then(() => { x.restLoading = false; msgDraw(s, null); });
  };
  ACT.lvsMsgsMore = (el) => { const s = BYID[el.dataset.uid]; const m = s && MSGS.get(s.id); if (!m) return; msgLoad(s.id, m).then(() => msgDraw(s, null)); msgDraw(s, null); };
})();

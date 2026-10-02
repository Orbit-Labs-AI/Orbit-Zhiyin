/* ============ live binding: recommendations (TandemLive.recs, js/06-live-client.js) ============
   Mock mode changes nothing. In live mode the demo renderers stay as they are (A7 cards and detail, A1「本周建议」, Lite
   l-home「本周最值得做的一件事」and l-recs, menubar「本周最值得做」): this file swaps the rows they read (RECS / RECI / REC_X)
   for GET /v1/recommendations, and recOrder / recTop(surface) put the backend's stable top slate (surface A1 / lite / menubar) first.
   - Never live yet and the endpoint is missing or down (404 / 501 / 503 / offline): the demo rows stay, with 示例数据.
   - Live once: later failures keep the last live rows (the strip says 刷新失败), never the demo rows.
   - Writes: view / open / preview / copy exposure; 不适用 / 稍后 / 不再推荐同类 are labels with an 8-second undo
     (DELETE /v1/labels/{id}); 重新计算 is POST /v1/recommendations/recompute. Each write invalidates the rec resources. */
const LVR = { applied: null, top: {}, rel: {}, labels: new Map(), poll: 0, detail: {} };
const LVR_SURFACES = ['A1', 'lite', 'menubar'];
const LVR_ROUTES = { recs: 'A7', 'l-recs': 'lite', overview: 'A1', 'l-home': 'lite' };
const LVR_DEGRADE = (e) => !e || !e.status || e.status === 404 || e.status === 501 || e.status === 503;
const lvRecLive = (id) => !!(RECI[id] && RECI[id].live);

TL.bind('recs', () => [TL.recs.desc('A7')], (d) => ({ items: (d.A7 && d.A7.items) || [], dims: (d.A7 && d.A7.dims) || [], run: d.A7 && d.A7.run }));

// Load the A7 list (and the top slate of the surfaces in view) without the page AbortSignal, then apply the rows.
function lvRecSync(surfaces) {
  if (TL.mode !== 'live') return;
  const scope = lvScope();
  const a7 = TL.recs.resource('A7', scope);
  if (a7.dirty && !a7.loading) TL.load(a7);
  (surfaces || []).forEach((sf) => {
    const r = TL.recs.resource(sf, scope);
    if (r.dirty && !r.loading) TL.load(r);
    if (r.data) LVR.top[sf] = (r.data.items || []).map((c) => c.rec_key);
  });
  if (a7.data && a7.data !== LVR.applied) lvRecApply(a7.data);
  // 202 computing: the recommend job does not publish analysis.ready for a section, so poll until a run exists
  const computing = [a7].concat((surfaces || []).map((sf) => TL.recs.resource(sf, scope))).some((r) => r.state === 'computing');
  if (computing && !LVR.poll) LVR.poll = setTimeout(() => { LVR.poll = 0; TL.recs.invalidate(); }, 3000);
}
function lvRecApply(data) {
  const rows = (data.items || []).map(TandemLive.recs.row);
  RECS.splice(0, RECS.length, ...rows);
  rows.forEach((r) => { RECI[r.id] = r; REC_X[r.id] = r.x; });
  LVR.applied = data;
  LVR.rel = {};
  const ids = rows.slice(0, 20).map((r) => r.id);
  if (ids.length >= 2) TL.recs.relations(ids).then((res) => { LVR.rel = {}; ((res.data && res.data.pairs) || []).forEach((p) => { (LVR.rel[p.a] = LVR.rel[p.a] || []).push(p); (LVR.rel[p.b] = LVR.rel[p.b] || []).push(p); }); if (S.route === 'recs') render(); }, () => {});
}
// Live never reached and the endpoint is missing / unavailable: keep the demo rows and label them.
function lvRecDegraded() {
  if (LVR.applied) return false;
  const r = TL.recs.resource('A7', lvScope());
  return r.state === 'error' && LVR_DEGRADE(r.error);
}
// Detail (GET /v1/recommendations/{id}): a finished outcome fills the track rows with the 7-day before / after values.
function lvRecDetail(id) {
  if (!lvRecLive(id) || LVR.detail[id]) return;
  LVR.detail[id] = 'loading';
  TL.recs.detail(id).then((res) => {
    const d = res.data || {}; LVR.detail[id] = d;
    const w = d.outcome && (d.outcome.windows || []).find((x) => x.window === '7d');
    const r = RECI[id];
    if (w && r) {
      const by = {}; (w.metrics || []).forEach((m) => { by[m.metric] = m; });
      r.track = r.track.map((t) => { const m = by[t[0]]; return m ? [t[0], m.before == null ? null : m.before, m.after == null ? null : m.after, t[3]] : t; });
    }
    if (S.route === 'recs' && S.recs.sel === id) render();
  }, () => { LVR.detail[id] = null; });
}

if (TL.mode === 'live') {
  // ---- top slate per surface ----
  const baseRecOrder = recOrder;
  recOrder = function (surface) {
    const base = baseRecOrder(surface);
    const keys = LVR.applied && LVR.top[surface];
    if (!keys) return base;
    const first = keys.map((k) => base.find((r) => r.rec_key === k)).filter(Boolean);
    return first.concat(base.filter((r) => first.indexOf(r) < 0));
  };

  // ---- pages: A7 and Lite l-recs keep the demo renderers; overview / Lite home get the rec card appended ----
  const baseRecs = PAGES.recs, baseLiteRecs = PAGES['l-recs'];
  TL_PAGES.recs = function () { lvView('recs'); lvRecSync(); return baseRecs(); };
  TL_PAGES.recs.after = baseRecs.after;
  PAGES.recs = TL_PAGES.recs;
  PAGES['l-recs'] = function () { lvView('recs'); lvRecSync(['lite']); return baseLiteRecs(); };
  if (baseLiteRecs.after) PAGES['l-recs'].after = baseLiteRecs.after;
  const append = (html, card) => { const i = html.lastIndexOf('</div>'); return i < 0 ? html + card : html.slice(0, i) + card + html.slice(i); };
  const baseOv = PAGES.overview, baseLiteHome = PAGES['l-home'];
  PAGES.overview = function () { lvRecSync(['A1']); const html = baseOv(); return LVR.applied ? append(html, '<div style="margin-top:12px" data-tl="recs-a1">' + ovRecsCard(recTop('A1').slice(0, 3)) + '</div>') : html; };
  PAGES['l-home'] = function () { lvRecSync(['lite']); const html = baseLiteHome(); return LVR.applied ? append(html, '<div class="lite" style="margin-top:12px" data-tl="recs-lite">' + liteOneCard(recTop('lite')) + '</div>') : html; };
  ['overview', 'l-home'].forEach((k) => { const b = k === 'overview' ? baseOv : baseLiteHome; if (b.after) PAGES[k].after = b.after; });

  // ---- render: 示例数据 when degraded, relations tags, view exposure ----
  const lvBaseRender = render;
  render = function () {
    lvBaseRender();
    const c = $('#content'); if (!c) return;
    const surface = LVR_ROUTES[S.route];
    if (!surface) return;
    const strip = c.querySelector(':scope > [data-tl="strip"]');
    if (strip && lvRecDegraded() && !strip.querySelector('[data-tl="sample"]')) strip.insertAdjacentHTML('beforeend', '<div>' + TLU.sample() + '</div>');
    if (S.route === 'recs' && S.recs.tab === 'why' && LVR.rel[S.recs.sel]) {
      const ev = c.querySelector('.rc-ev');
      if (ev && !c.querySelector('[data-tl="rec-rel"]')) ev.insertAdjacentHTML('beforebegin', '<div class="row" style="flex-wrap:wrap" data-tl="rec-rel">' + LVR.rel[S.recs.sel].map((p) => { const o = RECI[p.a === S.recs.sel ? p.b : p.a]; return o ? '<span class="tag" data-tip="' + esc(p.reason || '') + '">' + (p.relation === 'conflicts' ? '与「' : '可搭配「') + esc(o.title.split('：')[0]) + '」' + (p.relation === 'conflicts' ? '冲突' : '') + '</span>' : ''; }).join('') + '</div>');
    }
    if (S.route === 'recs' && lvRecLive(S.recs.sel)) lvRecDetail(S.recs.sel);
    const ids = [...c.querySelectorAll(S.route === 'recs' ? '.rcard[data-id]' : S.route === 'overview' ? '[data-tl="recs-a1"] [data-act="openRec"][data-id]' : S.route === 'l-home' ? '[data-tl="recs-lite"] [data-id]' : '.l-rc[data-id]')].map((el) => el.dataset.id).filter(lvRecLive);
    if (ids.length) TL.recs.viewed(surface, Array.from(new Set(ids))).catch(() => {});
  };
  const lvBasePop = renderPop;
  renderPop = function () {
    lvRecSync(['menubar']);
    lvBasePop.apply(this, arguments);
    const b = document.querySelector('[data-act="popRec"][data-id]');
    if (b && lvRecLive(b.dataset.id)) TL.recs.viewed('menubar', [b.dataset.id]).catch(() => {});
  };

  // ---- actions ----
  const ex = (id, surface, action) => { if (lvRecLive(id)) TL.recs.exposure(id, surface, action).catch(() => {}); };
  const A = Object.assign({}, ACT);
  ACT.selRec = (el, e) => { const was = S.recs.sel; A.selRec(el, e); if (S.recs.sel !== was) ex(S.recs.sel, 'A7', 'open'); };
  ACT.openRec = (el) => { const sf = el.closest && el.closest('[data-tl="recs-a1"]') ? 'A1' : S.pop ? 'menubar' : 'A7'; A.openRec(el); ex(el.dataset.id, sf, 'open'); };
  ACT.popRec = (el) => { ex(el.dataset.id, 'menubar', 'open'); A.popRec(el); };
  ACT.recTab = (el) => { A.recTab(el); if (el.dataset.v === 'preview') ex(S.recs.sel, 'A7', 'preview'); };
  ACT.copyRec = (el) => { A.copyRec(el); ex(el.dataset.id, S.route === 'recs' ? 'A7' : 'lite', 'copy'); };
  // 不适用 / 稍后 / 不再推荐同类: a label, hidden at once, undo within 8 seconds (DELETE /v1/labels/{id})
  const REASONS = [['has_equivalent', '已有等价配置'], ['dont_want', '不想要这类改动'], ['env_mismatch', '环境不匹配'], ['wrong_diagnosis', '诊断不对'], ['other', '其他原因']];
  function feedback(id, label, reason, msg) {
    const prevSel = S.recs.sel; S.recs.gone.add(id); render();
    const p = TL.recs.label(id, label, reason).then((res) => { const lid = res.data && res.data.label_id; if (lid) LVR.labels.set(id, lid); TL.recs.invalidate(); return lid; }, (e) => { S.recs.gone.delete(id); render(); toast('没能保存反馈（' + (e.code || e.message) + '），建议已恢复'); return null; });
    toast(msg, { act: '撤销', sec: 8, onAct: () => { S.recs.gone.delete(id); S.recs.sel = prevSel; render(); p.then((lid) => { if (!lid) return; LVR.labels.delete(id); TL.recs.unlabel(lid).then(() => TL.recs.invalidate(), () => toast('撤销没有保存到本机服务')); }); } });
  }
  ACT.dismissRec = (el) => {
    const id = el.dataset.id;
    if (!lvRecLive(id)) return A.dismissRec(el);
    openDD(el, [{ h: '不适用 · 原因' }].concat(REASONS.map((x) => ({ t: x[1], v: 'na:' + x[0] })), [{ sep: 1 }, { t: '稍后再说 · 7 天内不再出现', v: 'snooze' }, { t: '不再推荐同类建议', v: 'mute' }]), (v) => {
      if (v === 'snooze') feedback(id, 'snooze', null, '已推迟，7 天内不再出现');
      else if (v === 'mute') feedback(id, 'mute', null, '不再推荐同类建议');
      else feedback(id, 'not_applicable', String(v).slice(3), '已标记「不适用」，同类建议会降权');
    });
  };
  ACT.restoreRecs = () => {
    const pend = [...LVR.labels.values()]; LVR.labels.clear(); A.restoreRecs();
    if (pend.length) Promise.all(pend.map((lid) => TL.recs.unlabel(lid).catch(() => null))).then(() => TL.recs.invalidate());
  };
  ACT.recalc = () => {
    if (!LVR.applied && lvRecDegraded()) return A.recalc();
    const c = $('#content'); if (c) c.classList.add('stale');
    TL.recs.recompute(lvScope(), true).then((res) => {
      TL.recs.invalidate();
      toast(res.status === 202 ? '正在重新计算建议…' : '建议已按最新数据重算');
    }, (e) => { if (c) c.classList.remove('stale'); toast(e.code === 'no_projection' ? '还没有可分析的数据，导入会话后再试' : '重新计算失败（' + (e.code || e.message) + '）'); });
  };
  TL.on('event', (e) => { if ((e.name === 'job' && e.data && /recommend/.test(e.data.kind || '') && e.data.status === 'succeeded') || e.name === 'data.published') TL.recs.invalidate(); });
}

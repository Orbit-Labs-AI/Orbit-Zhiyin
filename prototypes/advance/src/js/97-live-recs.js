/* ============ live binding: recommendations (OrbitLive.recs, js/06-live-client.js) ============
   Mock mode changes nothing. In live mode the demo renderers stay as they are (A7 cards and detail, A1「本周建议」, Lite
   l-home「本周最值得做的一件事」and l-recs, menubar「本周最值得做」): this file swaps the rows they read (RECS / RECI / REC_X)
   for GET /v1/recommendations, and recOrder / recTop(surface) put the backend's stable top slate (surface A1 / lite / menubar) first.
   - Recommendations are personal data: live mode drops the demo rows at load (RECS / RECI / REC_X; ?demo=1 keeps them).
     No run yet (cold start), 0 cards, a missing / down endpoint (404 / 501 / 503 / offline) or computing all render the
     A7 page's own honest empty state, never demo rows. Live once: later failures keep the last live rows (strip: 刷新失败).
   - Rows carry the real agents (target.agents → LV.agentOf → AG ids; native vs 转换), the saving shares from ui.save (time /
     token % of the real trajectory), the resident token share from ui.tok_pct and the source link.
     获取 / 预览并安装 runs the real install sheet (97-live-library-install
     liInstall, source {type:'candidate'}): plan → preview → confirm → apply with the preview_digest; 撤销 reverts by install_id.
   - Writes: view / open / preview / copy exposure; 不适用 / 稍后 / 不再推荐同类 are labels with an 8-second undo
     (DELETE /v1/labels/{id}); 重新计算 is POST /v1/recommendations/recompute. Each write invalidates the rec resources. */
const LVR = { applied: null, top: {}, rel: {}, labels: new Map(), poll: 0, detail: {} };
const LVR_SURFACES = ['A1', 'lite', 'menubar'];
const LVR_ROUTES = { recs: 'A7', 'l-recs': 'lite', overview: 'A1', 'l-home': 'lite' };
const LVR_DEGRADE = (e) => !e || !e.status || e.status === 404 || e.status === 501 || e.status === 503;
const lvRecLive = (id) => !!(RECI[id] && RECI[id].live);

// Live: recommendations are personal, so the demo rows never show (development keeps them with ?demo=1).
if (TL.mode === 'live' && !LV.demo) {
  RECS.length = 0; Object.keys(RECI).forEach((k) => { delete RECI[k]; }); Object.keys(REC_X).forEach((k) => { delete REC_X[k]; });
  S.installed.clear(); S.recs.sel = null;
}
// Cand → RECS row: the shared mapper (OrbitLive.recs.row) plus real agents, ui.save / ui.tok_pct and the source link.
function lvRecRow(c) {
  const r = OrbitLive.recs.row(c); const u = c.ui || {};
  r.expertAdvice = Array.isArray(c.expert_advice) ? c.expert_advice.slice(0, 3) : [];
  const nat = c.agents || {}; const bids = ((c.target && c.target.agents) || Object.keys(nat)).filter(Boolean);
  const ids = [], parts = []; r.native = Object.keys(nat).filter((k) => nat[k] === 'native').map((b) => LV.agentOf(b).id);
  bids.forEach((b) => { const m = LV.agentOf(b); if (ids.indexOf(m.id) >= 0) return; ids.push(m.id); parts.push(r.native.indexOf(m.id) >= 0 ? m.name : '转换给 ' + m.short); });
  r.agents = ids; r.bagents = bids;
  if (ids.length) r.compat = parts.join(' · ');
  // r.x.pct (shares of the real trajectory) and r.x.tokp come from ui.save / ui.tok_pct via OrbitLive.recs.row; tok in k
  const sv = u.save && typeof u.save === 'object' ? u.save : null;
  r.x.tok = typeof u.tok === 'number' ? Math.round(u.tok / 100) / 10 : null;
  if (Array.isArray(u.n) && u.n[0] != null) r.x.n = [u.n[0], u.n[1] != null ? u.n[1] : u.n[0]];
  // evidence: catalog rows matched only by profile have no session behind them, so they say what matched instead of 0 个会话
  const evN = ((c.evidence || {}).counts || {}).sessions || ((c.evidence || {}).session_uids || []).length || 0; r.evN = evN;
  r.why = lvRecBrief(r.why && r.why !== r.title ? r.why : c.summary) || lvRecBrief(c.summary) || '';
  if (sv) r.saveBasis = sv.basis || null;   // 未估算: why (no problem evidence, no ledger yet …)
  if (!evN) {
    const m = ((c.feature_overlap || {}).matched || []).map((t) => String(t).replace(/^[a-z_]+:/, '')).filter((t, i, a) => t && a.indexOf(t) === i).slice(0, 3);
    r.ev = m.length ? '技术栈匹配 · ' + m.join(' · ') : '按使用画像匹配';
    if (/^0 个会话/.test(r.gain) || r.gain === '—') r.gain = '尚无会话证据 · 安装后开始追踪';
  }
  // B07: catalog-only matches (bucket 资料库推荐 / basis catalog_only) get their own section after the evidence cards
  r.lib = c.bucket === '资料库推荐' || c.basis === 'catalog_only';
  const src = c.source || {}; r.url = src.url || null; r.license = src.license || null; r.origin = src.origin || null; r.item_id = src.item_id || null;
  return r;
}
// one-line card text from a backend reason / catalog description: first non-empty line, first sentence when long, ≤ 90 chars
// B08: catalog descriptions can carry the index's raw `agent: … command: … dimension: …` metadata; those tokens never show
const LVR_TAGDUMP = /(?:^|\s)(?:agent|command|dimension|domain|file_type|friction|software|tag|kind|lang|language|topic|scene|tool|ftype|cmd):\s*\S+/gi;
const lvRecStrip = (t) => String(t || '').split(/\n+/).map((x) => x.replace(LVR_TAGDUMP, '').replace(/\s{2,}/g, ' ').trim()).filter(Boolean).join('\n');
function lvRecBrief(t) {
  let s = lvRecStrip(t).split(/\n+/).map((x) => x.trim()).find(Boolean) || '';
  if (s.length > 60) { const m = s.match(/^.{12,}?(?:[。！？]|[.!?](?=\s|$))/); if (m) s = m[0]; }
  s = s.replace(/\s*[—–-]\s*$/, '');
  if (s.length <= 90) return s;
  let cut = s.slice(0, 88); const sp = Math.max(cut.lastIndexOf(' '), cut.lastIndexOf('，'), cut.lastIndexOf('、')); if (sp > 50) cut = cut.slice(0, sp);
  return cut.replace(/[\s,，、;；:：—–-]+$/, '') + '…';
}
// installs made through the real sheet (install state: candidate_id / catalog source) mark the A7 card 已安装 · 追踪中
function lvRecInstalls() {
  if (typeof liState !== 'function') return;
  const st = liState().data; if (!st) return;
  RECS.forEach((r) => {
    const row = (st.items || []).find((i) => !/^(reverted|archived)$/.test(i.state) && (i.candidate_id === r.id || (i.source_type === 'candidate' && i.source_id === r.id) || (r.item_id && i.source_type === 'catalog' && i.source_id === r.item_id)));
    const cur = S.installed.get(r.id);
    const has = r.track.some((t) => t[2] != null);   // the 7-day verdict needs the outcome's after values (detail)
    if (row) { const days = Math.max(1, Math.min(has ? 7 : 6, Math.floor((Date.now() - (row.installed_at || Date.now())) / 86400000) + 1)); if (!cur || cur.install_id !== row.install_id || cur.days !== days) S.installed.set(r.id, { days, live: true, install_id: row.install_id, at: row.installed_at, scope: row.scope === 'project' ? 'proj' : 'global', target: '' }); }
    else if (cur && cur.live && !cur.fresh) S.installed.delete(r.id);
  });
}
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
  const rows = (data.items || []).map(lvRecRow);
  RECS.splice(0, RECS.length, ...rows);
  Object.keys(RECI).forEach((k) => { if (RECI[k].live) delete RECI[k]; });
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
// A7 state while no live row is on screen: pending | computing | empty (no run / 0 cards) | error (missing, down, offline)
function lvRecState() {
  const r = TL.recs.resource('A7', lvScope());
  if (LVR.applied) return (LVR.applied.items || []).length ? 'ready' : r.state === 'computing' ? 'computing' : 'empty';
  if (r.state === 'error') return 'error';
  if (r.state === 'computing') return 'computing';
  return 'pending';
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

// A7 without live rows: the page's own toolbar, dimension row and two-column layout with an honest state, never demo rows.
function lvRecEmptyPage() {
  const st = lvRecState(); const run = LVR.applied && LVR.applied.run;
  const msg = { pending: null, computing: '正在根据你的会话计算建议…', error: '建议服务暂时不可用，稍后自动重试。', empty: run ? '这次分析没有找到值得改的地方。导入更多会话或过几天再看。' : '还没有建议：Orbit 需要先分析你导入的会话。导入完成后会自动计算，也可以点「重新计算」。' }[st];
  const dims = (LVR.applied && LVR.applied.dims) || DIMS.map((d) => ({ id: d[0], label: d[1], count: 0 }));
  const body = msg ? '<div class="card pad col" data-tl="recs-empty" data-state="' + st + '" style="gap:10px;align-items:flex-start"><span class="eb">优化建议</span><p class="serif" style="margin:0;font-size:17px;line-height:1.5">' + esc(msg) + '</p>' + (st === 'error' ? '' : '<button type="button" class="btn" data-act="recalc">' + ic('sync', 14) + '重新计算</button>') + '</div>' : LV.pend(160);
  return tbar('优化建议', st === 'pending' ? '' : '0 条' + (run && run.created_at ? ' · ' + lvRecWhen(run.created_at) + ' 更新' : ''), '<button type="button" class="btn" data-act="recalc">' + ic('sync', 14) + '重新计算</button><button type="button" class="btn ai" data-act="ask" data-ctx="recs">' + ic('spark', 14) + '让本地 Agent 深度诊断</button>') +
    '<div class="content" id="content"><div class="frow"><div class="seg" role="tablist" aria-label="优化维度">' + dims.map((d) => '<button type="button" role="tab" data-act="recDim" data-v="' + esc(d.id) + '" class="' + (S.recs.dim === d.id ? 'on' : '') + '" aria-selected="' + (S.recs.dim === d.id) + '">' + esc(d.label) + '<span class="mono" style="font-size:11px;color:var(--ink-3);font-weight:500">' + TLU.num(d.count || 0) + '</span></button>').join('') + '</div></div>' +
    '<div class="recs"><div class="stack">' + body + '</div><div style="position:sticky;top:0">' + empty(st === 'pending' ? '正在读取建议…' : '有建议后，这里显示说明、预览和效果追踪') + '</div></div></div>';
}
const lvRecWhen = (ms) => { const d = new Date(ms); return isNaN(d) ? '—' : (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日 ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
// toolbar subtitle of the A7 page (46-a7-recs.js): the live run's time instead of the demo's fixed one
function lvRecUpdated() { const run = LVR.applied && LVR.applied.run; return run && run.created_at ? lvRecWhen(run.created_at) + ' 更新' : '尚未计算'; }

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
  TL_PAGES.recs = function () { lvView('recs'); lvRecSync(); lvRecInstalls(); return RECS.length || LV.demo ? baseRecs() : lvRecEmptyPage(); };
  TL_PAGES.recs.after = baseRecs.after;
  PAGES.recs = TL_PAGES.recs;
  PAGES['l-recs'] = function () { lvView('recs'); lvRecSync(['lite']); lvRecInstalls(); return baseLiteRecs(); };
  if (baseLiteRecs.after) PAGES['l-recs'].after = baseLiteRecs.after;
  // overview / Lite home render their own 本周建议 / 本周最值得做的一件事 from RECS + recTop: only load the slates here
  const baseOv = PAGES.overview, baseLiteHome = PAGES['l-home'];
  PAGES.overview = function () { lvRecSync(['A1']); return baseOv.apply(this, arguments); };
  PAGES['l-home'] = function () { lvRecSync(['lite']); return baseLiteHome.apply(this, arguments); };
  ['overview', 'l-home'].forEach((k) => { const b = k === 'overview' ? baseOv : baseLiteHome; if (b.after) PAGES[k].after = b.after; });

  // ---- render: 示例数据 when degraded, relations tags, view exposure ----
  const lvBaseRender = render;
  render = function () {
    lvBaseRender();
    const c = $('#content'); if (!c) return;
    const surface = LVR_ROUTES[S.route];
    if (!surface) return;
    const selected = RECI[S.recs.sel];
    if (S.route === 'recs' && S.recs.tab === 'why' && selected && (selected.expertAdvice || []).length) {
      const ev = c.querySelector('.rc-ev');
      if (ev && !c.querySelector('[data-tl="expert-advice"]')) ev.insertAdjacentHTML('beforebegin', '<div class="col" style="gap:10px;margin-bottom:14px" data-tl="expert-advice"><b style="font-size:13px">AI 补充建议 · 待验证</b>' + selected.expertAdvice.map((a, i) => '<div class="col" style="gap:6px;padding:10px;border:1px solid var(--line);border-radius:8px"><b style="font-size:13px">' + esc(a.title) + '</b><div style="font-size:12px;line-height:1.6">' + esc(a.summary) + '</div><ol style="margin:0;padding-left:18px;font-size:12px;line-height:1.6">' + (a.steps || []).map((s) => '<li>' + esc(s) + '</li>').join('') + '</ol><div class="cap" style="font-size:11px">依据：' + esc((a.evidence_ids || []).join('、') || '尚无具体证据') + '</div>' + (a.limitations || []).map((s) => '<div class="cap" style="font-size:11px">' + esc(s) + '</div>').join('') + '<div class="row"><span class="cap" style="font-size:11px;flex:1">效果尚未实测，先审阅再应用</span><button type="button" class="btn sm" data-act="recExpertStudio" data-id="' + esc(selected.id) + '" data-i="' + i + '">交给生成工坊</button></div></div>').join('') + '</div>');
    }
    if (S.route === 'recs' && S.recs.tab === 'why' && LVR.rel[S.recs.sel]) {
      const ev = c.querySelector('.rc-ev');
      if (ev && !c.querySelector('[data-tl="rec-rel"]')) ev.insertAdjacentHTML('beforebegin', '<div class="row" style="flex-wrap:wrap" data-tl="rec-rel">' + LVR.rel[S.recs.sel].map((p) => { const o = RECI[p.a === S.recs.sel ? p.b : p.a]; return o ? '<span class="tag" data-tip="' + esc(p.reason || '') + '">' + (p.relation === 'conflicts' ? '与「' : '可搭配「') + esc(o.title.split('：')[0]) + '」' + (p.relation === 'conflicts' ? '冲突' : '') + '</span>' : ''; }).join('') + '</div>');
    }
    if (S.route === 'recs' && lvRecLive(S.recs.sel)) lvRecDetail(S.recs.sel);
    const ids = [...c.querySelectorAll(S.route === 'recs' ? '.rcard[data-id]' : S.route === 'overview' ? '.ov-recs [data-act="openRec"][data-id]' : S.route === 'l-home' ? '.l-one [data-id]' : '.l-rc[data-id]')].map((el) => el.dataset.id).filter(lvRecLive);
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
  ACT.openRec = (el) => { const sf = el.closest && el.closest('.ov-recs') ? 'A1' : S.pop ? 'menubar' : 'A7'; A.openRec(el); ex(el.dataset.id, sf, 'open'); };
  ACT.recExpertStudio = (el) => {
    const r = RECI[el.dataset.id], advice = r && r.expertAdvice[+el.dataset.i]; if (!advice) return;
    if (S.studio.run && !S.studio.run.done && !S.studio.run.stopped) { toast('生成工坊正在运行，先停止或等它完成'); return; }
    S.studio.type = { skill: 'Skill', hook: 'Hook', prompt: '规则', workflow: '工作流' }[advice.kind] || '规则';
    S.studio.goal = [advice.title, advice.summary, ...(advice.steps || []), ...(advice.limitations || []).map((s) => '约束：' + s)].filter(Boolean).join('\n');
    S.studio.from = 'AI 建议「' + advice.title + '」'; S.studio.run = null; go('studio');
  };
  // 预览并安装: the real install sheet (plan → preview → apply with the preview digest); 撤销 reverts by install_id
  ACT.install = (el) => {
    const r = RECI[el.dataset.id];
    if (!r || !r.live || typeof liInstall !== 'function') return A.install(el);
    if (S.installed.has(r.id)) return ACT.openRec({ dataset: { id: r.id, tab: 'track' } });
    const surface = /^l-/.test(S.route) ? 'lite' : S.pop ? 'menubar' : S.route === 'overview' ? 'A1' : 'A7';
    liInstall({ item_id: 'cand:' + r.id, name: r.title.split('：')[0], kind: r.type, agents: r.bagents, summary: r.why, source: { type: 'candidate', id: r.id }, surface,
      onDone: (res) => { S.installed.set(r.id, { days: 1, live: true, fresh: true, install_id: res.install_id, at: Date.now(), scope: 'global', target: (res.written || []).map((w) => w.display).join('、') }); } });
  };
  ACT.doUninstall = (el) => {
    const id = el.dataset.id; const inst = S.installed.get(id);
    if (!inst || !inst.live || typeof liUndo !== 'function') return A.doUninstall(el);
    closeModal(); liUndo(inst.install_id, RECI[id] ? RECI[id].title.split('：')[0] : id).then((ok) => { if (ok) { S.installed.delete(id); render(); } });
  };
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
    if (!LVR.applied && lvRecDegraded()) { toast('建议服务暂不可用，稍后再试'); return; }
    const c = $('#content'); if (c) c.classList.add('stale');
    TL.recs.recompute(lvScope(), true).then((res) => {
      TL.recs.invalidate();
      toast(res.status === 202 ? '正在重新计算建议…' : '建议已按最新数据重算');
    }, (e) => { if (c) c.classList.remove('stale'); toast(e.code === 'no_projection' ? '还没有可分析的数据，导入会话后再试' : '重新计算失败（' + (e.code || e.message) + '）'); });
  };
  TL.on('event', (e) => { if ((e.name === 'job' && e.data && /recommend/.test(e.data.kind || '') && e.data.status === 'succeeded') || e.name === 'data.published') TL.recs.invalidate(); });
}

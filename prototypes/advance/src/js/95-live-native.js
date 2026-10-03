/* ============ live: native shell + first run (slice 7) ============
   Native (window.__ORBIT_NATIVE__, any mode): body.native layout (20-window.css), window ops through ORBIT.native.post
   (22-window.js nativeWin), host menu commands (tandem:command → settings / palette / about / route / toggleEdition / refresh).
   Live first run: /v1/app/state with no projection or no enabled source opens onboarding by itself; step 1 lists the sources of
   /v1/shell/onboarding (+ /v1/app/discovery) with estimates, 添加文件夹 = LVN.addSource() (native chooseFolder, browser: the
   path field) → POST /v1/app/sources; 开始分析 aligns the sources, PATCHes recent_days and POSTs an import job; job frames
   (polled as a fallback) drive the four stages; once published the spine reloads, the server persona
   (/v1/uiview/persona/reveal, else /v1/shell/reveal) feeds the unchanged Genesis sequence, settings get onboarded:true and the
   catalog syncs. Mock mode (file://) only gets the native layout when a host flag is present, which it never is. */
const LVN = { ACTIVE: ['queued', 'pending', 'running'], appState: null };
(function nativeLayout() {
  const n = ORBIT.native; if (!n.isNative) return;
  document.body.classList.add('native');
  if (n.surface) document.body.classList.add('surface-' + n.surface);
})();

/* ---- host menu commands ---- */
LVN.refresh = function () {
  if (!LV.live) { reindex(); return; }
  TL.invalidate(); LV.loadSpine(); TL.changed();
  toast('正在刷新');
};
LVN.command = function (d) {
  const cmd = d && d.cmd; if (!cmd) return;
  if (cmd === 'settings') { closeModal(); openSettings(d.tab || undefined); }
  else if (cmd === 'palette') { closeModal(); openPalette(); }
  else if (cmd === 'about') { closeModal(); openAbout(); }
  else if (cmd === 'toggleEdition') edToggle();
  else if (cmd === 'refresh') LVN.refresh();
  else if (cmd === 'route') {
    const r = String(d.route || '').replace(/^#/, '');
    if (r === 'settings' || /^settings[:/]/.test(r)) { openSettings(r.split(/[:/]/)[1] || undefined); return; }
    if (r === 'onboarding') { openOnboarding(0); return; }
    if (PAGES[r]) { if (OVL) { closeOverlay(); } closeModal(); if (/^l-/.test(r) !== (S.ed === 'lite')) edSet(/^l-/.test(r) ? 'lite' : 'advance'); go(r); }
  }
};
ORBIT.native.onCommand((d) => { try { LVN.command(d); } catch (e) { console.error('tandem:command', e); } });

/* ---- sources ---- */
const LVN_PATHS = [[/\.claude\b|claude/i, 'claude_code'], [/\.codex\b|codex/i, 'codex'], [/gemini/i, 'gemini'], [/copilot/i, 'copilot'],
  [/kimi/i, 'kimi'], [/hermes/i, 'hermes'], [/opencode/i, 'opencode'], [/deepseek|\bdsh\b|\.dsh/i, 'dsh'], [/(^|\/)\.?pi(\/|$)/i, 'pi']];
LVN.agentFromPath = (path) => { const hit = LVN_PATHS.find((x) => x[0].test(path || '')); return hit ? hit[1] : null; };
// addSource({agent?, path?, purpose?}) → {ok, source, agent, root} | {cancelled:true}; throws {message, path?} on failure.
// In the native shell it asks the host for a folder (chooseFolder → tandem:folder); in a browser the caller passes path.
LVN.addSource = async function (o) {
  o = o || {};
  let path = o.path;
  if (!path) {
    if (!ORBIT.native.hasHost()) return { cancelled: true, needPath: true };
    const r = await ORBIT.native.request('chooseFolder', { purpose: o.purpose || 'source', agent: o.agent && o.agent !== 'auto' ? o.agent : undefined, defaultPath: o.defaultPath || '~/' });
    if (!r || r.cancelled || !r.path) return { cancelled: true };
    path = r.path;
  }
  const agent = o.agent && o.agent !== 'auto' ? o.agent : LVN.agentFromPath(path);
  if (!agent) throw Object.assign(new Error('认不出这是哪个 Agent 的目录，先在左边选择 Agent'), { path });
  try {
    const res = await TL.send('POST', '/v1/app/sources', { agent, root: path, enabled: true });
    return { ok: true, source: res.data, agent, root: path };
  } catch (e) { throw Object.assign(new Error(e.status === 422 ? '这个文件夹不能作为来源：' + (e.message || '') : e.message || '添加失败'), { path, status: e.status }); }
};
const lvnBody = (r) => (r && r.data != null ? r.data : null);
const lvnTry = (path, o) => TL.get(path, o || {}).then(lvnBody, () => null);
// OB.live.sources from /v1/shell/onboarding (estimates, earliest mtime) merged with /v1/app/discovery (status, enabled)
LVN.loadOb = async function (ob) {
  const L = ob.live; L.state = 'loading'; if (OVL === 'ob' && OB === ob && ob.step === 1) drawOB();
  const [sh, disc] = await Promise.all([lvnTry('/v1/shell/onboarding'), lvnTry('/v1/app/discovery')]);
  if (OB !== ob) return;
  const map = new Map();
  (Array.isArray(disc) ? disc : []).forEach((x) => { if (x && x.agent) map.set(x.id || x.agent + ':' + x.root, { id: x.id || x.agent + ':' + x.root, agent: x.agent, root: x.root, files: x.files, est: x.files || 0, status: x.status || 'available', enabled: !!x.enabled, earliest: null }); });
  ((sh && sh.sources) || []).forEach((x) => {
    if (!x || !x.agent) return; const id = x.id || x.agent + ':' + x.root; const cur = map.get(id) || {};
    map.set(id, Object.assign(cur, { id, agent: x.agent, root: x.root, files: x.files, est: x.est_sessions != null ? x.est_sessions : x.files || 0, status: x.status || cur.status || 'available', enabled: !!x.enabled, earliest: x.earliest_mtime || null }));
  });
  const rank = (x) => (x.status === 'available' ? 0 : x.status === 'empty' ? 1 : 2);
  L.sources = Array.from(map.values()).sort((a, b) => rank(a) - rank(b) || (b.est || 0) - (a.est || 0) || (lvAgentOf(a.agent).slot || 99) - (lvAgentOf(b.agent).slot || 99));
  if (!L.touched) {
    const on = L.sources.filter((x) => x.enabled && x.status !== 'permission_denied');
    L.sel = new Set((on.length ? on : L.sources.filter((x) => x.status === 'available')).map((x) => x.id));
  } else L.sel = new Set(Array.from(L.sel).filter((id) => map.has(id)));
  if (sh && sh.settings && !L.touched) OB.recent = sh.settings.recent_days != null;
  L.stagesBase = sh && sh.progress && sh.progress.stages || null;
  L.semantic = sh && sh.semantic || null;
  L.state = sh || disc ? 'ready' : 'error'; L.loadErr = sh || disc ? null : '本机服务没有返回来源列表';
  lvnSyncSrc(L);
  if (OVL === 'ob' && OB === ob && ob.step === 1) drawOB();
};
function lvnSyncSrc(L) { OB.src = new Set(L.sources.filter((x) => L.sel.has(x.id)).map((x) => lvAgentOf(x.agent).id)); }

/* ---- import: job frames → the four stages → Genesis ---- */
const LVN_STAGES = OB_TEXT.stages;   // names / notes: OB_TEXT in 56-onboarding.js
function lvnStages(L) {
  const base = {}; (L.stagesBase || []).forEach((x) => { base[x.id] = x; });
  return LVN_STAGES.map(([id, label]) => {
    const b = base[id] || {};
    const sem = id === 'semantic' && (!L.semantic || !L.semantic.enabled);
    return { id, label: b.label || label, status: sem ? 'skipped' : 'pending', done: null, total: null, note: sem ? (L.semantic && L.semantic.note) || b.note || OB_TEXT.semanticOff : null };
  });
}
function lvnStage(L, id, patch) { const s = (L.stages || []).find((x) => x.id === id); if (s) Object.assign(s, patch); }
// A job frame only moves numbers: when the stage list keeps its shape (statuses, error, done) the open sheet is patched in
// place (notes, counts, bar) instead of rebuilt, and the sidebar entry follows; a shape change redraws the sheet.
function lvnShape(L) { return [L.err || '', L.done ? 1 : 0, L.starting ? 1 : 0, L.job ? L.job.status : '', (L.stages || []).map((x) => x.id + ':' + x.status).join(',')].join('|'); }
function lvnPatch(L) {
  const o = $('#overlay'); const box = o && o.querySelector('[data-ob="stages"]'); if (!box) return false;
  (L.stages || []).forEach((x) => {
    const row = box.querySelector('[data-stage="' + x.id + '"]'); if (!row) return;
    const col = row.querySelector('.col'); let n = col && col.querySelector('.s');
    if (x.note) { if (!n && col) { n = document.createElement('span'); n.className = 's'; col.appendChild(n); } if (n && n.textContent !== x.note) n.textContent = x.note; } else if (n) n.remove();
    const c = row.lastElementChild; const t = x.total ? fmt(x.done || 0) + ' / ' + fmt(x.total) : x.status === 'skipped' ? OB_TEXT.skipped : '';
    if (c && c.textContent !== t) c.textContent = t;
  });
  const pr = L.job && L.job.progress || {}; const bar = o.querySelector('[data-ob="bar"]');
  if (bar) bar.style.width = (pr.total ? Math.round(clamp(pr.completed / pr.total, 0, 1) * 100) : 4) + '%';
  return true;
}
function lvnDraw(ob) {
  const L = ob.live;
  if (OVL === 'ob' && OB === ob && ob.step === 1) {
    const sh = lvnShape(L);
    if (sh !== L.shape || ob.drawn !== 1 || !lvnPatch(L)) { L.shape = sh; drawOB(); }
  }
  LVN.sidePatch();
}
function lvnJob(ob, job) {
  const L = ob.live; if (!job || !L.job || job.id !== L.job.id) return;
  L.job = Object.assign({}, L.job, job);
  const pr = L.job.progress || {}; const st = L.job.status;
  if (LVN.ACTIVE.indexOf(st) >= 0) lvnStage(L, 'backfill', { status: 'running', done: pr.completed != null ? pr.completed : null, total: pr.total != null ? pr.total : null, note: OB_TEXT.stageNote(pr.stage) || (st === 'queued' ? OB_TEXT.queued : null) });
  else if (st === 'completed') { lvnStage(L, 'backfill', { status: 'done', done: pr.total != null ? pr.total : pr.completed, total: pr.total, note: null }); lvnAfter(ob); }
  else { lvnStage(L, 'backfill', { status: 'failed', note: (L.job.error && (L.job.error.message || L.job.error)) || OB_TEXT.failed }); L.err = '导入没有完成：' + ((L.job.error && (L.job.error.message || L.job.error)) || st); lvnStop(L); }
  lvnDraw(ob);
}
function lvnStop(L) { if (L.poll) clearInterval(L.poll); L.poll = null; if (L.off) L.off(); L.off = null; }
function lvnWatch(ob) {
  const L = ob.live; lvnStop(L);
  L.off = TL.on('event', (ev) => { if (ev.name === 'job' && ev.data) lvnJob(ob, ev.data); });
  L.poll = setInterval(() => {
    if (!L.job || L.after) return lvnStop(L);
    TL.send('GET', '/v1/app/jobs/' + encodeURIComponent(L.job.id)).then((r) => lvnJob(ob, r.data), () => { /* frames still come */ });
  }, 1500);
}
const lvnSleep = (ms) => new Promise((r) => setTimeout(r, ms));
// the projection revision the import just published (/v1/app/state storage.data_rev); analysis answers older than it are partial
LVN.dataRev = async function () { const st = await lvnTry('/v1/app/state'); return st && st.storage && st.storage.data_rev != null ? +st.storage.data_rev : null; };
const lvnRevOf = (meta) => (meta && meta.data_rev != null ? +meta.data_rev : null);
// spine reloaded after the import: a 200 can still be the previous snapshot (freshness stale, data_rev older than the import)
// while the analysis job recomputes, so keep reloading until the spine's data_rev reaches the published one (or time runs out)
async function lvnSpine(rev0, target) {
  const t0 = Date.now();
  LV.loadSpine();
  let k = 0;
  while (Date.now() - t0 < 30000) {
    const fresh = target == null || lvnRevOf(LV.meta) == null || lvnRevOf(LV.meta) >= target;
    if (LV.rev > rev0 && LV.state !== 'computing' && LV.state !== 'connecting' && fresh) return true;
    await lvnSleep(400);
    if (++k % 3 === 0) LV.loadSpine();
  }
  return LV.rev > rev0 && LV.state === 'ready' ? 'partial' : false;
}
// server persona → the persona(L) shape Genesis reads ({ok, classified, n, v, code, zh, en, line, conf}) + its candidates
LVN.personaOf = function (d) {
  if (!d || d.ok === false || !d.code) return { p: { ok: false, classified: false, n: d && d.n || 0 }, cands: [] };
  const v = { D: 50, I: 50, M: 50, V: 50 };
  (d.axes || []).forEach((a) => { const k = a.k || a.axis; if (k in v && a.value != null) v[k] = +a.value; });
  if (d.v) Object.keys(v).forEach((k) => { if (d.v[k] != null) v[k] = +d.v[k]; });
  const p = { ok: true, classified: d.classified != null ? !!d.classified : d.code.indexOf('?') < 0, n: d.n || 0, v, code: d.code, zh: d.zh || (d.type && d.type.zh) || '尚未定型', en: d.en || (d.type && d.type.en) || 'Undetermined', line: d.line || '', conf: d.conf || '—', server: true };
  const cands = (d.candidates || d.matches || []).map((c) => ({ c: c.code, zh: c.zh || (TYPES[c.code] || [])[0] || '', en: c.en || (TYPES[c.code] || [])[1] || '', sim: clamp(Math.round(c.match != null ? c.match : c.sim || 0), 3, 99) })).filter((c) => c.c);
  return { p, cands };
};
// The reveal waits for the analysis of the published revision (target); a stale answer from an older snapshot is only used
// when time runs out, and then it is marked partial so Genesis says so instead of presenting it as the final card.
LVN.reveal = async function (period, target) {
  const q = { period: period || '90', display_timezone: TL_TZ || 'UTC' };
  let stale = null;
  for (let i = 0; i < 16; i++) {
    let r = null;
    try { r = await TL.get('/v1/uiview/persona/reveal', { query: q, waitMs: 1500 }); } catch (e) { r = { state: 'error', error: e }; }
    if (r && r.data != null && r.state !== 'computing') {
      const rv = lvnRevOf(r.meta) != null ? lvnRevOf(r.meta) : lvnRevOf(r.data && r.data.meta);
      const old = target != null && (r.state === 'stale' || (rv != null && rv < target));
      if (!old) return LVN.personaOf(r.data);
      stale = r.data;
    }
    if (r && r.state === 'error') break;
    await lvnSleep(600);
  }
  if (stale) { const x = LVN.personaOf(stale); x.p.partial = true; return x; }
  const sh = await lvnTry('/v1/shell/reveal', { query: { display_timezone: TL_TZ || 'UTC' } });
  return LVN.personaOf(sh && sh.reason !== 'computing' ? sh : null);
};
// Recommendations for Genesis' 看看优化建议 line: load the A7 list once (it may still be computing right after the import)
LVN.loadRecs = async function (ms) {
  if (typeof lvRecSync !== 'function' || TL.mode !== 'live') return;
  const t0 = Date.now(); TL.recs.invalidate();
  while (Date.now() - t0 < (ms || 8000)) {
    const r = TL.recs.resource('A7', lvScope());
    try { await TL.load(r); } catch (e) { return; }
    if (r.data) { lvRecSync(); return; }
    if (r.state !== 'computing') return;
    await lvnSleep(800); r.dirty = true;
  }
};
async function lvnAfter(ob) {
  const L = ob.live; if (L.after) return; L.after = true; lvnStop(L); L.err = null;
  lvnStage(L, 'stats', { status: 'running', note: null }); lvnStage(L, 'persona', { status: 'pending', note: null }); lvnDraw(ob);
  // the import is in but the analysis did not come back: keep the first run open (no onboarded:true) and offer a retry
  const target = await LVN.dataRev();
  const spun = await lvnSpine(L.rev0, target);
  if (!spun || !ALL.length) {
    L.after = false;
    lvnStage(L, 'stats', { status: 'failed', note: ALL.length ? '本机服务没有返回分析结果' : '没有读到会话' });
    L.err = ALL.length ? '会话已导入，但分析结果暂时读不到（本机服务没有响应）。可以重试。' : '导入完成，但没有读到任何会话。检查来源目录后重试。';
    if (OB !== ob || OVL !== 'ob') notify({ t: '首次分析没有完成', b: L.err, a1: '重试', on1: () => { openOnboarding(1); } });
    lvnDraw(ob); return;
  }
  lvnStage(L, 'stats', { status: 'done', note: fmt(ALL.length) + ' 个会话' }); lvnStage(L, 'persona', { status: 'running' }); lvnDraw(ob);
  const [per] = await Promise.all([LVN.reveal(OB.recent ? '90' : 'all', target), LVN.loadRecs().catch(() => null)]);
  if (spun === 'partial') per.p.partial = true;   // the spine is still an older snapshot: Genesis labels its numbers as partial
  lvnStage(L, 'persona', { status: 'done', note: per.p.ok ? per.p.code : '样本不足' }); lvnDraw(ob);
  TL.send('PATCH', '/v1/app/settings', { onboarded: true, onboarding_step: 4 }).catch(() => { /* re-asked next launch */ });
  if (ORBIT.native && ORBIT.native.isNative) ORBIT.native.post('onboarded', {});   // native host shows the HUD only after this
  // The gateway schedules the first catalog sync itself (catalog/status.first_sync); only older gateways need the nudge,
  // so a running sync is not hit with a second POST (409 catalog_job_already_active).
  const nudge = () => TL.send('POST', '/v1/catalog/sync', {});
  TL.send('GET', '/v1/catalog/status').then((r) => {
    if (!((r && r.data) || {}).first_sync) return nudge();
  }, nudge).catch(() => { /* library keeps its seed rows */ });
  L.per = per;
  if (OB !== ob || OVL !== 'ob') {   // 在后台继续: tell the user instead of playing Genesis; the sidebar entry reopens it
    const p = per.p; L.done = true;
    notify({ t: '协作画像已生成', b: p.ok ? '你是 ' + p.code + '「' + p.zh + '」。点开看看四个维度和协作指纹。' : '会话已导入，样本还不够下结论。', a1: '查看画像', on1: () => go('persona') });
    render(); return;
  }
  lvnPlay(ob);
}
// Genesis for a finished first run (directly, or later from the sidebar entry / 查看揭晓 after 在后台继续)
function lvnPlay(ob) {
  const per = ob.live.per; if (!per) return;
  if (LVN.imp === ob) LVN.imp = null;   // the first run is over: the next 打开引导 starts a fresh one
  AG.forEach((a) => { if (OB.src.has(a.id)) S.srcOff.delete(a.id); else S.srcOff.add(a.id); });
  OB.revealP = per;
  const from = obSources();
  OB.step = 2; OB.prog = -1;
  genOpen('ob', { L: obSel(), from, p: per.p, cands: per.cands });
}
LVN.obImport = async function () {
  const ob = OB; const L = ob && ob.live; if (!L || L.starting || (L.job && !L.err)) return;
  // 重试 after a completed import whose analysis failed: only redo the analysis half
  if (L.err && L.job && L.job.status === 'completed') { L.rev0 = LV.rev; lvnAfter(ob); return; }
  const chosen = L.sources.filter((x) => L.sel.has(x.id));
  if (!chosen.length) return;
  L.err = null; L.starting = true; L.after = false; L.stages = lvnStages(L); L.job = null; lvnStage(L, 'backfill', { status: 'running', note: OB_TEXT.preparing });
  drawOB();
  try {
    await Promise.all(L.sources.filter((x) => x.status !== 'permission_denied' && !!x.enabled !== L.sel.has(x.id) && (L.sel.has(x.id) || x.enabled))
      .map((x) => TL.send('POST', '/v1/app/sources', { agent: x.agent, root: x.root, enabled: L.sel.has(x.id) }).then((r) => { x.enabled = L.sel.has(x.id); if (r.data && r.data.id && r.data.id !== x.id && L.sel.has(x.id)) { L.sel.delete(x.id); x.id = r.data.id; L.sel.add(x.id); } })));
    await TL.send('PATCH', '/v1/app/settings', { recent_days: OB.recent ? 90 : null, onboarding_step: 2 }).catch(() => null);
    L.rev0 = LV.rev;
    let job;
    try { job = (await TL.send('POST', '/v1/app/jobs', { kind: 'import', source_ids: chosen.map((x) => x.id) })).data; }
    catch (e) {
      if (e.status !== 409) throw e;
      const js = lvnBody(await TL.send('GET', '/v1/app/jobs')) || [];
      job = js.find((j) => j.kind === 'import' && LVN.ACTIVE.indexOf(j.status) >= 0); if (!job) throw e;
    }
    if (!job || !job.id) throw new Error('本机服务没有返回导入任务');
    L.job = { id: job.id, status: job.status || 'queued', progress: job.progress || null };
    LVN.imp = ob;
    lvnWatch(ob);
    lvnJob(ob, job);
  } catch (e) {
    L.err = '没能开始导入：' + (e.message || e.code || '本机服务没有响应');
    lvnStage(L, 'backfill', { status: 'failed', note: e.message || null });
  } finally { L.starting = false; lvnDraw(ob); }
};

if (LV.live) {
  // onboarding gets its live state on open (also when re-entered from settings / help menu)
  // Reopening (sidebar entry, help menu, settings) while a first run is in flight or ended in the background shows that run
  // where it is — the stage view of the running import, its failure with 重试, or 查看揭晓 — and never posts a second job.
  // An import started elsewhere (another window, before a reload) is attached to instead of started again.
  const baseOpenOb = openOnboarding;
  openOnboarding = function (step) {
    const imp = LVN.imp, L0 = imp && imp.live;
    if (L0 && (L0.starting || L0.after || L0.done || L0.err || (L0.job && LVN.ACTIVE.indexOf(L0.job.status) >= 0))) {
      if (OVL === 'ob' && OB === imp) return;
      closeModal(); closeDD(); closeOverlay();
      OB = imp; OB.step = 1; OB.drawn = null; L0.shape = null; OVL = 'ob'; $('#overlay').hidden = false;
      if (L0.job && !L0.after && !L0.done && LVN.ACTIVE.indexOf(L0.job.status) >= 0 && !L0.poll) lvnWatch(OB);
      drawOB(); return;
    }
    if (OB && OB.live) lvnStop(OB.live);
    baseOpenOb(step);
    if (!OB) return;
    OB.live = { state: 'loading', sources: [], sel: new Set(), job: null, stages: null, err: null, manual: { agent: 'auto', path: '' }, touched: false };
    const ob = OB;
    LVN.loadOb(ob).then(() => LVN.attach(ob)).catch(() => { /* the list shows its own error */ });
  };
  // an import job already running on the gateway (TL.job or GET /v1/app/jobs): show its stages instead of the source picker
  LVN.attach = async function (ob) {
    const L = ob.live; if (!L || L.job || L.starting || OB !== ob) return;
    let job = TL.job && TL.job.kind === 'import' && LVN.ACTIVE.indexOf(TL.job.status) >= 0 ? TL.job : null;
    if (!job) { const js = await lvnTry('/v1/app/jobs'); job = (Array.isArray(js) ? js : []).find((j) => j && j.kind === 'import' && LVN.ACTIVE.indexOf(j.status) >= 0) || null; }
    if (!job || !job.id || OB !== ob || L.job || L.starting) return;
    L.stages = lvnStages(L); L.rev0 = LV.rev; L.after = false;
    L.job = { id: job.id, status: job.status || 'queued', progress: job.progress || null };
    LVN.imp = ob; ob.step = 1;
    lvnWatch(ob); lvnJob(ob, job);
  };
  // sidebar entry under the edition switch (both editions): import progress → 查看, then 重新打开引导 / 重试
  LVN.bg = false;
  LVN.sideState = function () {
    const L = LVN.imp && LVN.imp.live, T = OB_TEXT.side;
    const tj = TL.job && TL.job.kind === 'import' && LVN.ACTIVE.indexOf(TL.job.status) >= 0 ? TL.job : null;
    const pct = (j) => { const pr = (j && j.progress) || {}; return pr.total ? ' ' + Math.round(clamp(pr.completed / pr.total, 0, 1) * 100) + '%' : ''; };
    if (L && L.err) return { k: 'fail', t: T.fail, a: T.retry, ico: 'alert' };
    if (L && L.done) return { k: 'done', t: T.done, a: '', ico: 'spark' };
    if (L && L.after) return { k: 'run', t: T.analyze, a: T.view, ico: 'sync' };
    if (L && (L.starting || (L.job && LVN.ACTIVE.indexOf(L.job.status) >= 0))) return { k: 'run', t: T.run + pct(L.job), a: T.view, ico: 'sync' };
    if (tj) return { k: 'run', t: T.run + pct(tj), a: T.view, ico: 'sync' };
    if (LVN.bg) return { k: 'done', t: T.done, a: '', ico: 'spark' };
    if (LV.state === 'empty' && !ALL.length) return { k: 'start', t: T.start, a: '', ico: 'plus' };
    return null;
  };
  LVN.sideHTML = function (x) {
    return '<button type="button" class="sb-imp" data-side="import" data-k="' + x.k + '" data-act="obReopen" aria-label="' + esc(x.t + (x.a ? ' · ' + x.a : '')) + '">' +
      '<span class="sb-imp-ic' + (x.k === 'run' ? ' spin-ic' : '') + '">' + ic(x.ico, 14) + '</span><span class="sb-imp-t">' + esc(x.t) + '</span>' + (x.a ? '<span class="sb-imp-a">' + esc(x.a) + ' ›</span>' : '') + '</button>';
  };
  SIDE_EXTRA = () => { if (ORBIT.native.surface) return ''; const x = LVN.sideState(); return x ? LVN.sideHTML(x) : ''; };
  // patch the entry in place on a frame; only appearing / disappearing re-renders the sidebar
  LVN.sidePatch = function () {
    const side = $('#side'); if (!side || ORBIT.native.surface) return;
    const x = LVN.sideState(), el = side.querySelector('[data-side="import"]');
    if (!x && !el) return;
    if (!x || !el) { renderSide(); return; }
    const html = LVN.sideHTML(x); if (el.outerHTML !== html) el.outerHTML = html;
  };
  TL.on('event', (ev) => { if (ev && ev.name === 'job') LVN.sidePatch(); });
  // reveal (help menu, persona page 重播揭晓, onboarding「播放揭晓动画」) plays the server persona
  const baseReveal = openReveal;
  openReveal = function (opt) {
    opt = Object.assign({}, opt || {});
    const per = OB && OB.revealP && OVL === 'ob' ? Promise.resolve(OB.revealP) : LVN.reveal(S.route === 'persona' && S.persona && S.persona.period ? String(S.persona.period) : '90');
    return per.then((x) => baseReveal(Object.assign(opt, { p: x.p, cands: x.cands })));
  };
  Object.assign(ACT, {
    obStart: (() => { const base = ACT.obStart; return (el, e) => (OB && OB.live ? LVN.obImport() : base(el, e)); })(),
    obSrcL: (el) => { const L = OB && OB.live; if (!L) return; L.touched = true; if (el.checked) L.sel.add(el.dataset.s); else L.sel.delete(el.dataset.s); lvnSyncSrc(L); drawOB(); },
    obAgent: (el) => { if (OB && OB.live) OB.live.manual.agent = el.value; },
    obPath: (el) => { if (OB && OB.live) OB.live.manual.path = el.value; },
    obAddFolder: async () => {
      const ob = OB, L = ob && ob.live; if (!L || L.adding) return;
      const host = ORBIT.native.hasHost();
      const path = host ? null : (L.manual.path || '').trim();
      if (!host && !path) { L.err = '先填写会话日志所在的文件夹路径'; drawOB(); const f = $('#obPath'); if (f) f.focus(); return; }
      L.adding = true; L.err = null; L.added = null; drawOB();
      try {
        const r = await LVN.addSource({ agent: L.manual.agent, path });
        if (r && r.ok) {
          L.touched = true; L.manual.path = '';
          const id = r.source && r.source.id; if (id) L.sel.add(id);
          await LVN.loadOb(ob); if (id) L.sel.add(id); lvnSyncSrc(L);
          L.added = r.root;   // shown inline under the list: a toast would sit on top of the sheet
        }
      } catch (e) { L.err = e.message || '添加失败'; if (e.path) L.manual.path = e.path; }
      finally { L.adding = false; lvnDraw(ob); }
    },
    obBgImport: () => { LVN.bg = true; closeOverlay(); render(); toast('导入会在后台继续，完成后通知你；侧栏顶部可以随时查看进度'); },
    obReopen: () => openOnboarding(0),
    obPlay: () => { if (OB && OB.live && OB.live.per) lvnPlay(OB); },
    // 跳过 while the import runs = continue in the background (the job keeps going; the sidebar entry brings the sheet back)
    obClose: (() => { const base = ACT.obClose; return (el, e) => { if (OB && OB.live && (OB.live.job || OB.live.starting)) LVN.bg = true; return base(el, e); }; })()
  });
  // first run: no projection yet, or no enabled source → onboarding opens by itself (main window only, once per load)
  if (!ORBIT.native.surface) setTimeout(() => {
    TL.get('/v1/app/state').then((r) => {
      const st = r && r.data; if (!st) return; LVN.appState = st;
      const absent = !st.storage || st.storage.projection === 'absent' || st.readiness === 'absent';
      const noSrc = !(st.sources || []).some((x) => x && x.enabled);
      const busy = (st.jobs || []).some((j) => j && j.kind === 'import' && LVN.ACTIVE.indexOf(j.status) >= 0);
      if ((absent || noSrc) && !busy && !OVL) openOnboarding(0);
    }, () => { /* no state route: nothing to decide */ });
  }, 0);
}

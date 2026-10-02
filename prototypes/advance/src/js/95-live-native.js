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
const LVN_STAGES = [['backfill', '导入历史会话'], ['stats', '统计分析'], ['semantic', '语义分析'], ['persona', '协作画像']];
function lvnStages(L) {
  const base = {}; (L.stagesBase || []).forEach((x) => { base[x.id] = x; });
  return LVN_STAGES.map(([id, label]) => {
    const b = base[id] || {};
    const sem = id === 'semantic' && (!L.semantic || !L.semantic.enabled);
    return { id, label: b.label || label, status: sem ? 'skipped' : 'pending', done: null, total: null, note: sem ? (L.semantic && L.semantic.note) || b.note || '仅统计模式：不调用模型' : null };
  });
}
function lvnStage(L, id, patch) { const s = (L.stages || []).find((x) => x.id === id); if (s) Object.assign(s, patch); }
function lvnDraw(ob) { if (OVL === 'ob' && OB === ob && ob.step === 1) drawOB(); }
function lvnJob(ob, job) {
  const L = ob.live; if (!job || !L.job || job.id !== L.job.id) return;
  L.job = Object.assign({}, L.job, job);
  const pr = L.job.progress || {}; const st = L.job.status;
  if (LVN.ACTIVE.indexOf(st) >= 0) lvnStage(L, 'backfill', { status: 'running', done: pr.completed != null ? pr.completed : null, total: pr.total != null ? pr.total : null, note: pr.stage ? String(pr.stage) : st === 'queued' ? '排队中' : null });
  else if (st === 'completed') { lvnStage(L, 'backfill', { status: 'done', done: pr.total != null ? pr.total : pr.completed, total: pr.total, note: null }); lvnAfter(ob); }
  else { lvnStage(L, 'backfill', { status: 'failed', note: (L.job.error && (L.job.error.message || L.job.error)) || '导入失败' }); L.err = '导入没有完成：' + ((L.job.error && (L.job.error.message || L.job.error)) || st); lvnStop(L); }
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
async function lvnSpine(rev0) {
  const t0 = Date.now();
  LV.loadSpine();
  let k = 0;
  while (Date.now() - t0 < 30000) {
    if (LV.rev > rev0 && LV.state !== 'computing' && LV.state !== 'connecting') return true;
    await lvnSleep(400);
    if (LV.rev === rev0 && ++k % 3 === 0) LV.loadSpine();
  }
  return false;
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
LVN.reveal = async function (period) {
  const q = { period: period || '90', display_timezone: TL_TZ || 'UTC' };
  for (let i = 0; i < 8; i++) {
    let r = null;
    try { r = await TL.get('/v1/uiview/persona/reveal', { query: q, waitMs: 1500 }); } catch (e) { r = { state: 'error', error: e }; }
    if (r && r.data != null && r.state !== 'computing') return LVN.personaOf(r.data);
    if (r && r.state === 'error') break;
    await lvnSleep(600);
  }
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
  if (!(await lvnSpine(L.rev0)) || !ALL.length) {
    L.after = false;
    lvnStage(L, 'stats', { status: 'failed', note: ALL.length ? '本机服务没有返回分析结果' : '没有读到会话' });
    L.err = ALL.length ? '会话已导入，但分析结果暂时读不到（本机服务没有响应）。可以重试。' : '导入完成，但没有读到任何会话。检查来源目录后重试。';
    if (OB !== ob || OVL !== 'ob') notify({ t: '首次分析没有完成', b: L.err, a1: '重试', on1: () => { openOnboarding(1); } });
    lvnDraw(ob); return;
  }
  lvnStage(L, 'stats', { status: 'done', note: fmt(ALL.length) + ' 个会话' }); lvnStage(L, 'persona', { status: 'running' }); lvnDraw(ob);
  const [per] = await Promise.all([LVN.reveal(OB.recent ? '90' : 'all'), LVN.loadRecs().catch(() => null)]);
  lvnStage(L, 'persona', { status: 'done', note: per.p.ok ? per.p.code : '样本不足' }); lvnDraw(ob);
  TL.send('PATCH', '/v1/app/settings', { onboarded: true, onboarding_step: 4 }).catch(() => { /* re-asked next launch */ });
  if (ORBIT.native && ORBIT.native.isNative) ORBIT.native.post('onboarded', {});   // native host shows the HUD only after this
  TL.send('POST', '/v1/catalog/sync', {}).catch(() => { /* library keeps its seed rows */ });
  if (OB !== ob || OVL !== 'ob') {   // 在后台继续: tell the user instead of playing Genesis
    const p = per.p;
    notify({ t: '协作画像已生成', b: p.ok ? '你是 ' + p.code + '「' + p.zh + '」。点开看看四个维度和协作指纹。' : '会话已导入，样本还不够下结论。', a1: '查看画像', on1: () => go('persona') });
    render(); return;
  }
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
  L.err = null; L.starting = true; L.after = false; L.stages = lvnStages(L); L.job = null; lvnStage(L, 'backfill', { status: 'running', note: '准备来源' });
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
    lvnWatch(ob);
    lvnJob(ob, job);
  } catch (e) {
    L.err = '没能开始导入：' + (e.message || e.code || '本机服务没有响应');
    lvnStage(L, 'backfill', { status: 'failed', note: e.message || null });
  } finally { L.starting = false; lvnDraw(ob); }
};

if (LV.live) {
  // onboarding gets its live state on open (also when re-entered from settings / help menu)
  const baseOpenOb = openOnboarding;
  openOnboarding = function (step) {
    if (OB && OB.live) lvnStop(OB.live);
    baseOpenOb(step);
    if (!OB) return;
    OB.live = { state: 'loading', sources: [], sel: new Set(), job: null, stages: null, err: null, manual: { agent: 'auto', path: '' }, touched: false };
    LVN.loadOb(OB);
  };
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
    obBgImport: () => { closeOverlay(); render(); toast('导入会在后台继续，完成后通知你'); }
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

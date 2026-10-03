/* ============ live core (slice 0): spine hydration, agent map, page feeds, native bridge ============
   Mock mode (file://, no gateway) changes nothing here: LV.live is false, nothing is fetched and 05-data stays as generated.
   Live mode hydrates the demo's own globals in place (ALL / BYID / AG / AGI / PJ / PJI, DAY0 / LASTDAY) from
   GET /v1/uiview/facts, so every polished renderer, filter and animation runs unchanged on real rows. Page files hook
   their constants through LV.feed(); see .work/release/slice0-notes.md for the contract. */
// TL changes are coalesced into one render() per animation frame (a 120 ms timer stands in when rAF is paused, e.g. a
// hidden WKWebView), and a frame whose observable live state is unchanged (every load came back 304 / identical) skips
// the render. lvSig() covers resources (enumerated via TL.invalidate with a matcher that never matches), the job /
// service / connection fields the badges read, LV's own spine state and a tick that every TL event and every explicit
// TL.changed() call (LV.detail arrivals, ops frames, studio jobs) bumps, so only redundant renders are dropped.
let lvFrame = 0, lvFrameT = null, lvLastSig = null, lvTick = 0;
const lvIds = new WeakMap(); let lvIdN = 0;
const lvId = (o) => { if (o == null || typeof o !== 'object') return String(o); let v = lvIds.get(o); if (!v) lvIds.set(o, v = ++lvIdN); return v; };
// Import progress is not page data: a job frame only moves the numbers, so the signature keeps the job's identity and
// status (start / finish re-render) and the frames themselves patch the progress nodes in place (lvPatchProgress).
const LV_ACTIVE = ['queued', 'pending', 'running'];
const lvJobSig = (j) => (j ? (j.id || '') + ':' + (j.kind || '') + ':' + (j.status || '') : '');
function lvImporting() {
  const j = TL.job; if (j && j.kind === 'import' && LV_ACTIVE.indexOf(j.status) >= 0) return true;
  const L = typeof OB !== 'undefined' && OB && OB.live; return !!(L && L.job && LV_ACTIVE.indexOf(L.job.status) >= 0);
}
function lvSig() {
  const parts = [lvTick, LV.rev, LV.state, LV.stale, LV.failed && LV.failed.reason, LV.job && LV.job.status, S.route, lvJobSig(TL.job), lvId(TL.failure), lvId(TL.error), lvId(TL.status),
    TL.events && TL.events.connected, lvId(TL.collection), TL.collection && TL.collection.state];
  try { parts.push(JSON.stringify(TL.services || {})); } catch (e) { parts.push(++lvTick); }
  TL.invalidate((r) => { parts.push(r.key + ':' + r.state + ':' + lvId(r.data) + ':' + lvId(r.error) + ':' + (r.loading ? 1 : 0) + (r.dirty ? 'd' : '')); return false; });
  return parts.join('|');
}
// A live-triggered render is postponed while the user is in the middle of something (wheel / touch scrolling in the last
// 700 ms, a dropdown open, or — during an import — typing in a field) — at most LV_DEFER_MAX, so data never goes stale for long — and while an
// import runs, live renders are spaced LV_IMPORT_GAP apart: the import publishes often and every publish would otherwise
// rebuild the page under the user's cursor (bug: scroll positions and open menus jumping back during the first import).
const LV_IMPORT_GAP = 4000, LV_DEFER_MAX = 8000;
let lvLastRenderT = 0, lvDeferSince = 0, lvUserT = 0;
if (typeof window !== 'undefined') {
  const mark = () => { lvUserT = Date.now(); };
  ['wheel', 'touchmove'].forEach((n) => window.addEventListener(n, mark, { passive: true, capture: true }));
  window.addEventListener('keydown', (e) => { if (/^(Page(Up|Down)|Arrow(Up|Down)|Home|End| )$/.test(e.key)) mark(); }, true);
}
function lvUserBusy(now) {
  if (now - lvUserT < 700) return true;
  if (typeof DD !== 'undefined' && DD) return true;
  // a focused field only holds renders back during an import (search answers must still arrive while typing)
  const a = document.activeElement;
  return !!(a && lvImporting() && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) && a.closest('#main, #side'));
}
// On a region-built page (RG.canRefresh, 24-regions.js) a live change is a region pass, not a page rebuild: render() then
// only re-evaluates the regions whose deps are among the live keys (facts when the spine revision moved, the route's feed,
// the connection / analysis status, 'tl' for any other TandemLive state) and morphs the changed ones in place, so the
// user-busy postponement is not needed there; the import spacing (LV_IMPORT_GAP) stays as a guard on both paths.
let lvRevShown = -1;
function lvFlush() {
  if (lvFrame) { cancelAnimationFrame(lvFrame); lvFrame = 0; }
  if (lvFrameT) { clearTimeout(lvFrameT); lvFrameT = null; }
  lvPatchProgress();
  const sig = lvSig(); if (sig === lvLastSig) { lvDeferSince = 0; return; }
  const now = Date.now();
  const soft = RG.canRefresh();
  const gap = lvImporting() && lvLastRenderT ? lvLastRenderT + LV_IMPORT_GAP - now : 0;
  const busy = !soft && lvUserBusy(now) && (!lvDeferSince || now - lvDeferSince < LV_DEFER_MAX);
  if (gap > 0 || busy) { if (!lvDeferSince) lvDeferSince = now; lvFrameT = setTimeout(lvFlush, Math.max(400, Math.min(gap, 2000))); return; }
  lvDeferSince = 0;
  if (soft) {
    const keys = new Set(['live', 'tl', 'job', 'feed:' + S.route]);
    if (LV.rev !== lvRevShown) keys.add('facts');
    RG.only = keys;
  }
  lvRevShown = LV.rev;
  try { render(); } finally { RG.only = null; }
}
// the import progress strip (TandemLive.ui.progress) is morphed in place on every job frame instead of re-rendering the page
function lvPatchProgress() {
  if (typeof document === 'undefined') return;
  const els = document.querySelectorAll('#content .tl-progress'); if (!els.length) return;
  const html = TLU.progress(TL); if (!html) return;
  els.forEach((el) => { if (el.outerHTML !== html) rgSwap(el, html); });
}
function lvSchedule() {
  if (lvFrame || lvFrameT) return;
  if (typeof requestAnimationFrame === 'function') lvFrame = requestAnimationFrame(lvFlush);
  lvFrameT = setTimeout(lvFlush, 120);
}
const TL = TandemLive.create({ onChange: () => lvSchedule() });
const TLU = TandemLive.ui;
const TL_TZ = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) { return null; } })();

/* ---- native bridge (WKWebView shell; browser fallbacks) ---- */
const ORBIT = (typeof window !== 'undefined' && window.ORBIT) || {};
if (typeof window !== 'undefined') window.ORBIT = ORBIT;
ORBIT.native = (function () {
  const flag = window.__ORBIT_NATIVE__;
  const info = flag === true ? { v: 1, app: null, platform: 'macos', features: [] } : flag && typeof flag === 'object' ? flag : null;
  const handler = () => { try { return window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.tandem; } catch (e) { return null; } };
  let q = null; try { q = new URLSearchParams(location.search || ''); } catch (e) { q = null; }
  const surface = q && ['panel', 'hud', 'widgets'].indexOf(q.get('surface')) >= 0 ? q.get('surface') : null;
  const REPLY = { chooseFolder: 'tandem:folder', save: 'tandem:saved' };
  const waits = new Map(); let seq = 0;
  Object.keys(REPLY).forEach((t) => window.addEventListener(REPLY[t], (e) => {
    const d = (e && e.detail) || {}; const w = waits.get(d.id); if (!w) return;
    waits.delete(d.id); if (w.timer) clearTimeout(w.timer); w.resolve(d);
  }));
  function post(type, payload) {
    const h = handler(); if (!h || typeof h.postMessage !== 'function') return false;
    h.postMessage(Object.assign({}, payload || {}, { type })); return true;
  }
  const fallback = {
    save(p) {
      const bytes = p.base64 != null ? Uint8Array.from(atob(p.base64), (c) => c.charCodeAt(0)) : p.text || '';
      const url = URL.createObjectURL(new Blob([bytes], { type: p.mime || 'application/octet-stream' }));
      const a = document.createElement('a'); a.href = url; a.download = p.filename || 'orbit-export'; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return { id: p.id, ok: true, path: null, browser: true };
    },
    chooseFolder(p) {
      const path = window.prompt('输入文件夹路径', p.defaultPath || '~/');
      return { id: p.id, path: path || null, cancelled: !path, browser: true };
    },
    openExternal(p) { if (/^https?:\/\//.test(p.url || '')) window.open(p.url, '_blank', 'noopener'); return { ok: true, browser: true }; },
    reveal(p) {
      try { navigator.clipboard.writeText(p.path || ''); } catch (e) { /* clipboard blocked */ }
      if (typeof toast === 'function') toast('已复制路径：' + (p.path || ''));
      return { ok: true, browser: true };
    }
  };
  // request(type, payload, {timeoutMs}) → Promise of the host's reply event detail (chooseFolder / save); other types resolve
  // {ok:true} once posted. Outside the native shell the browser fallback answers ({browser:true}); window ops resolve
  // {ok:false, browser:true} so the caller keeps its simulated behaviour.
  function request(type, payload, o) {
    payload = Object.assign({}, payload || {});
    if (!handler()) {
      const fb = fallback[type];
      return fb ? Promise.resolve().then(() => fb(payload)) : Promise.resolve({ ok: false, browser: true });
    }
    if (!REPLY[type]) { post(type, payload); return Promise.resolve({ ok: true }); }
    const id = payload.id || type + '-' + (++seq) + '-' + Date.now().toString(36);
    payload.id = id;
    return new Promise((resolve, reject) => {
      const w = { resolve, timer: null };
      if (o && o.timeoutMs) w.timer = setTimeout(() => { waits.delete(id); reject(Object.assign(new Error('timeout'), { code: 'timeout' })); }, o.timeoutMs);
      waits.set(id, w);
      if (!post(type, payload)) { waits.delete(id); reject(Object.assign(new Error('no host'), { code: 'no_host' })); }
    });
  }
  // tandem:command {cmd:'settings'|'palette'|'about'|'keys'|'onboarding'|'reveal'|'report'|'share'|'csv'|'route'|'toggleEdition'|'refresh', route?}
  function onCommand(fn) { const h = (e) => fn((e && e.detail) || {}); window.addEventListener('tandem:command', h); return () => window.removeEventListener('tandem:command', h); }
  return { isNative: !!info, info, surface, post, request, onCommand, has: (f) => !!info && (info.features || []).indexOf(f) >= 0, hasHost: () => !!handler() };
})();

/* ---- agent map: backend id → UI agent (color slot fixed by id, never by rank) ---- */
const LV_AGENTS = {};
[[['claude_code', 'claude'], 'cc', 'Claude Code', 'Claude', 1], [['codex'], 'cx', 'Codex', 'Codex', 2],
  [['gemini', 'gemini_cli'], 'gm', 'Gemini CLI', 'Gemini', 3], [['dsh', 'deepseek', 'deepseek_harness'], 'ds', 'DeepSeek Harness', 'DeepSeek', 4],
  [['copilot', 'copilot_cli'], 'cp', 'Copilot CLI', 'Copilot', 5], [['pi'], 'pi', 'Pi', 'Pi', 6], [['kimi', 'kimi_cli'], 'km', 'Kimi CLI', 'Kimi', 7],
  [['hermes', 'hermes_agent'], 'hm', 'Hermes Agent', 'Hermes', 8], [['opencode'], 'oc', 'OpenCode', 'OpenCode', 9]
].forEach(([keys, id, name, short, slot]) => keys.forEach((k) => { LV_AGENTS[k] = { id, key: keys[0], keys, name, short, slot }; }));
function lvAgentOf(backendId) {
  const k = String(backendId || '').toLowerCase();
  const m = LV_AGENTS[k];
  if (m) return m;
  return { id: k || 'unknown', key: k, keys: [k], name: backendId || '未知', short: backendId || '未知', slot: 0 };
}

/* ---- LV ---- */
const LV = {
  live: TL.mode === 'live',
  demo: (() => { try { return new URLSearchParams(location.search).get('demo') === '1'; } catch (e) { return false; } })(),
  AGENTS: LV_AGENTS,
  agentOf: lvAgentOf,
  state: 'connecting',         // connecting | computing | ready | empty | error
  stale: false,                // facts is recomputing; the screen keeps the previous spine
  meta: null, wire: null, rev: 0, excluded: [], undated: 0,
  feeds: {}, applied: {}
};
{ const ch0 = TL.changed; TL.changed = function () { lvTick++; return ch0.apply(this, arguments); }; }
// job frames are progress, not data (see lvJobSig): they do not count as a change of the live state
TL.on('event', (ev) => { if (!ev || ev.name !== 'job') lvTick++; });
// every render (whatever triggered it) records the live state it showed, so the next TL frame can tell whether it is new
LV.rendered = () => { lvLastRenderT = Date.now(); if (LV.live) { try { lvLastSig = lvSig(); } catch (e) { lvLastSig = null; } } };
if (LV.live && typeof window !== 'undefined') window.__lvRendered = LV.rendered;
// region deps (24-regions.js): 'tl' = any TandemLive change, 'live' = the connection / analysis status the strip and badges read
RG.dep('tl', () => lvTick + ':' + LV.rev);
RG.dep('live', () => [LV.state, LV.stale, LV.failed && LV.failed.reason, LV.job && LV.job.status, lvId(TL.error), lvId(TL.failure), TL.events && TL.events.connected]);
LV.backendId = (uiId) => { const a = AGI[uiId]; return a && a.key ? a.key : uiId; };
// scope for page endpoints: {range, agents (backend ids | null = all), project, tz} + the UI-only filters
LV.scope = () => {
  const on = AG.filter((a) => S.agents.has(a.id) && !S.srcOff.has(a.id));
  return { range: S.range, agents: on.length === AG.length ? null : on.map((a) => a.key || a.id), project: S.project || null, tz: TL_TZ,
    topic: S.topic || null, outcome: S.outcome || null, fric: S.fric || null, hour: S.hour };
};
// path + query string; array values repeat the key (agent=a&agent=b), null / undefined are dropped
LV.withQuery = (path, obj) => {
  const parts = [];
  Object.keys(obj || {}).forEach((k) => { const v = obj[k]; if (v == null) return; (Array.isArray(v) ? v : [v]).forEach((x) => parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(x))); });
  return parts.length ? path + (path.indexOf('?') >= 0 ? '&' : '?') + parts.join('&') : path;
};
LV.lru = function (max) {
  const m = new Map(); max = max || 30;
  return {
    get(k) { if (!m.has(k)) return undefined; const v = m.get(k); m.delete(k); m.set(k, v); return v; },
    set(k, v) { m.delete(k); m.set(k, v); while (m.size > max) m.delete(m.keys().next().value); return v; },
    has: (k) => m.has(k), delete: (k) => m.delete(k), clear: () => m.clear(), get size() { return m.size; }, keys: () => Array.from(m.keys())
  };
};
// on-demand drill-down: LV.detail(cache, key, path) → {state:'pending'|'ready'|'error', data, error}; first call fetches,
// the arrival re-renders; later calls are cache hits (no request). A transient failure (network / 5xx) keeps showing the
// error, then refetches with backoff (1 s · 2ⁿ, ≤ 15 s, 6 tries) and on TL.retry() / SSE reconnect (R4-11); 4xx stays.
const lvDetailErr = new Set();
const lvTransient = (err) => !!err && err.code !== 'analysis_unavailable' && err.retryable !== false && (!err.status || err.status >= 500);
function lvDetailFetch(cache, e, path, o) {
  e.retry = false;
  TL.get(path, o || {}).then((res) => { e.state = res.data == null ? 'pending' : 'ready'; e.data = res.data; e.error = null; e.fails = 0; lvDetailErr.delete(e); if (res.state === 'computing') cache.delete(e.key); },
    (err) => {
      e.state = 'error'; e.error = err; e.fails = (e.fails || 0) + 1;
      if (!lvTransient(err)) return;
      lvDetailErr.add(e);
      if (e.fails <= 6) setTimeout(() => { if (e.state === 'error' && cache.get(e.key) === e) { e.retry = true; TL.changed(); } }, Math.min(15000, 1000 * Math.pow(2, e.fails - 1)));
    }).then(() => TL.changed());
}
LV.detail = function (cache, key, path, o) {
  let e = cache.get(key);
  if (!e) { e = cache.set(key, { key, state: 'pending', data: null, error: null }); lvDetailFetch(cache, e, path, o); }
  else if (e.retry && e.state === 'error') lvDetailFetch(cache, e, path, o);
  return e;
};
TL.on('retry', () => { lvDetailErr.forEach((e) => { if (e.state === 'error') e.retry = true; }); lvDetailErr.clear(); });

/* ---- page feeds ----
   LV.feed(route | [routes], spec, apply): spec is a path string, an array of {name, path, query?, waitMs?} or a function
   (scope) → that array. While one of the routes is shown, the resources load through TL (ETag, SSE invalidation); every
   time they all hold new data, apply(data, ctx) runs right before the page renders, so it can overwrite the page's
   constants in their existing shapes. data is the response body for a string spec, {name: body} otherwise. */
LV.feed = function (routes, spec, apply) {
  const f = { routes: [].concat(routes), spec, apply, stamp: null, state: 'pending', error: null, data: null };
  f.routes.forEach((r) => { (LV.feeds[r] = LV.feeds[r] || []).push(f); });
  return f;
};
function lvFeedRes(f) {
  const sc = LV.scope();
  const list = typeof f.spec === 'string' ? [{ name: '_', path: f.spec }] : typeof f.spec === 'function' ? f.spec(sc) : f.spec;
  return list.map((x) => ({ name: x.name || '_', r: TL.resource(x.path, { query: x.query || null, waitMs: x.waitMs || 0 }) }));
}
// a resource key without its days= (a window switch of the same scope keeps the last screen until the new one decodes)
const lvNoDays = (k) => String(k).replace(/([?&])days=[^&]*&?/, '$1').replace(/[?&]$/, '');
const lvKeyDays = (k) => { const m = /[?&]days=(\d+)/.exec(String(k)); return m ? +m[1] : null; };
LV.pump = function (route) {
  if (!LV.live) return;
  LV.widen();
  (LV.feeds[route] || []).forEach((f) => {
    const rs = lvFeedRes(f);
    rs.forEach((x) => { if (x.r.dirty && !x.r.loading) TL.load(x.r); });
    // 422 analysis_scope_too_large: remember the window and re-render; the spec then asks for 30 days (then 7)
    const big = rs.find((x) => x.r.state === 'error' && x.r.error && x.r.error.code === 'analysis_scope_too_large');
    if (big) { const d = lvKeyDays(big.r.key); if (!LV.tooLarge.has(d != null ? d : LV.window ? LV.window.days : 0)) { LV.scopeTooLarge(d); setTimeout(() => TL.changed(), 0); f.state = f.data ? 'ready' : 'pending'; return; } }
    const err = rs.find((x) => x.r.state === 'error' && x.r.data == null);
    if (err) { f.state = 'error'; f.error = err.r.error; return; }
    if (rs.some((x) => x.r.data == null)) {
      const swap = f.data && f.parts && f.keys && f.keys.length === rs.length && rs.every((x, i) => lvNoDays(x.r.key) === lvNoDays(f.keys[i]));
      if (swap) return;   // same scope, another window still loading: keep the applied screen
      f.state = rs.some((x) => x.r.state === 'computing') ? 'computing' : 'pending'; return;
    }
    const stamp = rs.map((x) => x.r.key + '@' + x.r.updatedAt).join('|') + '#' + LV.rev;
    if (stamp === f.stamp) return;
    // a 304 / identical body refreshes updatedAt but hands back the same objects: nothing to re-apply
    const same = f.parts && f.rev === LV.rev && f.parts.length === rs.length && rs.every((x, i) => f.parts[i] === x.r.data);
    if (same) { f.stamp = stamp; return; }
    const data = rs.length === 1 && rs[0].name === '_' ? rs[0].r.data : rs.reduce((o, x) => { o[x.name] = x.r.data; return o; }, {});
    try { f.apply(data, { route, rev: LV.rev }); f.state = 'ready'; f.data = data; f.stamp = stamp; f.parts = rs.map((x) => x.r.data); f.keys = rs.map((x) => x.r.key); f.rev = LV.rev; }
    catch (e) { f.state = 'error'; f.error = { code: 'apply_failed', message: String(e && e.message || e) }; console.error('LV.feed apply', e); }
  });
};
// 'ready' when every feed of the route applied; 'error' (404 / 501 included) or 'pending' / 'computing' otherwise
LV.feedState = (route) => {
  const fs = LV.feeds[route] || []; if (!fs.length) return 'ready';
  if (fs.some((f) => f.state === 'error')) return 'error';
  if (fs.some((f) => f.state === 'computing')) return 'computing';
  return fs.every((f) => f.state === 'ready') ? 'ready' : 'pending';
};
LV.ready = (route) => !LV.live || LV.feedState(route) === 'ready';
// pending / empty placeholders in the prototype's own card language (no tl-table / tl-kpi)
LV.pend = (h) => '<div class="lv-pend" data-lv="pending" style="height:' + (h || 120) + 'px" aria-busy="true"></div>';
LV.na = (txt) => '<span class="cap" data-lv="na">' + esc(txt || '暂无数据') + '</span>';

/* ---- spine: /v1/uiview/facts → ALL / BYID / AG / PJ ---- */
function lvToday() {
  try { return new Intl.DateTimeFormat('en-CA', { timeZone: TL_TZ || 'UTC', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()); }
  catch (e) { return new Date().toISOString().slice(0, 10); }
}
const lvUtc = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : null; };

/* ---- auto window (first-open fast path): /v1/uiview/{facts,overview,persona} without days serve the widest ready window
   (all → 30 → 7) and warm wider ones; meta.window = {days, requested, wider: [{days, state, scope_hash}]}. LV.window keeps
   {days (served), wider} merged across responses; LV.daysFor(want) gives the days to request for a wanted range (only a
   window known to be ready, else null = auto); LV.tooLarge holds windows that answered 422 analysis_scope_too_large. */
const LV_DAYS = [7, 30, 90, 0];
LV.window = null;               // {days, wider: [{days, state, scope_hash}]}
LV.spineDays = null;            // explicit days the spine requests (null = auto)
LV.tooLarge = new Set();        // days values the gateway refused as too large (this data revision)
LV.progress = null;             // meta.progress of the spine's last 202
const lvWinMap = {};            // days → {state, scope_hash}
const lvCovers = (w, want) => w === 0 || (want !== 0 && w >= want);
const lvWider = (d, than) => d !== than && than !== 0 && (d === 0 || d > than);
LV.rangeDays = (r) => { r = +r || 0; return r === 0 ? 0 : r <= 7 ? 7 : r <= 30 ? 30 : r <= 90 ? 90 : 0; };
LV.periodDays = (p) => {
  if (p === 'all') return 0;
  if (/^\d+$/.test(String(p))) return LV.rangeDays(+p);
  const m = /^(\d{4})-(\d{2})$/.exec(p || ''); if (!m) return 90;
  const age = Math.round((lvUtc(lvToday()) - Date.UTC(+m[1], +m[2] - 1, 1)) / 86400000) + 1;
  return age <= 7 ? 7 : age <= 30 ? 30 : age <= 90 ? 90 : 0;
};
LV.dayLabel = (d) => (d === 0 ? '全部' : d + ' 天');
// the window a page wants: A2 / Lite persona follow their period, every other page the time range
LV.wantDays = (route) => (/persona$/.test(route || S.route) && S.persona ? LV.periodDays(S.persona.period) : LV.rangeDays(S.range));
LV.noteWindow = function (w) {
  if (!w || w.days == null) return;
  lvWinMap[w.days] = Object.assign({}, lvWinMap[w.days], { state: 'ready' });
  (w.wider || []).forEach((x) => { if (LV_DAYS.indexOf(x.days) >= 0) lvWinMap[x.days] = { state: x.state, scope_hash: x.scope_hash || (lvWinMap[x.days] || {}).scope_hash || null }; });
  LV.window = { days: w.days, requested: w.requested, wider: Object.keys(lvWinMap).map(Number).filter((d) => lvWider(d, w.days)).sort((a, b) => (a === 0) - (b === 0) || a - b).map((d) => Object.assign({ days: d }, lvWinMap[d])) };
};
LV.resetWindow = function () { Object.keys(lvWinMap).forEach((k) => { delete lvWinMap[k]; }); LV.tooLarge.clear(); LV.spineDays = null; };
// days to request for a wanted window: the narrowest ready window that covers it (never one refused as too large); a
// too-large want falls back to 30 then 7; null = no ready window covers it yet → auto (and the strip shows the hint)
LV.daysFor = function (want) {
  if (!LV.live || !LV.window) return null;
  if (LV.tooLarge.has(want)) { const fb = [30, 7].find((d) => !LV.tooLarge.has(d)); return fb != null ? fb : null; }
  const ok = Object.keys(lvWinMap).map(Number).filter((d) => LV_DAYS.indexOf(d) >= 0 && !LV.tooLarge.has(d) && lvWinMap[d].state === 'ready' && lvCovers(d, want));
  if (!ok.length) return null;
  return ok.sort((a, b) => (a === 0) - (b === 0) || a - b)[0];
};
// calm inline hint when the wanted window is wider than the served one: 「目前显示近 7 天 · 30 天数据计算中」
LV.windowHint = function (route) {
  const w = LV.window; if (!LV.live || !w || LV.state !== 'ready') return '';
  const want = LV.wantDays(route);
  const shown = w.days === 0 ? '全部数据' : '近 ' + w.days + ' 天';
  if (LV.tooLarge.has(want)) { const fb = LV.daysFor(want); return '数据量太大，已切换到' + (fb != null ? '近 ' + fb + ' 天' : shown); }
  if (lvCovers(w.days, want)) return '';
  const e = w.wider.find((x) => lvCovers(x.days, want));
  if (e && e.state === 'failed') return LV.dayLabel(e.days) + '数据量过大，显示' + shown;
  if (e && e.state === 'ready') return '';
  return '目前显示' + shown + ' · ' + LV.dayLabel(e ? e.days : want) + '数据计算中';
};
// 202 meta.progress → 「已用 N / M 秒 · K 条事件」 (or the queue position)
LV.progressNote = function (p) {
  if (!p) return '';
  const out = [];
  if (p.queue_position != null) out.push('排队第 ' + p.queue_position + ' 位');
  else if (p.elapsed_s != null) out.push('已用 ' + Math.round(p.elapsed_s) + (p.budget_s ? ' / ' + Math.round(p.budget_s) : '') + ' 秒');
  if (p.events) out.push(fmt(p.events) + ' 条事件');
  return out.length ? ' · ' + out.join(' · ') : '';
};
// a page (or the strip) wants a window the spine does not cover and a ready one does: reload the spine with it
LV.widen = function () {
  if (!LV.live || !LV.window || LV.state !== 'ready') return;
  const want = LV.wantDays();
  if (lvCovers(LV.window.days, want) && !LV.tooLarge.has(LV.window.days)) return;
  const d = LV.daysFor(want);
  if (d != null && d !== LV.window.days && d !== LV.spineDays) { LV.spineDays = d; setTimeout(() => LV.loadSpine(), 0); }
};
// 422 analysis_scope_too_large for a request of `days` (null = auto): remember it, fall back to 30 then 7
LV.scopeTooLarge = function (days) {
  const d = days != null ? days : LV.window ? LV.window.days : 0;
  LV.tooLarge.add(d);
  return [30, 7].find((x) => !LV.tooLarge.has(x));
};
// columnar-v1 → row objects (inverse of facts.compact)
LV.expand = function (wire) {
  if (!wire || !wire.fields) return (wire && wire.rows) || [];
  const fields = wire.fields, dicts = wire.dicts || {}, cons = wire.constants || {};
  const prefix = (wire.meta && wire.meta.id_prefix) || '';
  return (wire.rows || []).map((vals) => {
    const r = Object.assign({}, cons);
    fields.forEach((k, i) => {
      let v = vals[i];
      if (k === 'id') v = prefix + v;
      else if (dicts[k] && v != null) v = dicts[k][v];
      r[k] = v;
    });
    ['verify', 'live', 'excluded'].forEach((k) => { if (r[k] != null) r[k] = !!r[k]; });
    return r;
  });
};
function lvMakeAgent(m, extra) {
  const slot = m.slot;
  return Object.assign({ id: m.id, key: m.key, keys: m.keys, slot, name: m.name, short: m.short, c: slot ? 'var(--a' + slot + ')' : 'var(--a0)', t: slot ? 'var(--a' + slot + 't)' : 'var(--a0t)',
    path: '—', ver: '—', model: '—', cli: '', resume: '', all: 0, detected: false }, extra || {});
}
// hydrate({rows, agents?, projects?, meta?, discovered?}) — mutates the demo globals in place, then fixes up S
LV.hydrate = function (spine) {
  const rows = spine.rows || [];
  const today = lvToday();
  const t = lvUtc(today);
  const first = rows.reduce((m, r) => (r.d && (!m || r.d < m) ? r.d : m), null);
  DAY0 = Math.min(first ? lvUtc(first) : t, t - 119 * 86400000);
  LASTDAY = Math.round((t - DAY0) / 86400000);
  // 全部 starts at the earliest session, not at the 120-day spine floor (R4-04); no rows keeps the full spine
  FIRSTDAY = first ? Math.max(0, Math.min(LASTDAY, Math.round((lvUtc(first) - DAY0) / 86400000))) : 0;
  // agents: present in facts or detected, ordered by session count; default all; an explicit deselection survives by id (agentOff)
  agentSync();
  const ags = {};
  const add = (bid, extra) => { const m = lvAgentOf(bid); const a = ags[m.id] || (ags[m.id] = lvMakeAgent(m)); Object.assign(a, extra || {}); return a; };
  (spine.discovered || []).forEach((x) => add(x.agent, { detected: true, path: x.root || '—' }));
  (spine.environment || []).forEach((x) => { const m = lvAgentOf(x.agent); if (ags[m.id] || x.installed) add(x.agent, { detected: true, path: x.root || ags[m.id] && ags[m.id].path || '—', ver: x.version || '—' }); });
  // projects
  const pj = {};
  (spine.projects || []).forEach((p) => { pj[p.id] = p; });
  const ALLX = []; const excluded = []; let undated = 0;
  rows.forEach((r) => {
    if (r.excluded) { excluded.push(r); return; }
    if (!r.d) { undated++; return; }
    const ag = add(r.a);
    ag.all++;
    const p = r.p || '_none';
    if (!pj[p]) pj[p] = { id: p, name: r.p ? r.p : '未归属项目', path: null };
    ALLX.push({ id: r.id, d: Math.round((lvUtc(r.d) - DAY0) / 86400000), h: r.h || 0, mi: r.mi || 0, a: ag.id, p,
      dur: r.dur != null ? r.dur : r.span != null ? r.span : 0, msgs: r.msgs || 0, tools: r.tools || 0, errors: r.errors || 0, corr: r.corr || 0,
      steps: r.steps != null ? r.steps : null, out: r.out || null, live: !!r.live, verify: !!r.verify, mood: r.mood != null ? r.mood : null,
      topic: r.topic || 'other', fric: r.fric || null, tok: r.tok || 0, title: r.title || '（无标题）', model: r.model || null, effort: r.effort || null,
      dk: r.dk, dn: r.dn, vk: r.vk, op: r.op, t0: r.t0, t1: r.t1, raw: r });
  });
  ALLX.sort((x, y) => (x.d - y.d) || (x.h - y.h) || (x.mi - y.mi) || (x.id < y.id ? -1 : 1));
  ALL.length = 0; ALLX.forEach((s) => ALL.push(s));
  Object.keys(BYID).forEach((k) => { delete BYID[k]; }); ALL.forEach((s) => { BYID[s.id] = s; });
  AG.length = 0; Object.values(ags).sort((x, y) => (y.all - x.all) || (x.slot || 99) - (y.slot || 99) || (x.id < y.id ? -1 : 1)).forEach((a) => AG.push(a));
  Object.keys(AGI).forEach((k) => { delete AGI[k]; }); AG.forEach((a) => { AGI[a.id] = a; });
  const pcount = {}; ALL.forEach((s) => { pcount[s.p] = (pcount[s.p] || 0) + 1; });
  PJ.length = 0;
  Object.keys(pcount).sort((x, y) => (pcount[y] - pcount[x]) || (x < y ? -1 : 1)).forEach((id) => {
    const p = pj[id];
    PJ.push({ id, name: p.name || id, path: p.path || '—', git: '—', n: pcount[id], q: null, h: null, A: null, fr: null, I: null, V: null, err: null,
      tags: [], topics: {}, fric: {}, flow: [], cover: [], tip: '', rec: null, titles: [], live: true });
  });
  Object.keys(PJI).forEach((k) => { delete PJI[k]; }); PJ.forEach((p) => { PJI[p.id] = p; });
  LV.excluded = excluded; LV.undated = undated; LV.rev++;
  // S fix-ups
  agentApply();
  S.srcOff = new Set(Array.from(S.srcOff).filter((id) => AGI[id]));
  if (S.project && !PJI[S.project]) S.project = null;
  const done = ALL.filter((s) => !s.live);
  const newest = done.length ? done[done.length - 1] : ALL[ALL.length - 1];
  if (!BYID[S.sess.sel]) S.sess.sel = newest ? newest.id : null;
  if (S.sess.cmp && !BYID[S.sess.cmp]) S.sess.cmp = null;
  if (!PJI[S.proj.sel]) S.proj.sel = PJ[0] ? PJ[0].id : null;
  if (S.proj.cmp && !PJI[S.proj.cmp]) S.proj.cmp = null;
};

// first landing (A): when the default range holds no sessions but older history does (a first import of only older
// sessions), pick the narrowest range that has data (30 → 90 → all) once, instead of every page reading 「没有会话」
LV.autoRanged = false;
function lvAutoRange() {
  if (LV.autoRanged || !ALL.length) return;
  LV.autoRanged = true;
  if (S.range === 0 || sel({ noExtra: true }).length) return;
  const to = [90, 0].find((r) => (r === 0 || r > S.range) && sel({ range: r, noExtra: true }).length);
  if (to == null) return;
  const from = rangeLabel();
  S.range = to;
  if (typeof toast === 'function') toast(from + '内没有会话，已切换到' + rangeLabel());
}

let lvSpineAgain = false, lvSpineTimer = null, lvSpineBusy = null, lvSpineFails = 0, lvSpineData = null;
const LV_SECTION = 'uiview_facts';
LV.failed = null;   // {reason, message}: the spine's analysis failed for this data (strip: reason + 重新计算)
LV.job = null;      // the analysis job being polled for the spine: {id, status, elapsed_s, timeout_s}
function lvSpineFailed(f) {
  LV.failed = f; LV.job = null; LV.stale = false;
  if (LV.state !== 'ready') LV.state = 'error';
  TL.changed();
}
function lvWatchSpine(id) {
  if (LV.job && LV.job.id === id) return;
  LV.job = { id, status: 'queued' };
  TL.analysis.poll(id, (j) => { if (LV.job && LV.job.id === id) { LV.job = Object.assign({ id }, j); TL.changed(); } }).then((j) => {
    if (!LV.job || LV.job.id !== id) return;
    if (j.status === 'failed') { lvSpineFailed({ reason: (j.error && j.error.code) || 'analysis_failed', message: j.error && j.error.message }); return; }
    LV.job = null;
    if (j.status === 'gone') lvSpineLater(1200); else LV.loadSpine();
  }, () => { LV.job = null; lvSpineLater(1200); });
}
// 重新计算: POST /v1/analytics/recompute for the spine's scope (the same scope /v1/uiview/facts uses), then poll the job
LV.recompute = function () {
  LV.failed = null; LV.job = null;
  if (LV.state === 'error') LV.state = ALL.length ? 'ready' : 'computing';
  LV.stale = LV.state === 'ready';
  TL.changed();
  return TL.analysis.recompute([LV_SECTION], { display_timezone: TL_TZ || 'UTC' }).then((d) => {
    const j = ((d && d.jobs) || []).find((x) => x.job_id);
    if (j) lvWatchSpine(j.job_id); else LV.loadSpine();
  }, (e) => lvSpineFailed({ reason: null, message: (e && (e.message || e.code)) || '重新计算失败' }));
};
function lvSpineLater(ms) { clearTimeout(lvSpineTimer); lvSpineTimer = setTimeout(() => LV.loadSpine(), ms); }
const lvSide = (path) => TL.get(path).then((r) => r.data, () => null);
LV.loadSpine = function () {
  if (!LV.live) return Promise.resolve();
  if (lvSpineBusy) return lvSpineBusy;
  const days = LV.spineDays != null && LV_DAYS.indexOf(LV.spineDays) >= 0 ? LV.spineDays : null;
  lvSpineBusy = TL.get('/v1/uiview/facts', { query: { display_timezone: TL_TZ || 'UTC', days }, waitMs: 1500 }).then(async (res) => {
    lvSpineFails = 0;
    if (res.state === 'computing' || res.data == null) {
      LV.progress = (res.meta && res.meta.progress) || null;
      if (res.meta && res.meta.window) LV.noteWindow(res.meta.window);
      LV.stale = LV.state === 'ready'; if (LV.state !== 'ready') LV.state = 'computing';
      // the 202 names its job: poll GET /v1/analytics/jobs/{id} (backoff) and reload when it completes; without a job the
      // analysis is not running (its failure circuit is open), so the strip offers 重新计算 instead of retrying blindly
      const jid = res.meta && res.meta.job_id;
      if (jid) lvWatchSpine(jid);
      else if (TL.analysis) lvSpineFailed({ reason: TL.analysis.failed[LV_SECTION] || null });
      else lvSpineLater(1200);
      return;
    }
    LV.stale = false; LV.failed = null; LV.job = null; LV.progress = null;
    if (res.data && res.data.meta && res.data.meta.window) LV.noteWindow(res.data.meta.window);
    // 304: nothing changed — but a read that failed meanwhile has now succeeded, so leave the error state (R4-11)
    if (res.data === lvSpineData && LV.state !== 'connecting') { if (LV.state === 'error') LV.state = ALL.length ? 'ready' : 'empty'; return; }
    lvSpineData = res.data;
    const wire = res.data; const rows = LV.expand(wire);
    LV.wire = wire; LV.meta = wire.meta || null;
    const spine = { rows, projects: wire.projects || [], agents: wire.agents || [] };
    if (!rows.length) {
      const disc = await lvSide('/v1/app/discovery');
      spine.discovered = (Array.isArray(disc) ? disc : (disc && (disc.sources || disc.items)) || []).filter((x) => x && x.agent && x.status !== 'permission_denied');
    }
    if (!LV.env) { const env = await lvSide('/v1/install/environment'); LV.env = (env && env.agents) || []; }
    spine.environment = LV.env.filter((x) => x.installed);
    LV.hydrate(spine);
    LV.state = rows.length ? 'ready' : 'empty';
    lvAutoRange();
  }, (e) => {
    // 422 analysis_scope_too_large: this window is too big for the machine → 30 days, then 7 (the strip says so)
    if (e && e.code === 'analysis_scope_too_large') {
      const fb = LV.scopeTooLarge(days);
      if (fb != null && fb !== days) { LV.spineDays = fb; lvSpineAgain = true; return; }
    }
    if (e && e.code === 'analysis_unavailable') { LV.error = e; lvSpineFailed({ reason: e.reason || null, message: e.message }); return; }
    lvSpineFails++;
    // the gateway answered with an error (5xx / 4xx): that is a failed read, not a connection still being set up
    if (LV.state === 'ready' || LV.state === 'empty' || (e && e.status >= 400)) LV.state = 'error';
    else LV.state = 'connecting';
    LV.error = e;
    lvSpineLater(Math.min(15000, 1000 * Math.pow(2, Math.min(lvSpineFails, 4))));
  }).then(() => {
    lvSpineBusy = null;
    // the wanted window changed while this read was in flight (SSE analysis.ready, a range switch, a 422 fallback)
    if (lvSpineAgain || (LV.spineDays != null && LV.spineDays !== days)) { lvSpineAgain = false; setTimeout(() => LV.loadSpine(), 0); }
    else LV.widen();
    TL.changed();
  });
  return lvSpineBusy;
};

if (LV.live) {
  // live persona needs per-row units (G1): until slice 1's personaLive lands, never compute it from demo constants
  // no personal mock identity on a live screen: the gateway has no account, the user row reads as the local user
  ME.name = '本机用户'; ME.av = '我';
  persona = function (L) { return { ok: false, classified: false, n: L ? L.length : 0 }; };
  // no mock rows ever reach a live screen: start from the empty spine, then load
  LV.hydrate({ rows: [] });
  LV.state = 'connecting';
  // while an import runs, data.published arrives batch after batch: reload the spine at most every LV_IMPORT_GAP
  let lvDataT = null, lvDataLast = 0;
  const lvDataReload = () => { lvDataT = null; lvDataLast = Date.now(); LV.resetWindow(); LV.loadSpine(); };
  TL.on('event', (ev) => {
    if (/^data\b/.test(ev.name)) {
      if (!lvImporting()) { clearTimeout(lvDataT); lvDataReload(); return; }
      if (!lvDataT) lvDataT = setTimeout(lvDataReload, Math.max(0, lvDataLast + LV_IMPORT_GAP - Date.now()));
      return;
    }
    if (ev.name !== 'analysis.ready') return;
    // a wider window finished (same scope_hash as its meta.window entry): widen to it without blanking the screen
    const p = ev.data || ev.payload || ev.p || {};
    const hit = LV.window && p.scope_hash && (p.section || 'uiview_facts') === LV_SECTION && LV.window.wider.find((x) => x.scope_hash === p.scope_hash);
    if (hit) { lvWinMap[hit.days] = Object.assign({}, lvWinMap[hit.days], { state: 'ready' }); hit.state = 'ready'; if (!LV.tooLarge.has(hit.days)) LV.spineDays = hit.days; }
    LV.loadSpine();
  });
  TL.on('resync', () => LV.loadSpine());
  TL.on('retry', () => { if (!LV.failed && !LV.job && (LV.state === 'error' || LV.state === 'connecting')) { clearTimeout(lvSpineTimer); LV.loadSpine(); } });
  window.addEventListener('tandem:endpoint', () => { lvSpineData = null; LV.env = null; setTimeout(() => LV.loadSpine(), 0); });
  setTimeout(() => LV.loadSpine(), 0);
}

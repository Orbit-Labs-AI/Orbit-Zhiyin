/* ============ live core (slice 0): spine hydration, agent map, page feeds, native bridge ============
   Mock mode (file://, no gateway) changes nothing here: LV.live is false, nothing is fetched and 05-data stays as generated.
   Live mode hydrates the demo's own globals in place (ALL / BYID / AG / AGI / PJ / PJI, DAY0 / LASTDAY) from
   GET /v1/uiview/facts, so every polished renderer, filter and animation runs unchanged on real rows. Page files hook
   their constants through LV.feed(); see .work/release/slice0-notes.md for the contract. */
const TL = TandemLive.create({ onChange: () => render() });
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
  // tandem:command {cmd:'settings'|'palette'|'about'|'route'|'toggleEdition'|'refresh', route?}
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
// the arrival re-renders; later calls are cache hits (no request).
LV.detail = function (cache, key, path, o) {
  let e = cache.get(key);
  if (!e) {
    e = cache.set(key, { state: 'pending', data: null, error: null });
    TL.get(path, o || {}).then((res) => { e.state = res.data == null ? 'pending' : 'ready'; e.data = res.data; if (res.state === 'computing') cache.delete(key); },
      (err) => { e.state = 'error'; e.error = err; }).then(() => TL.changed());
  }
  return e;
};

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
LV.pump = function (route) {
  if (!LV.live) return;
  (LV.feeds[route] || []).forEach((f) => {
    const rs = lvFeedRes(f);
    rs.forEach((x) => { if (x.r.dirty && !x.r.loading) TL.load(x.r); });
    const err = rs.find((x) => x.r.state === 'error' && x.r.data == null);
    if (err) { f.state = 'error'; f.error = err.r.error; return; }
    if (rs.some((x) => x.r.data == null)) { f.state = rs.some((x) => x.r.state === 'computing') ? 'computing' : 'pending'; return; }
    const stamp = rs.map((x) => x.r.key + '@' + x.r.updatedAt).join('|') + '#' + LV.rev;
    if (stamp === f.stamp) return;
    const data = rs.length === 1 && rs[0].name === '_' ? rs[0].r.data : rs.reduce((o, x) => { o[x.name] = x.r.data; return o; }, {});
    try { f.apply(data, { route, rev: LV.rev }); f.state = 'ready'; f.data = data; f.stamp = stamp; }
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
  // agents: present in facts or detected, ordered by session count; deselections survive by id
  const prevOff = new Set(AG.filter((a) => !S.agents.has(a.id)).map((a) => a.id));
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
  S.agents = new Set(AG.map((a) => a.id).filter((id) => !prevOff.has(id)));
  S.srcOff = new Set(Array.from(S.srcOff).filter((id) => AGI[id]));
  if (S.project && !PJI[S.project]) S.project = null;
  const done = ALL.filter((s) => !s.live);
  const newest = done.length ? done[done.length - 1] : ALL[ALL.length - 1];
  if (!BYID[S.sess.sel]) S.sess.sel = newest ? newest.id : null;
  if (S.sess.cmp && !BYID[S.sess.cmp]) S.sess.cmp = null;
  if (!PJI[S.proj.sel]) S.proj.sel = PJ[0] ? PJ[0].id : null;
  if (S.proj.cmp && !PJI[S.proj.cmp]) S.proj.cmp = null;
};

let lvSpineTimer = null, lvSpineBusy = null, lvSpineFails = 0, lvSpineData = null;
function lvSpineLater(ms) { clearTimeout(lvSpineTimer); lvSpineTimer = setTimeout(() => LV.loadSpine(), ms); }
const lvSide = (path) => TL.get(path).then((r) => r.data, () => null);
LV.loadSpine = function () {
  if (!LV.live) return Promise.resolve();
  if (lvSpineBusy) return lvSpineBusy;
  lvSpineBusy = TL.get('/v1/uiview/facts', { query: { display_timezone: TL_TZ || 'UTC' }, waitMs: 1500 }).then(async (res) => {
    lvSpineFails = 0;
    if (res.state === 'computing' || res.data == null) {
      LV.stale = LV.state === 'ready'; if (LV.state !== 'ready') LV.state = 'computing';
      lvSpineLater(1200); return;
    }
    LV.stale = false;
    if (res.data === lvSpineData && LV.state !== 'connecting') return;   // 304: nothing changed
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
  }, (e) => {
    lvSpineFails++;
    if (LV.state === 'ready' || LV.state === 'empty') LV.state = 'error';
    else LV.state = 'connecting';
    LV.error = e;
    lvSpineLater(Math.min(15000, 1000 * Math.pow(2, Math.min(lvSpineFails, 4))));
  }).then(() => { lvSpineBusy = null; TL.changed(); });
  return lvSpineBusy;
};

if (LV.live) {
  // live persona needs per-row units (G1): until slice 1's personaLive lands, never compute it from demo constants
  persona = function (L) { return { ok: false, classified: false, n: L ? L.length : 0 }; };
  // no mock rows ever reach a live screen: start from the empty spine, then load
  LV.hydrate({ rows: [] });
  LV.state = 'connecting';
  TL.on('event', (ev) => { if (/^data\b|^analysis\.ready$/.test(ev.name)) LV.loadSpine(); });
  TL.on('resync', () => LV.loadSpine());
  window.addEventListener('tandem:endpoint', () => { lvSpineData = null; LV.env = null; setTimeout(() => LV.loadSpine(), 0); });
  setTimeout(() => LV.loadSpine(), 0);
}

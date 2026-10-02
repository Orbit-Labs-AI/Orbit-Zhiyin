// Unit tests for the shared live adapter (prototypes/shared/tandem-live.js). Run: node --test prototypes/shared/tests/
// Every response comes from the hand-written fixtures in ../fixtures; nothing talks to a real gateway or reads local sessions.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const TandemLive = require('../tandem-live.js');

const FX = (name) => JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'fixtures', name + '.json'), 'utf8'));
const tick = (ms = 5) => new Promise((r) => setTimeout(r, ms));
const json = (body, status = 200, headers = {}) => new Response(status === 304 ? null : JSON.stringify(body), { status, headers: Object.assign({ 'Content-Type': 'application/json' }, headers) });
const ENDPOINT = 'http://gw.test';

// Fake gateway: route(pathname, handler(url, init, n)) where n counts the hits on that path; every call is recorded.
function gateway(routes) {
  const calls = [];
  const hits = {};
  const fetch = async (url, init = {}) => {
    const u = new URL(url);
    calls.push({ url: u, headers: init.headers || {}, signal: init.signal });
    if (init.signal && init.signal.aborted) throw Object.assign(new Error('aborted'), { name: 'AbortError' });
    const h = routes[u.pathname];
    if (!h) return json({ error: { code: 'not_found', message: u.pathname, retryable: false } }, 404);
    hits[u.pathname] = (hits[u.pathname] || 0) + 1;
    return h(u, init, hits[u.pathname]);
  };
  return { fetch, calls, hits };
}
// Timers: short delays run for real; ≥ 1 s delays (Retry-After) are recorded so the test can fire them by hand.
function timers() {
  const long = [];
  return {
    long,
    setTimeout(f, ms) { if (ms >= 1000) { const t = { f, ms }; long.push(t); return t; } return setTimeout(f, ms); },
    clearTimeout(t) { const i = long.indexOf(t); if (i >= 0) long.splice(i, 1); else clearTimeout(t); }
  };
}
const live = (gw, extra = {}) => TandemLive.create(Object.assign({ mode: 'live', endpoint: ENDPOINT, token: 'tok', fetch: gw.fetch, timers: timers(), win: {} }, extra));

test('mode: file:// and plain pages are mock, gateway paths and ?live=1 are live; #token= is taken and removed', () => {
  assert.equal(TandemLive.detectMode({ location: { protocol: 'file:', pathname: '/x/tandem-demo.html', search: '' } }), 'mock');
  assert.equal(TandemLive.detectMode({ location: { protocol: 'http:', pathname: '/prototypes/demo.html', search: '' } }), 'mock');
  assert.equal(TandemLive.detectMode({ location: { protocol: 'http:', pathname: '/app', search: '' } }), 'live');
  assert.equal(TandemLive.detectMode({ location: { protocol: 'http:', pathname: '/lite/', search: '' } }), 'live');
  assert.equal(TandemLive.detectMode({ location: { protocol: 'http:', pathname: '/x.html', search: '?live=1' } }), 'live');
  let replaced = null;
  const win = { location: { protocol: 'http:', origin: 'http://gw.test', pathname: '/app', search: '', hash: '#sessions&token=abc' }, history: { replaceState: (a, b, u) => { replaced = u; } } };
  const C = TandemLive.create({ win, fetch: async () => json({}) });
  assert.equal(C.mode, 'live');
  assert.equal(C.token, 'abc');
  assert.equal(C.endpoint, 'http://gw.test');
  assert.equal(replaced, '/app#sessions');
});

test('scope: explicit empty lists, agent ids to source_ids, presets give the same query all day, no until_ts', () => {
  const status = FX('status');
  const morning = new Date(2026, 9, 1, 0, 5).getTime(), night = new Date(2026, 9, 1, 23, 55).getTime();
  const a = TandemLive.serializeScope({ range: 7, agents: ['cc', 'cx'], projects: null, tz: 'Asia/Shanghai' }, status, morning);
  const b = TandemLive.serializeScope({ range: 7, agents: ['cx', 'cc'], projects: null, tz: 'Asia/Shanghai' }, status, night);
  assert.equal(a, b);
  assert.match(a, /^from_ts=\d+&source_ids=src-claude&source_ids=src-codex&display_timezone=Asia%2FShanghai$/);
  assert.equal(Number(/from_ts=(\d+)/.exec(a)[1]), new Date(2026, 8, 25).getTime());
  assert.doesNotMatch(a, /until_ts/);
  // explicit empty selections are sent as `key=`; a disabled source never appears; null means "all" and is omitted
  assert.equal(TandemLive.serializeScope({ range: 0, agents: [], projects: [] }, status, morning), 'source_ids=&project_ids=');
  assert.equal(TandemLive.serializeScope({ range: 0, agents: ['gm'] }, status, morning), 'source_ids=');
  assert.equal(TandemLive.serializeScope({ range: 0, agents: null, excluded: ['s2', 's1'] }, status, morning), 'excluded_session_uids=s1&excluded_session_uids=s2');
  assert.notEqual(TandemLive.serializeScope({ range: 7 }, status, morning), TandemLive.serializeScope({ range: 7 }, status, morning + 86400000));
});

test('get: sends the token, stores the ETag and turns a 304 into the cached body', async () => {
  const gw = gateway({ '/v1/analytics/overview': (u, init, n) => n === 1 ? json(FX('overview'), 200, { ETag: 'W/"r:42:h:overview"' }) : (init.headers['If-None-Match'] === 'W/"r:42:h:overview"' ? json(null, 304) : json({}, 500)) });
  const C = live(gw);
  const first = await C.get('/v1/analytics/overview');
  assert.equal(first.status, 200);
  assert.equal(gw.calls[0].headers.Authorization, 'Bearer tok');
  const second = await C.get('/v1/analytics/overview');
  assert.equal(second.status, 304);
  assert.equal(gw.calls[1].headers['If-None-Match'], 'W/"r:42:h:overview"');
  assert.deepEqual(second.data, first.data);
  assert.equal(second.state, 'ready');
});

test('get: concurrent requests for one key share a fetch; aborting one waiter keeps the other, aborting all cancels it', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  const gw = gateway({ '/v1/analytics/tools': async () => { await gate; return json(FX('tools')); } });
  const C = live(gw);
  const a1 = new AbortController();
  const p1 = C.get('/v1/analytics/tools', { signal: a1.signal });
  const p2 = C.get('/v1/analytics/tools');
  await tick();
  assert.equal(gw.calls.length, 1);
  a1.abort();
  await assert.rejects(p1, { name: 'AbortError' });
  release();
  assert.equal((await p2).data.tools.totals.call_count, 6431);

  let release2; const gate2 = new Promise((r) => { release2 = r; });
  const gw2 = gateway({ '/v1/analytics/tools': async (u, init) => { await gate2; if (init.signal.aborted) throw Object.assign(new Error('aborted'), { name: 'AbortError' }); return json(FX('tools')); } });
  const C2 = live(gw2);
  const x = new AbortController(), y = new AbortController();
  const q1 = C2.get('/v1/analytics/tools', { signal: x.signal }), q2 = C2.get('/v1/analytics/tools', { signal: y.signal });
  await tick();
  x.abort(); y.abort();
  await assert.rejects(q1, { name: 'AbortError' }); await assert.rejects(q2, { name: 'AbortError' });
  assert.equal(gw2.calls[0].signal.aborted, true);
  assert.equal(C2.inflightCount(), 0);
  release2();
});

test('page switch aborts the previous page loads and leaves them dirty for the next visit', async () => {
  let release; const gate = new Promise((r) => { release = r; });
  const gw = gateway({
    '/v1/analytics/tools': async (u, init) => { await gate; if (init.signal.aborted) throw Object.assign(new Error('aborted'), { name: 'AbortError' }); return json(FX('tools')); },
    '/v1/analytics/projects': () => json(FX('projects'))
  });
  const C = live(gw);
  C.bind('tools', [{ name: 'tools', path: '/v1/analytics/tools' }], (d) => d.tools.tools);
  C.bind('projects', [{ name: 'projects', path: '/v1/analytics/projects' }], (d) => d.projects.projects.records);
  assert.equal(C.view('tools', { range: 30 }).state, 'loading');
  await tick();
  C.view('projects', { range: 30 });
  assert.equal(gw.calls[0].signal.aborted, true);
  release(); await tick();
  const res = C.resource('/v1/analytics/tools', { scope: { range: 30 } });
  assert.equal(res.dirty, true);
  assert.equal(res.state, 'idle');
});

test('stale snapshot shows a badge and refreshes to fresh after analysis.ready', async () => {
  const gw = gateway({ '/v1/analytics/overview': (u, i, n) => json(n === 1 ? FX('overview-stale') : FX('overview')) });
  const C = live(gw);
  C.bind('overview', [{ name: 'ov', path: '/v1/analytics/overview' }], (d) => d.ov.overview.counts);
  C.view('overview', null); await tick();
  let v = C.view('overview', null);
  assert.equal(v.state, 'stale');
  assert.equal(v.vm.sessions, 120);
  assert.match(TandemLive.ui.badge(v), /更新于 .* · 正在刷新/);
  const r = C.resource('/v1/analytics/overview');
  C.invalidate((x) => x === r);   // what analysis.ready does for its section
  v = C.view('overview', null);
  assert.equal(v.state, 'stale');   // last good data stays on screen while refreshing
  assert.equal(v.vm.sessions, 120);
  await tick();
  v = C.view('overview', null);
  assert.equal(v.state, 'ready');
  assert.equal(v.vm.sessions, 128);
});

// SSE helper: a gateway route whose n-th connection answers with the given frames (then closes) or a status code.
function sse(script) {
  return (u, init, n) => {
    const step = script[Math.min(n, script.length) - 1];
    if (typeof step === 'number') return new Response('', { status: step });
    const text = step.map((f) => (f.id ? 'id: ' + f.id + '\n' : '') + 'event: ' + f.event + '\ndata: ' + JSON.stringify(f.data) + '\n\n').join('');
    const enc = new TextEncoder().encode(text);
    // deliver in two chunks split mid-frame so the parser has to buffer
    const cut = Math.floor(enc.length / 2);
    return new Response(new ReadableStream({ start(c) { c.enqueue(enc.slice(0, cut)); c.enqueue(enc.slice(cut)); c.close(); } }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
  };
}

test('202 computing shows a skeleton, then analysis.ready over SSE triggers the refetch', async () => {
  let ready = false;
  const frames = FX('events').frames.filter((f) => f.event === 'analysis.ready');
  const gw = gateway({
    '/v1/analytics/overview': () => ready ? json(FX('overview')) : json(FX('overview-computing'), 202),
    '/v1/events': (u, i, n) => ready ? sse([frames])(u, i, 1) : sse([[]])(u, i, 1)
  });
  const C = live(gw, { backoff: { base: 2, max: 8 } });
  C.bind('overview', [{ name: 'ov', path: '/v1/analytics/overview' }], (d) => d.ov.overview.counts);
  C.view('overview', null); await tick();
  let v = C.view('overview', null);
  assert.equal(v.state, 'computing');
  assert.equal(v.vm, null);
  assert.match(TandemLive.ui.body(v, () => 'X'), /tl-skel/);
  ready = true;
  C.connectEvents();
  await tick(30);
  await C.stopEvents();
  v = C.view('overview', null); await tick();
  v = C.view('overview', null);
  assert.equal(v.state, 'ready');
  assert.equal(v.vm.tool_calls, 6431);
  assert.ok(gw.hits['/v1/analytics/overview'] >= 2);
});

test('503 + Retry-After keeps the last screen, shows the banner and retries after the delay', async () => {
  let down = false;
  const gw = gateway({ '/v1/analytics/overview': () => down ? json(FX('error-503'), 503, { 'Retry-After': '2' }) : json(FX('overview')) });
  const t = timers();
  const C = live(gw, { timers: t });
  C.bind('overview', [{ name: 'ov', path: '/v1/analytics/overview' }], (d) => d.ov.overview.counts);
  C.view('overview', null); await tick();
  down = true;
  C.invalidate();
  C.view('overview', null); await tick();
  const v = C.view('overview', null);
  assert.equal(v.state, 'error');
  assert.equal(v.vm.sessions, 128);                  // previous screen kept
  assert.equal(v.error.code, 'projection_pending');
  assert.match(TandemLive.ui.banner(C), /服务暂时不可用.*2 秒后重试/);
  assert.match(TandemLive.ui.body(v, (vm) => 'sessions=' + vm.sessions), /sessions=128/);
  const retry = t.long.find((x) => x.ms === 2000);
  assert.ok(retry, 'retry scheduled from Retry-After');
  down = false; retry.f(); await tick();
  C.view('overview', null); await tick();
  assert.equal(C.view('overview', null).state, 'ready');
  assert.equal(TandemLive.ui.banner(C), '');
});

test('SSE: exponential backoff, Last-Event-ID resume and resync on a gap', async () => {
  const f = FX('events').frames;
  const gw = gateway({
    '/v1/status': () => json(FX('status')),
    '/v1/events': sse([503, 503, [f[0], f[1]], [{ id: '7', event: 'service', data: { name: 'analysis', state: 'degraded' } }], [] ])
  });
  const C = live(gw, { backoff: { base: 1, max: 4 } });
  C.connectEvents();
  await tick(60);
  await C.stopEvents();
  const ev = gw.calls.filter((c) => c.url.pathname === '/v1/events');
  assert.ok(ev.length >= 4);
  assert.deepEqual(C.events.delays.slice(0, 2), [1, 2]);           // two failures in a row: 1, 2 …
  assert.equal(ev[0].headers.Authorization, 'Bearer tok');
  assert.equal(ev[2].headers['Last-Event-ID'], undefined);
  assert.equal(ev[3].headers['Last-Event-ID'], '2');               // resumes after the last frame seen
  assert.equal(C.events.resyncs, 1);                               // id 7 after 2: frames were lost
  assert.equal(C.services.analysis, 'degraded');
  assert.equal(C.job.kind, 'import');
  assert.match(TandemLive.ui.progress(C), /正在导入 · 写入批次 · 40 \/ 128/);
  assert.match(TandemLive.ui.banner(C), /服务异常：analysis 降级/);
});

test('events only invalidate the matching resources', async () => {
  const gw = gateway({ '/v1/analytics/overview': () => json(FX('overview')), '/v1/analytics/tools': () => json(FX('tools')),
    '/v1/events': sse([[{ id: '1', event: 'analysis.ready', data: { section: 'tools', scope_hash: 'sha256:fx-tools' } }], []]) });
  const C = live(gw, { backoff: { base: 50, max: 50 } });
  const ov = C.resource('/v1/analytics/overview'), tl = C.resource('/v1/analytics/tools');
  await C.load(ov); await C.load(tl);
  C.connectEvents(); await tick(20); await C.stopEvents();
  assert.equal(ov.dirty, false);
  assert.equal(tl.dirty, true);
});

test('live failure never falls back to demo data', async () => {
  const gw = { fetch: async () => { throw new TypeError('fetch failed'); } };
  const C = live(gw);
  C.bind('overview', [{ name: 'ov', path: '/v1/analytics/overview' }], (d) => d.ov.overview.counts);
  C.start();
  C.view('overview', null); await tick();
  const v = C.view('overview', null);
  assert.equal(v.state, 'error');
  assert.equal(v.vm, null);
  const html = TandemLive.ui.body(v, () => 'DEMO');
  assert.doesNotMatch(html, /DEMO/);
  assert.match(html, /读取失败/);
  assert.equal(C.error.code, 'network');
  assert.match(TandemLive.ui.banner(C), /无法连接 Orbit 本地服务/);
  await C.stopEvents();
  // mock mode never requests anything
  let n = 0;
  const M = TandemLive.create({ mode: 'mock', fetch: async () => { n++; return json({}); }, win: {} });
  await assert.rejects(M.get('/v1/status'), { code: 'mock_mode' });
  assert.equal(M.view('overview', null), null);
  assert.equal(n, 0);
});

test('unbound pages carry the 示例数据 badge in live mode; mock mode adds nothing', () => {
  const C = live(gateway({}));
  C.bind('overview', [{ name: 'ov', path: '/v1/analytics/overview' }], (d) => d);
  assert.match(TandemLive.ui.strip(C, 'persona', null), /示例数据/);
  assert.doesNotMatch(TandemLive.ui.strip(C, 'overview', { state: 'ready' }), /示例数据/);
  const M = TandemLive.create({ mode: 'mock', win: {} });
  assert.equal(TandemLive.ui.strip(M, 'persona', null), '');
});

test('empty and importing states; missing values render as —, never 0', async () => {
  const gw = gateway({ '/v1/analytics/overview': () => json(FX('overview-empty')) });
  const C = live(gw);
  C.bind('overview', [{ name: 'ov', path: '/v1/analytics/overview' }], (d) => d.ov.overview);
  C.view('overview', null); await tick();
  assert.equal(C.view('overview', null).state, 'empty');
  C.job = { kind: 'import', status: 'running', progress: { completed: 1, total: 4 } };
  assert.equal(C.view('overview', null).state, 'importing');
  assert.equal(TandemLive.ui.num(null), '—');
  assert.equal(TandemLive.ui.num(0), '0');
  assert.equal(TandemLive.ui.pct(null), '—');
  assert.equal(TandemLive.ui.money(undefined), '—');
});

test('tandem:endpoint switches endpoint and token, drops cached ETags and reconnects', async () => {
  const seen = [];
  const fetch = async (url, init) => { seen.push([new URL(url).origin, init.headers.Authorization]); return json(FX('status'), 200, { ETag: 'W/"s"' }); };
  const handlers = {};
  const win = { addEventListener: (n, f) => { handlers[n] = f; } };
  const C = TandemLive.create({ mode: 'live', endpoint: ENDPOINT, token: 'old', fetch, win, timers: timers(), backoff: { base: 1000, max: 1000 } });
  C.start(); await tick();
  handlers['tandem:endpoint']({ detail: { endpoint: 'http://gw2.test/', token: 'new' } });
  await tick(10);
  await C.stopEvents();
  assert.ok(seen.some(([o, a]) => o === 'http://gw2.test' && a === 'Bearer new'));
  assert.equal(C.endpoint, 'http://gw2.test');
});

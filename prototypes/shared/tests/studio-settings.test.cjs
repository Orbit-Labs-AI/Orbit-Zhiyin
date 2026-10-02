// Unit tests for the studio-settings section of the live adapter (send / unavailable / pollJob / collection frames).
// Responses come from ../fixtures/studio-settings; nothing talks to a real gateway. Run: node --test prototypes/shared/tests/
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const TandemLive = require('../tandem-live.js');

const FX = (name) => JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'fixtures', 'studio-settings', name + '.json'), 'utf8'));
const tick = (ms = 5) => new Promise((r) => setTimeout(r, ms));
const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers: Object.assign({ 'Content-Type': 'application/json' }, headers) });

function gateway(routes) {
  const calls = []; const hits = {};
  const fetch = async (url, init = {}) => {
    const u = new URL(url);
    calls.push({ url: u, method: init.method || 'GET', headers: init.headers || {}, body: init.body ? JSON.parse(init.body) : null });
    const h = routes[(init.method || 'GET') + ' ' + u.pathname] || routes[u.pathname];
    if (!h) return json({ error: { code: 'not_found', message: u.pathname, retryable: false } }, 404);
    hits[u.pathname] = (hits[u.pathname] || 0) + 1;
    return h(u, init, hits[u.pathname]);
  };
  return { fetch, calls };
}
function timers() {
  const long = [];
  return { long, setTimeout(f, ms) { if (ms >= 1000) { const t = { f, ms }; long.push(t); return t; } return setTimeout(f, ms); }, clearTimeout(t) { const i = long.indexOf(t); if (i >= 0) long.splice(i, 1); else clearTimeout(t); } };
}
const live = (gw) => TandemLive.create({ mode: 'live', endpoint: 'http://gw.test', token: 'tok', fetch: gw.fetch, timers: timers(), win: {} });
function sse(frames) {
  return () => new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode(frames.map((f) => 'id: ' + f.id + '\nevent: ' + f.event + '\ndata: ' + JSON.stringify(f.data) + '\n\n').join(''))); c.close(); } }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

test('send: JSON body, bearer token, query; errors carry status / code / detail', async () => {
  const gw = gateway({
    'POST /v1/ai/preview': () => json(FX('ai-preview')),
    'POST /v1/ai/jobs': () => json({ error: { code: 'consent_required', message: '需要授权', detail: { missing: ['snippets'] } } }, 403),
    'PUT /v1/notifications/policy': () => json(FX('notify-policy-all'))
  });
  const C = live(gw);
  const r = await C.send('POST', '/v1/ai/preview', { task_id: 'generate.skill' });
  assert.equal(r.status, 200);
  assert.equal(r.data.preview_digest, 'sha256:fx-preview');
  assert.equal(gw.calls[0].headers.Authorization, 'Bearer tok');
  assert.equal(gw.calls[0].headers['Content-Type'], 'application/json');
  assert.deepEqual(gw.calls[0].body, { task_id: 'generate.skill' });
  await assert.rejects(C.send('POST', '/v1/ai/jobs', {}), (e) => e.status === 403 && e.code === 'consent_required' && e.detail.missing[0] === 'snippets' && !C.unavailable(e));
  await C.send('PUT', '/v1/notifications/policy', {}, { query: { preset: 'all' } });
  assert.equal(gw.calls[2].url.search, '?preset=all');
  assert.equal(C.inflightCount(), 0);
});

test('unavailable: 404 / 501 / 503 / network fall back to demo values; 4xx answers do not; mock mode rejects', async () => {
  const gw = gateway({ 'GET /v1/ai/engines': () => json({ error: { code: 'not_available' } }, 501), 'GET /v1/platform/health': () => json({}, 503) });
  const C = live(gw);
  for (const p of ['/v1/ai/engines', '/v1/platform/health', '/v1/nope']) await assert.rejects(C.send('GET', p), (e) => C.unavailable(e));
  const down = TandemLive.create({ mode: 'live', endpoint: 'http://gw.test', fetch: async () => { throw new TypeError('fetch failed'); }, timers: timers(), win: {} });
  await assert.rejects(down.send('GET', '/v1/ai/engines'), (e) => e.code === 'network' && down.unavailable(e));
  assert.equal(C.unavailable({ status: 409, code: 'preview_stale' }), false);
  const mock = TandemLive.create({ mode: 'mock', win: {} });
  await assert.rejects(mock.send('GET', '/v1/ai/engines'), (e) => e.code === 'mock_mode');
});

test('pollJob: polls until the job ends; an ai.job frame wakes it before the interval', async () => {
  let done = false;
  const gw = gateway({
    '/v1/ai/jobs/fx-job-1': () => json(done ? FX('ai-job-done') : FX('ai-job-running')),
    '/v1/events': sse([{ id: '1', event: 'ai.job', data: { job_id: 'fx-job-1', status: 'succeeded' } }])
  });
  const C = live(gw);
  const seen = [];
  const p = C.pollJob('fx-job-1', (j) => seen.push(j.status), { intervalMs: 5000 });   // ≥ 1 s: only the frame can wake it
  await tick(20);
  assert.deepEqual(seen, ['running']);
  done = true;
  C.connectEvents();
  const job = await p;
  await C.stopEvents();
  assert.equal(job.artifact_id, 'fx-art-1');
  assert.deepEqual(seen, ['running', 'succeeded']);
});

test('pollJob: abort stops polling with an AbortError', async () => {
  const gw = gateway({ '/v1/ai/jobs/fx-job-1': () => json(FX('ai-job-running')) });
  const C = live(gw);
  const ctrl = new AbortController();
  const p = C.pollJob('fx-job-1', null, { intervalMs: 5000, signal: ctrl.signal });
  await tick(20); ctrl.abort();
  await assert.rejects(p, (e) => e.name === 'AbortError');
});

test('notify topic is requested; a collection service frame sets C.collection and raises no service banner', async () => {
  const frames = FX('notify-frames').frames;
  const gw = gateway({ '/v1/events': sse(frames) });
  const C = live(gw);
  const names = []; C.on('event', (e) => names.push(e.name));
  C.connectEvents(); await tick(30); await C.stopEvents();
  assert.match(gw.calls.find((c) => c.url.pathname === '/v1/events').url.search, /topics=[^&]*notify/);
  assert.deepEqual(names, ['notification', 'attention', 'service']);
  assert.equal(C.collection, 'paused');
  assert.equal(C.services.collection, undefined);
  assert.equal(TandemLive.ui.banner(C), '');
});

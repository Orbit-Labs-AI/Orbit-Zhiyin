// Round-3 API: a 202 names its job (GET /v1/analytics/jobs/{id} is polled with backoff instead of blind refetches);
// 503 analysis_unavailable carries its reason, raises no banner, schedules no retry; POST /v1/analytics/recompute resets it.
// Synthetic bodies only. Run: node --test prototypes/shared/tests/
const test = require('node:test');
const assert = require('node:assert/strict');
const OrbitLive = require('../orbit-live.js');

const tick = (ms = 5) => new Promise((r) => setTimeout(r, ms));
const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers: Object.assign({ 'Content-Type': 'application/json' }, headers) });
function gateway(routes) {
  const calls = []; const hits = {};
  const fetch = async (url, init = {}) => {
    const u = new URL(url); const k = (init.method || 'GET') + ' ' + u.pathname;
    calls.push({ k, url: u, body: init.body ? JSON.parse(init.body) : null });
    const h = routes[k];
    if (!h) return json({ error: { code: 'not_found', message: u.pathname } }, 404);
    hits[k] = (hits[k] || 0) + 1;
    return h(u, init, hits[k]);
  };
  return { fetch, calls, hits };
}
const live = (gw) => OrbitLive.create({ mode: 'live', endpoint: 'http://gw.test', token: 't', fetch: gw.fetch, win: {} });
const OV = { overview: { counts: { sessions: 12 } }, meta: { freshness: 'fresh' } };

test('202 with job_id polls the job with backoff, then refetches once it completes', async () => {
  let done = false; const seen = [];
  const gw = gateway({
    'GET /v1/analytics/overview': () => (done ? json(OV) : json({ meta: { freshness: 'computing', job_id: 'job-1' } }, 202)),
    'GET /v1/analytics/jobs/job-1': (u, i, n) => { seen.push(Date.now()); if (n >= 3) done = true; return json({ id: 'job-1', status: n >= 3 ? 'completed' : 'running', elapsed_s: n, timeout_s: 60 }); }
  });
  const C = live(gw);
  C.bind('overview', [{ name: 'ov', path: '/v1/analytics/overview' }], (d) => d.ov.overview.counts);
  C.view('overview', null); await tick(20);
  assert.equal(C.view('overview', null).state, 'computing');
  await tick(2200);
  C.view('overview', null); await tick(20);
  const v = C.view('overview', null);
  assert.equal(v.state, 'ready'); assert.equal(v.vm.sessions, 12);
  assert.equal(gw.hits['GET /v1/analytics/jobs/job-1'], 3);
  assert.equal(gw.hits['GET /v1/analytics/overview'], 2, 'no blind refetch while the job runs');
  assert.ok(seen[2] - seen[1] > seen[1] - seen[0], 'backoff grows');
});

test('a failed job becomes analysis_unavailable with its reason; recompute posts the scope and polls the new job', async () => {
  let phase = 'fail';
  const gw = gateway({
    'GET /v1/analytics/overview': () => (phase === 'ok' ? json(OV) : json({ meta: { freshness: 'computing', job_id: 'job-1' } }, 202)),
    'GET /v1/analytics/jobs/job-1': () => json({ id: 'job-1', status: 'failed', error: { code: 'timeout', message: 'analysis exceeded its time budget' } }),
    'POST /v1/analytics/recompute': () => json({ jobs: [{ section: 'overview', scope_hash: 'h', job_id: 'job-2' }], data_rev: 3 }, 202),
    'GET /v1/analytics/jobs/job-2': () => { phase = 'ok'; return json({ id: 'job-2', status: 'completed' }); }
  });
  const C = live(gw);
  C.bind('overview', [{ name: 'ov', path: '/v1/analytics/overview' }], (d) => d.ov.overview.counts);
  C.view('overview', { range: 7, tz: 'Asia/Shanghai' }); await tick(60);
  let v = C.view('overview', { range: 7, tz: 'Asia/Shanghai' });
  assert.equal(v.state, 'error'); assert.equal(v.error.code, 'analysis_unavailable'); assert.equal(v.error.reason, 'timeout');
  assert.equal(OrbitLive.ui.unavailable(v.error), '分析超时');
  assert.match(OrbitLive.ui.body(v, () => 'X'), /data-tl="unavailable"[^>]*>分析超时/);
  assert.equal(OrbitLive.ui.banner(C), '', 'no service banner for a failed analysis');
  await C.recompute(v.res.ov);
  const post = gw.calls.find((c) => c.k === 'POST /v1/analytics/recompute');
  assert.deepEqual(post.body.sections, ['overview']);
  assert.equal(post.body.scope.display_timezone, 'Asia/Shanghai'); assert.equal(typeof post.body.scope.from_ts, 'number');
  await tick(60);
  C.view('overview', { range: 7, tz: 'Asia/Shanghai' }); await tick(20);
  v = C.view('overview', { range: 7, tz: 'Asia/Shanghai' });
  assert.equal(v.state, 'ready'); assert.equal(v.vm.sessions, 12);
});

test('503 analysis_unavailable: reason from the message, no Retry-After loop, no banner', async () => {
  const gw = gateway({ 'GET /v1/analytics/tools': () => json({ error: { code: 'analysis_unavailable', message: 'timeout: analysis exceeded its time budget', retryable: true } }, 503, { 'Retry-After': '5' }) });
  const C = live(gw);
  const r = C.resource('/v1/analytics/tools');
  await C.load(r);
  assert.equal(r.state, 'error'); assert.equal(r.error.reason, 'timeout'); assert.equal(r.error.retryable, false);
  assert.equal(r.retryTimer, null); assert.equal(C.failure, null);
  assert.equal(OrbitLive.ui.reason('worker_crashed'), '分析进程异常退出');
});

test('a 202 whose job is gone (404) refetches once instead of polling forever', async () => {
  let n = 0;
  const gw = gateway({ 'GET /v1/uiview/facts': () => (++n > 1 ? json({ rows: [], meta: { freshness: 'fresh' } }) : json({ meta: { freshness: 'computing', job_id: 'gone' } }, 202)) });
  const C = live(gw);
  const r = C.resource('/v1/uiview/facts', { query: { display_timezone: 'UTC' } });
  await C.load(r); await tick(20);
  assert.equal(r.dirty, true);
  await C.load(r);
  assert.equal(r.state, 'ready');
});

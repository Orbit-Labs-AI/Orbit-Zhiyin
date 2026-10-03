// Unit tests for the ops section of the live adapter: realtime derive / buckets / SSE stream, session ops (exclude, resume,
// locate, tool-call drilldown) and export (CSV text, report, share card). Responses come from ../fixtures/ops; nothing talks
// to a real gateway. Run: node --test prototypes/shared/tests/
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const OrbitLive = require('../orbit-live.js');

const DIR = path.join(__dirname, '..', 'fixtures', 'ops');
const FX = (name) => JSON.parse(fs.readFileSync(path.join(DIR, name + '.json'), 'utf8'));
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const H = OrbitLive.ops;

function gateway(routes) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const u = new URL(url);
    calls.push({ url: u, method: init.method || 'GET', headers: init.headers || {}, body: init.body ? JSON.parse(init.body) : null });
    const h = routes[(init.method || 'GET') + ' ' + u.pathname] || routes[u.pathname];
    if (!h) return json({ error: { code: 'not_found', message: u.pathname, retryable: false } }, 404);
    return h(u, init, calls.length);
  };
  return { fetch, calls };
}
const timers = { setTimeout: (f, ms) => setTimeout(f, Math.min(ms, 5)), clearTimeout: (t) => clearTimeout(t) };
const live = (gw) => OrbitLive.create({ mode: 'live', endpoint: 'http://gw.test', token: 'tok', fetch: gw.fetch, timers, win: {} });
const sseBody = (chunks) => new ReadableStream({ start(c) { chunks.forEach((x) => c.enqueue(new TextEncoder().encode(x))); c.close(); } });

test('rtDerive: primary is the running session; alerts, others and today come from the snapshot', () => {
  const d = H.rtDerive(FX('realtime-active'));
  assert.equal(d.primary.session_uid, 'fx-rt-run');
  assert.deepEqual(d.failing.map((s) => s.session_uid), ['fx-rt-fail']);
  assert.deepEqual(d.waiting.map((s) => s.session_uid), ['fx-rt-wait']);
  assert.deepEqual(d.ctx.map((s) => s.session_uid), ['fx-rt-run']);
  assert.deepEqual(d.finished.map((s) => s.session_uid), ['fx-rt-done']);
  assert.deepEqual(d.others.map((s) => s.session_uid), ['fx-rt-fail', 'fx-rt-wait']);
  assert.equal(d.today.sessions_started, 7);
  assert.equal(H.rtCtxPct(d.primary), 91);
  assert.equal(H.rtCtxTh(d.primary), 92);
  assert.equal(H.rtCtxTh(d.failing[0]), 80, 'no auto-compact ratio → the demo default');
  const idle = H.rtDerive(FX('realtime-idle'));
  assert.equal(idle.primary, null); assert.equal(idle.active.length, 0);
  assert.equal(H.rtDerive(null).status, 'idle');
});

test('rtBuckets: lanes land in the right buckets; failures and your messages are counted apart', () => {
  const s = FX('realtime-active').sessions[0]; const now = FX('realtime-active').generated_at;
  const b = H.rtBuckets(s, now, 20, 30);
  assert.equal(b.length, 40);
  assert.equal(b.reduce((n, x) => n + x.tool, 0), 9);
  assert.equal(b.reduce((n, x) => n + x.err, 0), 1);
  assert.equal(b.reduce((n, x) => n + x.user, 0), 2);
  assert.equal(b[39].tool, 1, 'the call 20 s ago is in the last bucket');
  const five = H.rtBuckets(s, now, 5, 60);
  assert.equal(five.length, 5);
  assert.equal(five.reduce((n, x) => n + x.tool, 0), 6, 'only the last 5 minutes');
});

test('realtime: GET with lanes=1, then the stream replaces the snapshot frame by frame; a 404 stream stops retrying', async () => {
  const calm = FX('realtime-calm');
  let streams = 0;
  const gw = gateway({
    '/v1/analytics/realtime': () => json(FX('realtime-active')),
    '/v1/analytics/realtime/stream': () => {
      streams++;
      if (streams > 1) return json({ error: { code: 'not_found' } }, 404);
      const text = 'retry: 2000\n\n: keepalive\n\nevent: realtime\ndata: ' + JSON.stringify(calm) + '\n\n';
      return new Response(sseBody([text.slice(0, 40), text.slice(40)]), { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
    }
  });
  const C = live(gw);
  await C.ops.realtime();
  assert.equal(gw.calls[0].url.searchParams.get('lanes'), '1');
  assert.equal(gw.calls[0].headers.Authorization, 'Bearer tok');
  assert.equal(C.ops.derive().failing.length, 1);
  C.ops.startStream();
  for (let i = 0; i < 50 && C.ops.run; i++) await new Promise((r) => setTimeout(r, 5));
  assert.equal(C.ops.run, null, 'stream loop ended after the 404');
  assert.equal(streams, 2);
  assert.equal(C.ops.stream.frames, 1);
  assert.equal(C.ops.derive().failing.length, 0, 'the frame replaced the snapshot');
  assert.equal(gw.calls.find((c) => c.url.pathname.endsWith('/stream')).url.searchParams.get('lanes'), '1');
});

test('sseFrames: split frames, ignore comments, keep the incomplete tail', () => {
  const got = [];
  const rest = H.sseFrames('event: realtime\ndata: {"a":1}\n\n: ping\n\nevent: realtime\r\ndata: {"a"', (n, p) => got.push([n, p]));
  assert.deepEqual(got, [['realtime', { a: 1 }]]);
  assert.equal(rest, 'event: realtime\ndata: {"a"');
});

test('session ops: exclude body, include, resume, locate, dismiss', async () => {
  const gw = gateway({
    'POST /v1/sessions/fx-s1/exclude': () => json(FX('exclude')),
    'DELETE /v1/sessions/fx-s2/exclude': () => json(FX('include')),
    'GET /v1/sessions/fx-s1/resume': () => json(FX('resume')),
    'GET /v1/sessions/fx-s1/source_location': () => json(FX('source-location')),
    'POST /v1/analytics/realtime/fx-rt-fail/dismiss': () => json(FX('dismiss'))
  });
  const C = live(gw);
  assert.equal((await C.ops.exclude('fx-s1', 'test')).excluded, true);
  assert.deepEqual(gw.calls[0].body, { reason: 'test' });
  assert.equal((await C.ops.include('fx-s2')).excluded, false);
  const r = await C.ops.resume('fx-s1');
  assert.match(r.commands[0].shell, /claude --resume fx-native-1/);
  assert.equal(H.RESUME_OFF[FX('resume-running').disabled_reason], '会话还在运行，结束后再继续');
  assert.equal((await C.ops.locate('fx-s1')).files.length, 2);
  await C.ops.dismiss('fx-rt-fail', 3600);
  assert.deepEqual(gw.calls.at(-1).body, { seconds: 3600 });
  await assert.rejects(C.ops.exclude('fx-missing'), (e) => e.status === 404 && C.unavailable(e));
});

test('tool calls: filters become the query; cursor pages; bad answers reject with the code', async () => {
  const gw = gateway({ '/v1/analytics/tool_calls': (u) => (u.searchParams.get('cursor') ? json(FX('tool-calls-p2')) : u.searchParams.get('status') === 'bogus' ? json({ error: { code: 'invalid_request' } }, 422) : json(FX('tool-calls-p1'))) });
  const C = live(gw);
  assert.deepEqual(H.toolCallsQuery({ name: 'Bash', status: 'failed', cursor: null, empty: '' }), { limit: 50, status: 'failed', name: 'Bash' });
  const p1 = await C.ops.toolCalls({ name: 'Bash' });
  assert.equal(p1.has_more, true);
  assert.equal(gw.calls[0].url.searchParams.get('name'), 'Bash');
  assert.equal(gw.calls[0].url.searchParams.get('status'), 'all');
  const p2 = await C.ops.toolCalls({ name: 'Bash', cursor: p1.next_cursor });
  assert.equal(gw.calls[1].url.searchParams.get('cursor'), 'fx-cursor-2');
  assert.equal(p2.has_more, false);
  await assert.rejects(C.ops.toolCalls({ status: 'bogus' }), (e) => e.status === 422 && e.code === 'invalid_request' && !C.unavailable(e));
});

test('export: CSV text with the bearer header, report sections and scope, share card options', async () => {
  const csv = fs.readFileSync(path.join(DIR, 'export-csv.csv'), 'utf8');
  const gw = gateway({
    '/v1/export/csv': () => new Response(csv, { status: 200, headers: { 'Content-Type': 'text/csv' } }),
    'POST /v1/export/report': () => json(FX('export-report')),
    'POST /v1/export/share_card': (u, init) => json(JSON.parse(init.body).save ? FX('export-snapshot-saved') : FX('export-share-card'))
  });
  const C = live(gw);
  assert.equal(await C.ops.csv('tool_calls', { from_ts: 1, limit: 500 }), csv);
  const cu = gw.calls[0];
  assert.equal(cu.url.searchParams.get('table'), 'tool_calls'); assert.equal(cu.url.searchParams.get('limit'), '500'); assert.equal(cu.headers.Authorization, 'Bearer tok');
  assert.deepEqual(H.reportSections(new Set(['ov', 'fric', 'recs'])), ['overview', 'metrics', 'friction', 'recommendations']);
  const rep = await C.ops.report(new Set(['ov', 'proj']), { range: 0, agents: null, projects: null });
  assert.match(rep.markdown, /合成样本/);
  assert.deepEqual(gw.calls[1].body, { sections: ['overview', 'metrics', 'projects'], scope: {}, format: 'markdown', save: false });
  const card = await C.ops.shareCard({ hideNumbers: true, theme: 'dark' });
  assert.equal(card.code, 'DIMV');
  assert.deepEqual(gw.calls[2].body, { hide_numbers: true, theme: 'dark', save: false });
  assert.equal((await C.ops.shareCard({ save: true })).snapshot_id, 'fx-snap-1');
  assert.equal(H.BLOCKED[FX('export-share-blocked').blocked_reason].slice(0, 7), '所选范围还没有');
  const down = gateway({ '/v1/export/csv': () => json({ error: { code: 'not_ready', message: '还没有数据' } }, 503) });
  await assert.rejects(live(down).ops.csv('tool_calls'), (e) => e.status === 503 && e.code === 'not_ready');
});

test('mock mode: ops calls reject without touching fetch', async () => {
  let n = 0;
  const C = OrbitLive.create({ mode: 'mock', fetch: () => { n++; }, win: {} });
  await assert.rejects(C.ops.realtime(), (e) => e.code === 'mock_mode');
  await assert.rejects(C.ops.csv('tool_calls'), (e) => e.code === 'mock_mode');
  C.ops.startStream();
  assert.equal(n, 0); assert.equal(C.ops.run, undefined);
});

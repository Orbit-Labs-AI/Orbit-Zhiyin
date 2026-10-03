// Unit tests for the recs section of the shared live adapter (OrbitLive recs: Cand -> RECS row, C.recs reads and writes).
// Responses come from the hand-written fixtures in ../fixtures/recs; nothing talks to a real gateway.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const OrbitLive = require('../orbit-live.js');

const FX = (name) => JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'fixtures', name + '.json'), 'utf8'));
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
function gateway(handler) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const u = new URL(url);
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ method: init.method || 'GET', path: u.pathname, query: u.searchParams, headers: init.headers || {}, body });
    return handler(u, init.method || 'GET', body);
  };
  return { fetch, calls };
}
const live = (gw) => OrbitLive.create({ mode: 'live', endpoint: 'http://gw.test', token: 'tok', fetch: gw.fetch, win: {} });

test('recs.row: Cand.ui becomes a RECS row; savings are ui.save shares, missing numbers stay null', () => {
  const [allow, handoff, rule] = FX('recs/recommendations').items;
  const r = OrbitLive.recs.row(allow);
  assert.equal(r.id, 'fxc-allow');
  assert.equal(r.rec_key, 'kb:fx-readonly-allow');
  assert.equal(r.live, true);
  assert.deepEqual([r.dim, r.type, r.lvl, r.aud, r.primary], ['hook', 'Hook', 1, 0, '预览并安装']);
  assert.deepEqual(r.file[1], ['  "permissions": { "allow": ["Bash(git status:*)"] }', '+']);
  assert.deepEqual(r.track[0], ['每周审批次数', null, null, '次']);
  // approvals only wait: 1.1 % of the active time × .9, no token share
  assert.deepEqual([r.x.pct.t, r.x.pct.k, r.x.pct.st, r.x.pct.sk, r.x.pct.p, r.x.pct.key], [0.99, 0, 1.1, 0, 0.9, 'permission_friction']);
  assert.equal(r.gain, '省时 1.0% · 省 token 0%');
  assert.deepEqual([r.x.tokp, r.x.tok], [0, null]);
  assert.deepEqual(r.x.n, [12, 12]);
  assert.deepEqual([OrbitLive.recs.row(handoff).x.pct.t, OrbitLive.recs.row(handoff).x.pct.k], [0.6, 3.1]);
  assert.equal(OrbitLive.recs.row(rule).x.pct, null);   // 未估算
  // an older run still carrying hours (min_month) gives no share rather than a made-up one
  assert.equal(OrbitLive.recs.pct({ ui: { save: { min_month: 132, label: '≈ 2.2 h' } } }), null);
  assert.equal(OrbitLive.recs.pct({ score: { benefit: .42 } }), null);
});

test('recs.desc / resource: A7 asks for 50, the top surfaces for their slate size, all with the scope', async () => {
  const gw = gateway((u) => json(FX('recs/recommendations')));
  const C = live(gw);
  assert.deepEqual(C.recs.desc('A7').query, { surface: 'A7', limit: 50 });
  assert.deepEqual(C.recs.desc('menubar').query, { surface: 'menubar', limit: 1 });
  const r = C.recs.resource('A1', { range: 0, agents: null, projects: [] });
  await C.load(r);
  assert.equal(r.state, 'ready');
  assert.equal(r.data.items.length, 3);
  const q = gw.calls[0].query;
  assert.deepEqual([q.get('surface'), q.get('limit'), q.get('project_ids'), q.get('wait_ms')], ['A1', '3', '', '800']);
});

test('recs: 202 computing, then 404 / 503 are errors the page can degrade on', async () => {
  let mode = 'computing';
  const gw = gateway(() => mode === 'computing' ? json(FX('recs/recommendations-computing'), 202) : mode === 'missing' ? json({ error: { code: 'not_found' } }, 404) : json(FX('error-503'), 503));
  const C = live(gw);
  const r = C.recs.resource('A7', null);
  await C.load(r);
  assert.equal(r.state, 'computing');
  mode = 'missing'; C.recs.invalidate(); await C.load(r);
  assert.deepEqual([r.state, r.error.status], ['error', 404]);
  mode = 'down'; C.recs.invalidate(); await C.load(r);
  assert.deepEqual([r.state, r.error.status], ['error', 503]);
});

test('recs writes: exposure, batched views sent once per surface, labels with undo, recompute with the scope as JSON', async () => {
  const gw = gateway((u, method) => {
    if (u.pathname === '/v1/recommendations/exposures') return json(FX('recs/exposures'));
    if (/\/exposure$/.test(u.pathname)) return json(FX('recs/exposure'));
    if (u.pathname === '/v1/labels') return json(FX('recs/label'));
    if (u.pathname.startsWith('/v1/labels/') && method === 'DELETE') return json(FX('recs/label-undo'));
    if (u.pathname === '/v1/recommendations/recompute') return json(FX('recs/recompute'));
    return json({ error: { code: 'not_found' } }, 404);
  });
  const C = live(gw);
  C.status = FX('status');
  await C.recs.exposure('fxc-allow', 'A7', 'open', 0);
  assert.deepEqual(gw.calls[0], Object.assign({}, gw.calls[0], { method: 'POST', path: '/v1/recommendations/fxc-allow/exposure' }));
  assert.deepEqual(gw.calls[0].body, { surface: 'A7', action: 'open', position: 0 });
  assert.equal(gw.calls[0].headers['Content-Type'], 'application/json');
  assert.equal(gw.calls[0].headers.Authorization, 'Bearer tok');
  await C.recs.viewed('A1', ['fxc-handoff', 'fxc-allow']);
  assert.equal(await C.recs.viewed('A1', ['fxc-allow', 'fxc-handoff']), null);   // already reported: nothing sent
  await C.recs.viewed('lite', ['fxc-allow']);
  const views = gw.calls.filter((c) => c.path === '/v1/recommendations/exposures');
  assert.equal(views.length, 2);
  assert.deepEqual(views[0].body, { surface: 'A1', items: [{ candidate_id: 'fxc-handoff', position: 0, action: 'view' }, { candidate_id: 'fxc-allow', position: 1, action: 'view' }] });
  const lab = await C.recs.label('fxc-allow', 'not_applicable', 'has_equivalent');
  assert.equal(lab.data.label_id, 'fx-label-1');
  assert.deepEqual(gw.calls.at(-1).body, { target_kind: 'candidate', target_id: 'fxc-allow', label: 'not_applicable', reason: 'has_equivalent' });
  await C.recs.label('fxc-rule', 'snooze');
  assert.deepEqual(gw.calls.at(-1).body, { target_kind: 'candidate', target_id: 'fxc-rule', label: 'snooze' });
  await C.recs.unlabel('fx-label-1');
  assert.deepEqual([gw.calls.at(-1).method, gw.calls.at(-1).path], ['DELETE', '/v1/labels/fx-label-1']);
  const rc = await C.recs.recompute({ range: 0, agents: ['cc'], projects: [] }, true);
  assert.equal(rc.data.run_id, 'fx-run-2');
  assert.deepEqual(gw.calls.at(-1).body, { scope: { source_ids: ['src-claude'], project_ids: [] }, force: true });
});

test('recs writes: an error keeps its status and code; a failed view batch can be retried', async () => {
  let fail = true;
  const gw = gateway(() => fail ? json({ error: { code: 'no_projection', message: 'No published data', retryable: true } }, 409) : json(FX('recs/exposures')));
  const C = live(gw);
  await assert.rejects(C.recs.recompute(null, false), (e) => e.status === 409 && e.code === 'no_projection');
  await assert.rejects(C.recs.viewed('A7', ['fxc-allow']));
  fail = false;
  assert.equal((await C.recs.viewed('A7', ['fxc-allow'])).status, 200);
});

test('recs: relations need two ids; mock mode never sends', async () => {
  const gw = gateway((u) => json(FX('recs/relations')));
  const C = live(gw);
  assert.deepEqual((await C.recs.relations(['a'])).data, { pairs: [] });
  assert.equal(gw.calls.length, 0);
  const res = await C.recs.relations(['fxc-allow', 'fxc-handoff', 'fxc-allow']);
  assert.equal(res.data.pairs[0].relation, 'complements');
  assert.deepEqual(gw.calls[0].query.getAll('candidate_id'), ['fxc-allow', 'fxc-handoff']);
  const M = OrbitLive.create({ mode: 'mock', fetch: gw.fetch, win: {} });
  await assert.rejects(M.recs.label('x', 'mute'), (e) => e.code === 'mock_mode');
  assert.equal(gw.calls.length, 1);
});

// Unit tests for the library-install section of the shared live adapter (C.li in prototypes/shared/tandem-live.js).
// Responses come from the synthetic fixtures in ../fixtures/library-install; nothing talks to a real gateway.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const TandemLive = require('../tandem-live.js');

const FX = (name) => JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'fixtures', 'library-install', name + '.json'), 'utf8'));
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
function gateway(routes) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const u = new URL(url);
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ method: init.method || 'GET', path: u.pathname, search: u.search, body, headers: init.headers || {} });
    const h = routes[(init.method || 'GET') + ' ' + decodeURIComponent(u.pathname)];
    if (!h) return json({ error: { code: 'not_found', message: u.pathname } }, 404);
    return h(u, body, calls.filter((c) => c.method === (init.method || 'GET') && c.path === u.pathname).length);
  };
  return { fetch, calls };
}
const live = (gw) => TandemLive.create({ mode: 'live', endpoint: 'http://gw.test', token: 'tok', fetch: gw.fetch, win: {} });
const H = TandemLive.create({ mode: 'mock', win: {} }).li.helpers;

test('list requests: tabs map to sort / origin, kinds repeat, search uses /v1/catalog/search, cursor pages', () => {
  assert.deepEqual(H.liListRequest({ tab: 'hot', kind: '全部' }), { path: '/v1/catalog/items', query: { sort: 'installs', order: 'desc', limit: 30 } });
  assert.deepEqual(H.liListRequest({ tab: 'local' }).query, { sort: 'updated', order: 'desc', limit: 30, origin: 'local' });
  assert.equal(H.liListRequest({ tab: 'for', kind: '插件' }).path, '/v1/catalog/items?kind=plugin&kind=marketplace');
  assert.equal(H.liListRequest({ tab: 'for', cursor: 'c2' }).query.cursor, 'c2');
  assert.deepEqual(H.liListRequest({ tab: 'hot', kind: 'MCP', q: '  doc ' }), { path: '/v1/catalog/search?kind=mcp_server', query: { q: 'doc', limit: 30 } });
  assert.deepEqual(H.liFacetsRequest({ tab: 'local' }), { path: '/v1/catalog/facets', query: { origin: 'local' } });
  assert.equal(H.liItemPath('fx:hook/retry guard'), '/v1/catalog/items/fx%3Ahook/retry%20guard');
});

test('degraded: offline, missing route, not implemented and 503 fall back to demo data; 409 / 422 do not', () => {
  for (const s of [0, 404, 501, 503]) assert.equal(H.liDegraded({ status: s }), true, String(s));
  for (const s of [409, 422, 500]) assert.equal(H.liDegraded({ status: s }), false, String(s));
  assert.equal(H.liDegraded({ code: 'mock_mode' }), true);
});

test('preview rows: targets keep diff lines {n, op, text, gap}, units and disabled state; selection only lists narrowed units', () => {
  const t = H.liTargets(FX('install-preview-narrowed'));
  assert.equal(t.length, 2);
  assert.deepEqual(t[0].lines.map((l) => l.op), [' ', ' ', '+', '-', 'ai', ' ', ' ']);
  assert.equal(t[0].lines[5].gap, true);
  assert.equal(t[0].units[0].id, 'u1');
  assert.equal(t[1].disabled, true);
  assert.deepEqual(H.liSelection({ disabled: new Set([1]) }), { disabled_targets: [1] });
  assert.deepEqual(H.liSelection({ disabled: [], units: { 0: new Set(['u1']) } }), { disabled_targets: [], selected_units: { 0: ['u1'] } });
});

test('catalog reads and writes go to /v1/catalog with the token; FastAPI string details become error codes', async () => {
  const gw = gateway({
    'GET /v1/catalog/items': (u) => json(u.searchParams.get('cursor') ? FX('catalog-items-page2') : FX('catalog-items')),
    'GET /v1/catalog/facets': () => json(FX('catalog-facets')),
    'GET /v1/catalog/items/fx:hook/retry-guard': () => json(FX('catalog-item')),
    'GET /v1/catalog/items/fx:missing': () => json({ detail: 'catalog_item_not_found' }, 404),
    'DELETE /v1/catalog/local/local:abc': () => new Response(null, { status: 204 })
  });
  const C = live(gw);
  const first = await C.li.items({ tab: 'for' });
  assert.equal(first.items.length, 4);
  const second = await C.li.items({ tab: 'for', cursor: first.next_cursor });
  assert.equal(second.items[0].name, 'deploy-kit');
  assert.match(gw.calls[1].search, /cursor=fx-cursor-2/);
  assert.equal((await C.li.facets({})).kind[0].value, 'skill');
  const d = await C.li.item('fx:hook/retry-guard');
  assert.equal(d.versions.length, 2);
  assert.equal(d.permissions.level, 2);
  await assert.rejects(C.li.item('fx:missing'), (e) => e.status === 404 && e.code === 'catalog_item_not_found' && C.li.degraded(e));
  assert.equal(await C.li.removeLocal('local:abc'), true);
  assert.ok(gw.calls.every((c) => c.headers.Authorization === 'Bearer tok'));
});

test('prepare: environment narrows agents, needs_fetch re-plans with fetch:true (no /v1/install/fetch, J02), preview follows with the default selection', async () => {
  const gw = gateway({
    'GET /v1/install/environment': () => json(FX('install-environment')),
    'POST /v1/install/plans': (u, body, n) => json(n === 1 ? FX('install-plan-needs-fetch') : FX('install-plan'), 201),
    'POST /v1/install/fetch': () => json(FX('install-fetch')),
    'POST /v1/install/plans/plan-fx-1/preview': () => json(FX('install-preview-narrowed'))
  });
  const C = live(gw);
  const r = await C.li.prepare({ type: 'catalog', id: 'fx:hook/retry-guard' }, { itemAgents: ['claude_code', 'codex', 'gemini'], defaultOff: (plan) => plan.targets.filter((t) => t.agent !== plan.agents[0]).map((t) => t.idx) });
  const plans = gw.calls.filter((c) => c.path === '/v1/install/plans');
  assert.deepEqual(plans[0].body, { source: { type: 'catalog', id: 'fx:hook/retry-guard' }, scope: 'user', agents: ['claude_code', 'codex'] });
  assert.equal(plans[1].body.fetch, true);
  assert.deepEqual(plans[1].body, Object.assign({}, plans[0].body, { fetch: true }));
  assert.equal(gw.calls.filter((c) => c.path === '/v1/install/fetch').length, 0);
  assert.deepEqual(gw.calls.at(-1).body, { disabled_targets: [1] });
  assert.equal(r.preview.preview_digest, 'sha256:fx-digest-b');
});

test('prepare: an unchanged selection uses GET preview; link_only plans resolve without a preview', async () => {
  const gw = gateway({
    'GET /v1/install/environment': () => json({ error: { code: 'not_found' } }, 404),
    'POST /v1/install/plans': (u, body, n) => json(n === 1 ? FX('install-plan') : Object.assign(FX('install-plan'), { status: 'link_only', links: ['https://example.invalid/x'] }), 201),
    'GET /v1/install/plans/plan-fx-1/preview': () => json(FX('install-preview'))
  });
  const C = live(gw);
  const a = await C.li.prepare({ type: 'catalog', id: 'fx:hook/retry-guard' });
  assert.equal(a.preview.preview_digest, 'sha256:fx-digest-a');
  assert.equal(gw.calls[1].body.agents, undefined);   // no environment: backend defaults
  const b = await C.li.prepare({ type: 'catalog', id: 'x' });
  assert.equal(b.preview, null);
  assert.deepEqual(b.plan.links, ['https://example.invalid/x']);
  assert.equal(b.reason, '该资源只能按来源说明手动安装');
});

test('apply: sends the confirmed digest and selection; 409 preview_stale re-previews instead of writing', async () => {
  let stale = true;
  const gw = gateway({
    'POST /v1/install/apply': () => stale ? json(FX('install-apply-stale'), 409) : json(FX('install-apply')),
    'POST /v1/install/plans/plan-fx-1/preview': () => json(FX('install-preview-refreshed')),
    'POST /v1/install/inst-fx-1/revert': () => json(FX('install-revert'))
  });
  const C = live(gw);
  const st = { plan: FX('install-plan'), preview: FX('install-preview-narrowed'), sel: { disabled: new Set([1]) }, overrideRisk: false };
  const r1 = await C.li.apply(st);
  assert.equal(r1.stale, true);
  assert.equal(r1.preview.preview_digest, 'sha256:fx-digest-c');
  assert.deepEqual(gw.calls[0].body, { plan_id: 'plan-fx-1', preview_digest: 'sha256:fx-digest-b', disabled_targets: [1] });
  stale = false; st.preview = r1.preview;
  const r2 = await C.li.apply(st);
  assert.equal(r2.result.install_id, 'inst-fx-1');
  assert.equal(gw.calls.at(-1).body.preview_digest, 'sha256:fx-digest-c');
  assert.equal((await C.li.revert('inst-fx-1')).state, 'reverted');
});

test('send: offline becomes status 0 (degraded); other errors keep code and detail', async () => {
  const C = live({ fetch: async () => { throw new TypeError('Failed to fetch'); } });
  await assert.rejects(C.li.state(), (e) => e.status === 0 && e.code === 'offline' && C.li.degraded(e));
  const C2 = live(gateway({ 'POST /v1/install/apply': () => json({ error: { code: 'risk_blocked', message: '风险过高', detail: { level: 'dangerous' } } }, 403) }));
  await assert.rejects(C2.li.apply({ plan: { plan_id: 'p' }, preview: { preview_digest: 'd' }, sel: {} }), (e) => e.status === 403 && e.code === 'risk_blocked' && e.detail.level === 'dangerous' && !C2.li.degraded(e));
  const M = TandemLive.create({ mode: 'mock', win: {} });
  await assert.rejects(M.li.items({}), (e) => e.code === 'mock_mode');
});

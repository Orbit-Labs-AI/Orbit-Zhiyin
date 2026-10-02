// Live data adapter (prototypes/shared/tandem-live.js, src/js/06-live-client.js + 96-live-bind.js, and the @tandem-live block
// in the Lite HTML). The gateway is simulated with page.route on http://tandem.test: /app and /lite serve the built pages,
// /v1/* answers with the hand-written fixtures in prototypes/shared/fixtures, /v1/events with SSE frames from a queue.
//  1. mock          file:// pages stay in mock mode: no requests, no adapter markup on any page, no console errors
//  2. live Advance  import progress, overview counts, sessions + events, tools, projects, sidebar and settings › 数据源 all come
//                   from fixtures; missing values show「—」not 0; unbound pages carry 示例数据
//  3. outage        503 + Retry-After keeps the previous screen and shows the banner; service degraded shows too
//  4. restart       a tandem:endpoint event moves to the new gateway (new token) and re-renders from it
//  5. live Lite     same bindings in the single-file Lite page
//  6. Lite edition  Advance's Lite pages: l-home / l-sessions reuse the bound pages, l-recs is bound, l-persona shows 示例数据
//  7. recs          A7 / A1 / Lite / menubar read /v1/recommendations (fixtures/recs); exposure, labels with undo, recompute;
//                   404 / 503 before any live data show A7's honest empty state (recommendations are personal data)
import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const ADV_FILE = path.join(ROOT, 'advance', 'tandem-demo.html');
const LITE_FILE = path.join(ROOT, 'lite', 'tandem-benchmark-demo.html');
const FX = (name) => JSON.parse(fs.readFileSync(path.join(ROOT, 'shared', 'fixtures', name + '.json'), 'utf8'));
const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const sseText = (frames) => frames.map((f) => 'id: ' + f.id + '\nevent: ' + f.event + '\ndata: ' + JSON.stringify(f.data) + '\n\n').join('');

function collectErrors(page, allow) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const url = m.location().url || '';
    if (/fonts\.(googleapis|gstatic)\.com/.test(url)) return;
    if (allow && allow(m.text(), url)) return;
    // v0.0.1 optional routes this fixture gateway does not serve (first-run state, native popover, A1 uiview): the page
    // degrades on 404 by design; their own flows are covered in live-s6 / live-s7 / live-s8 and live-core
    if (/status of 404/.test(m.text()) && /^http:\/\/tandem\.test\/v1\/(app\/state|shell\/popover|uiview\/overview)(\?|$)/.test(url)) return;
    errors.push(m.text());
  });
  return errors;
}

// realtime fixtures carry absolute timestamps: move them so generated_at is now (lanes / since stay relative)
function rtNow(name) {
  const o = FX('ops/' + name); const dt = Date.now() - o.generated_at;
  const mv = (x) => (typeof x === 'number' ? x + dt : x);
  o.generated_at += dt;
  o.sessions.forEach((s) => { s.since = mv(s.since); if (s.lanes) Object.keys(s.lanes).forEach((k) => { s.lanes[k] = s.lanes[k].map(mv); }); });
  return o;
}
// Fixture gateway. state.queue holds the frame lists for the next /v1/events connections (an empty stream once drained).
async function gateway(page) {
  const state = { down: false, queue: [], seen: [] };
  const ev = FX('events').frames;
  state.queue.push([ev[0], ev[1]]);   // first connection: gateway ok + import job running
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.route(/^http:\/\/tandem2?\.test\//, async (route) => {
    const u = new URL(route.request().url());
    const second = u.host === 'tandem2.test';
    state.seen.push({ host: u.host, path: u.pathname, auth: route.request().headers().authorization || null });
    const json = (body, status = 200, headers = {}) => route.fulfill({ status, contentType: 'application/json', headers, body: JSON.stringify(body) });
    if (u.pathname === '/app') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fs.readFileSync(ADV_FILE, 'utf8') });
    if (u.pathname === '/lite') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fs.readFileSync(LITE_FILE, 'utf8') });
    if (u.pathname === '/v1/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseText(state.queue.shift() || []) });
    // ops (98-live-ops.js) reads the realtime snapshot and its stream on every live page; the full flow is in live-ops.spec.mjs
    if (u.pathname === '/v1/analytics/realtime/stream') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: realtime\ndata: ' + JSON.stringify(rtNow('realtime-calm')) + '\n\n' });
    if (state.down && u.pathname.startsWith('/v1/analytics/')) return json(FX('error-503'), 503, { 'Retry-After': '2' });
    const bump = (o) => { if (second) { o = JSON.parse(JSON.stringify(o)); if (o.counts) o.counts.sessions = 256; if (o.overview) o.overview.counts.sessions = 256; } return o; };
    const routes = {
      '/v1/status': () => bump(FX('status')),
      '/v1/analytics/overview': () => bump(FX('overview')),
      '/v1/analytics/sessions': () => FX('sessions'),
      '/v1/sessions/fx-s1/events': () => FX('session-events'),
      '/v1/analytics/tools': () => FX('tools'),
      '/v1/analytics/projects': () => FX('projects'),
      '/v1/app/sources': () => FX('app-sources'),
      '/v1/app/settings': () => FX('app-settings'),
      // library-install: the full flow is covered in live-library-install.spec.mjs
      '/v1/catalog/items': () => FX('library-install/catalog-items'),
      '/v1/catalog/facets': () => FX('library-install/catalog-facets'),
      '/v1/install/state': () => FX('library-install/install-state'),
      // studio-settings (97-live-studio-settings.js) reads these on every live page: notify policy, snooze, attention, collection
      '/v1/platform/collection': () => FX('studio-settings/collection'),
      '/v1/notifications/policy': () => FX('studio-settings/notify-policy'),
      '/v1/notifications/snooze': () => FX('studio-settings/notify-snooze'),
      '/v1/notifications/attention': () => FX('studio-settings/notify-attention'),
      '/v1/analytics/realtime': () => rtNow('realtime-calm'),
      '/v1/sessions/excluded': () => FX('ops/excluded'),
      // slice 0 spine (90-live-core.js): every live page hydrates from facts; see live-core.spec.mjs
      '/v1/uiview/facts': () => FX('core/facts'),
      '/v1/app/discovery': () => FX('core/discovery'),
      '/v1/install/environment': () => FX('core/install-environment')
    };
    const rec = recsRoute(u, route.request(), state); if (rec) return json(rec.body, rec.status || 200);
    if (routes[u.pathname]) return json(routes[u.pathname]());
    return json({ error: { code: 'not_found', message: u.pathname, retryable: false } }, 404);
  });
  return state;
}

test('mock mode: file:// Lite and Advance make no requests and add no adapter markup on any page', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  const requests = [];
  page.on('request', (r) => { if (!/^(file|data|blob):/.test(r.url()) && !/fonts\.(googleapis|gstatic)\.com/.test(r.url())) requests.push(r.url()); });
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  for (const file of [ADV_FILE, LITE_FILE]) {
    await page.goto('file://' + file);
    await expect(page.locator('#main')).not.toBeEmpty();
    expect(await page.evaluate(() => TL.mode)).toBe('mock');
    for (const r of await page.evaluate(() => ROUTES.map((x) => x[0]))) {
      await page.evaluate((id) => go(id), r);
      await expect.poll(() => page.evaluate(() => S.route)).toBe(r);
      expect(await page.locator('[data-tl], #tl-style').count(), r).toBe(0);
    }
  }
  expect(requests).toEqual([]);
  expect(errors).toEqual([]);
});

// superseded by slice 0: the plain TL_PAGES renderers are gone (polished pages on the facts spine, live-core.spec.mjs)
test.skip('live Advance: progress, overview, sessions, tools, projects, sidebar and sources render from fixtures', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  const gw = await gateway(page);
  await page.goto('http://tandem.test/app#token=fx-token');
  expect(await page.evaluate(() => [TL.mode, location.hash])).toEqual(['live', '']);
  const ov = page.locator('[data-tl="overview"]');
  await expect(ov).toContainText('128');
  await expect(ov).toContainText('1,874');
  await expect(ov.locator('.tl-kpi').filter({ hasText: 'Token' }).locator('b')).toHaveText('—');
  await expect(ov.locator('.tl-kpi').filter({ hasText: '费用' }).locator('b')).toHaveText('—');
  await expect(page.locator('.tl-progress')).toContainText('40 / 128');
  expect(gw.seen.filter((s) => s.path.startsWith('/v1/')).every((s) => s.auth === 'Bearer fx-token')).toBe(true);
  // sidebar: counts and agents from /v1/status; a disabled source shows 停用, an agent without a source shows —
  await expect(page.locator('#side [data-r="sessions"] .ct')).toHaveText('128');
  await expect(page.locator('#side .ag[data-a="cc"] .ct')).toHaveText('96');
  await expect(page.locator('#side .ag[data-a="gm"] .ct')).toHaveText('停用');
  await expect(page.locator('#side .ag[data-a="ds"] .ct')).toHaveText('—');
  // sessions + events
  await page.evaluate(() => go('sessions'));
  const rows = page.locator('[data-tl="sessions"] tbody tr');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(1)).toContainText('—');
  await rows.first().click();
  await expect(page.locator('[data-tl="events"] .tl-ev')).toHaveCount(3);
  await expect(page.locator('[data-tl="events"]')).toContainText('Bash · pnpm check');
  // tools, projects
  await page.evaluate(() => go('tools'));
  await expect(page.locator('[data-tl="tools"]')).toContainText('2,810');
  await expect(page.locator('[data-tl="tools"]')).toContainText('6.0%');
  await page.evaluate(() => go('projects'));
  await expect(page.locator('[data-tl="projects"]')).toContainText('tandem-fixture');
  // unbound page: 示例数据
  await page.evaluate(() => go('persona'));
  await expect(page.locator('#content [data-tl="sample"]')).toHaveText('示例数据');
  // settings › 数据源
  await page.evaluate(() => openSettings('sources'));
  await expect(page.locator('#set [data-tl="sources"] .srcrow')).toHaveCount(3);
  await expect(page.locator('#set [data-tl="sources"]')).toContainText('已停用');
  expect(errors).toEqual([]);
});

// superseded by slice 0: the plain TL_PAGES renderers are gone (polished pages on the facts spine, live-core.spec.mjs)
test.skip('live Advance in the Lite edition: l-home and l-sessions use the bound pages, the rest carry 示例数据', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  await gateway(page);
  await page.goto('http://tandem.test/app#token=fx-token');
  await expect(page.locator('[data-tl="overview"]')).toContainText('128');
  await page.evaluate(() => edSet('lite'));
  await expect.poll(() => page.evaluate(() => [S.ed, S.route])).toEqual(['lite', 'l-home']);
  await expect(page.locator('#content [data-tl="overview"]')).toContainText('1,874');
  await expect(page.locator('#content [data-tl="sample"]')).toHaveCount(0);
  await expect(page.locator('#side [data-r="l-sessions"] .ct')).toHaveText('128');
  await page.evaluate(() => go('l-sessions'));
  const rows = page.locator('[data-tl="sessions"] tbody tr');
  await expect(rows).toHaveCount(2);
  await rows.first().click();
  await expect(page.locator('[data-tl="events"] .tl-ev')).toHaveCount(3);
  await page.evaluate(() => go('l-persona'));
  await expect(page.locator('#content [data-tl="sample"]')).toHaveText('示例数据');
  await page.evaluate(() => go('l-recs'));   // bound by 97-live-recs.js
  await expect(page.locator('#content .l-rc').first()).toContainText('长会话交接摘要');
  await expect(page.locator('#content [data-tl="sample"]')).toHaveCount(0);
  // back to Advance: the mapped route keeps its live page
  await page.evaluate(() => edSet('advance'));
  await expect.poll(() => page.evaluate(() => [S.ed, S.route])).toEqual(['advance', 'recs']);
  await page.evaluate(() => go('sessions'));
  await expect(page.locator('[data-tl="sessions"] tbody tr')).toHaveCount(2);
  expect(errors).toEqual([]);
});

// superseded by slice 0: the plain TL_PAGES renderers are gone (polished pages on the facts spine, live-core.spec.mjs)
test.skip('live outage: 503 + Retry-After keeps the previous screen with a banner; gateway restart reconnects via tandem:endpoint', async ({ page }) => {
  ONLY('mac-14');
  // the browser logs the deliberate 503 responses as resource errors; nothing else may fail
  const errors = collectErrors(page, (text, url) => /status of 503/.test(text) && /^http:\/\/tandem\.test\/v1\/analytics\//.test(url));
  const gw = await gateway(page);
  await page.addInitScript(() => { window.__TANDEM_TOKEN__ = 'fx-token'; });
  await page.goto('http://tandem.test/app');
  await expect(page.locator('[data-tl="overview"]')).toContainText('1,874');
  gw.down = true;
  const ev = FX('events').frames;
  gw.queue.push([{ id: '3', event: 'service', data: { name: 'analysis', state: 'degraded' } }, Object.assign({}, ev[2], { id: '4' })]);
  await expect(page.locator('[data-tl="unavailable"]')).toContainText('服务暂时不可用');
  await expect(page.locator('[data-tl="overview"]')).toContainText('1,874');     // previous screen kept, not demo data
  await expect(page.locator('#content [data-tl="error"]')).toContainText('刷新失败');
  // gateway restarted elsewhere with a new token
  gw.down = false;
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('tandem:endpoint', { detail: { endpoint: 'http://tandem2.test', token: 'fx-token-2' } })));
  await expect(page.locator('[data-tl="overview"] .tl-kpi').first().locator('b')).toHaveText('256');
  await expect(page.locator('#side [data-r="sessions"] .ct')).toHaveText('256');
  expect(gw.seen.some((s) => s.host === 'tandem2.test' && s.path === '/v1/events' && s.auth === 'Bearer fx-token-2')).toBe(true);
  expect(gw.seen.filter((s) => s.host === 'tandem2.test').every((s) => s.auth === 'Bearer fx-token-2')).toBe(true);
  expect(errors).toEqual([]);
});

test('live Lite: the same bindings render overview, sessions, tools, projects, sidebar and sources from fixtures', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  const gw = await gateway(page);
  await page.goto('http://tandem.test/lite#token=fx-token');
  expect(await page.evaluate(() => TL.mode)).toBe('live');
  const ov = page.locator('[data-tl="overview"]');
  await expect(ov).toContainText('1,874');
  await expect(ov.locator('.tl-kpi').filter({ hasText: '模型请求' }).locator('b')).toHaveText('—');
  await expect(page.locator('.tl-progress')).toContainText('正在导入');
  await expect(page.locator('#side [data-id="sessions"] .ct')).toHaveText('128');
  await expect(page.locator('#side .ag[data-id="cx"] .ct')).toHaveText('32');
  await page.evaluate(() => go('sessions'));
  await page.locator('[data-tl="sessions"] tbody tr').first().click();
  await expect(page.locator('[data-tl="events"] .tl-ev')).toHaveCount(3);
  await page.evaluate(() => go('tools'));
  await expect(page.locator('[data-tl="tools"]')).toContainText('mcp__figma__get');
  await page.evaluate(() => go('projects'));
  await expect(page.locator('[data-tl="projects"]')).toContainText('notes-fixture');
  await page.evaluate(() => go('library'));
  await expect(page.locator('[data-tl="library"] .lib-feature')).toHaveCount(3);
  await expect(page.locator('#content [data-tl="sample"]')).toHaveCount(0);
  await page.evaluate(() => ACT.settings());
  await expect(page.locator('#modal [data-tl="sources"]')).toContainText('Gemini CLI');
  expect(gw.seen.filter((s) => s.path.startsWith('/v1/')).every((s) => s.auth === 'Bearer fx-token')).toBe(true);
  expect(errors).toEqual([]);
});

/* ---------- recommendations (97-live-recs.js, TandemLive recs section) ---------- */
// state.rec: {mode: 'ok' | 'missing' | 'down' | 'computing', hidden: candidate ids labelled away, posts: [{method, path, body}]}.
// The top surfaces answer a different order from A7 (handoff first) so the stable slate is visible on A1 / Lite / menubar.
const RFX = (name) => FX('recs/' + name);
function recsRoute(u, req, state) {
  const R = state.rec || (state.rec = { mode: 'ok', hidden: new Set(), posts: [] });
  const p = u.pathname;
  if (!p.startsWith('/v1/recommendations') && !p.startsWith('/v1/labels')) return null;
  if (R.mode === 'missing') return null;
  if (R.mode === 'down') return { status: 503, body: FX('error-503') };
  const method = req.method();
  if (method !== 'GET') { let body = null; try { body = JSON.parse(req.postData() || 'null'); } catch (e) { body = null; } R.posts.push({ method, path: p, body }); }
  if (p === '/v1/recommendations') {
    if (R.mode === 'computing') return { status: 202, body: RFX('recommendations-computing') };
    const all = RFX('recommendations'); const items = all.items.filter((c) => !R.hidden.has(c.candidate_id));
    const sf = u.searchParams.get('surface');
    const top = ['fxc-handoff', 'fxc-allow', 'fxc-rule'].map((id) => items.find((c) => c.candidate_id === id)).filter(Boolean);
    all.items = sf === 'A7' ? items : top.slice(0, Number(u.searchParams.get('limit')) || 3);
    return { body: all };
  }
  if (p === '/v1/recommendations/relations') return { body: RFX('relations') };
  if (p === '/v1/recommendations/exposures') return { body: RFX('exposures') };
  if (p === '/v1/recommendations/recompute') return { body: RFX('recompute') };
  if (/\/exposure$/.test(p)) return { body: RFX('exposure') };
  if (p === '/v1/labels' && method === 'POST') { R.hidden.add(R.posts[R.posts.length - 1].body.target_id); return { body: RFX('label') }; }
  if (p.startsWith('/v1/labels/') && method === 'DELETE') { R.hidden.clear(); return { body: RFX('label-undo') }; }
  if (/^\/v1\/recommendations\/[^/]+$/.test(p)) return { body: RFX('recommendation-detail') };
  return null;
}

test('live recs: A7 from fixtures, exposure, 不适用 with reason and 8-second undo, recompute; A1 / menubar take the top slate', async ({ page }) => {
  ONLY('mac-14');
  test.setTimeout(60_000);
  const errors = collectErrors(page);
  const gw = await gateway(page);
  gw.rec = { mode: 'ok', hidden: new Set(), posts: [] };
  await page.goto('http://tandem.test/app#token=fx-token');
  // A1: the overview's own 本周建议 card (no appended block) lists the backend's A1 slate first
  await expect(page.locator('#content [data-tl="recs-a1"]')).toHaveCount(0);
  const a1 = page.locator('#content .ov-recs');
  await expect(a1.locator('.ov-recn').first()).toHaveText('长会话交接摘要');
  await expect.poll(() => gw.rec.posts.some((x) => x.path === '/v1/recommendations/exposures' && x.body.surface === 'A1')).toBe(true);
  // A7: the demo renderer with fixture rows; save estimate from score.benefit, a missing one prints —
  await page.evaluate(() => go('recs'));
  const cards = page.locator('#content .rcard');
  await expect(cards).toHaveCount(3);
  await expect(page.locator('#content')).not.toContainText('PR 收尾');
  await expect(cards.filter({ hasText: '只读命令自动放行' }).locator('.rc-save b')).toHaveText('≈ 1.2 h');
  await expect(cards.filter({ hasText: '验收命令' }).locator('.rc-save b')).toHaveText('—');
  await expect(page.locator('#content [data-tl="sample"]')).toHaveCount(0);
  await expect.poll(() => gw.rec.posts.filter((x) => x.path === '/v1/recommendations/exposures' && x.body.surface === 'A7').flatMap((x) => x.body.items.map((i) => i.candidate_id)).sort()).toEqual(['fxc-allow', 'fxc-handoff', 'fxc-rule']);
  // open + detail + relations
  await cards.filter({ hasText: '长会话交接摘要' }).locator('.rc-title').click();
  await expect.poll(() => gw.rec.posts.some((x) => x.path === '/v1/recommendations/fxc-handoff/exposure' && x.body.action === 'open' && x.body.surface === 'A7')).toBe(true);
  await page.evaluate(() => ACT.recTab({ dataset: { v: 'why' } }));
  await expect(page.locator('#content [data-tl="rec-rel"]')).toContainText('只读命令自动放行');
  // 不适用: reason menu → label; undo within 8 s deletes the label and the card comes back
  await cards.filter({ hasText: '只读命令自动放行' }).locator('[data-act="dismissRec"]').click();
  await page.locator('#dd button', { hasText: '已有等价配置' }).click();
  await expect(cards).toHaveCount(2);
  await expect.poll(() => gw.rec.posts.find((x) => x.path === '/v1/labels')?.body).toEqual({ target_kind: 'candidate', target_id: 'fxc-allow', label: 'not_applicable', reason: 'has_equivalent' });
  await expect(page.locator('#toast')).toContainText('撤销');
  await page.locator('#toast [data-act="toastAct"]').click();
  await expect.poll(() => gw.rec.posts.some((x) => x.method === 'DELETE' && x.path === '/v1/labels/fx-label-1')).toBe(true);
  await expect(cards).toHaveCount(3);
  // snooze and mute are labels too
  await cards.filter({ hasText: '验收命令' }).locator('[data-act="dismissRec"]').click();
  await page.locator('#dd button', { hasText: '稍后再说' }).click();
  await expect.poll(() => gw.rec.posts.filter((x) => x.path === '/v1/labels').map((x) => x.body.label)).toEqual(['not_applicable', 'snooze']);
  // recompute
  await page.locator('#main [data-act="recalc"]').click();
  await expect.poll(() => gw.rec.posts.find((x) => x.path === '/v1/recommendations/recompute')?.body.force).toBe(true);
  await expect(page.locator('#toast')).toContainText('建议已按最新数据重算');
  // menubar: the menubar slate's one rec
  await page.evaluate(() => { S.attn.clear(); S.pop = true; render(); });
  await expect(page.locator('#pop [data-act="popRec"]')).toHaveAttribute('data-id', 'fxc-handoff');
  await expect.poll(() => gw.rec.posts.some((x) => x.path === '/v1/recommendations/exposures' && x.body.surface === 'menubar')).toBe(true);
  expect(errors).toEqual([]);
});

test('live recs in the Lite edition: l-home 本周最值得做的一件事 and l-recs use the lite slate', async ({ page }) => {
  ONLY('mac-14');
  test.setTimeout(60_000);
  const errors = collectErrors(page);
  const gw = await gateway(page);
  gw.rec = { mode: 'ok', hidden: new Set(), posts: [] };
  await page.goto('http://tandem.test/app#token=fx-token');
  await page.evaluate(() => edSet('lite'));
  // l-home's own 本周最值得做的一件事 card (no appended recs-lite block) takes the lite slate's first rec
  await expect(page.locator('#content [data-tl="recs-lite"]')).toHaveCount(0);
  await expect(page.locator('#content .l-one .rc-title')).toHaveText('长会话交接摘要');
  await page.evaluate(() => go('l-recs'));
  await expect(page.locator('#content .l-rc')).toHaveCount(3);
  await expect(page.locator('#content .l-rc').first()).toContainText('长会话交接摘要');
  await expect.poll(() => gw.rec.posts.some((x) => x.path === '/v1/recommendations/exposures' && x.body.surface === 'lite')).toBe(true);
  expect(errors).toEqual([]);
});

for (const mode of ['missing', 'down']) {
  // recommendations are personal data: a missing / down endpoint shows A7's honest empty state, never the demo rows
  test('live recs degrade: ' + mode + ' before any live data shows the honest empty state, no demo rows', async ({ page }) => {
    ONLY('mac-14');
    test.setTimeout(60_000);
    const errors = collectErrors(page, (text, url) => /status of (404|503)/.test(text) && /^http:\/\/tandem\.test\/v1\/recommendations/.test(url));
    const gw = await gateway(page);
    gw.rec = { mode, hidden: new Set(), posts: [] };
    await page.goto('http://tandem.test/app#token=fx-token');
    await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
    await expect(page.locator('#content [data-tl="recs-a1"]')).toHaveCount(0);
    await expect(page.locator('#content .ov-recs .ov-rec')).toHaveCount(0);
    await page.evaluate(() => go('recs'));
    await expect(page.locator('#content [data-tl="recs-empty"]')).toHaveAttribute('data-state', 'error');
    await expect(page.locator('#content [data-tl="recs-empty"]')).toContainText('建议服务暂时不可用');
    await expect(page.locator('#content [data-tl="sample"]')).toHaveCount(0);
    await expect(page.locator('#content .rcard')).toHaveCount(0);
    await expect(page.locator('#content')).not.toContainText('PR 收尾');
    expect(gw.rec.posts).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test('live Lite recs: 优化建议 reads the fixtures; 404 before any live data keeps the demo rows with 示例数据', async ({ page }) => {
  ONLY('mac-14');
  test.setTimeout(60_000);
  const errors = collectErrors(page, (text, url) => /status of 404/.test(text) && /^http:\/\/tandem\.test\/v1\/recommendations/.test(url));
  const gw = await gateway(page);
  gw.rec = { mode: 'ok', hidden: new Set(), posts: [] };
  await page.goto('http://tandem.test/lite#token=fx-token');
  await page.evaluate(() => go('recs'));
  await expect(page.locator('#content .rec-card')).toHaveCount(3);
  await expect(page.locator('#content')).toContainText('只读命令自动放行');
  await expect(page.locator('#content [data-tl="sample"]')).toHaveCount(0);
  await expect.poll(() => gw.rec.posts.some((x) => x.path === '/v1/recommendations/exposures' && x.body.surface === 'A7')).toBe(true);
  await page.locator('#content .rec-card').filter({ hasText: '长会话交接摘要' }).locator('[data-act="rec"]').click();
  await expect(page.locator('#recDetail')).toContainText('长会话交接摘要');
  await expect.poll(() => gw.rec.posts.some((x) => x.path === '/v1/recommendations/fxc-handoff/exposure' && x.body.action === 'open')).toBe(true);
  // a fresh page against a gateway without the endpoint keeps the demo rows
  gw.rec.mode = 'missing';
  await page.reload();
  await page.evaluate(() => go('recs'));
  await expect(page.locator('#content [data-tl="sample"]')).toHaveText('示例数据');
  await expect(page.locator('#content')).toContainText('先写完成条件');
  expect(errors).toEqual([]);
});

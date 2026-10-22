// Slice 0 (live core): /v1/uiview/facts hydrates the demo globals in place; every polished page renders on the real
// spine (full and empty) without plain tables; the strip reports connecting / computing / importing; the native bridge
// correlates request ids. Fixtures: prototypes/shared/fixtures/core (synthetic, real agent ids).
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NOW = new Date('2026-10-03T12:00:00+08:00');
const FACTS = fx('core/facts.json');
const AGENT_UI = { claude_code: 'cc', codex: 'cx', dsh: 'ds', pi: 'pi', kimi: 'km', hermes: 'hm', opencode: 'oc' };
const SLOT = { cc: 1, cx: 2, ds: 4, pi: 6, km: 7, hm: 8, oc: 9 };
const MOCK_MARKERS = /Confluo|latentskill|Gemini CLI|Copilot CLI/;

async function allRoutes(page) {
  return page.evaluate(() => ROUTES.map((r) => r[0]).concat(LITE_ROUTES.map((r) => r[0])));
}
async function visit(page, r) {
  const ed = /^l-/.test(r) ? 'lite' : 'advance';
  if (await page.evaluate(() => S.ed) !== ed) {
    await page.evaluate((e) => { go('overview'); edSet(e); }, ed);   // from a page Lite lacks, go() would switch straight back
    await expect.poll(() => page.evaluate(() => S.ed)).toBe(ed);
  }
  await page.evaluate((route) => go(route), r);
  await expect.poll(() => page.evaluate(() => S.route)).toBe(r);
}

test.beforeEach(async ({ page }) => { ONLY('mac-14'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

test('full spine: 7 real agents hydrate with fixed colors, counts and calendar; no mock rows or plain tables', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, 'core');
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  // the merged sidebar starts with the Agents group collapsed: open it to read the per-agent counts
  await page.evaluate(() => { S.sideOpen.agents = true; render(); });
  // TL changes render on the next animation frame (90-live-core.js): let that frame paint before reading the sidebar
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0))));
  const st = await page.evaluate(() => ({
    ag: AG.map((a) => [a.id, a.c, a.all]), n: ALL.length, byid: Object.keys(BYID).length, pj: PJ.map((p) => p.id),
    day0: new Date(DAY0).toISOString().slice(0, 10), last: LASTDAY, sel: S.sess.sel, newest: ALL[ALL.length - 1].id, proj: S.proj.sel,
    agents: Array.from(S.agents), side: Array.from(document.querySelectorAll('#side .ag')).map((b) => [b.dataset.a, b.querySelector('.ct').textContent])
  }));
  // ordered by session count; ties keep the fixed color-slot order so colors and positions never shuffle
  const byCount = FACTS.agents.slice().sort((x, y) => (y.n - x.n) || SLOT[AGENT_UI[x.id]] - SLOT[AGENT_UI[y.id]]);
  const want = byCount.map((a) => [AGENT_UI[a.id], 'var(--a' + SLOT[AGENT_UI[a.id]] + ')', a.n]);
  expect(st.ag).toEqual(want);
  expect(st.n).toBe(FACTS.rows.length);
  expect(st.byid).toBe(FACTS.rows.length);
  expect(st.pj.filter((p) => p !== '_none').sort()).toEqual(['proj_alpha', 'proj_beta']);   // _none = rows without a project
  expect(st.day0 <= FACTS.meta.first_day).toBe(true);
  expect(st.last).toBeGreaterThanOrEqual(119);
  expect(st.sel).toBe(st.newest);
  expect(st.proj).toBe(st.pj[0]);
  expect(st.side).toEqual(byCount.map((a) => [AGENT_UI[a.id], String(a.n)]));
  // the new color slots resolve to real colors in both themes
  for (const theme of ['light', 'dark']) {
    await page.evaluate((t) => setTheme(t), theme);
    const cs = await page.evaluate(() => ['--a6', '--a7', '--a8', '--a9', '--a6t', '--a9t'].map((k) => getComputedStyle(document.documentElement).getPropertyValue(k).trim()));
    expect(cs.every((c) => /^#[0-9a-f]{6}$/i.test(c))).toBe(true);
  }
  expect(await page.locator('.tl-table, .tl-kpi').count()).toBe(0);
  expect(await page.locator('#side').innerText()).not.toMatch(MOCK_MARKERS);
  expect(errors).toEqual([]);
});

for (const kind of ['full', 'empty']) {
  test('every route renders on the ' + kind + ' spine without page errors or plain tables', async ({ page }) => {
    test.setTimeout(90_000);
    const errors = collectErrors(page);
    await stubGateway(page, 'core', kind === 'empty' ? { 'GET /v1/uiview/facts': fx('core/facts-empty.json') } : {});
    await openLive(page);
    await expect.poll(() => page.evaluate(() => LV.state)).toBe(kind === 'empty' ? 'empty' : 'ready');
    if (kind === 'empty') {
      // before the first import the agents come from discovery (permission_denied skipped) + installed agents
      expect(await page.evaluate(() => AG.map((a) => [a.id, a.all, a.path]))).toEqual([['cc', 0, '~/.claude'], ['cx', 0, '~/.codex']]);
      expect(await page.evaluate(() => ALL.length)).toBe(0);
    }
    for (const r of await allRoutes(page)) {
      await visit(page, r);
      await page.waitForTimeout(150);
      expect(await page.locator('.tl-table, .tl-kpi').count(), r).toBe(0);
      expect(errors, r).toEqual([]);
    }
  });
}

test('strip: connecting before the gateway answers, computing on 202, then the 200 spine re-renders', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, 'core', { 'GET /v1/uiview/facts': { status: 202, body: fx('core/facts-computing.json') } });
  await page.goto('http://orbit.test/app?live=1#overview');
  await expect(page.locator('[data-tl="strip"] [data-tl="computing"]')).toBeVisible();
  expect(await page.evaluate(() => [LV.state, ALL.length])).toEqual(['computing', 0]);
  gw.set('GET /v1/uiview/facts', FACTS);
  await expect.poll(() => page.evaluate(() => LV.state), { timeout: 10_000 }).toBe('ready');
  await expect(page.locator('[data-tl="strip"] [data-tl="computing"]')).toHaveCount(0);
  expect(await page.evaluate(() => ALL.length)).toBe(FACTS.rows.length);
  await page.evaluate(() => { S.sideOpen.agents = true; render(); });
  await expect(page.locator('#side .ag[data-a="hm"]')).toBeVisible();
  expect(errors).toEqual([]);
});

test('strip: importing job frame shows progress; a data frame refetches the spine (304 keeps it)', async ({ page }) => {
  const gw = await stubGateway(page, 'core', { 'GET /v1/uiview/facts': { body: FACTS, headers: { ETag: '"3:fx"' } } });
  gw.push([{ event: 'job', data: { id: 'job_fx_1', kind: 'import', status: 'running', progress: { stage: '读取会话', completed: 3, total: 10 } } }]);
  await openLive(page, 'overview');
  await expect(page.locator('[data-tl="strip"] .tl-progress')).toContainText('正在导入');
  const before = gw.count('/v1/uiview/facts');
  await page.evaluate(() => TL.on && LV.loadSpine());
  await expect.poll(() => gw.count('/v1/uiview/facts')).toBeGreaterThan(before);
  expect(await page.evaluate(() => ALL.length)).toBe(FACTS.rows.length);
});

test('connecting: no gateway keeps the empty shell with 正在连接本机服务, never mock rows', async ({ page }) => {
  const errors = collectErrors(page);
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.addInitScript(() => { window.__ORBIT_ENDPOINT__ = 'http://orbit-down.test'; });
  await page.route(/^http:\/\/orbit-down\.test\//, (r) => r.abort('connectionrefused'));
  const html = (await import('node:fs')).readFileSync(new URL('../orbit-demo.html', import.meta.url), 'utf8');
  await page.route('http://orbit.test/app?live=1', (r) => r.fulfill({ contentType: 'text/html; charset=utf-8', body: html }));
  await page.goto('http://orbit.test/app?live=1');
  await expect(page.locator('[data-tl="strip"] [data-tl="connecting"]')).toBeVisible();
  expect(await page.evaluate(() => [ALL.length, AG.length, LV.state])).toEqual([0, 0, 'connecting']);
  expect(await page.locator('#main').innerText()).not.toMatch(MOCK_MARKERS);
  expect(errors.filter((e) => !/ERR_CONNECTION_REFUSED|Failed to fetch/.test(e))).toEqual([]);
});

test('feeds: LV.feed applies once per new response before render; 404 leaves the route in error, not mock', async ({ page }) => {
  await stubGateway(page, 'core', { 'GET /v1/fx/one': { value: 7 }, 'GET /v1/fx/missing': { status: 404 } });
  await openLive(page, 'tools');
  const r = await page.evaluate(async () => {
    window.__applied = [];
    LV.feeds.tools = []; LV.feeds.sentiment = []; // drop the real slice feeds: this test probes the feed mechanism itself
    LV.feed('tools', '/v1/fx/one', (d) => { window.__applied.push(d.value); });
    LV.feed('sentiment', [{ name: 'm', path: '/v1/fx/missing' }], () => { window.__applied.push('bad'); });
    render(); await new Promise((ok) => setTimeout(ok, 300)); render(); render();
    const tools = LV.feedState('tools');
    go('sentiment'); await new Promise((ok) => setTimeout(ok, 300)); render();
    return { applied: window.__applied, tools, sentiment: LV.feedState('sentiment') };
  });
  expect(r).toEqual({ applied: [7], tools: 'ready', sentiment: 'error' });
  // LRU: one request per key, revisits are cache hits
  const n = await page.evaluate(async () => {
    const c = LV.lru(2); LV.detail(c, 'a', '/v1/fx/one'); await new Promise((ok) => setTimeout(ok, 200));
    const hit = LV.detail(c, 'a', '/v1/fx/one'); LV.detail(c, 'b', '/v1/fx/one?b'); LV.detail(c, 'c', '/v1/fx/one?c');
    return [hit.state, hit.data.value, c.size, c.has('a')];
  });
  expect(n).toEqual(['ready', 7, 2, false]);
});

test('native bridge: request ids correlate with orbit:* replies; one-way posts; legacy true flag counts as native', async ({ page }) => {
  await stubGateway(page, 'core', {}, { native: { v: 1, app: '0.0.1', platform: 'macos', features: ['chooseFolder', 'save'] } });
  await openLive(page);
  const r = await page.evaluate(async () => {
    const p = ORBIT.native.request('chooseFolder', { purpose: 'source', agent: 'codex' });
    const m = window.__nativeMsgs[window.__nativeMsgs.length - 1];
    window.dispatchEvent(new CustomEvent('orbit:folder', { detail: { id: 'other', path: '/x', cancelled: false } }));
    window.dispatchEvent(new CustomEvent('orbit:folder', { detail: { id: m.id, path: '~/Code', cancelled: false } }));
    const reply = await p;
    ORBIT.native.post('zoom');
    return { isNative: ORBIT.native.isNative, has: ORBIT.native.has('save'), msg: m, reply, last: window.__nativeMsgs[window.__nativeMsgs.length - 1] };
  });
  expect(r.isNative).toBe(true);
  expect(r.has).toBe(true);
  expect(r.msg).toMatchObject({ type: 'chooseFolder', purpose: 'source', agent: 'codex' });
  expect(r.reply).toEqual({ id: r.msg.id, path: '~/Code', cancelled: false });
  expect(r.last).toEqual({ type: 'zoom' });
});

test('mock mode: file:// has no LV traffic, keeps the demo spine and a non-native bridge', async ({ page }) => {
  const reqs = [];
  page.on('request', (q) => { if (/^https?:/.test(q.url()) && !/fonts\./.test(q.url())) reqs.push(q.url()); });
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.goto('');
  await expect(page.locator('#main')).not.toBeEmpty();
  const st = await page.evaluate(() => ({ live: LV.live, n: ALL.length, ag: AG.map((a) => a.id), last: LASTDAY, day0: DAY0, native: ORBIT.native.isNative, wd: [0, 1, 5, 119].map(wd) }));
  expect(st).toEqual({ live: false, n: st.n, ag: ['cc', 'cx', 'km', 'ds', 'oc'], last: 119, day0: Date.UTC(2026, 5, 3), native: false, wd: [2, 3, 0, 2] });
  expect(st.n).toBeGreaterThan(400);
  expect(reqs).toEqual([]);
});

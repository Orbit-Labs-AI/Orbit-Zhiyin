// Live data adapter (prototypes/shared/tandem-live.js, src/js/06-live-client.js + 96-live-bind.js, and the @tandem-live block
// in the Lite HTML). The gateway is simulated with page.route on http://tandem.test: /app and /lite serve the built pages,
// /v1/* answers with the hand-written fixtures in prototypes/shared/fixtures, /v1/events with SSE frames from a queue.
//  1. mock          file:// pages stay in mock mode: no requests, no adapter markup on any page, no console errors
//  2. live Advance  import progress, overview counts, sessions + events, tools, projects, sidebar and settings › 数据源 all come
//                   from fixtures; missing values show「—」not 0; unbound pages carry 示例数据
//  3. outage        503 + Retry-After keeps the previous screen and shows the banner; service degraded shows too
//  4. restart       a tandem:endpoint event moves to the new gateway (new token) and re-renders from it
//  5. live Lite     same bindings in the single-file Lite page
//  6. Lite edition  Advance's Lite pages: l-home / l-sessions reuse the bound pages, l-persona / l-recs show 示例数据
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
    errors.push(m.text());
  });
  return errors;
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
      '/v1/app/settings': () => FX('app-settings')
    };
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

test('live Advance: progress, overview, sessions, tools, projects, sidebar and sources render from fixtures', async ({ page }) => {
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

test('live Advance in the Lite edition: l-home and l-sessions use the bound pages, the rest carry 示例数据', async ({ page }) => {
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
  for (const r of ['l-persona', 'l-recs']) {
    await page.evaluate((id) => go(id), r);
    await expect(page.locator('#content [data-tl="sample"]'), r).toHaveText('示例数据');
  }
  // back to Advance: the mapped route keeps its live page
  await page.evaluate(() => edSet('advance'));
  await expect.poll(() => page.evaluate(() => [S.ed, S.route])).toEqual(['advance', 'recs']);
  await page.evaluate(() => go('sessions'));
  await expect(page.locator('[data-tl="sessions"] tbody tr')).toHaveCount(2);
  expect(errors).toEqual([]);
});

test('live outage: 503 + Retry-After keeps the previous screen with a banner; gateway restart reconnects via tandem:endpoint', async ({ page }) => {
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
  await expect(page.locator('#content [data-tl="sample"]')).toBeVisible();
  await page.evaluate(() => ACT.settings());
  await expect(page.locator('#modal [data-tl="sources"]')).toContainText('Gemini CLI');
  expect(gw.seen.filter((s) => s.path.startsWith('/v1/')).every((s) => s.auth === 'Bearer fx-token')).toBe(true);
  expect(errors).toEqual([]);
});

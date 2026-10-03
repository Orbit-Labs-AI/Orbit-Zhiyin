// Real-scale UI (round 3, realdata-ui): what a v0.0.2 home (~2 200 sessions, 7 GB orbit.db, an import publishing) did to
// the page, rebuilt with synthetic fixtures — no real data.
//  1. While an import is publishing, every uiview answers 503 projection_pending + Retry-After: 1. The page used to poll the
//     open view once a second (and render twice a second) for as long as the import ran; now consecutive failures back off
//     to 30 s and data.published still refetches at once.
//  2. Thousands of sessions (columnar facts): every page opens without a long task and the A3 list stays paged.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NATIVE = { v: 1, app: '0.0.2', platform: 'macos', features: ['prefs'] };
const PENDING = { status: 503, headers: { 'Retry-After': '1' }, body: { error: { code: 'projection_pending', message: 'Import is publishing a new revision', retryable: true } } };

// columnar facts with n sessions over 88 days and 80 projects (same encoding as GET /v1/uiview/facts)
function bigFacts(n) {
  const f = fx('core/facts.json');
  const projects = Array.from({ length: 80 }, (_, i) => ({ id: 'proj_' + i, name: 'repo-' + i, path: '~/Code/repo-' + i, n: 0 }));
  const day0 = Date.UTC(2026, 6, 6);
  f.rows = Array.from({ length: n }, (_, i) => {
    projects[i % 80].n++;
    return ['s' + String(i).padStart(5, '0'), new Date(day0 + Math.floor(i * 88 / n) * 864e5).toISOString().slice(0, 10), (i * 7) % 24, (i * 13) % 60, i % 7, i % 80,
      '会话 ' + i + ' 修复构建脚本与测试', 5 + (i % 90), 10 + (i % 120), 4 + (i % 40), i % 200, i % 9, i % 4, i % 50, i % 2, i % 3, 0, 0, i % 4, 1000 * (i % 500)];
  });
  f.projects = projects; f.dicts = Object.assign({}, f.dicts, { p: projects.map((x) => x.id) });
  f.meta = Object.assign({}, f.meta, { day0: '2026-07-06', first_day: '2026-07-06', last_day: '2026-10-02', counts: { sessions: n, excluded: 0 } });
  return f;
}

test('projection_pending + Retry-After: 1 backs off instead of polling the open page every second', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  await page.clock.install({ time: new Date('2026-10-03T12:00:00+08:00') });
  const gw = await stubGateway(page, ['core', 's2'], { 'GET /v1/uiview/sessions': PENDING }, { native: NATIVE });
  await page.goto('http://orbit.test/app?live=1#sessions');
  await expect(page.locator('#main')).not.toBeEmpty();
  await expect.poll(() => gw.count('/v1/uiview/sessions')).toBeGreaterThan(0);
  const n0 = gw.count('/v1/uiview/sessions');
  const r0 = await page.evaluate(() => window.__renderCount);
  // one simulated minute, one second at a time (each step lets the refetch settle before the next timer)
  for (let i = 0; i < 60; i++) { await page.clock.runFor(1000); await page.waitForTimeout(15); }
  const polled = gw.count('/v1/uiview/sessions') - n0;
  const renders = (await page.evaluate(() => window.__renderCount)) - r0;
  // 1 + 2 + 4 + 8 + 16 + 30 s: at most ~7 refetches a minute (was 60, with 120 renders)
  expect(polled).toBeGreaterThan(2);
  expect(polled).toBeLessThanOrEqual(8);
  expect(renders).toBeLessThanOrEqual(20);
  // the import publishes: the next frame refetches at once, without waiting out the parked 30 s retry
  gw.set('GET /v1/uiview/sessions', fx('s2/list.json'));
  const n1 = gw.count('/v1/uiview/sessions');
  await page.evaluate(() => TL.invalidate());
  await page.clock.runFor(50);
  await expect.poll(() => gw.count('/v1/uiview/sessions')).toBeGreaterThan(n1);
  expect(errors).toEqual([]);
});

test('3 000 sessions: Advance and Lite pages open without long tasks; the A3 list stays paged', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(() => {
    window.__long = [];
    try { new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__long.push(Math.round(e.duration)))).observe({ type: 'longtask', buffered: true }); } catch (e) { /* no longtask API */ }
  });
  await stubGateway(page, ['core', 's1', 's3'], { 'GET /v1/uiview/facts': bigFacts(3000) }, { native: NATIVE });
  await openLive(page, 'overview');
  expect(await page.evaluate(() => ALL.length)).toBe(3000);
  const routes = ['overview', 'persona', 'sessions', 'tools', 'projects', 'sentiment', 'recs', 'library', 'studio', 'l-home', 'l-persona', 'l-sessions', 'l-recs'];
  for (const r of routes) {
    await page.evaluate(() => { window.__long = []; });
    await page.evaluate((rr) => { if (/^l-/.test(rr) !== (S.ed === 'lite')) edSet(/^l-/.test(rr) ? 'lite' : 'advance', rr); else go(rr); }, r);
    await expect.poll(() => page.evaluate(() => S.route)).toBe(r);
    await page.evaluate(() => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res))));
    const m = await page.evaluate(() => ({ long: Math.max(0, ...window.__long), dom: document.getElementsByTagName('*').length }));
    expect(m.long, r + ' long task').toBeLessThan(100);
    expect(m.dom, r + ' DOM size').toBeLessThan(4000);
  }
  await page.evaluate(() => edSet('advance', 'sessions'));
  await expect(page.locator('#slist .srow')).toHaveCount(120);
  await expect(page.locator('[data-act="sessLoadMore"]')).toContainText('还有 2880 个');
  expect(errors).toEqual([]);
});

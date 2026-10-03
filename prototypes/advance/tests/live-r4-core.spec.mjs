// Round 4, core: stub gateway, synthetic fixtures only (prototypes/shared/fixtures/core + s2).
//  R4-04  范围「全部」starts at the earliest session's day, not at the 120-day spine floor (no empty leading weeks).
//  R4-11  a transient network failure recovers by itself: the session trace refetches with backoff, the banner offers 重试,
//         and the service banner / error badge clear once the gateway answers again.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx } from './live-helpers.mjs';

const NOW = new Date('2026-10-03T12:00:00+08:00');
const FACTS = fx('core/facts.json');
const ONLY = () => test.skip(test.info().project.name !== 'mac-14', 'runs once, at the default size');
const A = 'session_fx016';
const LIST = fx('s2/list.json');
const frame = (page) => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0))));

test.beforeEach(async ({ page }) => { ONLY(); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

test('R4-04: 全部 is anchored to the earliest session (header, trend buckets, sentiment weeks)', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, 'core');
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  const first = FACTS.rows.map((r) => r[1]).sort()[0];
  await page.locator('[data-act="range"][data-v="0"]').first().click();
  await frame(page);
  const got = await page.evaluate(() => ({ w: win(0), first: Math.min(...ALL.map((s) => s.d)), label: winLabel(), bk: buckets(0)[0].a, d0: LASTDAY - 119 }));
  expect(got.w[0]).toBe(got.first);
  expect(got.bk).toBe(got.first);
  expect(got.w[0]).toBeGreaterThan(got.d0);           // the spine floor (today − 119) is no longer the window start
  expect(got.label.slice(0, 10)).toBe(first);
  // every bucket of the 全部 trend has the earliest session at or before it: no leading empty weeks
  const lead = await page.evaluate(() => { const bk = buckets(0)[0]; return ALL.filter((s) => s.d >= bk.a && s.d <= bk.b).length; });
  expect(lead).toBeGreaterThan(0);
  // 7 / 30 / 90 keep their fixed length
  expect(await page.evaluate(() => [7, 30, 90].map((r) => win(r)[1] - win(r)[0] + 1))).toEqual([7, 30, 90]);
  expect(errors).toEqual([]);
});

test('R4-11: a session detail that failed on the network refetches by itself with backoff', async ({ page }) => {
  const errors = collectErrors(page);
  const st = { down: true, hits: 0 };
  const gw = await stubGateway(page, ['core', 's2'], { 'GET /v1/uiview/sessions': () => LIST });
  // registered last, so it runs first: while down, the detail request fails like net::ERR_ADDRESS_INVALID
  await page.route(/^http:\/\/orbit\.test\/v1\/uiview\/sessions\/session_fx016(\?|$)/, (route) => { st.hits++; return st.down ? route.abort('addressunreachable') : route.fallback(); });
  await openLive(page, 'sessions');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  expect(await page.evaluate(() => S.sess.sel)).toBe(A);
  await expect(page.locator('.tl-sum')).toHaveAttribute('data-lv', 'error');
  // still down: it retries with backoff (≈ 1 s, 2 s …), not once and never again
  await expect.poll(() => st.hits, { timeout: 8000 }).toBeGreaterThan(1);
  st.down = false;
  await expect(page.locator('.tl-sum')).not.toHaveAttribute('data-lv', /.*/, { timeout: 12_000 });
  await expect(page.locator('.tl-mom').first()).toBeVisible();
  expect(gw.count('/v1/uiview/sessions/' + A)).toBeGreaterThan(0);
  expect(errors.filter((e) => !/ERR_ADDRESS_UNREACHABLE|net::/.test(e))).toEqual([]);
});

test('R4-11: a service banner after a network failure offers 重试, and clears once the gateway answers', async ({ page }) => {
  const errors = collectErrors(page);
  const st = { down: false };
  await stubGateway(page, ['core', 's2'], { 'GET /v1/uiview/sessions': () => LIST });
  await page.route(/^http:\/\/orbit\.test\/v1\/uiview\/sessions(\?|$)/, (route) => (st.down ? route.abort('addressunreachable') : route.fallback()));
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  st.down = true;
  await page.evaluate(() => { go('sessions'); });
  const banner = page.locator('#content > [data-tl="strip"] .tl-banner');
  await expect(banner).toContainText('服务暂时不可用', { timeout: 8000 });
  const retry = banner.locator('[data-act="lvRetry"]');
  await expect(retry).toHaveText('重试');
  st.down = false;
  await retry.click();
  await expect(page.locator('#content > [data-tl="strip"] .tl-banner')).toHaveCount(0, { timeout: 8000 });
  expect(await page.evaluate(() => LV.state)).toBe('ready');
  expect(errors.filter((e) => !/net::/.test(e))).toEqual([]);
});

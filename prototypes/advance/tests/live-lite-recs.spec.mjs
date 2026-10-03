// Lite recommendation cards on live data (A1/A2/Lite area): icons the backend names but the prototype has no glyph for
// (recommend/narrate.py emits ui.icon 'flow') and recs without a saving share (no ui.save → x.pct null).
// Regressions for journey J12 / B19: switching to Lite logged `<path> attribute d: … "undefined"` x3 and the cards showed
// a big green dash, the hero a made-up 0.0 total. Savings are shares of the real trajectory, never hours.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NOW = new Date('2026-10-03T12:00:00+08:00');
const OV = { 7: fx('s1/overview-7.json'), 30: fx('s1/overview-30.json'), 90: fx('s1/overview-90.json'), 0: fx('s1/overview-0.json') };

function recsBody(edit) {
  const b = fx('recs/recommendations.json');
  b.items.forEach((c, i) => edit(c, i));
  return b;
}
function routes(recs) {
  return {
    'GET /v1/uiview/overview': (req, u) => { const r = u.searchParams.get('range'); return OV[r] ? OV[r] : { status: 404 }; },
    'GET /v1/uiview/persona': (req, u) => { const p = u.searchParams.get('period') || '90'; return p === '30' ? fx('s1/persona-30.json') : p === '90' ? fx('s1/persona-90.json') : { status: 404 }; },
    'GET /v1/uiview/persona/reveal': () => fx('s1/reveal.json'),
    'GET /v1/recommendations': recs
  };
}
const badPaths = (page) => page.evaluate(() => [...document.querySelectorAll('path')].filter((p) => p.getAttribute('d') === 'undefined').length);

test.use({ timezoneId: 'Asia/Shanghai' });
test.beforeEach(async ({ page }) => { ONLY('mac-14'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

test('Lite recs: unknown backend icon falls back to a real glyph; no estimate → no 0.0 total, no green dash', async ({ page }) => {
  test.skip(!!PASS, 'stubbed recommendation bodies');
  const errors = collectErrors(page);
  await stubGateway(page, 's1', routes(recsBody((c) => { c.dim = 'flow'; c.ui.dim = 'flow'; c.ui.icon = 'flow'; delete c.ui.save; delete c.score.benefit; })));
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => visibleRecs().filter((r) => r.live).length)).toBeGreaterThan(0);
  expect(await badPaths(page)).toBe(0);
  await page.evaluate(() => edSet('lite'));
  await expect.poll(() => page.evaluate(() => S.route)).toBe('l-home');
  await expect(page.locator('.l-one .rc-top svg.ico path').first()).toHaveAttribute('d', /^M/);
  await expect(page.locator('.l-one .l-gain')).toContainText('节省比例待估算');
  await expect(page.locator('.l-one .l-gain .v')).toHaveCount(0);
  await page.evaluate(() => go('l-recs'));
  await expect(page.locator('.l-rhero')).toContainText('还没有节省比例的估计');
  await expect(page.locator('.l-rhero')).not.toContainText('0.0');
  await expect(page.locator('.l-rc .l-gain .v')).toHaveCount(0);
  expect(await page.locator('.l-rc .l-gain').first().innerText()).not.toMatch(/h \/ 月|小时/);
  expect(await badPaths(page)).toBe(0);
  expect(errors).toEqual([]);
});

test('Lite recs: shares present → the hero adds them per problem and each card shows its percentage', async ({ page }) => {
  test.skip(!!PASS, 'stubbed recommendation bodies');
  const errors = collectErrors(page);
  // two recs on one problem (alternatives: the best counts once) and one without a share
  const saves = [{ time_pct: 1.2, token_pct: 0.5, key: 'p1' }, { time_pct: 0.8, token_pct: 2.1, key: 'p1' }, null];
  await stubGateway(page, 's1', routes(recsBody((c, i) => { if (saves[i]) c.ui.save = Object.assign({ share: { time: 2, token: 3 }, effect: 0.6 }, saves[i]); else delete c.ui.save; })));
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => visibleRecs().filter((r) => r.live).length)).toBeGreaterThan(0);
  await page.evaluate(() => { edSet('lite'); go('l-recs'); });
  // max per problem: 1.2 % of the time, 2.1 % of the tokens — not 2.0 % / 2.6 %
  await expect(page.locator('.l-rhero .l-big-n .v')).toHaveAttribute('data-count', '1.2');
  await expect(page.locator('.l-rhero .l-big-n')).toContainText('1.2%的协作时间');
  await expect(page.locator('.l-rhero')).toContainText('token 预计省下 2.1%');
  await expect(page.locator('.l-rhero')).not.toContainText(/小时|h \/ 月/);
  await expect(page.locator('.l-rc .l-gain .v')).toHaveCount(2);
  await expect(page.locator('.l-rc .l-gain').nth(2)).toContainText('节省比例待估算');
  expect(errors).toEqual([]);
});

// Live core regressions from the v0.0.1 journey (J03–J06, B03–B04): sidebar / filter counts follow the live spine, no mock
// identity or demo welcome on live screens, an idle analysis worker is healthy, a facts 5xx is a failed read (not
// "connecting"). Stub gateway, fixtures in prototypes/shared/fixtures/core.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NOW = new Date('2026-10-03T12:00:00+08:00');

test.beforeEach(async ({ page }) => { ONLY('mac-14'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

const sideCount = (page, r) => page.locator('#side button[data-r="' + r + '"] .ct');

test('J03/J04: sidebar and filter counts follow the live spine; no mock identity in the footer', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, 'core');
  await openLive(page, 'overview');
  const [pj, ag] = await page.evaluate(() => [PJ.length, AG.length]);
  expect(pj).toBeGreaterThan(0);
  await expect(sideCount(page, 'projects')).toHaveText(String(pj));
  await expect(page.locator('.frow [data-act="agentMenu"]')).toHaveText('Agent · 全部 ' + ag);
  await expect(page.locator('.frow [data-act="projectMenu"]')).toHaveText('项目 · 全部 ' + pj);
  await expect(page.locator('#side .me .nm')).toHaveText('本机用户');
  expect(await page.locator('#side').innerText()).not.toMatch(/yhyfhgs/);
  await page.evaluate(() => { go('overview'); edSet('lite'); });
  await expect.poll(() => page.evaluate(() => S.ed)).toBe('lite');
  expect(await page.locator('#side').innerText()).not.toMatch(/yhyfhgs/);
  expect(errors).toEqual([]);
});

test('J03: the empty spine shows 0 projects and the real agent count, not the mock 9 / 5', async ({ page }) => {
  await stubGateway(page, 'core', { 'GET /v1/uiview/facts': fx('core/facts-empty.json') });
  await openLive(page, 'overview');
  expect(await page.evaluate(() => LV.state)).toBe('empty');
  const ag = await page.evaluate(() => AG.length);
  await expect(page.locator('.frow [data-act="projectMenu"]')).toHaveText('项目 · 全部 0');
  await expect(page.locator('.frow [data-act="agentMenu"]')).toHaveText('Agent · 全部 ' + ag);
  await expect(page.locator('[data-tl="connecting"]')).toHaveCount(0);
  await expect(page.locator('#side .sb-foot')).not.toContainText('正在连接本机服务');
});

test('J05: no demo welcome toast in live mode', async ({ page }) => {
  await stubGateway(page, 'core');
  await openLive(page, 'overview');
  await page.waitForTimeout(1200);
  expect(await page.locator('body').innerText()).not.toMatch(/欢迎体验 Orbit 交互 Demo|数据都是示例/);
});

test('J06/B04: an idle analysis worker raises no banner; degraded / restarting still do', async ({ page }) => {
  const gw = await stubGateway(page, 'core');
  gw.push([{ event: 'service', data: { name: 'analysis', state: 'idle' } }, { event: 'service', data: { name: 'gateway', state: 'ok' } }]);
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => TL.services.analysis)).toBe('idle');
  await expect(page.locator('[data-tl="degraded"]')).toHaveCount(0);
  await page.evaluate(() => { TL.services.analysis = 'degraded'; TL.changed(); });
  await expect(page.locator('[data-tl="degraded"]')).toContainText('analysis 降级');
  await page.evaluate(() => { TL.services.analysis = 'idle'; TL.changed(); });
  await expect(page.locator('[data-tl="degraded"]')).toHaveCount(0);
});

test('B03: a facts 500 is a failed read with real counts, not connecting with mock defaults', async ({ page }) => {
  await stubGateway(page, 'core', { 'GET /v1/uiview/facts': { status: 500 } });
  await page.goto('http://orbit.test/app?live=1#overview');
  await expect.poll(() => page.evaluate(() => LV.state), { timeout: 10_000 }).toBe('error');
  await expect(page.locator('[data-tl="strip"] [data-tl="error"]')).toContainText('读取失败');
  await expect(page.locator('[data-tl="connecting"]')).toHaveCount(0);
  await expect(page.locator('.frow [data-act="projectMenu"]')).toHaveText('项目 · 全部');
  expect(await page.locator('#side').innerText()).not.toMatch(/yhyfhgs/);
});

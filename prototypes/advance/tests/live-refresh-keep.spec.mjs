// Import / polling keeps the screen still (F03 / F08): while an import runs and reads answer 503 projection_pending with
// Retry-After: 1, the page is not rebuilt every second — the settings window, long pages and an open dropdown keep their
// scroll position and state — and the strip reads 「正在整理数据…」 instead of an error banner. Stub gateway.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, PASS } from './live-helpers.mjs';

const JOB = '10951bad4daa4a2fb0994de1f0d61e09';
const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
test.skip(!!PASS, 'stub-only: feeds synthetic job frames');

const frame = (page, name, data) => page.evaluate(([n, d]) => TL.dispatch(n, d), [name, data]);
const job = (done, total) => ({ id: JOB, kind: 'import', status: 'running', progress: { stage: 'map', completed: done, total, unit: 'files' } });
const PENDING = { status: 503, headers: { 'Retry-After': '1' }, body: { error: { code: 'projection_pending', message: 'The first import has not published yet', retryable: true } } };
// every page read beyond the spine answers projection_pending (the first import has not published yet)
const pendingAll = () => {
  const extra = {};
  ['sessions', 'tools', 'projects', 'overview', 'sentiment', 'recs', 'persona'].forEach((p) => { extra['GET /v1/uiview/' + p] = PENDING; });
  ['GET /v1/sessions', 'GET /v1/analytics/overview', 'GET /v1/analytics/sessions', 'GET /v1/analytics/tools', 'GET /v1/analytics/projects', 'GET /v1/analytics/sentiment', 'GET /v1/analytics/recommendations'].forEach((k) => { extra[k] = PENDING; });
  return extra;
};

const filler = '#content::after{content:"";display:block;flex:none;height:3000px} #set .body::after{content:"";display:block;flex:none;height:2000px}';
const renders = (page) => page.evaluate(() => window.__renderCount);

test('projection_pending while publishing: a calm 正在整理数据… line, quiet retries, no page rebuild', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core'], pendingAll());
  await openLive(page, 'sessions');
  await page.addStyleTag({ content: filler });
  await expect(page.locator('#content [data-tl="pending"]')).toContainText('正在整理数据');
  await expect(page.locator('#content [data-tl="unavailable"]')).toHaveCount(0);
  await expect(page.locator('#content [data-tl="retry"]')).toHaveCount(0);
  await expect(page.locator('#content [data-tl="strip"]')).not.toContainText('服务暂时不可用');
  await page.evaluate(() => { document.querySelector('#content').scrollTop = 500; });
  await page.waitForTimeout(1200);   // the first reads settle
  const n0 = await renders(page); const q0 = gw.count('/v1/uiview/sessions');
  await page.waitForTimeout(4000);
  // Retry-After: 1 keeps reading (quietly) but nothing is rebuilt and the page stays where the user scrolled it
  expect(gw.count('/v1/uiview/sessions') - q0).toBeGreaterThanOrEqual(2);
  expect(await renders(page) - n0).toBe(0);
  expect(await page.evaluate(() => document.querySelector('#content').scrollTop)).toBe(500);
  // settings › 数据源: scrolled down, it stays there through the polling and through renders of any origin
  await page.evaluate(() => openSettings('sources'));
  await expect(page.locator('#set .body')).toBeVisible();
  await page.evaluate(() => { document.querySelector('#set .body').scrollTop = 300; });
  await page.waitForTimeout(3000);
  expect(await page.evaluate(() => document.querySelector('#set .body').scrollTop)).toBe(300);
  await page.evaluate(() => { render(); renderSet(); });
  expect(await page.evaluate(() => document.querySelector('#set .body').scrollTop)).toBe(300);
  expect(await page.evaluate(() => document.querySelector('#content').scrollTop)).toBe(500);
  // another tab opens at its top — the old tab's scroll does not carry over (only a redraw of the same tab keeps it)
  const setTop = () => page.evaluate(() => document.querySelector('#set .body').scrollTop);
  await page.locator('#set [data-act="setTab"][data-v="analysis"]').click();
  await expect(page.locator('#set [data-act="setTab"][data-v="analysis"]')).toHaveAttribute('aria-selected', 'true');
  expect(await setTop()).toBe(0);
  await page.evaluate(() => { document.querySelector('#set .body').scrollTop = 120; });
  await page.evaluate(() => renderSet());
  expect(await setTop()).toBe(120);
  await page.locator('#set [data-act="setTab"][data-v="sources"]').click();
  expect(await setTop()).toBe(0);
  // a real failure still raises the error banner with 重试
  await page.evaluate(() => closeSettings && closeSettings());
  gw.set('GET /v1/uiview/sessions', { status: 500, body: { error: { code: 'internal', message: 'boom', retryable: true } } });
  await expect(page.locator('#content [data-tl="unavailable"]')).toContainText('服务暂时不可用', { timeout: 6000 });
  await expect(page.locator('#content [data-tl="retry"]')).toBeVisible();
  expect(errors).toEqual([]);
});

test('import running + pending reads: scroll and an open dropdown survive polling and forced renders, Lite too', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  await stubGateway(page, ['core'], pendingAll());
  await openLive(page, 'sessions');
  await page.addStyleTag({ content: filler });
  await frame(page, 'job', job(1, 40));
  await expect(page.locator('#content .tl-progress')).toBeVisible();
  // the import note stands for it: no separate pending banner, never an error banner
  await expect(page.locator('#content [data-tl="unavailable"]')).toHaveCount(0);
  await page.evaluate(() => { document.querySelector('#content').scrollTop = 400; });
  await page.waitForTimeout(50);
  await page.evaluate(() => document.querySelector('#main [data-act="agentMenu"]').click());
  await expect(page.locator('#dd')).toBeVisible();
  for (let i = 2; i <= 16; i++) { await frame(page, 'job', job(i, 40)); await page.waitForTimeout(200); }
  await expect(page.locator('#content .tl-progress')).toContainText('16');
  await expect(page.locator('#dd')).toBeVisible();
  expect(await page.evaluate(() => document.querySelector('#content').scrollTop)).toBe(400);
  // a full render (whatever triggers it) keeps the scroll and re-hangs the open dropdown from the rebuilt chip
  await page.evaluate(() => render());
  await expect(page.locator('#dd')).toBeVisible();
  expect(await page.evaluate(() => document.querySelector('#content').scrollTop)).toBe(400);
  expect(await page.evaluate(() => DD && DD.anchor.isConnected)).toBe(true);
  const a1 = await page.locator('#main [data-act="agentMenu"]').boundingBox(); const d1 = await page.locator('#dd').boundingBox();
  expect(Math.abs(d1.y - (a1.y + a1.height + 4))).toBeLessThan(2);
  expect(Math.abs(d1.x - a1.x)).toBeLessThan(2);
  await page.keyboard.press('Escape');
  await page.evaluate(() => closeDD());
  // Lite: a long page keeps its place through the same polling
  await page.evaluate(() => { edSet('lite'); go('l-home'); });
  await page.waitForTimeout(1000);   // the edition switch settles
  await page.evaluate(() => { document.querySelector('#content').scrollTop = 350; });
  expect(await page.evaluate(() => document.querySelector('#content').scrollTop)).toBe(350);
  const n0 = await renders(page);
  for (let i = 17; i <= 26; i++) { await frame(page, 'job', job(i, 40)); await page.waitForTimeout(200); }
  expect(await renders(page) - n0).toBeLessThanOrEqual(1);
  expect(await page.evaluate(() => document.querySelector('#content').scrollTop)).toBe(350);
  await page.evaluate(() => render());
  expect(await page.evaluate(() => document.querySelector('#content').scrollTop)).toBe(350);
  expect(errors).toEqual([]);
});

test('projection_pending on the overview and persona pages: the persona card reads 正在整理数据…, never 取不到', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  await stubGateway(page, ['core'], pendingAll());
  for (const route of ['overview', 'persona']) {
    await openLive(page, route);
    await page.waitForTimeout(2500);   // several Retry-After rounds
    await expect(page.locator('#content')).not.toContainText('画像暂时取不到');
    await expect(page.locator('#content')).not.toContainText('服务暂时不可用');
  }
  expect(errors).toEqual([]);
});

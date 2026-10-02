// Every page renders without runtime errors and nothing scrolls sideways; every overlay, menu, simulated
// event and shortcut opens cleanly. Together they fail when a source file goes missing from the build.
import { test, expect } from '@playwright/test';
import { routeIds, openDemo, go, closeAll } from './helpers.mjs';

test('all pages render without errors or horizontal overflow', async ({ page }, info) => {
  const errors = await openDemo(page);
  const routes = await routeIds(page);
  expect(routes.length).toBeGreaterThan(0);
  for (const r of routes) {
    await go(page, r);
    await expect(page.locator('#main')).not.toBeEmpty();
    // body and .desk clip overflow, so measure the pane that actually scrolls.
    const over = await page.evaluate(() => {
      const c = document.querySelector('#main .content');
      return { page: document.documentElement.scrollWidth - window.innerWidth, content: c ? c.scrollWidth - c.clientWidth : null };
    });
    expect.soft(over.content, r + ': #main .content not found').not.toBeNull();
    expect.soft(over.page, r + ' page overflow').toBeLessThanOrEqual(0);
    expect.soft(over.content, r + ' content overflow').toBeLessThanOrEqual(1);
  }
  if (info.project.name === 'compact') {
    // Under 900px the sidebar is an off-canvas drawer opened from the burger button.
    await expect(page.locator('.burger')).toBeVisible();
    const side = await page.locator('.side').boundingBox();
    expect(side.x + side.width).toBeLessThanOrEqual(1);
  }
  expect(errors).toEqual([]);
});

test('overlays, menus, simulated events and shortcuts work without errors', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'interaction coverage runs once, at the default size');
  const errors = await openDemo(page);
  const tabs = await page.evaluate(() => SET_TABS.map((t) => t[0]));
  const calls = [
    ['openPalette'], ['openAsk'], ['openKeys'], ['openAbout'], ['openMethod'],
    ['openReport'], ['openCSV'], ['openShare'], ['openOnboarding', 0], ['openReveal'],
    ['renderPop'], ['toggleHud'], ['toggleHud'], ['goBack'], ['mainAction'],
    ...tabs.map((t) => ['openSettings', t]),
    ...['running', 'waiting', 'done', 'stuck', 'ctx', 'weekly', 'newsrc', 'idle'].map((k) => ['simEvent', k]),
  ];
  for (const [fn, ...args] of calls) {
    const ok = await page.evaluate(([f, a]) => { if (typeof window[f] !== 'function') return false; window[f](...a); return true; }, [fn, args]);
    expect.soft(ok, fn + ' is not defined').toBe(true);
    await page.waitForTimeout(30);
    await closeAll(page);
  }
  await page.keyboard.press('ControlOrMeta+KeyK');
  await expect(page.locator('#modal')).toBeVisible();
  await closeAll(page);
  await page.keyboard.press('ControlOrMeta+Comma');
  await expect(page.locator('#set')).toBeVisible();
  await closeAll(page);
  const routes = await routeIds(page);
  for (let i = 0; i < Math.min(routes.length, 9); i++) {
    await page.keyboard.press('Alt+Digit' + (i + 1));
    await expect.poll(() => page.evaluate(() => S.route)).toBe(routes[i]);
  }
  expect(errors).toEqual([]);
});

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
    // A stage narrower than the 900×600 minimum window: the window fills the stage ("fit" mode, 16px margins), the sidebar
    // takes no content width by default, and the title-bar toggle opens it as an overlay without any sideways overflow.
    const vw = page.viewportSize();
    const win = page.locator('#win');
    await expect(win).toHaveAttribute('data-mode', 'fit');
    await expect(win).toHaveClass(/\bnosb\b/);
    const w = await win.boundingBox();
    expect(w.x).toBe(16); expect(w.width).toBe(vw.width - 32); expect(w.y).toBe(24 + 16); expect(w.height).toBe(vw.height - 24 - 32);
    await expect(page.locator('#side')).toBeHidden();
    const main = await page.locator('#main').boundingBox();
    expect(main.x).toBe(w.x); expect(main.width).toBe(w.width);
    await page.locator('#wtop [data-act="sideToggle"]').click();
    await expect(win).toHaveClass(/\bsbover\b/);
    await expect(page.locator('#side')).toBeVisible();
    // let the slide-in transition finish (infinite animations such as the live-dot pulse are skipped)
    await page.evaluate(() => Promise.race([Promise.all(document.getAnimations().filter((a) => { const t = a.effect && a.effect.getTiming(); return t && t.iterations !== Infinity; }).map((a) => a.finished.catch(() => {}))), new Promise((r) => setTimeout(r, 1500))]));
    const side = await page.locator('#side').boundingBox();
    expect(side.x).toBe(w.x); expect(side.x + side.width).toBeLessThanOrEqual(w.x + w.width);
    const over = await page.evaluate(() => { const m = document.querySelector('#main'); return { page: document.documentElement.scrollWidth - window.innerWidth, main: m.scrollWidth - m.clientWidth }; });
    expect(over.page).toBeLessThanOrEqual(0); expect(over.main).toBeLessThanOrEqual(1);
    await page.locator('#sidescrim').click({ position: { x: 600, y: 300 } });
    await expect(page.locator('#side')).toBeHidden();
  }
  expect(errors).toEqual([]);
});

test('overlays, menus, simulated events and shortcuts work without errors', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'interaction coverage runs once, at the default size');
  const errors = await openDemo(page);
  const tabs = await page.evaluate(() => SET_TABS.map((t) => t[0]));
  const calls = [
    ['openPalette'], ['openAsk'], ['openKeys'], ['openAbout'], ['openMethod'],
    ['openReport'], ['openShare'], ['openOnboarding', 0], ['openReveal'],
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

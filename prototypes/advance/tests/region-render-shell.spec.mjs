// Region rendering outside the page regions: go() to the page already on screen is not a navigation (no full render, the
// scroll stays), and the settings panel is morphed in place on every render (a live frame while it is open keeps the
// scrolled body and its nodes). Mock data (file://).
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');

test('go() to the current page refreshes regions in place; a route change still renders the page once', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  await go(page, 'projects');
  await page.evaluate(() => { const c = $('#content'); c.scrollTop = 200; c.__mark = 1; $('[data-region="a5:table"]').__mark = 1; });
  const r0 = await page.evaluate(() => window.__renderCount);
  const scrolled = await page.evaluate(() => $('#content').scrollTop);
  // a pinned project in the sidebar while 项目习惯 is open: picks the project without rebuilding the page
  const pid = await page.evaluate(() => PJ.slice(0, 3).map((p) => p.id).find((id) => id !== S.proj.sel));
  await page.locator('#side [data-act="pinProject"][data-p="' + pid + '"]').click();
  await expect.poll(() => page.evaluate(() => S.proj.sel)).toBe(pid);
  expect(await page.evaluate(() => window.__renderCount)).toBe(r0);
  expect(await page.evaluate(() => [$('#content').__mark, $('[data-region="a5:table"]').__mark, $('#content').scrollTop])).toEqual([1, 1, scrolled]);
  // the sidebar row of the current page and ⌥-shortcut style go() calls behave the same
  await page.locator('#side [data-act="go"][data-r="projects"]').click();
  await page.evaluate(() => go('projects'));
  expect(await page.evaluate(() => window.__renderCount)).toBe(r0);
  expect(await page.evaluate(() => [$('#content').__mark, $('#content').scrollTop])).toEqual([1, scrolled]);
  // a real route change is one full render and starts at the top
  await go(page, 'tools');
  expect(await page.evaluate(() => window.__renderCount)).toBe(r0 + 1);
  expect(await page.evaluate(() => $('#content').scrollTop)).toBe(0);
  expect(errors).toEqual([]);
});

test('settings panel: renders while it is open keep the scrolled body, its nodes and the focused field', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  await page.evaluate(() => openSettings('sources'));
  const body = page.locator('#set .body');
  await expect(body).toBeVisible();
  await page.evaluate(() => { const b = $('#set .body'); b.scrollTop = 240; b.__mark = 1; $('#set .tabs').__mark = 1; });
  const top = await page.evaluate(() => $('#set .body').scrollTop);
  expect(top).toBeGreaterThan(0);
  await page.evaluate(() => { render(); render(); render(); });
  expect(await page.evaluate(() => [$('#set .body').__mark, $('#set .tabs').__mark, $('#set .body').scrollTop])).toEqual([1, 1, top]);
  // the add-source form: typing survives a render (value and caret stay on the focused field)
  await page.locator('#set [data-act="setAddSrc"]').first().click();
  const path = page.locator('#srcPath');
  await expect(path).toBeFocused();
  await path.fill('~/logs/agent');
  await page.evaluate(() => render());
  await expect(path).toBeFocused();
  await expect(path).toHaveValue('~/logs/agent');
  // switching tabs still shows the other tab
  await page.locator('#set [data-act="setTab"][data-v="privacy"]').click();
  await expect(page.locator('#setTitle')).toHaveText(await page.evaluate(() => SET_TABS.find((x) => x[0] === 'privacy')[1]));
  expect(errors).toEqual([]);
});

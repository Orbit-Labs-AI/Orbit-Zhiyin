// Lite / Advance live in one window: the sidebar switch, menu, palette and ⌃⌘L swap editions, routes map both ways and the
// choice persists across reloads.
import { test, expect } from '@playwright/test';
import { openDemo } from './helpers.mjs';

const ed = (page) => page.evaluate(() => [S.ed, S.route]);

test('the sidebar switch swaps editions, maps the route and persists', async ({ page }) => {
  const errors = await openDemo(page, 'persona');
  await page.evaluate(() => { S.side = true; S.sideOver = true; render(); });
  expect(await ed(page)).toEqual(['advance', 'persona']);
  await page.locator('.edsw [data-v="lite"]').click();
  await expect.poll(() => ed(page)).toEqual(['lite', 'l-persona']);
  await expect(page.locator('#win')).toHaveAttribute('data-ed', 'lite');
  await expect(page.locator('.edsw [data-v="lite"]')).toHaveAttribute('aria-checked', 'true');
  // Lite sidebar: four pages only (keyboard shortcuts follow the Lite order)
  await expect(page.locator('#side .nav button[data-act="go"]')).toHaveCount(4);
  // same sidebar components as Advance: groups, Agents list, footer
  await expect(page.locator('#side .sect')).toHaveCount(3);
  await expect(page.locator('#side .nav .ag')).toHaveCount(5);
  await expect(page.locator('#side .sb-foot .pv')).toHaveCount(1);
  await page.keyboard.press('Alt+Digit4');
  await expect.poll(() => ed(page)).toEqual(['lite', 'l-recs']);
  await page.reload();
  await expect.poll(() => ed(page)).toEqual(['lite', 'l-recs']);
  await page.keyboard.press('Control+Meta+KeyL');
  await expect.poll(() => ed(page)).toEqual(['advance', 'recs']);
  await page.keyboard.press('Control+Meta+KeyL');
  await expect.poll(() => ed(page)).toEqual(['lite', 'l-recs']);
  // a link into an Advance-only page is a request for detail: it switches to Advance and offers the way back
  await page.evaluate(() => go('tools'));
  await expect.poll(() => ed(page)).toEqual(['advance', 'tools']);
  await expect(page.locator('#toast')).toContainText('Advance');
  await expect(page.locator('#win')).toHaveAttribute('data-ed', 'advance');
  expect(errors).toEqual([]);
});

test('edOpen jumps from Lite into an Advance detail page', async ({ page }) => {
  const errors = await openDemo(page);
  await page.evaluate(() => { S.ed = 'lite'; go('l-sessions'); });
  await expect.poll(() => ed(page)).toEqual(['lite', 'l-sessions']);
  await page.evaluate(() => edOpen('tools'));
  await expect.poll(() => ed(page)).toEqual(['advance', 'tools']);
  // menus and the palette list the current edition's pages
  const adv = await page.evaluate(() => navRoutes().length);
  await page.evaluate(() => { S.ed = 'lite'; go('l-home'); });
  const lite = await page.evaluate(() => navRoutes().map((r) => r[0]));
  expect(adv).toBe(9);
  expect(lite).toEqual(['l-home', 'l-persona', 'l-sessions', 'l-recs']);
  expect(errors).toEqual([]);
});

test('reduced motion swaps editions at once', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openDemo(page);
  await page.evaluate(() => edSet('lite'));
  expect(await ed(page)).toEqual(['lite', 'l-home']);
  expect(errors).toEqual([]);
});

// Editions are merged: the Lite/Advance switch bar is gone, every page is reachable inside Lite (pages without a Lite
// layout render the full page there), and the Advanced-mode setting only changes how the pages are rendered. The edition
// still persists, ⌃⌘L still toggles it, and edOpen opens a detail page inside the current edition instead of switching.
import { test, expect } from '@playwright/test';
import { openDemo } from './helpers.mjs';

const ed = (page) => page.evaluate(() => [S.ed, S.route]);
const LITE_ROUTES = ['l-home', 'l-persona', 'l-sessions', 'l-recs', 'library', 'sentiment', 'projects', 'tools', 'studio'];

test('merged editions: no switch bar, every page reachable in Lite, links keep the edition', async ({ page }) => {
  const errors = await openDemo(page, 'persona');
  expect(await ed(page)).toEqual(['advance', 'persona']);
  // the sidebar switch bar is removed in both editions
  await expect(page.locator('#side .edsw')).toHaveCount(0);
  await page.evaluate(() => edSet('lite'));
  await expect.poll(() => ed(page)).toEqual(['lite', 'l-persona']);
  await expect(page.locator('#win')).toHaveAttribute('data-ed', 'lite');
  await expect(page.locator('#side .edsw')).toHaveCount(0);
  // Lite carries the same sidebar components; every page is in it (更多 / Agents start collapsed)
  await expect(page.locator('#side .sect')).toHaveCount(5);
  expect(await page.evaluate(() => navRoutes().map((r) => r[0]))).toEqual(LITE_ROUTES);
  await page.evaluate(() => { S.sideOpen.more = true; S.sideOpen.agents = true; render(); });
  await expect(page.locator('#side .nav button[data-act="go"]')).toHaveCount(LITE_ROUTES.length);
  // a page Lite has no layout for is a request for detail, not an edition switch: it renders the full page in place
  await page.evaluate(() => go('tools'));
  await expect.poll(() => ed(page)).toEqual(['lite', 'tools']);
  await expect(page.locator('#win')).toHaveAttribute('data-ed', 'lite');
  await expect(page.locator('#content .frow').first()).toBeAttached();
  await expect(page.locator('#toast')).not.toContainText('Advance');
  // the edition persists (browser demo: the URL hash keeps the Lite route across reloads)
  expect(await page.evaluate(() => store.get('edition', null))).toBe('lite');
  await page.evaluate(() => go('l-persona'));
  await expect.poll(() => ed(page)).toEqual(['lite', 'l-persona']);
  await page.reload();
  await expect.poll(() => ed(page)).toEqual(['lite', 'l-persona']);
  expect(errors).toEqual([]);
});

test('edOpen opens a detail page inside the current edition and keeps the selection', async ({ page }) => {
  const errors = await openDemo(page);
  await page.evaluate(() => edSet('lite', 'l-sessions'));
  await expect.poll(() => ed(page)).toEqual(['lite', 'l-sessions']);
  const id = await page.evaluate(() => { const s = sel({ noExtra: true }).find((x) => !x.live); S.sess.sel = s.id; render(); return s.id; });
  await page.evaluate(() => edOpen('sessions'));
  await expect.poll(() => ed(page)).toEqual(['lite', 'sessions']);
  await expect(page.locator('#win')).toHaveAttribute('data-ed', 'lite');
  expect(await page.evaluate(() => S.sess.sel)).toBe(id);
  await expect(page.locator('#content .sess')).toBeVisible();
  await expect(page.locator('#content .frow').first()).toBeAttached();
  // the Window menu lists every page of the merged edition, not just the four Lite layouts
  const names = await page.evaluate(() => MENUS.window().filter((i) => i.k && /^⌥[1-9]$/.test(i.k)).map((i) => i.t));
  expect(names.slice(0, LITE_ROUTES.length)).toEqual(['概览', '协作画像', '会话轨迹', '优化建议', '资源库', '情绪语义', '项目习惯', '工具调用', '生成工坊']);
  expect(errors).toEqual([]);
});

test('Advanced mode: the setting and the View menu toggle the full layout, ⌃⌘L persists', async ({ page }) => {
  const errors = await openDemo(page, 'l-home');
  await page.evaluate(() => edSet('lite', 'l-home'));
  await expect.poll(() => ed(page)).toEqual(['lite', 'l-home']);
  // Settings › 通用 › 高级模式
  await page.evaluate(() => openSettings('general'));
  const sw = page.locator('#set [data-act="setAdv"]');
  await expect(sw).toHaveAttribute('aria-checked', 'false');
  await expect(page.locator('#set')).toContainText('高级模式');
  await sw.click();
  await expect.poll(() => page.evaluate(() => S.ed)).toBe('advance');
  await expect.poll(() => page.evaluate(() => S.route)).toBe('overview');
  await expect(page.locator('#win')).toHaveAttribute('data-ed', 'advance');
  await expect(sw).toHaveAttribute('aria-checked', 'true');
  await page.evaluate(() => closeSettings());
  // the View menu item is the same switch and shows the binding
  const item = await page.evaluate(() => MENUS.view().find((i) => i.t === '高级模式'));
  expect(item.k).toBe('⌃⌘L');
  expect(item.on).toBe(true);
  await page.keyboard.press('Control+Meta+KeyL');
  await expect.poll(() => page.evaluate(() => S.ed)).toBe('lite');
  await page.reload();
  await expect.poll(() => page.evaluate(() => S.ed)).toBe('lite');
  expect(errors).toEqual([]);
});

test('reduced motion swaps editions at once', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openDemo(page);
  await page.evaluate(() => edSet('lite'));
  expect(await ed(page)).toEqual(['lite', 'l-home']);
  expect(errors).toEqual([]);
});

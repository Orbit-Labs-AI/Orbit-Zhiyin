// Native shell commands (apps/desktop/Orbit.swift → orbit:command): a fake host injects __ORBIT_NATIVE__ and records the
// webkit messages; menu commands are dispatched the way the host's dispatch() does.
import { pathToFileURL } from 'node:url';
import { test, expect } from '@playwright/test';
import { ADV_FILE } from './live-helpers.mjs';

const URL0 = pathToFileURL(ADV_FILE).href;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launch(browser, prefs, o) {
  o = o || {};
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.addInitScript(([p, q]) => {
    window.__ORBIT_NATIVE__ = { v: 1, app: '0.0.2', platform: 'macos', features: ['window', 'prefs', 'commands'] };
    window.__ORBIT_PREFS__ = p;
    window.__nativeMsgs = [];
    window.webkit = { messageHandlers: { orbit: { postMessage: (m) => window.__nativeMsgs.push(JSON.parse(JSON.stringify(m))) } } };
  }, [prefs || {}, o.query || '']);
  await page.goto(URL0 + (o.query || ''));
  await page.waitForFunction((surf) => typeof S !== 'undefined' && (surf || !!document.querySelector('#content')), !!o.query);
  return { ctx, page };
}
const cmd = (page, detail) => page.evaluate((d) => window.dispatchEvent(new CustomEvent('orbit:command', { detail: d })), detail);
const at = (page) => page.evaluate(() => [S.ed, S.route]);

test('route command across editions lands on the requested page (Advance → l-recs, Lite → persona)', async ({ browser }) => {
  const { ctx, page } = await launch(browser, { edition: 'advance', route: { advance: 'library' } });
  expect(await at(page)).toEqual(['advance', 'library']);
  await cmd(page, { cmd: 'route', route: 'l-recs' });
  await expect.poll(() => at(page), { timeout: 4000 }).toEqual(['lite', 'l-recs']);
  await sleep(500);
  expect(await at(page)).toEqual(['lite', 'l-recs']);   // no late swap overwrites it

  await cmd(page, { cmd: 'route', route: 'persona' });
  await expect.poll(() => at(page), { timeout: 4000 }).toEqual(['advance', 'persona']);
  await sleep(500);
  expect(await at(page)).toEqual(['advance', 'persona']);

  // same edition: a plain go; a page Lite lacks switches to Advance
  await cmd(page, { cmd: 'route', route: 'tools' });
  await expect.poll(() => at(page)).toEqual(['advance', 'tools']);
  await ctx.close();
});

test('menu commands: pages by number, sidebar toggle, undo state and one action per shortcut', async ({ browser }) => {
  const { ctx, page } = await launch(browser, { edition: 'advance', route: { advance: 'overview' } });
  await cmd(page, { cmd: 'page', n: 3 });
  const third = await page.evaluate(() => navRoutes()[2][0]);
  await expect.poll(() => page.evaluate(() => S.route)).toBe(third);

  const side0 = await page.evaluate(() => S.side);
  await cmd(page, { cmd: 'sidebar' });
  await expect.poll(() => page.evaluate(() => S.side)).toBe(!side0);
  // the page reports the sidebar state so the host can title 显示 / 隐藏侧边栏
  await expect.poll(() => page.evaluate(() => window.__nativeMsgs.filter((m) => m.type === 'menuState').pop()?.sidebar)).toBe(!side0);

  expect(await page.evaluate(() => LVN.canUndo())).toBe(false);

  // the page keydown handled ⇧⌘E; the host's menu item firing right after must not open a second sheet
  let opened = 0;
  await page.exposeFunction('__countReport', () => { opened++; });
  await page.evaluate(() => { const base = openReport; openReport = function () { window.__countReport(); return base.apply(this, arguments); }; });
  await page.keyboard.press('Meta+Shift+KeyE');
  await cmd(page, { cmd: 'report' });
  await sleep(200);
  expect(opened).toBe(1);
  await ctx.close();
});

test('widgets surface renders content even when the in-page widgets setting is off', async ({ browser }) => {
  const { ctx, page } = await launch(browser, { widgets: false }, { query: '?surface=widgets' });
  await page.evaluate(() => { S.widgets = false; render(); });
  await expect(page.locator('#widgets')).toBeVisible();
  const box = await page.locator('#widgets').boundingBox();
  expect(box.height).toBeGreaterThan(120);
  expect(box.width).toBeLessThanOrEqual(364);
  const sizes = await page.evaluate(() => window.__nativeMsgs.filter((m) => m.type === 'resizeSurface').map((m) => m.height));
  expect(Math.max(...sizes)).toBeGreaterThan(120);
  await ctx.close();
});

test('HUD surface reports a width that fits the pill (the panel shrinks to it, no click-eating margin)', async ({ browser }) => {
  const { ctx, page } = await launch(browser, {}, { query: '?surface=hud' });
  await page.evaluate(() => { S.hud.show = true; render(); });
  await sleep(300);
  const last = await page.evaluate(() => window.__nativeMsgs.filter((m) => m.type === 'resizeSurface').pop());
  expect(last && last.height).toBeGreaterThan(30);
  expect(last.height).toBeLessThan(120);
  const pill = await page.locator('#hud > .pill').boundingBox();
  expect(last.width).toBeGreaterThanOrEqual(Math.ceil(pill.width));
  expect(last.width).toBeLessThanOrEqual(Math.ceil(pill.width) + 24);
  await ctx.close();
});

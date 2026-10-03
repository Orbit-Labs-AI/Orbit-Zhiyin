// UI preferences across App launches (native "prefs" feature) and the launch edition / page.
// The fake host injects __ORBIT_NATIVE__ (features incl. "prefs") + __ORBIT_PREFS__ and records webkit messages; the test
// merges the posted {type:'prefs', set} the way apps/desktop/Orbit.swift (UIPrefs) does and "relaunches" with the result.
import { pathToFileURL } from 'node:url';
import { test, expect } from '@playwright/test';
import { ADV_FILE } from './live-helpers.mjs';

const URL0 = pathToFileURL(ADV_FILE).href;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launch(browser, prefs, o) {
  o = o || {};
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.addInitScript(([p, features]) => {
    window.__ORBIT_NATIVE__ = { v: 1, app: '0.0.2', platform: 'macos', features };
    window.__ORBIT_PREFS__ = p;
    window.__nativeMsgs = [];
    window.webkit = { messageHandlers: { tandem: { postMessage: (m) => window.__nativeMsgs.push(JSON.parse(JSON.stringify(m))) } } };
  }, [prefs, o.features || ['window', 'prefs']]);
  await page.goto(URL0 + (o.query || ''));
  await page.waitForFunction((surf) => typeof S !== 'undefined' && (surf || !!document.querySelector('#content')), !!o.query);
  return { ctx, page };
}
// what the host would have on disk after this page's posts
async function merged(page, prefs) {
  await sleep(300);
  const msgs = await page.evaluate(() => window.__nativeMsgs.filter((m) => m.type === 'prefs'));
  const out = Object.assign({}, prefs);
  msgs.forEach((m) => Object.keys(m.set).forEach((k) => { if (m.set[k] == null) delete out[k]; else out[k] = m.set[k]; }));
  return { out, msgs };
}

test('fresh install starts in Lite; relaunch restores edition and each edition’s last page', async ({ browser }) => {
  let { ctx, page } = await launch(browser, {});
  expect(await page.evaluate(() => [S.ed, S.route])).toEqual(['lite', 'l-home']);
  await page.evaluate(() => go('l-persona'));
  let r = await merged(page, {});
  expect(r.msgs.length).toBeGreaterThan(0);
  expect(r.out.route).toEqual({ lite: 'l-persona' });
  await ctx.close();

  // second launch: still Lite, on the persona page; then switch to Advance › tools and quit
  ({ ctx, page } = await launch(browser, r.out));
  expect(await page.evaluate(() => [S.ed, S.route])).toEqual(['lite', 'l-persona']);
  await page.evaluate(() => { edOpen('tools'); });
  r = await merged(page, r.out);
  expect(r.out.edition).toBe('advance');
  expect(r.out.route).toEqual({ lite: 'l-persona', advance: 'tools' });
  await ctx.close();

  // third launch: Advance › tools; other prefs survive too (theme, page guide closed)
  ({ ctx, page } = await launch(browser, Object.assign({}, r.out, { theme: 'dark', guideOff: true })));
  expect(await page.evaluate(() => [S.ed, S.route, S.theme])).toEqual(['advance', 'tools', 'dark']);
  expect(await page.locator('.pg-guide').count()).toBe(0);
  await ctx.close();

  // back to Lite from the stored edition: lands on Lite's own last page
  ({ ctx, page } = await launch(browser, Object.assign({}, r.out, { edition: 'lite' })));
  expect(await page.evaluate(() => [S.ed, S.route])).toEqual(['lite', 'l-persona']);
  await ctx.close();
});

test('store.set posts merged keys; null deletes; other surfaces never write the route', async ({ browser }) => {
  let { ctx, page } = await launch(browser, { theme: 'light' });
  await page.evaluate(() => { store.set('range', 7); store.set('range', 30); store.set('theme', null); });
  const r = await merged(page, { theme: 'light' });
  const last = r.msgs[r.msgs.length - 1].set;
  expect(last.range).toBe(30);
  expect(last.theme).toBeNull();
  expect(r.out.theme).toBeUndefined();
  // another surface's change arrives as tandem:prefs and updates this page's copy
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('tandem:prefs', { detail: { set: { wgSize: 'l' } } })));
  expect(await page.evaluate(() => store.get('wgSize', 'm'))).toBe('l');
  await ctx.close();

  ({ ctx, page } = await launch(browser, { edition: 'advance', route: { advance: 'sessions' } }, { query: '?surface=widgets' }));
  await page.evaluate(() => go('persona'));
  const w = await merged(page, {});
  expect(w.msgs.some((m) => 'route' in m.set)).toBe(false);
  await ctx.close();
});

test('browser (no prefs feature) keeps localStorage, Advance and no native posts', async ({ browser }) => {
  const { ctx, page } = await launch(browser, { edition: 'lite' }, { features: ['window'] });
  expect(await page.evaluate(() => [store.native, S.ed, S.route])).toEqual([false, 'advance', 'overview']);
  await page.evaluate(() => { store.set('range', 7); go('tools'); });
  await sleep(250);
  expect(await page.evaluate(() => [window.__nativeMsgs.filter((m) => m.type === 'prefs').length, localStorage.getItem('tandem-demo:range')])).toEqual([0, '7']);
  await ctx.close();
});

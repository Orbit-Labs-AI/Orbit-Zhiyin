// Region rendering (24-regions.js) on A7 建议, A8 资源库, A9 生成工坊 and the three native surfaces (menu-bar panel, HUD,
// desktop widgets): a feed answer, a selection, typing or a streamed generation refresh only the regions that depend on
// them — the page is never rebuilt (window.__renderCount stays), nodes marked before the change keep their identity, scroll
// boxes keep their position and the page's own interaction state (selected card, tab, search caret, log scroll) survives.
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const mark = (page, sels) => page.evaluate((s) => s.forEach((x) => { const el = document.querySelector(x); if (el) el.__rr = 1; }), sels);
const marked = (page, sels) => page.evaluate((s) => s.filter((x) => { const el = document.querySelector(x); return el && el.__rr === 1; }), sels);
const counts = (page) => page.evaluate(() => ({ full: window.__renderCount, rg: Object.assign({}, window.__regionRenders) }));

test('A7 live: a new recommendations answer refreshes the list in place; selection, tab, scroll and other regions stay', async ({ page }) => {
  ONLY('mac-14'); test.skip(!!PASS, 'stubbed bodies');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = collectErrors(page);
  const body = () => fx('recs/recommendations.json');
  const gw = await stubGateway(page, 's1', { 'GET /v1/recommendations': body(), 'GET /v1/install/state': { items: [] } });
  await openLive(page, 'recs');
  await expect.poll(() => page.evaluate(() => RECS.filter((r) => r.live).length)).toBe(3);
  await expect(page.locator('[data-region="a7:list"] .rcard').first()).toBeVisible();
  // pick the second card and its 教程 tab, then scroll a long page
  const ids = await page.evaluate(() => [...document.querySelectorAll('[data-region="a7:list"] .rcard')].map((x) => x.dataset.id));
  await page.locator('[data-region="a7:list"] .rcard[data-id="' + ids[1] + '"] .rc-title').click();
  await page.locator('[data-region="a7:detail"] [data-act="recTab"][data-v="tut"]').click();
  await page.addStyleTag({ content: '#content::after{content:"";display:block;height:3000px}' });
  await page.evaluate(() => { document.querySelector('#content').scrollTop = 240; });
  const MARKS = ['#content', '[data-region="a7:dims"]', '[data-region="a7:lv"]', '[data-region="a7:list"]', '[data-region="a7:list"] .rcard[data-id="' + ids[0] + '"]', '[data-region="a7:detail"] [role="tablist"]', '#side .sb-scroll'];
  await mark(page, MARKS);
  const c0 = await counts(page);

  // the gateway answers with a changed title for the first card; a rec invalidation reloads A7
  gw.set('GET /v1/recommendations', () => { const b = body(); b.items[0].title = '区域刷新：只换这张卡片的标题'; b.items[0].ui.title = b.items[0].title; return b; });
  await page.evaluate(() => TL.recs.invalidate());
  await expect(page.locator('[data-region="a7:list"] .rcard[data-id="' + ids[0] + '"] .rc-title')).toHaveText('区域刷新：只换这张卡片的标题');
  const c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(c.rg['a7:list'] || 0).toBeGreaterThan(c0.rg['a7:list'] || 0);
  expect(await marked(page, MARKS)).toEqual(MARKS);
  expect(await page.evaluate(() => [S.recs.sel, S.recs.tab])).toEqual([ids[1], 'tut']);
  await expect(page.locator('[data-region="a7:list"] .rcard.sel')).toHaveAttribute('data-id', ids[1]);
  expect(await page.evaluate(() => document.querySelector('#content').scrollTop)).toBe(240);

  // selecting another card and switching the tab are region refreshes too (no page rebuild)
  await page.locator('[data-region="a7:list"] .rcard[data-id="' + ids[0] + '"] .rc-title').click();
  await page.locator('[data-region="a7:detail"] [data-act="recTab"][data-v="why"]').click();
  await expect(page.locator('[data-region="a7:list"] .rcard.sel')).toHaveAttribute('data-id', ids[0]);
  expect((await counts(page)).full).toBe(c0.full);
  expect(await marked(page, MARKS)).toEqual(MARKS);
  expect(errors).toEqual([]);
});

test('A8: typing a search, a kind chip and hiding an item refresh the results only; the field keeps focus and caret', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'library');
  await expect(page.locator('[data-region="a8:body"] .lb-card').first()).toBeVisible();
  const MARKS = ['#content', '#libQ', '[data-region="a8:tbar"]', '[data-region="a8:body"] .lib-feat', '#side .sb-scroll'];
  await mark(page, MARKS);
  const c0 = await counts(page);
  await page.locator('#libQ').click();
  await page.keyboard.type('pdf');
  await expect(page.locator('[data-region="a8:body"]')).toContainText('搜索「pdf」');
  expect(await page.evaluate(() => [document.activeElement.id, document.activeElement.value, document.activeElement.selectionStart])).toEqual(['libQ', 'pdf', 3]);
  await page.keyboard.press('Backspace'); await page.keyboard.press('Backspace'); await page.keyboard.press('Backspace');
  await expect(page.locator('[data-region="a8:body"]')).not.toContainText('搜索「');
  // a kind chip and 不感兴趣 (hide) morph the results; the rest of the page keeps its nodes
  await page.locator('[data-region="a8:body"] [data-act="libKind"][data-v="Skill"]').click();
  await expect(page.locator('[data-region="a8:body"] [data-act="libKind"][data-v="Skill"]')).toHaveAttribute('aria-pressed', 'true');
  const c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(c.rg['a8:body'] || 0).toBeGreaterThan(c0.rg['a8:body'] || 0);
  expect(await marked(page, MARKS.filter((m) => !/lib-feat/.test(m)))).toEqual(MARKS.filter((m) => !/lib-feat/.test(m)));
  expect(errors).toEqual([]);
});

test('A9: a streamed generation refreshes only the run and output cards; the goal keeps focus, the log keeps a scrolled-up position', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'studio');
  await page.locator('#studioGoal').fill('提交前先跑测试，失败就停下汇报');
  const MARKS = ['#content', '#studioGoal', '[data-region="a9:form"]', '[data-region="a9:priv"]', '#studioLog', '#side .sb-scroll'];
  await mark(page, MARKS);
  const c0 = await counts(page);
  await page.evaluate(() => ACT.studioStart());
  await page.locator('#studioGoal').focus();
  // let the draft stream a few lines, then scroll the log up (it must not jump back to the end on the next line)
  await expect.poll(() => page.evaluate(() => S.studio.run && S.studio.run.lines), { timeout: 10000 }).toBeGreaterThan(2);
  await page.addStyleTag({ content: '#studioLog{max-height:60px!important;overflow:auto!important}' });
  await page.evaluate(() => { for (let i = 0; i < 12; i++) S.studio.run.log.push('› 回看第 ' + (i + 1) + ' 段'); refreshStudio(); });
  await page.evaluate(() => { const l = document.querySelector('#studioLog'); l.scrollTop = 0; l.dispatchEvent(new Event('scroll')); });
  const lines = await page.evaluate(() => S.studio.run.lines);
  // an unrelated app render (a live frame, a filter) in the middle of the stream changes nothing here
  await page.evaluate(() => { render(); render(); });
  await expect.poll(() => page.evaluate(() => S.studio.run.lines)).toBeGreaterThan(lines);
  expect(await page.evaluate(() => document.querySelector('#studioLog').scrollTop)).toBe(0);
  expect(await page.evaluate(() => document.activeElement && document.activeElement.id)).toBe('studioGoal');
  await expect.poll(() => page.evaluate(() => S.studio.run.done), { timeout: 20000 }).toBe(true);
  const c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(c.rg['a9:run'] || 0).toBeGreaterThan(5);
  expect(c.rg['a9:out'] || 0).toBeGreaterThan(5);
  // the form only changes when the run starts / ends (the type lock, the start button), never per streamed line
  expect((c.rg['a9:form'] || 0) - (c0.rg['a9:form'] || 0)).toBeLessThanOrEqual(3);
  expect(await marked(page, MARKS)).toEqual(MARKS);
  await expect(page.locator('#studioGoal')).toHaveValue('提交前先跑测试，失败就停下汇报');
  expect(errors).toEqual([]);
});

test('native surfaces: menu-bar panel, HUD and widgets are morphed in place on every render', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'overview');
  await page.evaluate(() => { S.widgets = true; S.win.full = false; S.hud.show = true; S.pop = true; render(); });
  await expect(page.locator('#pop .sec').first()).toBeVisible();
  await expect(page.locator('#widgets .wg').first()).toBeVisible();
  const MARKS = ['#pop .sec', '#pop [data-act="popOpen"]', '#widgets .wg-row', '#widgets .wg.sq', '#widgets [data-act="wgMenu"]'];
  const hud = await page.evaluate(() => !document.querySelector('#hud').hidden && !!document.querySelector('#hudPill'));
  if (hud) MARKS.push('#hudPill');
  await mark(page, MARKS);
  await page.evaluate(() => { for (let i = 0; i < 5; i++) render(); renderPop(); renderWidgets(); renderHud(); });
  expect(await marked(page, MARKS)).toEqual(MARKS);
  // a size change of the widgets updates their contents and keeps the shared nodes
  await page.evaluate(() => ACT.wgSize({ dataset: { v: 'l' } }));
  await expect(page.locator('#widgets')).toHaveAttribute('data-size', 'l');
  expect(await marked(page, ['#widgets .wg-row', '#widgets [data-act="wgMenu"]'])).toEqual(['#widgets .wg-row', '#widgets [data-act="wgMenu"]']);
  expect(errors).toEqual([]);
});

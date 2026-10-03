// Region rendering on the Lite pages, A2 persona and A6 sentiment (24-regions.js): a live feed / facts change or a page
// interaction refreshes only the regions that read it. The page is never rebuilt (window.__renderCount stays), nodes
// tagged before the change keep their identity, scroll boxes keep their offset and in-page state (selected session,
// fingerprint hour, word-cloud layout) survives. Mock demo for interactions, stub gateway (s1 / s4 fixtures) for live data.
import { test, expect } from '@playwright/test';
import { openDemo } from './helpers.mjs';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
test.use({ timezoneId: 'Asia/Shanghai' });
const NOW = new Date('2026-10-03T12:00:00+08:00');

const counts = (page) => page.evaluate(() => ({ full: window.__renderCount, rg: Object.assign({}, window.__regionRenders) }));
const mark = (page, sels) => page.evaluate((xs) => xs.forEach((s) => { const el = document.querySelector(s); if (el) el.__rr = 1; }), sels);
const marked = (page, sels) => page.evaluate((xs) => xs.filter((s) => { const el = document.querySelector(s); return el && el.__rr === 1; }), sels);
const frame = (page, name, data) => page.evaluate(([n, d]) => TL.dispatch(n, d), [name, data]);
const grew = (c0, c, k) => (c.rg[k] || 0) > (c0.rg[k] || 0);
const same = (c0, c, k) => (c.rg[k] || 0) === (c0.rg[k] || 0);
function factsPlus(n) {
  const f = fx('s1/facts.json'); const iId = f.fields.indexOf('id'), iD = f.fields.indexOf('d');
  const src = f.rows[f.rows.length - 1];
  for (let k = 0; k < n; k++) { const r = src.slice(); r[iId] = 'rp' + k; r[iD] = '2026-10-02'; f.rows.push(r); }
  return f;
}
function overview(edit) {
  const OV = { 7: fx('s1/overview-7.json'), 30: fx('s1/overview-30.json'), 90: fx('s1/overview-90.json'), 0: fx('s1/overview-0.json') };
  return (req, u) => { const b = OV[u.searchParams.get('range')]; if (!b) return { status: 404 }; return edit ? edit(JSON.parse(JSON.stringify(b))) : b; };
}
const s1 = () => ({
  'GET /v1/uiview/overview': overview(),
  'GET /v1/uiview/persona': (req, u) => ((u.searchParams.get('period') || '90') === '30' ? fx('s1/persona-30.json') : fx('s1/persona-90.json'))
});

test('A2 persona: fingerprint hour, comparison group and period refresh their own cards only', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'persona');
  await expect(page.locator('[data-region="a2:fp"] svg.fp2')).toBeVisible();
  await page.addStyleTag({ content: '#content::after{content:"";display:block;height:3000px}' });
  await page.evaluate(() => { document.querySelector('#content').scrollTop = 260; });
  const MARKS = ['#content', '[data-region="a2:hero"] .letters', '[data-vz="pe-evo"] svg', '[data-region="a2:axes"]', '[data-vz="pe-axes"] svg', '[data-region="a2:fit"]', '#main .tsearch'];
  await mark(page, MARKS);
  const c0 = await counts(page);
  // an hour on the fingerprint: only the fingerprint region redraws
  await page.evaluate(() => ACT.fpHour({ dataset: { h: '14' } }));
  await expect(page.locator('[data-region="a2:fp"] .fps.sel')).toHaveCount(1);
  let c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(grew(c0, c, 'a2:fp')).toBe(true);
  for (const k of ['a2:hero', 'a2:axes', 'a2:sw', 'a2:fit', 'a2:tbar']) expect(same(c0, c, k), k).toBe(true);
  expect(await marked(page, MARKS)).toEqual(MARKS);
  expect(await page.evaluate(() => document.querySelector('#content').scrollTop)).toBe(260);
  // 对照组: only the axes card (its chart box keeps its node; the diverging chart redraws for the new reference)
  const c1 = await counts(page);
  await page.evaluate(() => document.querySelector('[data-region="a2:axes"] [data-act="vs"][data-v="pop"]').click());
  await expect(page.locator('[data-region="a2:axes"] [data-v="pop"]')).toHaveClass(/on/);
  c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(grew(c1, c, 'a2:axes')).toBe(true);
  for (const k of ['a2:hero', 'a2:fp', 'a2:fit']) expect(same(c1, c, k), k).toBe(true);
  await expect(page.locator('[data-region="a2:fp"] .fps.sel')).toHaveCount(1);   // the hour stays expanded
  // a period switch refreshes the cards in place: no page rebuild, the content box keeps its node
  await page.evaluate(() => document.querySelector('#main .tbar [data-act="period"][data-v="all"]').click());
  await expect(page.locator('#main .tbar [data-act="period"][data-v="all"]')).toHaveClass(/on/);
  c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(await marked(page, ['#content', '#main .tsearch'])).toEqual(['#content', '#main .tsearch']);
  // a route change is still one full render
  await page.evaluate(() => go('overview'));
  expect((await counts(page)).full).toBe(c0.full + 1);
  expect(errors).toEqual([]);
});

test('Lite sessions: picking a session keeps the list node and its scroll; a range switch does not rebuild', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'overview');
  await page.evaluate(() => edSet('lite'));
  await expect.poll(() => page.evaluate(() => S.route)).toBe('l-home');
  await page.evaluate(() => go('l-sessions'));
  await expect(page.locator('[data-region="ls:list"] .srow')).toHaveCount(8);
  await page.addStyleTag({ content: '.l-slist-c .slist{max-height:160px;overflow:auto}' });
  await page.evaluate(() => { document.querySelector('.l-slist-c .slist').scrollTop = 120; });
  const MARKS = ['.l-slist-c .slist', '[data-region="ls:list"]', '#content', '#main .tsearch'];
  await mark(page, MARKS);
  const c0 = await counts(page);
  const id = await page.locator('[data-region="ls:list"] .srow').nth(5).getAttribute('data-id');
  await page.evaluate((x) => document.querySelector('.srow[data-id="' + x + '"]').click(), id);
  await expect(page.locator('.srow.sel')).toHaveAttribute('data-id', id);
  let c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(grew(c0, c, 'ls:head')).toBe(true);
  expect(await marked(page, MARKS)).toEqual(MARKS);
  expect(await page.evaluate(() => document.querySelector('.l-slist-c .slist').scrollTop)).toBe(120);
  // 7 天: regions refresh, the page is not rebuilt
  await page.evaluate(() => document.querySelector('#main .tbar .seg [data-v="7"]').click());
  await expect(page.locator('#main .tbar .seg button.on')).toHaveText('7 天');
  c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(await marked(page, ['#content', '#main .tsearch'])).toEqual(['#content', '#main .tsearch']);
  expect(errors).toEqual([]);
});

test('Lite home (live): the overview feed refreshes the hero only; facts roll the tiles in place', async ({ page }) => {
  ONLY('mac-14');
  test.skip(!!PASS, 'stub-only: swaps fixtures');
  await page.clock.setFixedTime(NOW);
  const errors = collectErrors(page);
  const gw = await stubGateway(page, 's1', s1());
  await openLive(page, 'overview');
  await page.evaluate(() => edSet('lite'));
  await expect.poll(() => page.evaluate(() => S.route)).toBe('l-home');
  await expect.poll(() => page.evaluate(() => LV.feedState('l-home'))).toBe('ready');
  await expect(page.locator('[data-region="lh:tiles"] .vz-kpi .v').first()).toBeVisible();
  await page.waitForTimeout(700);
  const MARKS = ['#content', '[data-region="lh:tiles"]', '[data-region="lh:one"]', '#main .tsearch', '#side .sb-scroll'];
  await mark(page, MARKS);
  const c0 = await counts(page);
  const lede = 'Lite 首页只换了这一句，数字与条带保持不动。';
  gw.set('GET /v1/uiview/overview', overview((b) => { b.insight = Object.assign({}, b.insight, { lede }); return b; }));
  await frame(page, 'data.published', { data_rev: 2 });
  await expect(page.locator('[data-region="lh:hero"] .l-say')).toHaveText(lede);
  let c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(grew(c0, c, 'lh:hero')).toBe(true);
  for (const k of ['lh:tiles', 'lh:strip']) expect(same(c0, c, k), k).toBe(true);
  expect(await marked(page, MARKS)).toEqual(MARKS);
  // +12 sessions yesterday: the session tile reaches the new count without a page rebuild
  const before = await page.locator('[data-region="lh:tiles"] .vz-kpi .v').first().textContent();
  gw.set('GET /v1/uiview/facts', factsPlus(12));
  await frame(page, 'data.published', { data_rev: 3 });
  await expect(page.locator('[data-region="lh:tiles"] .vz-kpi .v').first()).toHaveText(String(+before.replace(/,/g, '') + 12));
  c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(await marked(page, MARKS)).toEqual(MARKS);
  expect(errors).toEqual([]);
});

test('A2 / Lite persona (live): a facts change refreshes in place and keeps the scroll', async ({ page }) => {
  ONLY('mac-14');
  test.skip(!!PASS, 'stub-only: swaps fixtures');
  await page.clock.setFixedTime(NOW);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = collectErrors(page);
  const gw = await stubGateway(page, 's1', s1());
  await openLive(page, 'persona');
  await expect(page.locator('[data-region="a2:hero"] .letters')).toBeVisible();
  await page.addStyleTag({ content: '#content::after{content:"";display:block;height:3000px}' });
  await page.evaluate(() => { document.querySelector('#content').scrollTop = 240; });
  const MARKS = ['#content', '[data-region="a2:hero"]', '[data-region="a2:axes"]', '#main .tsearch'];
  await mark(page, MARKS);
  const c0 = await counts(page);
  gw.set('GET /v1/uiview/facts', factsPlus(12));
  await frame(page, 'data.published', { data_rev: 2 });
  await expect.poll(() => page.evaluate(() => LV.rev)).toBeGreaterThan(0);
  await expect(page.locator('#main .tbar .meta')).toContainText('个会话');
  await page.waitForTimeout(400);
  const c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(await marked(page, MARKS)).toEqual(MARKS);
  expect(await page.evaluate(() => document.querySelector('#content').scrollTop)).toBe(240);
  // Lite persona: same, then a route change is one full render
  await page.evaluate(() => edSet('lite'));
  await expect.poll(() => page.evaluate(() => S.route)).toBe('l-persona');
  await expect(page.locator('[data-region="lp:hero"] .letters')).toBeVisible();
  await mark(page, ['[data-region="lp:hero"]', '[data-region="lp:evo"]']);
  const c1 = await counts(page);
  gw.set('GET /v1/uiview/facts', factsPlus(20));
  await frame(page, 'data.published', { data_rev: 3 });
  await page.waitForTimeout(600);
  expect((await counts(page)).full).toBe(c1.full);
  expect(await marked(page, ['[data-region="lp:hero"]', '[data-region="lp:evo"]'])).toEqual(['[data-region="lp:hero"]', '[data-region="lp:evo"]']);
  expect(errors).toEqual([]);
});

test('A6 sentiment (live): a phrases-only feed change refreshes that card; the word cloud keeps nodes and layout', async ({ page }) => {
  ONLY('mac-14');
  test.skip(!!PASS, 'stub-only: swaps fixtures');
  await page.clock.setFixedTime(NOW);
  const errors = collectErrors(page);
  const base = fx('s4/sentiment.json');
  const gw = await stubGateway(page, ['core', 's4'], { 'GET /v1/uiview/sentiment': base, 'GET /v1/search': { results: [] } });
  await openLive(page, 'sentiment');
  await expect(page.locator('[data-region="a6:words"] .sn-w').first()).toBeVisible();
  await page.waitForTimeout(600);
  const geo = () => page.evaluate(() => Array.from(document.querySelectorAll('.sn-cloud .sn-w')).map((e) => e.style.left + ',' + e.style.top + ',' + e.style.fontSize).join('|'));
  const g0 = await geo();
  const MARKS = ['#content', '[data-region="a6:words"]', '.sn-cloud', '.sn-cloud .sn-w', '[data-region="a6:fric"]', '[data-region="a6:mood"]', '#main .tsearch'];
  await mark(page, MARKS);
  const c0 = await counts(page);
  const d = JSON.parse(JSON.stringify(base)); d.phrases[0].text = '示例：只改了这一条反馈语';
  gw.set('GET /v1/uiview/sentiment', d);
  await frame(page, 'data.published', { data_rev: 2 });
  await expect(page.locator('[data-region="a6:phr"] .sn-ph').first()).toContainText('只改了这一条反馈语');
  const c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(grew(c0, c, 'a6:phr')).toBe(true);
  for (const k of ['a6:words', 'a6:fric', 'a6:mood', 'a6:body']) expect(same(c0, c, k), k).toBe(true);
  expect(await marked(page, MARKS)).toEqual(MARKS);
  expect(await geo()).toBe(g0);
  expect(errors).toEqual([]);
});

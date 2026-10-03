// Region rendering (24-regions.js): on the overview, live data (facts, the overview feed), import progress frames and a
// range switch refresh only the regions that depend on them — never the whole page. Untouched nodes keep their identity
// (marked before the change), the sidebar and content keep their scroll, an open Agent dropdown stays open, numbers roll
// from the old value to the new one (and jump straight to it under reduced motion). Stub gateway, s1 fixtures.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
test.skip(!!PASS, 'stub-only: swaps fixtures and feeds synthetic frames');
test.use({ timezoneId: 'Asia/Shanghai' });
const NOW = new Date('2026-10-03T12:00:00+08:00');
const JOB = '10951bad4daa4a2fb0994de1f0d61e09';

// facts + n extra sessions dated yesterday (cloned from the newest row, new ids)
function factsPlus(n) {
  const f = fx('s1/facts.json'); const iId = f.fields.indexOf('id'), iD = f.fields.indexOf('d');
  const src = f.rows[f.rows.length - 1];
  for (let k = 0; k < n; k++) { const r = src.slice(); r[iId] = 'rr' + k; r[iD] = '2026-10-02'; f.rows.push(r); }
  return f;
}
function overview(edit) {
  const OV = { 7: fx('s1/overview-7.json'), 30: fx('s1/overview-30.json'), 90: fx('s1/overview-90.json'), 0: fx('s1/overview-0.json') };
  return (req, u) => { const r = u.searchParams.get('range'); const b = OV[r]; if (!b) return { status: 404 }; return edit ? edit(JSON.parse(JSON.stringify(b))) : b; };
}
const routes = () => ({
  'GET /v1/uiview/overview': overview(),
  'GET /v1/uiview/persona': (req, u) => ((u.searchParams.get('period') || '90') === '30' ? fx('s1/persona-30.json') : fx('s1/persona-90.json'))
});
const frame = (page, name, data) => page.evaluate(([n, d]) => TL.dispatch(n, d), [name, data]);
const job = (done, total) => ({ id: JOB, kind: 'import', status: 'running', progress: { stage: 'backfill', completed: done, total } });

async function setup(page, reduce) {
  await page.clock.setFixedTime(NOW);
  if (reduce) await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = collectErrors(page);
  const gw = await stubGateway(page, 's1', routes());
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  await expect.poll(() => page.evaluate(() => LV.feedState('overview'))).toBe('ready');
  await expect(page.locator('[data-region="a1:kpi"] .vz-kpi .v').first()).toBeVisible();
  await page.waitForTimeout(700);   // the enter count-up settles
  return { errors, gw };
}
// tag nodes that must survive; returns the list of selectors still carrying their tag
const MARKS = ['#main .tsearch', '#side .edsw', '[data-region="a1:kpi"]', '[data-region="a1:heat"]', '[data-region="a1:trend"] .seg', '[data-vz="ov-trend"] svg', '[data-region="a1:recs"]', '#content', '#side .sb-scroll', '[data-region="side:agents"]'];
// the chart's own svg is redrawn by vizkit when its data changes (facts, range): checked only where the data stays
const CHART = '[data-vz="ov-trend"] svg';
const STABLE = MARKS.filter((m) => m !== CHART);
const mark = (page) => page.evaluate((sels) => sels.forEach((s) => { const el = document.querySelector(s); if (el) el.__rr = 1; }), MARKS);
const marked = (page) => page.evaluate((sels) => sels.filter((s) => { const el = document.querySelector(s); return el && el.__rr === 1; }), MARKS);
// every text the first KPI value shows from now on
const watchTile = (page) => page.evaluate(() => {
  window.__tile = []; const el = document.querySelector('[data-region="a1:kpi"] .vz-kpi .v');
  window.__tile.push(el.textContent);
  new MutationObserver(() => { const t = document.querySelector('[data-region="a1:kpi"] .vz-kpi .v').textContent; if (window.__tile[window.__tile.length - 1] !== t) window.__tile.push(t); })
    .observe(document.querySelector('[data-region="a1:kpi"]'), { subtree: true, childList: true, characterData: true });
});
const counts = (page) => page.evaluate(() => ({ full: window.__renderCount, rg: Object.assign({}, window.__regionRenders) }));

test('live facts, the overview feed, 20 import frames and a range switch refresh regions only', async ({ page }) => {
  ONLY('mac-14');
  const { errors, gw } = await setup(page, false);
  // a long page and a short sidebar list, both scrolled; then the Agent dropdown opens
  await page.addStyleTag({ content: '#content::after{content:"";display:block;height:3000px} #side .sb-scroll{max-height:120px}' });
  await page.evaluate(() => { document.querySelector('#content').scrollTop = 300; document.querySelector('#side .sb-scroll').scrollTop = 30; });
  await page.waitForTimeout(50);
  const scroll = () => page.evaluate(() => [document.querySelector('#content').scrollTop, document.querySelector('#side .sb-scroll').scrollTop]);
  const s0 = await scroll(); expect(s0[0]).toBe(300); expect(s0[1]).toBeGreaterThan(0);
  await page.evaluate(() => document.querySelector('#main [data-act="agentMenu"]').click());
  await expect(page.locator('#dd')).toBeVisible();
  await mark(page);
  const c0 = await counts(page);

  // 1) the overview feed changes (insight text only): the AI card refreshes, tiles / heat / trend do not
  gw.set('GET /v1/uiview/overview', overview((b) => { b.insight = Object.assign({}, b.insight, { lede: '区域刷新只换了这一句，其余内容与滚动位置都保持不动。' }); return b; }));
  await frame(page, 'data.published', { data_rev: 2 });
  await expect(page.locator('#aiLead')).toHaveText('区域刷新只换了这一句，其余内容与滚动位置都保持不动。');
  let c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(c.rg['a1:ai'] || 0).toBeGreaterThan(c0.rg['a1:ai'] || 0);
  for (const k of ['a1:kpi', 'a1:heat', 'a1:trend']) expect(c.rg[k] || 0, k).toBe(c0.rg[k] || 0);
  expect(await marked(page)).toEqual(MARKS);
  await expect(page.locator('#dd')).toBeVisible();
  expect(await scroll()).toEqual(s0);

  // 2) facts change (+12 sessions yesterday): the tiles roll from the old count to the new one, the page is not rebuilt
  const before = await page.locator('[data-region="a1:kpi"] .vz-kpi .v').first().textContent();
  await watchTile(page);
  gw.set('GET /v1/uiview/facts', factsPlus(12));
  await frame(page, 'data.published', { data_rev: 3 });
  const want = String(+before.replace(/,/g, '') + 12);
  await expect(page.locator('[data-region="a1:kpi"] .vz-kpi .v').first()).toHaveText(want);
  const seq = await page.evaluate(() => window.__tile);
  expect(seq[0]).toBe(before);
  expect(seq[seq.length - 1]).toBe(want);
  expect(seq.some((t) => +t > +before && +t < +want), 'intermediate values: ' + seq.join(' → ')).toBe(true);
  c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect((await marked(page)).filter((m) => m !== CHART)).toEqual(STABLE);
  await expect(page.locator('#dd')).toBeVisible();
  expect(await scroll()).toEqual(s0);

  // 3) 20 import progress frames: only the sidebar import entry and the progress strip move
  await mark(page);   // re-tag the redrawn chart
  const c1 = await counts(page);
  for (let i = 1; i <= 20; i++) { await frame(page, 'job', job(i, 40)); await page.waitForTimeout(40); }
  await expect(page.locator('#side [data-side="import"]')).toContainText('50%');
  c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(c.rg['side:import'] || 0).toBeGreaterThan(c1.rg['side:import'] || 0);
  for (const k of ['a1:kpi', 'a1:heat', 'a1:trend', 'a1:ai', 'side:agents']) expect(c.rg[k] || 0, k).toBe(c1.rg[k] || 0);
  expect(await marked(page)).toEqual(MARKS);
  await expect(page.locator('#dd')).toBeVisible();
  expect(await scroll()).toEqual(s0);

  // 4) a range switch (7 天): tiles and charts refresh in place, the page is not rebuilt, the scroll stays
  await page.keyboard.press('Escape');
  await page.evaluate(() => document.querySelector('#main .frow .seg [data-v="7"]').click());
  await expect(page.locator('#main .frow .seg button.on')).toHaveText('7 天');
  await expect(page.locator('#main .tbar .meta')).toContainText('个会话');
  c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(c.rg['a1:kpi']).toBeGreaterThan(c1.rg['a1:kpi'] || 0);
  expect((await marked(page)).filter((m) => m !== CHART)).toEqual(STABLE);
  // the range changes card heights above the fold: the same #content box keeps its scroll (browser scroll anchoring may
  // shift it by those few px to hold the visible content still), it is never reset to the top
  expect(Math.abs((await scroll())[0] - 300)).toBeLessThan(40);
  // a route change is still a full render
  await page.evaluate(() => go('persona'));
  expect((await counts(page)).full).toBe(c0.full + 1);
  expect(errors).toEqual([]);
});

test('reduced motion: a refreshed tile shows the new value at once', async ({ page }) => {
  ONLY('mac-14');
  const { errors, gw } = await setup(page, true);
  const before = await page.locator('[data-region="a1:kpi"] .vz-kpi .v').first().textContent();
  const n0 = await page.evaluate(() => window.__renderCount);
  await watchTile(page);
  gw.set('GET /v1/uiview/facts', factsPlus(12));
  await frame(page, 'data.published', { data_rev: 2 });
  const want = String(+before.replace(/,/g, '') + 12);
  await expect(page.locator('[data-region="a1:kpi"] .vz-kpi .v').first()).toHaveText(want);
  expect(await page.evaluate(() => window.__tile)).toEqual([before, want]);
  expect(await page.evaluate(() => window.__renderCount)).toBe(n0);
  expect(errors).toEqual([]);
});

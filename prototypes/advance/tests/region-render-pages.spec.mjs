// Region rendering (24-regions.js) on A3 sessions, A4 tools and A5 projects: a live feed update refreshes only the regions
// reading that feed. The page is never rebuilt (__renderCount stays), unrelated regions keep their node identity (tagged
// before the change), long lists and the content keep their scroll, and page state — a running replay, the search field
// with focus, an expanded tool row, the selected project — survives. Stub gateway, core + s2 / s3 fixtures.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';
import { openDemo, go } from './helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
test.skip(!!PASS, 'stub-only: swaps fixtures mid-test');
const NOW = new Date('2026-10-03T12:00:00+08:00');
const clone = (o) => JSON.parse(JSON.stringify(o));
const frame = (page, name, data) => page.evaluate(([n, d]) => TL.dispatch(n, d), [name, data]);
const counts = (page) => page.evaluate(() => ({ full: window.__renderCount, rg: Object.assign({}, window.__regionRenders) }));
const mark = (page, sels) => page.evaluate((ss) => ss.forEach((s) => { const el = document.querySelector(s); if (el) el.__rr = 1; }), sels);
const marked = (page, sels) => page.evaluate((ss) => ss.filter((s) => { const el = document.querySelector(s); return el && el.__rr === 1; }), sels);
const unchanged = (c0, c, keys) => keys.forEach((k) => expect(c.rg[k] || 0, k).toBe(c0.rg[k] || 0));

test.beforeEach(async ({ page }) => { ONLY('mac-14'); await page.clock.setFixedTime(NOW); });

test('A3: a list feed update refreshes the list only; the replay, list scroll and search focus survive', async ({ page }) => {
  const errors = collectErrors(page);
  const LIST = fx('s2/list.json');
  const route = (list) => (req, u) => (u.searchParams.get('q') ? { meta: list.meta, days: [], rows: [], total: 0, next_offset: null } : list);
  const gw = await stubGateway(page, ['core', 's2'], { 'GET /v1/uiview/sessions': route(LIST) });
  await openLive(page, 'sessions');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  await expect(page.locator('#tlBox svg.vz-svg')).toHaveCount(1);
  await expect(page.locator('.tl-sum')).not.toHaveAttribute('data-lv', /.*/);
  const A = await page.evaluate(() => S.sess.sel);
  const bar = () => page.evaluate((a) => document.querySelector('.srow[data-id="' + a + '"] svg[preserveAspectRatio="none"] path').getAttribute('d'), A);
  await expect.poll(bar).toContain('M');
  const d0 = await bar();
  // a short, scrolled list
  await page.addStyleTag({ content: '#slist{max-height:140px;overflow:auto}' });
  await page.evaluate(() => { document.querySelector('#slist').scrollTop = 40; });
  const top0 = await page.evaluate(() => document.querySelector('#slist').scrollTop);
  expect(top0).toBeGreaterThan(0);
  const MARKS = ['#main .tbar', '[data-region="a3:list"]', '#slist', '#sessQ', '[data-region="a3:band"]', '[data-region="a3:tl"]', '#tlBox', '#tlBox svg.vz-svg', '.tl-mom', '[data-region="a3:ins"]', '#content'];
  await mark(page, MARKS);
  const c0 = await counts(page);

  // 1) replay running: the list feed changes (new barcode ticks for the selected session)
  await page.evaluate(() => ACT.playToggle());
  expect(await page.evaluate(() => S.sess.playing)).toBe(true);
  const L2 = clone(LIST); L2.rows.find((r) => r.id === A).ticks = { t: [0.5], e: [] };
  gw.set('GET /v1/uiview/sessions', route(L2));
  await frame(page, 'data.published', { data_rev: 2 });
  await expect.poll(bar).not.toBe(d0);
  expect(await bar()).toBe('M' + (0.5 * 280).toFixed(1) + ' 1V7');
  let c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(c.rg['a3:list'] || 0).toBeGreaterThan(c0.rg['a3:list'] || 0);
  unchanged(c0, c, ['a3:band', 'a3:tl', 'a3:mom', 'a3:ins']);   // the toolbar follows S.sess.playing (回放 → 暂停) in place
  expect(await marked(page, MARKS)).toEqual(MARKS);
  expect(await page.evaluate(() => document.querySelector('#slist').scrollTop)).toBe(top0);
  // the replay was not interrupted: still playing, the timeline not re-mounted (same svg), the playhead moving
  expect(await page.evaluate(() => S.sess.playing)).toBe(true);
  await page.evaluate(() => ACT.playToggle());
  expect(await page.evaluate(() => S.sess.playing)).toBe(false);

  // 2) typing in the search field (focus kept) while another list update lands: value, caret and node identity stay
  await page.locator('#sessQ').click();
  await page.keyboard.type('#1');
  await expect(page.locator('#sessQ')).toBeFocused();
  const L3 = clone(L2); L3.rows.find((r) => r.id === A).ticks = { t: [0.25], e: [] };
  gw.set('GET /v1/uiview/sessions', route(L3));
  await frame(page, 'data.published', { data_rev: 3 });
  await expect.poll(() => page.evaluate(() => LV.feeds.sessions[0].data.list.rows.find((r) => r.id === S.sess.sel)?.ticks.t[0])).toBe(0.25);
  await expect(page.locator('#sessQ')).toBeFocused();
  await expect(page.locator('#sessQ')).toHaveValue('#1');
  c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(await marked(page, ['#sessQ', '#slist', '[data-region="a3:list"]'])).toEqual(['#sessQ', '#slist', '[data-region="a3:list"]']);
  expect(errors).toEqual([]);
});

test('A3 (demo): picking a session, highlighting a stat and switching the axis refresh regions only', async ({ page }) => {
  await openDemo(page);
  await go(page, 'sessions');
  await expect(page.locator('#tlBox svg.vz-svg')).toHaveCount(1);
  await page.addStyleTag({ content: '#slist{max-height:160px;overflow:auto}' });
  await page.evaluate(() => { document.querySelector('#slist').scrollTop = 120; });
  const top0 = await page.evaluate(() => document.querySelector('#slist').scrollTop);
  const MARKS = ['#main .tbar', '[data-region="a3:list"]', '#slist', '#sessQ', '[data-region="a3:tl"]', '#tlBox', '#content'];
  await mark(page, MARKS);
  const c0 = await counts(page);
  const other = await page.evaluate(() => Array.from(document.querySelectorAll('#slist .srow')).map((b) => b.dataset.id).find((id) => id !== S.sess.sel));
  await page.evaluate((id) => document.querySelector('#slist .srow[data-id="' + id + '"]').click(), other);
  await expect(page.locator('#slist .srow[data-id="' + other + '"]')).toHaveAttribute('aria-pressed', 'true');
  await page.locator('.stats7 [data-act="hiStat"][data-v="tools"]').click();
  await expect(page.locator('.stats7 [data-act="hiStat"][data-v="tools"]')).toHaveClass(/on/);
  await page.locator('[data-act="axis"][data-v="steps"]').click();
  await expect(page.locator('[data-act="axis"][data-v="steps"]')).toHaveClass(/on/);
  const c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(await marked(page, MARKS)).toEqual(MARKS);
  expect(await page.evaluate(() => document.querySelector('#slist').scrollTop)).toBe(top0);
  await expect(page.locator('#tlBox svg.vz-svg')).toHaveCount(1);
  // a route switch is still one full render
  await go(page, 'tools');
  expect((await counts(page)).full).toBe(c0.full + 1);
});

test('A4: a tools feed update refreshes the KPI tiles only; the expanded row, chart and content scroll survive', async ({ page }) => {
  const errors = collectErrors(page);
  const TOOLS = fx('s3/tools.json');
  const gw = await stubGateway(page, ['core', 's3']);
  await openLive(page, 'tools');
  await expect(page.locator('#main table.tt tbody tr[data-t="Bash"]')).toBeVisible();
  await page.locator('#main tr[data-t="Bash"]').click();
  await expect(page.locator('#main tr.tt-open [data-tl="call"]').first()).toBeVisible();
  await expect(page.locator('[data-vz="waits"] svg').first()).toBeVisible();
  await page.addStyleTag({ content: '#content::after{content:"";display:block;height:2000px}' });
  await page.evaluate(() => { document.querySelector('#content').scrollTop = 260; });
  const top0 = await page.evaluate(() => document.querySelector('#content').scrollTop);
  const MARKS = ['#main .tbar', '[data-region="a4:table"]', '#main tr.tt-open', '[data-region="a4:matrix"]', '#tm', '[data-region="a4:fails"]', '[data-region="a4:waits"]', '[data-vz="waits"] svg', '[data-region="a4:mcp"]', '#content'];
  await mark(page, MARKS);
  const c0 = await counts(page);
  const kpi = () => page.locator('[data-region="a4:kpi"] .vz-kpi .v').first();
  const T2 = clone(TOOLS); T2.kpis.calls.value = 1700;
  gw.set('GET /v1/uiview/tools', T2);
  await frame(page, 'data.published', { data_rev: 2 });
  await expect(kpi()).toHaveText('1,700');
  const c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(c.rg['a4:kpi'] || 0).toBeGreaterThan(c0.rg['a4:kpi'] || 0);
  unchanged(c0, c, ['a4:table', 'a4:matrix', 'a4:fails', 'a4:waits', 'a4:mcp', 'a4:tbar']);
  expect(await marked(page, MARKS)).toEqual(MARKS);
  await expect(page.locator('#main tr[data-t="Bash"]')).toHaveAttribute('aria-expanded', 'true');
  expect(Math.abs((await page.evaluate(() => document.querySelector('#content').scrollTop)) - top0)).toBeLessThanOrEqual(40);
  // sorting is state too: the table region morphs in place, the page is still not rebuilt
  await page.locator('#main table.tt th button[data-k="name"]').click();
  await expect(page.locator('#main table.tt th button[data-k="name"]')).toHaveAttribute('aria-sort', 'ascending');
  expect((await counts(page)).full).toBe(c0.full);
  expect(await marked(page, ['[data-region="a4:table"]', '[data-region="a4:kpi"]'])).toEqual(['[data-region="a4:table"]']);
  expect(errors).toEqual([]);
});

test('A5: a projects feed update refreshes the table side only; the selected project and its detail cards stay', async ({ page }) => {
  const errors = collectErrors(page);
  const PROJ = fx('s3/projects.json');
  const gw = await stubGateway(page, ['core', 's3']);
  await openLive(page, 'projects');
  await expect(page.locator('#main .pj-tbl tbody tr[data-p]').first()).toBeVisible();
  await expect(page.locator('[data-region="a5:vs"] .pj-vs').first()).toBeVisible();
  const sel = await page.evaluate(() => S.proj.sel);
  const other = PROJ.projects.find((r) => r.project_id !== sel);
  const MARKS = ['#main .tbar', '[data-region="a5:table"]', '[data-region="a5:head"]', '[data-region="a5:vs"]', '[data-region="a5:ag"]', '[data-region="a5:flow"]', '[data-region="a5:cov"]', '#content'];
  await mark(page, MARKS);
  const c0 = await counts(page);
  const P2 = clone(PROJ); P2.projects.find((r) => r.project_id === other.project_id).sessions = other.sessions + 1;
  gw.set('GET /v1/uiview/projects', P2);
  await frame(page, 'data.published', { data_rev: 2 });
  await expect(page.locator('#main .pj-tbl tr[data-p="' + other.project_id + '"] td[data-count]').first()).toHaveText(String(other.sessions + 1));
  const c = await counts(page);
  expect(c.full).toBe(c0.full);
  expect(c.rg['a5:table'] || 0).toBeGreaterThan(c0.rg['a5:table'] || 0);
  unchanged(c0, c, ['a5:head', 'a5:vs', 'a5:ag', 'a5:flow', 'a5:cov']);
  expect(await marked(page, MARKS)).toEqual(MARKS);
  expect(await page.evaluate(() => S.proj.sel)).toBe(sel);
  // picking the other project refreshes regions in place (no page rebuild)
  await page.locator('#main .pj-tbl tr[data-p="' + other.project_id + '"]').click();
  await expect(page.locator('#main .pj-tbl tr[data-p="' + other.project_id + '"]')).toHaveAttribute('aria-selected', 'true');
  expect((await counts(page)).full).toBe(c0.full);
  expect(await marked(page, ['[data-region="a5:table"]', '#content'])).toEqual(['[data-region="a5:table"]', '#content']);
  expect(errors).toEqual([]);
});

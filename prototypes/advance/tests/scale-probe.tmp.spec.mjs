// TEMP probe (not committed): real-scale synthetic facts, native shell, every page.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, fx } from './live-helpers.mjs';

const N = +(process.env.SCALE_N || 3000);
function bigFacts(n) {
  const f = fx('core/facts.json');
  const projects = Array.from({ length: 80 }, (_, i) => ({ id: 'proj_' + i, name: 'repo-' + i, path: '~/Code/repo-' + i, n: 0 }));
  const rows = [];
  const day0 = Date.UTC(2026, 6, 6);
  for (let i = 0; i < n; i++) {
    const d = new Date(day0 + Math.floor(i * 88 / n) * 864e5).toISOString().slice(0, 10);
    const p = i % 80; projects[p].n++;
    rows.push(['s' + String(i).padStart(5, '0'), d, (i * 7) % 24, (i * 13) % 60, i % 7, p, '会话标题 ' + i + ' 修复构建脚本与测试', 5 + (i % 90), 10 + (i % 120), 4 + (i % 40), i % 200, i % 9, i % 4, i % 50, i % 2, i % 3, 0, 0, i % 4, 1000 * (i % 500)]);
  }
  f.rows = rows; f.projects = projects; f.dicts = Object.assign({}, f.dicts, { p: projects.map((x) => x.id) });
  f.meta = Object.assign({}, f.meta, { day0: '2026-07-06', first_day: '2026-07-06', last_day: '2026-10-02', counts: { sessions: n, excluded: 0 } });
  f.agents = f.agents.map((a) => Object.assign({}, a, { n: Math.round(n / 7) }));
  return f;
}
const NATIVE = { v: 1, app: '0.0.2', platform: 'macos', features: ['prefs'] };
const ADV = ['overview', 'persona', 'sessions', 'tools', 'projects', 'sentiment', 'recs', 'library', 'studio'];
const LITE = ['l-home', 'l-persona', 'l-sessions', 'l-recs'];

test('scale probe', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14');
  test.setTimeout(300_000);
  const facts = bigFacts(N);
  await page.addInitScript(() => {
    window.__long = [];
    try { new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__long.push(Math.round(e.duration)))).observe({ type: 'longtask', buffered: true }); } catch (e) { /* none */ }
  });
  const gw = await stubGateway(page, ['core', 's1', 's3'], { 'GET /v1/uiview/facts': facts }, { native: NATIVE });
  page.on('pageerror', (e) => console.log('PAGEERROR', String(e).slice(0, 200)));
  await openLive(page, 'overview');
  await page.waitForTimeout(1500);
  const frames = (k) => page.evaluate((n) => new Promise((r) => { let i = 0; const f = () => (++i >= n ? r() : requestAnimationFrame(f)); requestAnimationFrame(f); }), k);
  // cost of one drag-region measurement on the current page
  for (const r of ADV.concat(LITE)) {
    await page.evaluate(() => { window.__long = []; });
    const t = await page.evaluate((rr) => { const t0 = performance.now(); if (/^l-/.test(rr) !== (S.ed === 'lite')) edSet(/^l-/.test(rr) ? 'lite' : 'advance', rr); else go(rr); return performance.now() - t0; }, r);
    await frames(3);
    await page.waitForTimeout(800);
    const m = await page.evaluate(() => {
      const dom = document.getElementsByTagName('*').length;
      const t0 = performance.now(); document.querySelectorAll('#win *, #overlay *, #modal *').forEach((el) => { if (el.scrollHeight > el.clientHeight + 1) getComputedStyle(el).overflowY; }); const scan = performance.now() - t0;
      return { route: S.route, dom, scan: Math.round(scan), drag: window.__dragRegions.length, renders: window.__renderCount, long: window.__long.slice().sort((a, b) => b - a).slice(0, 4) };
    });
    console.log(r.padEnd(11), 'go', Math.round(t), JSON.stringify(m));
  }
  // idle on sessions for 20s
  await page.evaluate(() => edSet('advance', 'sessions'));
  await page.waitForTimeout(1500);
  const before = await page.evaluate(() => [window.__renderCount, window.__dragRegions.length]);
  const seen0 = gw.seen.length;
  await page.evaluate(() => { window.__long = []; });
  await page.waitForTimeout(20000);
  const after = await page.evaluate(() => [window.__renderCount, window.__dragRegions.length, window.__long]);
  const by = {}; gw.seen.slice(seen0).forEach((x) => { by[x.path] = (by[x.path] || 0) + 1; });
  console.log('IDLE 20s renders', after[0] - before[0], 'drag reports', after[1] - before[1], 'long', JSON.stringify(after[2]), 'reqs', JSON.stringify(by));
  // scroll the session list
  const sc = await page.evaluate(async () => {
    const sl = document.getElementById('slist'); if (!sl) return null;
    const n0 = window.__dragRegions.length; window.__long = [];
    const ts = []; let stop = false; const f = (t) => { ts.push(t); if (!stop) requestAnimationFrame(f); }; requestAnimationFrame(f);
    for (let i = 0; i < 60; i++) { sl.scrollTop += 80; await new Promise((r) => setTimeout(r, 16)); }
    await new Promise((r) => setTimeout(r, 500)); stop = true;
    const d = ts.slice(1).map((t, i) => t - ts[i]).sort((a, b) => a - b);
    return { rows: sl.querySelectorAll('.srow').length, p95: Math.round(d[Math.floor(d.length * 0.95)]), max: Math.round(d[d.length - 1]), drag: window.__dragRegions.length - n0, long: window.__long };
  });
  console.log('SCROLL slist', JSON.stringify(sc));
  const lm = await page.evaluate(async () => {
    const out = [];
    for (let i = 0; i < 15; i++) {
      window.__long = []; const n0 = window.__dragRegions.length;
      const b = document.querySelector('[data-act="sessLoadMore"]'); if (!b) break;
      const t0 = performance.now(); b.click(); const t1 = performance.now() - t0;
      await new Promise((r) => setTimeout(r, 450));
      out.push([Math.round(t1), document.querySelectorAll('#slist .srow').length, document.getElementsByTagName('*').length, window.__long.slice()]);
    }
    const t0 = performance.now(); document.querySelectorAll('#win *, #overlay *, #modal *').forEach((el) => { if (el.scrollHeight > el.clientHeight + 1) getComputedStyle(el).overflowY; }); const scan = performance.now() - t0;
    return { out, scan: Math.round(scan) };
  });
  console.log('LOADMORE', JSON.stringify(lm));
  const sr = await page.evaluate(async () => {
    window.__long = [];
    const el = document.getElementById('sessQ'); const res = [];
    for (const q of ['会', '会话', '会话标', '会话标题 1']) { const t0 = performance.now(); el.value = q; el.dispatchEvent(new Event('input', { bubbles: true })); res.push(Math.round(performance.now() - t0)); await new Promise((r) => setTimeout(r, 120)); }
    await new Promise((r) => setTimeout(r, 600));
    return { res, long: window.__long, rows: document.querySelectorAll('#slist .srow').length };
  });
  console.log('SEARCH', JSON.stringify(sr));
  // filter switch consistency: range 7 → 0 → 30, agents
  expect(1).toBe(1);
});

// Opt-in audit: a first import runs in the background against a REAL gateway while the user stays on every page and
// scrolls it. Run through scripts/check-app-journey.sh with JOURNEY_SPEC=tests/region-import-audit.spec.mjs (AUDIT_ED=lite
// for the Lite pages). It counts full renders that were not a navigation (route / edition change — those must stay near 0),
// region refreshes per region, long tasks, scroll jumps, region roots replaced during a stay, whether an open dropdown
// survives the live frames, and the native surfaces (menu bar panel / HUD / widgets) and drag-region reports.
// Writes $AUDIT_OUT (default test-results/region-import-audit-<ed>.json). Works against older builds too (no RG: every
// render() is a full render), which is how the before / after numbers are taken.
import fs from 'node:fs';
import path from 'node:path';
import { test, expect } from '@playwright/test';

const GW = process.env.LIVE_GATEWAY ? process.env.LIVE_GATEWAY.replace(/\/+$/, '') : null;
const TOKEN = process.env.TANDEM_TOKEN || '';
const SRC = process.env.JOURNEY_SRC || '';
const ED = process.env.AUDIT_ED === 'lite' ? 'lite' : 'advance';
const OUT = process.env.AUDIT_OUT || path.resolve('test-results', 'region-import-audit-' + ED + '.json');
const DWELL = +(process.env.AUDIT_DWELL_MS || 7000);
const SOURCES = ['claude_code', 'codex', 'dsh', 'hermes', 'kimi', 'opencode', 'pi'];
const ROUTES = ED === 'lite' ? ['l-home', 'l-persona', 'l-sessions', 'l-recs'] : ['overview', 'persona', 'sentiment', 'sessions', 'projects', 'tools', 'recs', 'library', 'studio'];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, actionTimeout: 8000 });

function hostInit([endpoint, token]) {
  window.__TANDEM_ENDPOINT__ = endpoint; window.__TANDEM_TOKEN__ = token;
  window.__ORBIT_NATIVE__ = { v: 1, app: '0.0.3', platform: 'macos', features: ['chooseFolder', 'save', 'openExternal', 'reveal', 'window'] };
  window.__folders = []; window.__drag = { n: 0, last: null };
  const fire = (name, detail) => setTimeout(() => window.dispatchEvent(new CustomEvent(name, { detail })), 30);
  window.webkit = { messageHandlers: { tandem: { postMessage(m) {
    if (m && m.type === 'dragRegions') { window.__drag.n++; window.__drag.last = { noDrag: m.noDrag.length, drag: m.drag.length, at: Date.now() }; return; }
    if (m.type === 'chooseFolder') { const p = window.__folders.shift(); fire('tandem:folder', { id: m.id, path: p || null, cancelled: !p }); }
    if (m.type === 'save') fire('tandem:saved', { id: m.id, ok: true, path: '/tmp/orbit-audit/export' });
  } } } };
}

// wraps go() / render() (global bindings of the bundle) and watches long tasks; works with and without the region framework
function instrument() {
  const A = window.__rra = { phase: 'boot', nav: 0, stray: [], lt: [], t0: Date.now() };
  const g0 = go; go = function () { A.inGo = (A.inGo || 0) + 1; try { return g0.apply(this, arguments); } finally { A.inGo--; } };   // eslint-disable-line no-global-assign
  const e0 = typeof edSet === 'function' ? edSet : null;
  const r0 = render; render = function () {   // eslint-disable-line no-global-assign
    const full = typeof RG === 'undefined' || !RG.canRefresh() || ROUTE_ENTER;
    if (full) {
      if (A.inGo) A.nav++;
      else A.stray.push({ phase: A.phase, route: S.route, t: Date.now() - A.t0, stack: String(new Error().stack || '').split('\n').slice(2, 7).map((s) => s.trim().replace(/\(.*\//, '(')).join(' < ') });
    }
    return r0.apply(this, arguments);
  };
  void e0;
  try {
    new PerformanceObserver((l) => l.getEntries().forEach((e) => A.lt.push({ phase: A.phase, d: Math.round(e.duration) }))).observe({ type: 'longtask', buffered: false });
  } catch (e) { A.noLT = true; }
}

const ev = (page, fn, arg) => page.evaluate(fn, arg);
const importing = (page) => ev(page, () => (typeof lvImporting === 'function' ? lvImporting() : !!(TL.job && /queued|pending|running/.test(TL.job.status))) || !!(typeof LVN !== 'undefined' && LVN.imp && LVN.imp.live && LVN.imp.live.after && !LVN.imp.live.done));
const snapshot = (page) => ev(page, () => ({ full: window.__renderCount, nav: window.__rra.nav, stray: window.__rra.stray.length, regions: Object.assign({}, window.__regionRenders || {}) }));

test('import audit: full renders, region refreshes and long tasks while every page is open', async ({ page, context, browser }) => {
  test.skip(!GW || !TOKEN, 'needs LIVE_GATEWAY + TANDEM_TOKEN (scripts/check-app-journey.sh)');
  test.setTimeout(25 * 60_000);
  await context.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.addInitScript(hostInit, [GW, TOKEN]);
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e && e.message || e).slice(0, 300)));
  await page.goto(GW + '/app');
  await expect(page.locator('#main')).not.toBeEmpty();
  await expect.poll(() => ev(page, () => LV.state), { timeout: 15_000 }).not.toBe('connecting');
  await expect.poll(() => ev(page, () => OVL), { timeout: 10_000 }).toBe('ob');
  await ev(page, instrument);

  // ---- onboarding: add every synthetic source, start the import, continue in the background ----
  await page.locator('[data-act="obNext"]').filter({ visible: true }).first().click();
  await expect.poll(() => ev(page, () => OB && OB.live && OB.live.state), { timeout: 10_000 }).toBe('ready');
  for (const ag of SOURCES) {
    const dir = path.join(SRC, ag); if (!fs.existsSync(dir)) continue;
    await ev(page, (p) => window.__folders.push(p), dir);
    await page.locator('select.ob-agent').selectOption(ag).catch(() => null);
    await page.locator('[data-act="obAddFolder"]').filter({ visible: true }).first().click();
    await expect.poll(() => ev(page, () => OB.live.adding), { timeout: 10_000 }).toBeFalsy();
  }
  await page.locator('[data-act="obStart"]').filter({ visible: true }).first().click();
  await expect.poll(() => ev(page, () => !!(OB.live.job || OB.live.starting)), { timeout: 15_000 }).toBeTruthy();
  const tImport = Date.now();
  const bg = page.locator('[data-act="obBgImport"], [data-act="obBg"]').filter({ visible: true });
  await expect.poll(() => bg.count(), { timeout: 15_000 }).toBeGreaterThan(0);
  await bg.first().click();
  await expect.poll(() => ev(page, () => OVL), { timeout: 5000 }).toBeFalsy();
  await ev(page, () => { if (typeof closeModal === 'function') closeModal(); });
  if (ED === 'lite') { await ev(page, () => edSet('lite')); await expect.poll(() => ev(page, () => S.ed)).toBe('lite'); await sleep(600); }

  // ---- stay on every page (cycling while the import runs), scroll the page, keep a dropdown open once ----
  const visits = []; let doneAt = null; let cycle = 0;
  const base = await snapshot(page);
  while (cycle < 4) {
    for (const r of ROUTES) {
      const imp0 = await importing(page);
      if (!imp0 && doneAt == null) doneAt = Date.now();
      await ev(page, (r) => { if (OVL) closeOverlay(); if (typeof closeModal === 'function') closeModal(); go(r); }, r);
      await sleep(250);
      await ev(page, (r) => {
        window.__rra.phase = r;
        document.querySelectorAll('#main [data-region], #side [data-region]').forEach((el) => { el.__rraMark = 1; });
        const c = document.getElementById('content'); if (c) c.__rraMark = 1;
      }, r);
      const s0 = await snapshot(page);
      const lt0 = await ev(page, () => window.__rra.lt.length);
      const box = await page.locator('#content').boundingBox().catch(() => null);
      const tops = []; let jumps = 0; let dir = 1; const t0 = Date.now(); let ddKept = null;
      if (box) await page.mouse.move(box.x + box.width / 2, box.y + Math.min(box.height / 2, 300));
      // one stay per cycle keeps the Agent menu open for ~2.5 s while frames arrive (it must stay open)
      if (r === ROUTES[0] && (await page.locator('#main [data-act="agentMenu"]').filter({ visible: true }).count())) {
        await page.locator('#main [data-act="agentMenu"]').filter({ visible: true }).first().click();
        await sleep(2500);
        ddKept = await ev(page, () => !!(typeof DD !== 'undefined' && DD) && !!document.querySelector('#dd:not([hidden])'));
        await page.keyboard.press('Escape');
      }
      while (Date.now() - t0 < DWELL) {
        const before = await ev(page, () => { const c = document.getElementById('content'); return c ? [c.scrollTop, c.scrollHeight - c.clientHeight] : [0, 0]; });
        if (before[1] <= 0) { await sleep(500); continue; }
        if (before[0] >= before[1] - 2) dir = -1; else if (before[0] <= 0) dir = 1;
        await page.mouse.wheel(0, dir * 140);
        await sleep(450);
        const after = await ev(page, () => { const c = document.getElementById('content'); return c ? c.scrollTop : 0; });
        tops.push(Math.round(after));
        // a jump: moved against the wheel by more than a scroll-anchoring nudge
        if ((dir > 0 && after < before[0] - 40) || (dir < 0 && after > before[0] + 40)) jumps++;
      }
      const s1 = await snapshot(page);
      const lts = await ev(page, (n) => window.__rra.lt.slice(n).map((x) => x.d), lt0);
      const ident = await ev(page, () => {
        const els = Array.from(document.querySelectorAll('#main [data-region], #side [data-region]'));
        const c = document.getElementById('content');
        return { regions: els.length, replaced: els.filter((el) => !el.__rraMark).map((el) => el.getAttribute('data-region')).slice(0, 12), contentKept: !!(c && c.__rraMark) };
      });
      const reg = {}; Object.keys(s1.regions).forEach((k) => { const d = s1.regions[k] - (s0.regions[k] || 0); if (d) reg[k] = d; });
      visits.push({ cycle, route: r, importing: imp0, strayFull: s1.stray - s0.stray, fullDelta: s1.full - s0.full, navDelta: s1.nav - s0.nav, regionRefreshes: reg, longTasks: lts.length, longTaskMax: lts.length ? Math.max(...lts) : 0, scrollJumps: jumps, scrollSamples: tops.length, ddKept, ...ident });
    }
    cycle++;
    if (!(await importing(page)) && doneAt != null) break;
    if (!(await importing(page)) && doneAt == null) doneAt = Date.now();
  }
  const end = await snapshot(page);
  const A = await ev(page, () => ({ stray: window.__rra.stray, lt: window.__rra.lt, noLT: !!window.__rra.noLT }));
  const drag = await ev(page, () => window.__drag);

  // ---- native surfaces opened during / after the import: they must render and refresh without errors ----
  const surfaces = {};
  for (const sf of ['panel', 'hud', 'widgets']) {
    const p = await context.newPage();
    const errs = []; p.on('pageerror', (e) => errs.push(String(e && e.message || e).slice(0, 200)));
    await p.addInitScript(hostInit, [GW, TOKEN]);
    await p.goto(GW + '/app?surface=' + sf);
    await sleep(2500);
    const info = await p.evaluate((sf) => {
      const vis = (sel) => { const el = document.querySelector(sel); return !!(el && !el.hidden && el.getBoundingClientRect().height > 0); };
      const root = sf === 'panel' ? '#pop' : sf === 'hud' ? '#hud' : '#widgets';
      const el = document.querySelector(root);
      if (el) el.__rraMark = 1;
      const kids = el ? Array.from(el.querySelectorAll('*')).slice(0, 40) : [];
      kids.forEach((k) => { k.__rraMark = 1; });
      return { visible: vis(root), text: el ? el.innerText.replace(/\s+/g, ' ').slice(0, 80) : '', drag: window.__drag.n, kids: kids.length };
    }, sf);
    // three refreshes in a row (a live frame each): the surface root and its first nodes must stay the same nodes
    await p.evaluate(() => { render(); render(); render(); });
    await sleep(300);
    info.kept = await p.evaluate((sf) => {
      const el = document.querySelector(sf === 'panel' ? '#pop' : sf === 'hud' ? '#hud' : '#widgets');
      const kids = el ? Array.from(el.querySelectorAll('*')).slice(0, 40) : [];
      return { root: !!(el && el.__rraMark), kids: kids.filter((k) => k.__rraMark).length };
    }, sf);
    info.errors = errs;
    surfaces[sf] = info;
    await p.close();
  }
  void browser;

  const sum = (f) => visits.reduce((a, v) => a + f(v), 0);
  const report = {
    ed: ED, build: await ev(page, () => (typeof RG !== 'undefined' ? 'regions' : 'page-render')),
    importSeconds: doneAt ? Math.round((doneAt - tImport) / 1000) : null,
    sessions: await ev(page, () => ALL.length),
    totals: {
      fullRenders: end.full - base.full, navRenders: end.nav - base.nav, strayFullRenders: end.stray - base.stray,
      strayDuringImport: sum((v) => (v.importing ? v.strayFull : 0)),
      fullRendersDuringImportStays: sum((v) => (v.importing ? v.fullDelta - v.navDelta : 0)),
      regionRefreshes: Object.keys(end.regions).reduce((a, k) => a + end.regions[k] - (base.regions[k] || 0), 0),
      longTasks: sum((v) => v.longTasks), longTaskMax: Math.max(0, ...visits.map((v) => v.longTaskMax)),
      scrollJumps: sum((v) => v.scrollJumps), replacedRegionRoots: sum((v) => v.replaced.length),
      contentReplacedDuringStay: visits.filter((v) => !v.contentKept).length,
      ddKept: visits.filter((v) => v.ddKept != null).map((v) => v.ddKept)
    },
    regionRefreshesByKey: Object.fromEntries(Object.keys(end.regions).map((k) => [k, end.regions[k] - (base.regions[k] || 0)]).filter((x) => x[1]).sort((a, b) => b[1] - a[1])),
    strayFullRenderStacks: A.stray.slice(0, 20),
    longTasksAll: A.lt.length, noLongTaskApi: A.noLT,
    dragRegions: drag, surfaces, errors, visits
  };
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(report, null, 1));
  console.log('[audit]', ED, JSON.stringify(report.totals), 'import', report.importSeconds + 's', 'sessions', report.sessions);
  expect(errors, 'page errors').toEqual([]);
  if (report.build === 'regions') {
    expect(report.totals.strayFullRenders, 'full renders outside navigation').toBeLessThanOrEqual(1);
    expect(report.totals.scrollJumps, 'scroll jumps while scrolling a page').toBe(0);
    expect(drag.n, 'drag-region reports').toBeGreaterThan(0);
    Object.values(surfaces).forEach((s) => { expect(s.errors).toEqual([]); });
  }
});

// Round 4 first run: Genesis waits for the analysis of the revision the import published (R4-09), the onboarding source list
// snaps to whole rows (R4-10), and About shows the Orbit brand on the 本机服务 row (R4-17). Stub gateway only.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const JOB = '10951bad4daa4a2fb0994de1f0d61e09';
const clock = (page) => page.clock.setFixedTime(new Date('2026-10-03T12:00:00+08:00'));
test.skip(!!PASS, 'stub-only: writes sources and jobs');

function firstRun(extra) {
  const map = Object.assign({
    'GET /v1/uiview/facts': fx('core/facts-empty.json'),
    'POST /v1/app/sources': (req) => { const b = JSON.parse(req.postData() || '{}'); return { id: 'source_new_' + b.agent, agent: b.agent, root: b.root, enabled: b.enabled }; },
    'PATCH /v1/app/settings': (req) => Object.assign({ onboarded: false, recent_days: 90 }, JSON.parse(req.postData() || '{}')),
    'POST /v1/app/jobs': { status: 202, body: fx('s7/job-queued.json') },
    ['GET /v1/app/jobs/' + JOB]: fx('s7/job-running.json'),
    'POST /v1/catalog/sync': { status: 202, body: { accepted: true } }
  }, extra || {});
  return map;
}
// the import published data_rev 7: the projection is ready, the facts spine of that revision is what the app shows afterwards
function published(gw) {
  const st = fx('s7/app-state-empty.json');
  st.storage = { data_rev: 7, inventory_rev: 0, projection: 'ready', counts: { sessions: 26, events: 900, projects: 3 }, published_at: 1 };
  const facts = fx('core/facts.json'); facts.meta = Object.assign({}, facts.meta, { data_rev: 7 });
  gw.set('GET /v1/app/state', st);
  gw.set('GET /v1/uiview/facts', facts);
  gw.set('GET /v1/app/jobs/' + JOB, fx('s7/job-completed.json'));
}
// the previous snapshot the gateway serves while the analysis of rev 7 is still computing (what R4-09 played as the final card)
function staleReveal() {
  const r = fx('s7/persona-reveal.json');
  r.meta = Object.assign({}, r.meta, { freshness: 'stale', data_rev: 1, job_id: null });
  return Object.assign(r, { n: 95, classified: false, code: 'SI?T', zh: '尚未定型', en: 'Undetermined', line: '有维度落在 45–55 之间，暂不下结论。' });
}
async function startImport(page) {
  await openLive(page, 'overview');
  await page.locator('#overlay [data-act="obNext"]').click();
  await expect(page.locator('#overlay label.srcrow').first()).toBeVisible();
  await page.locator('#overlay [data-act="obStart"]').click();
  await expect(page.locator('#overlay [data-ob="stages"] .step')).toHaveCount(4);
}

test('R4-09: Genesis waits past a stale reveal for the published revision and shows the final persona', async ({ page }) => {
  await clock(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = collectErrors(page);
  let calls = 0;
  const gw = await stubGateway(page, ['core', 's7'], firstRun({ 'GET /v1/uiview/persona/reveal': () => (++calls <= 2 ? staleReveal() : fx('s7/persona-reveal.json')) }));
  await startImport(page);
  published(gw);
  await expect(page.locator('#genBox')).toBeVisible({ timeout: 15_000 });
  expect(calls).toBeGreaterThanOrEqual(3);
  await expect(page.locator('#genBox [data-g="code"]')).toHaveAttribute('aria-label', 'SIMT');
  await expect(page.locator('#genBox [data-g="head"]')).toContainText('基于 26 个会话');
  await expect(page.locator('#genBox [data-g="head"]')).not.toContainText('部分结果');
  await expect(page.locator('#genBox [data-g="count"]')).toContainText('26 个会话');
  expect(await page.evaluate(() => [OB.revealP.p.n, !!OB.revealP.p.partial])).toEqual([111, false]);
  expect(errors).toEqual([]);
});

test('R4-09: when only an older snapshot comes back, Genesis labels the card as partial instead of final', async ({ page }) => {
  test.setTimeout(60_000);
  await clock(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's7'], firstRun({ 'GET /v1/uiview/persona/reveal': () => staleReveal() }));
  await startImport(page);
  published(gw);
  await expect(page.locator('#genBox')).toBeVisible({ timeout: 45_000 });
  await expect(page.locator('#genBox [data-g="head"]')).toContainText('部分结果');
  expect(await page.evaluate(() => !!OB.revealP.p.partial)).toBe(true);
  expect(errors).toEqual([]);
});

test('R4-10: the onboarding source list shows whole rows only (no row cut at the card edge)', async ({ page }) => {
  await clock(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's7'], firstRun());
  await openLive(page, 'overview');
  await page.locator('#overlay [data-act="obNext"]').click();
  await expect(page.locator('#overlay label.srcrow')).toHaveCount(8);
  const cut = () => page.evaluate(() => {
    const sc = $('#overlay [data-ob="sources"]'); const r = sc.getBoundingClientRect(); const top = r.top + sc.clientTop, bot = top + sc.clientHeight;
    return { scrolls: sc.scrollHeight > sc.clientHeight + 1, cut: Array.from(sc.children).filter((c) => { const b = c.getBoundingClientRect(); return b.top < bot - 0.5 && b.bottom > bot + 0.5; }).length };
  });
  const a = await cut();
  expect(a.scrolls).toBe(true);
  expect(a.cut).toBe(0);
  // a redraw (ticking a source re-renders the sheet) keeps the snap and the scroll position
  const h0 = await page.evaluate(() => $('#overlay [data-ob="sources"]').style.height);
  await page.evaluate(() => { $('#overlay [data-ob="sources"]').scrollTop = 40; drawOB(); });
  expect(await page.evaluate(() => $('#overlay [data-ob="sources"]').style.height)).toBe(h0);
  expect(await page.evaluate(() => $('#overlay [data-ob="sources"]').scrollTop)).toBe(40);
  // the sheet still fits the 900 px window
  const b = await page.locator('#overlay .obox').boundingBox();
  expect(b.y + b.height).toBeLessThanOrEqual(900);
  expect(errors).toEqual([]);
});

test('R4-17: About shows Orbit on the 本机服务 row even when the gateway reports its legacy name', async ({ page }) => {
  const errors = collectErrors(page);
  const about = fx('s7/about.json'); about.app = Object.assign({}, about.app, { name: 'Tandem' });
  await stubGateway(page, ['core', 's7'], { 'GET /v1/app/state': fx('s7/app-state-full.json'), 'GET /v1/app/about': about });
  await openLive(page, 'overview');
  await page.evaluate(() => openAbout());
  const rows = page.locator('#modal [data-about="rows"]');
  await expect(rows).toBeVisible({ timeout: 10_000 });
  await expect(rows).toContainText('Orbit · 0.13.6 · tandem-app-v1');
  await expect(page.locator('#modal')).not.toContainText(/Tandem/);
  expect(errors).toEqual([]);
});

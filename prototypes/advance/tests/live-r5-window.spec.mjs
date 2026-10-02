// Round 5, first-open auto window (backend fast path): stub gateway, synthetic fixtures only (prototypes/shared/fixtures/core).
//  W1  auto window 7 with 30 computing → calm hint; SSE analysis.ready (same scope_hash) → facts days=30 → hint gone,
//      overview feed follows with days=30, the screen never blanks
//  W2  202 meta.progress → the computing badge names elapsed / budget seconds and the event count
//  W3  422 analysis_scope_too_large on 全部 → 「数据量太大，已切换到近 30 天」 and the feed asks days=30
//  W4  only days ∈ {7, 30, 90, 0} are ever requested; 全部 asks days=0 once that window is ready
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx } from './live-helpers.mjs';

const NOW = new Date('2026-10-03T12:00:00+08:00');
const FACTS = fx('core/facts.json');
const ONLY = () => test.skip(test.info().project.name !== 'mac-14', 'runs once, at the default size');
const daysOf = (q) => { const m = /[?&]days=([^&]*)/.exec(q || ''); return m ? m[1] : null; };
const withWin = (window) => Object.assign({}, FACTS, { meta: Object.assign({}, FACTS.meta, { window }) });
const AUTO7 = (s30, s0) => ({ days: 7, requested: 'auto', wider: [{ days: 30, state: s30, scope_hash: 'h30' }, { days: 0, state: s0, scope_hash: 'h0' }] });
const OV = { meta: { freshness: 'fresh' }, tools: [], insight: null };

test.beforeEach(async ({ page }) => { ONLY(); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

function allowedOnly(gw) {
  const bad = gw.seen.filter((x) => /^\/v1\/uiview\//.test(x.path) && daysOf(x.query) != null && ['7', '30', '90', '0'].indexOf(daysOf(x.query)) < 0);
  expect(bad).toEqual([]);
}

test('W1: auto 7-day window shows the hint, analysis.ready widens to days=30 without blanking', async ({ page }) => {
  const errors = collectErrors(page);
  const facts = (req, u) => { const d = u.searchParams.get('days'); return d === '30' ? withWin({ days: 30, requested: 30, wider: [] }) : withWin(AUTO7('computing', 'queued')); };
  const gw = await stubGateway(page, 'core', { 'GET /v1/uiview/facts': facts, 'GET /v1/uiview/overview': OV });
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  const hint = page.locator('[data-tl="strip"] [data-tl="window"]');
  await expect(hint).toHaveText('目前显示近 7 天 · 30 天数据计算中');
  expect(await page.evaluate(() => LV.window.days)).toBe(7);
  // the overview feed waits for a ready window: auto (no days=) while 30 days is computing
  expect(gw.seen.filter((x) => x.path === '/v1/uiview/overview').every((x) => daysOf(x.query) == null)).toBe(true);
  // the screen never goes back to pending placeholders while widening
  await page.evaluate(() => { window.__pend = 0; new MutationObserver(() => { if (document.querySelector('#content [data-lv="pending"]') && LV.state === 'ready') window.__pend++; }).observe(document.body, { subtree: true, childList: true }); });
  gw.push([{ event: 'analysis.ready', data: { section: 'uiview_facts', scope_hash: 'h30', data_rev: 3 } }]);
  await expect.poll(() => gw.seen.some((x) => x.path === '/v1/uiview/facts' && daysOf(x.query) === '30'), { timeout: 15_000 }).toBe(true);
  await expect.poll(() => page.evaluate(() => LV.window.days)).toBe(30);
  await expect(hint).toHaveCount(0);
  await expect.poll(() => gw.seen.some((x) => x.path === '/v1/uiview/overview' && daysOf(x.query) === '30')).toBe(true);
  expect(await page.evaluate(() => ALL.length)).toBe(FACTS.rows.length);
  expect(await page.evaluate(() => window.__pend)).toBe(0);
  // 7 days is covered by the 30-day window: no hint, no new window request
  await page.locator('[data-act="range"][data-v="7"]').first().click();
  await expect(hint).toHaveCount(0);
  // 全部 is still queued: hint names it
  await page.locator('[data-act="range"][data-v="0"]').first().click();
  await expect(hint).toHaveText('目前显示近 30 天 · 全部数据计算中');
  allowedOnly(gw);
  expect(errors).toEqual([]);
});

test('W2: 202 with meta.progress shows elapsed / budget seconds and the event count', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, 'core', {
    'GET /v1/uiview/facts': { status: 202, body: { meta: { freshness: 'computing', job_id: 'job_w2', window: AUTO7('queued', 'queued'),
      progress: { status: 'running', attempt: 1, events: 12345, elapsed_s: 12.4, budget_s: 300 } } } },
    'GET /v1/analytics/jobs/job_w2': { body: { job_id: 'job_w2', status: 'running' } }
  });
  await openLive(page, 'overview');
  const badge = page.locator('[data-tl="strip"] [data-tl="computing"]');
  await expect(badge).toContainText('已用 12 / 300 秒');
  await expect(badge).toContainText('12,345 条事件');
  allowedOnly(gw);
  expect(errors).toEqual([]);
});

test('W3: 422 analysis_scope_too_large on 全部 falls back to 30 days and says so', async ({ page }) => {
  const errors = collectErrors(page);
  const facts = (req, u) => withWin(u.searchParams.get('days') === '30' ? { days: 30, requested: 30, wider: [] } : { days: 0, requested: 'auto', wider: [] });
  const ov = (req, u) => u.searchParams.get('days') === '0'
    ? { status: 422, body: { error: { code: 'analysis_scope_too_large', message: 'narrow the window', retryable: false } } } : OV;
  const gw = await stubGateway(page, 'core', { 'GET /v1/uiview/facts': facts, 'GET /v1/uiview/overview': ov });
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  await page.locator('[data-act="range"][data-v="0"]').first().click();
  await expect.poll(() => gw.seen.some((x) => x.path === '/v1/uiview/overview' && daysOf(x.query) === '0')).toBe(true);
  await expect.poll(() => gw.seen.some((x) => x.path === '/v1/uiview/overview' && daysOf(x.query) === '30')).toBe(true);
  await expect.poll(() => page.evaluate(() => LV.feedState('overview'))).toBe('ready');
  await expect(page.locator('[data-tl="strip"] [data-tl="window"]')).toHaveText('数据量太大，已切换到近 30 天');
  allowedOnly(gw);
  expect(errors).toEqual([]);
});

test('W3b: 422 on the spine itself (days=0) falls back to days=30', async ({ page }) => {
  const errors = collectErrors(page);
  const facts = (req, u) => {
    const d = u.searchParams.get('days');
    if (d === '0') return { status: 422, body: { error: { code: 'analysis_scope_too_large', message: 'too large', retryable: false } } };
    if (d === '30') return withWin({ days: 30, requested: 30, wider: [] });
    return withWin({ days: 7, requested: 'auto', wider: [{ days: 30, state: 'ready', scope_hash: 'h30' }, { days: 0, state: 'ready', scope_hash: 'h0' }] });
  };
  const gw = await stubGateway(page, 'core', { 'GET /v1/uiview/facts': facts, 'GET /v1/uiview/overview': OV });
  await openLive(page, 'overview');
  await page.locator('[data-act="range"][data-v="0"]').first().click();
  await expect.poll(() => gw.seen.some((x) => x.path === '/v1/uiview/facts' && daysOf(x.query) === '0')).toBe(true);
  await expect.poll(() => page.evaluate(() => LV.window && LV.window.days)).toBe(30);
  await expect(page.locator('[data-tl="strip"] [data-tl="window"]')).toHaveText('数据量太大，已切换到近 30 天');
  expect(await page.evaluate(() => LV.state)).toBe('ready');
  allowedOnly(gw);
  expect(errors).toEqual([]);
});

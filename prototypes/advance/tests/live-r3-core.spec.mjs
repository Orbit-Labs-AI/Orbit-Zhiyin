// Round 3 (backend API changes), core / ops side: stub gateway, synthetic fixtures only.
//  2. a 202 names its job → GET /v1/analytics/jobs/{id} with backoff (no blind refetch); a failed job or a 503
//     analysis_unavailable shows the reason (分析超时) + 重新计算 → POST /v1/analytics/recompute, then the new job is polled
//  7. realtime reason=collection_paused → menu-bar panel / HUD / widgets show 采集已暂停 + 恢复采集 → POST /v1/platform/collection/resume
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx } from './live-helpers.mjs';

const NOW = new Date('2026-10-03T12:00:00+08:00');
const FACTS = fx('core/facts.json');
const ONLY = () => test.skip(test.info().project.name !== 'mac-14', 'runs once, at the default size');
const strip = (page) => page.locator('#content > [data-tl="strip"]');
const posts = (gw, p) => gw.seen.filter((s) => s.method === 'POST' && s.path === p);

test.beforeEach(async ({ page }) => { ONLY(); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

test('spine 202: the job is polled (no blind refetch); a timeout shows 分析超时 + 重新计算, which recomputes and reloads', async ({ page }) => {
  const errors = collectErrors(page);
  const st = { phase: 'running', body: null };
  const gw = await stubGateway(page, 'core', {
    'GET /v1/uiview/facts': () => (st.phase === 'ok' ? FACTS : { status: 202, body: { meta: { freshness: 'computing', job_id: st.phase === 'recompute' ? 'job-r3-2' : 'job-r3-1' } } }),
    'GET /v1/analytics/jobs/job-r3-1': () => (st.phase === 'running'
      ? { id: 'job-r3-1', kind: 'analysis', section: 'uiview_facts', status: 'running', elapsed_s: 4.2, timeout_s: 60, error: null }
      : { id: 'job-r3-1', kind: 'analysis', section: 'uiview_facts', status: 'failed', elapsed_s: null, timeout_s: 60, error: { code: 'timeout', message: 'analysis exceeded its time budget' } }),
    'POST /v1/analytics/recompute': (req) => { st.body = JSON.parse(req.postData() || '{}'); st.phase = 'recompute'; return { status: 202, body: { jobs: [{ section: 'uiview_facts', scope_hash: 'sha256:fx', job_id: 'job-r3-2' }], data_rev: 3 } }; },
    'GET /v1/analytics/jobs/job-r3-2': () => { st.phase = 'ok'; return { id: 'job-r3-2', kind: 'analysis', section: 'uiview_facts', status: 'completed', error: null }; }
  });
  await openLive(page, 'overview');
  await expect(strip(page).locator('[data-tl="computing"]')).toContainText('已用 4 / 60 秒');
  await expect.poll(() => gw.count('/v1/analytics/jobs/job-r3-1')).toBeGreaterThan(1);
  expect(gw.count('/v1/uiview/facts')).toBe(1);   // polling the job, not refetching facts
  st.phase = 'failed';
  await expect(strip(page).locator('[data-tl="unavailable"]')).toHaveText('分析超时', { timeout: 10_000 });
  const btn = strip(page).locator('[data-act="lvRecompute"]');
  await expect(btn).toHaveText('重新计算');
  const n = gw.count('/v1/uiview/facts');
  await page.waitForTimeout(1500);
  expect(gw.count('/v1/uiview/facts')).toBe(n);   // a failed analysis is not retried on its own
  await btn.click();
  await expect.poll(() => posts(gw, '/v1/analytics/recompute').length).toBe(1);
  expect(st.body).toEqual({ sections: ['uiview_facts'], scope: { display_timezone: await page.evaluate(() => TL_TZ || 'UTC') } });
  await expect.poll(() => page.evaluate(() => LV.state), { timeout: 10_000 }).toBe('ready');
  expect(await page.evaluate(() => [ALL.length, LV.failed])).toEqual([FACTS.rows.length, null]);
  await expect(strip(page).locator('[data-tl="unavailable"], [data-act="lvRecompute"]')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('feed 503 analysis_unavailable: the page strip names the reason and 重新计算 posts recompute; no service banner', async ({ page }) => {
  const errors = collectErrors(page);
  const st = { ok: false };
  const gw = await stubGateway(page, 'core', {
    'GET /v1/uiview/tools': () => (st.ok ? { status: 404 } : { status: 503, headers: { 'Retry-After': '5' }, body: { error: { code: 'analysis_unavailable', message: 'worker_crashed: analysis worker exited', retryable: true } } }),
    'POST /v1/analytics/recompute': () => { st.ok = true; return { status: 202, body: { jobs: [{ section: 'uiview_facts', scope_hash: 'sha256:fx', job_id: 'job-r3-3' }], data_rev: 3 } }; },
    'GET /v1/analytics/jobs/job-r3-3': { id: 'job-r3-3', status: 'completed' }
  });
  await openLive(page, 'tools');
  await expect(strip(page).locator('[data-tl="unavailable"]')).toHaveText('分析进程异常退出');
  await expect(page.locator('[data-tl="unavailable"].tl-banner, .tl-banner')).toHaveCount(0);
  const n = gw.count('/v1/uiview/tools');
  await page.waitForTimeout(1200);
  expect(gw.count('/v1/uiview/tools')).toBe(n);
  await strip(page).locator('[data-act="lvRecompute"]').click();
  await expect.poll(() => posts(gw, '/v1/analytics/recompute').length).toBe(1);
  await expect.poll(() => gw.count('/v1/uiview/tools')).toBeGreaterThan(n);   // refetched after the job completed
  expect(errors).toEqual([]);
});

// realtime while collection is paused: status paused, reason collection_paused, no sessions
const PAUSED = { generated_at: NOW.getTime(), status: 'paused', counts: { running: 0, awaiting_approval: 0, failing: 0, just_finished: 0, context_pressure: 0, idle: 0 }, today: null, reason: 'collection_paused', sessions: [] };
const CALM = Object.assign({}, PAUSED, { status: 'idle', reason: null, today: { sessions_started: 0, sessions_finished: 0 } });
const NATIVE = { v: 1, app: '0.0.1', platform: 'macos', features: ['chooseFolder', 'save', 'openExternal', 'reveal', 'window'] };
async function pausedGateway(page, opts) {
  const st = { paused: true };
  const gw = await stubGateway(page, ['core', 's8'], {
    'GET /v1/analytics/realtime': () => (st.paused ? PAUSED : CALM),
    'GET /v1/analytics/realtime/stream': { status: 404 },
    'POST /v1/platform/collection/resume': () => { st.paused = false; return { paused: false, catch_up_job_id: 'job-catchup' }; }
  }, opts);
  return gw;
}

test('collection paused (main window): panel, HUD and widgets show 采集已暂停; 恢复采集 posts resume and clears it', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await pausedGateway(page);
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => S.paused)).toBe(true);
  await page.evaluate(() => { S.widgets = true; S.hud.show = true; S.pop = true; render(); });
  await expect(page.locator('#pop')).toContainText('采集已暂停');
  await expect(page.locator('#pop [data-act="setPause"]')).toHaveText('恢复采集');
  await expect(page.locator('#hudPill[data-tl="rt-paused"]')).toContainText('采集已暂停');
  await expect(page.locator('#widgets [data-tl="rt-paused"]')).toContainText('恢复采集');
  await page.locator('#hudPill [data-act="setPause"]').click();
  await expect.poll(() => posts(gw, '/v1/platform/collection/resume').length).toBe(1);
  await expect.poll(() => page.evaluate(() => S.paused)).toBe(false);
  await expect(page.locator('#hudPill[data-tl="rt-paused"], #widgets [data-tl="rt-paused"]')).toHaveCount(0);
  expect(errors).toEqual([]);
});

for (const sf of ['panel', 'hud', 'widgets']) {
  test('collection paused (surface ' + sf + '): 采集已暂停 with 恢复采集 → POST resume', async ({ page }) => {
    const errors = collectErrors(page);
    const gw = await pausedGateway(page, { native: NATIVE });
    await page.goto('http://orbit.test/app?live=1&surface=' + sf);
    await expect.poll(() => page.evaluate(() => LV.state), { timeout: 10_000 }).not.toBe('connecting');
    const keep = { panel: '#pop', hud: '#hud', widgets: '#widgets' }[sf];
    await expect(page.locator(keep)).toContainText('采集已暂停');
    await page.locator(keep + ' [data-act="setPause"]').first().click();
    await expect.poll(() => posts(gw, '/v1/platform/collection/resume').length).toBe(1);
    await expect.poll(() => page.evaluate(() => S.paused)).toBe(false);
    await expect(page.locator(keep)).not.toContainText('采集已暂停');
    expect(errors).toEqual([]);
  });
}

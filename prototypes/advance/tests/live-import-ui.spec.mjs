// Import UI (bug 3 / bug 7): job frames during an import patch the progress in place instead of re-rendering the page,
// scroll positions and an open dropdown survive frames and renders, and after 在后台继续 the sidebar entry brings the
// running import's stage view back (no second job). Stub gateway; job frames are fed through TL.dispatch (the SSE path).
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const JOB = '10951bad4daa4a2fb0994de1f0d61e09';
const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
test.skip(!!PASS, 'stub-only: feeds synthetic job frames');

const frame = (page, name, data) => page.evaluate(([n, d]) => TL.dispatch(n, d), [name, data]);
const job = (done, total, status) => ({ id: JOB, kind: 'import', status: status || 'running', progress: { stage: 'backfill', completed: done, total } });

test('import frames do not re-render the page; scroll and the Agent dropdown stay put', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  await stubGateway(page, ['core']);
  await openLive(page, 'sessions');
  await expect(page.locator('#main .tbar h1')).toBeVisible();
  // the import starts: the strip and the sidebar entry appear (one render)
  await frame(page, 'job', job(1, 40));
  await expect(page.locator('#content .tl-progress')).toBeVisible();
  await expect(page.locator('#side [data-side="import"]')).toContainText('导入中');
  // the entry uses the system-font tokens (an undefined var() would drop the whole font shorthand)
  expect(await page.locator('#side [data-side="import"]').evaluate((el) => { const cs = getComputedStyle(el); return [cs.fontSize, cs.fontWeight]; })).toEqual(['12px', '500']);
  // user scrolls the page and the sidebar, then opens the Agent dropdown
  // a long page and a short sidebar list (synthetic data is small): both survive re-renders as CSS
  await page.addStyleTag({ content: '#content::after{content:"";display:block;height:3000px} #side .sb-scroll{max-height:120px}' });
  await page.evaluate(() => { document.querySelector('#content').scrollTop = 400; document.querySelector('#side .sb-scroll').scrollTop = 40; });
  await page.waitForTimeout(50);
  // DOM click: Playwright's click would scroll the chip (top of the page) into view first
  await page.evaluate(() => document.querySelector('#main [data-act="agentMenu"]').click());
  await expect(page.locator('#dd')).toBeVisible();
  const top0 = await page.evaluate(() => document.querySelector('#content').scrollTop);
  expect(top0).toBeGreaterThan(0);
  const n0 = await page.evaluate(() => window.__renderCount);
  // 20 progress frames (plus a publish every 5) over ~2 s
  for (let i = 2; i <= 21; i++) {
    await frame(page, 'job', job(i, 40));
    if (i % 5 === 0) await frame(page, 'data.published', { data_rev: i });
    await page.waitForTimeout(100);
  }
  await expect(page.locator('#content .tl-progress')).toContainText('21');
  await expect(page.locator('#side [data-side="import"]')).toContainText('53%');
  const n1 = await page.evaluate(() => window.__renderCount);
  expect(n1 - n0).toBeLessThanOrEqual(2);   // not one per frame
  await expect(page.locator('#dd')).toBeVisible();
  expect(await page.evaluate(() => document.querySelector('#content').scrollTop)).toBe(top0);
  // a full render (whatever triggers it) keeps the page and sidebar scroll positions
  await page.evaluate(() => { document.querySelector('#side .sb-scroll').scrollTop = 40; render(); });
  const after = await page.evaluate(() => [document.querySelector('#content').scrollTop, document.querySelector('#side .sb-scroll').scrollTop]);
  expect(after[0]).toBeGreaterThan(0);
  expect(after[1]).toBe(await page.evaluate(() => Math.min(40, document.querySelector('#side .sb-scroll').scrollHeight - document.querySelector('#side .sb-scroll').clientHeight)));
  expect(errors).toEqual([]);
});

function firstRun() {
  return {
    'GET /v1/uiview/facts': fx('core/facts-empty.json'),
    'POST /v1/app/sources': (req) => { const b = JSON.parse(req.postData() || '{}'); return { id: 'source_new_' + b.agent, agent: b.agent, root: b.root, enabled: b.enabled }; },
    'PATCH /v1/app/settings': (req) => Object.assign({ onboarded: false, recent_days: 90 }, JSON.parse(req.postData() || '{}')),
    'POST /v1/app/jobs': { status: 202, body: fx('s7/job-queued.json') },
    ['GET /v1/app/jobs/' + JOB]: fx('s7/job-running.json'),
    'POST /v1/catalog/sync': { status: 202, body: { accepted: true } }
  };
}

test('background import: the sidebar entry reopens the running stage view, then 重新打开引导 plays the reveal', async ({ page }) => {
  ONLY('mac-14');
  await page.clock.setFixedTime(new Date('2026-10-03T12:00:00+08:00'));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's7'], firstRun());
  await openLive(page, 'overview');
  await page.locator('#overlay [data-act="obNext"]').click();
  await expect(page.locator('#overlay label.srcrow').first()).toBeVisible();
  await page.locator('#overlay [data-act="obStart"]').click();
  await expect(page.locator('#overlay [data-ob="stages"] .step')).toHaveCount(4);
  await page.locator('#overlay [data-act="obBgImport"]').click();
  await expect(page.locator('#overlay')).toBeHidden();
  const entry = page.locator('#side [data-side="import"]');
  await expect(entry).toContainText('导入中');
  await expect(entry).toContainText('查看');
  // frames keep the entry current without rebuilding the sidebar
  await frame(page, 'job', job(6, 8));
  await expect(entry).toContainText('75%');
  // Lite shows the same entry
  await page.evaluate(() => edSet('lite'));
  await expect(page.locator('#side [data-side="import"]')).toContainText('导入中');
  await page.evaluate(() => edSet('advance'));
  await page.locator('#side [data-side="import"]').click();
  await expect(page.locator('#overlay')).toBeVisible();
  await expect(page.locator('#overlay [data-ob="stages"] .step')).toHaveCount(4);
  await expect(page.locator('#overlay [data-stage="backfill"]')).toHaveAttribute('data-st', 'running');
  // the help menu path (openOnboarding) while running also lands on the stage view, never on a fresh run
  await page.locator('#overlay [data-act="obBgImport"]').click();
  await page.evaluate(() => openOnboarding(0));
  await expect(page.locator('#overlay [data-ob="stages"]')).toBeVisible();
  expect(gw.seen.filter((x) => x.method === 'POST' && x.path === '/v1/app/jobs').length).toBe(1);
  // finish in the background
  await page.locator('#overlay [data-act="obBgImport"]').click();
  const st = fx('s7/app-state-empty.json');
  st.storage = { data_rev: 7, inventory_rev: 0, projection: 'ready', counts: { sessions: 26, events: 900, projects: 3 }, published_at: 1 };
  const facts = fx('core/facts.json'); facts.meta = Object.assign({}, facts.meta, { data_rev: 7 });
  gw.set('GET /v1/app/state', st); gw.set('GET /v1/uiview/facts', facts); gw.set('GET /v1/app/jobs/' + JOB, fx('s7/job-completed.json'));
  await expect(page.locator('#side [data-side="import"]')).toContainText('重新打开引导', { timeout: 20_000 });
  await page.locator('#side [data-side="import"]').click();
  await expect(page.locator('#overlay [data-act="obPlay"]')).toBeVisible();
  await page.locator('#overlay [data-act="obPlay"]').click();
  await expect(page.locator('#genBox')).toBeVisible();
  expect(gw.seen.filter((x) => x.method === 'POST' && x.path === '/v1/app/jobs').length).toBe(1);
  expect(errors).toEqual([]);
});

// Slice 5 (A7 优化建议 / A8 资源库 / install sheet) on the live core: real agents, no demo rows for personal data, honest
// cold-start state, 示例数据 only on bundled seed catalog items, first-visit catalog sync, openExternal links and the
// apply → revert flow with the preview digest. Fixtures: prototypes/shared/fixtures/{core,s5} (synthetic).
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx } from './live-helpers.mjs';

const NATIVE = { v: 1, app: '0.0.1', platform: 'macos', features: ['chooseFolder', 'save', 'openExternal', 'reveal', 'window'] };
const MOCK_RECS = /只读命令自动放行|PR 收尾|pr-wrapup|retry-breaker|design-review/;

test.beforeEach(async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'runs once, at the default size');
  // the install sheet's double-click guards need a moving clock, so only the other tests pin it
  if (!/预览并安装/.test(test.info().title)) await page.clock.setFixedTime(new Date('2026-10-03T12:00:00+08:00'));
  await page.emulateMedia({ reducedMotion: 'reduce' });
});

const noPlainTables = async (page) => {
  await expect(page.locator('.tl-table')).toHaveCount(0);
  await expect(page.locator('.tl-kpi')).toHaveCount(0);
};

test('A7: fixture recs render as polished cards with real agents, live run time and source link via openExternal', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's5'], {}, { native: NATIVE });
  await openLive(page, 'recs');
  const cards = page.locator('#content .rcard[data-id]');
  await expect(cards).toHaveCount(6);
  await expect(page.locator('#main')).not.toContainText(MOCK_RECS);
  await expect(page.locator('.tbar')).not.toContainText('9 月 30 日 23:10');
  // the one rec with a saving estimate sorts first and prints it; the rest print 「—」, never 0
  await expect(cards.first()).toContainText('claude-api');
  await expect(cards.first().locator('.rc-save')).toContainText('省时2.6%');
  // J16 / B08: one-line card text, no 0-session evidence links or 0 个会话出现 on profile matches
  for (const t of await page.locator('#content .rc-why').allInnerTexts()) expect(t.length).toBeLessThan(160);
  await expect(page.locator('#content .recs .stack')).not.toContainText(/0 个会话|TRIGGER/);
  // real agents: Claude Code native, Codex native on claude-api; other targets are converted
  await cards.first().click();
  const detail = page.locator('#content .rc-kpis');
  await expect(detail).toContainText('所有 Agent');   // claude-api targets every agent in the fixture
  await expect(detail).toContainText('Kimi / Hermes / OpenCode 转为等价配置');
  await expect(detail).not.toContainText('Claude / ');
  await expect(page.locator('#content [data-tip^="适用"]').first()).not.toContainText(/Gemini|Copilot/);
  await page.locator('#content [data-act="recTab"][data-v="why"]').click();
  await expect(page.locator('#content .rc-dfoot-n')).toContainText('资源目录');
  await page.locator('#content .rc-dfoot-n [data-act="liOpen"]').click();
  const msgs = await page.evaluate(() => window.__nativeMsgs);
  expect(msgs.some((m) => m.type === 'openExternal' && /^https:\/\/github\.com\//.test(m.url))).toBe(true);
  await noPlainTables(page);
  expect(errors).toEqual([]);
});

test('A7: 预览并安装 runs the real sheet (candidate source) and apply → revert uses the preview digest', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's5']);
  const bodies = [];
  page.on('request', (r) => { if (r.method() === 'POST' && /\/v1\/install\//.test(r.url())) bodies.push({ path: new URL(r.url()).pathname, body: r.postDataJSON() }); });
  await openLive(page, 'recs');
  await page.locator('#content .rcard[data-id="252667ab78141eda"]').click();
  await page.locator('#content .rc-dfoot [data-act="install"]').click();
  const pv = page.locator('#modal [data-tl="inst-preview"]');
  await expect(pv).toBeVisible();
  const plan = bodies.find((b) => b.path === '/v1/install/plans');
  expect(plan.body.source).toEqual({ type: 'candidate', id: '252667ab78141eda' });
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instNext"]').click();
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instDo"]').click();
  await expect(page.locator('#modal [data-tl="inst-done"]')).toBeVisible();
  expect(bodies.find((b) => b.path === '/v1/install/apply').body.preview_digest).toBe('sha256:fx-digest-a');
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instClose"]').click();
  await expect(page.locator('#content .rcard[data-id="252667ab78141eda"]')).toContainText('已安装');
  // 撤销安装… → revert by install_id
  await page.locator('#content .rc-dfoot [data-act="uninstall"]').click();
  await page.locator('#modal [data-act="doUninstall"]').click();
  await expect.poll(() => gw.seen.some((s) => s.method === 'POST' && s.path === '/v1/install/inst-fx-1/revert')).toBe(true);
  await expect(page.locator('#content .rcard[data-id="252667ab78141eda"]')).not.toContainText('已安装');
  await noPlainTables(page);
  expect(errors).toEqual([]);
});

test('A7: 预览并安装 on a candidate whose plan needs a fetch resends the plan with fetch:true, never /v1/install/fetch (J02)', async ({ page }) => {
  const errors = collectErrors(page);
  const plan = fx('s5/install-plan.json'); let plans = 0;
  const gw = await stubGateway(page, ['core', 's5'], {
    'POST /v1/install/plans': () => (++plans === 1 ? Object.assign({}, plan, { status: 'needs_fetch', targets: [] }) : plan),
    'POST /v1/install/fetch': { status: 422, body: { error: { code: 'invalid_request', message: 'must not be called' } } }
  });
  const bodies = [];
  page.on('request', (r) => { if (r.method() === 'POST' && /\/v1\/install\//.test(r.url())) bodies.push({ path: new URL(r.url()).pathname, body: r.postDataJSON() }); });
  await openLive(page, 'recs');
  await page.locator('#content .rcard[data-id="252667ab78141eda"]').click();
  await page.locator('#content .rc-dfoot [data-act="install"]').click();
  await expect(page.locator('#modal [data-tl="inst-preview"]')).toBeVisible();
  expect(gw.count('/v1/install/fetch')).toBe(0);
  const ps = bodies.filter((b) => b.path === '/v1/install/plans').map((b) => b.body);
  expect(ps.map((b) => [b.source.type, b.source.id, !!b.fetch])).toEqual([['candidate', '252667ab78141eda', false], ['candidate', '252667ab78141eda', true]]);
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instNext"]').click();
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instDo"]').click();
  await expect(page.locator('#modal [data-tl="inst-done"]')).toBeVisible();
  expect(bodies.find((b) => b.path === '/v1/install/apply').body.surface).toBe('A7');
  expect(errors).toEqual([]);
});

test('A7: a link_only / unmappable plan shows the reason and the links open through openExternal (J02)', async ({ page }) => {
  const errors = collectErrors(page);
  const plan = fx('s5/install-plan.json');
  await stubGateway(page, ['core', 's5'], {
    'POST /v1/install/plans': Object.assign({}, plan, { status: 'link_only', targets: [], link_reason: 'no_install_declaration', links: ['https://example.com/fx-remedy'] })
  }, { native: NATIVE });
  await openLive(page, 'recs');
  await page.locator('#content .rcard[data-id="252667ab78141eda"]').click();
  await page.locator('#content .rc-dfoot [data-act="install"]').click();
  await expect(page.locator('#modal [data-tl="inst-manual"]')).toHaveAttribute('data-status', 'link_only');
  await expect(page.locator('#modal [data-tl="inst-reason"]')).toContainText('没有声明安装方式');
  await page.locator('#modal [data-tl="inst-manual"] [data-act="liOpen"]').click();
  await expect.poll(() => page.evaluate(() => window.__nativeMsgs.filter((m) => m.method === 'openExternal' || m.cmd === 'openExternal' || JSON.stringify(m).indexOf('openExternal') >= 0).length)).toBeGreaterThan(0);
  expect(errors).toEqual([]);
});

test('A7: 资料库推荐 / catalog_only cards sit in their own section after the evidence cards, clamped, without raw metadata (B07/B08)', async ({ page }) => {
  const errors = collectErrors(page);
  const recs = fx('s5/recs-full.json');
  const base = recs.items[0];
  const lib = (i) => Object.assign(JSON.parse(JSON.stringify(base)), { candidate_id: 'fxlib' + i, rec_key: 'catalog:fx-lib-' + i, bucket: '资料库推荐', basis: 'catalog_only', title: 'fx-lib-' + i,
    summary: 'fx-lib-' + i + '\nA long synthetic catalog description that keeps going for a while so it needs more than three lines on a narrow card, then more words, and more words again to be sure. agent: claude_code command: python domain: infra dimension: flow',
    evidence: { counts: { sessions: 0 }, session_uids: [] }, ui: Object.assign({}, base.ui, { why: null, title: 'fx-lib-' + i }) });
  const body = Object.assign({}, recs, { items: recs.items.concat([lib(1), lib(2)]), counts: Object.assign({}, recs.counts || {}, { library: 2 }) });
  await stubGateway(page, ['core', 's5'], { 'GET /v1/recommendations': body });
  await openLive(page, 'recs');
  const sec = page.locator('#content [data-tl="rec-lib"]');
  await expect(sec).toContainText('资料库推荐');
  await expect(sec).toContainText('2');
  // after every evidence card: the section header follows the last non-library card
  const order = await page.locator('#content .recs .stack > *').evaluateAll((els) => els.map((e) => e.dataset.tl === 'rec-lib' ? 'H' : e.classList.contains('rcard') ? (/^fxlib/.test(e.dataset.id) ? 'L' : 'E') : '-'));
  const h = order.indexOf('H');
  expect(h).toBeGreaterThan(0);
  expect(order.slice(h + 1).filter((x) => x === 'E')).toEqual([]);
  expect(order.slice(h + 1).filter((x) => x === 'L').length).toBe(2);
  const why = page.locator('#content .rcard[data-id="fxlib1"] [data-tl="rec-why"]');
  await expect(why).not.toContainText(/agent:|command:|dimension:|domain:/);
  // polled: under full-suite load the card can be re-rendered between resolving and reading the style (detached → '')
  await expect.poll(() => why.evaluate((e) => getComputedStyle(e).webkitLineClamp)).toBe('3');
  expect(errors).toEqual([]);
});

test('A9: 安装 on a reviewed AI artifact runs the same 预览并安装 sheet with source artifact and surface A9; 撤销 reverts by install_id (J02)', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's5']);
  const bodies = [];
  page.on('request', (r) => { if (r.method() === 'POST' && /\/v1\/install\//.test(r.url())) bodies.push({ path: new URL(r.url()).pathname, body: r.postDataJSON() }); });
  await openLive(page, 'overview');
  await page.evaluate(() => { S.studio.run = { done: true, stopped: false, installed: null, live: { id: 'job-fx' }, art: { artifact_id: 'art-fx-1', title: 'fx-artifact' } }; ACT.studioInstall(); });
  await expect(page.locator('#modal [data-tl="inst-preview"]')).toBeVisible();
  expect(bodies.find((b) => b.path === '/v1/install/plans').body.source).toEqual({ type: 'artifact', id: 'art-fx-1' });
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instNext"]').click();
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instDo"]').click();
  await expect(page.locator('#modal [data-tl="inst-done"]')).toBeVisible();
  expect(bodies.find((b) => b.path === '/v1/install/apply').body.surface).toBe('A9');
  expect(await page.evaluate(() => S.studio.run.liveInstall)).toBe('inst-fx-1');
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instClose"]').click();
  await page.evaluate(() => ACT.studioUndo());
  await expect.poll(() => gw.seen.some((s) => s.method === 'POST' && s.path === '/v1/install/inst-fx-1/revert')).toBe(true);
  await expect.poll(() => page.evaluate(() => S.studio.run.installed)).toBe(null);
  expect(errors).toEqual([]);
});

test('A7 cold start: no run → honest empty state; a missing endpoint → honest error; never the demo rows', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's5'], { 'GET /v1/recommendations': fx('s5/recs-empty.json') });
  await openLive(page, 'recs');
  await expect(page.locator('#content [data-tl="recs-empty"]')).toHaveAttribute('data-state', 'empty');
  await expect(page.locator('#content .rcard')).toHaveCount(0);
  await expect(page.locator('#main')).not.toContainText(MOCK_RECS);
  await expect(page.locator('#content [data-tl="sample"]')).toHaveCount(0);
  await page.evaluate(() => go('overview'));
  await expect(page.locator('#main')).not.toContainText(MOCK_RECS);
  // a fresh page whose endpoint is missing: honest error state (a later failure after live data keeps the last rows)
  gw.set('GET /v1/recommendations', { status: 404 });
  await page.reload();
  await expect.poll(() => page.evaluate(() => LV.state)).not.toBe('connecting');
  await page.evaluate(() => go('recs'));
  await expect(page.locator('#content [data-tl="recs-empty"]')).toHaveAttribute('data-state', 'error');
  await expect(page.locator('#main')).not.toContainText(MOCK_RECS);
  await expect(page.locator('#content [data-tl="sample"]')).toHaveCount(0);
  await noPlainTables(page);
  expect(errors).toEqual([]);
});

test('A8: 示例数据 only on seed items; first visit syncs the catalog once with progress; detail links use openExternal', async ({ page }) => {
  const errors = collectErrors(page);
  let job = 'running';
  const gw = await stubGateway(page, ['core', 's5'], {
    'GET /v1/catalog/status': () => (job === 'running' ? fx('s5/catalog-status-seed.json') : fx('s5/catalog-status-synced.json')),
    'POST /v1/catalog/sync': { status: 202, body: { job_id: 'job-fx-1', kind: 'sync', status: 'queued' } },
    'GET /v1/catalog/jobs/job-fx-1': () => ({ job_id: 'job-fx-1', kind: 'sync', status: job }),
    'GET /v1/catalog/items/seed%3Asystematic-debugging': fx('s5/catalog-item-seed.json')
  }, { native: NATIVE });
  await openLive(page, 'library');
  const lib = page.locator('[data-tl="library"]');
  await expect(lib.locator('.lb-card').first()).toBeVisible();
  // seed rows carry the badge, KB rows never do
  await expect(page.locator('[data-tl-item^="seed:"] [data-tl="sample"]').first()).toBeVisible();
  const kb = page.locator('[data-tl-item^="kb:"]');
  expect(await kb.count()).toBeGreaterThan(0);
  await expect(kb.locator('[data-tl="sample"]')).toHaveCount(0);
  // first-visit sync: one POST, progress banner, gone once the job completes
  await expect(page.locator('#content [data-tl="lib-sync"]')).toHaveAttribute('data-state', 'running');
  expect(gw.seen.filter((s) => s.method === 'POST' && s.path === '/v1/catalog/sync')).toHaveLength(1);
  job = 'completed';
  await expect(page.locator('#content [data-tl="lib-sync"]')).toHaveCount(0, { timeout: 8000 });
  await page.evaluate(() => render());
  expect(gw.seen.filter((s) => s.method === 'POST' && s.path === '/v1/catalog/sync')).toHaveLength(1);
  // detail: versions as polished rows, 查看来源 → openExternal
  await page.locator('[data-tl-item="seed:systematic-debugging"] [data-act="liDetail"]').first().click();
  await expect(page.locator('#modal [data-tl="lib-detail"]')).toBeVisible();
  await expect(page.locator('#modal [data-tl="lib-detail"] .lb-desc')).not.toBeEmpty();
  await page.locator('#modal .mf [data-act="liOpen"]').click();
  const msgs = await page.evaluate(() => window.__nativeMsgs);
  expect(msgs.some((m) => m.type === 'openExternal' && m.url === 'https://github.com/obra/superpowers')).toBe(true);
  await noPlainTables(page);
  expect(errors).toEqual([]);
});

test('A8: a synced catalog never triggers a sync; the 已安装 sheet shows only real installs (none) even when install routes fail', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's5'], { 'GET /v1/install/state': { status: 503 }, 'GET /v1/install/ledger': { status: 503 } });
  await openLive(page, 'library');
  await expect(page.locator('[data-tl="library"] .lb-card').first()).toBeVisible();
  await page.waitForTimeout(300);
  expect(gw.seen.some((s) => s.path === '/v1/catalog/sync')).toBe(false);
  await page.locator('[data-act="libInstalled"]').click();
  await expect(page.locator('#modal [data-tl="installed"]')).toContainText('暂不可用');
  await expect(page.locator('#modal')).not.toContainText(/design-review|surge-cli|gh-helper/);
  await expect(page.locator('#modal [data-tl="sample"]')).toHaveCount(0);
  expect(errors.filter((e) => !/503/.test(e))).toEqual([]);
});

test('empty spine: recs and library render without page errors', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's5'], { 'GET /v1/uiview/facts': fx('core/facts-empty.json'), 'GET /v1/recommendations': fx('s5/recs-empty.json') });
  await openLive(page, 'recs');
  await expect(page.locator('#content [data-tl="recs-empty"]')).toBeVisible();
  for (const r of ['library', 'overview', 'recs']) {
    await page.evaluate((x) => go(x), r);
    await expect(page.locator('#content')).not.toBeEmpty();
  }
  await expect(page.locator('#main')).not.toContainText(MOCK_RECS);
  await noPlainTables(page);
  expect(errors).toEqual([]);
});

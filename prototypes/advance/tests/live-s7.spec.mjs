// Slice 7 (first run + native layout): live onboarding on /v1/app/state · /v1/shell/onboarding · /v1/app/discovery,
// 添加文件夹 (browser path field and native chooseFolder) → POST /v1/app/sources, 开始分析 → POST /v1/app/jobs, job progress
// drives the four stages, then the spine reloads and Genesis plays the server persona; settings onboarded:true + catalog sync.
// Native: body.native hides the fake desktop, #win fills the viewport, window ops / tandem:command go through the bridge.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const JOB = '10951bad4daa4a2fb0994de1f0d61e09';
const NATIVE = { v: 1, app: '0.0.1', platform: 'macos', features: ['chooseFolder', 'save', 'openExternal', 'reveal', 'window'] };
const clock = (page) => page.clock.setFixedTime(new Date('2026-10-03T12:00:00+08:00'));
const noPlain = async (page) => expect(await page.locator('.tl-table, .tl-kpi').count()).toBe(0);

function firstRun(extra) {
  const posted = { sources: [], settings: [], jobs: [] };
  const map = Object.assign({
    'GET /v1/uiview/facts': fx('core/facts-empty.json'),
    'POST /v1/app/sources': (req) => { const b = JSON.parse(req.postData() || '{}'); posted.sources.push(b); return { id: 'source_new_' + b.agent, agent: b.agent, root: b.root, enabled: b.enabled }; },
    'PATCH /v1/app/settings': (req) => { const b = JSON.parse(req.postData() || '{}'); posted.settings.push(b); return Object.assign({ onboarded: false, recent_days: 90 }, b); },
    'POST /v1/app/jobs': (req) => { posted.jobs.push(JSON.parse(req.postData() || '{}')); return { status: 202, body: fx('s7/job-queued.json') }; },
    ['GET /v1/app/jobs/' + JOB]: fx('s7/job-running.json'),
    'POST /v1/catalog/sync': { status: 202, body: { accepted: true } }
  }, extra || {});
  return { map, posted };
}

test.skip(!!PASS, 'first-run flow writes sources and jobs; run it against the stub only');

test('first run: readiness absent opens onboarding; sources and estimates come from the gateway', async ({ page }) => {
  await clock(page);
  const errors = collectErrors(page);
  const { map } = firstRun();
  const gw = await stubGateway(page, ['core', 's7'], map);
  await openLive(page, 'overview');
  await expect(page.locator('#overlay .obox')).toBeVisible();
  expect(await page.evaluate(() => OVL)).toBe('ob');
  await page.locator('#overlay [data-act="obNext"]').click();
  const rows = page.locator('#overlay [data-ob="sources"] label.srcrow');
  await expect(rows).toHaveCount(8);
  await expect(page.locator('#overlay')).toContainText('Claude Code');
  await expect(page.locator('#overlay')).toContainText('/fx/fx-src/codex');
  await expect(page.locator('#overlay')).not.toContainText('Cursor');
  await expect(page.locator('#overlay input[data-chg="obSrcL"]:checked')).toHaveCount(7);
  await expect(page.locator('#overlay [data-ob="total"]')).toContainText('约 103 个会话');
  // unticking a source updates the estimate
  await page.locator('#overlay input[data-s="source_826dcf0ea8f066b054f4b91ef3f3876752adee20dafa1f4a0b7688898737ae6b"]').uncheck();
  await expect(page.locator('#overlay [data-ob="total"]')).toContainText('约 95 个会话');
  expect(gw.count('/v1/shell/onboarding')).toBeGreaterThan(0);
  expect(gw.count('/v1/app/state')).toBeGreaterThan(0);
  await noPlain(page);
  expect(errors).toEqual([]);
});

test('first run: no auto onboarding once the store is ready and sources are enabled', async ({ page }) => {
  await clock(page);
  await stubGateway(page, ['core', 's7'], { 'GET /v1/app/state': fx('s7/app-state-full.json') });
  await openLive(page, 'overview');
  await page.waitForTimeout(400);
  expect(await page.evaluate(() => OVL)).toBe(null);
});

test('first run: 添加文件夹 (browser path field) → POST /v1/app/sources; 开始分析 → job → four stages → Genesis with the server persona', async ({ page }) => {
  await clock(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = collectErrors(page);
  const { map, posted } = firstRun();
  const gw = await stubGateway(page, ['core', 's7'], map);
  await openLive(page, 'overview');
  await page.locator('#overlay [data-act="obNext"]').click();
  await expect(page.locator('#overlay label.srcrow')).toHaveCount(8);
  // browser fallback: the path text field; the agent is inferred from the path
  await page.locator('#obPath').fill('/fx/extra/.kimi/sessions');
  await page.locator('#overlay [data-act="obAddFolder"]').click();
  await expect.poll(() => posted.sources.length).toBe(1);
  expect(posted.sources[0]).toEqual({ agent: 'kimi', root: '/fx/extra/.kimi/sessions', enabled: true });
  // 开始分析
  await page.locator('#overlay [data-act="obStart"]').click();
  await expect(page.locator('#overlay [data-ob="stages"] .step')).toHaveCount(4);
  await expect.poll(() => posted.jobs.length).toBe(1);
  expect(posted.jobs[0].kind).toBe('import');
  expect(posted.jobs[0].source_ids.length).toBeGreaterThanOrEqual(7);
  expect(posted.settings[0]).toMatchObject({ recent_days: 90 });
  // the selected sources got enabled before the job
  expect(posted.sources.filter((b) => b.enabled).length).toBeGreaterThanOrEqual(8);
  // job progress (polled; frames do the same) → backfill stage 3 / 8
  await expect(page.locator('#overlay [data-stage="backfill"]')).toHaveAttribute('data-st', 'running');
  await expect(page.locator('#overlay [data-stage="backfill"]')).toContainText('3 / 8', { timeout: 5000 });
  await expect(page.locator('#overlay [data-stage="semantic"]')).toHaveAttribute('data-st', 'skipped');
  // published: spine fills, Genesis plays (reduced motion → final state) with the server persona
  gw.set('GET /v1/uiview/facts', fx('core/facts.json'));
  gw.set('GET /v1/app/jobs/' + JOB, fx('s7/job-completed.json'));
  await expect(page.locator('#genBox')).toBeVisible({ timeout: 10_000 });
  await expect(page.locator('#genBox [data-g="code"]')).toHaveAttribute('aria-label', 'SIMT');
  await expect(page.locator('#genBox')).toContainText('即兴乐手');
  await expect(page.locator('#genBox [data-g="count"]')).toContainText('26 个会话');
  expect(await page.evaluate(() => ALL.length)).toBe(26);
  await expect.poll(() => posted.settings.some((b) => b.onboarded === true)).toBe(true);
  await expect.poll(() => gw.count('/v1/catalog/sync')).toBe(1);
  // 查看完整画像 lands on the persona page
  await page.locator('#genBox [data-act="obDone"]').click();
  await expect(page.locator('#overlay')).toBeHidden();
  expect(await page.evaluate(() => S.route)).toBe('persona');
  await noPlain(page);
  expect(errors).toEqual([]);
});

test('first run: Genesis motion runs on real rows (particles, needle, letters lock to the server code)', async ({ page }) => {
  await clock(page);
  const errors = collectErrors(page);
  const { map } = firstRun({ 'POST /v1/app/jobs': { status: 202, body: fx('s7/job-completed.json') }, ['GET /v1/app/jobs/' + JOB]: fx('s7/job-completed.json') });
  const gw = await stubGateway(page, ['core', 's7'], map);
  await openLive(page, 'overview');
  await page.locator('#overlay [data-act="obNext"]').click();
  await expect(page.locator('#overlay label.srcrow')).toHaveCount(8);
  gw.set('GET /v1/uiview/facts', fx('core/facts.json'));
  await page.locator('#overlay [data-act="obStart"]').click();
  await expect(page.locator('#genBox.run')).toBeVisible({ timeout: 10_000 });
  // mid-sequence: canvas particles and the morph from the source list are live
  expect(await page.evaluate(() => !!GNS && GNS.mode === 'ob' && GNS.L.length === 26 && GNS.p.code === 'SIMT' && GNS.cands[0].c === 'SIMT')).toBe(true);
  await expect(page.locator('#genBox.skip')).toBeVisible({ timeout: 12_000 });
  await expect(page.locator('#genBox [data-g="code"] .L')).toHaveText(['S', 'I', 'M', 'T']);
  expect(errors).toEqual([]);
});

test('re-entering onboarding from settings reloads the live sources', async ({ page }) => {
  await clock(page);
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's7'], { 'GET /v1/app/state': fx('s7/app-state-full.json') });
  await openLive(page, 'overview');
  await page.evaluate(() => openOnboarding(0));
  await page.locator('#overlay [data-act="obNext"]').click();
  await expect(page.locator('#overlay label.srcrow')).toHaveCount(8);
  await expect(page.locator('#overlay [data-act="obAddFolder"]')).toBeVisible();
  expect(errors).toEqual([]);
});

test('native: body.native hides the fake desktop, #win fills the viewport, window ops post to the host', async ({ page }) => {
  await clock(page);
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's7'], { 'GET /v1/app/state': fx('s7/app-state-full.json') }, { native: NATIVE });
  await openLive(page, 'overview');
  await expect(page.locator('body')).toHaveClass(/\bnative\b/);
  for (const sel of ['#mbar', '.wall', '#widgets', '#win .lights', '#hud']) await expect(page.locator(sel).first()).toBeHidden();
  const vp = page.viewportSize();
  const box = await page.locator('#win').boundingBox();
  expect(box).toEqual({ x: 0, y: 0, width: vp.width, height: vp.height });
  expect(await page.evaluate(() => $('#win').dataset.mode)).toBe('native');
  const inset = await page.evaluate(() => getComputedStyle($('#main')).paddingTop);
  expect(inset).toBe('28px');
  const types = () => page.evaluate(() => window.__nativeMsgs.map((m) => m.type));
  await page.keyboard.press('Meta+m');
  await page.keyboard.press('Control+Meta+f');
  await page.locator('#main .tbar h1').dblclick();
  await page.evaluate(() => ACT.winClose());
  expect(await types()).toEqual(['minimize', 'fullscreen', 'zoom', 'close']);
  // the window never moved / went away inside the page
  expect(await page.evaluate(() => ({ gone: S.winGone, full: S.win.full, zoom: !!S.win.zoom }))).toEqual({ gone: false, full: false, zoom: false });
  // ⌘2 switches pages like ⌥2 in the browser demo
  await page.keyboard.press('Meta+2');
  expect(await page.evaluate(() => S.route === navRoutes()[1][0])).toBe(true);
  await noPlain(page);
  expect(errors).toEqual([]);
});

test('native: tandem:command settings / palette / about / route / toggleEdition / refresh', async ({ page }) => {
  await clock(page);
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's7'], { 'GET /v1/app/state': fx('s7/app-state-full.json') }, { native: NATIVE });
  await openLive(page, 'overview');
  const cmd = (d) => page.evaluate((x) => window.dispatchEvent(new CustomEvent('tandem:command', { detail: x })), d);
  await cmd({ cmd: 'about' });
  await expect(page.locator('#modal')).toBeVisible();
  await expect(page.locator('#modal [data-about="version"]')).toHaveText('0.0.1');
  await expect(page.locator('#modal [data-about="rows"]')).toContainText('Kimi CLI');
  await cmd({ cmd: 'palette' });
  expect(await page.evaluate(() => MODAL_KEY)).toBe('palette');
  // (settings › 数据源 is slice 6's: its SRC_ST table still lacks the new agents, so open on 通用)
  await page.evaluate(() => { S.setTab = 'general'; });
  await cmd({ cmd: 'settings' });
  await expect(page.locator('#set')).toBeVisible();
  await cmd({ cmd: 'route', route: 'tools' });
  expect(await page.evaluate(() => S.route)).toBe('tools');
  const before = gw.count('/v1/uiview/facts');
  await cmd({ cmd: 'refresh' });
  await expect.poll(() => gw.count('/v1/uiview/facts')).toBeGreaterThan(before);
  await cmd({ cmd: 'route', route: 'overview' });
  await cmd({ cmd: 'toggleEdition' });
  await expect.poll(() => page.evaluate(() => S.ed)).toBe('lite');
  // keys sheet shows the App keys, not the browser stand-ins
  await page.evaluate(() => openKeys());
  await expect(page.locator('#modal')).toContainText('⌘1–9');
  await expect(page.locator('#modal')).not.toContainText('App 内');
  expect(errors).toEqual([]);
});

test('native: 添加文件夹 asks the host (chooseFolder) and posts the picked folder', async ({ page }) => {
  await clock(page);
  const errors = collectErrors(page);
  const { map, posted } = firstRun();
  await stubGateway(page, ['core', 's7'], map, { native: NATIVE });
  await openLive(page, 'overview');
  await page.locator('#overlay [data-act="obNext"]').click();
  await expect(page.locator('#overlay label.srcrow')).toHaveCount(8);
  await expect(page.locator('#obPath')).toHaveCount(0);
  await page.locator('#overlay select.ob-agent').selectOption('hermes');
  await page.locator('#overlay [data-act="obAddFolder"]').click();
  await expect.poll(() => page.evaluate(() => window.__nativeMsgs.filter((m) => m.type === 'chooseFolder').length)).toBe(1);
  const msg = await page.evaluate(() => window.__nativeMsgs.find((m) => m.type === 'chooseFolder'));
  expect(msg).toMatchObject({ type: 'chooseFolder', purpose: 'source', agent: 'hermes' });
  expect(typeof msg.id).toBe('string');
  await page.evaluate((id) => window.dispatchEvent(new CustomEvent('tandem:folder', { detail: { id, path: '/fx/picked/hermes-home', cancelled: false } })), msg.id);
  await expect.poll(() => posted.sources.length).toBe(1);
  expect(posted.sources[0]).toEqual({ agent: 'hermes', root: '/fx/picked/hermes-home', enabled: true });
  expect(errors).toEqual([]);
});

test('about in live without the route: honest empty state, no demo copy', async ({ page }) => {
  await clock(page);
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's7'], { 'GET /v1/app/state': fx('s7/app-state-full.json'), 'GET /v1/app/about': { status: 404 } });
  await openLive(page, 'overview');
  await page.evaluate(() => openAbout());
  await expect(page.locator('#modal [data-lv="na"]')).toBeVisible();
  await expect(page.locator('#modal')).not.toContainText('这个 Demo');
  expect(errors).toEqual([]);
});

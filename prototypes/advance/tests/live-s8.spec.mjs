// Slice 8 (src/js/98-live-ops.js + 55 / 60 / 61 / 62 / 70): surfaces, menu-bar panel, HUD, widgets, sim off, exports via the
// native save bridge, A3 ops, A4 call drill-down. Fixtures: core (spine) + s8 (popover, attention, ops, export).
//  1. realtime   snapshot → HUD pill / card, panel (failing, ctx, waiting on a real Kimi session), widgets; 忽略 → dismiss;
//                no demo session text anywhere; a stream frame calms everything down
//  2. calm       no realtime route: HUD hidden, panel from /v1/shell/popover (real date, top rec), sim menu off
//  3. surfaces   ?surface=panel | hud | widgets render only that component, post resizeSurface / openMain
//  4. export     report .md / CSV / share PNG → save {filename, mime, bytes}; tandem:saved → 在 Finder 中显示 → reveal; 404 → toast
//  5. A3 / A4    resume command, raw log → reveal, exclude with a reason, tool row → real calls
import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { stubGateway, openLive, collectErrors, fx, FIXTURES } from './live-helpers.mjs';

const NOW = Date.parse('2026-10-03T12:00:00+08:00');
const NATIVE = { v: 1, app: '0.0.1', platform: 'macos', features: ['chooseFolder', 'save', 'openExternal', 'reveal', 'window'] };
const ONLY = () => test.skip(test.info().project.name !== 'mac-14', 'runs once, at the default size');
const MOCK_TEXT = /team-hub|Hackathon|latentskill|Surge|confluo|Gemini|Copilot|10 月 1 日/;
// realtime fixtures carry absolute timestamps: move them so generated_at is the pinned clock
function rtAt(name) {
  const o = fx('s8/' + name); const dt = NOW - o.generated_at; const mv = (x) => (typeof x === 'number' ? x + dt : x);
  o.generated_at += dt;
  o.sessions.forEach((s) => { s.since = mv(s.since); if (s.lanes) Object.keys(s.lanes).forEach((k) => { s.lanes[k] = s.lanes[k].map(mv); }); });
  return o;
}
const SID = 'session_fx026';
async function setup(page, extra, opts) {
  await page.clock.setFixedTime(new Date(NOW));
  const gw = await stubGateway(page, ['core', 's8'], Object.assign({
    'GET /v1/analytics/realtime': () => rtAt('realtime-active.json'),
    'GET /v1/analytics/realtime/stream': { status: 404 },
    'POST /v1/analytics/realtime/fx-rt-fail/dismiss': fx('s8/dismiss.json')
  }, extra || {}), opts);
  return gw;
}
const msgs = (page, type) => page.evaluate((t) => (window.__nativeMsgs || []).filter((m) => m.type === t), type);

test('realtime: HUD, panel and widgets name the real sessions; 忽略 dismisses; no demo text', async ({ page }) => {
  ONLY();
  const errors = collectErrors(page);
  const gw = await setup(page);
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => [S.simBase, S.attn.has('stuck'), S.attn.has('ctx'), S.waitOpen])).toEqual(['running', true, true, true]);
  await page.evaluate(() => { S.widgets = true; render(); });
  await expect(page.locator('#hudPill')).toContainText('同一命令失败 5 次');
  await expect(page.locator('#hudPill')).toContainText('fx-rules');
  expect(await page.evaluate(() => [S.live.ctx, S.live.tools, HUD_TOOLS[0]])).toEqual([91, 9, 'Edit src/js/98-live-ops.js']);
  await page.evaluate(() => { S.pop = true; render(); });
  const pop = page.locator('#pop');
  await expect(pop.locator('[data-tl="rt-failing"]')).toContainText('make publish');
  await expect(pop.locator('[data-tl="rt-ctx"]')).toContainText('91%');
  await expect(pop.locator('[data-tl="rt-live"]')).toContainText('合成会话：整理 HUD 绑定');
  await expect(pop).toContainText('10 月 3 日 周六');
  await pop.locator('[data-tl="rt-failing"] [data-act="popIgnore"]').click();
  await expect.poll(() => gw.seen.filter((s) => s.method === 'POST' && s.path === '/v1/analytics/realtime/fx-rt-fail/dismiss').length).toBe(1);
  // HUD card: the waiting session is Kimi (real id → real name), not the demo's Codex · team-hub
  await page.evaluate(() => { S.pop = false; S.attn.clear(); S.hud.open = true; S.hudSim = 'running'; S.waitOpen = false; TLO.d.failing.length = 0; TLO.d.ctx.length = 0; renderHud(); });
  const card = page.locator('#hud .hcard[data-tl="rt-hud"]');
  await expect(card).toContainText('合成会话：整理 HUD 绑定');
  await expect(card).toContainText('Claude Code');
  await expect(card).toContainText('Kimi · fx-hub');
  for (const sel of ['#pop', '#hud', '#widgets']) expect(await page.locator(sel).innerText()).not.toMatch(MOCK_TEXT);
  await expect(page.locator('#widgets [data-r="sessions"] .mono').first()).toHaveText('7');
  expect(await page.locator('.tl-table, .tl-kpi').count()).toBe(0);
  expect(errors).toEqual([]);
});

test('calm: without realtime the HUD stays hidden, the panel uses /v1/shell/popover, the sim menu is off', async ({ page }) => {
  ONLY();
  const errors = collectErrors(page);
  await setup(page, { 'GET /v1/analytics/realtime': { status: 404 } });
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => TLO.off)).toBe(true);
  await expect(page.locator('#hud')).toBeHidden();
  await page.evaluate(() => { S.pop = true; render(); });
  const pop = page.locator('#pop');
  await expect(pop).toContainText('10 月 3 日 周六');
  await expect(pop).toContainText('昨天 · 10 月 2 日');
  expect(await pop.innerText()).not.toMatch(MOCK_TEXT);
  expect(await pop.locator('[data-tl="opening"]').count()).toBe(0);
  await page.evaluate(() => simEvent('waiting'));
  await expect(page.locator('#toast')).toContainText('实时模式不模拟事件');
  expect(await page.evaluate(() => [S.waitOpen, MENUS.demo().some((x) => /会话完成/.test(x.t || ''))])).toEqual([false, false]);
  expect(errors).toEqual([]);
});

for (const sf of ['panel', 'hud', 'widgets']) {
  test('surface ' + sf + ': only that component, transparent, resizeSurface + openMain', async ({ page }) => {
    ONLY();
    const errors = collectErrors(page);
    await setup(page, {}, { native: NATIVE });
    await page.goto('http://tandem.test/app?live=1&surface=' + sf);
    await expect.poll(() => page.evaluate(() => LV.state), { timeout: 10_000 }).not.toBe('connecting');
    expect(await page.evaluate(() => document.body.className)).toContain('surface-' + sf);
    expect(await page.evaluate(() => document.body.classList.contains('native'))).toBe(true);
    await expect(page.locator('#win')).toBeHidden();
    await expect(page.locator('#mbar')).toBeHidden();
    expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
    const keep = { panel: '#pop', hud: '#hud', widgets: '#widgets' }[sf];
    await expect(page.locator(keep)).toBeVisible();
    await expect.poll(async () => (await msgs(page, 'resizeSurface')).length).toBeGreaterThan(0);
    expect((await msgs(page, 'resizeSurface')).at(-1).height).toBeGreaterThan(20);
    if (sf === 'panel') {
      await page.locator('#pop [data-act="popOpen"]').click();
      await expect.poll(async () => (await msgs(page, 'openMain')).length).toBe(1);
    } else if (sf === 'hud') {
      await expect(page.locator('#hudPill')).toBeVisible();
      const h0 = (await msgs(page, 'resizeSurface')).at(-1).height;
      await page.evaluate(() => { S.hud.open = true; render(); });
      await expect.poll(async () => (await msgs(page, 'resizeSurface')).at(-1).height).toBeGreaterThan(h0);
      await page.evaluate(() => { S.hudSim = 'running'; TLO.d.failing.length = 0; render(); });
      await page.locator('#hud [data-act="hudTraj"]').click();
      await expect.poll(async () => (await msgs(page, 'openMain')).map((m) => m.route)).toEqual(['sessions/fx-rt-run']);
    } else {
      await page.locator('#widgets [data-act="wgGo"][data-r="persona"]').click();
      await expect.poll(async () => (await msgs(page, 'openMain')).map((m) => m.route)).toEqual(['persona']);
    }
    expect(errors).toEqual([]);
  });
}

test('export: report / CSV / share PNG go through save; tandem:saved offers 在 Finder 中显示 → reveal', async ({ page }) => {
  ONLY();
  const errors = collectErrors(page);
  const csv = fs.readFileSync(path.join(FIXTURES, 's8', 'export-csv.csv'), 'utf8');
  await setup(page, {}, { native: NATIVE });
  await page.route(/\/v1\/export\/csv/, (r) => r.fulfill({ status: 200, contentType: 'text/csv; charset=utf-8', body: csv }));
  await openLive(page, 'overview');
  await page.evaluate(() => openReport());
  await expect(page.locator('#repText')).toHaveValue(/合成样本/);
  await page.locator('#modal [data-act="repSave"]').click();
  await expect.poll(async () => (await msgs(page, 'save')).length).toBe(1);
  const s1 = (await msgs(page, 'save'))[0];
  expect(s1.filename).toBe('orbit-report-2026-10-03.md');
  expect(s1.mime).toBe('text/markdown');
  expect(s1.text).toContain('合成样本');
  await page.evaluate((id) => window.dispatchEvent(new CustomEvent('tandem:saved', { detail: { id, ok: true, path: '/Users/fx/Downloads/orbit-report-2026-10-03.md' } })), s1.id);
  await expect(page.locator('#toast')).toContainText('在 Finder 中显示');
  await page.locator('#toast [data-act="toastAct"]').click();
  await expect.poll(async () => (await msgs(page, 'reveal')).map((m) => m.path)).toEqual(['/Users/fx/Downloads/orbit-report-2026-10-03.md']);
  await page.evaluate(() => { closeModal(); openCSV(); });
  await expect(page.locator('#modal textarea[data-tl="csv"]')).toHaveValue(/fx-call-2,fx-s2,Bash,failed/);
  await page.locator('#modal [data-act="csvSave"]').click();
  await expect.poll(async () => (await msgs(page, 'save')).length).toBe(2);
  const s2 = (await msgs(page, 'save'))[1];
  expect([s2.filename, s2.mime, s2.text]).toEqual(['orbit-tool-calls-2026-10-03.csv', 'text/csv', csv]);
  await page.evaluate(() => { closeModal(); openShare(); });
  await expect(page.locator('#modal [data-tl="share-card"]')).toContainText('指挥家');
  await page.locator('#modal [data-act="shareSave"]').click();
  await expect.poll(async () => (await msgs(page, 'save')).length, { timeout: 10_000 }).toBe(3);
  const s3 = (await msgs(page, 'save'))[2];
  expect([s3.filename, s3.mime]).toEqual(['orbit-persona-DIMV-2026-10-03.png', 'image/png']);
  const png = Buffer.from(s3.base64, 'base64');
  expect(png.subarray(1, 4).toString()).toBe('PNG');
  expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([1080, 1350]);
  // a cancelled save says nothing
  await page.evaluate((id) => window.dispatchEvent(new CustomEvent('tandem:saved', { detail: { id, ok: false, cancelled: true } })), s3.id);
  expect(errors).toEqual([]);
});

test('export 404: honest toast, no demo report or card', async ({ page }) => {
  ONLY();
  const errors = collectErrors(page);
  await setup(page, { 'POST /v1/export/report': { status: 404 }, 'POST /v1/export/share_card': { status: 404 } });
  await openLive(page, 'overview');
  await page.evaluate(() => openReport());
  await expect(page.locator('#toast')).toContainText('本地服务暂不支持导出报告');
  expect(await page.evaluate(() => [MODAL_KEY, !!document.querySelector('#repText')])).toEqual([null, false]);
  await page.evaluate(() => openShare());
  await expect(page.locator('#toast')).toContainText('暂时不能生成分享卡');
  expect(await page.evaluate(() => MODAL_KEY)).toBe(null);
  expect(errors).toEqual([]);
});

test('A3 / A4: resume command, raw log → reveal, exclude with a reason, tool row lists real calls', async ({ page }) => {
  ONLY();
  const errors = collectErrors(page);
  const gw = await setup(page, {
    ['GET /v1/sessions/' + SID + '/resume']: fx('s8/resume.json'),
    ['GET /v1/sessions/' + SID + '/source_location']: fx('s8/source-location.json'),
    ['POST /v1/sessions/' + SID + '/exclude']: fx('s8/exclude.json')
  }, { native: NATIVE });
  await openLive(page, 'sessions');
  await page.evaluate((id) => { S.sess.sel = id; S.sess.mode = 'single'; render(); }, SID);
  await page.evaluate(() => ACT.resume());
  await expect(page.locator('#modal [data-tl="resume"]')).toContainText("claude --resume fx-native-1");
  await page.evaluate(() => { closeModal(); ACT.tlOpenLog(); });
  await expect.poll(async () => (await msgs(page, 'reveal')).map((m) => m.path)).toEqual(['/tmp/fx-home/.claude/projects/fx/fx-native-1.jsonl']);
  await page.locator('[data-act="sessMore"]').first().click();
  await page.locator('#dd').getByRole('menuitem', { name: '标记为不计入分析' }).click();
  await page.locator('#dd').getByRole('menuitem', { name: '测试会话' }).click();
  await expect.poll(() => gw.seen.filter((s) => s.method === 'POST' && s.path === '/v1/sessions/' + SID + '/exclude').length).toBe(1);
  await expect.poll(() => page.evaluate((id) => S.excluded.has(id), SID)).toBe(true);
  // A4: the expanded row of the first tool lists the gateway's calls
  await page.evaluate(() => go('tools'));
  const first = page.locator('#main tr[data-act="toggleTool"]').first();
  if (await first.count()) {
    await first.click();
    await expect(page.locator('#main [data-tl="tool-calls"] [data-tl="call"]').first()).toBeVisible();
    await expect(page.locator('#main [data-tl="tool-calls"]')).toContainText('pnpm');
  }
  expect(await page.locator('.tl-table, .tl-kpi').count()).toBe(0);
  expect(errors).toEqual([]);
});

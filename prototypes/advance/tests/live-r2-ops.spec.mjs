// Round 2 · ops regressions (98-live-ops.js, 55-exports.js, 85-keyboard.js):
//  J15  user-visible brand is Orbit: report title, share card wordmark (the Orbit·知音 vector in HTML and PNG), report / CSV / PNG file names
//  H4   ⇧⌘E opens the report sheet after the settings window was opened and closed (focus left on a hidden control)
//  B18  exports carry the scope the screen shows: report body.scope (from_ts / source_ids / project_ids), CSV query
//       (from_ts / agent / project_id)
import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { stubGateway, openLive, collectErrors, fx, FIXTURES } from './live-helpers.mjs';
import { openDemo } from './helpers.mjs';

const NOW = Date.parse('2026-10-03T12:00:00+08:00');
const NATIVE = { v: 1, app: '0.0.1', platform: 'macos', features: ['chooseFolder', 'save', 'openExternal', 'reveal', 'window'] };
const ONLY = () => test.skip(test.info().project.name !== 'mac-14', 'runs once, at the default size');
const msgs = (page, type) => page.evaluate((t) => (window.__nativeMsgs || []).filter((m) => m.type === t), type);
async function setup(page, extra, opts) {
  await page.clock.setFixedTime(new Date(NOW));
  return stubGateway(page, ['core', 's8'], Object.assign({
    'GET /v1/analytics/realtime': { status: 404 }, 'GET /v1/analytics/realtime/stream': { status: 404 }
  }, extra || {}), opts);
}

test('J15 mock: report title, share card wordmark and its PNG say Orbit, never Tandem', async ({ page }) => {
  ONLY();
  await openDemo(page);
  const r = await page.evaluate(() => {
    const md = reportMD(); const sp = sharePersona(); const card = shareCard(sp);
    return { head: md.split('\n')[0], md, card, model: JSON.stringify(shareModel(sp)) };
  });
  expect(r.head).toMatch(/^# Orbit 协作报告/);
  expect(r.md).not.toMatch(/Tandem|同频/i);
  // the wordmark is the published Orbit·知音 vector (docs/design/logo/kit/wordmark), not typed text
  expect(r.card).toContain('aria-label="Orbit·知音" data-wordmark="1"');
  expect(r.card).not.toMatch(/tandem|同频/i);
  expect(r.model).not.toMatch(/tandem|同频/i);
  // the PNG draws its wordmark with fillText: record the strings
  const drawn = await page.evaluate(async () => {
    const out = []; const f = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function (t, ...a) { out.push(String(t)); return f.call(this, t, ...a); };
    try { await sharePNG(shareModel(sharePersona()), false, false); } finally { CanvasRenderingContext2D.prototype.fillText = f; }
    return out;
  });
  expect(drawn.length).toBeGreaterThan(5);
  expect(drawn.join('\n')).not.toMatch(/tandem|同频/i);
});

test('J15 live: report fixture title and saved file names are Orbit', async ({ page }) => {
  ONLY();
  const errors = collectErrors(page);
  await setup(page, {}, { native: NATIVE });
  await openLive(page, 'overview');
  await page.evaluate(() => openReport());
  await expect(page.locator('#repText')).toHaveValue(/^# Orbit 协作报告/);
  expect(await page.locator('#repText').inputValue()).not.toMatch(/Tandem/);
  await page.locator('#modal [data-act="repSave"]').click();
  await expect.poll(async () => (await msgs(page, 'save')).length).toBe(1);
  expect((await msgs(page, 'save'))[0].filename).toMatch(/^orbit-report-\d{4}-\d{2}-\d{2}\.md$/);
  // offline banner (shared adapter) names Orbit
  expect(await page.evaluate(() => TandemLive.ui.banner({ mode: 'live', error: { code: 'network' } }))).toContain('无法连接 Orbit 本地服务');
  expect(errors).toEqual([]);
});

test('J15 Lite: sessions CSV, report and persona SVG downloads are orbit-*-<day>, no visible Tandem / 同频', async ({ page }) => {
  ONLY();
  const html = fs.readFileSync(path.join(FIXTURES, '..', '..', 'lite', 'tandem-benchmark-demo.html'), 'utf8');
  expect(html).not.toContain("download('tandem-");
  expect(html).toContain("download('orbit-sessions-'+new Date().toLocaleDateString('sv-SE')+'.csv'");
  expect(html).toContain("download('orbit-persona-'+new Date().toLocaleDateString('sv-SE')+'.svg'");
  expect(html).toContain("download('orbit-report-'+new Date().toLocaleDateString('sv-SE')+'.md'");
  expect(new Date(NOW).toLocaleDateString('sv-SE')).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.goto('file://' + path.join(FIXTURES, '..', '..', 'lite', 'tandem-benchmark-demo.html'));
  await page.waitForTimeout(500);
  const txt = await page.evaluate(() => document.title + '\n' + document.body.innerText);
  expect(txt).not.toMatch(/Tandem|同频|TANDEM/);
});

test('H4: ⇧⌘E / ⇧⌘S open their sheet at once while the gateway is still assembling (slow /v1/export/*)', async ({ page }) => {
  ONLY();
  const errors = collectErrors(page);
  // the journey hit the export right after settings changed the scope: the gateway waited ~3 s on fresh sections and the
  // sheet only appeared after the step had given up. Reproduce with a 2.5 s answer.
  await setup(page, {
    'POST /v1/export/report': { delay: 2500, body: fx('s8/export-report.json') },
    'POST /v1/export/share_card': { delay: 2500, body: fx('s8/export-share-card.json') }
  }, { native: NATIVE });
  await openLive(page, 'tools');
  await page.evaluate(() => { openSettings('about'); });
  await page.evaluate(() => { const b = document.querySelector('#set button'); if (b) b.focus(); closeModal(); closeSettings(); });
  await page.keyboard.press('Meta+Shift+e');
  await expect(page.locator('#repText[data-tl="report-pending"]')).toBeVisible({ timeout: 800 });
  await expect(page.locator('#modal [data-act="repSave"]')).toBeDisabled();
  await expect(page.locator('#repText[data-tl="report"]')).toHaveValue(/^# Orbit 协作报告/, { timeout: 6000 });
  await expect(page.locator('#modal [data-act="repSave"]')).toBeEnabled();
  await page.locator('#modal [data-act="repSave"]').click();
  await expect.poll(async () => (await msgs(page, 'save')).length).toBe(1);
  // closed before the answer: the late answer does not reopen the sheet
  await page.evaluate(() => { closeModal(); });
  await page.keyboard.press('Meta+Shift+e');
  await expect(page.locator('#repText')).toBeVisible({ timeout: 800 });
  await page.keyboard.press('Escape');
  await page.waitForTimeout(3000);
  expect(await page.evaluate(() => [MODAL_KEY, !!document.querySelector('#repText')])).toEqual([null, false]);
  // share card
  await page.keyboard.press('Meta+Shift+s');
  await expect(page.locator('#modal #shareBody[data-tl="share-pending"]')).toBeVisible({ timeout: 800 });
  await expect(page.locator('#modal [data-act="shareSave"]')).toBeDisabled();
  await expect(page.locator('#modal [data-tl="share-card"]')).toBeVisible({ timeout: 6000 });
  await expect(page.locator('#modal [data-act="shareSave"]')).toBeEnabled();
  expect(await page.evaluate(() => MODAL_KEY)).toBe('share');
  expect(errors).toEqual([]);
});

test('H4: a refused share card closes the pending sheet with the reason', async ({ page }) => {
  ONLY();
  await setup(page, { 'POST /v1/export/share_card': { delay: 400, body: Object.assign(fx('s8/export-share-card.json'), { eligible: false, blocked_reason: 'too_few_sessions' }) } });
  await openLive(page, 'overview');
  await page.keyboard.press('Meta+Shift+s');
  await expect(page.locator('#modal #shareBody[data-tl="share-pending"]')).toBeVisible({ timeout: 800 });
  await expect.poll(() => page.evaluate(() => MODAL_KEY)).toBe(null);
  await expect(page.locator('#toast')).toBeVisible();
});

test('B18: report and CSV exports carry the range, agents and project the screen shows', async ({ page }) => {
  ONLY();
  const errors = collectErrors(page);
  const bodies = [];
  const csv = fs.readFileSync(path.join(FIXTURES, 's8', 'export-csv.csv'), 'utf8');
  await setup(page, { 'POST /v1/export/report': (req) => { bodies.push(req.postDataJSON()); return fx('s8/export-report.json'); } }, { native: NATIVE });
  const qs = [];
  await page.route(/\/v1\/export\/csv/, (r) => { qs.push(new URL(r.request().url()).searchParams); r.fulfill({ status: 200, contentType: 'text/csv; charset=utf-8', body: csv }); });
  await openLive(page, 'tools');
  // the whole range first: no from_ts, no agent / project filters
  await page.evaluate(() => { S.range = 0; S.project = null; S.agents = new Set(AG.map((a) => a.id)); render(); openReport(); });
  await expect(page.locator('#repText')).toBeVisible();
  expect(bodies[0].scope.from_ts).toBeUndefined();
  expect(bodies[0].scope.source_ids).toBeUndefined();
  expect(bodies[0].scope.project_ids).toBeUndefined();
  // narrowed: 7 days, one agent, one project
  const pick = await page.evaluate(() => {
    const st = (TL.status && TL.status.sources) || []; const a = AG.find((x) => st.some((s) => TandemLive.AGENT_KEYS[x.id] && TandemLive.AGENT_KEYS[x.id].indexOf(s.agent) >= 0)) || AG[0];
    const p = PJ.find((x) => x.id !== '_none') || PJ[0];
    closeModal(); S.range = 7; S.agents = new Set([a.id]); S.project = p.id; render();
    const srcs = st.filter((s) => s.enabled !== false && (TandemLive.AGENT_KEYS[a.id] || [a.id]).indexOf(s.agent) >= 0).map((s) => s.id);
    return { a: a.id, key: a.key || a.id, p: p.id, srcs, from: lvtpFrom(7) };
  });
  await page.evaluate(() => openReport());
  await expect.poll(() => bodies.length).toBe(2);
  const sc = bodies[1].scope;
  expect(typeof sc.from_ts).toBe('number');
  expect(Math.abs(sc.from_ts - pick.from)).toBeLessThan(86400000);
  expect(sc.source_ids).toEqual(pick.srcs);
  expect(sc.project_ids).toEqual([pick.p]);
  await page.evaluate(() => { closeModal(); openCSV(); });
  await expect(page.locator('#modal textarea[data-tl="csv"]')).toBeVisible();
  const q = qs[qs.length - 1];
  expect(q.get('table')).toBe('tool_calls');
  expect(Number(q.get('from_ts'))).toBe(pick.from);
  expect(q.getAll('agent')).toEqual([pick.key]);
  expect(q.getAll('project_id')).toEqual([pick.p]);
  // '_none' (sessions without a project) has no backend filter: dropped rather than sent as a project id
  await page.evaluate(() => { closeModal(); S.project = '_none'; S.range = 0; S.agents = new Set(AG.map((a) => a.id)); openCSV(); });
  await expect.poll(() => qs.length).toBe(2);
  expect([qs[1].getAll('project_id'), qs[1].get('from_ts'), qs[1].getAll('agent')]).toEqual([[], null, []]);
  expect(errors).toEqual([]);
});

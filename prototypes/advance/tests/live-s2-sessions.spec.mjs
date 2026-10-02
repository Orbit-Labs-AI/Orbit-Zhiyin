// Slice 2 (A3 sessions, live): the polished trajectory page reads /v1/uiview/sessions/{uid} (one request per session, LRU),
// compare reads suggest_b + /compare, message text is paged from /v1/sessions/{uid}/events only when opened, and search adds
// the server's ?q= hits. Fixtures: prototypes/shared/fixtures/core + s2 (synthetic, real agent ids).
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NOW = new Date('2026-10-03T12:00:00+08:00');
const A = 'session_fx016', B = 'session_fx010', C = 'session_fx005';
const DA = fx('s2/detail-a.json');
const DP = (uid) => '/v1/uiview/sessions/' + uid;
const LIST = fx('s2/list.json'), SEARCH = fx('s2/search-tsc.json');
const sessionsRoute = (req, u) => {
  const q = u.searchParams.get('q');
  if (!q) return LIST;
  return q === 'tsc' ? SEARCH : { meta: LIST.meta, days: [], rows: [], total: 0, next_offset: null };
};

async function open(page, extra) {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's2'], Object.assign({ 'GET /v1/uiview/sessions': sessionsRoute }, extra || {}));
  await openLive(page, 'sessions');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  return { gw, errors };
}
const noPlainTables = async (page) => expect(await page.locator('.tl-table, .tl-kpi').count()).toBe(0);

test.beforeEach(async ({ page }, info) => { ONLY('mac-14'); test.skip(!!PASS !== /real gateway/.test(info.title), 'fixture tests run on the stub; the smoke test needs LIVE_GATEWAY'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

test('featured = newest finished; one detail request; lanes, phases, moments and 7 stats come from the detail', async ({ page }) => {
  const { gw, errors } = await open(page);
  expect(await page.evaluate(() => S.sess.sel)).toBe(A);
  await expect(page.locator('.tl-mom')).toHaveCount(DA.trajectory.moments.length);
  await expect(page.locator('#tlBox svg.vz-svg')).toHaveCount(1);
  const tr = await page.evaluate(() => { const t = traj(BYID[S.sess.sel]); return { n: t.ev.length, ph: t.phases.length, mo: t.moments.length, T: t.T, users: t.users.length, err: t.ev.filter((e) => e.err).length, comps: t.comps.length, playhead: S.sess.ph }; });
  const evs = DA.trajectory.events;
  expect(tr.n).toBe(evs.length);
  expect(tr.ph).toBe(DA.trajectory.phases.length);
  expect(tr.mo).toBe(DA.trajectory.moments.length);
  expect(tr.T).toBe(DA.trajectory.T);
  expect(tr.users).toBe(evs.filter((e) => e.lane === 'user').length);
  expect(tr.err).toBe(evs.filter((e) => e.err).length);
  expect(tr.comps).toBe(1);                       // ctx 81% → 30%
  expect(tr.playhead).toBe(DA.trajectory.T);      // playhead parked at the real end once the detail arrived
  // header band + 7 stats
  const band = await page.locator('.band').innerText();
  expect(band).toContain('DeepSeek Harness');
  expect(band).toContain('deepseek-v3 · high');
  expect(band).toContain('/synthetic/beta-lib');
  const stats = await page.locator('.stats7 .st-v').allInnerTexts();
  expect(stats).toEqual(['7', '29', '58', '0', '1', '81%', '36K']);
  await expect(page.locator('.tl-ai')).toHaveText(DA.insight.text);
  await expect(page.locator('.tl-sum')).not.toHaveAttribute('data-lv', /.*/);
  // real list barcodes: ticks for known rows, an honest empty barcode otherwise
  const bars = await page.evaluate((a) => { const b = document.querySelector('.srow[data-id="' + a + '"] svg[preserveAspectRatio="none"]'); return { d: b.querySelector('path').getAttribute('d'), na: b.getAttribute('data-lv') }; }, A);
  expect(bars.na).toBeNull();
  expect(bars.d.split('M').length - 1).toBe(11);
  const naBar = await page.evaluate(() => { const b = document.querySelector('.srow[data-id="session_fx004"] svg[preserveAspectRatio="none"]'); return b && b.getAttribute('data-lv'); });
  expect(naBar).toBe('na');   // no ticks for this row → empty barcode, never random positions
  // exactly one detail request; no message text fetched yet
  expect(gw.count(DP(A))).toBe(1);
  expect(gw.seen.filter((x) => /\/events$/.test(x.path) && x.path !== '/v1/events').length).toBe(0);
  // mood is "—" until G2
  await page.evaluate(() => { const s = BYID[S.sess.sel]; const e = traj(s).ev.find((x) => x.lane === 'user'); tlPick(s, { id: e.id }); });
  await expect(page.locator('#tlInsp')).toContainText('情绪—');
  await noPlainTables(page);
  expect(errors).toEqual([]);
});

test('revisits hit the LRU; play and scrub move the playhead', async ({ page }) => {
  const { gw, errors } = await open(page);
  await expect(page.locator('.tl-mom')).toHaveCount(4);
  await page.locator('.srow[data-id="' + C + '"]').click();
  await expect.poll(() => page.evaluate(() => traj(BYID[S.sess.sel]).state)).toBe('ready');
  await expect(page.locator('.tl-mom')).toHaveCount(1);
  await page.locator('.srow[data-id="' + A + '"]').click();
  await expect(page.locator('.tl-mom')).toHaveCount(4);
  expect(gw.count(DP(A))).toBe(1);
  expect(gw.count(DP(C))).toBe(1);
  // scrub: a moment jumps the playhead; the readout follows
  await page.locator('.tl-mom[data-mk="2"]').click();
  expect(await page.evaluate(() => S.sess.ph)).toBe(9.1);
  await expect(page.locator('#tlRead')).toContainText('已发生 8 / 17 个事件');
  // play from the start, then pause
  await page.evaluate(() => tlSeek(0));
  await page.evaluate(() => ACT.playToggle());   // header buttons can sit under the welcome banner
  await expect.poll(() => page.evaluate(() => S.sess.ph)).toBeGreaterThan(0.5);
  await page.evaluate(() => ACT.playToggle());   // header buttons can sit under the welcome banner
  expect(await page.evaluate(() => S.sess.playing)).toBe(false);
  expect(errors).toEqual([]);
});

test('compare: B from suggest_b, both timelines from their details, phase shares from /compare', async ({ page }) => {
  const { gw, errors } = await open(page);
  await page.evaluate(() => ACT.sessMode({ dataset: { v: 'cmp' } }));
  await expect.poll(() => page.evaluate(() => S.sess.cmp)).toBe(B);
  expect(gw.count(DP(A) + '/suggest_b')).toBe(1);
  await expect(page.locator('.tl-cmp svg.vz-svg')).toHaveCount(2);
  await expect(page.locator('.tl-cmp-tbl')).toContainText('调试 38%');
  await expect(page.locator('.tl-cmp-tbl')).toContainText('实施 60%');
  expect(gw.count('/v1/uiview/sessions/compare')).toBe(1);
  expect(gw.count(DP(B))).toBe(1);
  await noPlainTables(page);
  expect(errors).toEqual([]);
});

test('message text loads only when opened, paged from /events', async ({ page }) => {
  const { gw, errors } = await open(page);
  await expect(page.locator('.tl-mom')).toHaveCount(4);
  const EV = '/v1/sessions/' + A + '/events';
  expect(gw.count(EV)).toBe(0);
  await page.evaluate(() => { const s = BYID[S.sess.sel]; const e = traj(s).ev.filter((x) => x.lane === 'user')[1]; tlPick(s, { id: e.id }); });
  await page.locator('#tlInsp [data-act="lvsMsgs"]').click();
  await expect(page.locator('#lvsMsgBox .lvs-msg')).toHaveCount(4);
  await expect(page.locator('#lvsMsgBox')).toContainText('不要改 CI 配置，只改脚本');
  expect(gw.count(EV)).toBe(1);
  expect(gw.seen.find((x) => x.path === EV).query).toContain('limit=200');
  expect(errors).toEqual([]);
});

test('search: local title match first, then the server ?q= hits', async ({ page }) => {
  const { gw, errors } = await open(page);
  await page.locator('#sessQ').fill('tsc');
  await expect(page.locator('.srow[data-id="session_fx021"]')).toHaveCount(1);
  await expect(page.locator('.srow')).toHaveCount(1);
  expect(gw.seen.some((x) => x.path === '/v1/uiview/sessions' && /q=tsc/.test(x.query))).toBe(true);
  await page.locator('#sessQ').fill('#16');   // title match, no server hit needed
  await expect(page.locator('.srow[data-id="' + A + '"]')).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('missing detail: honest error state, no mock trajectory; empty spine renders without errors', async ({ page }) => {
  const { errors } = await open(page, { ['GET ' + DP(A)]: { status: 404 } });
  await expect(page.locator('.tl-sum')).toHaveAttribute('data-lv', 'error');
  expect(await page.evaluate(() => traj(BYID[S.sess.sel]).ev.length)).toBe(0);
  await expect(page.locator('.tl-mom')).toHaveCount(0);
  await expect(page.locator('.stats7 .st-v').nth(6)).toHaveText('36K');   // spine numbers still shown
  expect(await page.locator('#main').innerText()).not.toMatch(/Cloudflare|wrangler|confluo/i);
  await noPlainTables(page);
  expect(errors).toEqual([]);
});

test('empty spine: sessions page renders its own empty state', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's2'], { 'GET /v1/uiview/facts': fx('core/facts-empty.json'), 'GET /v1/uiview/sessions': sessionsRoute });
  await openLive(page, 'sessions');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('empty');
  await expect(page.locator('#main')).toContainText('没有会话');
  await noPlainTables(page);
  expect(errors).toEqual([]);
});

test('real gateway smoke: sessions page, detail, compare and messages render without errors', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, []);
  await openLive(page, 'sessions');
  const st = await page.evaluate(() => LV.state);
  console.log('real gateway spine:', st, await page.evaluate(() => ALL.length));
  if (st === 'ready') {
    await expect.poll(() => page.evaluate(() => traj(BYID[S.sess.sel]).state), { timeout: 10_000 }).toBe('ready');
    await expect(page.locator('#tlBox svg.vz-svg')).toHaveCount(1);
    await page.evaluate(() => ACT.sessMode({ dataset: { v: 'cmp' } }));   // notification banners may cover the header on a real home
    await page.waitForTimeout(1500);
    await page.evaluate(() => ACT.sessMode({ dataset: { v: 'single' } }));
    await page.evaluate(() => { const s = BYID[S.sess.sel]; const e = traj(s).ev.find((x) => x.lane === 'user'); if (e) tlPick(s, { id: e.id }); });
    const msg = page.locator('#tlInsp [data-act="lvsMsgs"]');
    if (await msg.count()) { await page.evaluate(() => ACT.lvsMsgs(document.querySelector('#tlInsp [data-act="lvsMsgs"]'))); await expect(page.locator('#lvsMsgBox [data-lv="pending"]')).toHaveCount(0, { timeout: 10_000 }); }
  }
  await noPlainTables(page);
  expect(errors).toEqual([]);
  console.log('real gateway smoke:', JSON.stringify(await page.evaluate(() => ({ sel: S.sess.sel, ev: traj(BYID[S.sess.sel]).ev.length, cmp: S.sess.cmp, msgs: LVS.msgs.size }))));
  await page.unrouteAll({ behavior: 'ignoreErrors' });
});

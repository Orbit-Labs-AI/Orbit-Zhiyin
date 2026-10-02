// Slice 4 (A6 sentiment + command palette search): the polished A6 page reads GET /v1/uiview/sentiment (mood stays "—"
// while the server has no scores, gap G2), phrase sources and palette results come from GET /v1/search and open their
// ref.page. Fixtures: prototypes/shared/fixtures/core + s4 (synthetic, real agent ids).
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NOW = new Date('2026-10-03T12:00:00+08:00');
const SEARCH = fx('s4/search.json');
const PHRASE = fx('s4/search-phrase.json');
const searchStub = (req, u) => (u.searchParams.get('kinds') === 'message' ? PHRASE : SEARCH);
const MOCK_A6 = /直接合并|别用子代理|用 Cloudflare 不是 Vercel|中文 62%/;

test.beforeEach(async ({ page }) => { ONLY('mac-14'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

async function openSent(page, extra) {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's4'], Object.assign({ 'GET /v1/search': searchStub }, extra || {}));
  await openLive(page, 'sentiment');
  return { errors, gw };
}
const noPlain = async (page) => expect(page.locator('.tl-table, .tl-kpi')).toHaveCount(0);

test('A6 reads /v1/uiview/sentiment; null mood shows "—" and hides the mood distribution', async ({ page }) => {
  test.skip(!!PASS, 'fixture values');
  const { errors, gw } = await openSent(page);
  await expect(page.locator('#main .sn-fric[data-act="fricGo"]')).toHaveCount(2);
  if (!PASS) {
    const q = gw.seen.filter((x) => x.path === '/v1/uiview/sentiment').map((x) => new URLSearchParams(x.query));
    expect(q.length).toBeGreaterThan(0);
    expect(q[0].get('days')).toBe('30'); expect(q[0].get('bucket')).toBe('day'); expect(q[0].get('tz')).toBeTruthy();
  }
  await expect(page.locator('#main .tbar')).toContainText('中文 55% · 英文 35% · 混合 5%');
  // chart: the polished moodcorr renderer, correction bars only, no band / median while every bucket is null
  await expect(page.locator('#main [data-vz="mood"] svg')).toHaveCount(1);
  await expect(page.locator('#main [data-lv="mood-null"]')).toBeVisible();
  await expect(page.locator('#main [data-vz="mood"] .sn-band')).toHaveCount(0);
  const bars = await page.locator('#main [data-vz="mood"] .vz-bar').count();
  const corrDays = await page.evaluate(() => sel().filter((s) => s.corr > 0).length);
  expect(bars).toBe(corrDays);
  // friction: server categories, sorted by sessions, mood "—"
  const fr = await page.locator('#main .sn-fric[data-act="fricGo"]').evaluateAll((els) => els.map((e) => [e.querySelector('.sn-fric-n').textContent, e.querySelector('.sn-fric-v').textContent, e.querySelector('.sn-fric-d').textContent, e.querySelector('.sn-fric-m').textContent]));
  expect(fr).toEqual([['方向错误', '18', '—', '—'], ['工具 / 环境失败', '10', '▲ 7', '—']]);
  const tp = await page.locator('#main .sn-topic').evaluateAll((els) => els.map((e) => [e.querySelector('b').textContent, e.querySelector('.mono:last-child').textContent]));
  expect(tp).toEqual([['Git 与版本管理', '—'], ['测试与调试', '—']]);
  await expect(page.locator('#main .sn-ph')).toHaveCount(3);
  await expect(page.locator('#main .sn-ph').first()).toContainText('示例：继续下一步');
  await expect(page.locator('#main .sn-note')).toContainText('1 条纠偏语');
  const drv = await page.locator('#main .sn-drv:not(.sn-drv-ax)').evaluateAll((els) => els.map((e) => [e.querySelector('.sn-drv-n').textContent, e.querySelector('.sn-drv-v').textContent, e.querySelector('.sn-drv-k').textContent]));
  expect(drv).toEqual([['会话超过 90 分钟', '−0.21', 'n=6'], ['连续失败 ≥ 2 次', '—', 'n=2']]);
  // in-place constants for the other readers
  const k = await page.evaluate(() => ({ ph: PHRASES.map((p) => p[0]), dr: DRIVERS.slice(), neg: QUOTES.neg.slice() }));
  expect(k.ph).toEqual(['示例：继续下一步', '示例：不是这个意思', '示例：测试都过了']);
  expect(k.dr).toEqual([['会话超过 90 分钟', -0.21]]);
  expect(k.neg).toContain('「示例：不是这个意思」');
  await expect(page.locator('#main')).not.toContainText(MOCK_A6);
  await noPlain(page);
  // table view of the same chart
  await page.locator('#main [data-act="moodView"]').click();
  await expect(page.locator('#main [data-vz="mood"] table')).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('A6 mood series: medians and bands from the server buckets, signed mood glyphs', async ({ page }) => {
  test.skip(!!PASS, 'fixture values');
  const { errors } = await openSent(page, { 'GET /v1/uiview/sentiment': fx('s4/sentiment-mood.json') });
  await expect(page.locator('#main .sn-fric[data-act="fricGo"]')).toHaveCount(2);
  await expect(page.locator('#main [data-lv="mood-null"]')).toHaveCount(0);
  const st = await page.evaluate(() => { const ms = CUR.mood; return { withMood: ms.filter((b) => b.dist).length, neg: ms.filter((b) => b.dist && b.dist.p50 < 0).length, first: ms.find((b) => b.dist) }; });
  expect(st.withMood).toBe(9);
  expect(st.neg).toBe(3);
  expect(st.first.dist).toMatchObject({ p25: 0.4, p50: 0.6, p75: 0.8 });
  await expect(page.locator('#main [data-vz="mood"] .vz-line')).toHaveCount(1);
  expect(await page.locator('#main [data-vz="mood"] .vz-line').getAttribute('d')).toMatch(/^M/);
  await expect(page.locator('#main .sn-fric[data-k="工具 / 环境失败"] .sn-fric-m')).toHaveText('-0.3');
  await expect(page.locator('#main .sn-topic').first().locator('.mono').last()).toHaveText('+0.4');
  // 90 days → weekly buckets keep only the weighted median (no invented band)
  await page.evaluate(() => { S.range = 90; render(); });
  await expect.poll(() => page.evaluate(() => CUR.mood && CUR.mood.length)).toBeLessThan(20);
  const wk = await page.evaluate(() => CUR.mood.filter((b) => b.dist && b.a !== b.b).map((b) => [b.dist.p25, b.dist.p75]));
  expect(wk.length).toBeGreaterThan(0);
  wk.forEach((x) => expect(x).toEqual([null, null]));
  await noPlain(page);
  expect(errors).toEqual([]);
});

// B13: a topic at +1.0 keeps its bar inside the ruler (the value text is not covered); one friction class reads as one
test('A6 B13: ±1 topic bars stay inside the ruler; a single friction class is not called "前两类"', async ({ page }) => {
  test.skip(!!PASS, 'fixture values');
  const d = fx('s4/sentiment-mood.json');
  d.topics[0].avg_balance = 1; d.topics[1].avg_balance = -1;
  d.friction = d.friction.slice(0, 1);
  const { errors } = await openSent(page, { 'GET /v1/uiview/sentiment': d });
  await expect(page.locator('#main .sn-fric[data-act="fricGo"]')).toHaveCount(1);
  await expect(page.locator('#main .sn-foot').first()).not.toContainText('前两类');
  await expect(page.locator('#main .sn-foot').first()).toContainText(await page.locator('#main .sn-fric-n').first().textContent());
  await expect(page.locator('#main .sn-topic').first().locator('.mono').last()).toHaveText('+1.0');
  const geo = await page.locator('#main .sn-topic').evaluateAll((els) => els.map((e) => {
    const div = e.querySelector('.sn-div').getBoundingClientRect(); const bar = e.querySelector('.sn-div .bar').getBoundingClientRect();
    const val = e.querySelector('.row > .mono:last-child').getBoundingClientRect();
    return { inL: bar.left >= div.left - 0.5, inR: bar.right <= div.right + 0.5, clear: bar.right <= val.left + 0.5 };
  }));
  geo.forEach((g) => expect(g).toEqual({ inL: true, inR: true, clear: true }));
  expect(errors).toEqual([]);
});

test('A6 interactions: friction / phrase sources navigate to real sessions', async ({ page }) => {
  test.skip(!!PASS, 'fixture ids');
  const { errors, gw } = await openSent(page);
  await expect(page.locator('#main .sn-fric[data-act="fricGo"]')).toHaveCount(2);
  // spine knows 方向错误 → global friction filter
  await page.locator('#main .sn-fric[data-k="方向错误"]').click();
  await expect.poll(() => page.evaluate(() => [S.route, S.fric])).toEqual(['sessions', '方向错误']);
  await page.evaluate(() => { S.fric = null; go('sentiment'); });
  await expect(page.locator('#main .sn-fric[data-act="fricGo"]')).toHaveCount(2);
  // server-only category → newest session of that category
  await page.locator('#main .sn-fric[data-k="工具 / 环境失败"]').click();
  await expect.poll(() => page.evaluate(() => [S.route, S.sess.sel])).toEqual(['sessions', 'session_fx016']);
  await page.evaluate(() => { go('sentiment'); });
  // phrase sources: /v1/search?kinds=message
  await page.locator('#main .sn-ph[data-k="示例：不是这个意思"]').click();
  const dd = page.locator('#dd');
  await expect(dd).toContainText('出处（2 次');
  expect(gw.seen.some((x) => x.path === '/v1/search' && /kinds=message/.test(x.query))).toBe(true);
  await dd.locator('button', { hasText: '整理示例仓库的测试 #20' }).click();
  await expect.poll(() => page.evaluate(() => [S.route, S.sess.sel])).toEqual(['sessions', 'session_fx020']);
  // topic the spine does not carry: no filter that would empty every page
  await page.evaluate(() => { go('sentiment'); });
  await page.locator('#main .sn-topic[data-k="software.testing_debugging"]').click();
  expect(await page.evaluate(() => S.topic)).toBe(null);
  await page.locator('#main .sn-topic[data-k="git"]').click();
  expect(await page.evaluate(() => S.topic)).toBe('git');
  // rule draft uses the real correction phrases
  await page.evaluate(() => ACT.phrasesToRule());
  expect(await page.evaluate(() => S.studio.goal)).toContain('「示例：不是这个意思」');
  expect(errors).toEqual([]);
});

test('A6 endpoint missing or empty spine: honest empty cards, no mock rows, no errors', async ({ page }) => {
  test.skip(!!PASS, 'fixture values');
  const { errors } = await openSent(page, { 'GET /v1/uiview/sentiment': { status: 404 } });
  await expect(page.locator('#main [data-lv-sent="error"]')).toHaveCount(1);
  await expect(page.locator('#main [data-lv="na"]').first()).toBeVisible();
  await expect(page.locator('#main')).not.toContainText(MOCK_A6);
  await noPlain(page);
  expect(errors).toEqual([]);
});

test('A6 + palette on the empty spine', async ({ page }) => {
  test.skip(!!PASS, 'fixture');
  const errors = collectErrors(page);
  await stubGateway(page, 'core', { 'GET /v1/uiview/facts': fx('core/facts-empty.json'), 'GET /v1/uiview/sentiment': { status: 503, body: { error: { code: 'no_projection', message: 'x', retryable: true } } }, 'GET /v1/search': searchStub });
  await openLive(page, 'sentiment');
  await expect(page.locator('#main [data-lv-sent]')).toHaveCount(1);
  await page.evaluate(() => openPalette());
  await page.fill('#palQ', '示例');
  await expect(page.locator('#palList')).toContainText('示例：请重构这个模块');
  // hits whose session is not in the spine say so instead of opening a mock row
  await page.locator('#palList .palrow', { hasText: '请重构这个模块' }).click();
  await expect(page.locator('#toast')).toContainText('不在当前数据中');
  await noPlain(page);
  expect(errors).toEqual([]);
});

test('palette: local spine rows at once, /v1/search groups merged and opened by ref.page', async ({ page }) => {
  test.skip(!!PASS, 'fixture ids');
  const { errors, gw } = await openSent(page);
  await page.evaluate(() => openPalette());
  // empty query: newest real sessions, no server call, no demo shortcuts / mock recs
  const groups0 = await page.locator('#palList .eb').allTextContents();
  expect(groups0).toContain('会话');
  await expect(page.locator('#palList')).toContainText('修复示例构建脚本 #16');
  await expect(page.locator('#palList')).not.toContainText('部署相关会话');
  expect(gw.count('/v1/search')).toBe(0);
  await page.fill('#palQ', '示例');
  await expect(page.locator('#palList')).toContainText('pnpm test 示例');
  const groups = await page.locator('#palList .eb').allTextContents();
  ['会话', '项目', '消息', '命令', '文件'].forEach((g) => expect(groups).toContain(g));
  expect(new Set(groups).size).toBe(groups.length);   // every group listed once
  // the server session hit duplicates a local row → listed once
  await expect(page.locator('#palList .palrow', { hasText: '整理示例仓库的测试 #5' })).toHaveCount(1);
  const calls = gw.seen.filter((x) => x.path === '/v1/search' && !/kinds=/.test(x.query));
  expect(calls.length).toBe(1);
  expect(new URLSearchParams(calls[0].query).get('q')).toBe('示例');
  // command hit → its session
  await page.locator('#palList .palrow', { hasText: 'pnpm test 示例' }).click();
  await expect.poll(() => page.evaluate(() => [S.route, S.sess.sel])).toEqual(['sessions', 'session_fx008']);
  // project hit → A5 with that project (cached query: no second request)
  await page.evaluate(() => openPalette());
  await page.fill('#palQ', '示例');
  await page.locator('#palList .palrow', { hasText: 'beta-lib 示例' }).click();
  await expect.poll(() => page.evaluate(() => [S.route, S.proj.sel])).toEqual(['projects', 'proj_beta']);
  expect(gw.seen.filter((x) => x.path === '/v1/search' && !/kinds=/.test(x.query)).length).toBe(1);
  await noPlain(page);
  expect(errors).toEqual([]);
});

test('palette: search endpoint missing shows an honest note, local results still work', async ({ page }) => {
  test.skip(!!PASS, 'fixture');
  const { errors } = await openSent(page, { 'GET /v1/search': { status: 404 } });
  await page.evaluate(() => openPalette());
  await page.fill('#palQ', '示例');
  await expect(page.locator('#palList')).toContainText('本机搜索暂不可用');
  await expect(page.locator('#palList')).toContainText('修复示例构建脚本 #16');
  expect(errors).toEqual([]);
});

// real-gateway smoke (LIVE_GATEWAY + TANDEM_TOKEN): the polished A6 root and the palette render on a real home
test('real gateway smoke: A6 and palette search', async ({ page }) => {
  test.skip(!PASS, 'needs LIVE_GATEWAY');
  const errors = collectErrors(page);
  await stubGateway(page, []);
  await openLive(page, 'sentiment');
  await expect(page.locator('#main [data-vz="mood"], #main [data-lv-sent]').first()).toBeVisible({ timeout: 15_000 });
  await expect.poll(() => page.evaluate(() => LV.feedState('sentiment')), { timeout: 15_000 }).toMatch(/ready|error/);
  await expect(page.locator('#main')).not.toContainText(MOCK_A6);
  await page.evaluate(() => openPalette());
  await page.fill('#palQ', 'pytest');
  await expect(page.locator('#palList')).not.toContainText('正在搜索', { timeout: 10_000 });
  await noPlain(page);
  expect(errors).toEqual([]);
});

// Round 3 API changes on the analysis pages (stub fixtures):
//  4. A3 messages: capped event text (truncated + text_range) shows 已截断 · 展开全文, which reads the rest from
//     /v1/evidence/{id}?text_offset=&max_chars= and appends it; an evidence 404 {error:{code:not_found}} says so.
//  5. Palette: /v1/search complete:false + partial_reasons → 结果不完整：…; counts_at_least → 至少 N 条.
//  6. A4: a null failure rate (rate_reason / low status_coverage) renders "—" with the reason, never 0% or NaN.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const NOW = new Date('2026-10-03T12:00:00+08:00');
const A = 'session_fx016';
test.beforeEach(async ({ page }) => { test.skip(test.info().project.name !== 'mac-14' || !!PASS, 'stub fixtures, default size'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

const LIST = fx('s2/list.json');
const sessionsRoute = (req, u) => (u.searchParams.get('q') ? { meta: LIST.meta, days: [], rows: [], total: 0, next_offset: null } : LIST);

test('A3 messages: truncated text offers 展开全文 and appends the rest from /v1/evidence; 404 is honest', async ({ page }) => {
  const errors = collectErrors(page);
  const ev = fx('s2/events-a.json');
  const FULL1 = '修复示例构建脚本 #16。' + '甲'.repeat(40) + '【末尾】';
  const cut = (x, full, n) => Object.assign(x, { text: full.slice(0, n), truncated: true, truncated_fields: ['text'], text_range: { offset: 0, length: n, total: full.length } });
  cut(ev.items[1], FULL1, 12);
  cut(ev.items[3], '我先读了 build.sh，问题在 tsc 的 --project 路径。' + '乙'.repeat(30), 10);
  const gw = await stubGateway(page, ['core', 's2'], {
    'GET /v1/uiview/sessions': sessionsRoute,
    ['GET /v1/sessions/' + A + '/events']: ev,
    'GET /v1/evidence/event_s2_m01': (req, u) => { const o = +u.searchParams.get('text_offset'); const n = +u.searchParams.get('max_chars'); return { id: 'event_s2_m01', text: FULL1.slice(o, o + n), truncated: o > 0, truncated_fields: ['text'], text_range: { offset: o, length: Math.min(n, FULL1.length - o), total: FULL1.length } }; },
    'GET /v1/evidence/event_s2_m03': { status: 404, body: { error: { code: 'not_found', message: '证据不存在或不在分析范围内' } } }
  });
  await openLive(page, 'sessions');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  await page.evaluate(() => { S.sess.sel = 'session_fx016'; render(); ACT.lvsMsgs(null); });
  const box = page.locator('#lvsMsgBox');
  await expect(box.locator('.lvs-msg')).toHaveCount(4);
  await expect(box.locator('[data-lv="trunc"]')).toHaveCount(2);
  await expect(box.locator('[data-lv="trunc"]').first()).toHaveText('已截断 · 展开全文');
  await expect(box).not.toContainText('【末尾】');
  await box.locator('[data-ev="event_s2_m01"] [data-lv="trunc"]').click();
  await expect(box.locator('[data-ev="event_s2_m01"]')).toContainText('【末尾】');
  await expect(box.locator('[data-ev="event_s2_m01"] [data-lv="trunc"]')).toHaveCount(0);
  const q = new URLSearchParams(gw.seen.find((x) => x.path === '/v1/evidence/event_s2_m01').query);
  expect(q.get('text_offset')).toBe('12');
  expect(+q.get('max_chars')).toBeGreaterThan(0);
  // the text is the prefix + the fetched rest exactly once
  expect((await box.locator('[data-ev="event_s2_m01"] .v').textContent()).split('修复示例构建脚本').length).toBe(2);
  await box.locator('[data-ev="event_s2_m03"] [data-lv="trunc"]').click();
  await expect(box.locator('[data-ev="event_s2_m03"] [data-lv="trunc-error"]')).toContainText('已不在本地数据中');
  expect(errors).toEqual([]);
});

const SEARCH = fx('s4/search.json');
async function openPal(page, body) {
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's4'], { 'GET /v1/search': body });
  await openLive(page, 'overview');
  await page.evaluate(() => openPalette());
  return errors;
}

test('palette: incomplete empty search explains which sources are missing', async ({ page }) => {
  const errors = await openPal(page, { q: 'zzqq', took_ms: 3, index: { state: 'building', docs: 0 }, counts: {}, counts_at_least: [], results: [], partial: ['command', 'message'], partial_reasons: { command: 'timeout', message: 'index_building' }, complete: false });
  await page.fill('#palQ', 'zzqq');
  const list = page.locator('#palList');
  await expect(list).toContainText('结果不完整：');
  await expect(list).toContainText('消息 索引仍在建立');
  await expect(list).toContainText('命令 查询超时');
  await expect(list).toContainText('没有结果不代表没有匹配');
  await expect(list).not.toContainText('没有匹配「zzqq」');
  expect(errors).toEqual([]);
});

test('palette: capped kinds read 至少 N 条; a complete search adds no note', async ({ page }) => {
  const body = Object.assign({}, SEARCH, { counts: Object.assign({}, SEARCH.counts, { message: 100 }), counts_at_least: ['message'], partial_reasons: {}, complete: true });
  const errors = await openPal(page, body);
  await page.fill('#palQ', '示例');
  const list = page.locator('#palList');
  await expect(list).toContainText('pnpm test 示例');
  await expect(list).toContainText('消息 至少 100 条');
  await expect(list).not.toContainText('结果不完整');
  expect(errors).toEqual([]);
});

test('A4: null error rates render "—" with the coverage reason, never 0% or NaN', async ({ page }) => {
  const errors = collectErrors(page);
  const t = fx('s3/tools.json');
  // every row of the first tool's kind (A4 merges a kind's rows into one unified tool) has explicit outcomes for 20% of calls
  t.tools.filter((r) => r.kind === t.tools[0].kind).forEach((row) => { const k = Math.round(row.n * 0.2); Object.assign(row, { known: k, unknown: row.n - k, failed: 0, err: null, status_coverage: 0.2, rate_reason: 'status_coverage_below_min' }); });
  Object.assign(t.kpis.error_rate, { value: null, known: 0, failed: 0, unknown: 1612, rate_reason: 'no_known_status' });
  await stubGateway(page, ['core', 's3'], { 'GET /v1/uiview/tools': t });
  await openLive(page, 'tools');
  const main = page.locator('#main');
  await expect(main.locator('table.tt tbody tr.click').first()).toBeVisible();
  const name = await page.evaluate(() => (toolRows().find((r) => r.err == null) || {}).name);
  expect(name).toBeTruthy();
  const cell = main.locator('tr.click[data-t="' + name + '"] td.tt-err');
  await expect(cell).toHaveText('—');
  await expect(cell).toHaveAttribute('data-tip', /只有 20% 的调用记录了明确成败.*不计算错误率/);
  const kpi = main.locator('.vz-kpi', { hasText: '错误率' });
  await expect(kpi).toHaveAttribute('data-tip', /没有记录到明确成败的调用/);
  await expect(kpi).not.toContainText(/\d%/);
  await expect(main).not.toContainText('NaN');
  // other rows keep their real rates; sorting by 错误率 puts the "—" row last
  await expect(main.locator('tr.click td.tt-err', { hasText: '%' }).first()).toBeVisible();
  await page.evaluate(() => { S.tools.sort = 'err'; S.tools.dir = -1; render(); });
  await expect(main.locator('tr.click').last()).toHaveAttribute('data-t', name);
  expect(errors).toEqual([]);
});

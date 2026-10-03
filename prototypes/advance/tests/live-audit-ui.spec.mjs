// Front-end live audit (fix/app-feedback-r4 · audit-ui). Live rows may carry no outcome / verify signal and the L0 insight is a
// rule template; neither may be dressed up as a real number or as AI. Flow (mac-14 only):
//  1 unknown outcome   facts with out / verify = null: Lite home 完成率 tile reads「—」(never 0 %), the evidence line has no
//                      「0% 要求验证」; A1 outcome card says 完成 — and how many sessions have a result; the session lists
//                      badge each row 结果未知 (not 完成)
//  2 rule badges       live A1 / Lite home insight carries the neutral「规则解读」tag (the button offers AI 生成, not 重新生成); Lite session insight carries「规则」
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx } from './live-helpers.mjs';

test.beforeEach(async ({ page }) => { test.skip(test.info().project.name !== 'mac-14', 'interaction checks run once'); await page.emulateMedia({ reducedMotion: 'reduce' }); });

function factsNoOutcome(extra) {
  const f = fx('core/facts.json');
  const drop = ['out', 'verify'].concat(extra || []);
  const idx = drop.map((k) => f.fields.indexOf(k)).filter((i) => i >= 0).sort((a, b) => b - a);
  idx.forEach((i) => { f.fields.splice(i, 1); f.rows.forEach((r) => r.splice(i, 1)); });
  drop.forEach((k) => { f.constants[k] = null; });
  return f;
}

test('unknown outcome / verify never shows as 0 % or 完成', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, 'core', {
    'GET /v1/uiview/facts': factsNoOutcome(),
    'GET /v1/uiview/persona': (req, u) => fx(u.searchParams.get('period') === '30' ? 's1/persona-30.json' : 's1/persona-90.json')
  });
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => ALL.length)).toBeGreaterThan(0);
  expect(await page.evaluate(() => ALL.every((s) => s.out == null && s.verify == null))).toBe(true);
  // A1 outcome card
  await page.evaluate(() => go('overview'));
  const card = page.locator('.ov-out-t');
  await expect(card).toContainText('完成 —');
  await expect(card).toContainText('0 个有结果');
  await expect(page.locator('#aiCard')).not.toContainText('完成率 0%');
  // Lite home: the 完成率 tile and the evidence line
  await page.evaluate(() => { go('overview'); edSet('lite'); });
  await expect(page.locator('#main .l-hero')).toBeVisible();
  const tile = page.locator('#main .vz-kpi, #main .kpi').filter({ hasText: '完成率' });
  await expect(tile).toContainText('—');
  await expect(tile).not.toContainText('0%');
  await expect(page.locator('#main .l-ev')).toContainText('完成率 —');
  await expect(page.locator('#main .l-ev')).not.toContainText('要求验证');
  // Lite sessions: rows and head say 结果未知
  await page.evaluate(() => go('l-sessions'));
  await expect(page.locator('#main .l-shead')).toContainText('结果未知');
  await expect(page.locator('#main .l-shead')).not.toContainText('部分完成');
  // A2 persona: facts line, V-axis evidence and the per-agent fit rows never read 0 % / 完成 0%
  await page.evaluate(() => edSet('advance', 'persona'));
  await expect(page.locator('#main .pe-facts')).toBeVisible();
  await expect(page.locator('#main .pe-facts')).toContainText('— 要求验证');
  await expect(page.locator('#main')).not.toContainText('0% 要求验证');
  await expect(page.locator('#main')).not.toContainText('0% 会话要求或运行了验证');
  await expect(page.locator('#main')).not.toContainText('完成 0%');
  // no outcome signal: the fit score is not computed (no made-up 98)
  const fit = page.locator('#main .pe-fit').filter({ has: page.locator('[data-lv="fit-na"]') });
  await expect(fit.first()).toContainText('没有完成信号');
  await expect(fit.first().locator('.pe-fit-t b')).toHaveText('—');
  expect(errors).toEqual([]);
});

test('no user messages: 摩擦率 / 自主比 read —, not 0', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, 'core', { 'GET /v1/uiview/facts': factsNoOutcome(['msgs', 'corr']) });
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => ALL.length)).toBeGreaterThan(0);
  await page.evaluate(() => go('overview'));
  const tiles = page.locator('#ovTiles');
  await expect(tiles.locator('[data-k="f"] .v')).toHaveText('—');
  await expect(tiles.locator('[data-k="a"] .v')).toHaveText('—');
  await expect(page.locator('#aiCard')).not.toContainText('没有明显的摩擦');
  await page.evaluate(() => { go('overview'); edSet('lite'); });
  const lt = page.locator('#main .vz-kpi').filter({ hasText: '摩擦率' });
  await expect(lt.locator('.v')).toHaveText('—');
  expect(errors).toEqual([]);
});

test('rule-template insights carry the 规则 tag, not the AI badge', async ({ page }) => {
  const errors = collectErrors(page);
  await page.clock.setFixedTime(new Date('2026-10-03T12:00:00+08:00'));
  await stubGateway(page, 's1', {
    'GET /v1/uiview/overview': (req, u) => fx('s1/overview-' + ({ 7: 7, 30: 30, 90: 90 }[u.searchParams.get('range')] || 0) + '.json'),
    'GET /v1/uiview/persona': (req, u) => fx(u.searchParams.get('period') === '30' ? 's1/persona-30.json' : 's1/persona-90.json')
  });
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  await expect.poll(() => page.evaluate(() => !!(LV.ov && LV.ov.insight && LV.ov.insight.lede))).toBe(true);
  await page.evaluate(() => go('overview'));
  const ai = page.locator('#aiCard .ov-aih').first();
  await expect(ai.locator('[data-lv="ins-basis"]')).toHaveText('规则解读');
  await expect(ai.locator('.aib')).toHaveCount(0);
  await expect(page.locator('#aiCard [data-act="regen"]')).not.toContainText('重新生成');
  await page.evaluate(() => { go('overview'); edSet('lite'); });
  await expect(page.locator('#main .l-hero [data-lv="ins-basis"]')).toHaveText('规则解读');
  await expect(page.locator('#main .l-hero .aib')).toHaveCount(0);
  await page.evaluate(() => go('l-sessions'));
  await expect(page.locator('#main .l-ins .tag')).toHaveText('规则');
  await expect(page.locator('#main .l-ins .aib')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('A4: no call with a known status shows 失败次数 — and 错误率 — (not 0)', async ({ page }) => {
  const errors = collectErrors(page);
  const tools = fx('s3/tools.json');
  const n = tools.kpis.calls ? tools.kpis.calls.value : 0;
  tools.kpis.error_rate = Object.assign({}, tools.kpis.error_rate, { value: null, lo: null, hi: null, failed: 0, known: 0, unknown: n, prev: null, delta: null });
  await stubGateway(page, ['core', 's3'], { 'GET /v1/uiview/tools': tools });
  await openLive(page, 'tools');
  await expect.poll(() => page.evaluate(() => S.tools && S.tools.failOnly !== false ? 'fail' : 'all')).toBe('fail');
  const fail = page.locator('#main .vz-kpi').filter({ hasText: '失败次数' });
  await expect(fail.locator('.v')).toHaveText('—');
  const rate = page.locator('#main .vz-kpi').filter({ hasText: '错误率' });
  await expect(rate.locator('.v')).toHaveText('—');
  await expect(rate.locator('.vz-kpi-u')).toHaveCount(0);
  expect(errors).toEqual([]);
});

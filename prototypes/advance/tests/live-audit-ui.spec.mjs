// Front-end live audit (fix/app-feedback-r4 · audit-ui). Live rows may carry no outcome / verify signal and the L0 insight is a
// rule template; neither may be dressed up as a real number or as AI. Flow (mac-14 only):
//  1 unknown outcome   facts with out / verify = null: Lite home 完成率 tile reads「—」(never 0 %), the evidence line has no
//                      「0% 要求验证」; A1 outcome card says 完成 — and how many sessions have a result; the session lists
//                      badge each row 结果未知 (not 完成)
//  2 rule badges       live A1 / Lite home insight carries the neutral「规则」tag and no 重新生成; Lite session insight too
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx } from './live-helpers.mjs';

test.beforeEach(async ({ page }) => { test.skip(test.info().project.name !== 'mac-14', 'interaction checks run once'); await page.emulateMedia({ reducedMotion: 'reduce' }); });

function factsNoOutcome() {
  const f = fx('core/facts.json');
  const drop = ['out', 'verify'];
  const idx = drop.map((k) => f.fields.indexOf(k)).filter((i) => i >= 0).sort((a, b) => b - a);
  idx.forEach((i) => { f.fields.splice(i, 1); f.rows.forEach((r) => r.splice(i, 1)); });
  drop.forEach((k) => { f.constants[k] = null; });
  return f;
}

test('unknown outcome / verify never shows as 0 % or 完成', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, 'core', { 'GET /v1/uiview/facts': factsNoOutcome() });
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
  await expect(ai.locator('.tag')).toHaveText('规则');
  await expect(ai.locator('.aib')).toHaveCount(0);
  await expect(page.locator('#aiCard [data-act="regen"]')).toHaveCount(0);
  await page.evaluate(() => { go('overview'); edSet('lite'); });
  await expect(page.locator('#main .l-hero .tag')).toHaveText('规则');
  await expect(page.locator('#main .l-hero .aib')).toHaveCount(0);
  await page.evaluate(() => go('l-sessions'));
  await expect(page.locator('#main .l-ins .tag')).toHaveText('规则');
  await expect(page.locator('#main .l-ins .aib')).toHaveCount(0);
  expect(errors).toEqual([]);
});

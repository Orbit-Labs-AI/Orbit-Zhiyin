// v0.0.4 bug hunt (UI) regressions — synthetic fixtures, stubbed gateway (mac-14 only):
//  K1  a KPI tile without a drawable trend has no period label: A4 仅看失败 reads「36」, not「36 近 12 周」(a 12-week count)
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, PASS } from './live-helpers.mjs';

test.beforeEach(async ({ page }) => { test.skip(test.info().project.name !== 'mac-14', 'interaction checks run once'); test.skip(!!PASS, 'stubbed bodies'); await page.emulateMedia({ reducedMotion: 'reduce' }); });

test('K1 A4: 仅看失败 has no 近 12 周 next to the failure count', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's3']);
  await openLive(page, 'tools');
  await page.evaluate(() => { S.tools.failOnly = true; edSet('advance', 'tools'); });
  const fail = page.locator('#main .vz-kpi').filter({ hasText: '失败次数' });
  await expect(fail).toBeVisible();
  await expect(fail.locator('.vz-spark')).toHaveCount(0);
  await expect(fail.locator('.vz-kpi-p')).toHaveCount(0);
  // the tiles that do draw a 12-week line keep their label
  await page.evaluate(() => { S.tools.failOnly = false; render(); });
  const calls = page.locator('#main .vz-kpi').filter({ hasText: '工具调用' });
  await expect(calls.locator('.vz-kpi-p')).toHaveText('近 12 周');
  expect(errors).toEqual([]);
});

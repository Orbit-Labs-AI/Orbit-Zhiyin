// v0.0.4 bug hunt (UI) regressions — synthetic fixtures, stubbed gateway (mac-14 only):
//  K1  a KPI tile without a drawable trend has no period label: A4 仅看失败 reads「36」, not「36 近 12 周」(a 12-week count)
//  R1  a live rec with a body but no path hint: preview says 剪贴板 / 不写入文件 (copy) or 由安装预览生成 (install), never an
//      empty path, an empty file name marked 新建 or「已限定项目 · 」with nothing after it
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

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

test('R1 A7: preview of a live rec without a path hint never shows an empty target', async ({ page }) => {
  const errors = collectErrors(page);
  const b = fx('recs/recommendations.json');
  const copy = b.items.find((c) => c.ui.primary === '复制片段'); copy.ui.target = '';
  const inst = b.items.find((c) => c.ui.primary === '预览并安装' && c.ui.file.length); inst.ui.target = '';
  await stubGateway(page, 's1', { 'GET /v1/recommendations': b, 'GET /v1/install/state': { items: [] } });
  await openLive(page, 'recs');
  await expect.poll(() => page.evaluate(() => RECS.filter((r) => r.live).length)).toBe(3);
  const pv = page.locator('#content .rc-pv');
  await page.evaluate((i) => { edSet('advance', 'recs'); S.recs.lv = new Set([1, 2, 3, 4]); S.recs.sel = i; S.recs.tab = 'preview'; render(); }, copy.candidate_id);
  await expect(pv.locator('[data-tl="rec-pv-clip"]')).toHaveText('剪贴板');
  await expect(pv).toContainText('不写入文件');
  await expect(pv).not.toContainText('已限定项目');
  await expect(pv).not.toContainText('新建');
  await expect(pv.locator('.code')).toHaveCount(1);
  await page.evaluate((i) => { S.recs.sel = i; S.recs.tab = 'preview'; render(); }, inst.candidate_id);
  await expect(pv.locator('[data-tl="rec-pv-planned"]')).toContainText('安装预览');
  await expect(pv).not.toContainText('已限定项目');
  await expect(pv).not.toContainText('不写入文件');
  expect(errors).toEqual([]);
});

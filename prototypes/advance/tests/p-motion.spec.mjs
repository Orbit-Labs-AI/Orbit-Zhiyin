// Motion layer (src/js/37-motion.js, shared by Lite and Advance):
//   enter cascade   go() into a page animates the #content blocks; they end fully visible with no transform left behind
//   count-up        data-count numbers roll from 0 on enter and from the previous value on a filter re-render, ending on the target
//   reduced motion  no cascade, numbers show the target at once
//   page guide      「这页回答」 line on every page of both editions; × hides it everywhere and is remembered; 显示 menu restores it
//   micro           seg selection slides, filter chips pop in / shrink out before the filter is cleared
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';

const settled = (page) => page.evaluate(() => motionBlocks($('#content')).map((el) => {
  const cs = getComputedStyle(el); return { op: cs.opacity, tf: cs.transform, n: el.getAnimations().length };
}));
const kpiDone = (page) => page.evaluate(() => $$('#content [data-count]').every((el) => el.textContent.replace(/[^\d.-]/g, '') === String(+el.dataset.count) || parseFloat(el.textContent.replace(/[^\d.-]/g, '')) === +el.dataset.count));

test.beforeEach(({}, info) => { test.skip(info.project.name !== 'mac-14' && info.project.name !== 'compact', 'motion runs at two sizes'); });

test('page enter cascades the blocks and leaves no transform behind', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'tools');
  await page.evaluate(() => go('overview'));
  const running = await page.evaluate(() => motionBlocks($('#content')).filter((el) => el.getAnimations().length).length);
  expect(running).toBeGreaterThan(5);
  // the cascade is staggered: a later block starts after an earlier one
  const delays = await page.evaluate(() => motionBlocks($('#content')).slice(0, 4).map((el) => el.getAnimations()[0].effect.getTiming().delay));
  expect(delays[3]).toBeGreaterThan(delays[0]);
  await expect.poll(async () => (await settled(page)).every((b) => b.n === 0)).toBe(true);
  for (const b of await settled(page)) { expect(b.op).toBe('1'); expect(b.tf).toBe('none'); }
  // a filter re-render does not replay the cascade
  await page.locator('#main .frow .seg button').first().click();
  expect(await page.evaluate(() => motionBlocks($('#content')).filter((el) => el.getAnimations().some((a) => a.effect.getTiming().delay > 0)).length)).toBe(0);
  expect(errors).toEqual([]);
});

test('KPI numbers count up from 0 on enter and from the previous value on re-render', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'tools');
  await page.evaluate(() => go('overview'));
  const first = page.locator('#ovTiles .vz-kpi .v').first();
  const target = await first.getAttribute('data-count');
  expect(Number(target)).toBeGreaterThan(10);
  const early = await first.textContent();
  expect(Number(early.replace(/,/g, ''))).toBeLessThan(Number(target));
  await expect.poll(() => kpiDone(page)).toBe(true);
  expect((await first.textContent()).replace(/,/g, '')).toBe(target);
  expect(await page.evaluate(() => getComputedStyle($('#ovTiles .vz-kpi .v')).fontVariantNumeric)).toContain('tabular-nums');
  expect(await page.evaluate(() => $('#ovTiles .vz-kpi .v').style.minWidth)).toBe('');
  // re-render with a narrower range: rolls from the old value down to the new one
  await page.evaluate(() => { S.range = 7; render(); });
  const t2 = await first.getAttribute('data-count');
  expect(Number(t2)).toBeLessThan(Number(target));
  const mid = Number((await first.textContent()).replace(/,/g, ''));
  expect(mid).toBeGreaterThan(Number(t2));
  await expect.poll(() => kpiDone(page)).toBe(true);
  expect((await first.textContent()).replace(/,/g, '')).toBe(t2);
  // decimals and suffixes survive: recs savings (≈ 6.1 h) and project hours (12.3h)
  await go(page, 'recs');
  await expect.poll(() => kpiDone(page)).toBe(true);
  expect(await page.locator('.rc-save b').first().textContent()).toMatch(/^≈ [\d.]+ (h|min)$/);
  await go(page, 'projects');
  await expect.poll(() => kpiDone(page)).toBe(true);
  expect(await page.locator('.pj-tbl td[data-count]').nth(1).textContent()).toMatch(/^\d+\.\dh$/);
  expect(errors).toEqual([]);
});

test('reduced motion shows the final numbers at once and skips the cascade', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openDemo(page);
  await go(page, 'tools');
  await page.evaluate(() => go('overview'));
  expect(await kpiDone(page)).toBe(true);
  expect(await page.evaluate(() => motionBlocks($('#content')).some((el) => el.getAnimations().length))).toBe(false);
  await page.locator('#main .frow .seg button').first().click();
  expect(await page.locator('#main .seg-ind').count()).toBe(0);
  expect(errors).toEqual([]);
});

test('page guide: on every page of both editions, × hides it everywhere and is remembered', async ({ page }) => {
  const errors = await openDemo(page);
  const routes = await page.evaluate(() => ROUTES.map((r) => r[0]));
  for (const r of routes) {
    await go(page, r);
    await expect(page.locator('#content > .pg-guide')).toHaveCount(1);
    await expect(page.locator('#content > .pg-guide')).toContainText('这页回答');
    await expect(page.locator('#content > .pg-guide')).toContainText('先');
  }
  // Lite uses the same component with its own, shorter line
  await page.evaluate(() => { S.ed = 'lite'; go('l-home'); });
  const lite = page.locator('#content > .pg-guide');
  await expect(lite).toHaveCount(1);
  const liteTxt = await lite.textContent();
  await page.evaluate(() => { S.ed = 'advance'; go('overview'); });
  expect(liteTxt.length).toBeLessThan((await page.locator('#content > .pg-guide').textContent()).length);
  // × collapses it, the choice holds for every page and survives a reload
  await page.locator('.pg-guide-x').click();
  await expect(page.locator('.pg-guide')).toHaveCount(0);
  await go(page, 'tools');
  await expect(page.locator('.pg-guide')).toHaveCount(0);
  await page.evaluate(() => { S.ed = 'lite'; go('l-recs'); });
  await expect(page.locator('.pg-guide')).toHaveCount(0);
  await page.evaluate(() => { S.ed = 'advance'; go('overview'); });
  await page.reload();
  await expect(page.locator('#main')).not.toBeEmpty();
  await expect(page.locator('.pg-guide')).toHaveCount(0);
  // 显示 › 页面导读 brings it back
  await page.locator('.mbar [data-m="view"]').click();
  await page.locator('#dd').getByText('页面导读').click();
  await expect(page.locator('#content > .pg-guide')).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('Lite pages get the same cascade, guide and count-up', async ({ page }) => {
  const errors = await openDemo(page);
  await page.evaluate(() => { S.ed = 'lite'; $('#win').dataset.ed = 'lite'; go('l-home'); });
  await expect.poll(() => page.evaluate(() => S.route)).toBe('l-home');
  await expect(page.locator('#content > .pg-guide')).toHaveCount(1);
  await page.evaluate(() => go('l-persona'));
  expect(await page.evaluate(() => motionBlocks($('#content')).some((el) => el.getAnimations().length))).toBe(true);
  await expect.poll(async () => (await settled(page)).every((b) => b.n === 0 && b.op === '1' && b.tf === 'none')).toBe(true);
  // the data-count convention works on any markup: 0 → 1,234 with the separator kept
  await page.evaluate(() => { $('#content').insertAdjacentHTML('beforeend', '<span id="cu" data-count="1234">1,234</span>'); countUp($('#content'), { fromZero: true }); });
  expect(await page.locator('#cu').textContent()).not.toBe('1,234');
  await expect(page.locator('#cu')).toHaveText('1,234');
  expect(errors).toEqual([]);
});

test('seg selection slides and filter chips pop in / shrink out', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'overview');
  const seg = page.locator('#main .frow .seg');
  await seg.locator('button').nth(3).click();
  expect(await page.locator('#main .frow .seg .seg-ind').count()).toBe(1);
  await expect(page.locator('#main .seg-ind')).toHaveCount(0);
  await expect(seg).not.toHaveClass(/seg-mv/);
  await expect(seg.locator('button.on')).toHaveText('全部');
  await page.evaluate(() => { S.topic = Object.keys(TOPICS)[0]; render(); });
  const chip = page.locator('#main [data-act="clearFilter"]');
  expect(await chip.evaluate((c) => c.getAnimations().length)).toBe(1);
  await chip.evaluate((c) => c.getAnimations().forEach((a) => a.finish()));
  await chip.click();
  await expect.poll(() => page.evaluate(() => S.topic)).toBeNull();
  await expect(chip).toHaveCount(0);
  expect(errors).toEqual([]);
});

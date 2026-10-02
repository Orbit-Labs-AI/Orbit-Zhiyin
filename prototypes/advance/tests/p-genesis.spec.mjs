// Branch ui/ed-genesis: the Genesis sequence (first launch 2–3 and the persona reveal, src/js/56-onboarding.js).
// Runs at mac-14 and compact (the box switches to its stacked layout in narrow windows).
//
// Test flow:
//  1 full run       「开始分析」keeps the same box (no innerHTML swap): particles canvas, stage labels 01 → 04, facts one by one
//                   (OB.prog 0..3), six candidate type cards during 04, then the final card (code = obPersona().code, 匹配度);
//                  「查看完整画像」flies the code letters and the fingerprint (.g-fly clones) to the persona page's [data-hero]
//                   and closes the overlay; nothing is left behind and no page errors follow
//  2 skip           「跳过」at any moment lands on the final card at once; later timers do nothing; Tab never reaches the
//                   hidden half of the footer
//  3 reduced motion obStart and openReveal show the final state directly (no .run, no canvas); landing does not fly
//  4 Lite           with S.ed = 'lite' landing goes to l-persona with the analysed 90-day scope
//  5 interruptions  Esc / 在后台继续 / closeOverlay in the middle cancel every timer, frame and animation; the reveal's
//                  「查看完整画像」lands on persona the same way
import { test, expect } from '@playwright/test';
import { openDemo } from './helpers.mjs';

const only = () => test.skip(!['mac-14', 'compact'].includes(test.info().project.name), 'genesis runs at mac-14 and compact');
const start = (page) => page.evaluate(() => { go('overview'); openOnboarding(0); ACT.obNext(); });

test('first launch: one continuous sequence from 开始分析 to the persona page', async ({ page }) => {
  only();
  test.setTimeout(40_000);
  const errors = await openDemo(page);
  await start(page);
  const box0 = await page.evaluate(() => { window.__box = $('#overlay .obox'); return !!window.__box; });
  expect(box0).toBe(true);
  await page.locator('#overlay [data-act="obStart"]').click();
  // the step-1 box element is kept and becomes the Genesis box
  expect(await page.evaluate(() => $('#overlay .obox') === window.__box && $('#genBox').classList.contains('run'))).toBe(true);
  await expect(page.locator('#overlay canvas.g-cv')).toHaveCount(1);
  await expect(page.locator('#genBox .g-stage')).toContainText('01 /');
  const seen = new Set(); const stages = new Set(); let cards = 0;
  await expect.poll(async () => {
    const s = await page.evaluate(() => [OB.prog, OB.step, $('#genBox .g-stage') && $('#genBox .g-stage').textContent.slice(0, 2), $$('#genBox .g-card').length]);
    seen.add(s[0]); stages.add(s[2]); cards = Math.max(cards, s[3]);
    return s[1];
  }, { timeout: 9000, intervals: [100] }).toBe(3);
  expect([...seen].filter((x) => x >= 0).length, 'facts arrive one by one').toBeGreaterThanOrEqual(3);
  for (const k of ['01', '02', '03', '04']) expect([...stages], 'stage ' + k).toContain(k);
  expect(cards, 'candidate type cards appear around the dial').toBe(6);
  const want = await page.evaluate(() => obPersona().code);
  await expect(page.locator('#genBox')).toHaveClass(/skip/);
  await expect(page.locator('#genBox [data-g="code"]')).toHaveText(new RegExp(want.split('').join('[\\s\\S]*')));
  await expect(page.locator('#genBox [data-g="match"]')).toContainText('匹配度');
  await expect(page.locator('#overlay canvas')).toHaveCount(0);
  expect(await page.evaluate(() => document.activeElement && document.activeElement.dataset.act)).toBe('obDone');
  // landing: clones fly, overlay closes, route is the persona page, hero targets visible again
  await page.locator('#overlay [data-act="obDone"]').click();
  expect(await page.locator('.g-fly').count()).toBeGreaterThan(0);
  expect(await page.evaluate(() => S.route)).toBe('persona');
  await expect(page.locator('#overlay')).toBeHidden({ timeout: 2000 });
  expect(await page.evaluate(() => [GNS, OVL, document.querySelectorAll('.g-fly').length])).toEqual([null, null, 0]);
  expect(await page.evaluate(() => $$('#main [data-hero], #main [data-hero] .L').every((el) => getComputedStyle(el).visibility === 'visible'))).toBe(true);
  await page.waitForTimeout(1200);
  expect(errors).toEqual([]);
});

test('skip lands on the final card at once and nothing fires afterwards', async ({ page }) => {
  only();
  test.setTimeout(30_000);
  const errors = await openDemo(page);
  await start(page);
  await page.evaluate(() => ACT.obStart());
  await page.waitForTimeout(600);
  await page.locator('#genBox [data-act="genSkip"]').click();
  expect(await page.evaluate(() => [OB.step, OB.prog, $('#genBox').classList.contains('skip'), !!$('#overlay canvas')])).toEqual([3, 3, true, false]);
  await expect(page.locator('#genBox [data-act="obBg"]')).toBeDisabled();
  await expect(page.locator('#genBox [data-act="obDone"]')).toBeEnabled();
  await expect(page.locator('#genBox [data-act="genSkip"]')).toBeHidden();
  await expect(page.locator('#genBox .g-stage')).toContainText('05 /');
  // Tab stays in the overlay and never lands on a disabled (hidden) footer button
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => $('#overlay').contains(document.activeElement) && !document.activeElement.disabled)).toBe(true);
  }
  await page.waitForTimeout(6500);
  await expect(page.locator('#genBox .g-stage')).toContainText('05 /');
  expect(await page.evaluate(() => $$('#genBox .g-card').length)).toBe(0);
  expect(errors).toEqual([]);
});

test('reduced motion shows the final state directly and lands without flying', async ({ page }) => {
  only();
  const errors = await openDemo(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await start(page);
  await page.evaluate(() => ACT.obStart());
  expect(await page.evaluate(() => [OB.step, OB.prog, $('#genBox').classList.contains('run'), !!$('#overlay canvas'), GNS.done])).toEqual([3, 3, false, false, true]);
  await page.evaluate(() => ACT.obDone());
  expect(await page.evaluate(() => [S.route, $('#overlay').hidden, document.querySelectorAll('.g-fly').length])).toEqual(['persona', true, 0]);
  await page.evaluate(() => openReveal());
  await expect(page.locator('#revBox')).toHaveClass(/skip/);
  await expect(page.locator('#revStage')).toContainText('05 /');
  await page.evaluate(() => ACT.revGo());
  expect(await page.evaluate(() => [S.route, $('#overlay').hidden])).toEqual(['persona', true]);
  expect(errors).toEqual([]);
});

test('Lite edition: landing goes to l-persona', async ({ page }) => {
  only();
  const errors = await openDemo(page);
  await page.evaluate(() => { S.ed = 'lite'; $('#win').dataset.ed = 'lite'; go('l-home'); });
  await page.evaluate(() => { openOnboarding(0); ACT.obNext(); ACT.obStart(); ACT.genSkip(); ACT.obDone(); });
  expect(await page.evaluate(() => S.route)).toBe('l-persona');
  await expect(page.locator('#overlay')).toBeHidden({ timeout: 2000 });
  expect(await page.evaluate(() => [GNS, document.querySelectorAll('.g-fly').length])).toEqual([null, 0]);
  // the landing page keeps the analysed scope (last 90 days), so the code and the numbers match what was just generated
  expect(await page.evaluate(() => [S.range, S.persona.period, obPersona().code === personaNow().code])).toEqual([90, '90', true]);
  await expect(page.locator('#content [data-hero="code"]')).toBeVisible();
  await page.evaluate(() => { S.ed = 'advance'; $('#win').dataset.ed = 'advance'; go('overview'); });
  expect(errors).toEqual([]);
});

test('Esc, 在后台继续 and closing mid-run cancel everything; the reveal lands on persona', async ({ page }) => {
  only();
  test.setTimeout(40_000);
  const errors = await openDemo(page);
  // Esc in the middle of the first launch closes it
  await start(page);
  await page.evaluate(() => ACT.obStart());
  await page.waitForTimeout(2200);
  await page.keyboard.press('Escape');
  expect(await page.evaluate(() => [$('#overlay').hidden, GNS, !!document.querySelector('canvas.g-cv')])).toEqual([true, null, false]);
  // 在后台继续 in the middle
  await start(page);
  await page.evaluate(() => ACT.obStart());
  await page.waitForTimeout(3600);
  await page.locator('#overlay [data-act="obBg"]').click();
  expect(await page.evaluate(() => [$('#overlay').hidden, GNS])).toEqual([true, null]);
  // reveal: any key skips, then 查看完整画像 lands on persona
  await page.evaluate(() => { go('overview'); openReveal(); });
  await expect(page.locator('#revBox')).toHaveClass(/run/);
  await page.waitForTimeout(1200);
  await page.keyboard.press('Escape');
  await expect(page.locator('#revBox')).toHaveClass(/skip/);
  expect(await page.evaluate(() => document.activeElement && document.activeElement.dataset.act)).toBe('revGo');
  await page.keyboard.press('Enter');
  expect(await page.evaluate(() => S.route)).toBe('persona');
  await expect(page.locator('#overlay')).toBeHidden({ timeout: 2000 });
  // a reveal closed mid-run leaves nothing running
  await page.evaluate(() => { openReveal(); });
  await page.waitForTimeout(1500);
  await page.evaluate(() => { closeOverlay(); render(); });
  await page.waitForTimeout(6000);
  expect(await page.evaluate(() => [GNS, OVL, $('#overlay').hidden, document.querySelectorAll('.g-fly, canvas.g-cv').length])).toEqual([null, null, true, 0]);
  expect(errors).toEqual([]);
});

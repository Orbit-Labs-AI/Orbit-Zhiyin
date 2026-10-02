// Branch ui/compass: the collaboration fingerprint (fp2SVG, src/js/41-a2-persona.js) drawn as a compass, and the needle in
// Genesis (src/js/56-onboarding.js).
//
// Test flow:
//  1 dial         persona page: 120 bezel ticks, 8 rose points (4 major by D I M V + 4 minor), needle --hd = circular mean of
//                 session start times (computed here independently), 24 hour segments still expand into session dots
//  2 entry wobble entering persona (Advance) and l-persona (Lite) shakes the needle once (WAAPI on .fp-nd); re-renders do not
//  3 genesis      the needle is driven frame by frame while running, sits on --hd when the sequence ends, and the persona page
//                 it lands on points the same way (same data scope up to a session) without a wobble on arrival
//  4 reduced      reduce motion: no wobble on entry, Genesis opens on its final state with the needle on --hd
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';

// circular mean of start times on the 24 h dial, 0° = 00:00 clockwise (independent of fpHeading)
const meanDeg = (page, expr) => page.evaluate((e) => {
  const L = eval(e); let x = 0, y = 0;
  for (const s of L) { const t = (s.h * 60 + s.mi) / 1440 * 2 * Math.PI; x += Math.cos(t); y += Math.sin(t); }
  return ((Math.atan2(y, x) * 180 / Math.PI) % 360 + 360) % 360;
}, expr);
const needle = (page, scope) => page.evaluate((sc) => { const n = document.querySelector(sc + ' svg.fp2 .fp-needle'); return n ? { hd: parseFloat(getComputedStyle(n).getPropertyValue('--hd')), data: +n.dataset.hd, inline: n.style.transform, anims: n.querySelector('.fp-nd').getAnimations().length, title: n.querySelector('title').textContent } : null; }, scope);
const rot = (deg) => { const r = deg * Math.PI / 180; return [Math.cos(r), Math.sin(r)]; };

test('persona dial: bezel ticks, rose points, needle on the collaboration centre, hour ring still interactive', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'persona');
  const fp = page.locator('#main svg.fp2');
  const ticks = await fp.locator('.fp-tk').evaluateAll((els) => els.reduce((n, el) => n + (el.getAttribute('d').match(/M/g) || []).length, 0));
  expect(ticks, '120 bezel ticks (every 3°)').toBe(120);
  await expect(fp.locator('.fp-rose.pet .fp-pt')).toHaveCount(4);
  await expect(fp.locator('.fp-minor')).toHaveCount(4);
  expect(await fp.locator('.fp-rose .fp-pt').evaluateAll((els) => els.map((el) => el.dataset.k).join(''))).toBe('DIMV');
  // major point lengths follow the axis strength: the strongest axis has the longest point
  const lens = await page.evaluate(() => ['D', 'I', 'M', 'V'].map((k, i) => [axisView(CUR.persona, i).strong, fpRoseLen(axisView(CUR.persona, i).strong)]));
  for (const [s, l] of lens) expect(l).toBeGreaterThanOrEqual(0.36 * 70 - 0.01), expect(l).toBeLessThanOrEqual(70.01), expect(s).toBeGreaterThanOrEqual(50);
  const want = await meanDeg(page, 'personaScope([PERIODS[S.persona.period][0], PERIODS[S.persona.period][1]])');
  const n = await needle(page, '#main');
  expect(Math.abs(n.hd - want)).toBeLessThan(0.1);
  expect(n.data).toBe(n.hd);
  expect(n.title).toMatch(/^协作重心 \d{1,2}:\d{2}$/);
  // the rendered transform is rotate(--hd) around the dial centre
  const m = await page.evaluate(() => getComputedStyle(document.querySelector('#main svg.fp2 .fp-needle')).transform);
  const [c, s] = rot(n.hd); const v = m.match(/matrix\(([^)]+)\)/)[1].split(',').map(Number);
  expect(Math.abs(v[0] - c) + Math.abs(v[1] - s)).toBeLessThan(0.01);
  await expect(page.locator('#main .pe-fp-legend')).toContainText('协作重心 ' + n.title.split(' ')[1]);
  // hour ring: 24 segments, clicking one expands its session dots, again collapses
  await expect(fp.locator('.fps')).toHaveCount(24);
  const h = await page.evaluate(() => CUR.fp.byH.findIndex((x) => x.length > 0));
  await page.locator('#main svg.fp2 .fps[data-h="' + h + '"]').dispatchEvent('click');
  await expect.poll(() => page.locator('#main svg.fp2 .fpd').count()).toBeGreaterThan(0);
  await expect(page.locator('#main svg.fp2 .fps.dim')).toHaveCount(23);
  await page.locator('#main svg.fp2 .fps[data-h="' + h + '"]').dispatchEvent('click');
  await expect(page.locator('#main svg.fp2 .fpd')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('entering persona / l-persona wobbles the needle once; re-renders and hour clicks do not', async ({ page }) => {
  const errors = await openDemo(page);
  await page.evaluate(() => go('overview'));
  await page.evaluate(() => go('persona'));
  expect((await needle(page, '#main')).anims, 'damped wobble on entry').toBe(1);
  const kf = await page.evaluate(() => document.querySelector('#main svg.fp2 .fp-nd').getAnimations()[0].effect.getKeyframes().map((k) => k.transform));
  expect(kf[0]).toBe('rotate(-40deg)'); expect(kf[kf.length - 1]).toBe('rotate(0deg)');
  await page.waitForTimeout(1500);
  expect((await needle(page, '#main')).anims).toBe(0);
  await page.evaluate(() => render());
  expect((await needle(page, '#main')).anims, 'plain re-render keeps the needle still').toBe(0);
  // Lite persona gets the same dial and the same entrance
  await page.evaluate(() => { S.ed = 'lite'; $('#win').dataset.ed = 'lite'; go('l-home'); });
  await page.evaluate(() => go('l-persona'));
  await expect(page.locator('#content [data-hero="fp"] svg.fp2 .fp-needle')).toHaveCount(1);
  expect((await needle(page, '#content [data-hero="fp"]')).anims).toBe(1);
  expect(errors).toEqual([]);
});

test('genesis: needle spins, settles on the collaboration centre, and lands matching the persona page', async ({ page }) => {
  test.skip(!['mac-14', 'compact'].includes(test.info().project.name), 'genesis runs at mac-14 and compact');
  test.setTimeout(40_000);
  const errors = await openDemo(page);
  await page.evaluate(() => { go('overview'); openOnboarding(0); ACT.obNext(); });
  await page.locator('#overlay [data-act="obStart"]').click();
  // while running the needle is written frame by frame (inline transform), with several different angles in 01
  const angles = new Set();
  for (let i = 0; i < 6; i++) { angles.add(await page.evaluate(() => $('#genBox .fp-needle').style.transform)); await page.waitForTimeout(120); }
  expect([...angles].filter(Boolean).length).toBeGreaterThanOrEqual(4);
  // the planned curve is continuous through 01 → 02 (lands on 00 exactly when the sweep starts) and ends on --hd
  const c = await page.evaluate(() => { const g = GNS; const P = g.T.place; return { a: genNeedle(g, P - 1) % 360, b: genNeedle(g, P), end: genNeedle(g, g.T.end), hd: g.hd }; });
  expect(c.b).toBe(0); expect(360 - c.a).toBeLessThan(1);
  expect(Math.abs(((c.end - c.hd) % 360 + 540) % 360 - 180)).toBeLessThan(0.05);
  await expect.poll(() => page.evaluate(() => OB.step), { timeout: 9000 }).toBe(3);
  const g = await needle(page, '#genBox');
  expect(g.inline, 'final state hands the needle back to --hd').toBe('');
  expect(Math.abs(g.hd - await meanDeg(page, 'obSel()'))).toBeLessThan(0.1);
  await page.locator('#overlay [data-act="obDone"]').click();
  await expect(page.locator('#overlay')).toBeHidden({ timeout: 2000 });
  const p = await needle(page, '#main');
  // the landing page uses the persona scope (which can differ from obSel by a session); the angle must not visibly jump
  expect(Math.abs(p.hd - g.hd)).toBeLessThan(1);
  expect(p.anims, 'no wobble when the dial flies in').toBe(0);
  expect(errors).toEqual([]);
});

test('reduced motion: needle still on entry and genesis opens with the needle on --hd', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openDemo(page);
  await page.evaluate(() => go('overview'));
  await page.evaluate(() => go('persona'));
  expect((await needle(page, '#main')).anims).toBe(0);
  await page.locator('#main svg.fp2').hover();
  expect(await page.evaluate(() => getComputedStyle(document.querySelector('#main svg.fp2 .fp-nd')).animationName)).toBe('none');
  await page.evaluate(() => openReveal());
  await expect(page.locator('#revBox')).toHaveClass(/skip/);
  const r = await needle(page, '#revBox');
  expect(r.inline).toBe(''); expect(r.anims).toBe(0);
  expect(await page.evaluate(() => [GNS.done, !!$('#overlay canvas')])).toEqual([true, false]);
  expect(errors).toEqual([]);
});

// Branches ui/compass + ui/orbit: the collaboration fingerprint (fp2SVG, src/js/41-a2-persona.js) drawn as the Orbit compass,
// and the needle / orbit motif in Genesis (src/js/56-onboarding.js).
//
// Test flow:
//  1 dial         persona page: 120 bezel ticks, 8 rose points (4 major by D I M V + 4 minor), needle --hd = circular mean of
//                 session start times (computed here independently); five smooth orbit-band layers (one per Agent, 2° samples);
//                 24 transparent hour hit areas still expand into session dots; each Agent planet sits on that Agent's own
//                 circular mean (measured from the rendered dot, 1°); the needle is 0.8 × RR and drawn under the letters;
//                 --orbit appears only on the needle's north half, the 00 triangle and the Orbit mark
//  2 entry        entering persona (Advance) and l-persona (Lite) shakes the needle once (WAAPI on .fp-nd), sweeps the band open
//                 from 00 (.fp-sweep) and runs every planet from 00 to its heading; re-renders do not
//  3 genesis      the dial starts tilted (Orbit orbit, rotateX) and flattens; the needle is driven frame by frame, sits on --hd
//                 when the sequence ends, and the persona page it lands on points the same way without a wobble on arrival
//  4 reduced      reduce motion: nothing moves on entry, Genesis opens on its final state with the needle on --hd
//  5 brand        no visible "Tandem" left: window title and the text of every page, settings tab, onboarding step and menu
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
const adiff = (a, b) => Math.abs(((a - b) % 360 + 540) % 360 - 180);

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
  // orbit band: one smooth layer per Agent with sessions, in AG order, 181 samples (every 2°) on each edge
  const layers = await fp.locator('.fp-orb .fpo').evaluateAll((els) => els.map((el) => [el.dataset.a, (el.getAttribute('d').match(/L/g) || []).length]));
  const withS = await page.evaluate(() => { const L = personaScope([PERIODS[S.persona.period][0], PERIODS[S.persona.period][1]]); return AG.filter((a) => L.some((s) => s.a === a.id)).map((a) => a.id); });
  expect(layers.map((x) => x[0])).toEqual(withS);
  expect(withS.length).toBe(5);
  for (const [, n] of layers) expect(n).toBe(181 * 2 - 1);
  expect(await fp.locator('.fp-orb').getAttribute('mask')).toMatch(/^url\(#fpm\d+\)$/);
  // planets: one per Agent with sessions; the rendered dot sits on that Agent's own circular mean (independent, 1°)
  const pl = await page.evaluate(() => {
    const svg = document.querySelector('#main svg.fp2'), r = svg.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    return [...svg.querySelectorAll('.fp-pl')].map((g) => { const b = g.querySelector('.fp-pd').getBoundingClientRect(); return [g.dataset.a, (Math.atan2(b.left + b.width / 2 - cx, cy - (b.top + b.height / 2)) * 180 / Math.PI + 360) % 360]; });
  });
  expect(pl.map((x) => x[0])).toEqual(withS);
  for (const [a, deg] of pl) expect(adiff(deg, await meanDeg(page, 'personaScope([PERIODS[S.persona.period][0], PERIODS[S.persona.period][1]]).filter((s) => s.a === "' + a + '")')), a).toBeLessThan(1);
  await page.locator('#main svg.fp2 .fp-pl').last().dispatchEvent('mouseover');
  // needle: 0.8 × rose radius, shorter than the letter ring, drawn before (under) the letters and scores
  const nd = await page.evaluate(() => { const d = $('#main svg.fp2 .fp-nn').getAttribute('d'); const kids = [...$('#main svg.fp2').children].map((e) => e.getAttribute('class')); return { nl: 200 - +d.match(/^M200 ([\d.]+)/)[1], rr: FPG.RR, order: [kids.indexOf('fp-compass'), kids.indexOf('fp-axl'), kids.indexOf('fp-rose pet')] }; });
  expect(nd.nl).toBeCloseTo(0.8 * nd.rr, 5);
  expect(nd.nl).toBeLessThan(nd.rr + 11);
  expect(nd.order[2]).toBeLessThan(nd.order[0]); expect(nd.order[0]).toBeLessThan(nd.order[1]);
  // --orbit is used only by the needle's north half, the 00 reference triangle and the Orbit mark (plus the legend's needle swatch)
  for (const theme of ['light', 'dark']) {
    const bad = await page.evaluate((t) => {
      setTheme(t);
      const want = getComputedStyle(document.documentElement).getPropertyValue('--orbit').trim();
      const probe = document.createElement('i'); probe.style.color = want; document.body.appendChild(probe); const rgb = getComputedStyle(probe).color; probe.remove();
      const ok = (el) => el.matches('.fp-nn, .fp-n0') || !!el.closest('.orbit-mark') || (el.closest('.pe-fp-legend') && el.tagName === 'SPAN');
      const hits = [...document.querySelectorAll('#desk *')].filter((el) => { const c = getComputedStyle(el); return [c.fill, c.stroke, c.backgroundColor, el.closest('svg') ? '' : c.color].includes(rgb); });
      return { rgb, needle: hits.some((el) => el.matches('#main .fp-nn')), tri: hits.some((el) => el.matches('#main .fp-n0')), bad: hits.filter((el) => !ok(el)).map((el) => el.tagName + '.' + el.getAttribute('class')) };
    }, theme);
    expect(bad.rgb, theme).toBe(theme === 'light' ? 'rgb(95, 107, 111)' : 'rgb(163, 173, 176)');
    expect([bad.needle, bad.tri, bad.bad], theme).toEqual([true, true, []]);
  }
  await page.evaluate(() => setTheme('system'));
  expect(errors).toEqual([]);
});

test('entering persona / l-persona wobbles the needle once; re-renders and hour clicks do not', async ({ page }) => {
  const errors = await openDemo(page);
  await page.evaluate(() => go('overview'));
  await page.evaluate(() => go('persona'));
  expect((await needle(page, '#main')).anims, 'damped wobble on entry').toBe(1);
  const kf = await page.evaluate(() => document.querySelector('#main svg.fp2 .fp-nd').getAnimations()[0].effect.getKeyframes().map((k) => k.transform));
  expect(kf[0]).toBe('rotate(-40deg)'); expect(kf[kf.length - 1]).toBe('rotate(0deg)');
  // the band sweeps open from 00 and every planet runs from 00 to its own heading
  const orbIn = (sc) => page.evaluate((sc) => { const svg = document.querySelector(sc + ' svg.fp2'); return { sweep: svg.querySelector('.fp-sweep').getAnimations().map((a) => a.effect.getKeyframes().map((k) => k.strokeDashoffset)), pl: [...svg.querySelectorAll('.fp-pl')].map((g) => { const a = g.getAnimations()[0]; const k = a ? a.effect.getKeyframes() : []; return [a ? a.effect.getTiming().duration : 0, k.length ? k[0].transform : null, k.length ? k[k.length - 1].transform : null, 'rotate(' + g.dataset.pa + 'deg)']; }) }; }, sc);
  const o = await orbIn('#main');
  expect(o.sweep).toEqual([['1', '0']]);
  expect(o.pl.length).toBe(5);
  for (const [dur, k0, k1, want] of o.pl) expect([dur, k0, k1]).toEqual([1200, 'rotate(0deg)', want]);
  await page.waitForTimeout(1500);
  expect((await needle(page, '#main')).anims).toBe(0);
  await page.evaluate(() => render());
  expect((await needle(page, '#main')).anims, 'plain re-render keeps the needle still').toBe(0);
  expect(await orbIn('#main'), 'plain re-render keeps the orbit still').toEqual({ sweep: [], pl: o.pl.map((x) => [0, null, null, x[3]]) });
  // Lite persona gets the same dial and the same entrance
  await page.evaluate(() => { S.ed = 'lite'; $('#win').dataset.ed = 'lite'; go('l-home'); });
  await page.evaluate(() => go('l-persona'));
  await expect(page.locator('#content [data-hero="fp"] svg.fp2 .fp-needle')).toHaveCount(1);
  expect((await needle(page, '#content [data-hero="fp"]')).anims).toBe(1);
  const lo = await orbIn('#content [data-hero="fp"]');
  expect(lo.sweep.length).toBe(1); expect(lo.pl.every((x) => x[0] === 1200)).toBe(true);
  expect(errors).toEqual([]);
});

test('genesis: needle spins, settles on the collaboration centre, and lands matching the persona page', async ({ page }) => {
  test.skip(!['mac-14', 'compact'].includes(test.info().project.name), 'genesis runs at mac-14 and compact');
  test.setTimeout(40_000);
  const errors = await openDemo(page);
  await page.evaluate(() => { go('overview'); openOnboarding(0); ACT.obNext(); });
  await page.locator('#overlay [data-act="obStart"]').click();
  // 01 opens on the Orbit motif: the dial is seen tilted (rotateX) and flattens; the needle is written frame by frame (inline
  // transform) — held on 00 while the mark's inner arc folds into it, then spinning with several different angles
  expect(await page.evaluate(() => $('#genBox .g-fp').style.transform)).toMatch(/rotateX\((?!0\.00deg)/);
  await expect(page.locator('#genBox .g-arc')).toHaveCount(1);
  const angles = new Set();
  for (let i = 0; i < 12; i++) { angles.add(await page.evaluate(() => $('#genBox .fp-needle').style.transform)); await page.waitForTimeout(120); }
  expect([...angles].filter(Boolean).length).toBeGreaterThanOrEqual(4);
  await expect.poll(() => page.evaluate(() => $('#genBox .g-fp').style.transform), { timeout: 4000 }).toBe('');
  // the planned curve is continuous through 01 → 02 (lands on 00 exactly when the sweep starts) and ends on --hd
  const c = await page.evaluate(() => { const g = GNS; const P = g.T.place; return { a: genNeedle(g, P - 1) % 360, b: genNeedle(g, P), end: genNeedle(g, g.T.end), hd: g.hd }; });
  expect(c.b).toBe(0); expect(360 - c.a).toBeLessThan(1);
  expect(Math.abs(((c.end - c.hd) % 360 + 540) % 360 - 180)).toBeLessThan(0.05);
  await expect.poll(() => page.evaluate(() => OB.step), { timeout: 9000 }).toBe(3);
  const g = await needle(page, '#genBox');
  expect(g.inline, 'final state hands the needle back to --hd').toBe('');
  // the band has been swept open and the planets have settled back on their --pa
  expect(await page.evaluate(() => [$('#genBox .fp-sweep').style.strokeDashoffset, $$('#genBox .fp-pl').every((el) => !el.style.transform && !el.style.opacity)])).toEqual(['', true]);
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
  expect(await page.evaluate(() => [$('#main .fp-sweep').getAnimations().length, $$('#main .fp-pl').filter((g) => g.getAnimations().length).length])).toEqual([0, 0]);
  const r = await needle(page, '#revBox');
  expect(r.inline).toBe(''); expect(r.anims).toBe(0);
  expect(await page.evaluate(() => [GNS.done, !!$('#overlay canvas')])).toEqual([true, false]);
  expect(errors).toEqual([]);
});

test('brand: no visible "Tandem" in the title, pages, settings, onboarding or menus', async ({ page }) => {
  test.skip(!['mac-14', 'compact'].includes(test.info().project.name), 'text sweep runs at mac-14 and compact');
  test.setTimeout(60_000);
  const errors = await openDemo(page);
  expect(await page.title()).toMatch(/^Orbit/);
  const seen = (where) => page.evaluate((w) => { const t = document.title + '\n' + document.body.innerText; return t.includes('Tandem') ? w + ': ' + t.split('\n').filter((l) => l.includes('Tandem')).join(' | ') : null; }, where);
  const hits = [];
  hits.push(await seen('start'));
  for (const ed of ['advance', 'lite']) {
    const routes = await page.evaluate((e) => { S.ed = e; $('#win').dataset.ed = e; render(); return navRoutes().map((r) => r[0]); }, ed);
    for (const r of routes) { await page.evaluate((x) => go(x), r); hits.push(await seen(ed + ' ' + r)); }
  }
  await page.evaluate(() => { S.ed = 'advance'; $('#win').dataset.ed = 'advance'; go('overview'); });
  for (const t of ['general', 'sources', 'privacy', 'analysis', 'notify', 'about']) { await page.evaluate((x) => openSettings(x), t); hits.push(await seen('settings ' + t)); }
  await page.evaluate(() => { $('#set').hidden = true; openOnboarding(0); });
  hits.push(await seen('onboarding 0'));
  await page.evaluate(() => ACT.obNext()); hits.push(await seen('onboarding 1'));
  await page.evaluate(() => closeOverlay());
  await page.locator('.mbar .app').click(); hits.push(await seen('app menu'));
  await page.keyboard.press('Escape');
  await page.evaluate(() => { closeDD(); S.pop = true; render(); }); hits.push(await seen('menu bar panel'));
  expect(await page.evaluate(() => reportMD().includes('Tandem'))).toBe(false);
  expect(hits.filter(Boolean)).toEqual([]);
  expect(errors).toEqual([]);
});

// The App icon and the menu-bar item are the official Orbit logo (docs/design/logo/variants/spiral, via tools/brand-icon.mjs):
// the full rendition from 48px up, the heavier small rendition below; the tile uses the logo's 22.5% corner; the page has the
// icon as its favicon.
test('App icon and menu-bar item use the official Orbit logo vectors', async ({ page }) => {
  const errors = await openDemo(page);
  const r = await page.evaluate(() => ({
    big: appIcon(64).includes(ORBIT_ICON), small: appIcon(32).includes(ORBIT_SMALL), glyph: GLYPH.includes(ORBIT_SMALL) && GLYPH.includes('currentColor'),
    menubar: !!document.querySelector('#mbar .glyph .orbit-mark polygon'),
    radius: (() => { const s = document.createElement('span'); s.className = 'appicon'; s.style.width = '100px'; s.style.height = '100px'; document.body.appendChild(s); const v = parseFloat(getComputedStyle(s).borderTopLeftRadius); s.remove(); return v; })(),
    favicon: (document.querySelector('link[rel="icon"]') || {}).href || ''
  }));
  expect([r.big, r.small, r.glyph, r.menubar]).toEqual([true, true, true, true]);
  expect(r.radius).toBeCloseTo(22.46, 1);
  expect(r.favicon.startsWith('data:image/svg+xml,')).toBe(true);
  expect(errors).toEqual([]);
});

// Branches ui/compass + ui/orbit: the collaboration fingerprint (fp2SVG, src/js/41-a2-persona.js) drawn as the Orbit compass,
// and the needle / orbit motif in Genesis (src/js/56-onboarding.js).
//
// Test flow:
//  1 dial         persona page: 120 bezel ticks; the core is the persona's flower (.fp-flower data-code = the code; 12 / 5
//                 petals for M / F, a back whorl only for V, a helm ring only for S) and all 16 types give 16 different flowers;
//                 the flower turns to --hd = circular mean of session start times (computed here independently) so its lead
//                 petal points there; the orbit is one smooth layer per Agent (2° samples) with a contour line each;
//                 24 transparent hour hit areas still expand into session dots; each Agent badge carries that Agent's logo and
//                 sits on that Agent's own circular mean (measured from the rendered badge, 1°), badges never overlap;
//                 --orbit appears only on the lead petal, the 00 triangle and the Orbit mark
//  2 entry        entering persona (Advance) and l-persona (Lite) sways the flower once (WAAPI on .fp-bd), sweeps the band open
//                 from 00 (.fp-sweep) and runs every badge from 00 to its heading; re-renders do not
//  3 genesis      the dial starts tilted (Orbit orbit, rotateX) and flattens; the closed bud is spun frame by frame, blooms,
//                 sits on --hd when the sequence ends, and the persona page it lands on points the same way without a sway
//  4 reduced      reduce motion: nothing moves on entry, Genesis opens on its final state with the flower open and on --hd
//  5 brand        no visible "Tandem" left: window title and the text of every page, settings tab, onboarding step and menu  // orbit-rename: keep
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';

// circular mean of start times on the 24 h dial, 0° = 00:00 clockwise (independent of fpHeading)
const meanDeg = (page, expr) => page.evaluate((e) => {
  const L = eval(e); let x = 0, y = 0;
  for (const s of L) { const t = (s.h * 60 + s.mi) / 1440 * 2 * Math.PI; x += Math.cos(t); y += Math.sin(t); }
  return ((Math.atan2(y, x) * 180 / Math.PI) % 360 + 360) % 360;
}, expr);
const needle = (page, scope) => page.evaluate((sc) => { const n = document.querySelector(sc + ' svg.fp2 .fp-bloom'); return n ? { hd: parseFloat(getComputedStyle(n).getPropertyValue('--hd')), data: +n.dataset.hd, inline: n.style.transform, anims: n.querySelector('.fp-bd').getAnimations().length, closed: [...n.querySelectorAll('.fp-pw')].filter((el) => el.style.transform).length, title: n.querySelector('title').textContent } : null; }, scope);
const rot = (deg) => { const r = deg * Math.PI / 180; return [Math.cos(r), Math.sin(r)]; };
const adiff = (a, b) => Math.abs(((a - b) % 360 + 540) % 360 - 180);

test('persona dial: bezel ticks, type flower turned to the collaboration centre, curve orbit, logo badges, hour ring', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'persona');
  const fp = page.locator('#main svg.fp2');
  const ticks = await fp.locator('.fp-tk').evaluateAll((els) => els.reduce((n, el) => n + (el.getAttribute('d').match(/M/g) || []).length, 0));
  expect(ticks, '120 bezel ticks (every 3°)').toBe(120);
  // the core is the persona's flower: petal count, back whorl and helm ring follow the letters
  const fl = await page.evaluate(() => { const f = $('#main svg.fp2 .fp-flower'); const n = (sel) => { const el = f.querySelector(sel); return el ? (el.getAttribute('d').match(/M/g) || []).length : 0; }; return { code: f.dataset.code, want: CUR.persona.code, front: n('.fp-pet') + n('.fp-lead'), lead: n('.fp-lead'), back: n('.fp-back path'), helm: f.querySelectorAll('.fp-heart circle').length }; });
  expect(fl.code).toBe(fl.want);
  expect(fl.lead).toBe(1);
  expect(fl.front).toBe(fl.code[2] === 'M' ? 12 : 5);
  expect(fl.back).toBe(fl.code[3] === 'V' ? fl.front : 0);
  expect(fl.helm).toBe(fl.code[0] === 'S' ? 3 : 2);
  // 16 types → 16 different flowers (petal count × swirl × length / heart × back whorl)
  const shapes = await page.evaluate(() => Object.keys(TYPES).map((k) => { const g = bloom(typeP(k), 200, 82); return [g.n, g.hr.toFixed(1), g.minor ? 1 : 0, g.lead].join('|'); }));
  expect(new Set(shapes).size).toBe(16);
  const want = await meanDeg(page, 'personaScope([PERIODS[S.persona.period][0], PERIODS[S.persona.period][1]])');
  const n = await needle(page, '#main');
  expect(Math.abs(n.hd - want)).toBeLessThan(0.1);
  expect(n.data).toBe(n.hd);
  expect(n.title).toMatch(/^协作重心 \d{1,2}:\d{2}$/);
  // the rendered transform is rotate(--hd) around the dial centre
  const m = await page.evaluate(() => getComputedStyle(document.querySelector('#main svg.fp2 .fp-bloom')).transform);
  const [c, s] = rot(n.hd); const v = m.match(/matrix\(([^)]+)\)/)[1].split(',').map(Number);
  expect(Math.abs(v[0] - c) + Math.abs(v[1] - s)).toBeLessThan(0.01);
  await expect(page.locator('#main .pe-fp-legend')).toHaveCount(0);
  await expect(page.locator('#main .pe-line .aib')).toHaveCount(0);
  // hour ring: 24 segments, clicking one expands its session dots, again collapses
  await expect(fp.locator('.fps')).toHaveCount(24);
  const h = await page.evaluate(() => CUR.fp.byH.findIndex((x) => x.length > 0));
  await page.locator('#main svg.fp2 .fps[data-h="' + h + '"]').dispatchEvent('click');
  await expect.poll(() => page.locator('#main svg.fp2 .fpd').count()).toBeGreaterThan(0);
  await expect(page.locator('#main svg.fp2 .fps.dim')).toHaveCount(23);
  await page.locator('#main svg.fp2 .fps[data-h="' + h + '"]').dispatchEvent('click');
  await expect(page.locator('#main svg.fp2 .fpd')).toHaveCount(0);
  // orbit: one smooth layer per Agent with sessions, in AG order, 181 samples (every 2°) on each edge, each with its contour line
  const layers = await fp.locator('.fp-orb .fpo').evaluateAll((els) => els.map((el) => [el.dataset.a, (el.getAttribute('d').match(/L/g) || []).length]));
  expect(await fp.locator('.fp-orb .fpc').evaluateAll((els) => els.map((el) => el.dataset.a))).toEqual(layers.map((x) => x[0]));
  const withS = await page.evaluate(() => { const L = personaScope([PERIODS[S.persona.period][0], PERIODS[S.persona.period][1]]); return AG.filter((a) => L.some((s) => s.a === a.id)).map((a) => a.id); });
  expect(layers.map((x) => x[0])).toEqual(withS);
  expect(withS.length).toBe(5);
  for (const [, n] of layers) expect(n).toBe(181 * 2 - 1);
  expect(await fp.locator('.fp-orb').getAttribute('mask')).toMatch(/^url\(#fpm\d+\)$/);
  // badges: one per Agent with sessions, each with that Agent's logo; the rendered badge sits on that Agent's own circular mean
  // (independent, 1°) and no two badges overlap
  const pl = await page.evaluate(() => {
    const svg = document.querySelector('#main svg.fp2'), r = svg.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    return [...svg.querySelectorAll('.fp-pl')].map((g) => { const b = g.querySelector('.fp-pd circle').getBoundingClientRect(); return [g.dataset.a, (Math.atan2(b.left + b.width / 2 - cx, cy - (b.top + b.height / 2)) * 180 / Math.PI + 360) % 360, b.left + b.width / 2, b.top + b.height / 2, b.width, g.querySelector('.fp-pd svg path') ? g.querySelector('.fp-pd svg path').getAttribute('d') === AGLOGO[g.dataset.a][1] : false]; });
  });
  expect(pl.map((x) => x[0])).toEqual(withS);
  expect(pl.every((x) => x[5]), 'every badge carries its Agent logo').toBe(true);
  for (let i = 0; i < pl.length; i++) for (let j = i + 1; j < pl.length; j++) expect(Math.hypot(pl[i][2] - pl[j][2], pl[i][3] - pl[j][3]), pl[i][0] + ' vs ' + pl[j][0]).toBeGreaterThanOrEqual(pl[i][4] - 0.5);
  for (const [a, deg] of pl) expect(adiff(deg, await meanDeg(page, 'personaScope([PERIODS[S.persona.period][0], PERIODS[S.persona.period][1]]).filter((s) => s.a === "' + a + '")')), a).toBeLessThan(1);
  await page.locator('#main svg.fp2 .fp-pl').last().dispatchEvent('mouseover');
  // the flower is drawn last, over the core disk; the lead petal is the topmost petal
  const kids = await page.evaluate(() => [...$('#main svg.fp2').children].map((e) => e.getAttribute('class')));
  expect(kids.indexOf('fp-core')).toBeLessThan(kids.indexOf('fp-flower')); expect(kids[kids.length - 1]).toBe('fp-flower');
  // --orbit is used only by the lead petal, the 00 reference triangle and the Orbit mark (plus the legend's lead swatch)
  for (const theme of ['light', 'dark']) {
    const bad = await page.evaluate((t) => {
      setTheme(t);
      const want = getComputedStyle(document.documentElement).getPropertyValue('--orbit').trim();
      const probe = document.createElement('i'); probe.style.color = want; document.body.appendChild(probe); const rgb = getComputedStyle(probe).color; probe.remove();
      const ok = (el) => el.matches('.fp-lead, .fp-n0') || !!el.closest('.orbit-mark');
      const hits = [...document.querySelectorAll('#desk *')].filter((el) => { const c = getComputedStyle(el); return [c.fill, c.stroke, c.backgroundColor, el.closest('svg') ? '' : c.color].includes(rgb); });
      return { rgb, needle: hits.some((el) => el.matches('#main .fp-lead')), tri: hits.some((el) => el.matches('#main .fp-n0')), bad: hits.filter((el) => !ok(el)).map((el) => el.tagName + '.' + el.getAttribute('class')) };
    }, theme);
    expect(bad.rgb, theme).toBe(theme === 'light' ? 'rgb(95, 107, 111)' : 'rgb(163, 173, 176)');
    expect([bad.needle, bad.tri, bad.bad], theme).toEqual([true, true, []]);
  }
  await page.evaluate(() => setTheme('system'));
  expect(errors).toEqual([]);
});

test('entering persona / l-persona sways the flower once; re-renders and hour clicks do not', async ({ page }) => {
  const errors = await openDemo(page);
  await page.evaluate(() => go('overview'));
  await page.evaluate(() => go('persona'));
  expect((await needle(page, '#main')).anims, 'damped wobble on entry').toBe(1);
  const kf = await page.evaluate(() => document.querySelector('#main svg.fp2 .fp-bd').getAnimations()[0].effect.getKeyframes().map((k) => k.transform));
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
  expect((await needle(page, '#main')).anims, 'plain re-render keeps the flower still').toBe(0);
  expect(await orbIn('#main'), 'plain re-render keeps the orbit still').toEqual({ sweep: [], pl: o.pl.map((x) => [0, null, null, x[3]]) });
  // Lite persona gets the same dial and the same entrance
  await page.evaluate(() => { S.ed = 'lite'; $('#win').dataset.ed = 'lite'; go('l-home'); });
  await page.evaluate(() => go('l-persona'));
  await expect(page.locator('#content [data-hero="fp"] svg.fp2 .fp-bloom')).toHaveCount(1);
  expect((await needle(page, '#content [data-hero="fp"]')).anims).toBe(1);
  const lo = await orbIn('#content [data-hero="fp"]');
  expect(lo.sweep.length).toBe(1); expect(lo.pl.every((x) => x[0] === 1200)).toBe(true);
  expect(errors).toEqual([]);
});

test('genesis: the bud spins, blooms, settles on the collaboration centre, and lands matching the persona page', async ({ page }) => {
  test.skip(!['mac-14', 'compact'].includes(test.info().project.name), 'genesis runs at mac-14 and compact');
  test.setTimeout(40_000);
  const errors = await openDemo(page);
  await page.evaluate(() => { go('overview'); openOnboarding(0); ACT.obNext(); });
  await page.locator('#overlay [data-act="obStart"]').click();
  // 01 opens on the Orbit motif: the dial is seen tilted (rotateX) and flattens; the closed bud (petals at FPG.BUD) is turned
  // frame by frame (inline transform) — held on 00 while the mark's inner arc folds into its lead petal, then spinning
  expect(await page.evaluate(() => $('#genBox .g-fp').style.transform)).toMatch(/rotateX\((?!0\.00deg)/);
  await expect(page.locator('#genBox .g-arc')).toHaveCount(1);
  const angles = new Set();
  expect(await page.evaluate(() => $('#genBox .fp-front').style.transform)).toBe('scale(0.34)');
  for (let i = 0; i < 12; i++) { angles.add(await page.evaluate(() => $('#genBox .fp-bloom').style.transform)); await page.waitForTimeout(120); }
  expect([...angles].filter(Boolean).length).toBeGreaterThanOrEqual(4);
  await expect.poll(() => page.evaluate(() => $('#genBox .g-fp').style.transform), { timeout: 4000 }).toBe('');
  // the planned curve is continuous through 01 → 02 (lands on 00 exactly when the sweep starts) and ends on --hd
  const c = await page.evaluate(() => { const g = GNS; const P = g.T.place; return { a: genNeedle(g, P - 1) % 360, b: genNeedle(g, P), end: genNeedle(g, g.T.end), hd: g.hd }; });
  expect(c.b).toBe(0); expect(360 - c.a).toBeLessThan(1);
  expect(Math.abs(((c.end - c.hd) % 360 + 540) % 360 - 180)).toBeLessThan(0.05);
  await expect.poll(() => page.evaluate(() => OB.step), { timeout: 9000 }).toBe(3);
  const g = await needle(page, '#genBox');
  expect(g.inline, 'final state hands the flower back to --hd').toBe('');
  expect(g.closed, 'and leaves it fully open').toBe(0);
  // the band has been swept open and the planets have settled back on their --pa
  expect(await page.evaluate(() => [$('#genBox .fp-sweep').style.strokeDashoffset, $$('#genBox .fp-pl').every((el) => !el.style.transform && !el.style.opacity)])).toEqual(['', true]);
  expect(Math.abs(g.hd - await meanDeg(page, 'obSel()'))).toBeLessThan(0.1);
  await page.locator('#overlay [data-act="obDone"]').click();
  await expect(page.locator('#overlay')).toBeHidden({ timeout: 2000 });
  const p = await needle(page, '#main');
  // the landing page uses the persona scope (which can differ from obSel by a session); the angle must not visibly jump
  expect(Math.abs(p.hd - g.hd)).toBeLessThan(1);
  expect(p.anims, 'no sway when the dial flies in').toBe(0);
  expect(errors).toEqual([]);
});

test('reduced motion: flower still on entry and genesis opens with the flower open on --hd', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openDemo(page);
  await page.evaluate(() => go('overview'));
  await page.evaluate(() => go('persona'));
  expect((await needle(page, '#main')).anims).toBe(0);
  await page.locator('#main svg.fp2').hover();
  expect(await page.evaluate(() => getComputedStyle(document.querySelector('#main svg.fp2 .fp-bd')).animationName)).toBe('none');
  await page.evaluate(() => openReveal());
  await expect(page.locator('#revBox')).toHaveClass(/skip/);
  expect(await page.evaluate(() => [$('#main .fp-sweep').getAnimations().length, $$('#main .fp-pl').filter((g) => g.getAnimations().length).length])).toEqual([0, 0]);
  const r = await needle(page, '#revBox');
  expect(r.inline).toBe(''); expect(r.anims).toBe(0); expect(r.closed).toBe(0);
  expect(await page.evaluate(() => [GNS.done, !!$('#overlay canvas')])).toEqual([true, false]);
  expect(errors).toEqual([]);
});

test('brand: no visible "Tandem" in the title, pages, settings, onboarding or menus', async ({ page }) => {  // orbit-rename: keep
  test.skip(!['mac-14', 'compact'].includes(test.info().project.name), 'text sweep runs at mac-14 and compact');
  test.setTimeout(60_000);
  const errors = await openDemo(page);
  expect(await page.title()).toMatch(/^Orbit/);
  const seen = (where) => page.evaluate((w) => { const t = document.title + '\n' + document.body.innerText; return t.includes('Tandem') ? w + ': ' + t.split('\n').filter((l) => l.includes('Tandem')).join(' | ') : null; }, where);  // orbit-rename: keep
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
  expect(await page.evaluate(() => reportMD().includes('Tandem'))).toBe(false);  // orbit-rename: keep
  expect(hits.filter(Boolean)).toEqual([]);
  expect(errors).toEqual([]);
});

// The App icon and the menu-bar item are the official Orbit logo (docs/design/logo/orbit-*.svg, via tools/brand-icon.mjs):
// one path at every size (the 1024 icon scaled as a whole, no heavier small rendition); the tile uses the logo's 22.5% corner; the page has
// the icon as its favicon.
test('App icon and menu-bar item use the official Orbit logo vectors', async ({ page }) => {
  const errors = await openDemo(page);
  const r = await page.evaluate(() => ({
    big: appIcon(128).includes(ORBIT_PATH) && appIcon(64).includes(ORBIT_PATH), small: appIcon(32).includes(ORBIT_PATH) && typeof ORBIT_SMALL === 'undefined', glyph: GLYPH.includes(ORBIT_PATH) && GLYPH.includes('currentColor'),
    menubar: !!document.querySelector('#mbar .glyph .orbit-mark path'),
    radius: (() => { const s = document.createElement('span'); s.className = 'appicon'; s.style.width = '100px'; s.style.height = '100px'; document.body.appendChild(s); const v = parseFloat(getComputedStyle(s).borderTopLeftRadius); s.remove(); return v; })(),
    favicon: (document.querySelector('link[rel="icon"]') || {}).href || ''
  }));
  expect([r.big, r.small, r.glyph, r.menubar]).toEqual([true, true, true, true]);
  expect(r.radius).toBeCloseTo(22.46, 1);
  expect(r.favicon.startsWith('data:image/svg+xml,')).toBe(true);
  expect(errors).toEqual([]);
});

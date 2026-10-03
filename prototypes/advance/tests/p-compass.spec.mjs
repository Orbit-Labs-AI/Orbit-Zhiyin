// The Orbit dial — the collaboration fingerprint (fp2SVG, src/js/41-a2-persona.js) — with the 16 type flowers (bloom,
// src/js/35-visuals.js), the persona switch motion (src/js/38-bloom-motion.js) and the dial inside Genesis (src/js/56-onboarding.js).
//
// Test flow:
//  1 flowers      16 types → 16 different flowers, each rotationally symmetric: N = 3–6 identical ink petals (petal k is petal 0
//                 turned by k · 360°/N) and an optional ring of N soft-gray petals, also symmetric, half a step off. The letters
//                 read from the drawing: M 5–6 / F 3–4 petals, I twisted / P straight, D longer petals and a smaller heart than S,
//                 V a ring heart (ring + centre dot) / T a solid dot. Petal 0's axis is on 0° (straight: base and tip on 0°;
//                 twisted: base and tip on either side, centred on 0°). There is no lead petal
//  2 dial         persona (every size) and l-persona: a square box; hairline bezel + 128 ticks; the 16 type codes in reflected
//                 Gray-code order (computed here), upright at their sector centres ((i + 0.5) × 22.5°), so the right half is D, the
//                 left S, the top I and the bottom P; in --font-type, muted, the user's type in ink-1 bold, no compass words; a code
//                 shows exactly when it renders at ≥ 8 px, the user's always (all 16 on the persona page at every size; Lite's smaller
//                 dial keeps only yours in narrower windows); codes, the --orbit triangle, the badges and the curves never collide. The
//                 flower is the persona's (the same geometry as bloom(p)) turned to its sector centre, with the triangle on the
//                 same bearing. Every session lands in exactly one type; the 16 transparent type areas expand / collapse their
//                 session dots. The orbit: one curve per Agent (translucent fill + outline), each grown from the same baseline (not
//                 stacked) to its own session density on one shared height scale (Gaussian σ = 8° at 2.5° samples, height ∝
//                 density^0.9, the tallest point = FPG.RH; recomputed here from the session bearings), so the curves cross;
//                 larger Agents drawn first; nothing filled behind the ring. One badge per Agent with its logo, on one orbit outside
//                 the curves, at the circular mean of that Agent's session bearings (recomputed here; a collision nudges it ≤ 15°).
//                 --orbit appears only on the triangle and the Orbit mark
//  3 entry        entering persona / l-persona sways the flower once and opens it from the bud, sweeps the band open from 00 and
//                 runs every badge from 00 to its heading; re-renders do not
//  4 switch       the same type with other numbers only settles the flower (no fold) while the curves morph; another type folds
//                 the old flower (a ghost copy, turning) into its heart, then the new one blooms from the heart turning on to its
//                 type; the triangle turns, the emphasis moves to the new code, the curves morph from the old shapes, curves of
//                 Agents that left fade out, the badges glide; everything ends on the plain render; a plain re-render plays nothing
//  5 reduced sw.  reduced motion: the switch is instant — no ghost, fold, morph or glide, only a 160 ms cross-fade of the flower
//  6 genesis      the dial starts tilted and flattens; the closed bud (FPG.BUD) spins frame by frame through 01–02, blooms in 03
//                 (0.34 → ≥ 1, then handed back to CSS), settles on the sector centre, and the persona page it lands on points the
//                 same way without a sway
//  7 reduced      reduce motion: nothing moves on entry; Genesis and the reveal open on the final state with the flower open on --hd
//  8 brand        no visible "Tandem" left: window title and the text of every page, settings tab, onboarding step and menu  // orbit-rename: keep
//  9 icon         the App icon and the menu-bar item are the official Orbit logo vectors
import { test, expect } from '@playwright/test';
import { openDemo, go, settle } from './helpers.mjs';

// the 16 types around the dial: reflected Gray code, D I M V first, 22.5° each clockwise from 12 o'clock (independent of FP_TYPES)
const GRAY = Array.from({ length: 16 }, (_, i) => { const g = i ^ (i >> 1); return [['D', 'S'], ['I', 'P'], ['M', 'F'], ['V', 'T']].map((p, k) => p[(g >> (3 - k)) & 1]).join(''); });
// type i owns the sector i × 22.5° … (i + 1) × 22.5°; its flower petal, its triangle and its code sit on the sector centre
const typeDeg = (code) => (GRAY.indexOf(code) + 0.5) * 22.5;
const sdiff = (a, b) => ((a - b) % 360 + 540) % 360 - 180;   // signed a − b in (−180°, 180°]
const adiff = (a, b) => Math.abs(sdiff(a, b));
const brg = (p, c = 200) => (Math.atan2(p[0] - c, c - p[1]) * 180 / Math.PI + 360) % 360;   // bearing of a point, clockwise from 12 o'clock
const turn = (p, deg, c = 200) => { const r = deg * Math.PI / 180, x = p[0] - c, y = p[1] - c; return [c + x * Math.cos(r) - y * Math.sin(r), c + x * Math.sin(r) + y * Math.cos(r)]; };
const rot = (deg) => { const r = deg * Math.PI / 180; return [Math.cos(r), Math.sin(r)]; };
const rotOf = (tf) => { const m = /rotate\((-?[\d.]+)deg\)/.exec(tf || ''); return m ? +m[1] : null; };
const scaleOf = (tf) => { const m = /scale\(([\d.]+)\)/.exec(tf || ''); return m ? +m[1] : null; };
// an absolute M / L / C / Z path → subpaths: the command letters, every coordinate pair, and each segment's end point (M first)
function subpaths(d) {
  const out = []; let cur = null;
  for (const [, c, args] of d.matchAll(/([MLCZ])([^MLCZ]*)/g)) {
    if (c === 'Z') { cur.cmds += 'Z'; continue; }
    const n = (args.match(/-?\d*\.?\d+/g) || []).map(Number), pairs = [];
    for (let i = 0; i + 1 < n.length; i += 2) pairs.push([n[i], n[i + 1]]);
    if (c === 'M') { cur = { cmds: '', pts: [], ends: [] }; out.push(cur); }
    cur.cmds += c; cur.pts.push(...pairs); cur.ends.push(pairs[pairs.length - 1]);
  }
  return out;
}
// the largest distance between petal k and petal 0 turned by k · step (∞ when they are not drawn the same way)
const symErr = (sp, step) => Math.max(0, ...sp.map((s, k) => (s.cmds !== sp[0].cmds || s.pts.length !== sp[0].pts.length ? Infinity
  : Math.max(...s.pts.map((q, j) => { const r = turn(sp[0].pts[j], k * step); return Math.hypot(r[0] - q[0], r[1] - q[1]); })))));
// a petal's axis runs from its base (the first point) to the end of its midline (the middle segment end: the tip, or a heart's notch);
// bearings relative to 0°, and their midpoint
const axisOf = (s) => { const b = sdiff(brg(s.ends[0]), 0), t = sdiff(brg(s.ends[(s.ends.length - 1) / 2]), 0); return { b, t, mid: b + sdiff(t, b) / 2 }; };
const axisOn0 = (d) => subpaths(d).map(axisOf).reduce((x, y) => (Math.abs(y.mid) < Math.abs(x.mid) ? y : x));
function expectAxisOn0(ax, twisted, label) {
  if (!twisted) { expect(Math.abs(ax.b), label + ': straight petal, base on 0°').toBeLessThan(0.2); expect(Math.abs(ax.t), label + ': straight petal, tip on 0°').toBeLessThan(0.2); return; }
  expect(ax.b * ax.t, label + ': the twisted petal crosses 0°').toBeLessThan(0);
  expect(Math.abs(ax.t - ax.b), label + ': twisted').toBeGreaterThan(5);
  expect(Math.abs(ax.mid), label + ': centred on 0°').toBeLessThan(4);
}
const needle = (page, scope) => page.evaluate((sc) => { const n = document.querySelector(sc + ' svg.fp2 .fp-bloom'); return n ? { hd: parseFloat(getComputedStyle(n).getPropertyValue('--hd')), data: +n.dataset.hd, inline: n.style.transform, anims: n.querySelector('.fp-bd').getAnimations().length, closed: [...n.querySelectorAll('.fp-pw')].filter((el) => el.style.transform).length, title: n.querySelector('title').textContent } : null; }, scope);
// the curves recomputed from the session bearings: each Agent's own Gaussian density (σ = 8°) at the FP_N sample bearings, all Agents on
// one scale (the densest point anywhere = RH), height ∝ density^0.9
const SIG = 8, POW = 0.9;
const density = (as, th) => as.reduce((v, a) => { const x = sdiff(th, a); return v + Math.exp(-x * x / (2 * SIG * SIG)); }, 0);
const circMean = (as) => { let x = 0, y = 0; as.forEach((d) => { x += Math.sin(d * Math.PI / 180); y += Math.cos(d * Math.PI / 180); }); return (Math.atan2(x, y) * 180 / Math.PI + 360) % 360; };
const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const clearOf = (c, b) => Math.hypot(Math.max(b.x - c.x, 0, c.x - (b.x + b.w)), Math.max(b.y - c.y, 0, c.y - (b.y + b.h))) - c.r;   // > 0: circle clear of box

// everything one dial draws, in viewBox units (400 × 400, centre 200, 200), boxes measured from the rendered page
const dialFacts = (page, scope, lite) => page.evaluate(([sc, isLite]) => {
  // screen → viewBox through the dial's own CTM (the svg box itself may be larger than the drawing)
  const svg = document.querySelector(sc + ' svg.fp2'), M = svg.getScreenCTM(), inv = M.inverse(), k = M.a, cs = (el) => getComputedStyle(el);
  const at = (x, y) => new DOMPoint(x, y).matrixTransform(inv);
  const box = (el) => { const r = el.getBoundingClientRect(), a = at(r.left, r.top), b = at(r.right, r.bottom); return { x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y }; };
  const probe = (css) => { const i = document.createElement('i'); i.style.cssText = css; document.body.appendChild(i); const s = getComputedStyle(i), o = { color: s.color, font: s.fontFamily }; i.remove(); return o; };
  const p = isLite ? persona(personaScope()) : CUR.persona, g = bloom(p, 200, FPG.RR), fl = svg.querySelector('.fp-flower'), bl = fl.querySelector('.fp-bloom');
  const shapes = 'circle, path, rect, ellipse, polygon';
  const R = svg.getBoundingClientRect();
  return {
    size: [R.width, R.height],
    ticks: [...svg.querySelectorAll('.fp-tk')].reduce((n, el) => n + (el.getAttribute('d').match(/M/g) || []).length, 0),
    bezel: [...svg.querySelectorAll('.fp-base circle')].map((c) => [+c.getAttribute('r'), cs(c).fill]),
    words: [...svg.querySelectorAll('text')].map((t) => t.textContent).join(' '),
    codes: [...svg.querySelectorAll('.fp-hours text')].map((t) => { const m = t.getScreenCTM(), on = cs(t).display !== 'none'; return { c: t.textContent, t: +t.dataset.t, x: +t.getAttribute('x'), y: +t.getAttribute('y'), me: t.classList.contains('me'), tcode: t.classList.contains('tcode'), skew: Math.abs(m.b) + Math.abs(m.c), shown: on, px: +t.getAttribute('font-size') * k, fam: cs(t).fontFamily, fill: cs(t).fill, weight: +cs(t).fontWeight, box: on ? box(t) : null }; }),
    ink: probe('color:var(--ink-1)').color, muted: probe('color:var(--ink-3)').color, typeFont: probe('font-family:var(--font-type)').font,
    tri: box(svg.querySelector('.fp-n0')), triTf: svg.querySelector('.fp-n0').getAttribute('transform'),
    flower: { code: fl.dataset.code, want: p.code, pet: fl.querySelector('.fp-pet').getAttribute('d'), bk: fl.querySelector('.fp-bk') ? fl.querySelector('.fp-bk').getAttribute('d') : '', major: g.major, back: g.back, lead: fl.querySelectorAll('.fp-lead').length, heart: fl.querySelectorAll('.fp-heart circle').length, hd: parseFloat(cs(bl).getPropertyValue('--hd')), data: +bl.dataset.hd, m: cs(bl).transform, title: bl.querySelector('title').textContent, name: TYPES[p.code] ? TYPES[p.code][0] : null },
    orbit: {
      R0: FPG.R0, RH: FPG.RH, PR: FPG.PR, N: FP_N, mask: svg.querySelector('.fp-orb').getAttribute('mask'),
      fills: [...svg.querySelectorAll('.fp-orb .fpo')].map((el) => ({ a: el.dataset.a, d: el.getAttribute('d'), op: +cs(el).fillOpacity })),
      lines: [...svg.querySelectorAll('.fp-orb .fpc')].map((el) => ({ a: el.dataset.a, d: el.getAttribute('d'), stroke: cs(el).stroke, fill: cs(el).fill, w: parseFloat(cs(el).strokeWidth) })),
      extra: [...svg.querySelectorAll('.fp-orb *')].filter((el) => el.matches(shapes) && !el.matches('.fpo, .fpc')).length,
      sess: AG.map((a) => [a.id, CUR.fp.byT.flat().filter((s) => s.a === a.id).map((s) => CUR.fp.cls.by[s.id].a)])
    },
    cls: { n: CUR.fp.n, sum: CUR.fp.byT.reduce((a, x) => a + x.length, 0), ids: new Set(CUR.fp.byT.flat().map((s) => s.id)).size },
    // nothing filled behind the ring: besides the curves, the flower, the badges, session dots and the triangle, every shape is unfilled
    filled: [...svg.querySelectorAll(shapes)].filter((el) => { const s = cs(el); return s.fill !== 'none' && s.fill !== 'transparent' && s.fill !== 'rgba(0, 0, 0, 0)' && +s.fillOpacity > 0; })
      .filter((el) => !el.closest('.fp-flower, .fp-pls, .dots, .fp-orb, .fp-focus, defs') && !el.matches('.fp-n0, .fp-tk')).map((el) => el.tagName + '.' + el.getAttribute('class') + '.' + (el.parentNode.getAttribute('class') || '')),
    hit: [...svg.querySelectorAll('.fps path')].map((el) => el.getAttribute('fill')),
    empty: ['.fp-core', '.fp-band'].map((s) => svg.querySelector(s).childElementCount),
    bg: cs(svg).backgroundColor,
    badges: [...svg.querySelectorAll('.fp-pl')].map((el) => { const c = el.querySelector('.fp-pd circle'), b = box(c), lg = el.querySelector('.fp-pd svg path'); return { a: el.dataset.a, pa: +el.dataset.pa, mean: +el.dataset.mean, x: b.x + b.w / 2, y: b.y + b.h / 2, r: b.w / 2 + parseFloat(cs(c).strokeWidth) / 2, logo: !!lg && lg.getAttribute('d') === AGLOGO[el.dataset.a][1], tip: TIPS.fpp(el.dataset.a) }; })
  };
}, [scope, !!lite]);

function expectDial(f, label, all16) {
  // the dial's box is square (height follows the width, no blank band above / below the drawing)
  expect(Math.abs(f.size[0] - f.size[1]), label + ': square dial box ' + f.size.join(' × ')).toBeLessThan(0.5);
  // bezel: a hairline circle with 128 ticks
  expect(f.ticks, label + ': 128 bezel ticks (8 per type)').toBe(128);
  expect(f.bezel.some(([r, fill]) => r === 196 && fill === 'none'), label + ': hairline bezel').toBe(true);
  // the 16 type codes: Gray-code order, upright at the sector centres, no compass words
  expect(f.codes.map((x) => x.c), label).toEqual(GRAY);
  for (let i = 0; i < 16; i++) expect([...GRAY[i]].filter((c, k) => c !== GRAY[(i + 1) % 16][k]).length, 'neighbours differ by one letter').toBe(1);
  expect(f.words, label + ': no compass words').not.toMatch(/即兴|委托|规划|掌舵/);
  for (const [i, x] of f.codes.entries()) {
    expect(adiff(brg([x.x, x.y]), (i + 0.5) * 22.5), label + ' ' + x.c + ' at its sector centre').toBeLessThan(0.2);
    expect(x.c[0], label + ' ' + x.c + ': right half D, left half S').toBe(x.x > 200 ? 'D' : 'S');
    expect(x.c[1], label + ' ' + x.c + ': top half I, bottom half P').toBe(x.y < 200 ? 'I' : 'P');
    expect(x.skew, label + ' ' + x.c + ' upright').toBeLessThan(1e-6);
    expect([x.tcode, x.fam], label + ' ' + x.c + ' in --font-type').toEqual([true, f.typeFont]);
    // legibility: a code shows exactly when it renders at 8 px or more (the CSS thresholds round to 7.98 px); only the user's own
    // code always stays, so a small dial (Lite in a narrow window) still names your type
    if (!x.me) expect(x.shown, label + ' ' + x.c + ' (' + x.px.toFixed(2) + ' px) shown exactly when legible').toBe(x.px >= 7.95);
    if (x.shown) expect(Math.hypot(x.box.x + x.box.w / 2 - x.x, x.box.y + x.box.h / 2 - x.y), label + ' ' + x.c + ' centred on its anchor').toBeLessThan(1.5);
  }
  if (all16) expect(f.codes.filter((x) => x.shown).length, label + ': all 16 codes legible at ' + f.size[0].toFixed(0) + ' px').toBe(16);
  const me = f.codes.filter((x) => x.me);
  expect(me.map((x) => x.c), label + ': exactly the user type is emphasised').toEqual([f.flower.code]);
  expect([me[0].shown, me[0].fill, me[0].weight >= 700], label + ': the user type in ink-1 bold').toEqual([true, f.ink, true]);
  for (const x of f.codes.filter((y) => !y.me)) expect([x.fill, x.weight < 700], label + ' ' + x.c + ' muted').toEqual([f.muted, true]);
  // the flower: the persona's own geometry, no lead petal, a ring heart only for V, turned to the sector centre with the triangle
  const fl = f.flower, hd = typeDeg(fl.code);
  expect(fl.code, label).toBe(fl.want);
  expect([fl.pet, fl.bk], label + ': the dial draws bloom(p)').toEqual([fl.major, fl.back]);
  expect(fl.lead, label + ': no lead petal').toBe(0);
  expect(fl.heart, label + ': ring + dot for V, a dot for T').toBe(fl.code[3] === 'V' ? 2 : 1);
  expectAxisOn0(axisOn0(fl.pet), fl.code[1] === 'I', label + ' ' + fl.code);
  expect(Math.abs(fl.hd - hd), label + ': --hd is the sector centre').toBeLessThan(0.01);
  expect(fl.data).toBe(fl.hd);
  expect(fl.title).toBe('你的类型 ' + fl.code + ' ' + fl.name);
  const [c, s] = rot(hd), v = fl.m.match(/matrix\(([^)]+)\)/)[1].split(',').map(Number);
  expect(Math.abs(v[0] - c) + Math.abs(v[1] - s), label + ': the flower is rendered turned by --hd').toBeLessThan(0.01);
  expect(f.triTf, label).toBe('rotate(' + hd + ' 200 200)');
  expect(adiff(brg([f.tri.x + f.tri.w / 2, f.tri.y + f.tri.h / 2]), hd), label + ': the --orbit triangle on the same bearing').toBeLessThan(1);
  // every session lands in exactly one type
  expect([f.cls.sum, f.cls.ids], label).toEqual([f.cls.n, f.cls.n]);
  // the orbit: one curve per Agent with sessions, larger Agents first (ties in AG order), fill + outline, masked for the entry sweep
  const o = f.orbit, base = o.R0 + 1, withS = o.sess.filter(([, as]) => as.length);
  const order = withS.slice().sort((x, y) => y[1].length - x[1].length).map((x) => x[0]);
  expect(o.fills.map((x) => x.a), label + ': larger Agents drawn first').toEqual(order);
  expect(o.lines.map((x) => x.a), label).toEqual(order);
  expect(o.mask).toMatch(/^url\(#fpm\d+\)$/);
  expect(o.extra, label + ': only curves in the orbit').toBe(0);
  const dens = Object.fromEntries(withS.map(([a, as]) => [a, Array.from({ length: o.N }, (_, k) => density(as, k * 360 / o.N))]));
  const mx = Math.max(...Object.values(dens).flat()), H = {}, EDGE = {};
  for (const [i, fill] of o.fills.entries()) {
    const [outer, inner] = fill.d.replace(/Z$/, '').split('L'), out = subpaths(outer)[0].ends, inn = subpaths('M' + inner)[0].ends;
    expect([out.length, inn.length], label + ' ' + fill.a + ': one point every 360°/FP_N').toEqual([o.N + 1, o.N + 1]);
    // not stacked: every curve is closed along the common baseline
    expect(Math.max(...inn.map((q) => Math.abs(Math.hypot(q[0] - 200, q[1] - 200) - base))), label + ' ' + fill.a + ' grows from the baseline').toBeLessThan(0.1);
    expect(o.lines[i].d, label + ' ' + fill.a + ': the outline is the curve').toBe(outer + 'Z');
    H[fill.a] = out.slice(0, o.N).map((q) => Math.hypot(q[0] - 200, q[1] - 200) - base); EDGE[fill.a] = out;
    const err = Math.max(...H[fill.a].map((h, k) => Math.abs(h - o.RH * Math.pow(dens[fill.a][k] / mx, POW))));
    expect(err, label + ' ' + fill.a + ': height = its own session density on the shared scale').toBeLessThan(0.12);
    expect(Math.max(...out.slice(0, o.N).map((q, k) => (H[fill.a][k] > 0.5 ? adiff(brg(q), k * 360 / o.N) : 0))), label + ' ' + fill.a + ' sample bearings').toBeLessThan(0.1);
    expect(fill.op > 0 && fill.op < 1, label + ' ' + fill.a + ': translucent fill').toBe(true);
    expect([o.lines[i].fill, o.lines[i].stroke !== 'none', o.lines[i].w > 0.5], label + ' ' + fill.a + ': crisp outline').toEqual(['none', true, true]);
  }
  const top = Math.max(...Object.values(H).flat());
  expect(Math.abs(top - o.RH), label + ': the densest point reaches FPG.RH').toBeLessThan(0.1);
  // independent curves cross each other (stacked bands never do)
  const ids = Object.keys(H); let crossings = 0;
  for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) { const d = H[ids[i]].map((h, k) => h - H[ids[j]][k]); if (Math.max(...d) > 1 && Math.min(...d) < -1) crossings++; }
  expect(crossings, label + ': curves overlap').toBeGreaterThan(0);
  // nothing filled behind the ring; the type areas are transparent; the face is the page
  expect([f.filled, f.empty, f.bg], label).toEqual([[], [0, 0], 'rgba(0, 0, 0, 0)']);
  expect(f.hit.length).toBe(16); expect(f.hit.every((x) => x === 'transparent')).toBe(true);
  // badges: one per Agent with sessions (AG order) carrying its logo, on one orbit outside the curves, at the circular mean of its
  // session bearings, nudged by at most 15° where it would collide
  expect(f.badges.map((b) => b.a), label).toEqual(withS.map((x) => x[0]));
  for (const b of f.badges) {
    expect(b.logo, label + ' ' + b.a + ' carries its logo').toBe(true);
    expect(adiff(b.mean, circMean(withS.find((x) => x[0] === b.a)[1])), label + ' ' + b.a + ' mean').toBeLessThan(0.15);
    expect(adiff(brg([b.x, b.y]), b.pa), label + ' ' + b.a + ' drawn at data-pa').toBeLessThan(0.6);
    expect(adiff(b.pa, b.mean), label + ' ' + b.a + ' nudge').toBeLessThanOrEqual(15);
    expect(Math.abs(Math.hypot(b.x - 200, b.y - 200) - o.PR), label + ' ' + b.a + ' on the badge orbit').toBeLessThan(0.6);
    expect(o.PR - b.r, label + ' ' + b.a + ' outside the curves').toBeGreaterThan(base + top);
    expect(b.tip, label + ' ' + b.a + ' tooltip').toContain('平均偏向 ' + GRAY[Math.floor(b.mean / 22.5) % 16]);
    expect(clearOf(b, f.tri), label + ' ' + b.a + ' clear of the triangle').toBeGreaterThan(0);
  }
  for (let i = 0; i < f.badges.length; i++) for (let j = i + 1; j < f.badges.length; j++) {
    const a = f.badges[i], b = f.badges[j];
    expect(Math.hypot(a.x - b.x, a.y - b.y) - a.r - b.r, label + ': ' + a.a + ' vs ' + b.a).toBeGreaterThan(0);
  }
  // the shown codes collide with nothing: each other, the triangle, the badges, the curves (every curve edge, sampled 4× between its points)
  const shown = f.codes.filter((x) => x.shown);
  const edge = Object.values(EDGE).flatMap((pts) => pts.slice(0, -1).flatMap((q, i) => [0, 0.25, 0.5, 0.75].map((t) => [q[0] + (pts[i + 1][0] - q[0]) * t, q[1] + (pts[i + 1][1] - q[1]) * t])));
  const inside = (q, b) => q[0] > b.x && q[0] < b.x + b.w && q[1] > b.y && q[1] < b.y + b.h;
  for (const [i, x] of shown.entries()) {
    for (const y of shown.slice(i + 1)) expect(overlap(x.box, y.box), label + ': ' + x.c + ' vs ' + y.c).toBe(false);
    expect(overlap(x.box, f.tri), label + ': ' + x.c + ' vs the triangle').toBe(false);
    for (const b of f.badges) expect(clearOf(b, x.box), label + ': ' + x.c + ' vs badge ' + b.a).toBeGreaterThan(0);
    expect(edge.filter((q) => inside(q, x.box)).length, label + ': ' + x.c + ' clear of the curves').toBe(0);
  }
}

test('16 type flowers: distinct, rotationally symmetric, letters readable from the drawing, one petal axis on 0°', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'pure geometry, runs once');
  const errors = await openDemo(page);
  // drawn at radius 8000 around (200, 200) so the 0.1 rounding of the path numbers is far below the angles measured here
  const F = await page.evaluate(() => Object.keys(TYPES).map((code) => { const g = bloom(typeP(code), 200, 8000); return { code, n: g.n, major: g.major, back: g.back, lead: g.lead, hr: g.hr, heart: bloomHeart(g, 200, 200, 'ink', 'bg', 1.4) }; }));
  expect(F.map((f) => f.code).sort()).toEqual([...GRAY].sort());
  expect(new Set(F.map((f) => f.major + '|' + f.back + '|' + f.heart)).size, '16 different flowers').toBe(16);
  const reach = {};
  for (const f of F) {
    const maj = subpaths(f.major), back = f.back ? subpaths(f.back) : [], step = 360 / f.n;
    expect(f.lead, f.code + ': no lead petal').toBe('');
    expect(maj.length, f.code + ': N ink petals').toBe(f.n);
    expect(f.n, f.code + ': M 5–6 petals, F 3–4').toBeGreaterThanOrEqual(f.code[2] === 'M' ? 5 : 3);
    expect(f.n, f.code + ': M 5–6 petals, F 3–4').toBeLessThanOrEqual(f.code[2] === 'M' ? 6 : 4);
    expect(symErr(maj, step), f.code + ': the ink petals repeat every 360°/N').toBeLessThan(0.16);
    if (back.length) {
      expect(back.length, f.code + ': the soft ring has N petals too').toBe(f.n);
      expect(symErr(back, step), f.code + ': the soft petals repeat every 360°/N').toBeLessThan(0.16);
      expect(adiff(brg(back[0].ends[0]) - brg(maj[0].ends[0]), step / 2), f.code + ': the soft ring sits half a step off').toBeLessThan(0.3);
    }
    expectAxisOn0(axisOn0(f.major), f.code[1] === 'I', f.code);
    // hearts: V a ring (paper fill, ink stroke) around a centre dot, T one solid dot
    const circles = [...f.heart.matchAll(/<circle [^>]*>/g)].map((m) => m[0]);
    if (f.code[3] === 'V') { expect(circles.length, f.code).toBe(2); expect(circles[0]).toMatch(/fill="bg" stroke="ink"/); expect(circles[1]).toMatch(/fill="ink"/); }
    else { expect(circles.length, f.code).toBe(1); expect(circles[0]).toMatch(/fill="ink"/); }
    reach[f.code] = { r: Math.max(...maj.flatMap((s) => s.ends.map((q) => Math.hypot(q[0] - 200, q[1] - 200)))), hr: f.hr };
  }
  // D (delegate) has longer petals and a smaller heart than the S (steer) flower with the same other three letters
  for (const c of GRAY.filter((x) => x[0] === 'D')) {
    const s = 'S' + c.slice(1);
    expect(reach[c].r, c + ' petals longer than ' + s).toBeGreaterThan(reach[s].r);
    expect(reach[c].hr, c + ' heart smaller than ' + s).toBeLessThan(reach[s].hr);
  }
  expect(errors).toEqual([]);
});

test('persona dial: 16 type codes on the bezel, the type flower on its sector, independent Agent curves, logo badges', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'persona');
  expectDial(await dialFacts(page, '#main'), 'persona', true);            // the persona page dial is large enough for all 16 codes at every size
  // the 16 transparent type areas: clicking one expands its session dots and dims the rest, again collapses
  const fp = page.locator('#main svg.fp2');
  await expect(fp.locator('.fps')).toHaveCount(16);
  const h = await page.evaluate(() => CUR.fp.byT.findIndex((x) => x.length > 0));
  await page.locator('#main svg.fp2 .fps[data-t="' + h + '"]').dispatchEvent('click');
  await expect.poll(() => page.locator('#main svg.fp2 .fpd').count()).toBe(await page.evaluate((t) => CUR.fp.byT[t].length, h));
  await expect(page.locator('#main svg.fp2 .fps.dim')).toHaveCount(15);
  await page.locator('#main svg.fp2 .fps[data-t="' + h + '"]').dispatchEvent('click');
  await expect(page.locator('#main svg.fp2 .fpd')).toHaveCount(0);
  await expect(page.locator('#main .pe-fp-legend')).toHaveCount(0);
  // the flower is drawn last
  const kids = await page.evaluate(() => [...$('#main svg.fp2').children].map((e) => e.getAttribute('class')));
  expect(kids.indexOf('fp-core')).toBeLessThan(kids.indexOf('fp-flower')); expect(kids[kids.length - 1]).toBe('fp-flower');
  // --orbit is used only by the type triangle and the Orbit mark
  for (const theme of ['light', 'dark']) {
    const bad = await page.evaluate((t) => {
      setTheme(t);
      const want = getComputedStyle(document.documentElement).getPropertyValue('--orbit').trim();
      const probe = document.createElement('i'); probe.style.color = want; document.body.appendChild(probe); const rgb = getComputedStyle(probe).color; probe.remove();
      const ok = (el) => el.matches('.fp-n0') || !!el.closest('.orbit-mark');
      const hits = [...document.querySelectorAll('#desk *')].filter((el) => { const c = getComputedStyle(el); return [c.fill, c.stroke, c.backgroundColor, el.closest('svg') ? '' : c.color].includes(rgb); });
      return { rgb, tri: hits.some((el) => el.matches('#main .fp-n0')), bad: hits.filter((el) => !ok(el)).map((el) => el.tagName + '.' + el.getAttribute('class')) };
    }, theme);
    expect(bad.rgb, theme).toBe(theme === 'light' ? 'rgb(95, 107, 111)' : 'rgb(163, 173, 176)');
    expect([bad.tri, bad.bad], theme).toEqual([true, []]);
  }
  await page.evaluate(() => setTheme('system'));
  // Lite draws the same dial at 300 (larger codes)
  await page.evaluate(() => { S.ed = 'lite'; $('#win').dataset.ed = 'lite'; go('l-home'); });
  await go(page, 'l-persona');
  expectDial(await dialFacts(page, '#content [data-hero="fp"]', true), 'l-persona');
  expect(errors).toEqual([]);
});

test('entering persona / l-persona sways the flower once and opens it from the bud; re-renders do not', async ({ page }) => {
  const errors = await openDemo(page);
  await page.evaluate(() => go('overview'));
  await page.evaluate(() => go('persona'));
  expect((await needle(page, '#main')).anims, 'damped wobble on entry').toBe(1);
  const kf = await page.evaluate(() => document.querySelector('#main svg.fp2 .fp-bd').getAnimations()[0].effect.getKeyframes().map((k) => k.transform));
  expect(kf[0]).toBe('rotate(-40deg)'); expect(kf[kf.length - 1]).toBe('rotate(0deg)');
  // under the sway the petals open from the Genesis bud (FPG.BUD) to full size
  const bud = await page.evaluate(() => ['.fp-front', '.fp-back'].map((s) => { const el = document.querySelector('#main svg.fp2 ' + s); return el ? el.getAnimations().map((a) => a.effect.getKeyframes().map((k) => k.transform)) : null; }));
  expect(bud[0].length).toBe(1);
  expect(scaleOf(bud[0][0][0]), 'opens from the bud').toBe(0.34); expect(bud[0][0][bud[0][0].length - 1]).toBe('rotate(0deg) scale(1)');
  if (bud[1]) expect(scaleOf(bud[1][0][0])).toBe(0.34);
  // the band sweeps open from 00 and every badge runs from 00 to its own heading
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
  expect(await page.evaluate(() => $('#main svg.fp2').getAnimations({ subtree: true }).length), 'nothing else moves either').toBe(0);
  // Lite persona gets the same dial and the same entrance
  await page.evaluate(() => { S.ed = 'lite'; $('#win').dataset.ed = 'lite'; go('l-home'); });
  await page.evaluate(() => go('l-persona'));
  await expect(page.locator('#content [data-hero="fp"] svg.fp2 .fp-bloom')).toHaveCount(1);
  expect((await needle(page, '#content [data-hero="fp"]')).anims).toBe(1);
  const lo = await orbIn('#content [data-hero="fp"]');
  expect(lo.sweep.length).toBe(1); expect(lo.pl.every((x) => x[0] === 1200)).toBe(true);
  expect(errors).toEqual([]);
});

// window.__anims(el): every animation on one element — duration, delay and the keyframes that matter here
const installAnims = (page) => page.evaluate(() => {
  window.__anims = (el) => (el ? el.getAnimations().map((a) => { const t = a.effect.getTiming(); return { dur: t.duration, delay: t.delay, kf: a.effect.getKeyframes().map((k) => ({ tf: k.transform || null, op: k.opacity == null ? null : +k.opacity, fill: k.fill || null, fw: k.fontWeight == null ? null : String(k.fontWeight) })) }; }) : null);
});
const dialState = (page) => page.evaluate(() => {
  const svg = $('#main svg.fp2');
  return { code: svg.querySelector('.fp-flower').dataset.code, hd: +svg.querySelector('.fp-bloom').dataset.hd, me: svg.querySelector('.fp-code.me').textContent, tri: svg.querySelector('.fp-n0').getAttribute('transform'),
    curves: Object.fromEntries([...svg.querySelectorAll('.fp-orb path[data-a]')].map((p) => [p.getAttribute('class') + ':' + p.dataset.a, p.getAttribute('d')])),
    pa: Object.fromEntries([...svg.querySelectorAll('.fp-pl')].map((g) => [g.dataset.a, +g.dataset.pa])), ghosts: svg.querySelectorAll('.bm-ghost, [data-bm]').length,
    inline: [...svg.querySelectorAll('.fp-pw, .fp-bloom')].filter((el) => el.style.transform).length };
});

test('persona switch: the same type settles; another type folds the old flower into its heart and blooms the new one', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'motion runs once, at the default size');
  const errors = await openDemo(page);
  await go(page, 'persona');                           // 9 月 → DIMV; go() waits for the entry to finish
  const a = await dialState(page);
  expect(a.code).toBe('DIMV');
  // 近 90 天 is also DIMV with other numbers: no fold, the petals settle once while the curves morph from the old shapes
  await installAnims(page);
  const same = await page.evaluate(() => {
    document.querySelector('#main [data-act="period"][data-v="90"]').click();
    const A = window.__anims, svg = $('#main svg.fp2');
    return { code: svg.querySelector('.fp-flower').dataset.code, ghosts: svg.querySelectorAll('.bm-ghost').length, pw: [...svg.querySelectorAll('.fp-flower .fp-pw')].map(A), tri: A(svg.querySelector('.fp-n0')).length, cc: svg.querySelector('.fpc[data-a="cc"]').getAttribute('d') };
  });
  expect([same.code, same.ghosts, same.tri]).toEqual(['DIMV', 0, 0]);
  for (const x of same.pw) { expect(x.length, 'one settle per petal ring').toBe(1); expect(x[0].dur).toBe(560); expect(scaleOf(x[0].kf[0].tf)).toBe(0.95); expect(x[0].kf[x[0].kf.length - 1].tf).toBe('none'); }
  expect(same.cc, 'the morph starts from the old curve').toBe(a.curves['fpc:cc']);
  await settle(page);
  const b = await dialState(page);
  expect(b.curves['fpc:cc'], 'and ends on the new one').not.toBe(a.curves['fpc:cc']);
  // Kimi alone (uiview-persona-v1 demo units) is SPFV — D → S and a type with a soft ring: the old flower folds into its heart,
  // the new one blooms from the heart toward its type
  const d = sdiff(typeDeg('SPFV'), typeDeg('DIMV'));
  const sw = await page.evaluate(() => {
    S.agents = new Set(['km']); agentSync(); render();
    const A = window.__anims, svg = $('#main svg.fp2'), gh = svg.querySelector('.bm-ghost'), fl = svg.querySelector('.fp-flower');
    return {
      code: fl.dataset.code, hd: +fl.querySelector('.fp-bloom').dataset.hd,
      ghost: gh && { next: gh.nextElementSibling === fl, code: gh.querySelector('[data-code]').dataset.code, live: gh.querySelectorAll('[class*="fp-"]').length, front: A(gh.querySelector('.bm-front')), back: A(gh.querySelector('.bm-back')), bloom: A(gh.querySelector('.bm-bloom')) },
      front: A(fl.querySelector('.fp-front')), back: A(fl.querySelector('.fp-back')), bloom: A(fl.querySelector('.fp-bloom')), heart: A(fl.querySelector('.fp-heart')),
      tri: A(svg.querySelector('.fp-n0')), was: A(svg.querySelector('.fp-code[data-t="0"]')), now: A(svg.querySelector('.fp-code.me')), me: svg.querySelector('.fp-code.me').textContent,
      curves: Object.fromEntries([...svg.querySelectorAll('.fp-orb path[data-a]')].map((p) => [p.getAttribute('class') + ':' + p.dataset.a, p.getAttribute('d')])), gone: svg.querySelectorAll('.fp-orb [data-bm="gone"]').length,
      pl: [...svg.querySelectorAll('.fp-pl')].map((g) => ({ a: g.dataset.a, pa: +g.dataset.pa, an: A(g) }))
    };
  });
  expect([sw.code, sw.hd, sw.me]).toEqual(['SPFV', typeDeg('SPFV'), 'SPFV']);
  // 收起: a ghost of the old flower (renamed classes, kept right behind the new one) turns on toward the new type and folds into its heart
  expect(sw.ghost).toMatchObject({ next: true, code: 'DIMV', live: 0 });
  const fold = sw.ghost.front[0], last = (x) => x.kf[x.kf.length - 1];
  expect([sw.ghost.front.length, fold.delay, fold.dur]).toEqual([1, 0, 300]);
  expect(fold.kf[0].tf).toBe('rotate(0deg) scale(1)');
  expect([scaleOf(last(fold).tf), last(fold).op], 'folds into the heart').toEqual([0.06, 0]);
  expect(rotOf(last(fold).tf) * d, 'petals twist the way the flower turns').toBeGreaterThan(0);
  expect(sw.ghost.back[0].delay, 'the soft ring folds 50 ms behind').toBe(50);
  expect(rotOf(sw.ghost.bloom[0].kf[0].tf)).toBeCloseTo(typeDeg('DIMV'), 2);
  expect(rotOf(last(sw.ghost.bloom[0]).tf)).toBeCloseTo(typeDeg('DIMV') + 0.3 * d, 2);
  // 绽开: the new petals open from the heart once the fold is under way, overshoot a little and settle, while the flower turns the
  // rest of the way onto the new type; the soft ring trails
  const open = sw.front[0];
  expect(sw.front.length).toBe(1);
  expect(open.delay, 'the bloom starts after the fold').toBeGreaterThan(fold.delay);
  expect(open.delay + open.dur, 'and ends after it').toBeGreaterThan(fold.delay + fold.dur);
  expect([scaleOf(open.kf[0].tf), open.kf[0].op], 'opens from the heart').toEqual([0.06, 0]);
  expect(rotOf(open.kf[0].tf) * d, 'untwists the same way').toBeLessThan(0);
  expect(Math.max(...open.kf.map((k) => scaleOf(k.tf) || 0))).toBeGreaterThan(1);
  expect(last(open).tf).toBe('rotate(0deg) scale(1)');
  expect(sw.back[0].delay).toBeGreaterThan(open.delay);
  expect(rotOf(sw.bloom[0].kf[0].tf)).toBeCloseTo(typeDeg('SPFV') - 0.7 * d, 2);
  expect(rotOf(last(sw.bloom[0]).tf)).toBeCloseTo(typeDeg('SPFV'), 2);
  expect(sw.heart.length, 'D → S: the heart swaps at the fold point').toBe(1);
  // the triangle turns to the new type; the emphasis leaves the old code and lands on the new one
  expect([sw.tri.length, sw.tri[0].dur, rotOf(last(sw.tri[0]).tf)]).toEqual([1, 760, typeDeg('SPFV')]);
  expect([sw.was[0].kf[0].fill, last(sw.was[0]).fill]).toEqual(['var(--ink-1)', 'var(--ink-3)']);
  expect([sw.now[0].kf[0].fill, last(sw.now[0]).fill, last(sw.now[0]).fw]).toEqual(['var(--ink-3)', 'var(--ink-1)', '800']);
  expect(sw.now[0].delay).toBeGreaterThan(sw.was[0].delay);
  // curves of the Agents still there morph from their old shapes; the curves of Agents that left fade out; badges glide
  const kept = Object.keys(sw.curves);
  expect(kept.length).toBeGreaterThan(0);
  for (const k of kept) expect(sw.curves[k], k + ' starts from its old shape').toBe(b.curves[k]);
  expect(sw.gone, 'curves of the Agents that left fade out').toBe(Object.keys(b.curves).length - kept.length);
  expect(sw.gone).toBeGreaterThan(0);
  for (const p of sw.pl) {
    const from = b.pa[p.a];
    if (from == null || adiff(from, p.pa) < 0.3) continue;
    expect(p.an.length, p.a + ' glides').toBe(1);
    expect(rotOf(p.an[0].kf[0].tf), p.a + ' from its old bearing (shortest arc)').toBeCloseTo(p.pa - sdiff(p.pa, from), 1);
    expect(rotOf(last(p.an[0]).tf), p.a + ' to its new bearing').toBeCloseTo(p.pa, 1);
  }
  // it all ends exactly on the plain render of the new dial, and a plain re-render then plays nothing
  await expect.poll(() => page.evaluate(() => $$('#main svg.fp2 .bm-ghost, #main svg.fp2 [data-bm]').length), { timeout: 3000 }).toBe(0);
  await settle(page);
  const end = await dialState(page);
  expect(end.inline, 'no transform left on the petals').toBe(0);
  await page.evaluate(() => render());
  expect(await page.evaluate(() => $('#main svg.fp2').getAnimations({ subtree: true }).length), 'a plain re-render plays nothing').toBe(0);
  expect(await dialState(page)).toEqual(end);
  expect(await page.evaluate(() => { const t = $('#main svg.fp2 .fp-code.me'); return [getComputedStyle(t).fontWeight, getComputedStyle(t).fill]; })).toEqual(['800', await page.evaluate(() => { const i = document.createElement('i'); i.style.color = 'var(--ink-1)'; document.body.appendChild(i); const c = getComputedStyle(i).color; i.remove(); return c; })]);
  expect(errors).toEqual([]);
});

test('persona switch under reduced motion: no fold, morph or glide — only a 160 ms cross-fade of the new flower', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'motion runs once, at the default size');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openDemo(page);
  await go(page, 'persona');
  const r = await page.evaluate(() => {
    document.querySelector('#main .pe-evrow [data-act="period"][data-v="jun"]').click();
    const svg = $('#main svg.fp2');
    return { anims: svg.getAnimations({ subtree: true }).map((a) => ({ el: a.effect.target.getAttribute('class'), dur: a.effect.getTiming().duration, props: [...new Set(a.effect.getKeyframes().flatMap((k) => Object.keys(k).filter((x) => !['offset', 'computedOffset', 'easing', 'composite'].includes(x))))] })),
      code: svg.querySelector('.fp-flower').dataset.code };
  });
  expect(r.code).toBe('SIMV');
  expect(r.anims).toEqual([{ el: 'fp-flower', dur: 160, props: ['opacity'] }]);
  // everything is already at its new place: the same as a plain render of the new dial
  const now = await dialState(page);
  expect([now.ghosts, now.inline, now.me, now.tri]).toEqual([0, 0, 'SIMV', 'rotate(' + typeDeg('SIMV') + ' 200 200)']);
  await page.evaluate(() => render());
  expect(await dialState(page)).toEqual(now);
  expect(errors).toEqual([]);
});

test('genesis: the bud spins, blooms, settles on the sector centre, and lands matching the persona page', async ({ page }) => {
  test.skip(!['mac-14', 'compact'].includes(test.info().project.name), 'genesis runs at mac-14 and compact');
  test.setTimeout(40_000);
  const errors = await openDemo(page);
  await page.evaluate(() => { go('overview'); openOnboarding(0); ACT.obNext(); });
  await page.locator('#overlay [data-act="obStart"]').click();
  // 01 opens on the Orbit motif: the dial is seen tilted (rotateX) and flattens; the closed bud (petals at FPG.BUD) is turned frame by
  // frame (inline transform) — held on 00 while the mark's inner arc folds into the petal on 0°, then spinning
  expect(await page.evaluate(() => $('#genBox .g-fp').style.transform)).toMatch(/rotateX\((?!0\.00deg)/);
  await expect(page.locator('#genBox .g-arc')).toHaveCount(1);
  const angles = new Set(), samples = [];
  const sample = () => page.evaluate(() => ({ st: ($('#genBox .g-stage') || {}).textContent || '', bloom: $('#genBox .fp-bloom').style.transform, front: $('#genBox .fp-front').style.transform, step: OB.step }));
  expect((await sample()).front).toBe('scale(0.34)');
  for (let i = 0; i < 12; i++) { const s = await sample(); angles.add(s.bloom); samples.push(s); await page.waitForTimeout(120); }
  expect([...angles].filter(Boolean).length).toBeGreaterThanOrEqual(4);
  await expect.poll(() => page.evaluate(() => $('#genBox .g-fp').style.transform), { timeout: 4000 }).toBe('');
  // the planned curve is continuous through 01 → 02 (lands on 00 exactly when the sweep starts) and ends on --hd
  const c = await page.evaluate(() => { const g = GNS; const P = g.T.place; return { a: genNeedle(g, P - 1) % 360, b: genNeedle(g, P), end: genNeedle(g, g.T.end), hd: g.hd }; });
  expect(c.b).toBe(0); expect(360 - c.a).toBeLessThan(1);
  expect(adiff(c.end, c.hd)).toBeLessThan(0.05);
  await expect.poll(async () => { const s = await sample(); samples.push(s); return s.step; }, { timeout: 9000, intervals: [60] }).toBe(3);
  // bud → bloom: closed (0.34) through 01–02, opening in 03 (between bud and full, then past full with the overshoot), handed back
  // to CSS at the end
  const sc = samples.map((s) => [s.st.slice(0, 2), s.front === '' ? 1 : scaleOf(s.front)]);
  expect(sc.filter(([st]) => st === '01' || st === '02').every(([, v]) => v === 0.34), 'a closed bud through 01–02').toBe(true);
  expect(sc.some(([, v]) => v > 0.34 && v < 1), 'opening').toBe(true);
  expect(Math.max(...samples.map((s) => scaleOf(s.front) || 0)), 'a slight overshoot').toBeGreaterThan(1);
  const g = await needle(page, '#genBox');
  expect(g.inline, 'final state hands the flower back to --hd').toBe('');
  expect(g.closed, 'and leaves it fully open').toBe(0);
  // the band has been swept open and the badges have settled back on their --pa
  expect(await page.evaluate(() => [$('#genBox .fp-sweep').style.strokeDashoffset, $$('#genBox .fp-pl').every((el) => !el.style.transform && !el.style.opacity)])).toEqual(['', true]);
  expect(g.hd).toBe(typeDeg(await page.evaluate(() => GNS.p.code)));
  await page.locator('#overlay [data-act="obDone"]').click();
  await expect(page.locator('#overlay')).toBeHidden({ timeout: 2000 });
  const p = await needle(page, '#main');
  // the landing page points at the same type
  expect(p.hd).toBe(g.hd);
  expect(p.anims, 'no sway when the dial flies in').toBe(0);
  expect(errors).toEqual([]);
});

test('reduced motion: flower still on entry and genesis opens with the flower open on --hd', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openDemo(page);
  await page.evaluate(() => go('overview'));
  await page.evaluate(() => go('persona'));
  expect((await needle(page, '#main')).anims).toBe(0);
  expect(await page.evaluate(() => $('#main svg.fp2').getAnimations({ subtree: true }).length), 'nothing on the dial moves').toBe(0);
  await page.locator('#main svg.fp2').hover();
  expect(await page.evaluate(() => getComputedStyle(document.querySelector('#main svg.fp2 .fp-bd')).animationName)).toBe('none');
  await page.evaluate(() => openReveal());
  await expect(page.locator('#revBox')).toHaveClass(/skip/);
  expect(await page.evaluate(() => [$('#main .fp-sweep').getAnimations().length, $$('#main .fp-pl').filter((g) => g.getAnimations().length).length])).toEqual([0, 0]);
  const r = await needle(page, '#revBox');
  expect(r.inline).toBe(''); expect(r.anims).toBe(0); expect(r.closed).toBe(0);
  expect(r.hd).toBe(typeDeg(await page.evaluate(() => GNS.p.code)));
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

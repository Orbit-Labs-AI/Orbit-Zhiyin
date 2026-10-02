/* Tandem promo: a beat-locked timeline. Two live copies of the app take turns showing ONE component each (everything
   else in that copy is hidden), framed by a virtual camera next to the copy that explains it. Transitions overlap the
   outgoing and incoming component with long eases; there are no beat-synced shakes or flashes.
   Everything is a pure function of the master time t (seconds), so the page plays in real time with the soundtrack
   (preview) or frame by frame on Playwright's fake clock (render.mjs). Times are written in beats. */
'use strict';
const BPM = 124, BEAT = 60 / BPM, END = 120;              // beats; music.py uses the same grid
const RENDER = location.search.includes('render');
const DEBUG = location.search.includes('debug');
const $ = (s, r) => (r || document).querySelector(s);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, p) => a + (b - a) * p;
const E = {
  lin: (p) => p,
  out: (p) => 1 - Math.pow(1 - p, 3),
  quart: (p) => 1 - Math.pow(1 - p, 4),
  in: (p) => p * p * p,
  inOut: (p) => (p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
  sine: (p) => -(Math.cos(Math.PI * p) - 1) / 2,
  expo: (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p))
};
const stage = $('#stage'), fxEl = $('#fx'), glowEl = $('#glow');

/* ---------- the two app copies ("decks") and their cameras ---------- */
// x,y: the app point (frame px) put at screen point (ax, ay); s: zoom; rx/ry/rz: tilt around (ax, ay); z: dolly;
// o: opacity; bl: blur. Tweens start from wherever the deck's camera is when they fire.
const ZERO = { x: 800, y: 500, s: 1, ax: 960, ay: 540, rx: 0, ry: 0, rz: 0, z: 0, o: 0, bl: 0 };
const decks = [0, 1].map((i) => ({ i, frame: $('#app' + i), cam: $('#cam' + i), rig: $('#rig' + i), C: Object.assign({}, ZERO), W: null, D: null }));
// deck 2 is not an app copy: it holds the promo's own compass (800 × 800 at the rig origin)
decks.push({ i: 2, frame: null, cam: $('#cam2'), rig: $('#rig2'), C: Object.assign({}, ZERO), W: null, D: null, virtual: true });
const tweens = [];
const BOX = { C: [960, 560, 1560, 760], R: [1250, 540, 1060, 800], L: [670, 540, 1060, 800] };
function find(d, sel) {
  const D = decks[d].D; if (!D) return null;
  if (typeof sel === 'function') return sel(D);
  return D.querySelector(sel);
}
function rectOf(d, sel) {
  if (decks[d].virtual) return { x: 0, y: 0, w: 800, h: 800 };
  const list = (Array.isArray(sel) ? sel : [sel]).map((s) => find(d, s)).filter(Boolean);
  if (!list.length) { console.warn('promo: no target', String(sel)); return { x: 600, y: 400, w: 400, h: 200 }; }
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  for (const el of list) { const r = el.getBoundingClientRect(); x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top); x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom); }
  if (DEBUG) console.warn('rect', d, String(sel).slice(0, 40), Math.round(x0), Math.round(y0), Math.round(x1 - x0), Math.round(y1 - y0));
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}
// fit a component into a screen box [cx, cy, w, h]
function framing(d, sel, box, o = {}) {
  const r = rectOf(d, sel); const [cx, cy, w, h] = typeof box === 'string' ? BOX[box] : box;
  const s = o.s || Math.min(w / r.w, h / r.h, o.max || 2.3) * (o.zoom || 1);
  return { x: r.x + r.w * (o.px ?? .5), y: r.y + r.h * (o.py ?? .5), s, ax: cx, ay: cy, rx: 0, ry: 0, rz: o.rz || 0, z: 0, o: 1, bl: 0 };
}
// tween(d, b, dur, to, ease, from): to = object or () => object; from(T) gives the start state relative to the target
function tween(d, b, dur, to, ease = E.inOut, from = null) { tweens.push({ d, b, dur, to, ease, from }); }
const IN = {
  rise: (T) => ({ ay: T.ay + 150, s: T.s * .97, o: 0, bl: 10 }),
  sink: (T) => ({ ay: T.ay - 150, s: T.s * .97, o: 0, bl: 10 }),
  depth: (T) => ({ s: T.s * .8, o: 0, bl: 8 }),
  near: (T) => ({ s: T.s * 1.18, o: 0, bl: 10 }),
  fromR: (T) => ({ ax: T.ax + 380, o: 0, bl: 6 }),
  fromL: (T) => ({ ax: T.ax - 380, o: 0, bl: 6 }),
  tilt: () => ({ ry: -24, rx: 10, z: -180, o: 0, bl: 4 }),
  plane: (T) => ({ rx: 26, ry: -18, rz: 3, ay: T.ay + 140, o: 0, bl: 6 }),
  fade: () => ({ o: 0 })
};
const OUT = {
  up: (C) => ({ ay: C.ay - 150, o: 0, bl: 10 }),
  down: (C) => ({ ay: C.ay + 150, o: 0, bl: 10 }),
  far: (C) => ({ s: C.s * .84, o: 0, bl: 8 }),
  near: (C) => ({ s: C.s * 1.35, o: 0, bl: 14 }),
  toL: (C) => ({ ax: C.ax - 380, o: 0, bl: 6 }),
  toR: (C) => ({ ax: C.ax + 380, o: 0, bl: 6 }),
  fade: () => ({ o: 0 })
};
// shot: show one component of deck d from beat b until `until`, entering with o.inn and leaving with o.out
function shot(d, b, until, o) {
  if (o.prep) at(b - (o.lead || .05), () => o.prep(app(d)));
  at(b - .02, () => solo(d, o.sel));
  const inDur = o.inDur || 1, outDur = o.outDur || .9;
  tween(d, b, inDur, () => framing(d, o.frame || o.sel, o.box || 'C', o), o.ease || E.quart, IN[o.inn || 'rise']);
  // the component keeps moving while it holds: slow push and an optional pan/turn/orbit
  const hold = until - b - inDur;
  if (hold > 0) tween(d, b + inDur, hold + outDur, () => { const C = decks[d].C; const r = { s: C.s * (o.push || 1.035) }; if (o.pan) r.ax = C.ax + o.pan; if (o.turn) r.rz = C.rz + o.turn; if (o.orbit) r.ry = C.ry + o.orbit; return r; }, E.sine);
  tween(d, until, outDur, () => OUT[o.out || 'up'](decks[d].C), o.outEase || E.in);
}
function applyCams(t) {
  for (const tw of tweens) {
    const t0 = tw.b * BEAT; if (t < t0 || tw.done) continue;
    const C = decks[tw.d].C;
    if (!tw.res) {
      tw.res = Object.assign({}, typeof tw.to === 'function' ? tw.to() : tw.to);
      if (tw.from) Object.assign(C, ZERO, tw.res, tw.from(tw.res));
      tw.start = Object.assign({}, C);
      // a newer move owns its keys: older moves on the same deck let go of them
      for (const o of tweens) if (o !== tw && o.d === tw.d && o.res && !o.done) for (const k in tw.res) delete o.res[k];
    }
    const p = tw.dur ? clamp((t - t0) / (tw.dur * BEAT)) : 1, e = tw.ease(p);
    for (const k in tw.res) C[k] = lerp(tw.start[k], tw.res[k], e);
    if (p >= 1) tw.done = true;
  }
  for (const k of decks) {
    const c = k.C;
    k.cam.style.transformOrigin = c.ax.toFixed(1) + 'px ' + c.ay.toFixed(1) + 'px';
    k.cam.style.transform = 'perspective(2400px) translateZ(' + c.z.toFixed(1) + 'px) rotateX(' + c.rx.toFixed(3) + 'deg) rotateY(' + c.ry.toFixed(3) + 'deg) rotateZ(' + c.rz.toFixed(3) + 'deg)';
    k.rig.style.transform = 'translate(' + (c.ax - c.x * c.s).toFixed(2) + 'px,' + (c.ay - c.y * c.s).toFixed(2) + 'px) scale(' + c.s.toFixed(4) + ')';
    k.cam.style.opacity = c.o.toFixed(3);
    k.cam.style.filter = c.bl > .05 ? 'blur(' + c.bl.toFixed(2) + 'px)' : 'none';
    k.cam.style.visibility = c.o < .002 ? 'hidden' : 'visible';
  }
}

/* ---------- type ---------- */
// txt(b0, b1, lines, pos): lines = [[cls, html], …] ('gap' for a spacer); pos = {x, y, align: 'l'|'c'|'r'}.
// Lines rise through a mask one after another (o.st beats apart) and leave together, drifting up.
const fx = [];
function txt(b0, b1, lines, pos, o = {}) {
  const html = lines.map(([c, h]) => (c === 'gap' ? '<div class="gap"></div>' : Array.isArray(h) ? '<div class="' + c + '">' + h.map((w) => '<span class="ln"><span>' + w + '</span></span>').join('') + '</div>' : '<span class="ln ' + c + '"><span>' + h + '</span></span>')).join('');
  const al = pos.align || 'l';
  const style = 'left:' + pos.x + 'px;top:' + pos.y + 'px;text-align:' + ({ l: 'left', c: 'center', r: 'right' })[al] + (o.style ? ';' + o.style : '');
  fx.push({ b0, b1, html, style, base: 'translate(' + ({ l: '0', c: '-50%', r: '-100%' })[al] + ',-50%)', anim: o.anim || mask(o.st ?? .18, o.inB || 1, o.outB || .6), tick: o.tick, tag: o.tag, el: null });
}
function mask(st, inB, outB) {
  return (el, tl, life) => {
    const q = E.inOut(clamp((life - tl) / (outB * BEAT)));
    el.querySelectorAll('.ln>span').forEach((s, i) => {
      const p = E.expo(clamp((tl - i * st * BEAT) / (inB * BEAT)));
      s.style.transform = 'translateY(' + ((1 - p) * 130 - (1 - q) * 30).toFixed(2) + '%)';
      s.style.opacity = (Math.min(1, p * 1.4) * q).toFixed(3);
      s.style.filter = q < .999 ? 'blur(' + ((1 - q) * 8).toFixed(1) + 'px)' : 'none';
    });
  };
}
// count-up for [data-count] spans
const count = (beats) => (el, tl) => el.querySelectorAll('[data-count]').forEach((n) => { n.textContent = Math.round(+n.dataset.count * E.out(clamp(tl / (beats * BEAT)))); });
function applyFx(t) {
  for (const f of fx) {
    const t0 = f.b0 * BEAT, t1 = f.b1 * BEAT, live = t >= t0 && t < t1;
    if (live && !f.el) { f.el = document.createElement('div'); f.el.className = 'k'; f.el.innerHTML = f.html; f.el.setAttribute('style', f.style); f.el.style.transform = f.base; fxEl.appendChild(f.el); }
    if (!live && f.el) { f.el.remove(); f.el = null; }
    if (f.el) { f.anim(f.el, t - t0, t1 - t0, t); if (f.tick) f.tick(f.el, t - t0, t1 - t0, t); }
  }
}
let glow = { b: null, from: 0, to: 0, v: 0, dur: 2 };
function glowAt(b, v, dur = 2) { at(b, () => { glow = { b, from: glow.v, to: v, v: glow.v, dur }; }); }
function applyGlow(t) { if (glow.b == null) return; glow.v = lerp(glow.from, glow.to, E.inOut(clamp((t / BEAT - glow.b) / glow.dur))); glowEl.style.opacity = glow.v.toFixed(3); }

/* ---------- app control ---------- */
const cues = [];
function at(b, fn) { cues.push({ b, fn, done: false }); }
function app(d) {
  const k = decks[d], W = k.W, D = k.D;
  return {
    W, D, S: W.eval('S'),
    go: (r) => { if (W.closeOverlay) W.closeOverlay(); if (W.closeModal) W.closeModal(); W.go(r); },
    click: (sel) => { const el = typeof sel === 'string' ? D.querySelector(sel) : sel; if (el) el.click(); else console.warn('promo: no click target', sel); },
    render: () => W.render()
  };
}
// show only these elements of deck d (they are scrolled into view first)
function solo(d, sel) {
  const D = decks[d].D; decks[d].solo = sel;
  D.querySelectorAll('.promo-solo').forEach((e) => e.classList.remove('promo-solo'));
  for (const s of Array.isArray(sel) ? sel : [sel]) {
    const el = find(d, s); if (!el) { console.warn('promo: no solo target', String(s)); continue; }
    const r = el.getBoundingClientRect();
    if (r.top < 0 || r.bottom > D.documentElement.clientHeight) el.scrollIntoView({ block: 'center', behavior: 'instant' });
    el.classList.add('promo-solo');
  }
}
const byText = (sel, text) => (D) => [...D.querySelectorAll(sel)].find((e) => e.textContent.includes(text));
const PROMO_CSS = 'html,body,.desk{background:transparent!important}.desk .wall{display:none!important}.tip{display:none!important}' +
  'html body *{visibility:hidden!important}html body .promo-solo,html body .promo-solo *{visibility:visible!important}' +
  'html body .promo-solo:not(svg){box-shadow:0 0 0 .5px rgba(255,255,255,.14),0 30px 90px rgba(0,0,0,.55)!important}' +
  '.promo-card{background:var(--surface)!important;border-radius:12px;box-shadow:0 0 0 22px var(--surface),0 30px 90px 22px rgba(0,0,0,.55)!important}' +
  '.promo-solo [hidden]{visibility:hidden!important}:root{color-scheme:light!important}';

/* ---------- drivers: per-frame changes to the app's own charts, as functions of the beat ---------- */
// drive(d, b0, b1, fn): fn(p, b, D) runs every frame from b0 until it has run once with p = 1
const drives = [];
function drive(d, b0, b1, fn) { drives.push({ d, b0, b1, fn, fin: false }); }
function applyDrives(t) {
  const b = t / BEAT;
  for (const x of drives) {
    if (x.fin || b < x.b0) continue;
    const D = decks[x.d].D; if (!D && !decks[x.d].virtual) continue;
    const p = clamp((b - x.b0) / (x.b1 - x.b0));
    try { x.fn(p, b, D); } catch (e) { console.error('drive @' + x.b0, e); x.fin = true; }
    if (p >= 1) x.fin = true;
  }
}
const SVGNS = 'http://www.w3.org/2000/svg';
const lp = (b, b0, dur) => clamp((b - b0) / dur);          // local progress of a staggered item

// odometer digits: every digit is a strip 0-9 ×3 that rolls up and settles on its value
function odo(v) {
  return String(v).split('').map((c) => (/\d/.test(c) ? '<span class="dg" data-d="' + c + '"><span class="st">' + '0123456789'.repeat(3).split('').join('<br>') + '</span></span>' : '<span class="sep">' + c + '</span>')).join('');
}
function rollOdo(el, b, b0, dur) {
  el.querySelectorAll('.dg').forEach((g, i, all) => {
    const d = +g.dataset.d, q = E.quart(lp(b, b0 + (all.length - 1 - i) * .12, dur));
    g.firstChild.style.transform = 'translateY(' + (-(20 + d) * q).toFixed(3) + 'em)';
  });
}

// trend chart: column i grows from the baseline, one after another
function growBars(svg, b, b0, gap, dur) {
  svg.querySelectorAll('path.vz-bar').forEach((p) => {
    const q = E.quart(lp(b, b0 + +p.dataset.i * gap, dur));
    p.style.animation = 'none'; p.style.transformBox = 'view-box'; p.style.transformOrigin = '0px 168px';
    p.style.transform = q >= 1 ? '' : 'scaleY(' + q.toFixed(4) + ')';
  });
}
// fingerprint ring: the 24 hour segments appear clockwise, growing out from the centre
function growRing(svg, b, b0, gap, dur) {
  svg.querySelectorAll('g.ring > g.fps').forEach((g) => {
    const q = E.quart(lp(b, b0 + +g.dataset.h * gap, dur));
    g.style.transformBox = 'view-box'; g.style.transformOrigin = '200px 200px';
    g.style.transform = 'scale(' + lerp(.72, 1, q).toFixed(4) + ')'; g.style.opacity = q.toFixed(3);
  });
}
// a line (or several) drawn forward with a clip that slides from left to right
function drawForward(svg, f, x0, x1) {
  let cp = svg.querySelector('#promoClip');
  if (!cp) {
    cp = document.createElementNS(SVGNS, 'clipPath'); cp.id = 'promoClip';
    const r = document.createElementNS(SVGNS, 'rect'); r.setAttribute('y', '-20'); r.setAttribute('height', '400'); r.setAttribute('x', String(x0 - 6));
    cp.appendChild(r); svg.appendChild(cp);
    svg.querySelectorAll('path.vz-line, circle.vz-pt').forEach((e) => e.setAttribute('clip-path', 'url(#promoClip)'));
  }
  cp.firstChild.setAttribute('width', String(Math.max(0, (x1 - x0 + 12) * f)));
}
// KPI sparkline: the line draws itself and the dot rides its head
function drawSpark(svg, f) {
  const path = svg.querySelector('path'), dot = svg.querySelector('circle'); if (!path) return;
  const L = path.getTotalLength();
  path.style.strokeDasharray = L.toFixed(2); path.style.strokeDashoffset = (L * (1 - f)).toFixed(2);
  if (dot) { const pt = path.getPointAtLength(L * f); dot.setAttribute('cx', pt.x.toFixed(2)); dot.setAttribute('cy', pt.y.toFixed(2)); dot.style.opacity = f > .01 ? '1' : '0'; }
}

/* the persona compass (deck 2). It follows the app's compass dial (fp2SVG in 41-a2-persona.js, from the ui/compass
   session) at 2× on a dark face: bezel with 120 ticks and 24-hour bearings, a rose whose four major points face the
   D I M V axes (length = strength of the axis, the tip shows the winning pole), four short minor points, and a
   double-diamond needle on the collaboration heading. The outer ring of the app becomes one continuous five-layer band
   (one layer per Agent, smoothed between the hours), and the five Agents orbit on it. Every one of the 16 types has an
   archetype for all of this, so switching types stretches the rose, flips the tip letters, swings the needle and
   reshapes the band. Names, poles and wording come from the app (TYPES, AXES), checked with the "16型人格名称" session. */
const CP = { C: 400, R0: 248, BAND: 76, RR: 140, NL: 112 };   // needle = 0.8 × rose radius (shared spec)
const AXR2 = { D: 0, I: 90, M: 180, V: 270 };              // = AXR in 41-a2-persona.js
const cpt = (r, deg) => [CP.C + r * Math.sin(deg * Math.PI / 180), CP.C - r * Math.cos(deg * Math.PI / 180)];
const f2 = (q) => q[0].toFixed(1) + ' ' + q[1].toFixed(1);
const roseLen = (strong) => CP.RR * (.36 + .64 * clamp((strong - 50) / 35));          // = fpRoseLen
function rosePt(deg, len, w) {                              // = fpRosePt: clockwise half solid, the other outlined
  const tip = cpt(len, deg), r = cpt(w, deg + 45), l = cpt(w, deg - 45);
  return ['M400 400L' + f2(tip) + 'L' + f2(r) + 'Z', 'M400 400L' + f2(tip) + 'L' + f2(l) + 'Z'];
}
// axis i of a value set → strength and winning letter (= axisView in 15-derive.js)
function axisOf(v, i) {
  const ax = CPD.AXES[i], val = v[ax.k], pos = ax.k !== 'I' ? 100 - val : val;
  const leftWins = pos < 50; return { strong: Math.max(val, 100 - val), letter: leftWins ? ax.L : ax.R };
}
// archetype of a type: its letters win at strength 74–82, a small per-type variation keeps shapes organic
function archetype(code) {
  const h = [...code].reduce((a, c) => a * 31 + c.charCodeAt(0), 7), j = (k) => ((h >> (k * 3)) & 7) - 3;
  const s = (k) => 78 + j(k);
  return { D: code[0] === 'D' ? s(0) : 100 - s(0), I: code[1] === 'I' ? s(1) : 100 - s(1), M: code[2] === 'M' ? s(2) : 100 - s(2), V: code[3] === 'V' ? s(3) : 100 - s(3) };
}
// archetype rhythm (24 h × 5 agents) and heading: P plans in the morning, I improvises late; M spreads over agents
function rhythm(code) {
  const peak = code[1] === 'P' ? 10.5 : 21.5, peak2 = code[0] === 'D' ? 15.5 : 13, wd = code[2] === 'M' ? 3.4 : 2.1;
  const mix = code[2] === 'M' ? [.42, .24, .16, .11, .07] : [.78, .12, .05, .03, .02];
  const g = (h, c) => { const d = Math.min(Math.abs(h - c), 24 - Math.abs(h - c)); return Math.exp(-d * d / (2 * wd * wd)); };
  return Array.from({ length: 24 }, (_, h) => { const v = .08 + g(h, peak) + .7 * g(h, peak2); return mix.map((m) => v * m); });
}
const headingOf = (code) => (code[1] === 'P' ? 12.5 : code[0] === 'D' ? 18 : 16) * 15;
const AGC = ['var(--a1)', 'var(--a2)', 'var(--a3)', 'var(--a4)', 'var(--a5)'];
let CPD = null;                                             // read once from the app: TYPES, AXES, my persona, hours, heading
function compassData() {
  if (CPD) return CPD;
  const W = decks[0].W;
  const L = W.eval('sel({ noExtra: true })'), ids = W.eval('AG').map((a) => a.id);
  const hrs = Array.from({ length: 24 }, () => [0, 0, 0, 0, 0]); L.forEach((s) => { hrs[s.h][ids.indexOf(s.a)]++; });
  const mx = Math.max(...hrs.map((r) => r.reduce((a, b) => a + b, 0)));
  let sx = 0, cx = 0; L.forEach((s) => { const a = (s.h + s.mi / 60) / 24 * Math.PI * 2; sx += Math.sin(a); cx += Math.cos(a); });
  const ahd = ids.map((id) => { let a = 0, c = 0; L.filter((s) => s.a === id).forEach((s) => { const r = (s.h + s.mi / 60) / 24 * Math.PI * 2; a += Math.sin(r); c += Math.cos(r); }); return (Math.atan2(a, c) * 180 / Math.PI + 360) % 360; });
  CPD = { TYPES: W.eval('TYPES'), AXES: W.eval('AXES'), me: W.eval('persona(sel({ noExtra: true }))'), hrs: hrs.map((r) => r.map((x) => x / mx * 1.6)), hd: (Math.atan2(sx, cx) * 180 / Math.PI + 360) % 360, ahd };
  return CPD;
}
function buildCompass() {
  const k = decks[2]; if (k.svg) return k.svg;
  compassData();
  const W = 'rgba(255,255,255,';
  let tk = ['', '', '']; for (let i = 0; i < 120; i++) { const w = i % 30 === 0 ? 2 : i % 5 === 0 ? 1 : 0; tk[w] += 'M' + f2(cpt(389, i * 3)) + 'L' + f2(cpt([381, 375, 368][w], i * 3)); }
  let h = '<defs><mask id="cpSweep" maskUnits="userSpaceOnUse" x="-100" y="-100" width="1000" height="1000"><path id="cpSweepP" fill="#fff"/></mask>' +
    '<radialGradient id="cpFace"><stop offset="0" stop-color="' + W + '.07)"/><stop offset=".7" stop-color="' + W + '.03)"/><stop offset="1" stop-color="' + W + '0)"/></radialGradient></defs>' +
    '<g class="cp-dial"><circle cx="400" cy="400" r="396" fill="url(#cpFace)" stroke="' + W + '.55)" stroke-width="2"/><circle cx="400" cy="400" r="390" fill="none" stroke="' + W + '.18)" stroke-width="1"/>' +
    '<path d="' + tk[0] + '" stroke="' + W + '.22)" stroke-width="1"/><path d="' + tk[1] + '" stroke="' + W + '.45)" stroke-width="1.4"/><path d="' + tk[2] + '" stroke="#fff" stroke-width="2.4"/>' +
    '<path d="M400 8L390 -10L410 -10Z" fill="var(--orbit)"/>' +
    [0, 3, 6, 9, 12, 15, 18, 21].map((hh) => { const card = hh % 6 === 0, q = cpt(card ? 343 : 352, hh * 15); return '<text x="' + q[0].toFixed(1) + '" y="' + q[1].toFixed(1) + '" text-anchor="middle" dominant-baseline="central" class="' + (card ? 'cp-hc' : 'cp-hs') + '">' + String(hh).padStart(2, '0') + '</text>'; }).join('') +
    '<circle cx="400" cy="400" r="' + CP.R0 + '" fill="none" stroke="' + W + '.2)"/><circle cx="400" cy="400" r="' + (CP.R0 + CP.BAND) + '" fill="none" stroke="' + W + '.08)" stroke-dasharray="3 5"/></g>' +
    '<g id="cpBand" mask="url(#cpSweep)">' + AGC.map((c, i) => '<path class="band" fill="' + c + '" fill-opacity="' + (.95 - i * .05) + '"/>').join('') + '</g>' +
    '<g id="cpPlanets">' + AGC.map((c) => '<g class="pl"><circle r="15" fill="' + c + '" opacity=".22"/><circle r="7.5" fill="' + c + '" stroke="#000" stroke-width="2"/></g>').join('') + '</g>' +
    '<g class="cp-core"><circle cx="400" cy="400" r="184" fill="rgba(10,10,12,.92)" stroke="' + W + '.22)"/><circle cx="400" cy="400" r="' + CP.RR + '" fill="none" stroke="' + W + '.12)" stroke-dasharray="2 6"/>' +
    '<path d="M400 220V580M220 400H580" stroke="' + W + '.12)" stroke-width="1.4"/>' +
    [45, 135, 225, 315].map((d) => { const x = rosePt(d, CP.RR * .4, CP.RR * .1); return '<path d="' + x[0] + '" fill="' + W + '.55)"/><path d="' + x[1] + '" fill="none" stroke="' + W + '.55)" stroke-width="1.4" stroke-linejoin="round"/>'; }).join('') + '</g>' +
    '<g id="cpRose">' + 'DIMV'.split('').map((x) => '<g class="pt" data-k="' + x + '"><path class="a" fill="#f4f4f6"/><path class="b" fill="rgba(10,10,12,.9)" stroke="#f4f4f6" stroke-width="2.2" stroke-linejoin="round"/></g>').join('') + '</g>' +
    '<g id="cpNeedle"><path d="M400 ' + (400 - CP.NL) + 'L406 400L394 400Z" fill="var(--orbit)"/><path d="M400 ' + (400 + CP.NL) + 'L406 400L394 400Z" fill="rgba(10,10,12,.9)" stroke="var(--orbit)" stroke-width="2"/></g>' +
    '<g id="cpLbl">' + 'DIMV'.split('').map((x) => '<g class="lb" data-k="' + x + '"><text class="cp-l" text-anchor="middle" dominant-baseline="central"></text><text class="cp-s" text-anchor="middle" dominant-baseline="central"></text></g>').join('') + '</g>' +
    '<circle cx="400" cy="400" r="14" fill="#0b0b0d" stroke="#fff" stroke-width="2.6"/><circle cx="400" cy="400" r="4" fill="#fff"/>';
  const svg = document.createElementNS(SVGNS, 'svg'); svg.setAttribute('viewBox', '0 0 800 800'); svg.setAttribute('width', '800'); svg.setAttribute('height', '800'); svg.setAttribute('class', 'compass');
  svg.style.overflow = 'visible'; svg.innerHTML = h; k.rig.appendChild(svg); k.svg = svg;
  return svg;
}
// st = { v:{D,I,M,V}, hrs: 24×5, hd: needle deg, grow 0..1, sweep 0..1, spin: extra rose turn (deg), lit 0..1, orbit: planet phase (deg), dial 0..1 }
function drawCompass(st) {
  const svg = buildCompass();
  const N = 180, cum = new Array(N + 1).fill(0);
  const val = (hr, i, f) => { const a = st.hrs[(hr + 23) % 24][i], b = st.hrs[hr][i], c = st.hrs[(hr + 1) % 24][i], d = st.hrs[(hr + 2) % 24][i]; return .5 * (2 * b + (-a + c) * f + (2 * a - 5 * b + 4 * c - d) * f * f + (-a + 3 * b - 3 * c + d) * f * f * f); };
  svg.querySelectorAll('path.band').forEach((path, i) => {
    const inner = cum.slice(), outer = [];
    for (let s = 0; s <= N; s++) { const hh = s / N * 24, hr = Math.floor(hh) % 24; cum[s] += Math.max(0, val(hr, i, hh - Math.floor(hh))) * CP.BAND / 1.6; outer.push(cum[s]); }
    let d = ''; for (let s = 0; s <= N; s++) d += (s ? 'L' : 'M') + f2(cpt(CP.R0 + 2 + outer[s], s / N * 360));
    for (let s = N; s >= 0; s--) d += 'L' + f2(cpt(CP.R0 + 2 + inner[s], s / N * 360));
    path.setAttribute('d', d + 'Z');
  });
  const sw = clamp(st.sweep), sp = svg.querySelector('#cpSweepP');
  if (sw >= 1) sp.setAttribute('d', 'M-100 -100H900V900H-100Z');
  else { let d = 'M400 400'; for (let s = 0; s <= 60; s++) d += 'L' + f2(cpt(700, sw * 360 * s / 60)); sp.setAttribute('d', d + 'Z'); }
  // the five Agents orbit on the band; at rest each one sits on its own collaboration heading (shared spec)
  svg.querySelectorAll('#cpPlanets .pl').forEach((g, i) => {
    const run = (st.orbit || 0) + i * 23, rest = CPD.ahd[i], k = clamp(st.settle || 0);
    const a = run + ((((rest - run) % 360) + 540) % 360 - 180) * E.inOut(k), q = cpt(CP.R0 + CP.BAND * .55, a);
    g.setAttribute('transform', 'translate(' + f2(q) + ')'); g.style.opacity = (clamp(sw * 3 - i * .3) * (st.planets ?? 1)).toFixed(3);
  });
  // rose: four major points; the tip shows the winning pole and its strength
  const gr = clamp(st.grow);
  'DIMV'.split('').forEach((x, i) => {
    const a = axisOf(st.v, i), len = Math.max(1, roseLen(a.strong) * E.out(clamp(gr * 1.5 - i * .15))), q = rosePt(AXR2[x] + (st.spin || 0), len, CP.RR * .18);
    const g = svg.querySelector('#cpRose .pt[data-k="' + x + '"]'); g.querySelector('.a').setAttribute('d', q[0]); g.querySelector('.b').setAttribute('d', q[1]);
    const lb = svg.querySelector('#cpLbl .lb[data-k="' + x + '"]'), d = AXR2[x] + (st.spin || 0), tip = cpt(len + 30, d), sc = [tip[0], tip[1] + (AXR2[x] === 0 ? -30 : 30)];
    const t1 = lb.querySelector('.cp-l'), t2 = lb.querySelector('.cp-s');
    t1.setAttribute('x', tip[0].toFixed(1)); t1.setAttribute('y', tip[1].toFixed(1)); t1.textContent = a.letter;
    t2.setAttribute('x', sc[0].toFixed(1)); t2.setAttribute('y', sc[1].toFixed(1)); t2.textContent = Math.round(a.strong);
    const on = clamp(typeof st.lit === 'number' ? st.lit : st.lit[x] ?? 1);
    lb.style.opacity = (gr * (.35 + .65 * on)).toFixed(3); t1.style.fill = on > .5 && st.mine ? 'var(--acc)' : '#fff';
  });
  svg.querySelector('#cpNeedle').setAttribute('transform', 'rotate(' + (st.hd || 0).toFixed(2) + ' 400 400)');
  svg.querySelector('#cpNeedle').style.opacity = (st.needle ?? 1).toFixed(3);
  svg.querySelectorAll('.cp-dial, .cp-core, #cpRose, #cpLbl, #cpNeedle').forEach((e) => { if (e.id !== 'cpNeedle') e.style.opacity = (st.dial ?? 1).toFixed(3); });
}
function mixState(a, b, f) {
  const v = {}; for (const k of 'DIMV') v[k] = lerp(a.v[k], b.v[k], f);
  let dh = ((b.hd - a.hd) % 360 + 540) % 360 - 180;           // the needle takes the short way round
  return { v, hrs: a.hrs.map((r, h) => r.map((x, i) => lerp(x, b.hrs[h][i], f))), hd: a.hd + dh * f };
}

/* the Orbit mark, live: the same conical spiral as docs/design/logo/generate.py, variant "spiral" (1.6 turns, radius
   9 → 16, rise 14, phase 0.6, seen at yaw 20° / pitch 45° — the app icon), drawn as a tapered line so it can be traced
   from its tail, turned in 3D and flattened (pitch 90° = seen from above, a near-circle like the compass ring).
   Five Agent dots ride a flat orbit before they merge into the line. Everything is drawn into #orbit (stage space). */
const ORB = { turns: 1.6, r0: 9, r1: 16, rise: 14, phase: .6, N: 240, TAPER: .12 };
const orbEl = $('#orbit');
function orbitPts(yaw, pitch) {
  const Y = yaw * Math.PI / 180, P = pitch * Math.PI / 180, out = [];
  for (let k = 0; k <= ORB.N; k++) {
    const t = k / ORB.N, th = 2 * Math.PI * ORB.turns * t + ORB.phase, r = ORB.r0 + (ORB.r1 - ORB.r0) * t;
    const x = r * Math.cos(th), y = r * Math.sin(th), z = ORB.rise * (t - .5);
    const x1 = x * Math.cos(Y) - y * Math.sin(Y), y1 = x * Math.sin(Y) + y * Math.cos(Y);
    const y2 = y1 * Math.cos(P) - z * Math.sin(P), z2 = y1 * Math.sin(P) + z * Math.cos(P);
    out.push([x1 / ORB.r1, -z2 / ORB.r1, -y2 / ORB.r1]);   // screen x, screen y (unit = outer radius), depth (bigger = nearer)
  }
  return out;
}
// o = { t: drawn share 0..1, yaw, pitch, R: px per unit, cx, cy, w: max width, a: opacity, head: 0..1 glow at the tip }
function orbitSVG(o) {
  if (!o || o.a <= .001) return '';
  const p = orbitPts(o.yaw, o.pitch), n = Math.max(1, Math.round(o.t * ORB.N));
  const z0 = Math.min(...p.map((q) => q[2])), z1 = Math.max(...p.map((q) => q[2]));
  // split the drawn part into runs of similar depth; draw the runs back to front, each with a black halo so a nearer
  // run cuts cleanly across a farther one (the icon's over/under), and taper the two ends
  const L = 6, X = (q) => (o.cx + q[0] * o.R).toFixed(1) + ' ' + (o.cy + q[1] * o.R).toFixed(1);
  const lvl = (k) => Math.min(L - 1, Math.floor(((p[k][2] + p[k + 1][2]) / 2 - z0) / (z1 - z0 || 1) * L));
  const runs = []; let cur = null;
  for (let k = 0; k < n; k++) { const v = lvl(k); if (!cur || cur.v !== v) { cur = { v, k0: k, k1: k }; runs.push(cur); } else cur.k1 = k; }
  runs.sort((a, b) => a.v - b.v);
  let h = '<g opacity="' + o.a.toFixed(3) + '" fill="none" stroke-linecap="round" stroke-linejoin="round">';
  for (const r of runs) {
    let d = 'M' + X(p[r.k0]); for (let k = r.k0 + 1; k <= r.k1 + 1; k++) d += 'L' + X(p[k]);
    // the halo stops a few points short of the run's ends, so neighbouring runs join without a nick
    const h0 = Math.min(r.k1, r.k0 + 3), h1 = Math.max(h0, r.k1 - 2); let dh = 'M' + X(p[h0]); for (let k = h0 + 1; k <= h1 + 1; k++) dh += 'L' + X(p[k]);
    const end = Math.min(1, Math.min(r.k0, n - r.k1) / ORB.N / ORB.TAPER + .35), w = (o.w * .45 + o.w * .55 * (r.v + .5) / L) * end;
    h += (h1 > h0 ? '<path d="' + dh + '" stroke="#000" stroke-width="' + (w + 10).toFixed(1) + '"/>' : '') + '<path d="' + d + '" stroke="' + (o.color || '#e9eaee') + '" stroke-width="' + w.toFixed(1) + '"/>';
  }
  if (o.head > .01 && n < ORB.N) { const q = X(p[n]).split(' '); h += '<circle cx="' + q[0] + '" cy="' + q[1] + '" r="' + (o.w * 1.6).toFixed(1) + '" fill="url(#orbGlow)" opacity="' + o.head.toFixed(3) + '"/><circle cx="' + q[0] + '" cy="' + q[1] + '" r="' + (o.w * .55).toFixed(1) + '" fill="#fff" opacity="' + o.head.toFixed(3) + '"/>'; }
  return h + '</g>';
}
// the five Agents on a flat orbit (an ellipse around cx, cy) — before they merge into the mark
function planetsSVG(o) {
  if (!o || o.a <= .001) return '';
  return '<g opacity="' + o.a.toFixed(3) + '">' + AGC.map((c, i) => {
    const a = (o.phase + i * 72) * Math.PI / 180, x = o.cx + Math.cos(a) * o.rx * (1 - o.pull), y = o.cy + Math.sin(a) * o.ry * (1 - o.pull);
    const tx = lerp(x, o.tx, o.pull), ty = lerp(y, o.ty, o.pull);
    return '<circle cx="' + tx.toFixed(1) + '" cy="' + ty.toFixed(1) + '" r="16" fill="' + c + '" opacity=".18"/><circle cx="' + tx.toFixed(1) + '" cy="' + ty.toFixed(1) + '" r="7" fill="' + c + '"/>';
  }).join('') + '<ellipse cx="' + o.cx + '" cy="' + o.cy + '" rx="' + (o.rx * (1 - o.pull)).toFixed(1) + '" ry="' + (o.ry * (1 - o.pull)).toFixed(1) + '" fill="none" stroke="rgba(255,255,255,.14)" stroke-dasharray="2 7"/></g>';
}
// the orbit timeline (beats) — open: planets → the mark is traced and turns into place → it flattens into a ring that
// opens the first scene; close: the compass tilts back into an orbit and the mark is traced over it → end card
function orbitAt(b) {
  let h = '';
  // 1 · the five Agents circle the centre while the line "自己是怎样和它们协作的" plays, then fall onto the tail of the mark
  if (b >= 5.6 && b < 8.6) {
    const start = orbitPts(-25, 72)[0];
    h += planetsSVG({ a: E.out(lp(b, 5.6, .8)) * (1 - E.in(lp(b, 8.1, .5))), phase: (b - 5.6) * 95, cx: 960, cy: 780, rx: 360, ry: 70, pull: E.inOut(lp(b, 7.5, 1)), tx: 960 + start[0] * 215, ty: 410 + start[1] * 215 });
  }
  // 2 · the mark is traced from its tail while it turns into the icon's angle; then it flattens and grows into a ring
  if (b >= 7.9 && b < 14.4) {
    const flat = E.inOut(lp(b, 12.6, 1.6));
    h += orbitSVG({ t: E.inOut(lp(b, 7.9, 2.4)), yaw: lerp(lerp(-25, 20, E.out(lp(b, 7.9, 3.4))), 20, flat), pitch: lerp(lerp(72, 45, E.out(lp(b, 7.9, 3.4))), 90, flat), R: lerp(215, 980, E.in(flat)), cx: 960, cy: lerp(410, 540, flat), w: lerp(15, 4, flat), a: 1 - E.in(lp(b, 13.4, 1)), head: 1 - lp(b, 10.1, .5) });
  }
  // 3 · close: traced again over the tilted compass ring, then it settles as the end-card mark and slowly turns
  if (b >= 105.2) {
    const m = E.inOut(lp(b, 107.4, 2));                    // from over the compass to the end-card position
    h += orbitSVG({ t: E.inOut(lp(b, 105.2, 2.4)), yaw: 20 + 14 * Math.sin((b - 108) * .35) * lp(b, 109, 3), pitch: lerp(64, 45, m), R: lerp(330, 215, m), cx: 960, cy: lerp(500, 410, m), w: lerp(9, 15, m), a: E.out(lp(b, 105.2, .6)) * (1 - E.inOut(lp(b, 118, 1.6))), head: 1 - lp(b, 107.4, .5) });
  }
  orbEl.innerHTML = '<defs><radialGradient id="orbGlow"><stop offset="0" stop-color="rgba(255,255,255,.9)"/><stop offset="1" stop-color="rgba(255,255,255,0)"/></radialGradient></defs>' + h;
}

/* a macOS pointer that glides to a control, presses it, and then the action runs — one per app copy, drawn inside the
   copy so it follows the camera, counter-scaled so it keeps a constant size on screen */
const CURSOR_SVG = '<svg viewBox="0 0 28 28" width="28" height="28"><path d="M6 3.5v19.2l4.6-4.4 3 6.9 3.3-1.4-2.9-6.8h6.5z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
const clicks = [];
function clickAt(d, b, sel, fn) { clicks.push({ d, b, sel, fn }); at(b, () => { const el = find(d, sel); if (el) fn(app(d), el); else console.warn('promo: no click target', sel); }); }
function cursorEl(d) {
  const k = decks[d]; if (k.cursor) return k.cursor;
  const c = document.createElement('div'); c.className = 'cursor'; c.innerHTML = CURSOR_SVG + '<i class="ripple"></i>'; k.rig.appendChild(c); k.cursor = c; return c;
}
function applyCursors(t) {
  const b = t / BEAT;
  for (const k of decks) { const c = k.cursor; if (c) c.style.opacity = '0'; }
  for (const x of clicks) {
    if (b < x.b - 1.3 || b > x.b + .9) continue;
    if (!x.to) { const el = find(x.d, x.sel); if (!el) continue; const r = el.getBoundingClientRect(); x.to = [r.left + r.width * .5, r.top + r.height * .55]; x.from = [x.to[0] + 160, x.to[1] + 120]; }
    const c = cursorEl(x.d), s = decks[x.d].C.s;
    const m = E.inOut(lp(b, x.b - 1.1, 1)), press = b >= x.b && b < x.b + .25 ? .82 : 1;
    const px = lerp(x.from[0], x.to[0], m), py = lerp(x.from[1], x.to[1], m);
    c.style.opacity = (E.out(lp(b, x.b - 1.3, .35)) * (1 - E.in(lp(b, x.b + .55, .35)))).toFixed(3);
    c.style.transform = 'translate(' + px.toFixed(2) + 'px,' + py.toFixed(2) + 'px) scale(' + (1.8 / s * press).toFixed(4) + ')';
    const rp = lp(b, x.b, .6); const ri = c.querySelector('.ripple');
    ri.style.opacity = b >= x.b ? (1 - rp).toFixed(3) : '0'; ri.style.transform = 'translate(-50%,-50%) scale(' + (.4 + rp * 1.6).toFixed(3) + ')';
  }
}

/* ============================== the script ============================== */
// Shot list with timings, motion, type and sound per shot: STORYBOARD.md. Times are beats (124 BPM, 1 beat = 0.484 s).
// 0–8 open · 8–13.6 logo · 13.4–19 numbers → KPI tiles · 19–23 sparkline runs forward · 23–29.5 bars grow ·
// 29.5–46 01 Analysis: the compass (16 types, fast and slow, landing on yours) · 46–58 02 Recommend: 12 suggestions add up
// the hours saved, then a one-click install · 58–66 03 Trajectory · 66–79 insight → studio · 79–86.5 04 Ask (build) ·
// 87–101 seven features, two beats each · 101–108.5 the compass again · 109–120 end card
const L = 160, R = 1760;                                    // text margins
function split2(s) { const i = s.indexOf('，', 6); return i > 0 ? [s.slice(0, i + 1), s.slice(i + 1)] : [s]; }
function smallest(D, sel, text) { return [...D.querySelectorAll(sel)].filter((e) => e.textContent.includes(text)).sort((a, b) => a.textContent.length - b.textContent.length)[0]; }
function script() {
  // --- open (缓)
  txt(.25, 3.9, [['row md', ['你每天', '和 <span class="acc">5</span> 个 Agent', '协作上百次']]], { x: 960, y: 450, align: 'c' }, { st: .6 });
  const AGS = [['Claude Code', 'var(--a1)'], ['Codex', 'var(--a2)'], ['Gemini CLI', 'var(--a3)'], ['DeepSeek', 'var(--a4)'], ['Copilot', 'var(--a5)']];
  txt(1.5, 3.9, [['', AGS.map((a) => '<span class="chip"><i style="background:' + a[1] + '"></i>' + a[0] + '</span>').join('')]], { x: 960, y: 560, align: 'c' }, {
    anim: (el, tl, life) => {
      const q = E.inOut(clamp((life - tl) / (.6 * BEAT)));
      el.querySelectorAll('.chip').forEach((c, i) => { const p = E.expo(clamp((tl - (.7 + i * .375) * BEAT) / (.8 * BEAT))); c.style.opacity = (p * q).toFixed(3); c.style.transform = 'translateY(' + ((1 - p) * 24).toFixed(1) + 'px)'; c.style.marginRight = i < 4 ? '44px' : '0'; c.style.filter = q < .999 ? 'blur(' + ((1 - q) * 8).toFixed(1) + 'px)' : 'none'; });
    }
  });
  txt(4, 5.9, [['row md', ['却很少', '回头看看']]], { x: 960, y: 540, align: 'c' }, { st: .5 });
  txt(6, 7.9, [['row md', ['自己是', '<span class="serif acc"><i>怎样</i></span>', '和它们协作的']]], { x: 960, y: 540, align: 'c' }, { st: .4 });

  // --- logo
  glowAt(8, 1, 3);
  txt(9.6, 13.2, [['word', 'Orbit']], { x: 960, y: 690, align: 'c' }, { inB: 1.4, outB: .8 });
  txt(10.6, 13.2, [['lt', '看见你与 Agent 的每一次协作']], { x: 960, y: 790, align: 'c' }, { inB: 1.4, outB: .8 });
  glowAt(13, .45, 2);

  // --- numbers roll, then fly into the KPI tiles they come from
  const NUMS = [[186, '', '个会话'], [142, 'h', '小时协作'], ['1,284', '', '条消息']];
  const TILES = { box: [960, 600, 1700, 420] };
  const morph = [];
  at(17.3, () => {
    const T = framing(0, '.tiles', TILES.box);
    NUMS.forEach((n, i) => {
      const f = fx.find((x) => x.tag === 'num' + i); const span = f && f.el && f.el.querySelector('.odo'); if (!span) return;
      const v = decks[0].D.querySelectorAll('.tiles .vz-kpi .v')[i]; if (!v) return;
      const r = v.getBoundingClientRect(), k = stage.getBoundingClientRect().width / 1920, s0 = span.getBoundingClientRect();
      const tx = T.ax + (r.left - T.x) * T.s, ty = T.ay + (r.top + r.height / 2 - T.y) * T.s;
      const sx = (s0.left - stage.getBoundingClientRect().left) / k, sy = (s0.top + s0.height / 2 - stage.getBoundingClientRect().top) / k;
      morph[i] = { dx: tx - sx, dy: ty - sy, sc: (r.height * T.s) / (s0.height / k) };
    });
  });
  NUMS.forEach((n, i) => {
    const b0 = 13.8 + i * .5;
    txt(b0, 19.2, [['', '<span class="odo">' + odo(n[0]) + '</span><span class="odo-u">' + n[1] + '</span>'], ['lt', n[2]]], { x: 960 + (i - 1) * 520, y: 520, align: 'c' }, {
      anim: (el, tl, life, t) => {
        const b = t / BEAT, m = E.inOut(lp(b, 17.4, 1.45)), mv = morph[i];
        const inP = E.expo(clamp(tl / (.9 * BEAT)));
        el.style.opacity = (inP * (1 - E.inOut(lp(b, 18.85, .3)))).toFixed(3);
        rollOdo(el, b, b0, 1.9);
        const o = el.querySelector('.odo');
        o.style.transformOrigin = '0 50%';
        const ink = Math.round(lerp(255, 23, Math.pow(m, 3)));
        o.style.color = 'rgb(' + ink + ',' + ink + ',' + Math.round(lerp(255, 27, Math.pow(m, 3))) + ')';
        o.style.transform = mv ? 'translate(' + (mv.dx * m).toFixed(1) + 'px,' + (mv.dy * m).toFixed(1) + 'px) scale(' + lerp(1, mv.sc, m).toFixed(4) + ')' : '';
        el.querySelectorAll('.odo-u, .ln.lt').forEach((x) => { x.style.opacity = (1 - E.out(lp(b, 17.2, .6))).toFixed(3); });
        el.style.transform = 'translate(-50%,-50%) translateY(' + ((1 - inP) * 40).toFixed(1) + 'px)';
        el.querySelectorAll('.ln').forEach((x) => { x.style.overflow = 'visible'; });
      }, tag: 'num' + i
    });
  });
  txt(14, 17.3, [['eb', 'Overview · 近 30 天']], { x: 960, y: 330, align: 'c' });
  at(13.1, () => { app(0).go('overview'); solo(0, '.tiles'); });
  drive(0, 13.1, 19.3, (p, b, D) => D.querySelectorAll('.tiles svg.vz-spark').forEach((s, i) => drawSpark(s, i === 1 ? 0 : E.inOut(lp(b, 18.2, 1.1)))));
  drive(0, 13.1, 19.4, (p, b, D) => D.querySelectorAll('.tiles .vz-kpi .v').forEach((v, i) => {
    if (v.dataset.count) v.textContent = Number(v.dataset.count).toLocaleString('en-US', { maximumFractionDigits: 1 });
    v.style.opacity = i < 3 ? E.inOut(lp(b, 18.85, .3)).toFixed(3) : '';
  }));
  tween(0, 17.4, 1.6, () => framing(0, '.tiles', TILES.box), E.inOut, (T) => ({ s: T.s * .96, o: 0, bl: 4 }));
  // the 协作时长 tile: its line runs forward
  tween(0, 19.1, 1.6, () => framing(0, '.tiles > .vz-kpi:nth-child(2)', [960, 560, 1400, 700], { max: 8 }), E.inOut);
  drive(0, 19.8, 22.6, (p, b, D) => drawSpark(D.querySelectorAll('.tiles svg.vz-spark')[1], E.inOut(p)));
  tween(0, 20.7, 2.5, () => ({ s: decks[0].C.s * 1.05, ax: decks[0].C.ax - 60 }), E.sine);
  txt(19.8, 22.8, [['eb', '协作时长 · 近 12 周 · ▲ 13%']], { x: 960, y: 120, align: 'c' });
  tween(0, 22.8, 1, () => OUT.toL(decks[0].C), E.in);

  // --- keep moving right: the trend chart slides in and its bars grow one by one
  const trend = byText('.card.pad', 'Agent 使用趋势');
  const bars = (D) => { const c = trend(D); return c && c.querySelector('svg.vz-t-bar'); };
  at(22.4, () => { const a = app(1); a.S.ov.stack = 'stacked'; a.go('overview'); solo(1, trend); });
  drive(1, 22.45, 27.6, (p, b, D) => { const s = bars(D); if (s) growBars(s, b, 23.2, .12, .55); });
  tween(1, 22.9, 1.2, () => framing(1, bars, [960, 560, 1700, 820], { max: 6, px: .2, zoom: 1.55 }), E.quart, IN.fromR);
  tween(1, 24.1, 3, () => framing(1, bars, [960, 560, 1700, 820], { max: 6, px: .82, zoom: 1.55 }), E.inOut);
  txt(23.4, 26.9, [['eb', '每日会话 · 按 Agent 堆叠']], { x: 960, y: 120, align: 'c' });
  tween(1, 27.1, 1.5, () => framing(1, trend, [1250, 540, 1060, 820]), E.inOut);
  txt(27.7, 29.6, [['eb', 'Agents'], ['gap'], ['hv sv', '五个 Agent'], ['md acc', '一张图对齐']], { x: L, y: 540 });
  tween(1, 29.5, 2, () => ({ rz: -75, s: decks[1].C.s * .55, o: 0, bl: 6, ax: 900 }), E.inOut);

  // ===== 01 · Analysis: the persona compass =====
  // the 16 types: three slow ones with their story, twelve that flick past faster and slower, then yours
  const SEQ = [['DPMV', 32.5, 2], ['SPFV', 34.5, 1.5], ['SIFT', 36, 1.25]];
  const FAST = ['DPFT', 'SIMT', 'DIFV', 'SPMT', 'DPMT', 'SIMV', 'DIFT', 'SPFT', 'DPFV', 'SIFV', 'SPMV', 'DIMT'];
  const FD = [.6, .5, .4, .32, .28, .26, .26, .28, .34, .42, .55, .75];
  let fb = 37.25; FAST.forEach((c, i) => { SEQ.push([c, fb, FD[i]]); fb += FD[i]; });
  const LAND = 42.25; SEQ.push(['ME', LAND, 4]);
  const stOf = (code) => { const D = compassData(); return code === 'ME' ? { v: D.me.v, hrs: D.hrs, hd: D.hd } : { v: archetype(code), hrs: rhythm(code), hd: headingOf(code) }; };
  const seqAt = (b) => { let i = 0; while (i + 1 < SEQ.length && b >= SEQ[i + 1][1]) i++; return i; };
  const rotAt = (b) => b < 37.25 ? 0 : b < 42.6 ? 1080 * E.inOut(lp(b, 37.25, 5.35)) : 6 * Math.sin((b - 42.6) * 4) * Math.exp(-(b - 42.6) * 1.6);
  drive(2, 29.4, 46.6, (p, b) => {
    const i = seqAt(b), cur = SEQ[i], prev = SEQ[Math.max(0, i - 1)];
    const m = Math.min(.5, cur[2] * .7), f = b < SEQ[0][1] ? 1 : E.inOut(lp(b, cur[1], m));
    const st = mixState(stOf(i ? prev[0] : cur[0]), stOf(cur[0]), f);
    st.lit = 1; st.mine = cur[0] === 'ME';
    if (st.mine) { st.lit = {}; 'DIMV'.split('').forEach((c, k) => { st.lit[c] = E.out(lp(b, 42.6 + k * .25, .3)); }); }
    st.sweep = E.inOut(lp(b, 30, 2.5));
    st.grow = b < LAND - .3 ? E.out(lp(b, 31.6, 1)) : b < LAND + .1 ? lerp(1, .35, E.inOut(lp(b, LAND - .3, .4))) : lerp(.35, 1, E.out(lp(b, LAND + .1, 1.1)));
    st.hd += rotAt(b); st.orbit = (b - 29.5) * 34 + rotAt(b) * .3; st.needle = E.out(lp(b, 32.2, .8)); st.settle = lp(b, LAND + .4, 1.6);
    drawCompass(st);
  });
  tween(2, 29.5, 2.4, () => framing(2, 'all', [600, 540, 860, 860]), E.inOut, (T) => ({ rx: 64, rz: 30, s: T.s * .7, o: 0, bl: 5 }));
  tween(2, 31.7, 5.4, () => ({ rz: -4, s: decks[2].C.s * 1.03 }), E.sine);
  glowAt(29.5, .3, 2);
  txt(30.4, 32.3, [['eb', '01 · Analysis'], ['gap'], ['hv sv', '16 种协作人格'], ['md acc', '4 个维度 · 8 个极']], { x: R, y: 540, align: 'r' }, { st: .2 });
  at(29.4, () => compassData());
  SEQ.slice(0, 3).forEach(([code, b, d]) => {
    const T = compassData.cache || null;
    txt(b + .12, b + d - .02, [['eb', code.split('').join(' ')], ['gap'], ['hv sv', '<span data-name="' + code + '"></span>'], ['md', '<span class="serif dim" data-en="' + code + '"></span>'], ['gap'], ['lt', '<span data-d1="' + code + '"></span>'], ['lt', '<span data-d2="' + code + '"></span>']], { x: R, y: 540, align: 'r' }, {
      st: .1, inB: .8, outB: .35, tick: (el) => fillType(el, code)
    });
  });
  // the fast flicks: one caption that swaps with the dial, a counter of how many you have seen
  tween(2, 37.05, 1, () => framing(2, 'all', [900, 530, 980, 980]), E.inOut);
  txt(37.25, LAND - .05, [['eb', '<span class="flick-n"></span> / 16'], ['md', '<span class="flick"></span>']], { x: 1850, y: 540, align: 'r' }, {
    inB: .4, outB: .2, tick: (el, tl, life, t) => {
      const b = t / BEAT, i = seqAt(b), code = SEQ[i][0]; if (code === 'ME') return;
      if (el.dataset.c !== code) { const D = compassData(); el.dataset.c = code; el.querySelector('.flick').innerHTML = '<span class="mono">' + code + '</span> ' + D.TYPES[code][0]; el.querySelector('.flick-n').textContent = String(i + 1).padStart(2, '0'); el._t = t; }
      const k = E.out(clamp((t - el._t) / (.18 * BEAT))); const fl = el.querySelector('.flick');
      fl.style.opacity = k.toFixed(3); fl.style.transform = 'translateY(' + ((1 - k) * 18).toFixed(1) + 'px)';
    }
  });
  // landing on yours: the petals fold in and bloom again with your real values, the four letters light up
  tween(2, LAND + .2, 1.6, () => framing(2, 'all', [600, 540, 860, 860]), E.inOut);
  glowAt(LAND, .7, 1.5);
  txt(LAND + .8, 45.9, [['eb', '你的类型 · Your type'], ['gap'], ['xl sv', '<span class="serif">DIMV</span>'], ['md', '指挥家 <span class="serif acc"><i>The Conductor</i></span>'], ['gap'], ['lt', '整段交出，多线并进，'], ['lt', '亲自验收。'], ['gap'], ['eb', '委托 72 · 即兴 61 · 多线 73 · 求证 67']], { x: R, y: 540, align: 'r' }, { st: .12 });
  tween(2, 46, 1.2, () => OUT.far(decks[2].C), E.in);
  glowAt(46, 0, 1.2);

  // ===== 02 · Recommend: twelve suggestions, the hours they save, then a one-click install =====
  const rcards = (D) => [...D.querySelectorAll('.rcard')];
  const SAVE = [];                                          // hours per card, read from the cards themselves
  const RECB = 46.4, RECG = .45;                            // card i arrives at RECB + i·RECG
  at(45.7, () => {
    const a = app(0); a.go('recs'); solo(0, (D) => D.querySelector('.rcard').parentElement);
    // the cards count their own numbers up, so read the target value, not the text
    rcards(a.D).forEach((c) => { const n = c.querySelector('[data-count]'), m = c.textContent.match(/≈\s*[\d.]+\s*(h|min)/); SAVE.push(n ? +n.dataset.count / (m && m[1] === 'min' ? 60 : 1) : 0); });
  });
  drive(0, 45.75, 52.6, (p, b, D) => {
    const cs = rcards(D);
    cs.forEach((c, i) => { const q = E.out(lp(b, RECB + i * RECG, .6)); c.style.opacity = q.toFixed(3); c.style.transform = 'translateX(' + ((1 - q) * 70).toFixed(1) + 'px)'; });
    const ct = D.querySelector('#content'); if (ct && cs[0]) { const step = cs[1].offsetTop - cs[0].offsetTop || 178; ct.scrollTop = Math.max(0, (b - RECB) / RECG - 2.4) * step * .92; }
  });
  tween(0, 46, 1.4, () => framing(0, [(D) => rcards(D)[0], (D) => rcards(D)[2]], [1250, 540, 860, 980], { max: 2.2 }), E.quart, IN.rise);
  txt(46.3, 51.9, [['eb', '02 · Recommend'], ['gap'], ['xl sv', '<span class="cnt">0.0</span><span style="font-size:.38em;letter-spacing:0"> h / 月</span>'], ['md acc', '每月省下的时间'], ['gap'], ['lt', '<span class="cnt-n">0</span> / 12 条建议 · 按节省时间排序']], { x: L, y: 540 }, {
    st: .15, tick: (el, tl, life, t) => {
      const b = t / BEAT; let sum = 0, n = 0;
      SAVE.forEach((h, i) => { const q = E.out(lp(b, RECB + i * RECG + .25, .5)); sum += h * q; if (q > .5) n++; });
      el.querySelector('.cnt').textContent = sum.toFixed(1); el.querySelector('.cnt-n').textContent = n;
    }
  });
  tween(0, 51.8, .9, () => OUT.up(decks[0].C), E.in);
  // the top suggestion: preview → write → done, each a click
  const recDetail = (D) => smallest(D, '#main .card', '每月节省');
  at(51.3, () => { const a = app(1); a.go('recs'); const d = recDetail(a.D); const btn = d && d.querySelector('[data-act="install"]'); if (btn) btn.click(); solo(1, '#modal'); });
  tween(1, 52, 1.3, () => framing(1, '#modal', [1250, 540, 1020, 820]), E.quart, IN.rise);
  tween(1, 53.3, 4.5, () => ({ s: decks[1].C.s * 1.04 }), E.sine);
  txt(52.4, 57.7, [['eb', 'Install'], ['gap'], ['hv sv', '预览，再写入'], ['md acc', '一键安装 · 随时撤销'], ['gap'], ['lt', '装上之后，追踪 7 天效果']], { x: L, y: 540 }, { st: .3 });
  clickAt(1, 54.4, '#modal .btn.p', (a, el) => a.click(el));
  clickAt(1, 56, '#modal .btn.p', (a, el) => a.click(el));
  tween(1, 57.8, .9, () => OUT.up(decks[1].C), E.in);

  // ===== 03 · Trajectory: follow the playhead through the phases of one session =====
  const tlsvg = '.tl-card svg.vz-t-timeline';
  at(57.5, () => { app(0).go('sessions'); solo(0, '.tl-card'); });
  tween(0, 58, 2, () => framing(0, '.tl-card', [1310, 540, 1040, 900]), E.quart, IN.plane);
  txt(58.4, 60.6, [['eb', '03 · Trajectory'], ['gap'], ['hv sv', '卡在哪一刻'], ['md acc', '逐秒回放，一眼看清']], { x: L, y: 540 }, { st: .25, outB: .5 });
  // the promo drives the replay itself: the playhead runs the whole session from its start in these four beats
  drive(0, 59.6, 63.6, (p, b, D) => { const a = app(0); if (a.S.sess.playing) a.W.eval('stopPlay()'); a.S.sess.ph = a.W.eval('traj(BYID[S.sess.sel]).T') * E.inOut(lp(b, 59.8, 3.6)); a.W.eval('tlFrame(true)'); });
  tween(0, 60.1, 1.4, () => framing(0, tlsvg, [1250, 500, 1300, 700], { max: 4, px: .18 }), E.inOut);
  drive(0, 61.5, 63.6, (p, b, D) => {                       // the camera rides with the playhead
    const ph = D.querySelector(tlsvg + ' .vz-playhead'); if (!ph) return;
    const r = ph.getBoundingClientRect(); decks[0].C.x = lerp(decks[0].C.x, r.left + 30, .12);
  });
  const PHASE = { '探索': ['读代码，找入口', ''], '规划': ['拆成 5 步', ''], '实施': ['纠偏 2 次', 'warn'], '部署': ['同一命令连续失败 4 次', 'crit'], '验证': ['上线验证通过 · 42 分钟', 'good'] };
  txt(60.8, 63.7, [['md sv', '<span class="ph-n"></span>'], ['lt', '<span class="ph-d"></span>']], { x: L, y: 860 }, {
    inB: .5, outB: .3, tick: (el, tl, life, t) => {
      const D = decks[0].D, svg = D && D.querySelector(tlsvg), ph = svg && svg.querySelector('.vz-playhead'); if (!ph) return;
      const px = ph.getBoundingClientRect().left; let cur = '探索';
      [...svg.querySelectorAll('text')].filter((x) => PHASE[x.textContent]).forEach((x) => { if (x.getBoundingClientRect().left - 14 <= px) cur = x.textContent; });
      if (el.dataset.p !== cur) { el.dataset.p = cur; el.querySelector('.ph-n').textContent = cur; const d = el.querySelector('.ph-d'); d.textContent = PHASE[cur][0]; d.className = 'ph-d ' + PHASE[cur][1]; el._t = t; }
      const k = E.out(clamp((t - (el._t || 0)) / (.25 * BEAT))); el.querySelectorAll('.ln>span').forEach((s) => { s.style.transform = 'translateY(' + ((1 - k) * 40).toFixed(1) + '%)'; s.style.opacity = k.toFixed(3); });
    }
  });
  const inspector = (D) => [...D.querySelectorAll('.tl-card div')].filter((e) => e.textContent.includes('事件检视') && e.getBoundingClientRect().width < 360).sort((a, b) => a.textContent.length - b.textContent.length).pop();
  tween(0, 63.6, 1.4, () => framing(0, inspector, [760, 560, 900, 620], { max: 3 }), E.inOut);
  txt(63.9, 65.9, [['hv sv', '每次失败'], ['md acc', '都留有现场']], { x: R, y: 540, align: 'r' }, { st: .25 });
  tween(0, 66, .9, () => OUT.up(decks[0].C), E.in);

  // ===== insight → studio: the review turns into a fix the local agent writes =====
  shot(1, 66.2, 70.6, { sel: byText('.card.pad.col', '这次会话的启示'), box: [1300, 540, 700, 860], inn: 'rise', out: 'up', prep: (a) => a.go('sessions') });
  txt(66.5, 70.6, [['eb', 'Insight'], ['gap'], ['hv sv', '下次怎么做'], ['md acc', '复盘直接给出改法']], { x: L, y: 540 }, { st: .3 });
  clickAt(1, 69.4, (D) => smallest(D, '.card.pad.col button', '生成规则'), () => {});
  const runCard = (D) => D.querySelectorAll('#main .card.pad.col')[1];
  const skillCard = (D) => smallest(D, '#main .card.col', 'SKILL.md');
  at(70.2, () => { const a = app(0); a.go('studio'); a.click('[data-act="studioStart"]'); solo(0, [runCard, skillCard]); });
  tween(0, 70.8, 1.3, () => framing(0, runCard, [1250, 540, 900, 860]), E.quart, IN.rise);
  txt(71.2, 74.8, [['eb', 'Studio'], ['gap'], ['hv sv', '交给本地 Agent'], ['md acc', '生成 Skill、Hook 与规则']], { x: L, y: 540 }, { st: .3 });
  drive(0, 74.6, 76.6, (p, b, D) => { const ct = D.querySelector('#content'), sk = skillCard(D); if (ct && sk) { if (ct._s0 == null) { ct._s0 = ct.scrollTop; ct._s1 = Math.max(0, sk.offsetTop - 120); } ct.scrollTop = lerp(ct._s0, ct._s1, E.inOut(lp(b, 74.8, 1.6))); } });
  tween(0, 76.4, 1.2, () => framing(0, skillCard, [1220, 540, 1040, 880], { max: 2.2 }), E.inOut);
  drive(0, 75.6, 79.9, (p, b, D) => { const c = runCard(D); if (c) c.style.opacity = (1 - E.inOut(lp(b, 75.8, .9))).toFixed(3); });
  txt(76, 78.8, [['hv sv', '边写边验'], ['md acc', '自检 · 回放 dry-run · 第二视角评分']], { x: L, y: 540 }, { st: .25 });
  tween(0, 78.9, .9, () => OUT.up(decks[0].C), E.in);

  // ===== 04 · Ask the local agent (build) =====
  shot(1, 79, 86.5, { sel: '#modal', box: [1310, 560, 980, 760], inn: 'rise', inDur: 1.4, out: 'near', outDur: 1, push: 1.14, prep: (a) => { a.go('overview'); a.W.openAsk('overview'); } });
  clickAt(1, 80.4, '[data-act="askPick"]', (a, el) => a.click(el));
  glowAt(79, .5, 2);
  txt(79.5, 86.5, [['eb', '04 · Ask'], ['gap'], ['hv sv', '问你自己的'], ['hv ai', '本地 Agent'], ['gap'], ['lt', '数据不出本机 · 0 B 上传']], { x: L, y: 540 }, { st: .5 });
  glowAt(86, 0, 1.5);

  // ===== seven features, two beats each (急), each with its own small interaction =====
  const feat = (i, sel, word, sub, prep, o = {}) => {
    const b = 87 + i * 2, right = i % 2 === 0, d = i % 2;
    shot(d, b - .3, b + 1.75, Object.assign({ sel, box: o.box || (right ? [1330, 540, 920, 760] : [590, 540, 920, 760]), inn: right ? 'fromR' : 'fromL', inDur: .8, out: 'far', outDur: .45, prep, lead: o.lead || .3, push: 1.03 }, o));
    txt(b + .35, b + 1.75, [['hv sv', word], ['lt acc', sub]], o.tpos || (right ? { x: L, y: 540 } : { x: R, y: 540, align: 'r' }), { inB: .7, outB: .45, st: .12 });
    return b;
  };
  let b0 = feat(0, trend, '深色模式', '跟随系统外观', (a) => { a.S.ov.stack = 'stacked'; a.go('overview'); });
  at(b0 + .9, () => app(0).W.setTheme('dark'));
  b0 = feat(1, '.edsw', 'Lite / Advance', '一键切换 · ⌃⌘L', (a) => { a.W.closeModal(); a.go('overview'); }, { box: [960, 400, 1000, 300], max: 4, tpos: { x: 960, y: 700, align: 'c' } });
  clickAt(1, b0 + .9, '[data-act="edition"][data-v="lite"]', (a) => a.W.edSet('lite'));
  b0 = feat(2, '#notes .nt', '第一时间提醒', '会话等你确认时', (a) => { a.W.setTheme('light'); a.go('overview'); a.D.querySelectorAll('#notes .nt').forEach((n) => n.remove()); a.W.simEvent('waiting'); }, { max: 3, lead: .5 });
  clickAt(0, b0 + 1.1, '#notes .nt [data-act="noteAct"]', () => {});
  b0 = feat(3, '#modal', '⌘K', '任何页面、会话与操作', (a) => { a.W.edSet('advance'); a.W.openPalette(); }, { lead: .5 });
  drive(1, b0 + .3, b0 + 1.2, (p, b, D) => { const q = D.querySelector('#palQ'); if (!q) return; const s = '部署'.slice(0, Math.floor(E.lin(p) * 2.99)); if (q.value !== s) { q.value = s; q.dispatchEvent(new Event('input', { bubbles: true })); } });
  b0 = feat(4, '#hud', '悬浮组件', '会话运行时，陪在桌面一角', (a) => { a.S.hud.show = true; a.S.sim = 'running'; a.render(); }, { max: 3.2 });
  clickAt(0, b0 + .8, '#hudPill', (a, el) => a.click(el));
  feat(5, '#widgets', '桌面小组件', '人格 · 今日 · 本周 · 最值得做', (a) => { a.W.closeModal(); a.S.widgets = true; a.go('overview'); });
  feat(6, '#pop', '菜单栏面板', '所有会话的状态，一眼看清', (a) => { a.S.hud.show = false; a.S.hud.open = false; a.S.widgets = false; a.S.pop = true; a.render(); }, { out: 'far', max: 2.2 });

  // ===== close on your compass (缓) =====
  drive(2, 100.4, 108.6, (p, b) => {
    const st = stOf('ME'); st.sweep = 1; st.lit = 1; st.mine = true; st.grow = 1 + .025 * Math.sin((b - 101) * 1.6);
    st.orbit = 0; st.settle = 1; st.hd += 5 * Math.sin((b - 101) * 1.3) * Math.exp(-(b - 101) * .4);
    st.dial = 1 - E.inOut(lp(b, 104.4, 1.6)); st.needle = st.dial; st.planets = 1 - E.inOut(lp(b, 106, 1.2));
    drawCompass(st);
  });
  tween(2, 101, 2.4, () => framing(2, 'all', [960, 500, 800, 800]), E.quart, IN.depth);
  tween(2, 103.4, 1, () => ({ s: decks[2].C.s * 1.02 }), E.sine);
  tween(2, 104.2, 2.4, () => ({ rx: 64 }), E.inOut);
  tween(2, 106.4, 1.6, () => ({ o: 0, bl: 6 }), E.inOut);
  glowAt(101, .6, 3);
  txt(101.8, 105, [['row md', ['<span>只读本地日志</span>', '<span class="acc">数据不出本机</span>']], ['gap'], ['eb', 'local-first · 0 B uploaded']], { x: 960, y: 985, align: 'c' }, { st: .4 });
  glowAt(106, 0, 1);

  // --- end card
  glowAt(107.5, .9, 3);
  txt(109.4, 119.6, [['word', 'Orbit']], { x: 960, y: 690, align: 'c' }, { inB: 1.5, outB: 2 });
  txt(111, 119.6, [['lt', '看见你与 Agent 的每一次协作']], { x: 960, y: 790, align: 'c' }, { inB: 1.5, outB: 2 });
  txt(113, 119.6, [['eb', 'for macOS · ActionMesh AI']], { x: 960, y: 865, align: 'c' }, { inB: 1.5, outB: 2 });
  glowAt(117, 0, 2.5);
}
// a type card's name, English name and description, from the app's TYPES
function fillType(el, code) {
  if (el.dataset.f) return; const D = compassData(); const T = D.TYPES[code]; if (!T) return; el.dataset.f = 1;
  const d = split2(T[2]);
  el.querySelector('[data-name]').textContent = T[0]; el.querySelector('[data-en]').innerHTML = '<i>' + T[1] + '</i>';
  el.querySelector('[data-d1]').textContent = d[0]; el.querySelector('[data-d2]').textContent = d[1] || '';
}

/* ---------- clock & frame loop ---------- */
const PROMO = window.PROMO = { ready: false, duration: END * BEAT, t: 0 };
let t0 = null, offset = 0, audio = null, actx = null;
function now() {
  if (actx && audio) return actx.currentTime - audio.start + offset;
  return t0 == null ? 0 : (performance.now() - t0) / 1000 + offset;
}
function step(tt) {
  const t = tt ?? now(); PROMO.t = t;
  for (const c of cues) if (!c.done && t >= c.b * BEAT) { c.done = true; try { c.fn(); } catch (e) { console.error('cue @' + c.b, e); } }
  // the app re-renders on clicks and route changes: re-mark the solo component when its element was replaced
  for (const k of decks) if (k.solo && k.D) for (const s of Array.isArray(k.solo) ? k.solo : [k.solo]) { const el = find(k.i, s); if (el && !el.classList.contains('promo-solo')) el.classList.add('promo-solo'); }
  applyDrives(t); applyCams(t); applyCursors(t); orbitAt(t / BEAT); applyFx(t); applyGlow(t);
}
// Pin every CSS animation/transition (here and in both app copies) to the virtual clock: each one is paused and its
// currentTime set from the moment it was first seen; finished ones are finished explicitly so the end events still fire.
const SEEN = new WeakMap();
function syncAnims() {
  const n = performance.now();
  for (const doc of [document, decks[0].D, decks[1].D]) {
    if (!doc) continue;
    for (const a of doc.getAnimations()) {
      if (a.playState === 'finished') continue;
      let s = SEEN.get(a); if (s === undefined) { s = n - (a.currentTime || 0); SEEN.set(a, s); }
      const el = (n - s) * (a.playbackRate || 1), tm = a.effect && a.effect.getComputedTiming();
      if (tm && isFinite(tm.endTime) && el >= tm.endTime) { a.finish(); continue; }
      a.pause(); a.currentTime = el;
    }
  }
}
PROMO.start = (from = 0) => {
  offset = from; t0 = performance.now();
  for (const c of cues) if (c.b * BEAT < from) { c.done = true; try { c.fn(); } catch (e) { console.error(e); } }
  if (!RENDER) (function loop() { step(); requestAnimationFrame(loop); })();
};
PROMO.sync = (t) => { step(t); syncAnims(); };
function fit() { if (RENDER) return; const k = Math.min(innerWidth / 1920, innerHeight / 1080); stage.style.transform = 'scale(' + k + ')'; }
addEventListener('resize', fit); fit();
if (RENDER) document.documentElement.classList.add('render');
let loaded = 0;
decks.filter((k) => k.frame).forEach((k) => k.frame.addEventListener('load', () => {
  k.W = k.frame.contentWindow; k.D = k.frame.contentDocument;
  const st = k.D.createElement('style'); st.textContent = PROMO_CSS; k.D.head.appendChild(st);
  if (RENDER) k.D.startViewTransition = undefined;              // view transitions run off the virtual clock
  const S = k.W.eval('S'); S.widgets = false; S.hud.show = false; k.W.render();
  k.D.querySelectorAll('#notes .nt').forEach((n) => n.remove());
  if (++loaded < 2) return;
  script(); tweens.sort((a, b) => a.b - b.b); cues.sort((a, b) => a.b - b.b); step(0);
  if (DEBUG) { const d = document.createElement('div'); d.className = 'dbg'; stage.appendChild(d); setInterval(() => { d.textContent = 'b' + (PROMO.t / BEAT).toFixed(2); }, 50); }
  PROMO.ready = true;
}));
$('#play').addEventListener('click', async () => {
  $('#play').remove();
  const from = +(new URLSearchParams(location.search).get('t') || 0);
  try {
    actx = new AudioContext();
    const buf = await (await fetch('out/soundtrack.wav')).arrayBuffer();
    const src = actx.createBufferSource(); src.buffer = await actx.decodeAudioData(buf); src.connect(actx.destination);
    audio = { start: actx.currentTime + .1 }; src.start(audio.start, from);
    PROMO.start(from);
  } catch (e) { console.warn('no soundtrack, playing silent', e); actx = null; audio = null; PROMO.start(from); }
});

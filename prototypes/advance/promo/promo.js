/* Orbit promo: a beat-locked timeline. Two live copies of the app take turns showing ONE component each (everything
   else in that copy is hidden), framed by a virtual camera next to the copy that explains it. Transitions overlap the
   outgoing and incoming component with long eases; there are no beat-synced shakes or flashes.
   Everything is a pure function of the master time t (seconds), so the page plays in real time with the soundtrack
   (preview) or frame by frame on Playwright's fake clock (render.mjs). Times are written in beats. */
'use strict';
const BPM = 132, BEAT = 60 / BPM;                         // beats; music.py uses the same grid
let END = 88;                                             // length in beats of the closing scene, in its own beats (it sets it)
/* v17.3: every scene file is written in its own beats (= film beats before v17.3). SHIFT[scene] (beats) pushes everything
   that scene registers later: tween / txt / tag / drive / at / clickAt / markAt and every AGD call (key, follow, pulse,
   link, bubble, glow, back, chat). Callbacks (drive, markAt, ticks, AGD live params, AGD follow / back / link targets /
   bubble offsets / chat from / to) receive the scene's own beats; while one runs, CTX_SH holds its shift, so AGD.pos(i, b)
   and AGD.centroid(b) called inside it read b in that scene's beats too. music.py carries the same table. */
const SHIFT = { '10-intro': 0, '15-redesign': 6.9, '20-orbit': 11.3, '30-persona': 16.9, '40-recs': 22.9, '50-tools': 31.7, '60-close': 37.7 };
let SH = 0, CTX_SH = 0;
// run f with the callback context of a scene shifted by sh (AGD.pos / centroid inside read that scene's beats)
function inCtx(sh, f) { const p = CTX_SH; CTX_SH = sh; try { return f(); } finally { CTX_SH = p; } }
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
const stage = $('#stage'), fxEl = $('#fx');

/* ---------- the two app copies ("decks") and their cameras ---------- */
// x,y: the app point (frame px) put at screen point (ax, ay); s: zoom; rx/ry/rz: tilt around (ax, ay); z: dolly;
// o: opacity; bl: blur; mx/my: directional (motion) blur in px along x / y, for whips. Tweens start from wherever the
// deck's camera is when they fire.
const ZERO = { x: 800, y: 500, s: 1, ax: 960, ay: 540, rx: 0, ry: 0, rz: 0, z: 0, o: 0, bl: 0, mx: 0, my: 0 };
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
function tween(d, b, dur, to, ease = E.inOut, from = null) { tweens.push({ d, b: b + SH, dur, to, ease, from }); }
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
    const f = [];
    if ((c.mx || 0) > .3 || (c.my || 0) > .3) { mblur(k.i).setAttribute('stdDeviation', (c.mx || 0).toFixed(1) + ' ' + (c.my || 0).toFixed(1)); f.push('url(#mb' + k.i + ')'); }
    if (c.bl > .05) f.push('blur(' + c.bl.toFixed(2) + 'px)');
    k.cam.style.filter = f.length ? f.join(' ') : 'none';
    k.cam.style.visibility = c.o < .002 ? 'hidden' : 'visible';
  }
}
// one directional-blur filter per deck (CSS blur() is round; a whip needs blur along its direction only)
function mblur(i) {
  let g = document.getElementById('mb' + i);
  if (!g) {
    let svg = document.getElementById('mbDefs');
    if (!svg) { svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.id = 'mbDefs'; svg.setAttribute('width', '0'); svg.setAttribute('height', '0'); svg.style.position = 'absolute'; stage.appendChild(svg); }
    const fl = document.createElementNS('http://www.w3.org/2000/svg', 'filter'); fl.id = 'mb' + i; fl.setAttribute('x', '-20%'); fl.setAttribute('y', '-20%'); fl.setAttribute('width', '140%'); fl.setAttribute('height', '140%');
    g = document.createElementNS('http://www.w3.org/2000/svg', 'feGaussianBlur'); fl.appendChild(g); svg.appendChild(fl);
  }
  return g;
}

/* ---------- type ---------- */
// txt(b0, b1, lines, pos): lines = [[cls, html], …] ('gap' for a spacer); pos = {x, y, align: 'l'|'c'|'r'}.
// Lines rise through a mask one after another (o.st beats apart) and leave together, drifting up.
const fx = [];
function txt(b0, b1, lines, pos, o = {}) {
  const html = lines.map(([c, h]) => (c === 'gap' ? '<div class="gap"></div>' : Array.isArray(h) ? '<div class="' + c + '">' + h.map((w) => '<span class="ln"><span>' + w + '</span></span>').join('') + '</div>' : '<span class="ln ' + c + '"><span>' + h + '</span></span>')).join('');
  const al = pos.align || 'l';
  const style = 'left:' + pos.x + 'px;top:' + pos.y + 'px;text-align:' + ({ l: 'left', c: 'center', r: 'right' })[al] + (o.style ? ';' + o.style : '');
  fx.push({ sh: SH, b0: b0 + SH, b1: b1 + SH, html, style, base: 'translate(' + ({ l: '0', c: '-50%', r: '-100%' })[al] + ',-50%)', anim: o.anim || mask(o.st ?? .18, o.inB || 1, o.outB || .6, o.spread), tick: o.tick, tag: o.tag, el: null });
}
function mask(st, inB, outB, spread) {
  return (el, tl, life) => {
    const q = E.inOut(clamp((life - tl) / (outB * BEAT)));
    el.querySelectorAll('.ln>span').forEach((s, i) => {
      const p = E.expo(clamp((tl - i * st * BEAT) / (inB * BEAT)));
      s.style.transform = 'translateY(' + ((1 - p) * 130 - (1 - q) * 30).toFixed(2) + '%)';
      s.style.opacity = (Math.min(1, p * 1.4) * q).toFixed(3);
      s.style.filter = q < .999 ? 'blur(' + ((1 - q) * 8).toFixed(1) + 'px)' : 'none';
      if (spread) s.style.letterSpacing = q < .999 ? ((1 - q) * .45).toFixed(3) + 'em' : '';   // the words drift apart as they leave
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
    if (f.el) { const ts = t - f.sh * BEAT; inCtx(f.sh, () => { f.anim(f.el, t - t0, t1 - t0, ts); if (f.tick) f.tick(f.el, t - t0, t1 - t0, ts); }); }
  }
}

/* ---------- app control ---------- */
const cues = [];
function at(b, fn) { cues.push({ b: b + SH, sh: SH, fn, done: false }); }
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
const PROMO_CSS = 'html,body,.desk{background:transparent!important}.desk .wall{display:none!important}.tip{display:none!important}' +
  'html body *{visibility:hidden!important}html body .promo-solo,html body .promo-solo *{visibility:visible!important}' +
  'html body .promo-solo:not(svg){box-shadow:0 0 0 .5px rgba(255,255,255,.14),0 30px 90px rgba(0,0,0,.55)!important}' +
  '.promo-card{background:var(--surface)!important;border-radius:12px;box-shadow:0 0 0 22px var(--surface),0 30px 90px 22px rgba(0,0,0,.55)!important}' +
  '.promo-solo [hidden]{visibility:hidden!important}:root{color-scheme:light!important}';

/* ---------- drivers: per-frame changes to the app's own charts, as functions of the beat ---------- */
// drive(d, b0, b1, fn): fn(p, b, D) runs every frame from b0 until it has run once with p = 1
const drives = [];
function drive(d, b0, b1, fn) { drives.push({ d, b0: b0 + SH, b1: b1 + SH, sh: SH, fn, fin: false }); }
function applyDrives(t) {
  const b = t / BEAT;
  for (const x of drives) {
    if (x.fin || b < x.b0) continue;
    const D = decks[x.d].D; if (!D && !decks[x.d].virtual) continue;
    const p = clamp((b - x.b0) / (x.b1 - x.b0));
    try { inCtx(x.sh, () => x.fn(p, b - x.sh, D)); } catch (e) { console.error('drive @' + x.b0, e); x.fin = true; }
    if (p >= 1) x.fin = true;
  }
}
const SVGNS = 'http://www.w3.org/2000/svg';
const lp = (b, b0, dur) => clamp((b - b0) / dur);          // local progress of a staggered item

/* ---------- tags: text attached to a component, inside its copy of the app ----------
   A tag lives in the deck's rig, so it tilts, turns and slides with the component it describes; it is anchored to one
   edge of that component (top / bottom / left / right, plus an along-edge share) and counter-scaled by the camera so
   its type keeps its size on screen. This is what keeps words and components from ever overlapping. */
const tags = [];
function tag(d, b0, b1, sel, side, lines, o = {}) {
  const html = lines.map(([c, h]) => (c === 'gap' ? '<div class="gap"></div>' : '<span class="ln ' + c + '"><span>' + h + '</span></span>')).join('');
  tags.push({ d, sh: SH, b0: b0 + SH, b1: b1 + SH, sel, side, html, o, el: null, anim: o.anim || mask(o.st ?? .14, o.inB || .9, o.outB || .5) });
}
function applyTags(t) {
  for (const g of tags) {
    const t0 = g.b0 * BEAT, t1 = g.b1 * BEAT, live = t >= t0 && t < t1, k = decks[g.d];
    if (live && !g.el) { g.el = document.createElement('div'); g.el.className = 'k tag ' + g.side; g.el.innerHTML = g.html; k.rig.appendChild(g.el); }
    if (!live && g.el) { g.el.remove(); g.el = null; }
    if (!g.el) continue;
    const r = rectOf(g.d, g.sel), s = 1 / k.C.s * (g.o.scale || 1), gap = (g.o.gap ?? 26) / k.C.s, al = g.o.at ?? 0;
    let x, y, tr;
    if (g.side === 'top') { x = r.x + r.w * al; y = r.y - gap; tr = 'translate(' + (-al * 100) + '%,-100%)'; }
    else if (g.side === 'bottom') { x = r.x + r.w * al; y = r.y + r.h + gap; tr = 'translate(' + (-al * 100) + '%,0)'; }
    else if (g.side === 'left') { x = r.x - gap; y = r.y + r.h * (g.o.at ?? .5); tr = 'translate(-100%,-50%)'; }
    else { x = r.x + r.w + gap; y = r.y + r.h * (g.o.at ?? .5); tr = 'translate(0,-50%)'; }
    g.el.style.left = x.toFixed(1) + 'px'; g.el.style.top = y.toFixed(1) + 'px';
    g.el.style.textAlign = g.side === 'left' ? 'right' : al >= .99 ? 'right' : al > .01 && al < .99 ? 'center' : 'left';
    g.el.style.transformOrigin = g.side === 'left' ? '100% 50%' : g.side === 'right' ? '0 50%' : (al * 100) + '% ' + (g.side === 'top' ? '100%' : '0');
    g.el.style.transform = 'scale(' + s.toFixed(4) + ') ' + tr;
    const ts = t - g.sh * BEAT; inCtx(g.sh, () => { g.anim(g.el, t - t0, t1 - t0, ts); if (g.o.tick) g.o.tick(g.el, t - t0, t1 - t0, ts); });
  }
}

/* ---------- the persona compass (deck 2) ----------
   The app's Orbit 0.0.4 dial (fp2SVG in 41-a2-persona.js) on an 800 frame (app units × 2, centre 400), drawn from the
   app's own functions so it follows the app: a bezel ring with 128 ticks and, inside them, the 16 type codes (.tcode,
   SF Pro Rounded, Gray-code order, fpCodeLbls; the current type emphasised, the --orbit triangle outside the bezel
   pointing at it; no pole words); one independent curve per Agent (fpOrbit layers, all from one baseline, translucent
   muted fill + a thin edge, free to overlap); the Agent badges on the orbit FPG.PR at each Agent's mean direction
   (fpOrbit planets — the AGD dots ride exactly there, cpBadge); in the middle the persona flower (bloom / bloomParts:
   symmetric 3–6 petals, no lead petal), turned so a petal faces the type. A change of type (st.wave) plays
   38-bloom-motion.js: fold / unfold, curve morph, badge glide, triangle turn, emphasis hand-over. Colours: the app's
   dark theme on pure black. */
const CP = { C: 400, K: 2, R0: 210, RH: 108, RR: 160, PR: 344, PB: 18, BUD: .34, RING: 300 };   // FPG × 2 (R0 = FPG.R0 + 1, the curves' baseline)
const cpt = (r, deg) => [CP.C + r * Math.sin(deg * Math.PI / 180), CP.C - r * Math.cos(deg * Math.PI / 180)];
const f2 = (q) => q[0].toFixed(1) + ' ' + q[1].toFixed(1);
const CODES = Array.from({ length: 16 }, (_, i) => { const g = i ^ (i >> 1); return ['DS', 'IP', 'MF', 'VT'].map((p, k) => p[(g >> (3 - k)) & 1]).join(''); });   // = the app's FP_TYPES; CODES[0] = DIMV
const AGC = ['var(--a1)', 'var(--a2)', 'var(--a3)', 'var(--a4)', 'var(--a5)'];
// the app's dark theme: --ink-1…4, --fp-base (= --h2) / --fp-bo, --h4, --petal2
const CPC = { ink1: [242, 242, 244], ink2: '#c9c9ce', ink3: [154, 154, 160], ink4: '#66666c', base: '#4a4a50', bo: .45, h4: '#a8a8ae', petal2: '#5c5c63' };
const cpFill = (c) => 'color-mix(in oklab, ' + c + ' 42%, ' + CPC.base + ')';     // fpFill
const cpLine = (c) => 'color-mix(in oklab, ' + c + ' 52%, ' + CPC.h4 + ')';       // fpLine
const cpTypeDeg = (t) => (t + .5) * 22.5;
const cpDelta = (a, b) => ((b - a) % 360 + 540) % 360 - 180;                     // bmDelta: shortest signed arc
// CSS cubic-bezier easings of 38-bloom-motion (BM_IN / BM_OUT / BM_IO) and 'ease-out'
function cpBez(x1, y1, x2, y2) {
  const bx = (t) => 3 * x1 * t * (1 - t) * (1 - t) + 3 * x2 * t * t * (1 - t) + t * t * t, by = (t) => 3 * y1 * t * (1 - t) * (1 - t) + 3 * y2 * t * t * (1 - t) + t * t * t;
  return (x) => { if (x <= 0) return 0; if (x >= 1) return 1; let lo = 0, hi = 1, t = x; for (let i = 0; i < 24; i++) { if (bx(t) < x) lo = t; else hi = t; t = (lo + hi) / 2; } return by(t); };
}
const BMI = cpBez(.55, .06, .8, .4), BMO = cpBez(.22, .7, .28, 1), BMIO = cpBez(.45, .05, .3, 1), BMEO = cpBez(0, 0, .58, 1);
const cpWin = (ms, d0, dur) => clamp((ms - d0) / dur);
// bmFold: turn, shrink to .06, fade in the last quarter (BM_IN). bmOpen: untwist from −turn at .06, ≈4 % overshoot at 62 %, settle (BM_OUT)
const cpFold = (p, turn) => { const e = BMI(p); return { r: turn * e, s: 1 - .94 * e, o: e < .72 ? 1 : 1 - (e - .72) / .28 }; };
const cpOpen = (p, turn, over) => {
  const e = BMO(p), ov = over || 1.045;
  if (e < .62) { const k = e / .62; return { r: -turn + turn * 1.08 * k, s: .06 + (ov - .06) * k, o: e < .16 ? e / .16 : 1 }; }
  const k = (e - .62) / .38; return { r: turn * .08 * (1 - k), s: ov + (1 - ov) * k, o: 1 };
};
const cpTf = (r, s) => 'rotate(' + r.toFixed(2) + ' 400 400) translate(400 400) scale(' + Math.max(.001, s).toFixed(4) + ') translate(-400 -400)';
let CPD = null;
// one data set: classification, orbit (sm: the 10.8-unit codes of the compact dial, legible on film) and persona, by AGD index
function cpOrb(L) {
  const W = decks[0].W, cls = W.eval('fpClassify')(L), orb = W.eval('fpOrbit')(L, cls, true), p = W.eval('persona')(L), code = W.eval('bloomCode')(p);
  const ly = AGID.map((id) => orb.layers.find((y) => y.a.id === id && y.n)), pl = AGID.map((id) => orb.planets.find((y) => y.a.id === id));
  return { L, cls, orb, p, code, idx: CODES.indexOf(code), ly: ly.map((x) => (x ? x.outer : null)), pl: pl.map((x) => (x ? x.deg : null)) };
}
function compassData() {
  if (CPD) return CPD;
  const W = decks[0].W, L = W.eval('sel({ noExtra: true })');
  const me = W.eval('persona')(L), typeP = W.eval('typeP'), bloom = W.eval('bloom'), parts = W.eval('bloomParts');
  const col = { ink: 'rgb(' + CPC.ink1 + ')', gray: CPC.petal2, lead: 'var(--orbit)', bg: '#000', hw: 2.8 };
  // pf / pb: the main / gray petals as single paths (bloom draws each petal as one 'M…Z' run), for the petal relay
  const sp = (d) => (d ? d.split(/(?=M)/).filter((x) => x.trim()) : []);
  const flower = (p) => { const g = bloom(p, CP.C, CP.RR), q = parts(g, CP.C, CP.C, col); return { back: q.back, front: q.front, heart: q.heart, pf: sp(g.major), pb: sp(g.back), n: g.n }; };
  const base = cpOrb(L);
  CPD = { TYPES: W.eval('TYPES'), AXES: W.eval('AXES'), AG: W.eval('AG'), me, L, cls: base.cls, orb: base.orb, agLogo: W.eval('agLogo'),
    lbl: W.eval('fpCodeLbls')(true), sets: { base }, fl: CODES.map((c) => flower(typeP(c))), mine: flower(me), mineIdx: CODES.indexOf(W.eval('bloomCode')(me)) };
  return CPD;
}
// a data set by key: 'base' = sel({ noExtra: true }) (the default), or one of the app's PERIODS ('jun' SIFV, 'jul' DIFV,
// 'aug' / 'sep' DIMV, '90', 'all' with the demo data) — st.data / st.wave.da / db
function cpSet(key) {
  const D = compassData(); if (!key || key === 'base') return D.sets.base;
  if (!D.sets[key]) { const W = decks[0].W, P = W.eval('PERIODS')[key]; D.sets[key] = P ? cpOrb(W.eval('personaScope')([P[0], P[1]])) : D.sets.base; }
  return D.sets[key];
}
// closed Catmull-Rom through N + 1 radii (first = last) at fixed bearings (fpCR × 2); rev: reversed; head 'M' | 'L'
function cpCR(rad, rev, head) {
  const N = rad.length - 1, P = []; for (let s = 0; s < N; s++) P.push(cpt(rad[s], s / N * 360));
  if (rev) P.reverse();
  const n = P.length, g = (i) => P[(i + n) % n];
  let d = head + f2(P[0]);
  for (let i = 0; i < n; i++) { const p0 = g(i - 1), p1 = g(i), p2 = g(i + 1), p3 = g(i + 2); d += 'C' + f2([p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6]) + ' ' + f2([p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6]) + ' ' + f2(p2); }
  return d;
}
function buildCompass() {
  const k = decks[2]; if (k.svg) return k.svg;
  const D = compassData();
  const tk = ['', '', '']; for (let i = 0; i < 128; i++) { const w = i % 32 === 0 ? 2 : i % 8 === 0 ? 1 : 0; tk[w] += 'M' + f2(cpt(392, i * 2.8125)) + 'L' + f2(cpt([385, 379, 370][w], i * 2.8125)); }
  const codes = D.lbl.map((x) => '<text class="tcode cp-code" data-t="' + x.t + '" x="' + (x.p[0] * CP.K).toFixed(1) + '" y="' + (x.p[1] * CP.K).toFixed(1) + '" text-anchor="middle" dominant-baseline="central" font-size="' + (x.fs * CP.K).toFixed(1) + '" style="letter-spacing:.04em">' + x.code + '</text>').join('');
  // each petal its own path (.pt, data-d = its bearing in the unturned flower: main petal j at j·360/n, gray petal j half a
  // step later), same fills as bloomParts; falls back to the joined layers if the split does not give n petals
  const one = (d, j, n, half, fill, c) => '<path class="' + c + ' pt" data-d="' + ((j + half) * 360 / n).toFixed(2) + '" d="' + d + '" fill="' + fill + '"/>';
  const fl = (f, i) => '<g class="fl" data-i="' + i + '" opacity="0"><g class="rot"><g class="bk">' +
    (f.pf.length === f.n && (!f.pb.length || f.pb.length === f.n) ? f.pb.map((d, j) => one(d, j, f.n, .5, CPC.petal2, 'fp-bk')).join('') + '</g><g class="fr">' + f.pf.map((d, j) => one(d, j, f.n, 0, 'rgb(' + CPC.ink1 + ')', 'fp-pet')).join('')
      : (f.back || '') + '</g><g class="fr">' + f.front) + '</g></g><g class="ht">' + f.heart + '</g></g>';
  const h = '<defs><radialGradient id="cpHead"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset=".35" stop-color="#cfe9ef" stop-opacity=".6"/><stop offset="1" stop-color="#a3adb0" stop-opacity="0"/></radialGradient></defs>' +
    '<clipPath id="cpTickClip"><path/></clipPath><clipPath id="cpBandClip"><path/></clipPath>' +
    // ruled-out types: their band sectors fade through a mask (the dial has no face, so nothing is painted over the light behind)
    '<mask id="cpDim" maskUnits="userSpaceOnUse" x="-200" y="-200" width="1200" height="1200"><rect x="-200" y="-200" width="1200" height="1200" fill="#fff"/>' + CODES.map((c, t) => '<path data-t="' + t + '" fill="#000" opacity="0" d="' + cpSector(CP.R0 - 2, CP.R0 + CP.RH + 12, t * 22.5, (t + 1) * 22.5) + '"/>').join('') + '</mask>' +
    '<g class="cp-dial"><circle cx="400" cy="400" r="392" fill="none" stroke="' + CPC.ink4 + '" stroke-width="1.6"/>' +
    '<g class="cp-ticks"><path d="' + tk[0] + '" stroke="' + CPC.ink4 + '" stroke-width="1"/><path d="' + tk[1] + '" stroke="' + CPC.ink4 + '" stroke-width="1.8"/><path d="' + tk[2] + '" stroke="' + CPC.ink2 + '" stroke-width="2.4"/></g>' +
    '<path class="cp-ptr" d="M400 4L390 -16L410 -16Z" fill="var(--orbit)"/></g>' +
    '<g class="cp-trace" fill="none" stroke-linecap="round"></g>' +
    '<g class="cp-codes">' + codes + '</g>' +
    '<g class="cp-band" mask="url(#cpDim)"><g class="body">' + AGID.map((id, i) => '<path data-a="' + id + '" fill="' + cpFill(AGC[i]) + '" fill-opacity="' + CPC.bo + '"/>').join('') + '</g>' +
    '<g class="edges">' + AGID.map((id, i) => '<path data-a="' + id + '" fill="none" stroke="' + cpLine(AGC[i]) + '" stroke-width="1.8" stroke-linejoin="round"/>').join('') + '</g>' +
    '<circle class="ring" cx="400" cy="400" r="' + CP.RING + '" fill="none" stroke="#fff" stroke-opacity=".6" stroke-width="2.4" opacity="0"/>' +
    '</g>' +
    '<g class="cp-pls">' + AGID.map((id, i) => '<g class="pl" data-a="' + id + '"><circle r="' + (CP.PB + 1.6) + '" fill="#000"/>' + D.agLogo(id, 0, 0, CP.PB, cpLine(AGC[i]), '#000') + '</g>').join('') + '</g>' +
    '<g class="cp-flower">' + D.fl.map(fl).join('') + fl(D.mine, 'me') + '</g>';
  const svg = document.createElementNS(SVGNS, 'svg'); svg.setAttribute('viewBox', '0 0 800 800'); svg.setAttribute('width', '800'); svg.setAttribute('height', '800'); svg.setAttribute('class', 'compass');
  svg.style.overflow = 'visible'; svg.innerHTML = h; k.rig.appendChild(svg); k.svg = svg;
  k.fls = [...svg.querySelectorAll('.cp-flower .fl')].map((g) => ({ g, rot: g.querySelector('.rot'), fr: g.querySelector('.fr'), bk: g.querySelector('.bk'), ht: g.querySelector('.ht'), pets: [...g.querySelectorAll('.pt')].map((el) => ({ el, d: +el.dataset.d })) }));
  k.body = [...svg.querySelectorAll('.cp-band .body path')]; k.edges = [...svg.querySelectorAll('.cp-band .edges path')];
  k.codes = [...svg.querySelectorAll('.cp-code')]; k.pls = [...svg.querySelectorAll('.cp-pls .pl')]; k.dims = [...svg.querySelectorAll('#cpDim path')];
  return svg;
}
function cpSector(r0, r1, a0, a1) { const p0 = cpt(r0, a0), p1 = cpt(r1, a0), p2 = cpt(r1, a1), p3 = cpt(r0, a1); return 'M' + f2(p0) + 'L' + f2(p1) + 'A' + r1 + ' ' + r1 + ' 0 0 1 ' + f2(p2) + 'L' + f2(p3) + 'A' + r0 + ' ' + r0 + ' 0 0 0 ' + f2(p0) + 'Z'; }
/* st: { deg: bearing of the flower (a petal faces it) and the --orbit triangle; the code nearest the triangle is
   emphasised. mine: 0..1 from the type's flower to your own (same type, your proportions). grow: 0 bud .. 1 open.
   fi: flower to show (a CODES index; default: the type under the triangle). twist: extra turn of the flower (deg).
   data: data set of the curves and badges (cpSet key, default 'base').
   wave: a change of type as 38-bloom-motion plays it: { a, b, u, da, db } — a / b = CODES indices of the old / new type
     (a null: b only unfolds from its heart, turning 32°), u = 0..1 progress of the app's 860 ms (fold 0–35 %, unfold
     30–100 %), da / db = data sets before / after (curves morph, badges glide; default st.data). While a wave runs the
     flower, triangle and emphasis follow it (deg is ignored when a is set).
   sweep (band reveal: a wedge from sweepFrom, clockwise), sweepSegs ([[from°, span°] × N]: the band shows through the
   union of N wedges; overrides sweep / sweepFrom), keep: 16 × 0..1 (1 = type still possible, 0 = ruled out:
   its band sector and code dim), dial, core (flower), needle (triangle), codes (0..1 code opacity factor), collapse
   (curves → one ring at r 300, badges onto it), ticks (0..1: ticks and codes revealed clockwise from north), trace
   (0..1: a light running once around the ticks; traceA its strength), pl (opacity of the compass's own badges; the film
   passes 0 and AGD draws them). spin / orbit / settle: kept for old call sites, no effect — since 0.0.4 every badge stays
   at its Agent's mean direction and the curves stay on their types, as in the app.
   Promo-only options (absent = the app's behaviour): tri (bearing of the triangle and the emphasised code; default deg, so
   the flower can turn on its own); rev (5 degrees by AGD index: Agent i's curve and badge revolve that far around the
   dial; CPS / cpBadge follow); relay: { a, b, u, a0 } a petal-by-petal change of type, u 0..1 — a's petals, ranked
   clockwise from 12 o'clock at flower bearing a0 (default deg), fold into the heart one after another at an even cadence
   (u .0–.77) while b's open one after another right behind them (u .14–1), hearts cross-fade at u .38–.68; the flower
   keeps turning with deg. } */
// a pie wedge (clip) from bearing a0, span degrees clockwise
function cpWedge(a0, span) {
  if (span >= 359.9) return 'M-200 -200H1000V1000H-200Z';
  if (span <= 0) return 'M400 400Z';
  const p0 = cpt(560, a0), p1 = cpt(560, a0 + span);
  return 'M400 400L' + f2(p0) + 'A560 560 0 ' + (span > 180 ? 1 : 0) + ' 1 ' + f2(p1) + 'Z';
}
function cpArc(r, a0, a1) { const p0 = cpt(r, a0), p1 = cpt(r, a1); return 'M' + f2(p0) + 'A' + r + ' ' + r + ' 0 ' + (a1 - a0 > 180 ? 1 : 0) + ' 1 ' + f2(p1); }
// CPS: the last drawCompass state (st, plus pla = badge opacity factor, pl[i] = [px, py, r] of Agent i (AGD order) in
// compass units and pa[i] = its presence 0..1 in the shown data). cpStage: compass point → stage px through deck 2's
// camera (perspective · Z · X · Y · Z, as the CSS). cpBadge(i): where AGD's 'compass' formation puts Agent i this frame.
let CPS = null;
function cpStage(px, py) {
  const C = decks[2].C, R = Math.PI / 180;
  let X = (px - C.x) * C.s, Y = (py - C.y) * C.s, Z = 0, a = C.rz * R;
  [X, Y] = [X * Math.cos(a) - Y * Math.sin(a), X * Math.sin(a) + Y * Math.cos(a)];
  a = C.ry * R; [X, Z] = [X * Math.cos(a) + Z * Math.sin(a), -X * Math.sin(a) + Z * Math.cos(a)];
  a = C.rx * R; [Y, Z] = [Y * Math.cos(a) - Z * Math.sin(a), Y * Math.sin(a) + Z * Math.cos(a)];
  Z += C.z; const w = 1 - Z / 2400;
  return [C.ax + X / w, C.ay + Y / w];
}
function cpBadge(i) {
  let q = CPS && CPS.pl[i];
  if (!q) { const d = CPD && CPD.sets.base.pl[i]; q = cpt(CP.PR, d ?? i * 72 + 18); }
  const p = cpStage(q[0], q[1]);
  return { x: p[0], y: p[1], r: CP.PB * decks[2].C.s, a: CPS ? CPS.pa[i] : 1 };
}
function drawCompass(st) {
  const svg = buildCompass(), k = decks[2], D = CPD, col = clamp(st.collapse || 0), wv = st.wave, dial = st.dial ?? 1, core = st.core ?? 1;
  const sw = clamp(st.sweep ?? 1), keep = st.keep;
  // the switch clock (app ms): a type change runs 860 ms; a first bloom (a null) 680 ms
  const fold = wv && wv.a != null && wv.a !== wv.b, ms = wv ? clamp(wv.u) * (fold ? 860 : 680) : 0;
  const SA = cpSet(wv && wv.da != null ? wv.da : st.data), SB = cpSet(wv && wv.db != null ? wv.db : st.data);
  // ---- curves: each Agent from the shared baseline; a data change blends every radius (560 ms, ease-in-out), new
  // curves fade in (120–540 ms), gone curves fade out from their old shape (0–360 ms); collapse pulls all to r 300
  const mo = SA === SB ? 1 : E.inOut(cpWin(ms, 0, 560)), rr = (e) => lerp(CP.R0 + e * CP.K, CP.RING, col);
  const key = col.toFixed(4) + '|' + (wv && wv.da != null ? wv.da : st.data || 'base') + '>' + (wv && wv.db != null ? wv.db : st.data || 'base') + '|' + (SA === SB ? '' : ms.toFixed(1));
  if (k.bandKey !== key) {
    k.bandKey = key;
    const N = (SB.ly.find(Boolean) || SA.ly.find(Boolean) || new Array(145).fill(0)).length - 1, inner = cpCR(new Array(N + 1).fill(rr(0)), true, 'L');
    AGID.forEach((id, i) => {
      const a = SA.ly[i], b = SB.ly[i], fb = k.body[i], fe = k.edges[i];
      let o = 1, e = b || a;
      if (a && b && SA !== SB) e = b.map((v, s) => lerp(a[s], v, mo));
      else if (!a && b && SA !== SB) o = BMEO(cpWin(ms, 120, 420));
      else if (a && !b) o = SA === SB ? 1 : 1 - E.in(cpWin(ms, 0, 360));
      if (!e || o < .002) { fb.style.display = fe.style.display = 'none'; return; }
      fb.style.display = fe.style.display = '';
      const out = cpCR(e.map(rr), false, 'M');
      fb.setAttribute('d', out + inner + 'Z'); fe.setAttribute('d', out + 'Z');
      fb.style.opacity = (o * (1 - col)).toFixed(3); fe.style.opacity = (o * (1 - E.in(col))).toFixed(3);
    });
    svg.querySelector('.cp-band .ring').setAttribute('opacity', E.in(col).toFixed(3));
  }
  const rv = st.rev;
  AGID.forEach((id, i) => { const r = rv ? rv[i] || 0 : 0, fb = k.body[i], fe = k.edges[i]; if (r || fb._r) { const t = r ? 'rotate(' + r.toFixed(3) + ' 400 400)' : ''; fb.setAttribute('transform', t); fe.setAttribute('transform', t); fb._r = r; } });
  const bg = svg.querySelector('.cp-band');
  if (st.sweepSegs) { svg.querySelector('#cpBandClip path').setAttribute('d', st.sweepSegs.map(([a0, sp]) => cpWedge(a0, sp)).join('')); bg.setAttribute('clip-path', 'url(#cpBandClip)'); }
  else if (sw < 1) { svg.querySelector('#cpBandClip path').setAttribute('d', cpWedge(st.sweepFrom || 0, sw * 360)); bg.setAttribute('clip-path', 'url(#cpBandClip)'); } else bg.removeAttribute('clip-path');
  k.dims.forEach((p, t) => { p.setAttribute('opacity', ((1 - (keep ? keep[t] : 1)) * .72 * (1 - col)).toFixed(3)); });
  // ---- badges on the orbit at each Agent's mean direction; a data change glides them along the shortest arc (640 ms,
  // 40 ms apart, BM_IO), a new Agent fades in (260–580 ms), a gone one fades out. Positions go to CPS.pl for AGD
  const pla = st.pl ?? 1, pos = [], pa = [];
  let gi = 0;
  AGID.forEach((id, i) => {
    const a = SA.pl[i], b = SB.pl[i]; let d = b ?? a ?? i * 72 + 18, o = (b ?? a) != null ? 1 : 0;
    if (SA !== SB) {
      if (a != null && b != null) { const dd = cpDelta(a, b); if (Math.abs(dd) >= .3) d = a + dd * BMIO(cpWin(ms, 40 * gi++, 640)); }
      else if (b != null) o = BMEO(cpWin(ms, 260, 320));
      else if (a != null) o = 1 - BMEO(cpWin(ms, 0, 300));
    }
    if (rv) d += rv[i] || 0;
    const q = cpt(lerp(CP.PR, CP.RING, col), d); pos[i] = [q[0], q[1], CP.PB]; pa[i] = o;
    const g = k.pls[i], v = o * clamp(sw * 2 - i * .2) * (1 - col) * dial * pla;
    g.setAttribute('transform', 'translate(' + f2(q) + ')'); g.style.opacity = v.toFixed(3); g.style.display = v < .002 ? 'none' : '';
  });
  CPS = Object.assign({}, st, { pla, pl: pos, pa });
  // ---- ticks drawn on clockwise from north (the codes come in with them), and a light that runs once around them
  const tkv = clamp(st.ticks ?? 1), tg = svg.querySelector('.cp-ticks');
  if (tkv < 1) { svg.querySelector('#cpTickClip path').setAttribute('d', cpWedge(0, tkv * 360)); tg.setAttribute('clip-path', 'url(#cpTickClip)'); } else tg.removeAttribute('clip-path');
  const trg = svg.querySelector('.cp-trace'), tr = st.trace, ta = st.traceA ?? 1;
  if (tr != null && tr > 0 && ta > .001) {
    const head = tr * 360, n = 14, tail = 120; let h = '';
    for (let j = 0; j < n; j++) { const a0 = Math.max(0, head - tail * (j + 1) / n), a1 = Math.max(0, head - tail * j / n); if (a1 - a0 < .2) continue; h += '<path d="' + cpArc(381, a0, a1) + '" stroke="var(--orbit)" stroke-width="' + (9 - j * .5).toFixed(1) + '" stroke-opacity="' + ((1 - j / n) * .9 * ta).toFixed(3) + '"/>'; }
    const hp = cpt(381, head); h += '<circle cx="' + hp[0].toFixed(1) + '" cy="' + hp[1].toFixed(1) + '" r="18" fill="url(#cpHead)" opacity="' + ta.toFixed(3) + '"/><circle cx="' + hp[0].toFixed(1) + '" cy="' + hp[1].toFixed(1) + '" r="5" fill="#fff" opacity="' + ta.toFixed(3) + '"/>';
    trg.innerHTML = h;
  } else if (trg.firstChild) trg.innerHTML = '';
  // ---- triangle, flower angles and the emphasised code
  const deg = st.deg || 0, tw = st.twist || 0;
  let tri = st.tri ?? deg, em = null;
  const hA = fold ? cpTypeDeg(wv.a) : deg, hB = fold ? cpTypeDeg(wv.b) : deg, dl = cpDelta(hA, hB), sg = dl < 0 ? -1 : 1;
  if (fold) {
    // the triangle turns along the shortest arc with a small settle (760 ms, BM_IO); the old code fades back to gray from
    // 60 ms, the new one darkens from 420 ms as the triangle lands
    const e = BMIO(cpWin(ms, 0, 760)); tri = e < .78 ? hA + dl * 1.04 * e / .78 : hB + dl * .04 * (1 - (e - .78) / .22);
    em = new Array(16).fill(0); em[wv.a] = 1 - BMEO(cpWin(ms, 60, 380)); em[wv.b] = Math.max(em[wv.b], BMEO(cpWin(ms, 420, 420)));
  }
  if (!em) { em = CODES.map((c, t) => clamp((17.5 - Math.abs(cpDelta(tri, cpTypeDeg(t)))) / 12.5)); }   // the code under the triangle (soft at the sector edges)
  const cf = (st.codes ?? 1) * dial;
  k.codes.forEach((x, t) => {
    const v = clamp(em[t]) * (st.needle ?? 1), rv = E.out(clamp((tkv * 360 - t * 22.5) / 30)), kp = keep ? keep[t] : 1;
    const c = CPC.ink3.map((a, j) => Math.round(lerp(a, CPC.ink1[j], v)));
    x.setAttribute('fill', 'rgb(' + c + ')'); x.style.fontWeight = v > .5 ? 800 : 600;
    x.style.opacity = (cf * rv * lerp(.3, 1, kp) * (1 - col)).toFixed(3);
  });
  const ptr = svg.querySelector('.cp-ptr');
  ptr.setAttribute('transform', 'rotate(' + tri.toFixed(2) + ' 400 400)'); ptr.style.opacity = ((st.needle ?? 1) * dial).toFixed(3);
  svg.querySelector('.cp-dial').style.opacity = dial.toFixed(3);
  // ---- flowers: the type under the triangle (cross-fading into the neighbour near a sector edge) or fi; `mine` hands
  // over to your own flower; a wave folds a and unfolds b as 38-bloom-motion
  const u = ((deg % 360) + 360) % 360 / 22.5, i0 = Math.floor(u) % 16, fr = u - Math.floor(u), dd = Math.min(fr, 1 - fr), nb = (i0 + (fr < .5 ? 15 : 1)) % 16;
  const x = dd < .15 ? dd / .15 : 1, op = new Array(17).fill(0);
  if (st.fi != null) op[st.fi] = 1; else { op[i0] = .5 + .5 * x; op[nb] += .5 - .5 * x; }
  if (wv) { op.fill(0); if (fold) op[wv.a] = 1; op[wv.b] = 1; }
  const rl = !wv && st.relay && st.relay.a !== st.relay.b ? st.relay : null, ru = rl ? clamp(rl.u) : 0;
  if (rl) { op.fill(0); op[rl.a] = 1; op[rl.b] = 1; }
  const mine = clamp(st.mine || 0);
  if (mine > 0) { if (wv) { op[16] = op[wv.b] * mine; op[wv.b] *= 1 - mine; } else { for (let t = 0; t < 16; t++) op[t] *= 1 - mine; op[16] = mine; } }
  const gr = clamp(st.grow ?? 1), sc = CP.BUD + (1 - CP.BUD) * gr, hearts = fold ? [D.fl[wv.a].heart, D.fl[wv.b].heart] : null, same = hearts && hearts[0] === hearts[1];
  k.fls.forEach((f, j) => {
    const o = op[j] * core; f.g.setAttribute('opacity', o.toFixed(3)); if (o < .002) return;
    const side = !wv ? null : fold && j === wv.a ? 'a' : (j === wv.b || j === 16) ? 'b' : null;
    let ang = deg + tw, F = null, B = null, H = null;
    if (side === 'a') {
      // the old flower turns 30 % of the way while it folds (300 ms, BM_IN); petals twist 28°, the gray ring 50 ms behind
      ang = hA + dl * .3 * BMI(cpWin(ms, 0, 300)) + tw; F = cpFold(cpWin(ms, 0, 300), 28 * sg); B = cpFold(cpWin(ms, 50, 300), 28 * sg);
      H = { s: 1, o: same ? 0 : 1 - cpWin(ms, 230, 110) };
    } else if (side === 'b') {
      if (fold) {
        // the new flower turns the remaining 70 % while it unfolds (260–860 ms, BM_OUT); untwist 32°, the gray ring 80 ms behind
        ang = hB - dl * .7 * (1 - BMO(cpWin(ms, 260, 600))) + tw; F = cpOpen(cpWin(ms, 260, 520), 32 * sg); B = cpOpen(cpWin(ms, 340, 520), 32 * sg);
        if (!same) { const e = BMO(cpWin(ms, 230, 320)); H = e < .55 ? { s: .4 + .74 * e / .55, o: e / .55 } : { s: 1.14 - .14 * (e - .55) / .45, o: 1 }; }
      } else { F = cpOpen(cpWin(ms, 0, 600), 32, 1.05); B = cpOpen(cpWin(ms, 80, 600), 32, 1.05); }
    }
    const set = (el, q) => { if (!q) { if (el._q) { el.removeAttribute('transform'); el.style.opacity = ''; el._q = 0; } return; } el._q = 1; el.setAttribute('transform', cpTf(q.r || 0, q.s)); el.style.opacity = clamp(q.o).toFixed(3); };
    // relay: rank this flower's petals clockwise from 12 o'clock (at the change's starting bearing a0), then an even
    // cadence — the old flower's petals fold (twist 14° into the heart), the new one's open right behind them
    const rs = rl && (j === rl.a ? 'A' : j === rl.b ? 'B' : null);
    if (rs) {
      const a0 = rl.a0 ?? deg + tw, n = f.pets.length, sameH = D.fl[rl.a].heart === D.fl[rl.b].heart;
      const ord = f.pets.map((p, m) => [((a0 + p.d) % 360 + 360) % 360, m]).sort((x, y) => x[0] - y[0]);
      ord.forEach(([, m], r) => { const p0 = rs === 'A' ? .55 * r / n : .14 + .55 * r / n, q = rs === 'A' ? cpFold(clamp((ru - p0) / .22), 14) : cpOpen(clamp((ru - p0) / .3), 18); set(f.pets[m].el, q); });
      if (rs === 'A') H = { s: 1 - .3 * E.in(clamp((ru - .38) / .16)), o: sameH ? 0 : 1 - BMEO(clamp((ru - .38) / .16)) };
      else if (!sameH) { const e = BMO(clamp((ru - .44) / .24)); H = e < .55 ? { s: .4 + .74 * e / .55, o: e / .55 } : { s: 1.14 - .14 * (e - .55) / .45, o: 1 }; }
    } else f.pets.forEach((p) => set(p.el, null));
    f.rot.setAttribute('transform', cpTf(ang, sc));
    set(f.fr, F); set(f.bk, B); set(f.ht, H);
  });
}
/* ---------- the Orbit mark, live ----------
   The same conical spiral as docs/design/logo/generate.py, variant "spiral" (1.6 turns, radius 9 → 16, rise 14, phase
   0.6, seen at yaw 20° / pitch 45° — the app icon), drawn as a tapered line so it can be traced, turned in 3D and seen
   from above (pitch 90° = a flat spiral whose outer turn is a near circle).
   v17: scenes place it with markAt / markRing (below); orbitSVG itself is never changed. */
// curve and stroke = docs/design/logo/orbit-spec.json; K = design px per curve unit at the icon view
// (orbit-geometry.json projection.scale), so every pose is the app icon's curve scaled as a whole
const ORB = { turns: 1.6, r0: 9, r1: 16, rise: 14, phase: .6, N: 480, K: 15.044624443, wFar: 4, wNear: 14, taper: .1, wFloor: .6, gap: 24 };
const orbEl = $('#orbit');
function orbitPts(yaw, pitch) {
  const Y = yaw * Math.PI / 180, P = pitch * Math.PI / 180, out = [];
  for (let k = 0; k <= ORB.N; k++) {
    const t = k / ORB.N, th = 2 * Math.PI * ORB.turns * t + ORB.phase, r = ORB.r0 + (ORB.r1 - ORB.r0) * t;
    const x = r * Math.cos(th), y = r * Math.sin(th), z = ORB.rise * (t - .5);
    const x1 = x * Math.cos(Y) - y * Math.sin(Y), y1 = x * Math.sin(Y) + y * Math.cos(Y);
    const y2 = y1 * Math.cos(P) - z * Math.sin(P), z2 = y1 * Math.sin(P) + z * Math.cos(P);
    out.push([x1 / ORB.r1, -z2 / ORB.r1, -y2 / ORB.r1]);
  }
  return out;
}
/* The line follows docs/design/logo/orbit.py: width = max(w_floor, (w_far + (w_near − w_far)·depth)·sin(e·π/2)) with
   depth normalised over this pose and e the taper over the first / last 10 % of the screen arc length; where the
   projection crosses itself the far branch is cut gap/2 + its width on either side; round ends. Each run is one filled
   outline. o = { t0, t: drawn span 0..1 along the curve, yaw, pitch, R: px per unit, cx, cy, a, head, color } */
function orbitSVG(o) {
  if (!o || o.a <= .001) return '';
  const N = ORB.N, u = o.R / (ORB.r1 * ORB.K), p = orbitPts(o.yaw, o.pitch).map((q) => [o.cx + q[0] * o.R, o.cy + q[1] * o.R, q[2]]);
  const Ls = [0]; for (let k = 1; k <= N; k++) Ls.push(Ls[k - 1] + Math.hypot(p[k][0] - p[k - 1][0], p[k][1] - p[k - 1][1]));
  const T = Ls[N] || 1, z0 = Math.min(...p.map((q) => q[2])), z1 = Math.max(...p.map((q) => q[2]));
  const w = p.map((q, k) => { const e = Math.min(1, Ls[k] / (T * ORB.taper), (T - Ls[k]) / (T * ORB.taper)); return Math.max(ORB.wFloor, (ORB.wFar + (ORB.wNear - ORB.wFar) * (q[2] - z0) / (z1 - z0 || 1)) * Math.sin(e * Math.PI / 2)) * u; });
  const cut = new Uint8Array(N + 1), xs = [];
  for (let i = 0; i < N; i++) {
    const a = p[i], b = p[i + 1];
    for (let j = i + 3; j < N; j++) {
      const c = p[j], d = p[j + 1];
      if (Math.max(c[0], d[0]) < Math.min(a[0], b[0]) || Math.min(c[0], d[0]) > Math.max(a[0], b[0]) || Math.max(c[1], d[1]) < Math.min(a[1], b[1]) || Math.min(c[1], d[1]) > Math.max(a[1], b[1])) continue;
      const den = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0]); if (Math.abs(den) < 1e-12) continue;
      const s = ((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) / den, v = ((c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])) / den;
      if (s < 0 || s >= 1 || v < 0 || v >= 1) continue;
      const f = a[2] + s * (b[2] - a[2]) < c[2] + v * (d[2] - c[2]) ? i : j;
      xs.push({ i, j, f, r: ORB.gap / 2 * u + w[f] });
    }
  }
  const n0 = Math.min(N - 1, Math.round((o.t0 || 0) * N)), n = Math.min(N, Math.max(n0 + 1, Math.round(o.t * N)));
  // a crossing is cut only once both of its branches are drawn, and the gap opens as the line moves on past it (so a
  // stroke being traced, or grown from its tail, is never broken ahead of the branch that will cross it)
  for (const x of xs) {
    if (x.i < n0 || x.j > n) continue;
    const fw = n >= N ? 1 : clamp((Ls[n] - Ls[x.j]) / (x.r * 2)), bw = n0 <= 0 ? 1 : clamp((Ls[x.i] - Ls[n0]) / (x.r * 2)), r = x.r * Math.min(fw, bw);
    for (let k = 0; k <= N; k++) if (Math.abs(Ls[k] - Ls[x.f]) < r) cut[k] = 1;
  }
  const X = (q) => q[0].toFixed(2) + ' ' + q[1].toFixed(2);
  const run = (k0, k1) => {
    const L = [], Rr = [];
    for (let k = k0; k <= k1; k++) {
      const a = p[Math.max(k0, k - 1)], b = p[Math.min(k1, k + 1)], ln = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, nx = -(b[1] - a[1]) / ln, ny = (b[0] - a[0]) / ln, h = w[k] / 2;
      L.push([p[k][0] + nx * h, p[k][1] + ny * h]); Rr.push([p[k][0] - nx * h, p[k][1] - ny * h]);
    }
    const r1 = (w[k1] / 2).toFixed(2), r0 = (w[k0] / 2).toFixed(2);
    return 'M' + L.map(X).join('L') + 'A' + r1 + ' ' + r1 + ' 0 0 0 ' + X(Rr[Rr.length - 1]) + 'L' + Rr.reverse().map(X).join('L') + 'A' + r0 + ' ' + r0 + ' 0 0 0 ' + X(L[0]) + 'Z';
  };
  let d = '', k0 = null;
  for (let k = n0; k <= n; k++) {
    if (!cut[k] && k0 == null) k0 = k;
    if ((cut[k] || k === n) && k0 != null) { const k1 = cut[k] ? k - 1 : k; if (k1 > k0) d += run(k0, k1); k0 = null; }
  }
  let h = '<g opacity="' + o.a.toFixed(3) + '"><path d="' + d + '" fill="' + (o.color || '#e9eaee') + '"/>';
  if (o.head > .01 && n < N) { const q = p[n], hw = ORB.wNear * u; h += '<circle cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="' + (hw * 1.6).toFixed(1) + '" fill="url(#orbGlow)" opacity="' + o.head.toFixed(3) + '"/><circle cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="' + (hw * .55).toFixed(1) + '" fill="#fff" opacity="' + o.head.toFixed(3) + '"/>'; }
  return h + '</g>';
}
// an Agent as its own logo (the app's agLogo badge: dark disc, Agent-coloured ring and mark), AGC order = the app's AG
const AGID = ['cc', 'cx', 'gm', 'ds', 'cp'];
let AGLOGO = null;
function agBadge(i, x, y, r) { AGLOGO = AGLOGO || decks[0].W.eval('agLogo'); return AGLOGO(AGID[i], +x.toFixed(1), +y.toFixed(1), r, AGC[i], '#0e0f12'); }
const MARK_INK = '#fff';
/* ---------- the mark track (v17) ----------
   markAt(b0, b1, fn): in [b0, b1) fn(p, b) runs every frame (p = progress 0..1 in the segment) and returns an orbitSVG
   pose { t0, t, yaw, pitch, R, cx, cy, a, head, color }, an array of poses, or null; overlapping segments all draw
   (cross-fades). Colour defaults to MARK_INK. MARK.pose = the last pose drawn this frame (null if none). */
const MARKS = [];
function markAt(b0, b1, fn) { MARKS.push({ b0: b0 + SH, b1: b1 + SH, sh: SH, fn }); }
const MARK = {
  pose: null,
  ICON: { yaw: 20, pitch: 45 },                            // the app icon view
  TOP: { yaw: 0, pitch: 90 },                              // seen from above: outer turn radius R, inner 9/16·R
  // numeric mix of two poses (keys of b missing in a are taken from b)
  mix: (a, b, e) => { const o = Object.assign({}, a, b); for (const k in b) if (typeof b[k] === 'number' && typeof a[k] === 'number') o[k] = lerp(a[k], b[k], e); return o; }
};
/* markRing: the spiral grown from its tail (outer turn first) at pitch 90 − tilt (or o.pitch), yaw o.yaw (0). The tail
   (z = rise / 2) is lifted back onto the circle of radius R (v16 CLOSE's lift, × o.lift, default 1; 0 at pitch 90).
   o = { cx, cy, R, grow 0..1 (1), tilt (0), yaw, pitch, lift, a (1), head } */
function markRing(o) {
  const pitch = o.pitch ?? 90 - (o.tilt || 0), g = clamp(o.grow ?? 1);
  const lift = (ORB.rise / 2 / ORB.r1) * o.R * Math.cos(pitch * Math.PI / 180) * (o.lift ?? 1);
  return { t0: 1 - g * .999, t: 1, yaw: o.yaw || 0, pitch, R: o.R, cx: o.cx, cy: o.cy + lift, a: o.a ?? 1, head: o.head || 0 };
}
function orbitAt(bf) {
  let h = ''; MARK.pose = null;
  for (const m of MARKS) {
    if (bf < m.b0 || bf >= m.b1) continue;
    let r; try { r = inCtx(m.sh, () => m.fn(clamp((bf - m.b0) / (m.b1 - m.b0)), bf - m.sh)); } catch (e) { console.error('markAt @' + m.b0, e); m.b1 = -1; continue; }
    for (const q of (Array.isArray(r) ? r : [r])) { if (!q) continue; const o = Object.assign({ t: 1, a: 1, color: MARK_INK }, q); h += orbitSVG(o); MARK.pose = o; }
  }
  orbEl.innerHTML = h ? '<defs><radialGradient id="orbGlow"><stop offset="0" stop-color="rgba(255,255,255,.9)"/><stop offset="1" stop-color="rgba(255,255,255,0)"/></radialGradient></defs>' + h : '';
}

/* a macOS pointer that glides to a control, presses it, and then the action runs — one per app copy, drawn inside the
   copy so it follows the camera, counter-scaled so it keeps a constant size on screen */
const CURSOR_SVG = '<svg viewBox="0 0 28 28" width="28" height="28"><path d="M6 3.5v19.2l4.6-4.4 3 6.9 3.3-1.4-2.9-6.8h6.5z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
const clicks = [];
// o.bloom: colour of a press bloom (a radial fill under the pointer, then a soft glow that spreads to about 3×, as in
// the GWI reference); o.size: its diameter on screen in px; o.glide: beats the pointer takes to reach the control;
// o.cursor: false = no pointer and no glide, only the bloom at the target (an Agent dot plays the pointer).
function clickAt(d, b, sel, fn, o = {}) { clicks.push({ d, b: b + SH, sel, fn, o }); at(b, () => { const el = find(d, sel); if (el) fn(app(d), el); else console.warn('promo: no click target', sel); }); }
function cursorEl(d) {
  const k = decks[d]; if (k.cursor) return k.cursor;
  const c = document.createElement('div'); c.className = 'cursor'; c.innerHTML = CURSOR_SVG + '<i class="ripple"></i>'; k.rig.appendChild(c); k.cursor = c; return c;
}
function applyCursors(t) {
  const b = t / BEAT;
  for (const k of decks) { const c = k.cursor; if (c) c.style.opacity = '0'; }
  for (const x of clicks) {
    const nc = x.o.cursor === false, gl = nc ? 0 : x.o.glide || 1.1;
    if (b < x.b - gl - .2 || b > x.b + .9) { if (x.bloom) x.bloom.style.opacity = '0'; continue; }
    if (!x.to) { const el = find(x.d, x.sel); if (!el) continue; const r = el.getBoundingClientRect(); x.to = [r.left + r.width * .5, r.top + r.height * .55]; x.from = [x.to[0] + 160, x.to[1] + 120]; }
    const s = decks[x.d].C.s;
    if (nc) { if (x.o.bloom) clickBloom(x, b, s, null); continue; }
    const c = cursorEl(x.d);
    const m = E.inOut(lp(b, x.b - gl, gl - .1)), press = b >= x.b && b < x.b + .25 ? .82 : 1;
    const px = lerp(x.from[0], x.to[0], m), py = lerp(x.from[1], x.to[1], m);
    c.style.opacity = (E.out(lp(b, x.b - 1.3, .35)) * (1 - E.in(lp(b, x.b + .55, .35)))).toFixed(3);
    c.style.transform = 'translate(' + px.toFixed(2) + 'px,' + py.toFixed(2) + 'px) scale(' + (1.8 / s * press).toFixed(4) + ')';
    const rp = lp(b, x.b, .6); const ri = c.querySelector('.ripple');
    ri.style.opacity = b >= x.b ? (1 - rp).toFixed(3) : '0'; ri.style.transform = 'translate(-50%,-50%) scale(' + (.4 + rp * 1.6).toFixed(3) + ')';
    if (x.o.bloom) clickBloom(x, b, s, c);
  }
}
function clickBloom(x, b, s, c) {
  if (!x.bloom) { x.bloom = document.createElement('div'); x.bloom.className = 'bloom'; x.bloom.innerHTML = '<i class="bf"></i><i class="bg"></i>'; x.bloom.style.setProperty('--c', x.o.bloom); decks[x.d].rig.insertBefore(x.bloom, c || null); }
  const fp = E.out(lp(b, x.b, .14)), gp = E.out(lp(b, x.b + .05, .75)), sz = (x.o.size || 90) / s;
  x.bloom.style.opacity = b >= x.b ? '1' : '0';
  x.bloom.style.transform = 'translate(' + x.to[0].toFixed(1) + 'px,' + x.to[1].toFixed(1) + 'px)';
  const bf = x.bloom.firstChild, bg = x.bloom.lastChild;
  bf.style.width = bf.style.height = bg.style.width = bg.style.height = sz.toFixed(1) + 'px';
  bf.style.transform = 'translate(-50%,-50%) scale(' + fp.toFixed(3) + ')'; bf.style.opacity = (1 - E.in(lp(b, x.b + .3, .5))).toFixed(3);
  bg.style.transform = 'translate(-50%,-50%) scale(' + (1 + 2.2 * gp).toFixed(3) + ')'; bg.style.opacity = (.85 * (1 - gp)).toFixed(3);
}
// screen (stage) position of a point given in deck d's frame px, or of an element of deck d (ax, ay = share of its box);
// follows the deck's camera, tilts included. Used for portals and for type that has to meet a component on screen.
function stageXY(d, fx, fy) {
  const k = decks[d]; let pr = k.probe;
  if (!pr) { pr = document.createElement('i'); pr.style.cssText = 'position:absolute;left:0;top:0;width:0;height:0'; k.rig.appendChild(pr); k.probe = pr; }
  pr.style.left = fx + 'px'; pr.style.top = fy + 'px';
  const r = pr.getBoundingClientRect(), st = stage.getBoundingClientRect(), z = st.width / 1920;
  return [(r.left - st.left) / z, (r.top - st.top) / z];
}
function elXY(d, sel, ax = .5, ay = .5) { const el = find(d, sel); if (!el) return [960, 540]; const r = el.getBoundingClientRect(); return stageXY(d, r.left + r.width * ax, r.top + r.height * ay); }
// a per-frame function that is not tied to an app copy: every(b0, b1, (p, b) => …)
const every = (b0, b1, fn) => drive(2, b0, b1, (p, b) => fn(p, b));


/* ============================== scenes ==============================
   The film itself lives in scenes/*.js: each file registers one scene with scene(name, fn), promo.html loads them in
   file-name order and script() runs them in that order once both app copies have loaded. A scene only adds cues,
   tweens, drives, clicks and type for its own beats. STORYBOARD.md gives every scene its beats, decks and the state it
   must hand over to the next one; times are beats (132 BPM, 1 beat = 0.455 s). */
const SCENES = [];
function scene(name, fn) { SCENES.push({ name, fn }); }
let END_SH = 0;                                            // SHIFT of the scene that set END
function script() { for (const s of SCENES) { SH = SHIFT[s.name] || 0; const e0 = END; try { s.fn(); } catch (e) { console.error('scene ' + s.name, e); } if (END !== e0) END_SH = SH; } SH = 0; }
// styles a scene needs for its own type or overlays
function css(text) { const st = document.createElement('style'); st.textContent = text; document.head.appendChild(st); }
const L = 160, R = 1760;
function smallest(D, sel, text) { return [...D.querySelectorAll(sel)].filter((e) => e.textContent.includes(text)).sort((a, b) => a.textContent.length - b.textContent.length)[0]; }

/* ---------- clock & frame loop ---------- */
const PROMO = window.PROMO = { ready: false, duration: 0, t: 0 };
let t0 = null, offset = 0, audio = null, actx = null;
function now() {
  if (actx && audio) return actx.currentTime - audio.start + offset;
  return t0 == null ? 0 : (performance.now() - t0) / 1000 + offset;
}
function step(tt) {
  const t = tt ?? now(); PROMO.t = t;
  for (const c of cues) if (!c.done && t >= c.b * BEAT) { c.done = true; try { inCtx(c.sh, c.fn); } catch (e) { console.error('cue @' + c.b, e); } }
  // the app re-renders on clicks and route changes: re-mark the solo component when its element was replaced
  for (const k of decks) if (k.solo && k.D) for (const s of Array.isArray(k.solo) ? k.solo : [k.solo]) { const el = find(k.i, s); if (el && !el.classList.contains('promo-solo')) el.classList.add('promo-solo'); }
  // scrollIntoView inside an app copy (solo) also scrolls the promo page and the stage itself: pin them every frame
  stage.scrollLeft = stage.scrollTop = 0; document.documentElement.scrollLeft = document.documentElement.scrollTop = 0; document.body.scrollLeft = document.body.scrollTop = 0;
  applyDrives(t); applyCams(t); applyCursors(t); applyTags(t); orbitAt(t / BEAT);
  if (typeof applyAgents === 'function') applyAgents(t);  // scenes/02-agents.js: after the cameras and the mark (it reads deck 2's camera)
  applyFx(t);
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
  for (const c of cues) if (c.b * BEAT < from) { c.done = true; try { inCtx(c.sh, c.fn); } catch (e) { console.error(e); } }
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
  boot();
}));
function boot() {
  script(); END += END_SH; PROMO.duration = END * BEAT; tweens.sort((a, b) => a.b - b.b); cues.sort((a, b) => a.b - b.b); step(0);
  if (DEBUG) { const d = document.createElement('div'); d.className = 'dbg'; stage.appendChild(d); setInterval(() => { d.textContent = 'b' + (PROMO.t / BEAT).toFixed(2); }, 50); }
  PROMO.ready = true;
}
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

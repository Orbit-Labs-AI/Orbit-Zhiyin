/* Tandem promo: a beat-locked timeline. Two live copies of the app take turns showing ONE component each (everything
   else in that copy is hidden), framed by a virtual camera next to the copy that explains it. Transitions overlap the
   outgoing and incoming component with long eases; there are no beat-synced shakes or flashes.
   Everything is a pure function of the master time t (seconds), so the page plays in real time with the soundtrack
   (preview) or frame by frame on Playwright's fake clock (render.mjs). Times are written in beats. */
'use strict';
const BPM = 124, BEAT = 60 / BPM, END = 106;              // beats; music.py uses the same grid
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
const tweens = [];
const BOX = { C: [960, 560, 1560, 760], R: [1250, 540, 1060, 800], L: [670, 540, 1060, 800] };
function find(d, sel) {
  const D = decks[d].D; if (!D) return null;
  if (typeof sel === 'function') return sel(D);
  return D.querySelector(sel);
}
function rectOf(d, sel) {
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
    const D = decks[x.d].D; if (!D) continue;
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

/* the compass: the radar in the middle of the fingerprint becomes a dial of the 16 persona codes (Gray-code order, so
   neighbours differ by one letter; DIMV sits at north) with a needle that spins and settles on your type */
const CODES = Array.from({ length: 16 }, (_, i) => { const g = i ^ (i >> 1); return ['DS', 'IP', 'MF', 'VT'].map((p, k) => p[(g >> (3 - k)) & 1]).join(''); });
function compass(svg) {
  let c = svg.querySelector('g.promo-compass'); if (c) return c;
  // hide the radar, its spokes, inner rings and the four value labels
  svg.querySelectorAll('g.radar, g.dots').forEach((e) => { e.style.display = 'none'; });
  [...svg.children].forEach((e) => {
    if (e.tagName === 'path' && /^M200 200L/.test(e.getAttribute('d') || '')) e.style.display = 'none';
    if (e.tagName === 'circle' && +e.getAttribute('r') < 40) e.style.display = 'none';
    if (e.tagName === 'text' && e.getAttribute('font-weight') === '700') e.style.display = 'none';
  });
  c = document.createElementNS(SVGNS, 'g'); c.setAttribute('class', 'promo-compass');
  let h = '';
  for (let i = 0; i < 64; i++) { const a = i / 64 * Math.PI * 2, r0 = i % 4 ? 90 : 86.5; h += '<line x1="' + (200 + Math.sin(a) * r0).toFixed(2) + '" y1="' + (200 - Math.cos(a) * r0).toFixed(2) + '" x2="' + (200 + Math.sin(a) * 93).toFixed(2) + '" y2="' + (200 - Math.cos(a) * 93).toFixed(2) + '" stroke="var(--ink-3)" stroke-width="' + (i % 4 ? .5 : .9) + '"/>'; }
  CODES.forEach((code, i) => { const a = i / 16 * Math.PI * 2; h += '<text class="pc-code" data-i="' + i + '" x="' + (200 + Math.sin(a) * 75).toFixed(2) + '" y="' + (200 - Math.cos(a) * 75 + 2.6).toFixed(2) + '" text-anchor="middle" font-size="7.2" font-family="var(--mono)" font-weight="600" fill="var(--ink-3)">' + code + '</text>'; });
  h += '<g class="pc-needle"><path d="M200 132L205.6 200H194.4Z" fill="var(--a1)"/><path d="M194.4 200H205.6L200 226Z" fill="var(--ink-3)"/></g><circle cx="200" cy="200" r="6.5" fill="var(--ink-1)"/><circle cx="200" cy="200" r="2.2" fill="var(--bg)"/>';
  c.innerHTML = h; svg.appendChild(c);
  return c;
}
// needle angle (deg, 0 = north/DIMV, clockwise): five fast turns that slow down, overshoot a little, settle — music.py
// ticks every time the needle passes a code, from the same function
const SPIN0 = 34, SPIN1 = 38;
function needleAt(b) {
  const p = clamp((b - SPIN0) / (SPIN1 - SPIN0));
  if (p < .8) return 8 - 1943 * Math.pow(1 - p / .8, 4);
  const q = (p - .8) / .2; return 8 * Math.cos(Math.PI * q * 1.5) * (1 - q);
}
function setNeedle(svg, deg, glowCode) {
  const c = compass(svg);
  c.querySelector('.pc-needle').setAttribute('transform', 'rotate(' + deg.toFixed(3) + ' 200 200)');
  c.querySelectorAll('.pc-code').forEach((t) => {
    const on = +t.dataset.i === 0 ? glowCode : 0;
    t.setAttribute('fill', on > .5 ? 'var(--a1)' : 'var(--ink-3)'); t.setAttribute('font-size', (7.2 + on * 2.4).toFixed(2));
  });
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
// 0–8 open · 8–13.5 logo · 13.5–19 numbers roll and fly into the KPI tiles · 19–23 a sparkline draws forward ·
// 23–29.5 bars grow one by one · 29.5–33.5 the bars curl into the 24-hour ring · 33.5–42.5 the compass spins to DIMV ·
// 42.5–47.5 persona lines run forward · 47.5–63.5 trajectory · 63.5–71 ask (build) · 72–88 eight features · 88–96 compass
// again · 96–106 end card. Consecutive scenes share a direction of motion or a shape, so each one flows into the next.
const L = 160, R = 1760;                                    // text margins
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
  txt(8, 13.6, [['', '<img class="mark" src="mark.svg" alt="">']], { x: 960, y: 420, align: 'c' }, {
    anim: (el, tl, life) => {
      const p = E.quart(clamp(tl / (2.2 * BEAT))), q = E.in(clamp(1 - (life - tl) / (1.2 * BEAT)));
      el.style.opacity = (p * (1 - q)).toFixed(3); el.style.filter = 'blur(' + ((1 - p) * 16 + q * 10).toFixed(1) + 'px)';
      el.style.transform = 'translate(-50%,-50%) scale(' + (lerp(1.12, 1, p) * (1 + tl * .01) * (1 - q * .12)).toFixed(4) + ')';
    }
  });
  txt(9, 13.6, [['word', 'Tandem']], { x: 960, y: 620, align: 'c' }, { inB: 1.4, outB: 1 });
  txt(10.5, 13.6, [['lt', '看见你与 Agent 的每一次协作']], { x: 960, y: 730, align: 'c' }, { inB: 1.4, outB: 1 });
  glowAt(13, .45, 2);

  // --- 1 · numbers roll, then fly into the KPI tiles they come from
  const NUMS = [[186, '', '个会话'], [142, 'h', '小时协作'], ['1,284', '', '条消息']];
  const TILES = { box: [960, 600, 1700, 420] };
  const morph = [];                                         // per number: screen offset and scale to its tile value
  at(17.3, () => {
    const T = framing(0, '.tiles', TILES.box);
    NUMS.forEach((n, i) => {
      const f = fx.find((x) => x.tag === 'num' + i); const span = f && f.el && f.el.querySelector('.odo'); if (!span) return;
      const v = decks[0].D.querySelectorAll('.tiles .vz-kpi .v')[i]; if (!v) return;
      const r = v.getBoundingClientRect(), k = stage.getBoundingClientRect().width / 1920, s0 = span.getBoundingClientRect();
      // left edges and vertical centres meet (the app's digits are narrower than the promo's, so centres would drift)
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
        const ink = Math.round(lerp(255, 23, Math.pow(m, 3)));      // white on black → the tile's ink as it lands
        o.style.color = 'rgb(' + ink + ',' + ink + ',' + Math.round(lerp(255, 27, Math.pow(m, 3))) + ')';
        o.style.transform = mv ? 'translate(' + (mv.dx * m).toFixed(1) + 'px,' + (mv.dy * m).toFixed(1) + 'px) scale(' + lerp(1, mv.sc, m).toFixed(4) + ')' : '';
        el.querySelectorAll('.odo-u, .ln.lt').forEach((x) => { x.style.opacity = (1 - E.out(lp(b, 17.2, .6))).toFixed(3); });
        el.style.transform = 'translate(-50%,-50%) translateY(' + ((1 - inP) * 40).toFixed(1) + 'px)';
        el.querySelectorAll('.ln').forEach((x) => { x.style.overflow = 'visible'; });
      }, tag: 'num' + i
    });
  });
  txt(14, 17.3, [['eb', '01 · Overview · 近 30 天']], { x: 960, y: 330, align: 'c' });
  // the tiles fade in under the flying numbers
  at(13.1, () => { app(0).go('overview'); solo(0, '.tiles'); });
  drive(0, 13.1, 19.3, (p, b, D) => D.querySelectorAll('.tiles svg.vz-spark').forEach((s, i) => drawSpark(s, i === 1 ? 0 : E.inOut(lp(b, 18.2, 1.1)))));
  // the tiles hold their final values (no count-up of their own) and the first three take over from the flying numbers
  drive(0, 13.1, 19.4, (p, b, D) => D.querySelectorAll('.tiles .vz-kpi .v').forEach((v, i) => {
    if (v.dataset.count) v.textContent = Number(v.dataset.count).toLocaleString('en-US', { maximumFractionDigits: 1 });
    v.style.opacity = i < 3 ? E.inOut(lp(b, 18.85, .3)).toFixed(3) : '';
  }));
  tween(0, 17.4, 1.6, () => framing(0, '.tiles', TILES.box), E.inOut, (T) => ({ s: T.s * .96, o: 0, bl: 4 }));
  // --- 2 · into the 协作时长 tile: its line runs forward
  tween(0, 19.1, 1.6, () => framing(0, '.tiles > .vz-kpi:nth-child(2)', [960, 560, 1400, 700], { max: 8 }), E.inOut);
  drive(0, 19.8, 22.6, (p, b, D) => drawSpark(D.querySelectorAll('.tiles svg.vz-spark')[1], E.inOut(p)));
  tween(0, 20.7, 2.5, () => ({ s: decks[0].C.s * 1.05, ax: decks[0].C.ax - 60 }), E.sine);
  txt(19.8, 22.8, [['eb', '协作时长 · 近 12 周']], { x: 960, y: 120, align: 'c' });
  tween(0, 22.8, 1, () => OUT.toL(decks[0].C), E.in);

  // --- 3 · keep moving right: the trend chart slides in and its bars grow one by one
  const trend = byText('.card.pad', 'Agent 使用趋势');
  const bars = (D) => { const c = trend(D); return c && c.querySelector('svg.vz-t-bar'); };
  at(22.4, () => { const a = app(1); a.S.ov.stack = 'stacked'; a.go('overview'); solo(1, trend); });
  drive(1, 22.45, 27.6, (p, b, D) => { const s = bars(D); if (s) growBars(s, b, 23.2, .12, .55); });
  tween(1, 22.9, 1.2, () => framing(1, bars, [960, 560, 1700, 820], { max: 6, px: .2, zoom: 1.55 }), E.quart, IN.fromR);
  tween(1, 24.1, 3, () => framing(1, bars, [960, 560, 1700, 820], { max: 6, px: .82, zoom: 1.55 }), E.inOut);
  txt(23.4, 26.9, [['eb', '每日会话 · 按 Agent 堆叠']], { x: 960, y: 120, align: 'c' });
  tween(1, 27.1, 1.5, () => framing(1, trend, [1250, 540, 1060, 820]), E.inOut);
  txt(27.7, 29.6, [['eb', 'Agents'], ['gap'], ['hv sv', '五个 Agent'], ['md acc', '一张图对齐']], { x: L, y: 540 });
  // --- 4 · the bars curl into the 24-hour ring
  tween(1, 29.5, 2, () => ({ rz: -75, s: decks[1].C.s * .55, o: 0, bl: 6, ax: 900 }), E.inOut);
  const fp = '.persona-hero svg.fp2';
  at(29.1, () => { app(0).go('persona'); solo(0, fp); });
  drive(0, 29.15, 33.4, (p, b, D) => { const s = D.querySelector(fp); if (!s) return; growRing(s, b, 30, .13, .7); const c = compass(s); c.style.opacity = E.inOut(lp(b, 33.2, 1.2)).toFixed(3); setNeedle(s, needleAt(b), 0); });
  tween(0, 29.6, 2.2, () => framing(0, fp, [700, 540, 880, 880]), E.inOut, (T) => ({ rz: 80, s: T.s * .55, o: 0, bl: 6 }));
  tween(0, 31.8, 1.8, () => ({ rz: -6 }), E.sine);
  txt(30.6, 33.4, [['eb', 'Rhythm'], ['gap'], ['hv sv', '24 小时'], ['md acc', '你什么时候在协作']], { x: R, y: 540, align: 'r' }, { st: .25 });
  // --- 5 · into the centre: the compass spins and settles on your type
  drive(0, 33.4, 38.6, (p, b, D) => { const s = D.querySelector(fp); if (!s) return; compass(s).style.opacity = E.inOut(lp(b, 33.2, 1.2)).toFixed(3); setNeedle(s, needleAt(b), E.out(lp(b, 37.4, .8))); });
  tween(0, 33.5, 2, () => framing(0, fp, [960, 540, 1200, 1200], { max: 9, zoom: 2.05 }), E.inOut);
  tween(0, 33.5, 4.5, () => ({ rz: 0 }), E.out);
  txt(33.4, 34.6, [['md sv', '你的协作人格'], ['md acc', '指向哪里？']], { x: R, y: 540, align: 'r' }, { st: .2, outB: .5 });
  tween(0, 38.4, 1.8, () => framing(0, fp, [700, 540, 860, 860]), E.inOut);
  txt(38.9, 42.6, [['eb', 'Your type'], ['gap'], ['xl sv', '<span class="serif">DIMV</span>'], ['md', '指挥家 <span class="serif acc"><i>The Conductor</i></span>'], ['gap'], ['lt', '委托 72 · 即兴 61 · 多线 73 · 求证 67']], { x: R, y: 540, align: 'r' }, { st: .2 });
  tween(0, 40.2, 2.4, () => ({ s: decks[0].C.s * 1.03 }), E.sine);
  tween(0, 42.6, 1, () => OUT.toL(decks[0].C), E.in);
  // --- 6 · the four dimensions month by month: the lines run forward
  const evo = '.persona-hero svg.vz-t-line';
  at(42.3, () => { app(1).go('persona'); solo(1, evo); });
  drive(1, 42.3, 47.6, (p, b, D) => { const s = D.querySelector(evo); if (s) s.classList.add('promo-card'); });
  drive(1, 42.35, 46.2, (p, b, D) => { const s = D.querySelector(evo); if (s) drawForward(s, E.inOut(lp(b, 43.2, 3)), 30, 408); });
  tween(1, 42.8, 1.2, () => framing(1, evo, [1230, 560, 1120, 640], { max: 3, px: .42 }), E.quart, IN.fromR);
  tween(1, 44, 2.6, () => framing(1, evo, [1230, 560, 1120, 640], { max: 3, px: .56 }), E.inOut);
  txt(43.3, 47.4, [['eb', 'Evolution'], ['gap'], ['hv sv', '人格也在成长'], ['md acc', '每个月重算一次'], ['gap'], ['lt', '<span class="mono">SIFV → DIFV → DIMV</span>']], { x: L, y: 540 }, { st: .3 });
  tween(1, 47.4, .9, () => OUT.up(decks[1].C), E.in);

  // --- trajectory: the playhead runs forward too
  shot(0, 47.6, 55.4, { sel: '.tl-card', box: [1310, 540, 1040, 900], inn: 'plane', inDur: 2, out: 'up', pan: -40, push: 1.05, prep: (a) => a.go('sessions') });
  at(48.2, () => app(0).click('[data-act="playToggle"]'));
  txt(48.2, 55.4, [['eb', '02 · Trajectory'], ['gap'], ['hv sv', '卡在哪一刻'], ['md acc', '逐秒回放，一眼看清']], { x: L, y: 540 }, { st: .3 });
  shot(1, 55.6, 63.2, { sel: byText('.card.pad.col', '这次会话的启示'), box: [1300, 540, 700, 860], inn: 'rise', out: 'up', prep: (a) => a.go('sessions') });
  txt(56, 63.2, [['eb', 'Insight'], ['gap'], ['hv sv', '下次怎么做'], ['md acc', '复盘直接给出改法']], { x: L, y: 540 }, { st: .3 });

  // --- ask the local agent (build)
  shot(0, 63.5, 71, { sel: '#modal', box: [1310, 560, 980, 760], inn: 'rise', inDur: 1.4, out: 'near', outDur: 1, push: 1.14, prep: (a) => { a.go('overview'); a.W.openAsk('overview'); } });
  clickAt(0, 64.8, '[data-act="askPick"]', (a, el) => a.click(el));
  glowAt(63.5, .5, 2);
  txt(64, 71, [['eb', '03 · Ask'], ['gap'], ['hv sv', '问你自己的'], ['hv ai', '本地 Agent'], ['gap'], ['lt', '数据不出本机 · 0 B 上传']], { x: L, y: 540 }, { st: .5 });
  glowAt(70.5, 0, 1.5);

  // --- eight features, two beats each (急): component and a word, alternating sides and copies
  const feat = (i, sel, word, sub, prep, o = {}) => {
    const b = 72 + i * 2, right = i % 2 === 0, d = (i + 1) % 2;
    shot(d, b - .3, b + 1.75, Object.assign({ sel, box: o.box || (right ? [1330, 540, 920, 760] : [590, 540, 920, 760]), inn: right ? 'fromR' : 'fromL', inDur: .8, out: right ? 'toL' : 'toR', outDur: .6, prep, lead: o.lead || .3, push: 1.03 }, o));
    txt(b, b + 1.75, [['hv sv', word], ['lt acc', sub]], o.tpos || (right ? { x: L, y: 540 } : { x: R, y: 540, align: 'r' }), { inB: .7, outB: .45, st: .12 });
  };
  at(70.4, () => { const a = app(1); a.go('studio'); a.click('[data-act="studioStart"]'); });
  feat(0, (D) => D.querySelectorAll('#main .card.pad.col')[1], '生成工坊', '把建议变成 Skill、Hook 与规则', null);
  feat(1, '.rcard.sel', '12 条建议', '每月约省下 20 小时', (a) => a.go('recs'));
  feat(2, trend, '深色模式', '跟随系统外观', (a) => { a.S.ov.stack = 'stacked'; a.go('overview'); });
  at(76.9, () => app(1).W.setTheme('dark'));
  feat(3, '.edsw', 'Lite / Advance', '一键切换 · ⌃⌘L', (a) => { a.W.closeModal(); a.go('overview'); }, { box: [960, 400, 1000, 300], max: 4, tpos: { x: 960, y: 700, align: 'c' } });
  clickAt(0, 78.9, '[data-act="edition"][data-v="lite"]', (a) => a.W.edSet('lite'));
  feat(4, '#notes .nt', '第一时间提醒', '会话等你确认时', (a) => { a.W.setTheme('light'); a.go('overview'); a.D.querySelectorAll('#notes .nt').forEach((n) => n.remove()); a.W.simEvent('waiting'); }, { max: 3, lead: .5 });
  feat(5, '#modal', '⌘K', '任何页面、会话与操作', (a) => { a.W.edSet('advance'); a.W.openPalette(); }, { lead: .5 });
  feat(6, '#hud', '悬浮组件', '会话运行时，陪在桌面一角', (a) => { a.S.hud.show = true; a.S.sim = 'running'; a.render(); }, { max: 3.2 });
  feat(7, '#widgets', '桌面小组件', '人格 · 今日 · 本周 · 最值得做', (a) => { a.W.closeModal(); a.S.widgets = true; a.go('overview'); }, { out: 'far' });

  // --- close on the compass, still pointing at you (缓)
  shot(1, 88, 95, { sel: fp, box: [960, 470, 700, 700], inn: 'depth', inDur: 2.4, out: 'far', outDur: 1.4, rz: -10, turn: 22, push: 1.06,
    prep: (a) => { a.W.closeModal(); a.S.widgets = false; a.S.hud.show = false; a.W.edSet('advance'); a.go('persona'); }, lead: .8 });
  drive(1, 87.3, 96.5, (p, b, D) => { const s = D.querySelector(fp); if (s) setNeedle(s, 5 * Math.sin((b - 88) * .9) * Math.exp(-(b - 88) * .15), 1); });
  glowAt(88, .7, 3);
  txt(89.5, 95, [['md sv', '只读本地日志'], ['md acc', '数据不出本机'], ['gap'], ['eb', 'local-first · 0 B uploaded']], { x: 960, y: 950, align: 'c' }, { st: .4 });
  glowAt(95, 0, 1);

  // --- end card
  glowAt(96, 1, 3);
  txt(96, 105.6, [['', '<img class="mark" src="mark.svg" alt="">']], { x: 960, y: 420, align: 'c' }, {
    anim: (el, tl, life) => {
      const p = E.quart(clamp(tl / (2.4 * BEAT))), q = E.inOut(clamp((life - tl) / (2 * BEAT)));
      el.style.opacity = (p * q).toFixed(3); el.style.filter = 'blur(' + ((1 - p) * 16 + (1 - q) * 8).toFixed(1) + 'px)';
      el.style.transform = 'translate(-50%,-50%) scale(' + (lerp(.9, 1, p) * (1 + tl * .008)).toFixed(4) + ')';
    }
  });
  txt(97, 105.6, [['word', 'Tandem']], { x: 960, y: 620, align: 'c' }, { inB: 1.5, outB: 2 });
  txt(98.5, 105.6, [['lt', '看见你与 Agent 的每一次协作']], { x: 960, y: 730, align: 'c' }, { inB: 1.5, outB: 2 });
  txt(100.5, 105.6, [['eb', 'for macOS · ActionMesh AI']], { x: 960, y: 810, align: 'c' }, { inB: 1.5, outB: 2 });
  glowAt(103.5, 0, 2.5);
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
  applyDrives(t); applyCams(t); applyCursors(t); applyFx(t); applyGlow(t);
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
decks.forEach((k) => k.frame.addEventListener('load', () => {
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

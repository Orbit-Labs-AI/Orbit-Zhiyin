/* Tandem promo: a beat-locked timeline. Two live copies of the app take turns showing ONE component each (everything
   else in that copy is hidden), framed by a virtual camera next to the copy that explains it. Transitions overlap the
   outgoing and incoming component with long eases; there are no beat-synced shakes or flashes.
   Everything is a pure function of the master time t (seconds), so the page plays in real time with the soundtrack
   (preview) or frame by frame on Playwright's fake clock (render.mjs). Times are written in beats. */
'use strict';
const BPM = 124, BEAT = 60 / BPM, END = 118;              // beats; music.py uses the same grid
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
  fx.push({ b0, b1, html, style, base: 'translate(' + ({ l: '0', c: '-50%', r: '-100%' })[al] + ',-50%)', anim: o.anim || mask(o.st ?? .18, o.inB || 1, o.outB || .6, o.spread), tick: o.tick, tag: o.tag, el: null });
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
// a chart drawn forward by a clip that slides from x0 to the head (svg units); sel = what the clip covers
function clipTo(svg, x0, head, sel) {
  let cp = svg.querySelector('#promoClip');
  if (!cp) {
    cp = document.createElementNS(SVGNS, 'clipPath'); cp.id = 'promoClip';
    const r = document.createElementNS(SVGNS, 'rect'); r.setAttribute('y', '-40'); r.setAttribute('height', '600'); r.setAttribute('x', String(x0 - 8));
    cp.appendChild(r); svg.appendChild(cp);
    svg.querySelectorAll(sel).forEach((e) => { e.style.animation = 'none'; e.setAttribute('clip-path', 'url(#promoClip)'); });
  }
  cp.firstChild.setAttribute('width', String(Math.max(0, head - x0 + 8)));
}
// rect bars of a chart rise from their baseline as the head passes them
function riseRects(svg, head, base) {
  svg.querySelectorAll('rect.vz-bar').forEach((r) => {
    const x = +r.getAttribute('x'), k = clamp((head - x) / 40);
    r.style.animation = 'none'; r.style.transformBox = 'view-box'; r.style.transformOrigin = '0px ' + base + 'px';
    r.style.transform = k >= 1 ? '' : 'scaleY(' + E.out(k).toFixed(4) + ')';
  });
}

/* ---------- tags: text attached to a component, inside its copy of the app ----------
   A tag lives in the deck's rig, so it tilts, turns and slides with the component it describes; it is anchored to one
   edge of that component (top / bottom / left / right, plus an along-edge share) and counter-scaled by the camera so
   its type keeps its size on screen. This is what keeps words and components from ever overlapping. */
const tags = [];
function tag(d, b0, b1, sel, side, lines, o = {}) {
  const html = lines.map(([c, h]) => (c === 'gap' ? '<div class="gap"></div>' : '<span class="ln ' + c + '"><span>' + h + '</span></span>')).join('');
  tags.push({ d, b0, b1, sel, side, html, o, el: null, anim: o.anim || mask(o.st ?? .14, o.inB || .9, o.outB || .5) });
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
    g.anim(g.el, t - t0, t1 - t0, t);
    if (g.o.tick) g.o.tick(g.el, t - t0, t1 - t0, t);
  }
}

/* ---------- the persona compass (deck 2) ----------
   Same geometry as the app's compass dial (fp2SVG in 41-a2-persona.js, the spec shared with the "Lite/Advanced UI 协调与
   动效设计" and "16型人格名称" sessions): bezel with 120 ticks and 24-hour bearings, a rose whose four major points face the
   D I M V axes (length = strength, the tip shows the winning pole), four short minor points, a double-diamond needle.
   For the film the needle is the selector: the 16 types sit on 16 bearings (Gray-code order, so neighbours differ by one
   letter and the rose morphs smoothly; your type sits at north), and as the needle sweeps, the rose, the tip letters
   and the aurora around the dial follow it continuously. The aurora is the 24-hour rhythm drawn as six thin ribbons
   with a soft body, in the Orbit steel-blue range; it swells where the needle is, and the faster the needle moves the
   further the swell runs ahead and behind it. The five Agents are the planets on it. */
const CP = { C: 400, R0: 250, BAND: 80, RR: 140, NL: 112 };
const AXR2 = { D: 0, I: 90, M: 180, V: 270 };
const cpt = (r, deg) => [CP.C + r * Math.sin(deg * Math.PI / 180), CP.C - r * Math.cos(deg * Math.PI / 180)];
const f2 = (q) => q[0].toFixed(1) + ' ' + q[1].toFixed(1);
const roseLen = (strong) => CP.RR * (.36 + .64 * clamp((strong - 50) / 35));
function rosePt(deg, len, w) { const tip = cpt(len, deg), r = cpt(w, deg + 45), l = cpt(w, deg - 45); return ['M400 400L' + f2(tip) + 'L' + f2(r) + 'Z', 'M400 400L' + f2(tip) + 'L' + f2(l) + 'Z']; }
function axisOf(v, i) { const ax = CPD.AXES[i], val = v[ax.k], pos = ax.k !== 'I' ? 100 - val : val; return { strong: Math.max(val, 100 - val), letter: pos < 50 ? ax.L : ax.R }; }
const CODES = Array.from({ length: 16 }, (_, i) => { const g = i ^ (i >> 1); return ['DS', 'IP', 'MF', 'VT'].map((p, k) => p[(g >> (3 - k)) & 1]).join(''); });   // CODES[0] = DIMV
function archetype(code) {
  const h = [...code].reduce((a, c) => a * 31 + c.charCodeAt(0), 7), j = (k) => ((h >> (k * 3)) & 7) - 3, s = (k) => 78 + j(k);
  return { D: code[0] === 'D' ? s(0) : 100 - s(0), I: code[1] === 'I' ? s(1) : 100 - s(1), M: code[2] === 'M' ? s(2) : 100 - s(2), V: code[3] === 'V' ? s(3) : 100 - s(3) };
}
function rhythm(code) {                                     // 24 hourly totals (0..1.6) for an archetype
  const peak = code[1] === 'P' ? 10.5 : 21.5, peak2 = code[0] === 'D' ? 15.5 : 13, wd = code[2] === 'M' ? 3.4 : 2.1;
  const g = (h, c) => { const d = Math.min(Math.abs(h - c), 24 - Math.abs(h - c)); return Math.exp(-d * d / (2 * wd * wd)); };
  return Array.from({ length: 24 }, (_, h) => .12 + g(h, peak) + .7 * g(h, peak2));
}
const AGC = ['var(--a1)', 'var(--a2)', 'var(--a3)', 'var(--a4)', 'var(--a5)'];
const RIB = ['#1d4a57', '#2a6c7d', '#3f93a6', '#6cb8c8', '#a8d9e3', '#eaf7f9'];      // deep teal → ice, inner → outer
let CPD = null;
function compassData() {
  if (CPD) return CPD;
  const W = decks[0].W;
  const L = W.eval('sel({ noExtra: true })'), ids = W.eval('AG').map((a) => a.id);
  const tot = new Array(24).fill(0); L.forEach((s) => { tot[s.h]++; });
  const mx = Math.max(...tot);
  const head = (xs) => { let a = 0, c = 0; xs.forEach((s) => { const r = (s.h + s.mi / 60) / 24 * Math.PI * 2; a += Math.sin(r); c += Math.cos(r); }); return (Math.atan2(a, c) * 180 / Math.PI + 360) % 360; };
  CPD = { TYPES: W.eval('TYPES'), AXES: W.eval('AXES'), me: W.eval('persona(sel({ noExtra: true }))'), rh: tot.map((x) => x / mx * 1.6), ahd: ids.map((id) => head(L.filter((s) => s.a === id))) };
  return CPD;
}
// the persona at a needle bearing: a smooth blend of the two nearest types (index = bearing / 22.5)
function personaAt(deg, mine) {
  const D = compassData(), u = (((deg % 360) + 360) % 360) / 22.5, i0 = Math.floor(u) % 16, i1 = (i0 + 1) % 16, f = E.inOut(u - Math.floor(u));
  const a = archetype(CODES[i0]), b = archetype(CODES[i1]), ra = rhythm(CODES[i0]), rb = rhythm(CODES[i1]);
  const v = {}; for (const k of 'DIMV') v[k] = lerp(a[k], b[k], f);
  let rh = ra.map((x, h) => lerp(x, rb[h], f));
  if (mine > 0) { for (const k of 'DIMV') v[k] = lerp(v[k], D.me.v[k], mine); rh = rh.map((x, h) => lerp(x, D.rh[h], mine)); }
  return { v, rh, code: CODES[Math.round(u) % 16] };
}
function buildCompass() {
  const k = decks[2]; if (k.svg) return k.svg;
  compassData();
  const W = 'rgba(255,255,255,';
  const tk = ['', '', '']; for (let i = 0; i < 120; i++) { const w = i % 30 === 0 ? 2 : i % 5 === 0 ? 1 : 0; tk[w] += 'M' + f2(cpt(389, i * 3)) + 'L' + f2(cpt([381, 375, 368][w], i * 3)); }
  const h = '<defs><radialGradient id="cpFace"><stop offset="0" stop-color="' + W + '.06)"/><stop offset=".75" stop-color="' + W + '.025)"/><stop offset="1" stop-color="' + W + '0)"/></radialGradient>' +
    '<radialGradient id="cpBody" cx="400" cy="400" r="340" gradientUnits="userSpaceOnUse"><stop offset=".72" stop-color="#123843" stop-opacity="0"/><stop offset=".78" stop-color="#1f6577" stop-opacity=".75"/><stop offset=".9" stop-color="#4fb3c8" stop-opacity=".45"/><stop offset="1" stop-color="#eaf7f9" stop-opacity="0"/></radialGradient>' +
    '<filter id="cpSoft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="5"/></filter></defs>' +
    '<g class="cp-dial"><circle cx="400" cy="400" r="396" fill="url(#cpFace)" stroke="' + W + '.5)" stroke-width="2"/><circle cx="400" cy="400" r="390" fill="none" stroke="' + W + '.15)"/>' +
    '<path d="' + tk[0] + '" stroke="' + W + '.2)"/><path d="' + tk[1] + '" stroke="' + W + '.42)" stroke-width="1.4"/><path d="' + tk[2] + '" stroke="#fff" stroke-width="2.4"/>' +
    '<path d="M400 8L390 -10L410 -10Z" fill="var(--orbit)"/>' +
    [0, 3, 6, 9, 12, 15, 18, 21].map((hh) => { const card = hh % 6 === 0, q = cpt(card ? 343 : 352, hh * 15); return '<text x="' + q[0].toFixed(1) + '" y="' + q[1].toFixed(1) + '" text-anchor="middle" dominant-baseline="central" class="' + (card ? 'cp-hc' : 'cp-hs') + '">' + String(hh).padStart(2, '0') + '</text>'; }).join('') + '</g>' +
    '<g id="cpAur"><path class="body" fill="url(#cpBody)" fill-rule="evenodd"/><path class="glow" fill="none" stroke="#ffd9b8" stroke-width="9" stroke-linecap="round" filter="url(#cpSoft)" opacity=".8"/>' + RIB.map((c, i) => '<path class="rib" fill="none" stroke="' + c + '" stroke-width="' + (2 + i * .5).toFixed(2) + '" stroke-opacity="' + (.7 + i * .05).toFixed(2) + '"/>').join('') + '</g>' +
    '<g id="cpPlanets">' + AGC.map((c) => '<g class="pl"><circle r="16" fill="' + c + '" opacity=".2"/><circle r="7.5" fill="' + c + '" stroke="#000" stroke-width="2"/></g>').join('') + '</g>' +
    '<g class="cp-core"><circle cx="400" cy="400" r="184" fill="rgba(8,9,11,.94)" stroke="' + W + '.2)"/><circle cx="400" cy="400" r="' + CP.RR + '" fill="none" stroke="' + W + '.1)" stroke-dasharray="2 6"/><path d="M400 220V580M220 400H580" stroke="' + W + '.1)" stroke-width="1.4"/>' +
    [45, 135, 225, 315].map((d) => { const x = rosePt(d, CP.RR * .4, CP.RR * .1); return '<path d="' + x[0] + '" fill="' + W + '.5)"/><path d="' + x[1] + '" fill="none" stroke="' + W + '.5)" stroke-width="1.4" stroke-linejoin="round"/>'; }).join('') + '</g>' +
    '<g id="cpRose">' + 'DIMV'.split('').map((x) => '<g class="pt" data-k="' + x + '"><path class="a" fill="#f4f4f6"/><path class="b" fill="rgba(8,9,11,.9)" stroke="#f4f4f6" stroke-width="2.2" stroke-linejoin="round"/></g>').join('') + '</g>' +
    '<g id="cpNeedle"><path d="M400 ' + (400 - CP.NL) + 'L406 400L394 400Z" fill="var(--orbit)"/><path d="M400 ' + (400 + CP.NL) + 'L406 400L394 400Z" fill="rgba(8,9,11,.9)" stroke="var(--orbit)" stroke-width="2"/></g>' +
    '<g id="cpLbl">' + 'DIMV'.split('').map((x) => '<g class="lb" data-k="' + x + '"><text class="cp-l" text-anchor="middle" dominant-baseline="central"></text><text class="cp-s" text-anchor="middle" dominant-baseline="central"></text></g>').join('') + '</g>' +
    '<g id="cpTip"><text class="cp-tc" text-anchor="middle" dominant-baseline="central"></text><text class="cp-tn" text-anchor="middle" dominant-baseline="central"></text></g>' +
    '<circle class="cp-hub" cx="400" cy="400" r="14" fill="#08090b" stroke="#fff" stroke-width="2.6"/><circle class="cp-hub" cx="400" cy="400" r="4" fill="#fff"/>';
  const svg = document.createElementNS(SVGNS, 'svg'); svg.setAttribute('viewBox', '0 0 800 800'); svg.setAttribute('width', '800'); svg.setAttribute('height', '800'); svg.setAttribute('class', 'compass');
  svg.style.overflow = 'visible'; svg.innerHTML = h; k.rig.appendChild(svg); k.svg = svg;
  return svg;
}
/* st: { deg: needle bearing, mine: 0..1 blend to your real persona, speed: needle deg/beat, grow, sweep (aurora reveal),
   orbit (planet phase), settle (planets to their headings), dial, core, collapse (aurora → one ring), tip (needle label) } */
function drawCompass(st) {
  const svg = buildCompass(), P = personaAt(st.deg, st.mine || 0);
  // aurora: radius profile = rhythm (Catmull-Rom over the hours) + a swell around the needle that stretches with speed
  const N = 240, rh = P.rh, val = (hh) => { const i = Math.floor(hh), f = hh - i, a = rh[(i + 23) % 24], b = rh[i % 24], c = rh[(i + 1) % 24], d = rh[(i + 2) % 24]; return .5 * (2 * b + (-a + c) * f + (2 * a - 5 * b + 4 * c - d) * f * f + (-a + 3 * b - 3 * c + d) * f * f * f); };
  const sp = Math.min(1, Math.abs(st.speed || 0) / 260), sig = 16 + 40 * sp, col = clamp(st.collapse || 0);
  const prof = []; for (let s = 0; s <= N; s++) {
    const a = s / N * 360, dd = ((a - st.deg) % 360 + 540) % 360 - 180;
    const swell = (.45 + .55 * sp) * Math.exp(-dd * dd / (2 * sig * sig)) + .18 * sp * Math.exp(-(dd + sig) * (dd + sig) / (2 * sig * sig * 2.5)) * Math.sin(dd / 6);
    prof.push(Math.max(.04, (val(a / 15) / 1.6 * .75 + swell * .55)) * (1 - col));
  }
  const ring = (k) => { let d = ''; for (let s = 0; s <= N; s++) d += (s ? 'L' : 'M') + f2(cpt(lerp(CP.R0 + CP.BAND * prof[s] * k, 300, col), s / N * 360)); return d + 'Z'; };
  const sw = clamp(st.sweep ?? 1);
  const ribs = svg.querySelectorAll('#cpAur .rib');
  ribs.forEach((p, i) => { p.setAttribute('d', ring(Math.pow((i + 1) / RIB.length, .85))); p.style.strokeDasharray = sw < 1 ? (sw * 2400).toFixed(0) + ' 4000' : ''; });
  svg.querySelector('#cpAur .body').setAttribute('d', ring(1) + ring(0));
  svg.querySelector('#cpAur .body').style.opacity = (sw * (1 - col)).toFixed(3);
  // the bright crest that rides on the outer ribbon at the needle
  let gd = ''; for (let s = -24; s <= 24; s++) { const a = st.deg + s * (1.2 + sp), idx = Math.round((((a % 360) + 360) % 360) / 360 * N); gd += (s > -24 ? 'L' : 'M') + f2(cpt(CP.R0 + CP.BAND * prof[idx] + 2, a)); }
  const gl = svg.querySelector('#cpAur .glow'); gl.setAttribute('d', gd); gl.style.opacity = (.35 + .55 * sp) * sw * (1 - col) * (st.dial ?? 1);
  // planets
  svg.querySelectorAll('#cpPlanets .pl').forEach((g, i) => {
    const run = (st.orbit || 0) + i * 23, rest = CPD.ahd[i], k = clamp(st.settle || 0);
    const a = run + ((((rest - run) % 360) + 540) % 360 - 180) * E.inOut(k), q = cpt(lerp(CP.R0 + CP.BAND * .5, 300, col), a);
    g.setAttribute('transform', 'translate(' + f2(q) + ')'); g.style.opacity = (clamp(sw * 2 - i * .2) * (1 - col)).toFixed(3);
  });
  // rose and its tip letters
  const gr = clamp(st.grow ?? 1);
  'DIMV'.split('').forEach((x, i) => {
    const a = axisOf(P.v, i), len = Math.max(1, roseLen(a.strong) * E.out(clamp(gr * 1.5 - i * .15))), q = rosePt(AXR2[x], len, CP.RR * .18);
    const g = svg.querySelector('#cpRose .pt[data-k="' + x + '"]'); g.querySelector('.a').setAttribute('d', q[0]); g.querySelector('.b').setAttribute('d', q[1]);
    const lb = svg.querySelector('#cpLbl .lb[data-k="' + x + '"]'), tip = cpt(len + 30, AXR2[x]), sc = [tip[0], tip[1] + (AXR2[x] === 0 ? -30 : 30)];
    const t1 = lb.querySelector('.cp-l'), t2 = lb.querySelector('.cp-s');
    t1.setAttribute('x', tip[0].toFixed(1)); t1.setAttribute('y', tip[1].toFixed(1)); t1.textContent = a.letter;
    t2.setAttribute('x', sc[0].toFixed(1)); t2.setAttribute('y', sc[1].toFixed(1)); t2.textContent = Math.round(a.strong);
    lb.style.opacity = (gr * (st.core ?? 1)).toFixed(3);
  });
  svg.querySelector('#cpNeedle').setAttribute('transform', 'rotate(' + st.deg.toFixed(2) + ' 400 400)');
  svg.querySelector('#cpNeedle').style.opacity = (st.needle ?? 1) * (st.core ?? 1);
  // the type under the needle, written just outside the bezel at the needle's bearing
  const tp = svg.querySelector('#cpTip'), tq = cpt(452, st.deg), tc = tp.querySelector('.cp-tc'), tn = tp.querySelector('.cp-tn');
  tc.setAttribute('x', tq[0].toFixed(1)); tc.setAttribute('y', (tq[1] - 14).toFixed(1)); tn.setAttribute('x', tq[0].toFixed(1)); tn.setAttribute('y', (tq[1] + 18).toFixed(1));
  const code = (st.mine || 0) > .5 ? CPD.me.code : P.code; tc.textContent = code; tn.textContent = '';
  tp.style.opacity = (st.tip ?? 0).toFixed(3);
  svg.querySelector('.cp-dial').style.opacity = (st.dial ?? 1).toFixed(3);
  svg.querySelectorAll('.cp-core, #cpRose, .cp-hub').forEach((e) => { e.style.opacity = (st.core ?? 1).toFixed(3); });
}
// needle bearing during the sweep: slow start, two and a half fast turns, a long slow arrival at north (your type)
const SW0 = 37, SW1 = 46;
function sweepAt(b) {
  if (b < SW0) return -150;
  const p = lp(b, SW0, SW1 - SW0), e = p < .5 ? 16 * Math.pow(p, 5) : 1 - Math.pow(-2 * p + 2, 5) / 2;     // quintic in-out
  const total = 1080 + 150;                                 // from -150° through about three and a half turns to north
  return -150 + total * e + (b > SW1 ? 4 * Math.sin((b - SW1) * 5) * Math.exp(-(b - SW1) * 2.2) : 0);
}

/* ---------- the Orbit mark, live ----------
   The same conical spiral as docs/design/logo/generate.py, variant "spiral" (1.6 turns, radius 9 → 16, rise 14, phase
   0.6, seen at yaw 20° / pitch 45° — the app icon), drawn as a tapered line so it can be traced, turned in 3D and seen
   from above (pitch 90° = a flat spiral whose outer turn is a near circle).
   Open: the five Agent planets fall onto its tail, it is traced, it tips over to a top view and the camera spirals down
   into the hole in its middle, where the first scene is waiting. Close: the compass aurora collapses to one ring, the
   ring grows its inner turn back (a flat spiral seen from above), and the spiral rises into the icon. */
const ORB = { turns: 1.6, r0: 9, r1: 16, rise: 14, phase: .6, N: 260, TAPER: .12 };
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
// o = { t0, t: drawn span 0..1 along the curve, yaw, pitch, R: px per unit, cx, cy, w, a, head }
function orbitSVG(o) {
  if (!o || o.a <= .001) return '';
  const p = orbitPts(o.yaw, o.pitch), n0 = Math.min(ORB.N - 1, Math.round((o.t0 || 0) * ORB.N)), n = Math.min(ORB.N, Math.max(n0 + 1, Math.round(o.t * ORB.N)));
  const z0 = Math.min(...p.map((q) => q[2])), z1 = Math.max(...p.map((q) => q[2]));
  const L = 6, X = (q) => (o.cx + q[0] * o.R).toFixed(1) + ' ' + (o.cy + q[1] * o.R).toFixed(1);
  const lvl = (k) => Math.min(L - 1, Math.floor(((p[k][2] + p[k + 1][2]) / 2 - z0) / (z1 - z0 || 1) * L));
  const runs = []; let cur = null;
  for (let k = n0; k < n; k++) { const v = lvl(k); if (!cur || cur.v !== v) { cur = { v, k0: k, k1: k }; runs.push(cur); } else cur.k1 = k; }
  runs.sort((a, b) => a.v - b.v);
  let h = '<g opacity="' + o.a.toFixed(3) + '" fill="none" stroke-linecap="round" stroke-linejoin="round">';
  for (const r of runs) {
    let d = 'M' + X(p[r.k0]); for (let k = r.k0 + 1; k <= r.k1 + 1; k++) d += 'L' + X(p[k]);
    const h0 = Math.min(r.k1, r.k0 + 3), h1 = Math.max(h0, r.k1 - 2); let dh = 'M' + X(p[h0]); for (let k = h0 + 1; k <= h1 + 1; k++) dh += 'L' + X(p[k]);
    const end = Math.min(1, Math.min(r.k0 - n0 + (n0 ? 99 : 0), n - r.k1) / ORB.N / ORB.TAPER + .35), w = (o.w * .45 + o.w * .55 * (r.v + .5) / L) * end;
    h += (h1 > h0 ? '<path d="' + dh + '" stroke="#000" stroke-width="' + (w + 10).toFixed(1) + '"/>' : '') + '<path d="' + d + '" stroke="' + (o.color || '#e9eaee') + '" stroke-width="' + w.toFixed(1) + '"/>';
  }
  if (o.head > .01 && n < ORB.N) { const q = X(p[n]).split(' '); h += '<circle cx="' + q[0] + '" cy="' + q[1] + '" r="' + (o.w * 1.6).toFixed(1) + '" fill="url(#orbGlow)" opacity="' + o.head.toFixed(3) + '"/><circle cx="' + q[0] + '" cy="' + q[1] + '" r="' + (o.w * .55).toFixed(1) + '" fill="#fff" opacity="' + o.head.toFixed(3) + '"/>'; }
  return h + '</g>';
}
function planetsSVG(o) {
  if (!o || o.a <= .001) return '';
  return '<g opacity="' + o.a.toFixed(3) + '">' + AGC.map((c, i) => {
    const a = (o.phase + i * 72) * Math.PI / 180, x = o.cx + Math.cos(a) * o.rx * (1 - o.pull), y = o.cy + Math.sin(a) * o.ry * (1 - o.pull);
    const tx = lerp(x, o.tx, o.pull), ty = lerp(y, o.ty, o.pull);
    return '<circle cx="' + tx.toFixed(1) + '" cy="' + ty.toFixed(1) + '" r="16" fill="' + c + '" opacity=".18"/><circle cx="' + tx.toFixed(1) + '" cy="' + ty.toFixed(1) + '" r="7" fill="' + c + '"/>';
  }).join('') + '<ellipse cx="' + o.cx + '" cy="' + o.cy + '" rx="' + (o.rx * (1 - o.pull)).toFixed(1) + '" ry="' + (o.ry * (1 - o.pull)).toFixed(1) + '" fill="none" stroke="rgba(255,255,255,.14)" stroke-dasharray="2 7"/></g>';
}
const OPEN = { trace: 7.9, tilt: 11.4, dive: 12.8, end: 14.6 };
const CLOSE = { ring: 105.8, rise: 107.6, settle: 110 };
function orbitAt(b) {
  let h = '';
  if (b >= 5.6 && b < 8.6) {
    const start = orbitPts(-25, 72)[0];
    h += planetsSVG({ a: E.out(lp(b, 5.6, .8)) * (1 - E.in(lp(b, 8.1, .5))), phase: (b - 5.6) * 95, cx: 960, cy: 790, rx: 380, ry: 64, pull: E.inOut(lp(b, 7.5, 1)), tx: 960 + start[0] * 215, ty: 410 + start[1] * 215 });
  }
  if (b >= OPEN.trace && b < OPEN.end) {
    const turn = E.out(lp(b, OPEN.trace, 3.4)), tilt = E.inOut(lp(b, OPEN.tilt, OPEN.dive - OPEN.tilt)), dive = lp(b, OPEN.dive, OPEN.end - OPEN.dive);
    const yaw = lerp(lerp(-25, 20, turn), 0, tilt) - 620 * E.in(dive);                       // the dive spins the spiral
    const Rn = lerp(215, 270, tilt) * Math.pow(18, E.in(dive));
    $('#hole1').style.clipPath = b >= OPEN.dive ? 'circle(' + (Rn * ORB.r0 / ORB.r1 * .9).toFixed(1) + 'px at 960px ' + lerp(410, 540, tilt).toFixed(1) + 'px)' : 'circle(0px at 960px 540px)';
    h += orbitSVG({ t: E.inOut(lp(b, OPEN.trace, 2.4)), yaw, pitch: lerp(lerp(72, 45, turn), 90, tilt), R: lerp(215, 270, tilt) * Math.pow(18, E.in(dive)), cx: 960, cy: lerp(410, 540, tilt), w: lerp(15, 13, tilt) * (1 + 6 * E.in(dive)), a: 1 - E.in(lp(b, OPEN.end - .6, .6)), head: 1 - lp(b, OPEN.trace + 2.2, .5) });
  }
  if (b >= OPEN.end && b < OPEN.end + .2) $('#hole1').style.clipPath = 'none';
  if (b >= CLOSE.ring) {
    const R0 = 300 * decks[2].C.s, grow = E.inOut(lp(b, CLOSE.ring, CLOSE.rise - CLOSE.ring)), rise = E.inOut(lp(b, CLOSE.rise, CLOSE.settle - CLOSE.rise));
    h += orbitSVG({ t0: 1 - grow * .999, t: 1, yaw: lerp(0, 20, rise) + 12 * Math.sin((b - 104) * .35) * lp(b, 104, 3), pitch: lerp(90, 45, rise), R: lerp(R0, 215, rise), cx: 960, cy: lerp(540, 410, rise), w: lerp(7, 15, rise), a: E.out(lp(b, CLOSE.ring, .4)) * (1 - E.inOut(lp(b, 115.8, 1.8))), head: 0 });
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
// Pace: the two core features (01 Analysis — the compass; 02 Recommend) get the long, slow shots; the overview and the
// smaller features become walls of components filling the screen, moving fast. Words are either full-screen statements
// on black or tags attached to a component's edge (they tilt and slide with it), so type never sits on a component.
const L = 160, R = 1760;
function split2(s) { const i = s.indexOf('，', 6); return i > 0 ? [s.slice(0, i + 1), s.slice(i + 1)] : [s]; }
function smallest(D, sel, text) { return [...D.querySelectorAll(sel)].filter((e) => e.textContent.includes(text)).sort((a, b) => a.textContent.length - b.textContent.length)[0]; }
function script() {
  // ===== open (缓): words, the five Agents, the Orbit mark, then down into it =====
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
  glowAt(7.9, 1, 3);
  txt(9.6, 11.9, [['word', 'Orbit']], { x: 960, y: 690, align: 'c' }, { inB: 1.4, outB: .8 });
  txt(10.6, 11.9, [['lt', '看见你与 Agent 的每一次协作']], { x: 960, y: 790, align: 'c' }, { inB: 1.2, outB: .8 });
  glowAt(12.6, 0, 1.6);

  // ===== the sentiment curve, first person: ride along it while it is drawn, the phrases you say stand up beside it =====
  const MOOD = 'svg.vz-t-moodcorr', moodCard = (D) => { const s = D.querySelector(MOOD); return s && s.closest('.card'); };
  const headX = (b) => 60 + 760 * E.inOut(lp(b, 14.4, 7.8));                          // svg units
  const ride = (b) => ({ x: 689 + headX(b) - 30, y: 372, s: 3.1, ax: 960, ay: 720, rx: 58, ry: 0, rz: -72, z: 0, o: 1, bl: 0 });
  at(12.9, () => { app(1).go('sentiment'); solo(1, moodCard); });
  tween(1, 13.6, 1.7, () => ride(15.3), E.out, (T) => ({ s: T.s * .14, rz: T.rz - 200, o: 0, bl: 6 }));
  drive(1, 15.3, 22.3, (p, b) => { const r = ride(b), C = decks[1].C; C.x = r.x; C.y = r.y; });
  drive(1, 12.95, 22.6, (p, b, D) => { const s = D.querySelector(MOOD); if (!s) return; clipTo(s, 36, headX(b) + 34, 'path.vz-line, path.vz-cband, circle.vz-pt, text.vz-lbl'); riseRects(s, headX(b) + 34, 214); });
  const PH = [['用中文', 9, '偏好'], ['先只读审查', 5, '规划'], ['方向错误', 3, '纠偏'], ['部署后验证线上', 7, '验证'], ['直接合并', 6, '纠偏'], ['简洁一点', 4, '风格'], ['不要改别的文件', 4, '纠偏'], ['可以，提交吧', 12, '满意']];
  const PHC = { 偏好: 'var(--a2)', 规划: 'var(--a3)', 纠偏: 'var(--a1)', 验证: '#6fcf97', 风格: 'var(--a5)', 满意: '#cfe3e8' };
  at(12.95, () => {
    PH.forEach((ph, i) => {
      const bi = 15 + i * .82, x = 689 + headX(bi) + 40, y = 260 + (i % 2 ? 228 : 4);
      const el = document.createElement('div'); el.className = 'phr'; el.style.left = x + 'px'; el.style.top = y + 'px';
      el.innerHTML = '<i style="background:' + PHC[ph[2]] + '"></i>「' + ph[0] + '」<b>×' + ph[1] + '</b><small>' + ph[2] + '</small>';
      el.dataset.b = bi; decks[1].rig.appendChild(el); (decks[1].phr = decks[1].phr || []).push(el);
    });
  });
  drive(1, 13, 23.2, (p, b) => (decks[1].phr || []).forEach((el) => {     // stand up when the head reaches them
    const q = E.out(lp(b, +el.dataset.b, .6)), C = decks[1].C;
    el.style.opacity = (q * (1 - lp(b, 22.2, .6))).toFixed(3);
    el.style.transform = 'translate(-50%,-100%) rotateZ(' + (-C.rz) + 'deg) rotateX(' + (-C.rx) + 'deg) translateY(' + ((1 - q) * 30).toFixed(1) + 'px) scale(' + (lerp(.6, 1, q) / C.s * 2.6).toFixed(4) + ')';
  }));
  txt(15.4, 21.9, [['eb', 'Sentiment · 情绪与语义'], ['gap'], ['hv sv', '听懂每一句话'], ['lt acc', '本地 Agent 给每条消息打分、归类']], { x: L - 60, y: 170 }, { st: .3, spread: 1, outB: .9 });
  tween(1, 22.2, 1.1, () => ({ o: 0, bl: 8, s: decks[1].C.s * 1.25 }), E.in);

  // ===== numbers roll, then fly into the KPI tiles; the tiles open into the overview wall =====
  const NUMS = [[186, '', '个会话'], [142, 'h', '小时协作'], ['1,284', '', '条消息']];
  const TB = [960, 600, 1700, 420], morph = [];
  at(25.8, () => {
    const T = framing(0, '.tiles', TB);
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
    const b0 = 22.3 + i * .5;
    txt(b0, 27.7, [['', '<span class="odo">' + odo(n[0]) + '</span><span class="odo-u">' + n[1] + '</span>'], ['lt', n[2]]], { x: 960 + (i - 1) * 520, y: 520, align: 'c' }, {
      anim: (el, tl, life, t) => {
        const b = t / BEAT, m = E.inOut(lp(b, 25.9, 1.45)), mv = morph[i], inP = E.expo(clamp(tl / (.9 * BEAT)));
        el.style.opacity = (inP * (1 - E.inOut(lp(b, 27.35, .3)))).toFixed(3);
        rollOdo(el, b, b0, 1.9);
        const o = el.querySelector('.odo'); o.style.transformOrigin = '0 50%';
        const ink = Math.round(lerp(255, 23, Math.pow(m, 3))); o.style.color = 'rgb(' + ink + ',' + ink + ',' + Math.round(lerp(255, 27, Math.pow(m, 3))) + ')';
        o.style.transform = mv ? 'translate(' + (mv.dx * m).toFixed(1) + 'px,' + (mv.dy * m).toFixed(1) + 'px) scale(' + lerp(1, mv.sc, m).toFixed(4) + ')' : '';
        el.querySelectorAll('.odo-u, .ln.lt').forEach((x) => { x.style.opacity = (1 - E.out(lp(b, 25.7, .6))).toFixed(3); });
        el.style.transform = 'translate(-50%,-50%) translateY(' + ((1 - inP) * 40).toFixed(1) + 'px)';
        el.querySelectorAll('.ln').forEach((x) => { x.style.overflow = 'visible'; });
      }, tag: 'num' + i
    });
  });
  txt(22.5, 25.8, [['eb', 'Overview · 近 30 天']], { x: 960, y: 330, align: 'c' });
  const trend = byText('.card.pad', 'Agent 使用趋势'), bars = (D) => { const c = trend(D); return c && c.querySelector('svg.vz-t-bar'); };
  const WALL = ['.tiles', '#aiCard', '.ov-out', trend, '.ov-pers'];
  at(21.6, () => { const a = app(0); a.S.ov.stack = 'stacked'; a.go('overview'); solo(0, '.tiles'); });
  drive(0, 21.6, 27.9, (p, b, D) => D.querySelectorAll('.tiles .vz-kpi .v').forEach((v, i) => {
    if (v.dataset.count) v.textContent = Number(v.dataset.count).toLocaleString('en-US', { maximumFractionDigits: 1 });
    v.style.opacity = i < 3 ? E.inOut(lp(b, 27.35, .3)).toFixed(3) : '';
  }));
  drive(0, 21.6, 31, (p, b, D) => { const s = bars(D); if (s) growBars(s, b, 28.6, .07, .5); });
  tween(0, 25.9, 1.6, () => framing(0, '.tiles', TB), E.inOut, (T) => ({ s: T.s * .96, o: 0, bl: 4 }));
  at(27.6, () => solo(0, WALL));
  tween(0, 27.8, 2.4, () => Object.assign(framing(0, WALL, [1180, 560, 1360, 800]), { rx: 20, ry: -18, rz: -5 }), E.inOut);
  tween(0, 30.2, 3.4, () => ({ rx: 12, ry: 6, rz: 2, s: decks[0].C.s * 1.05 }), E.sine);
  tag(0, 28.4, 33.2, '.tiles', 'left', [['eb', 'Overview'], ['gap'], ['md sv', '186 个会话'], ['lt acc', '142 小时 · 5 个 Agent']], { st: .2, gap: 80 });
  tag(0, 29, 33.2, '#aiCard', 'top', [['eb', 'AI 解读 · 本地 Agent 一句话说透']], { at: 0 });
  tag(0, 29.4, 33.2, trend, 'left', [['md sv', '五个 Agent'], ['lt acc', '一张图对齐']], { at: .5, gap: 95 });
  tag(0, 30, 33.2, '.ov-pers', 'bottom', [['lt', '你的协作人格 →']], { at: 1 });
  tween(0, 33.3, 2, () => ({ rz: -70, s: decks[0].C.s * .45, o: 0, bl: 6, ax: 900 }), E.inOut);

  // ===== 01 · Analysis: the compass (缓 → 急 → 缓, one continuous sweep) =====
  glowAt(33.4, .3, 2);
  drive(2, 33.3, 50.9, (p, b) => {
    const deg = sweepAt(b), speed = (sweepAt(b + .05) - sweepAt(b - .05)) / .1;
    const dip = b < 46 ? E.out(lp(b, 35, 1.4)) : b < 46.35 ? lerp(1, .4, E.inOut(lp(b, 46, .35))) : lerp(.4, 1, E.out(lp(b, 46.35, 1.2)));
    drawCompass({ deg, speed, mine: E.inOut(lp(b, 44.6, 1.6)), grow: dip, sweep: E.inOut(lp(b, 34, 2.4)), orbit: (b - 33.6) * 28 + deg * .3, settle: lp(b, 47, 1.8), tip: E.out(lp(b, 36.4, .8)) * (1 - E.inOut(lp(b, 46.8, .6))), needle: 1 });
  });
  tween(2, 33.6, 2.4, () => framing(2, 'all', [1120, 560, 760, 760]), E.inOut, (T) => ({ rx: 64, rz: 40, s: T.s * .6, o: 0, bl: 5 }));
  txt(34.2, 36.7, [['eb', '01 · Analysis'], ['gap'], ['hv sv', '16 种'], ['hv sv', '协作人格'], ['md acc', '4 个维度 · 8 个极']], { x: L - 30, y: 540 }, { st: .2, outB: .6 });
  tween(2, 36.4, 1.6, () => framing(2, 'all', [960, 540, 900, 900]), E.inOut);
  tween(2, 38, 7.6, () => ({ s: decks[2].C.s * 1.06, rz: -3 }), E.sine);
  txt(36.8, 46.5, [['md', '你是'], ['hv sv', '<span class="slot"><span class="s0"></span><span class="s1"></span></span>'], ['eb', '<span class="slot-c"></span>']], { x: 70, y: 540 }, {
    st: .15, inB: .7, outB: .5, tick: (el, tl, life, t) => {
      const b = t / BEAT, code = b >= 45.4 ? compassData().me.code : personaAt(sweepAt(b), 0).code, D = compassData();
      if (el._c !== code) { el._p = el._c; el._c = code; el._t = t; el.querySelector('.s0').textContent = el._p ? D.TYPES[el._p][0] : ''; el.querySelector('.s1').textContent = D.TYPES[code][0]; el.querySelector('.slot-c').textContent = code.split('').join(' '); }
      const k = E.out(clamp((t - el._t) / (.22 * BEAT)));
      el.querySelector('.s0').style.transform = 'translateY(' + (-k * 105).toFixed(1) + '%)'; el.querySelector('.s0').style.opacity = (1 - k).toFixed(3);
      el.querySelector('.s1').style.transform = 'translateY(' + ((1 - k) * 105).toFixed(1) + '%)'; el.querySelector('.s1').style.opacity = k.toFixed(3);
    }
  });
  // landing on yours: the needle settles at north, the rose folds and blooms with your values, the dial moves aside
  tween(2, 46.6, 1.8, () => framing(2, 'all', [640, 540, 860, 860]), E.inOut);
  glowAt(46, .6, 1.5);
  txt(47.2, 50.4, [['eb', '你的类型 · Your type'], ['gap'], ['xl sv', '<span class="serif">DIMV</span>'], ['md', '指挥家 <span class="serif acc"><i>The Conductor</i></span>'], ['gap'], ['lt', '整段交出，多线并进，亲自验收。'], ['gap'], ['eb', '委托 72 · 即兴 61 · 多线 73 · 求证 67']], { x: R + 40, y: 540, align: 'r' }, { st: .12 });
  tween(2, 50.5, 1.2, () => OUT.far(decks[2].C), E.in);
  glowAt(50.5, 0, 1.2);

  // ===== 02 · Recommend (缓): twelve suggestions on a tilted column add up the hours they save =====
  const rcards = (D) => [...D.querySelectorAll('.rcard')], SAVE = [], RECB = 50.9, RECG = .5;
  at(49.9, () => {
    const a = app(0); a.go('recs'); solo(0, (D) => D.querySelector('.rcard').parentElement);
    rcards(a.D).forEach((c) => { const n = c.querySelector('[data-count]'), m = c.textContent.match(/≈\s*[\d.]+\s*(h|min)/); SAVE.push(n ? +n.dataset.count / (m && m[1] === 'min' ? 60 : 1) : 0); });
  });
  drive(0, 49.95, 57.6, (p, b, D) => {
    const cs = rcards(D);
    cs.forEach((c, i) => { const q = E.out(lp(b, RECB + i * RECG, .7)); c.style.opacity = q.toFixed(3); c.style.transform = 'translateX(' + ((1 - q) * 80).toFixed(1) + 'px)'; });
    const ct = D.querySelector('#content'); if (ct && cs[1]) { const step = cs[1].offsetTop - cs[0].offsetTop || 178; ct.scrollTop = Math.max(0, (b - RECB) / RECG - 2.4) * step * .92; }
  });
  tween(0, 50.4, 1.6, () => Object.assign(framing(0, [(D) => rcards(D)[0], (D) => rcards(D)[2]], [1260, 540, 820, 940], { max: 2.2 }), { ry: -14, rz: -3 }), E.quart, IN.rise);
  txt(50.8, 56.9, [['eb', '02 · Recommend'], ['gap'], ['xl sv', '<span class="cnt">0.0</span><span style="font-size:.38em;letter-spacing:0"> h / 月</span>'], ['md acc', '每月省下的时间'], ['gap'], ['lt', '<span class="cnt-n">0</span> / 12 条建议 · 按节省时间排序']], { x: L, y: 540 }, {
    st: .15, tick: (el, tl, life, t) => {
      const b = t / BEAT; let sum = 0, n = 0;
      SAVE.forEach((h, i) => { const q = E.out(lp(b, RECB + i * RECG + .25, .55)); sum += h * q; if (q > .5) n++; });
      el.querySelector('.cnt').textContent = sum.toFixed(1); el.querySelector('.cnt-n').textContent = n;
    }
  });
  tween(0, 57, 1, () => OUT.up(decks[0].C), E.in);
  // the top suggestion installs: modal above, words below
  const recDetail = (D) => smallest(D, '#main .card', '每月节省');
  at(56.6, () => { const a = app(1); a.go('recs'); const d = recDetail(a.D); const btn = d && d.querySelector('[data-act="install"]'); if (btn) btn.click(); solo(1, '#modal'); });
  tween(1, 57.3, 1.5, () => Object.assign(framing(1, '#modal', [960, 420, 1180, 640]), { rx: 14 }), E.quart, IN.rise);
  tween(1, 58.8, 4, () => ({ rx: 4, s: decks[1].C.s * 1.04 }), E.sine);
  txt(57.8, 62.7, [['row hv', ['<span class="sv-t">预览，</span>', '<span class="sv-t">再写入</span>']], ['md acc', '一键安装 · 随时撤销 · 装上后追踪 7 天效果']], { x: 960, y: 930, align: 'c' }, { st: .3 });
  clickAt(1, 59.4, '#modal .btn.p', (a, el) => a.click(el));
  clickAt(1, 61, '#modal .btn.p', (a, el) => a.click(el));
  tween(1, 62.8, .9, () => OUT.up(decks[1].C), E.in);

  // ===== 03 · Trajectory: the playhead runs one session start to end, the phases are named as it passes =====
  const tlsvg = '.tl-card svg.vz-t-timeline';
  at(62.5, () => { app(0).go('sessions'); solo(0, '.tl-card'); });
  tween(0, 63, 2, () => framing(0, '.tl-card', [1310, 540, 1040, 900]), E.quart, IN.plane);
  txt(63.4, 65.6, [['eb', '03 · Trajectory'], ['gap'], ['hv sv', '卡在哪一刻'], ['md acc', '逐秒回放，一眼看清']], { x: L, y: 540 }, { st: .25, outB: .5 });
  drive(0, 64.6, 68.6, (p, b) => { const a = app(0); if (a.S.sess.playing) a.W.eval('stopPlay()'); a.S.sess.ph = a.W.eval('traj(BYID[S.sess.sel]).T') * E.inOut(lp(b, 64.8, 3.6)); a.W.eval('tlFrame(true)'); });
  tween(0, 65.1, 1.4, () => framing(0, tlsvg, [1250, 500, 1300, 700], { max: 4, px: .18 }), E.inOut);
  drive(0, 66.5, 68.6, (p, b, D) => { const ph = D.querySelector(tlsvg + ' .vz-playhead'), card = D.querySelector('.tl-card'); if (!ph) return; const C = decks[0].C, lim = card.getBoundingClientRect().left - (680 - C.ax) / C.s; C.x = Math.min(lim, lerp(C.x, ph.getBoundingClientRect().left + 30, .12)); });   // ride with the playhead, but keep the card clear of the caption
  const PHASE = { '探索': ['读代码，找入口', ''], '规划': ['拆成 5 步', ''], '实施': ['纠偏 2 次', 'warn'], '部署': ['同一命令连续失败 4 次', 'crit'], '验证': ['上线验证通过 · 42 分钟', 'good'] };
  txt(65.8, 68.7, [['md sv', '<span class="ph-n"></span>'], ['lt', '<span class="ph-d"></span>']], { x: L, y: 880 }, {
    inB: .5, outB: .3, tick: (el, tl, life, t) => {
      const D = decks[0].D, svg = D && D.querySelector(tlsvg), ph = svg && svg.querySelector('.vz-playhead'); if (!ph) return;
      const px = ph.getBoundingClientRect().left; let cur = '探索';
      [...svg.querySelectorAll('text')].filter((x) => PHASE[x.textContent]).forEach((x) => { if (x.getBoundingClientRect().left - 14 <= px) cur = x.textContent; });
      if (el.dataset.p !== cur) { el.dataset.p = cur; el.querySelector('.ph-n').textContent = cur; const d = el.querySelector('.ph-d'); d.textContent = PHASE[cur][0]; d.className = 'ph-d ' + PHASE[cur][1]; el._t = t; }
      const k = E.out(clamp((t - (el._t || 0)) / (.25 * BEAT))); el.querySelectorAll('.ln>span').forEach((s) => { s.style.transform = 'translateY(' + ((1 - k) * 40).toFixed(1) + '%)'; s.style.opacity = k.toFixed(3); });
    }
  });
  const inspector = (D) => [...D.querySelectorAll('.tl-card div')].filter((e) => e.textContent.includes('事件检视') && e.getBoundingClientRect().width < 360).sort((a, b) => a.textContent.length - b.textContent.length).pop();
  tween(0, 68.6, 1.4, () => Object.assign(framing(0, inspector, [760, 560, 900, 620], { max: 3 }), { ry: 12 }), E.inOut);
  tag(0, 68.9, 70.9, inspector, 'right', [['hv sv', '每次失败'], ['md acc', '都留有现场']], { gap: 80 });
  tween(0, 71, .9, () => OUT.up(decks[0].C), E.in);

  // ===== insight → studio (a vertical feed: everything rises) =====
  shot(1, 71.2, 75.6, { sel: byText('.card.pad.col', '这次会话的启示'), box: [1300, 540, 700, 860], inn: 'rise', out: 'up', rz: 3, prep: (a) => a.go('sessions') });
  txt(71.5, 75.6, [['eb', 'Insight'], ['gap'], ['hv sv', '下次怎么做'], ['md acc', '复盘直接给出改法']], { x: L, y: 540 }, { st: .3 });
  clickAt(1, 74.4, (D) => smallest(D, '.card.pad.col button', '生成规则'), () => {});
  const runCard = (D) => D.querySelectorAll('#main .card.pad.col')[1], skillCard = (D) => smallest(D, '#main .card.col', 'SKILL.md');
  at(75.2, () => { const a = app(0); a.go('studio'); a.click('[data-act="studioStart"]'); solo(0, [runCard, skillCard]); });
  tween(0, 75.8, 1.3, () => Object.assign(framing(0, runCard, [1250, 540, 900, 860]), { ry: -10 }), E.quart, IN.rise);
  txt(76.2, 79.8, [['eb', 'Studio'], ['gap'], ['hv sv', '交给本地 Agent'], ['md acc', '生成 Skill、Hook 与规则']], { x: L, y: 540 }, { st: .3 });
  drive(0, 79.6, 81.6, (p, b, D) => { const ct = D.querySelector('#content'), sk = skillCard(D); if (ct && sk) { if (ct._s0 == null) { ct._s0 = ct.scrollTop; ct._s1 = Math.max(0, sk.offsetTop - 120); } ct.scrollTop = lerp(ct._s0, ct._s1, E.inOut(lp(b, 79.8, 1.6))); } });
  drive(0, 80.6, 84.9, (p, b, D) => { const c = runCard(D); if (c) c.style.opacity = (1 - E.inOut(lp(b, 80.8, .9))).toFixed(3); });
  tween(0, 81.4, 1.2, () => Object.assign(framing(0, skillCard, [1220, 540, 1040, 880], { max: 2.2 }), { ry: 0 }), E.inOut);
  txt(81, 83.8, [['hv sv', '边写边验'], ['md acc', '自检 · 回放 dry-run · 第二视角评分']], { x: L, y: 540 }, { st: .25 });
  tween(0, 83.9, .9, () => OUT.up(decks[0].C), E.in);

  // ===== 04 · Ask (build) =====
  shot(1, 84, 90.5, { sel: '#modal', box: [1310, 560, 980, 760], inn: 'rise', inDur: 1.4, out: 'near', outDur: 1, push: 1.14, prep: (a) => { a.go('overview'); a.W.openAsk('overview'); } });
  clickAt(1, 85.4, '[data-act="askPick"]', (a, el) => a.click(el));
  glowAt(84, .5, 2);
  txt(84.5, 90.5, [['eb', '04 · Ask'], ['gap'], ['hv sv', '问你自己的'], ['hv ai', '本地 Agent'], ['gap'], ['lt', '数据不出本机 · 0 B 上传']], { x: L, y: 540 }, { st: .5, spread: 1, outB: .8 });
  glowAt(90, 0, 1.5);

  // ===== the smaller features (急): one wall of desktop pieces filling the screen, each one acts in turn =====
  const DESK = ['#widgets', '#hud', '#notes', '.edsw'];
  at(90.3, () => { const a = app(0); a.W.closeModal(); a.S.widgets = true; a.S.hud.show = true; a.S.sim = 'running'; a.go('overview'); a.D.querySelectorAll('#notes .nt').forEach((n) => n.remove()); solo(0, DESK); });
  const WIDE = () => Object.assign(framing(0, ['#widgets', '#hud', '.edsw'], [960, 560, 1500, 900]), { s: 1.12, x: 800, y: 500, rx: 14, ry: -12, rz: -3 });
  tween(0, 90.8, 1.6, WIDE, E.quart, IN.plane);
  tag(0, 91.4, 93.6, '#widgets', 'right', [['hv sv', '桌面小组件'], ['lt acc', '人格 · 今日 · 本周 · 最值得做']], { gap: 60 });
  at(92.6, () => { const a = app(0); a.D.querySelectorAll('#notes .nt').forEach((n) => n.remove()); a.W.simEvent('waiting'); });
  tween(0, 92.6, 1.1, () => Object.assign(framing(0, '#notes .nt', [1200, 380, 900, 400], { max: 2 }), { rx: 8, ry: 10, rz: 2 }), E.inOut);
  tag(0, 93, 94.6, '#notes .nt', 'left', [['md sv', '第一时间提醒'], ['lt acc', '会话等你确认时']], { gap: 50 });
  at(94, () => { app(0).W.openPalette(); solo(0, DESK.concat('#modal')); });
  drive(0, 94.4, 95.4, (p, b, D) => { const q = D.querySelector('#palQ'); if (!q) return; const s = '部署'.slice(0, Math.floor(p * 2.99)); if (q.value !== s) { q.value = s; q.dispatchEvent(new Event('input', { bubbles: true })); } });
  tween(0, 94, 1.1, () => Object.assign(framing(0, '#modal', [960, 470, 900, 640], { max: 1.8 }), { rx: 10, ry: -6, rz: -2 }), E.inOut);
  tag(0, 94.4, 95.8, '#modal', 'bottom', [['md sv', '⌘K'], ['lt acc', '任何页面、会话与操作']], { at: .5 });
  at(95.6, () => { app(0).W.closeModal(); solo(0, DESK); });
  tween(0, 95.8, 1.1, () => Object.assign(framing(0, '.edsw', [960, 600, 1000, 300], { max: 3.2 }), { rx: 18, ry: 8, rz: 0 }), E.inOut);
  clickAt(0, 96.6, '[data-act="edition"][data-v="lite"]', (a) => a.W.edSet('lite'));
  at(97.2, () => { const a = app(0); a.S.hud.show = true; a.S.sim = 'running'; a.render(); });
  tag(0, 96, 97.4, '.edsw', 'bottom', [['md sv', 'Lite / Advance'], ['lt acc', '一键切换 · ⌃⌘L']], { at: .5, gap: 50 });
  tween(0, 97.4, 1.1, () => Object.assign(framing(0, '#hud', [900, 560, 1100, 400], { max: 2.6 }), { rx: 12, ry: -10, rz: 2 }), E.inOut);
  clickAt(0, 97.9, '#hudPill', (a, el) => a.click(el));
  tag(0, 97.7, 99, '#hud', 'right', [['md sv', '悬浮组件'], ['lt acc', '会话运行时，陪在桌面一角']], { gap: 50 });
  tween(0, 98.8, 1.2, WIDE, E.inOut);
  at(99.2, () => { app(0).W.setTheme('dark'); });
  tag(0, 99.3, 100.6, '#widgets', 'right', [['hv sv', '深色模式'], ['lt acc', '跟随系统外观']], { gap: 60 });
  tween(0, 100.6, 1.3, () => ({ rz: 80, s: decks[0].C.s * .3, o: 0, bl: 6 }), E.inOut);

  // ===== close: your compass, the aurora collapses to one ring, the ring becomes the Orbit mark =====
  drive(2, 100.7, 107.6, (p, b) => drawCompass({ deg: 4 * Math.sin((b - 101) * 1.5) * Math.exp(-(b - 101) * .5), speed: 0, mine: 1, grow: 1 + .02 * Math.sin((b - 101) * 1.6), sweep: 1, orbit: 0, settle: 1, tip: 0, needle: 1, core: 1 - E.inOut(lp(b, 104, 1.2)), dial: 1 - E.inOut(lp(b, 104.4, 1.6)), collapse: E.inOut(lp(b, 104.4, 1.6)) }));
  tween(2, 100.9, 2, () => framing(2, 'all', [960, 540, 900, 900]), E.quart, (T) => ({ s: T.s * .3, rz: -80, o: 0, bl: 6 }));
  tween(2, 106.2, .8, () => ({ o: 0 }), E.inOut);
  glowAt(101, .6, 3);
  txt(102, 104.6, [['row md', ['<span>只读本地日志</span>', '<span class="acc">数据不出本机</span>']]], { x: 960, y: 1030, align: 'c' }, { st: .4 });
  glowAt(106, .9, 3);
  txt(109.2, 117.6, [['word', 'Orbit']], { x: 960, y: 690, align: 'c' }, { inB: 1.5, outB: 2 });
  txt(110.6, 117.6, [['lt', '看见你与 Agent 的每一次协作']], { x: 960, y: 790, align: 'c' }, { inB: 1.5, outB: 2 });
  txt(112.4, 117.6, [['eb', 'for macOS · ActionMesh AI']], { x: 960, y: 865, align: 'c' }, { inB: 1.5, outB: 2 });
  glowAt(115, 0, 2.5);
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
  applyDrives(t); applyCams(t); applyCursors(t); applyTags(t); orbitAt(t / BEAT); applyFx(t); applyGlow(t);
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

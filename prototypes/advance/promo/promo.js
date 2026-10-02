/* Tandem promo: a beat-locked timeline. Two live copies of the app take turns showing ONE component each (everything
   else in that copy is hidden), framed by a virtual camera next to the copy that explains it. Transitions overlap the
   outgoing and incoming component with long eases; there are no beat-synced shakes or flashes.
   Everything is a pure function of the master time t (seconds), so the page plays in real time with the soundtrack
   (preview) or frame by frame on Playwright's fake clock (render.mjs). Times are written in beats. */
'use strict';
const BPM = 124, BEAT = 60 / BPM;                         // beats; music.py uses the same grid
let END = 118;                                            // length in beats; the closing scene sets it
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
    prof.push(Math.max(.04, (val(((a / 15 - .5) % 24 + 24) % 24) / 1.6 * .75 + swell * .55)) * (1 - col));   // each hour's value sits on the middle of its sector, as in the app
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
// Timings (beats) of the two mark sequences. The open and close scenes overwrite them with Object.assign.
// open: planets appear, are pulled onto the tail, the mark is traced, tips over and is dived into;
// close: the ring grows its inner turn, rises into the icon and settles; sway = when the 3D sway starts; out = fade.
const OPEN = { planets: 5.6, pull: 7.5, trace: 7.9, tilt: 11.4, dive: 12.8, end: 14.6 };
const CLOSE = { ring: 105.8, rise: 107.6, settle: 110, sway: 104, out: 115.8, outDur: 1.8 };
function orbitAt(b) {
  let h = '';
  if (b >= OPEN.planets && b < OPEN.trace + .7) {
    const start = orbitPts(-25, 72)[0];
    h += planetsSVG({ a: E.out(lp(b, OPEN.planets, .8)) * (1 - E.in(lp(b, OPEN.trace + .2, .5))), phase: (b - OPEN.planets) * 95, cx: 960, cy: 790, rx: 380, ry: 64, pull: E.inOut(lp(b, OPEN.pull, 1)), tx: 960 + start[0] * 215, ty: 410 + start[1] * 215 });
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
    h += orbitSVG({ t0: 1 - grow * .999, t: 1, yaw: lerp(0, 20, rise) + 12 * Math.sin((b - CLOSE.sway) * .35) * lp(b, CLOSE.sway, 3), pitch: lerp(90, 45, rise), R: lerp(R0, 215, rise), cx: 960, cy: lerp(540, 410, rise), w: lerp(7, 15, rise), a: E.out(lp(b, CLOSE.ring, .4)) * (1 - E.inOut(lp(b, CLOSE.out, CLOSE.outDur))), head: 0 });
  }
  orbEl.innerHTML = '<defs><radialGradient id="orbGlow"><stop offset="0" stop-color="rgba(255,255,255,.9)"/><stop offset="1" stop-color="rgba(255,255,255,0)"/></radialGradient></defs>' + h;
}

/* a macOS pointer that glides to a control, presses it, and then the action runs — one per app copy, drawn inside the
   copy so it follows the camera, counter-scaled so it keeps a constant size on screen */
const CURSOR_SVG = '<svg viewBox="0 0 28 28" width="28" height="28"><path d="M6 3.5v19.2l4.6-4.4 3 6.9 3.3-1.4-2.9-6.8h6.5z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
const clicks = [];
// o.bloom: colour of a press bloom (a radial fill under the pointer, then a soft glow that spreads to about 3×, as in
// the GWI reference); o.size: its diameter on screen in px; o.glide: beats the pointer takes to reach the control.
function clickAt(d, b, sel, fn, o = {}) { clicks.push({ d, b, sel, fn, o }); at(b, () => { const el = find(d, sel); if (el) fn(app(d), el); else console.warn('promo: no click target', sel); }); }
function cursorEl(d) {
  const k = decks[d]; if (k.cursor) return k.cursor;
  const c = document.createElement('div'); c.className = 'cursor'; c.innerHTML = CURSOR_SVG + '<i class="ripple"></i>'; k.rig.appendChild(c); k.cursor = c; return c;
}
function applyCursors(t) {
  const b = t / BEAT;
  for (const k of decks) { const c = k.cursor; if (c) c.style.opacity = '0'; }
  for (const x of clicks) {
    const gl = x.o.glide || 1.1;
    if (b < x.b - gl - .2 || b > x.b + .9) { if (x.bloom) x.bloom.style.opacity = '0'; continue; }
    if (!x.to) { const el = find(x.d, x.sel); if (!el) continue; const r = el.getBoundingClientRect(); x.to = [r.left + r.width * .5, r.top + r.height * .55]; x.from = [x.to[0] + 160, x.to[1] + 120]; }
    const c = cursorEl(x.d), s = decks[x.d].C.s;
    const m = E.inOut(lp(b, x.b - gl, gl - .1)), press = b >= x.b && b < x.b + .25 ? .82 : 1;
    const px = lerp(x.from[0], x.to[0], m), py = lerp(x.from[1], x.to[1], m);
    c.style.opacity = (E.out(lp(b, x.b - 1.3, .35)) * (1 - E.in(lp(b, x.b + .55, .35)))).toFixed(3);
    c.style.transform = 'translate(' + px.toFixed(2) + 'px,' + py.toFixed(2) + 'px) scale(' + (1.8 / s * press).toFixed(4) + ')';
    const rp = lp(b, x.b, .6); const ri = c.querySelector('.ripple');
    ri.style.opacity = b >= x.b ? (1 - rp).toFixed(3) : '0'; ri.style.transform = 'translate(-50%,-50%) scale(' + (.4 + rp * 1.6).toFixed(3) + ')';
    if (x.o.bloom) {
      if (!x.bloom) { x.bloom = document.createElement('div'); x.bloom.className = 'bloom'; x.bloom.innerHTML = '<i class="bf"></i><i class="bg"></i>'; x.bloom.style.setProperty('--c', x.o.bloom); decks[x.d].rig.insertBefore(x.bloom, c); }
      const fp = E.out(lp(b, x.b, .14)), gp = E.out(lp(b, x.b + .05, .75)), sz = (x.o.size || 90) / s;
      x.bloom.style.opacity = b >= x.b ? '1' : '0';
      x.bloom.style.transform = 'translate(' + x.to[0].toFixed(1) + 'px,' + x.to[1].toFixed(1) + 'px)';
      const bf = x.bloom.firstChild, bg = x.bloom.lastChild;
      bf.style.width = bf.style.height = bg.style.width = bg.style.height = sz.toFixed(1) + 'px';
      bf.style.transform = 'translate(-50%,-50%) scale(' + fp.toFixed(3) + ')'; bf.style.opacity = (1 - E.in(lp(b, x.b + .3, .5))).toFixed(3);
      bg.style.transform = 'translate(-50%,-50%) scale(' + (1 + 2.2 * gp).toFixed(3) + ')'; bg.style.opacity = (.85 * (1 - gp)).toFixed(3);
    }
  }
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
   must hand over to the next one; times are beats (124 BPM, 1 beat = 0.484 s). */
const SCENES = [];
function scene(name, fn) { SCENES.push({ name, fn }); }
function script() { for (const s of SCENES) { try { s.fn(); } catch (e) { console.error('scene ' + s.name, e); } } }
// styles a scene needs for its own type or overlays
function css(text) { const st = document.createElement('style'); st.textContent = text; document.head.appendChild(st); }
const L = 160, R = 1760;
function split2(s) { const i = s.indexOf('，', 6); return i > 0 ? [s.slice(0, i + 1), s.slice(i + 1)] : [s]; }
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
  script(); PROMO.duration = END * BEAT; tweens.sort((a, b) => a.b - b.b); cues.sort((a, b) => a.b - b.b); step(0);
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

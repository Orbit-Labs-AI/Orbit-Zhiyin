/* Orbit promo: a beat-locked timeline. Two live copies of the app take turns showing ONE component each (everything
   else in that copy is hidden), framed by a virtual camera next to the copy that explains it. Transitions overlap the
   outgoing and incoming component with long eases; there are no beat-synced shakes or flashes.
   Everything is a pure function of the master time t (seconds), so the page plays in real time with the soundtrack
   (preview) or frame by frame on Playwright's fake clock (render.mjs). Times are written in beats. */
'use strict';
const BPM = 132, BEAT = 60 / BPM;                         // beats; music.py uses the same grid
let END = 118;                                            // length in beats; the closing scene sets it (scene beats)
/* Scene beats vs film beats: the opening (10-open) runs on film beats; every later scene keeps its own (v7-grid) beats
   and is played SHIFT[name] beats later: 8 for the wordmark reveal, more after the persona and the recommendations,
   which were given longer holds so every line can be read. Each cue, tween, text, tag, drive and click remembers the
   shift of the scene that registered it and sees the clock in its own scene beats. music.py uses the same table. */
const SHIFT = { '10-open': 0, '20-sentiment': 8, '30-persona': 8, '40-recs': 19, '60-close': 9.5 };
let SH = 0;
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
    if (f.el) { const ts = t - f.sh * BEAT; f.anim(f.el, t - t0, t1 - t0, ts); if (f.tick) f.tick(f.el, t - t0, t1 - t0, ts); }
  }
}
let glow = { b: null, from: 0, to: 0, v: 0, dur: 2 };
function glowAt(b, v, dur = 2) { const g = b + SH; at(b, () => { glow = { b: g, from: glow.v, to: v, v: glow.v, dur }; }); }
function applyGlow(t) { if (glow.b == null) return; glow.v = lerp(glow.from, glow.to, E.inOut(clamp((t / BEAT - glow.b) / glow.dur))); glowEl.style.opacity = glow.v.toFixed(3); }

/* ---------- app control ---------- */
const cues = [];
function at(b, fn) { cues.push({ b: b + SH, fn, done: false }); }
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
function drive(d, b0, b1, fn) { drives.push({ d, b0: b0 + SH, b1: b1 + SH, sh: SH, fn, fin: false }); }
function applyDrives(t) {
  const b = t / BEAT;
  for (const x of drives) {
    if (x.fin || b < x.b0) continue;
    const D = decks[x.d].D; if (!D && !decks[x.d].virtual) continue;
    const p = clamp((b - x.b0) / (x.b1 - x.b0));
    try { x.fn(p, b - x.sh, D); } catch (e) { console.error('drive @' + x.b0, e); x.fin = true; }
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
    const ts = t - g.sh * BEAT; g.anim(g.el, t - t0, t1 - t0, ts);
    if (g.o.tick) g.o.tick(g.el, t - t0, t1 - t0, ts);
  }
}

/* ---------- the persona compass (deck 2) ----------
   The app's Orbit dial (fp2SVG in 41-a2-persona.js, FPG geometry × 2 on an 800 frame), drawn from the app's own
   functions so it follows the app: a bezel with 128 ticks and the 16 types in Gray-code order (neighbours differ by one
   letter; right half 委托 D, left 掌舵 S, top 即兴 I, bottom 规划 P — only these four words), the orbit band where every
   session sits at the bearing of its own four axes (fpClassify / fpOrbit, one muted layer per Agent, the Agent logos on
   the crest), and in the core the persona flower (bloom) whose lead petal points at a type.
   For the film the lead petal is the selector: as it turns, the flower becomes the type it points at (typeP), the
   bezel pointer follows it, and sectors that the evidence rules out dim. Colours are the app's, re-mixed for black. */
const CP = { C: 400, K: 2, R0: 200, RH: 116, RR: 160, CORE: 180, BUD: .34, SPIN: [9, 6.5, 4.5, 3, 1.8] };   // SPIN: deg / beat per Agent layer
const cpt = (r, deg) => [CP.C + r * Math.sin(deg * Math.PI / 180), CP.C - r * Math.cos(deg * Math.PI / 180)];
const f2 = (q) => q[0].toFixed(1) + ' ' + q[1].toFixed(1);
function axisOf(v, i) { const ax = CPD.AXES[i], val = v[ax.k], pos = ax.k !== 'I' ? 100 - val : val; return { strong: Math.max(val, 100 - val), letter: pos < 50 ? ax.L : ax.R }; }
const CODES = Array.from({ length: 16 }, (_, i) => { const g = i ^ (i >> 1); return ['DS', 'IP', 'MF', 'VT'].map((p, k) => p[(g >> (3 - k)) & 1]).join(''); });   // = the app's FP_TYPES; CODES[0] = DIMV
const AGC = ['var(--a1)', 'var(--a2)', 'var(--a3)', 'var(--a4)', 'var(--a5)'];
const cpMute = (c, k) => 'color-mix(in oklab, ' + c + ' ' + k + '%, #5d6066)';          // the app's fpMute, against a dark grey
let CPD = null;
function compassData() {
  if (CPD) return CPD;
  const W = decks[0].W, L = W.eval('sel({ noExtra: true })'), cls = W.eval('fpClassify')(L), orb = W.eval('fpOrbit')(L, cls);
  const me = W.eval('persona(sel({ noExtra: true }))'), typeP = W.eval('typeP'), bloom = W.eval('bloom'), parts = W.eval('bloomParts'), agLogo = W.eval('agLogo');
  const col = { ink: '#eef0f3', gray: 'rgba(238,240,243,.34)', lead: 'var(--orbit)', bg: '#0b0c0f', hw: 2.8 };
  const flower = (p) => { const g = bloom(p, CP.C, CP.RR), q = parts(g, CP.C, CP.C, col); return { back: q.back, front: q.front, heart: q.heart }; };
  CPD = { TYPES: W.eval('TYPES'), AXES: W.eval('AXES'), AG: W.eval('AG'), me, L, cls, orb, agLogo,
    fl: CODES.map((c) => flower(typeP(c))), mine: flower(me), mineIdx: CODES.indexOf(W.eval('bloomCode')(me)) };
  return CPD;
}
function buildCompass() {
  const k = decks[2]; if (k.svg) return k.svg;
  const D = compassData(), Wt = 'rgba(255,255,255,';
  const tk = ['', '', '']; for (let i = 0; i < 128; i++) { const w = i % 32 === 0 ? 2 : i % 8 === 0 ? 1 : 0; tk[w] += 'M' + f2(cpt(392, i * 2.8125)) + 'L' + f2(cpt([385, 378, 370][w], i * 2.8125)); }
  const poles = [[0, '即兴'], [90, '委托'], [180, '规划'], [270, '掌舵']].map(([a, t]) => { const q = cpt(352, a); return '<text class="cp-pole" x="' + q[0].toFixed(1) + '" y="' + q[1].toFixed(1) + '" text-anchor="middle" dominant-baseline="central">' + t + '</text>'; }).join('');
  const lys = D.orb.layers.filter((ly) => ly.n);
  const fl = (f, i) => '<g class="fl" data-i="' + i + '" opacity="0"><g class="rot">' + (f.back ? '<g class="bk">' + f.back + '</g>' : '') + '<g class="fr">' + f.front + '</g></g><g class="ht">' + f.heart + '</g></g>';
  const h = '<defs><radialGradient id="cpFace"><stop offset="0" stop-color="' + Wt + '.06)"/><stop offset=".75" stop-color="' + Wt + '.025)"/><stop offset="1" stop-color="' + Wt + '0)"/></radialGradient>' +
    '<radialGradient id="cpHead"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset=".35" stop-color="#cfe9ef" stop-opacity=".6"/><stop offset="1" stop-color="#a3adb0" stop-opacity="0"/></radialGradient></defs>' +
    '<clipPath id="cpTickClip"><path/></clipPath><clipPath id="cpBandClip"><path/></clipPath>' +
    '<g class="cp-dial"><circle cx="400" cy="400" r="392" fill="url(#cpFace)" stroke="' + Wt + '.5)" stroke-width="1.8"/>' +
    '<g class="cp-ticks"><path d="' + tk[0] + '" stroke="' + Wt + '.22)" stroke-width="1.4"/><path d="' + tk[1] + '" stroke="' + Wt + '.45)" stroke-width="2"/><path d="' + tk[2] + '" stroke="#fff" stroke-width="2.8"/></g>' +
    '<g class="cp-poles">' + poles + '</g><path class="cp-ptr" d="M400 396L390 376L410 376Z" fill="var(--orbit)"/></g>' +
    '<g class="cp-trace" fill="none" stroke-linecap="round"></g>' +
    '<g class="cp-band"><circle class="base" cx="400" cy="400" r="' + (CP.R0 + 2) + '" fill="none" stroke="' + Wt + '.16)" stroke-width="1.4"/>' +
    '<path class="crest" fill="none" stroke="' + Wt + '.07)" stroke-width="18" stroke-linejoin="round"/>' +
    lys.map((ly) => '<path class="ly" fill="' + cpMute(AGC[D.AG.indexOf(ly.a)], 58) + '" fill-opacity=".42"/>').join('') +
    lys.map((ly) => '<path class="ed" fill="none" stroke="' + cpMute(AGC[D.AG.indexOf(ly.a)], 78) + '" stroke-width="2.3" stroke-linejoin="round"/>').join('') +
    '<g class="dim">' + CODES.map((c, t) => '<path data-t="' + t + '" fill="#000" opacity="0" d="' + cpSector(CP.R0 - 2, CP.R0 + CP.RH + 10, t * 22.5, (t + 1) * 22.5) + '"/>').join('') + '</g></g>' +
    '<g class="cp-pls">' + D.orb.planets.map((x) => { const c = AGC[D.AG.indexOf(x.a)]; return '<g class="pl"><circle r="27" fill="' + cpMute(c, 60) + '" fill-opacity=".2"/>' + D.agLogo(x.a.id, 0, 0, 19, cpMute(c, 86), '#0e0f12') + '</g>'; }).join('') + '</g>' +
    '<g class="cp-core"><circle cx="400" cy="400" r="' + CP.CORE + '" fill="#08090b" stroke="' + Wt + '.16)" stroke-width="1.6"/></g>' +
    '<g class="cp-flower">' + D.fl.map(fl).join('') + fl(D.mine, 'me') + '</g>';
  const svg = document.createElementNS(SVGNS, 'svg'); svg.setAttribute('viewBox', '0 0 800 800'); svg.setAttribute('width', '800'); svg.setAttribute('height', '800'); svg.setAttribute('class', 'compass');
  svg.style.overflow = 'visible'; svg.innerHTML = h; k.rig.appendChild(svg); k.svg = svg;
  k.lys = lys; k.fls = [...svg.querySelectorAll('.cp-flower .fl')];
  // every petal (and stamen, dot) becomes its own path, ranked clockwise from the lead petal, so a change of type can
  // fold the petals in one by one and open the next flower's petals one by one right behind them
  k.pet = k.fls.map((g) => {
    const out = [];
    g.querySelectorAll('.rot path').forEach((p) => {
      const parts = (p.getAttribute('d') || '').split(/(?=M)/).filter((x) => x.trim());
      parts.forEach((d) => { const q = p.cloneNode(false); q.setAttribute('d', d); p.parentNode.insertBefore(q, p); out.push(q); });
      p.remove();
    });
    const ang = (q) => { const b = q.getBBox(), a = Math.atan2(b.x + b.width / 2 - 400, 400 - (b.y + b.height / 2)) * 180 / Math.PI; return (((a + 2) % 360) + 360) % 360; };   // 2°: a lead petal a hair left of north still ranks first
    out.forEach((q) => { q._a = ang(q); });
    return out.sort((a, b) => a._a - b._a);
  });
  k.ht = k.fls.map((g) => g.querySelector('.ht'));
  // each Agent layer starts a fifth of the ring apart from the others (its badge evenly spread), then circles at its own speed
  k.ph = lys.map((ly, i) => { const x = D.orb.planets.find((y) => y.a === ly.a || (y.a && ly.a && y.a.id === ly.a.id)); return i * 72 + 18 - (x ? x.deg : 0); });
  return svg;
}
function cpSector(r0, r1, a0, a1) { const p0 = cpt(r0, a0), p1 = cpt(r1, a0), p2 = cpt(r1, a1), p3 = cpt(r0, a1); return 'M' + f2(p0) + 'L' + f2(p1) + 'A' + r1 + ' ' + r1 + ' 0 0 1 ' + f2(p2) + 'L' + f2(p3) + 'A' + r0 + ' ' + r0 + ' 0 0 0 ' + f2(p0) + 'Z'; }
/* st: { deg: bearing of the lead petal and the bezel pointer, mine: 0..1 from the type's flower to your own, grow: 0 bud
   .. 1 open, fi (flower to show, a CODES index; default: the type under the petal), twist (extra turn of the flower,
   deg), sweep (band reveal: a wedge from sweepFrom, clockwise), orbit (badge phase while they ride with the petal),
   spin (beats: each Agent layer and its badge turn by spin × CP.SPIN[layer], from evenly spread starts), wave (a petal-by-
   petal change of type: { a, b, u }), settle (unused since v13: the badges always ride their layers), keep: 16 × 0..1 (1 = sector still possible, 0 = ruled out and dimmed), dial,
   core, needle (pointer), collapse (band → one ring at r 300), ticks (0..1: ticks revealed clockwise from north),
   trace (0..1: a light running once around the ticks; traceA its strength) } */
// a pie wedge (clip) from bearing a0, span degrees clockwise
function cpWedge(a0, span) {
  if (span >= 359.9) return 'M-200 -200H1000V1000H-200Z';
  if (span <= 0) return 'M400 400Z';
  const p0 = cpt(560, a0), p1 = cpt(560, a0 + span);
  return 'M400 400L' + f2(p0) + 'A560 560 0 ' + (span > 180 ? 1 : 0) + ' 1 ' + f2(p1) + 'Z';
}
function cpArc(r, a0, a1) { const p0 = cpt(r, a0), p1 = cpt(r, a1); return 'M' + f2(p0) + 'A' + r + ' ' + r + ' 0 ' + (a1 - a0 > 180 ? 1 : 0) + ' 1 ' + f2(p1); }
function drawCompass(st) {
  const svg = buildCompass(), k = decks[2], D = CPD, col = clamp(st.collapse || 0), deg = st.deg;
  // the band: each Agent layer between its inner and outer edge (app units × 2); collapsing pulls every edge to r 300
  const N = D.orb.layers[0].outer.length - 1, rad = (e) => lerp(CP.R0 + 2 + e * CP.K, 300, col);
  const edge = (e) => { let d = ''; for (let s = 0; s <= N; s++) d += (s ? 'L' : 'M') + f2(cpt(rad(e[s]), s / N * 360)); return d + 'Z'; };
  const band = (ly) => { let d = ''; for (let s = 0; s <= N; s++) d += (s ? 'L' : 'M') + f2(cpt(rad(ly.outer[s]), s / N * 360)); for (let s = N; s >= 0; s--) d += 'L' + f2(cpt(rad(ly.inner[s]), s / N * 360)); return d + 'Z'; };
  if (k.col !== col) {
    k.col = col;
    svg.querySelectorAll('.cp-band .ly').forEach((p, i) => p.setAttribute('d', band(k.lys[i])));
    svg.querySelectorAll('.cp-band .ed').forEach((p, i) => p.setAttribute('d', edge(k.lys[i].outer)));
    svg.querySelector('.cp-band .crest').setAttribute('d', edge(k.lys[k.lys.length - 1].outer));
    svg.querySelectorAll('.cp-band .ly, .cp-band .crest').forEach((p) => { p.style.opacity = (1 - col).toFixed(3); });
  }
  // each Agent's layer (and its badge) keeps circling at its own even speed, inner layers faster, like orbits
  const rot = k.lys.map((ly, i) => k.ph[i] + (st.spin || 0) * CP.SPIN[i % CP.SPIN.length]);
  svg.querySelectorAll('.cp-band .ly').forEach((p, i) => p.setAttribute('transform', 'rotate(' + rot[i].toFixed(2) + ' 400 400)'));
  svg.querySelectorAll('.cp-band .ed').forEach((p, i) => p.setAttribute('transform', 'rotate(' + rot[i].toFixed(2) + ' 400 400)'));
  svg.querySelector('.cp-band .crest').setAttribute('transform', 'rotate(' + rot[rot.length - 1].toFixed(2) + ' 400 400)');
  const sw = clamp(st.sweep ?? 1), bg = svg.querySelector('.cp-band');
  if (sw < 1) { svg.querySelector('#cpBandClip path').setAttribute('d', cpWedge(st.sweepFrom || 0, sw * 360)); bg.setAttribute('clip-path', 'url(#cpBandClip)'); } else bg.removeAttribute('clip-path');
  svg.querySelector('.cp-band .base').style.opacity = ((st.dial ?? 1) * (1 - col)).toFixed(3);
  // ruled-out sectors dim
  svg.querySelectorAll('.cp-band .dim path').forEach((p, t) => { p.setAttribute('opacity', ((1 - (st.keep ? st.keep[t] : 1)) * .72 * (1 - col)).toFixed(3)); });
  // ticks drawn on clockwise from north, and a light that runs once around them
  const tkv = clamp(st.ticks ?? 1), tg = svg.querySelector('.cp-ticks');
  if (tkv < 1) { svg.querySelector('#cpTickClip path').setAttribute('d', cpWedge(0, tkv * 360)); tg.setAttribute('clip-path', 'url(#cpTickClip)'); } else tg.removeAttribute('clip-path');
  svg.querySelector('.cp-poles').style.opacity = E.out(clamp(tkv * 1.4 - .4)).toFixed(3);
  const trg = svg.querySelector('.cp-trace'), tr = st.trace, ta = st.traceA ?? 1;
  if (tr != null && tr > 0 && ta > .001) {
    const head = tr * 360, n = 14, tail = 120; let h = '';
    for (let j = 0; j < n; j++) { const a0 = Math.max(0, head - tail * (j + 1) / n), a1 = Math.max(0, head - tail * j / n); if (a1 - a0 < .2) continue; h += '<path d="' + cpArc(381, a0, a1) + '" stroke="var(--orbit)" stroke-width="' + (9 - j * .5).toFixed(1) + '" stroke-opacity="' + ((1 - j / n) * .9 * ta).toFixed(3) + '"/>'; }
    const hp = cpt(381, head); h += '<circle cx="' + hp[0].toFixed(1) + '" cy="' + hp[1].toFixed(1) + '" r="18" fill="url(#cpHead)" opacity="' + ta.toFixed(3) + '"/><circle cx="' + hp[0].toFixed(1) + '" cy="' + hp[1].toFixed(1) + '" r="5" fill="#fff" opacity="' + ta.toFixed(3) + '"/>';
    trg.innerHTML = h;
  } else if (trg.firstChild) trg.innerHTML = '';
  // badges: ride with the petal (spread 23° apart), then take the shortest arc to their own bearing and radius
  svg.querySelectorAll('.cp-pls .pl').forEach((g, i) => {
    // the badge rides its own layer: same speed, on that layer's outer edge just outside the crest
    const x = D.orb.planets[i], li = k.lys.findIndex((ly) => ly.a === x.a || (ly.a && x.a && ly.a.id === x.a.id));
    const a = x.deg + (li >= 0 ? rot[li] : 0), ly = k.lys[Math.max(0, li)], sIdx = Math.round((((x.deg % 360) + 360) % 360) / 360 * N) % (N + 1);
    const r = lerp(CP.R0 + 2 + ly.outer[sIdx] * CP.K + 30, 300, col), q = cpt(r, a);
    g.setAttribute('transform', 'translate(' + f2(q) + ')'); g.style.opacity = (clamp(sw * 2 - i * .2) * (1 - col) * (st.dial ?? 1)).toFixed(3);
  });
  // the flower of the type under the petal; near a sector edge it cross-fades into the neighbour; `mine` hands over to
  // your own flower (same type, your own proportions)
  const u = ((deg % 360) + 360) % 360 / 22.5, i0 = Math.floor(u) % 16, fr = u - Math.floor(u), dd = Math.min(fr, 1 - fr), nb = (i0 + (fr < .5 ? 15 : 1)) % 16;
  const x = dd < .15 ? dd / .15 : 1, op = new Array(17).fill(0);
  if (st.fi != null) op[st.fi] = 1; else { op[i0] = .5 + .5 * x; op[nb] += .5 - .5 * x; }   // fi: show this type's flower whatever the bearing
  const mine = clamp(st.mine || 0); if (mine > 0) { for (let j = 0; j < 16; j++) op[j] *= 1 - mine; op[16] = mine; }
  // wave: { a: the flower folding in, b: the flower opening, u: 0..1 } — petal by petal, clockwise from the lead petal,
  // at an even cadence; each of b's petals starts opening just after the petal of a at the same rank has folded
  const wv = st.wave;
  if (wv) { op.fill(0); if (wv.a != null) op[wv.a] = 1; op[wv.b] = 1; }
  const gr = clamp(st.grow ?? 1), sc = CP.BUD + (1 - CP.BUD) * gr, core = st.core ?? 1;
  k.fls.forEach((g, j) => {
    const o = op[j] * core; g.setAttribute('opacity', o.toFixed(3)); if (o < .002) return;
    g.querySelector('.rot').setAttribute('transform', 'rotate(' + (deg + (st.twist || 0)).toFixed(2) + ' 400 400) translate(400 400) scale(' + sc.toFixed(4) + ') translate(-400 -400)');
    const P = k.pet[j], n = P.length, side = wv ? (j === wv.a ? 'a' : j === wv.b ? 'b' : null) : null;
    P.forEach((q, r) => {
      let v = 1;
      if (side === 'a') v = 1 - E.sine(clamp((wv.u - .5 * r / n) / .3));
      else if (side === 'b') v = E.sine(clamp((wv.u - .2 - .5 * r / n) / .3));
      if (v >= .999) { if (q._v !== 1) { q.removeAttribute('transform'); q.style.opacity = ''; q._v = 1; } return; }
      q._v = v;
      q.setAttribute('transform', 'rotate(' + ((1 - v) * (side === 'a' ? 40 : -40)).toFixed(2) + ' 400 400) translate(400 400) scale(' + Math.max(.001, v).toFixed(4) + ') translate(-400 -400)');
      q.style.opacity = Math.min(1, v * 1.6).toFixed(3);
    });
    k.ht[j].style.opacity = side === 'a' ? (1 - E.sine(clamp((wv.u - .3) / .4))).toFixed(3) : side === 'b' ? E.sine(clamp((wv.u - .3) / .4)).toFixed(3) : '';
  });
  svg.querySelector('.cp-ptr').setAttribute('transform', 'rotate(' + deg.toFixed(2) + ' 400 400)');
  svg.querySelector('.cp-ptr').style.opacity = ((st.needle ?? 1) * (st.dial ?? 1)).toFixed(3);
  svg.querySelector('.cp-dial').style.opacity = (st.dial ?? 1).toFixed(3);
  svg.querySelector('.cp-core').style.opacity = core.toFixed(3);
}
/* ---------- the Orbit mark, live ----------
   The same conical spiral as docs/design/logo/generate.py, variant "spiral" (1.6 turns, radius 9 → 16, rise 14, phase
   0.6, seen at yaw 20° / pitch 45° — the app icon), drawn as a tapered line so it can be traced, turned in 3D and seen
   from above (pitch 90° = a flat spiral whose outer turn is a near circle).
   Open: the five Agent planets fall onto its tail, it is traced, it tips over to a top view and the camera spirals down
   into the hole in its middle, where the first scene is waiting. Close: the compass aurora collapses to one ring, the
   ring grows its inner turn back (a flat spiral seen from above), and the spiral rises into the icon. */
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
function planetsSVG(o) {
  if (!o || o.a <= .001) return '';
  return '<g opacity="' + o.a.toFixed(3) + '">' + AGC.map((c, i) => {
    const a = (o.phase + i * 72) * Math.PI / 180, x = o.cx + Math.cos(a) * o.rx * (1 - o.pull), y = o.cy + Math.sin(a) * o.ry * (1 - o.pull);
    const tx = lerp(x, o.tx, o.pull), ty = lerp(y, o.ty, o.pull), r = o.r || 15;
    return '<circle cx="' + tx.toFixed(1) + '" cy="' + ty.toFixed(1) + '" r="' + (r * 1.9).toFixed(1) + '" fill="' + c + '" opacity=".16"/>' + agBadge(i, tx, ty, r);
  }).join('') + '<ellipse cx="' + o.cx + '" cy="' + o.cy + '" rx="' + (o.rx * (1 - o.pull)).toFixed(1) + '" ry="' + (o.ry * (1 - o.pull)).toFixed(1) + '" fill="none" stroke="rgba(255,255,255,.14)" stroke-dasharray="2 7"/></g>';
}
/* The brand reveal, used as is: docs/design/logo/kit/motion/orbit-reveal.html holds the precomputed frames of the
   mark turning once about its own axis while it tips from pitch 45° to the wordmark's O (pitch 75°) and slides onto
   the O, then the letters rbit·知音 rising one by one (the kit's 1500 ms turn, 110 ms letter stagger, 420 ms each,
   letters from 75 % of the turn; in reverse, the last letter leaves first). Frames and letters are in the wordmark's
   own coordinates (viewBox 38.9 40 2322.1 428.3). */
const REVEAL = { url: '../../../docs/design/logo/kit/motion/orbit-reveal.html', vb: [38.9, 40, 2322.1, 428.3], F: null, L: null, D: 0 };
const revealReady = fetch(REVEAL.url).then((r) => r.text()).then((h) => {
  const doc = new DOMParser().parseFromString(h, 'text/html'), js = doc.querySelector('script').textContent;
  REVEAL.F = JSON.parse(/const F=(\[.*?\]),N=/s.exec(js)[1]);
  REVEAL.D = +/D=(-?[\d.]+)/.exec(js)[1];
  REVEAL.T = +/T=(\d+)/.exec(js)[1] / 1000 / BEAT;                   // turn, beats
  REVEAL.L = [...doc.querySelectorAll('path.l')].map((p) => ({ d: p.getAttribute('d'), i: +/--i:(\d+)/.exec(p.getAttribute('style'))[1], j: +/--j:(\d+)/.exec(p.getAttribute('style'))[1] }));
}).catch((e) => console.error('promo: reveal frames', e));
const MS = (ms) => ms / 1000 / BEAT;
// the wordmark group on screen: centre (cx, cy), k screen px per wordmark unit; v = turn 0..1; on / off = letter beats
function revealSVG(o) {
  const [x, y, w, h] = REVEAL.vb, mx = x + w / 2, my = y + h / 2, F = REVEAL.F, N = F.length;
  let g = '<g opacity="' + o.a.toFixed(3) + '" fill="' + MARK_INK + '" transform="translate(' + o.cx.toFixed(2) + ' ' + o.cy.toFixed(2) + ') scale(' + o.k.toFixed(5) + ') translate(' + (-mx) + ' ' + (-my) + ')">';
  g += '<path d="' + F[Math.round(o.v * (N - 1))] + '" transform="translate(' + (REVEAL.D * (1 - o.v)).toFixed(2) + ' 0)"/>';
  for (const l of REVEAL.L) {
    const pin = E.out(clamp((o.b - o.on - MS(l.i * 110)) / MS(420))), pout = o.off == null ? 0 : E.out(clamp((o.b - o.off - MS(l.j * 110)) / MS(420))), p = pin * (1 - pout);
    if (p > .001) g += '<path d="' + l.d + '" opacity="' + p.toFixed(3) + '" transform="translate(0 ' + (24 * (1 - p)).toFixed(2) + ')"/>';
  }
  return g + '</g>';
}
// bounding box of the mark drawn by orbitSVG at a pose with R = 1 around (0, 0), and of a reveal frame in wordmark units
const MBOX = {};
function boxOf(d) { const p = document.createElementNS(SVGNS, 'path'); p.setAttribute('d', d); orbEl.appendChild(p); const r = p.getBBox(); p.remove(); return r; }
function unitBox(yaw, pitch) {
  const key = yaw + '/' + pitch; if (MBOX[key]) return MBOX[key];
  const m = /d="([^"]+)"/.exec(orbitSVG({ t: 1, yaw, pitch, R: 1000, cx: 0, cy: 0, a: 1 }));
  const r = boxOf(m[1]); return (MBOX[key] = { x: r.x / 1000, y: r.y / 1000, w: r.width / 1000, h: r.height / 1000 });
}
// the orbitSVG pose (R, cx, cy) that puts the mark exactly where a reveal frame sits on screen
function matchFrame(fi, dx, o, yaw, pitch) {
  const key = 'F' + fi, [x, y, w, h] = REVEAL.vb; MBOX[key] = MBOX[key] || boxOf(REVEAL.F[fi]);
  const f = MBOX[key], u = unitBox(yaw, pitch), R = f.width * o.k / u.w;
  const sx = o.cx + (f.x + dx - (x + w / 2)) * o.k, sy = o.cy + (f.y - (y + h / 2)) * o.k;
  return { R, cx: sx - u.x * R, cy: sy - u.y * R };
}
const MARK_INK = '#fff';
// Timings (film beats) of the two mark sequences; the open and close scenes overwrite them with Object.assign.
// open: planets, pulled onto the tail, the mark traced to the icon view (by `hold`), the reveal turn (`turn`), letters
// in (`on`) and out (`off`), the O tips to the top view (`tip`) and the camera dives into it (`dive` → `end`);
// close (scene beats): the band's ring tips into an orbit (`orbit`), the spiral grows along it (`grow`), rises to the
// icon view (`rise` → `settle`), fades (`out`).
const OPEN = { planets: 3.0, pull: 7.5, trace: 7.9, hold: 10.4, turn: 11.0, off: 17.4, tip: 18.6, dive: 20.8, end: 22.6, cy: 500, k0: 1.0, k1: .6 };
const CLOSE = { ring: 104.2, orbit: 104.2, grow: 105.0, rise: 106.6, settle: 108.4, out: 111.6, outDur: 1.4, tilt: 64 };
function orbitAt(bf) {
  let h = '', b = bf;
  const O = OPEN, ready = !!REVEAL.F;
  if (b >= O.planets && b < O.trace + .7) {
    const start = orbitPts(-25, 72)[0];
    h += planetsSVG({ a: E.out(lp(b, O.planets, .8)) * (1 - E.in(lp(b, O.trace + .2, .5))), phase: (b - O.planets) * 95, cx: 960, cy: 790, rx: 380, ry: 64, pull: E.inOut(lp(b, O.pull, 1)), tx: 960 + start[0] * 215, ty: 410 + start[1] * 215 });
  }
  if (ready && b >= O.trace && b < O.end) {
    const W0 = { cx: 960, cy: O.cy, k: O.k0 }, P0 = matchFrame(0, REVEAL.D, W0, 20, 45);
    if (b < O.hold) {
      // traced while it turns from a steep view to the icon view, landing exactly on the reveal's first frame
      const turn = E.out(lp(b, O.trace, O.hold - O.trace));
      h += orbitSVG({ t: E.inOut(lp(b, O.trace, 2.4)), yaw: lerp(-25, 20, turn), pitch: lerp(72, 45, turn), R: P0.R, cx: P0.cx, cy: P0.cy, a: 1, head: 1 - lp(b, O.trace + 2.2, .5), color: MARK_INK });
    } else if (b < O.tip) {
      const v = E.inOut(lp(b, O.turn, REVEAL.T)), k = lerp(O.k0, O.k1, E.inOut(lp(b, O.turn, REVEAL.T)));
      h += revealSVG({ a: 1, cx: 960, cy: O.cy, k, v, b, on: O.turn + REVEAL.T * .75, off: O.off });
    } else {
      // the O (pitch 75°) tips to the top view, moves to the centre and grows; then the camera dives into its hole
      const P1 = matchFrame(REVEAL.F.length - 1, 0, { cx: 960, cy: O.cy, k: O.k1 }, 20, 75);
      const tilt = E.inOut(lp(b, O.tip, O.dive - O.tip)), dive = lp(b, O.dive, O.end - O.dive);
      const R = lerp(P1.R, 270, tilt) * Math.pow(18, E.in(dive)), cx = lerp(P1.cx, 960, tilt), cy = lerp(P1.cy, 540, tilt);
      $('#hole1').style.clipPath = b >= O.dive ? 'circle(' + (R * ORB.r0 / ORB.r1 * .9).toFixed(1) + 'px at ' + cx.toFixed(1) + 'px ' + cy.toFixed(1) + 'px)' : 'circle(0px at 960px 540px)';
      h += orbitSVG({ t: 1, yaw: lerp(20, 0, tilt) - 620 * E.in(dive), pitch: lerp(75, 90, tilt), R, cx, cy, a: 1 - E.in(lp(b, O.end - .6, .6)), color: MARK_INK });
    }
  }
  if (b >= O.end && b < O.end + .2) $('#hole1').style.clipPath = 'none';
  b = bf - SHIFT['60-close'];                                        // the close runs on scene beats
  if (b >= CLOSE.ring) {
    const C = CLOSE, R0 = 300 * decks[2].C.s, tip = E.inOut(lp(b, C.orbit, 1.2)), grow = E.inOut(lp(b, C.grow, C.rise - C.grow)), rise = E.inOut(lp(b, C.rise, C.settle - C.rise));
    const pitch = lerp(lerp(90, 90 - C.tilt, tip), 45, rise), a = E.out(lp(b, C.grow, .3)) * (1 - E.inOut(lp(b, C.out, C.outDur)));
    // five Agent planets ride the orbit while the spiral grows out of it, as at the start of the film
    if (b < C.rise + .6) h += planetsSVG({ a: E.out(lp(b, C.orbit + .3, .6)) * (1 - E.inOut(lp(b, C.rise - .2, .8))), phase: (b - C.orbit) * 70, cx: 960, cy: 540, rx: R0, ry: R0 * Math.sin(pitch * Math.PI / 180), pull: 0, tx: 960, ty: 540 });
    // while it lies on the orbit, the tail (z = rise / 2) sits on the compass ring: undo its projected height
    const R = lerp(R0, 215, rise), lift = (ORB.rise / 2 / ORB.r1) * R * Math.cos(pitch * Math.PI / 180) * (1 - rise);
    h += orbitSVG({ t0: 1 - grow * .999, t: 1, yaw: lerp(0, 20, rise), pitch, R, cx: 960, cy: lerp(540, 410, rise) + lift, a, color: MARK_INK });
  }
  orbEl.innerHTML = '<defs><radialGradient id="orbGlow"><stop offset="0" stop-color="rgba(255,255,255,.9)"/><stop offset="1" stop-color="rgba(255,255,255,0)"/></radialGradient></defs>' + h;
}

/* a macOS pointer that glides to a control, presses it, and then the action runs — one per app copy, drawn inside the
   copy so it follows the camera, counter-scaled so it keeps a constant size on screen */
const CURSOR_SVG = '<svg viewBox="0 0 28 28" width="28" height="28"><path d="M6 3.5v19.2l4.6-4.4 3 6.9 3.3-1.4-2.9-6.8h6.5z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
const clicks = [];
// o.bloom: colour of a press bloom (a radial fill under the pointer, then a soft glow that spreads to about 3×, as in
// the GWI reference); o.size: its diameter on screen in px; o.glide: beats the pointer takes to reach the control.
function clickAt(d, b, sel, fn, o = {}) { clicks.push({ d, b: b + SH, sel, fn, o }); at(b, () => { const el = find(d, sel); if (el) fn(app(d), el); else console.warn('promo: no click target', sel); }); }
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
   must hand over to the next one; times are beats (132 BPM, 1 beat = 0.455 s). */
const SCENES = [];
function scene(name, fn) { SCENES.push({ name, fn }); }
function script() { for (const s of SCENES) { SH = SHIFT[s.name] || 0; try { s.fn(); } catch (e) { console.error('scene ' + s.name, e); } } SH = 0; }
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
  // scrollIntoView inside an app copy (solo) also scrolls the promo page and the stage itself: pin them every frame
  stage.scrollLeft = stage.scrollTop = 0; document.documentElement.scrollLeft = document.documentElement.scrollTop = 0; document.body.scrollLeft = document.body.scrollTop = 0;
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
  revealReady.then(boot);
}));
function boot() {
  script(); PROMO.duration = (END + SHIFT['60-close']) * BEAT; tweens.sort((a, b) => a.b - b.b); cues.sort((a, b) => a.b - b.b); step(0);
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

/* AGD — the one set of five Agent dots that runs through the whole film (STORYBOARD.md「共享 API (a)」「转场关键帧」).
   Every dot is always its Agent's logo badge (agBadge), never a plain dot. All beats are film beats.

   AGD.ID = ['cc','cx','gm','ds','cp'] (= AGID, index i = 0..4), AGD.NAME = display names, AGD.C = AGC colours.
   AGD.key(b, form, o)       formation keyframe from beat b. Each dot eases (o.ease, default E.inOut) over o.dur beats
                             (1.2), staggered o.stag beats per index (.08), from its LIVE position in the previous
                             formation (which keeps moving during the blend) to the new formation. o.arc = px the path
                             bows upwards; o.polar = [cx, cy] blends on ellipse parameters (K0) instead of straight chords.
                             The first key (no previous formation) pops the dots in: r 0 → r with E.back over .3 beats.
   forms (o params; x/y stage px, r badge radius px, a opacity):
     'off'      shrink to r·.4 and fade out where they are
     'pts'      pts: [[x, y] ×5], r (40), a (1), drift (12 px Lissajous, periods 9–14 beats, phase hash01(i))
     'ring'     cx, cy, R, ph (deg of i = 0, 0 = up, clockwise), spin (deg/beat), r — B = ph + 72i + spin·(b − key b)
     'compass'  r (optional) — cpBadge(i): rides the compass badge of Agent i through deck 2's camera (drawCompass must be
                called every frame while this is live; pass pl: 0 so the compass draws no badges of its own)
     'column'   x, y0, gap, r, order ([row of dot i] | 'y' = rank by y at the key beat) — (x, y0 + order[i]·gap)
     'row'      cx, y, gap, r, order ([slot of dot i] | 'x') — (cx + (order[i] − 2)·gap, y)
     'arc'      cx, cy, gap, sag, r, a, order ([slot of dot i], default i) — slot k: (cx + (k − 2)·gap, cy + sag·((k − 2)/2)²);
                sag > 0 = ∩ (ends hang down), sag < 0 = ∪ (ends turn up)
     'merge'    x, y, r, spin (deg/beat of the ring, 6) — dots fan ±12 px, then close into one over .4 beats; cc on
                top, ringed by 5 Agent-coloured 72° arcs (r + 7, 1.5 px)
     'orbit'    cx, cy, rx, ry, ph, spin, r — θ = ph + 72i + spin·(b − key b), (cx + rx·sinθ, cy − ry·cosθ); near half
                ±12 % larger/brighter; far half (cosθ > 0) is drawn in #agdBack, behind the mark
   Live parameters: every numeric param of pts / ring / arc / column / row / merge / orbit may be a function (b, i) =>
                             number, evaluated each frame (a pen / caret following words, a merge dot riding a playhead)
                             without breaking the key's live blend; pts may be (b, i) => [x, y]. merge fans in once from
                             its key beat; moving x / y never fans it out again.
   AGD.P.cluster = { cx 960, cy 560, R 60, r 34, spin 8 } ('ring'), AGD.P.arcB = { cx 960, cy 608, gap 112, sag 24, r 34 },
   AGD.P.arcD = { cx 960, cy 560, gap 108, sag 24, r 34 } ('arc') — compact presets, spread them: { ...AGD.P.arcB, dur }.
   AGD.P.scatterA / arc / scatterC  deprecated aliases (point arrays for 'pts') of cluster / arcB / cluster.
   AGD.pts(form, o)          the 5 [x, y] of a ring / arc / row / column formation at its key beat (no drift, no spin).
   AGD.centroid(b)           { x, y, rho }: mean of the dots' AGD.pos and their largest distance from it (a ≤ .02 skipped).
   AGD.follow(b0, b1, fn, o) per-frame override: fn(i, b, base) → partial { x, y, r, a } or null (no override). Blends in
                             and out over o.blend beats (.6). Wins over keys.
   AGD.pulse(i, b, k, dur)   the dot's r is multiplied by k and back (sine) over dur beats (.4): breathing 1.06, flinch .94
   AGD.pos(i, b)             final { x, y, r, a } of dot i at beat b (keys + follow + pulse) — read this at hand-overs
   AGD.link(b0, b1, i, to, o) 2 px cubic from dot i to to = [x, y] | (b) => [x, y]; o.bend (.4 of dx, horizontal tangents),
                             o.draw (.35 beats, grows from the dot), o.out (.3, retracts into the dot), o.color (Agent
                             colour mixed with white, opacity .7), o.width (2), o.dash ('3 6' = dashed), o.pulse (bright
                             dots per beat flowing dot → target; 0)
   AGD.bubble(i, b0, b1, text, o) HTML bubble anchored to dot i (follows it). o.dx / o.dy (number or (b) => number): tail
                             offset from the dot centre (0, −r − 18 = above; dy > 0 hangs it below, tail up); o.kind 'ask'
                             (dark glass) | 'fix' (amber ⟲ tag, warm border). Pops from the dot .25 beats (E.back), shrinks
                             back into it .2 beats before b1. o.stem: a 1.5 px white 30 % line from the tail to the dot
                             centre (upper-layer bubbles). o.replace (true): when a newer bubble (also not replace: false)
                             pops on the same dot, this one shrinks back into the dot over .2 beats from that beat; pass
                             replace: false to keep stacking (pushing) instead.
   AGD.glow(i, b0, b1, v)    soft Agent-coloured glow behind dot i (v 0..1, .3-beat ramps)
   AGD.chat(b0, b1, { x, y, w, from, to }) → c   app-style input box (88 px high, centre x, y), rises 40 px + fades in
                             .4 beats from b0, sinks out over the last .4 beats. from: (b) => { x, y } (e.g. AGD.centroid):
                             instead grows out of that point (scale .15 → 1, E.out .6 beats, a 1 by .25 beats); to: (b) =>
                             { x, y }: shrinks back into that point over the last .4 beats (E.in). c.type(b, text, dur): types it evenly over dur beats.
                             c.send(b, i, o): button press at b, box clears, the text pops from dot i as
                             AGD.bubble(i, b + .15, o.until ?? b + 2, text, o), with a .3-beat light trail box → dot.
   Layers: #agdBack (under #orbit: far orbit half; scenes may draw their own guides there via AGD.back()), #agd (over
   #orbit: links, glows, badges), #agdb (HTML: bubbles, input boxes). applyAgents(t) runs each frame after the cameras
   and the mark. */
'use strict';
const AGD = { ID: AGID, NAME: ['Claude Code', 'Codex', 'Gemini CLI', 'DeepSeek', 'Copilot'], C: AGC };
AGD.P = {
  cluster: { cx: 960, cy: 560, R: 60, r: 34, spin: 8 },                 // 1a, 'ring'
  arcB: { cx: 960, cy: 608, gap: 112, sag: 24, r: 34 },                 // 1b, 'arc'
  arcD: { cx: 960, cy: 560, gap: 108, sag: 24, r: 34 }                  // 1d, 'arc'
};
css(`
#agdBack,#agd{position:absolute;inset:0;width:1920px;height:1080px;pointer-events:none;overflow:visible}
#agdb{position:absolute;inset:0;pointer-events:none}
.agb{position:absolute;left:0;top:0;display:inline-flex;align-items:center;gap:10px;padding:14px 22px;border-radius:22px;white-space:nowrap;
  font:500 28px var(--sans);color:#fff;background:rgba(22,24,29,.82);border:1px solid rgba(255,255,255,.16);
  box-shadow:0 12px 34px rgba(0,0,0,.5);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);will-change:transform,opacity}
.agb::after{content:'';position:absolute;left:var(--tx,50%);width:14px;height:14px;background:inherit;border:inherit;border-width:0 1px 1px 0;transform:translateX(-50%) rotate(45deg)}
.agb.dn::after{bottom:-8px}
.agb.up::after{top:-8px;transform:translateX(-50%) rotate(225deg)}
.agb.fix{border-color:rgba(243,178,92,.45);background:rgba(30,24,18,.86)}
.agb.fix i{font-style:normal;font:600 22px var(--sans);color:#f3b25c;display:inline-grid;place-items:center;width:30px;height:30px;border-radius:50%;background:rgba(243,178,92,.16)}
.agchat{position:absolute;left:0;top:0;height:88px;box-sizing:border-box;border-radius:28px;display:flex;align-items:center;gap:18px;padding:0 16px 0 26px;
  background:rgba(24,26,31,.78);border:1px solid rgba(255,255,255,.16);box-shadow:0 24px 70px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.06);
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);font:400 34px var(--sans);color:#fff;will-change:transform,opacity}
.agchat .pl{font:300 44px var(--sans);color:rgba(255,255,255,.55);line-height:1;margin-top:-4px}
.agchat .tx{flex:1;white-space:nowrap;overflow:hidden}
.agchat .tx.ph{color:rgba(255,255,255,.38)}
.agchat .car{display:inline-block;width:2px;height:38px;margin-left:2px;vertical-align:-7px;background:#fff}
.agchat .snd{width:58px;height:58px;border-radius:50%;background:#e2602b;display:grid;place-items:center;flex:none}
.agchat .snd svg{width:26px;height:26px}
`);
(() => {
  const mk = (id, before) => { const e = document.createElementNS(SVGNS, 'svg'); e.id = id; e.setAttribute('viewBox', '0 0 1920 1080'); e.setAttribute('aria-hidden', 'true'); stage.insertBefore(e, before); return e; };
  if (!$('#agdBack')) mk('agdBack', orbEl);
  if (!$('#agd')) mk('agd', fxEl);
  if (!$('#agdb')) { const d = document.createElement('div'); d.id = 'agdb'; stage.insertBefore(d, fxEl); }
})();
const AGD_KEYS = [], AGD_FOL = [], AGD_PUL = [], AGD_LINKS = [], AGD_BUB = [], AGD_GLOW = [], AGD_CHATS = [], AGD_BACK = [];
let AGD_SORTED = false;
const agWrap = (d) => ((d % 360) + 540) % 360 - 180;       // to (−180, 180]
const agDeg = Math.PI / 180;
AGD.key = (b, form, o = {}) => { AGD_KEYS.push({ b: b + SH, form, o }); AGD_SORTED = false; };
AGD.follow = (b0, b1, fn, o = {}) => AGD_FOL.push({ b0, b1, fn, blend: o.blend ?? .6 });
AGD.pulse = (i, b, k, dur = .4) => AGD_PUL.push({ i, b, k, dur });
AGD.link = (b0, b1, i, to, o = {}) => AGD_LINKS.push({ b0, b1, i, to, o, id: AGD_LINKS.length });
AGD.bubble = (i, b0, b1, text, o = {}) => AGD_BUB.push({ i, b0, b1, text, o, el: null });
AGD.glow = (i, b0, b1, v = 1) => AGD_GLOW.push({ i, b0, b1, v });
// a scene's own drawing under the mark and the dots: fn(b) → SVG string, drawn into #agdBack in [b0, b1)
AGD.back = (b0, b1, fn) => AGD_BACK.push({ b0, b1, fn });

// one formation, evaluated live at beat b → { x, y, r, a, back, el } (el: ellipse descriptor for polar blends, orbit only)
// a formation parameter, live: o[k] may be a number or (b, i) => number
const agV = (o, k, d, b, i) => { const x = o[k]; return typeof x === 'function' ? x(b, i) : x ?? d; };
function agForm(n, i, b) {
  const K = AGD_KEYS[n], o = K.o, f = K.form, db = b - K.b, v = (k, d) => agV(o, k, d, b, i);
  switch (f) {
    case 'pts': {
      const h = hash01(i, 5), dr = v('drift', 12), px = 9 + 5 * hash01(i, 6), py = 9 + 5 * hash01(i, 7), q = typeof o.pts === 'function' ? o.pts(b, i) : o.pts[i];
      return { x: q[0] + dr * Math.sin(2 * Math.PI * (b / px + h)), y: q[1] + dr * Math.sin(2 * Math.PI * (b / py + h * 1.7) ), r: v('r', 40), a: v('a', 1) };
    }
    case 'ring': {
      const B = v('ph', 0) + 72 * i + v('spin', 0) * db, R = v('R', 0);
      return { x: v('cx', 960) + R * Math.sin(B * agDeg), y: v('cy', 540) - R * Math.cos(B * agDeg), r: v('r', 40), a: v('a', 1) };
    }
    case 'arc': {
      const k = (Array.isArray(o.order) ? o.order[i] : i) - 2;
      return { x: v('cx', 960) + k * v('gap', 108), y: v('cy', 560) + v('sag', 0) * (k / 2) * (k / 2), r: v('r', 34), a: v('a', 1) };
    }
    case 'orbit': {
      const th = v('ph', 0) + 72 * i + v('spin', 0) * db, c = Math.cos(th * agDeg), cx = v('cx', 960), cy = v('cy', 540), rx = v('rx', 0), ry = v('ry', 0);
      return { x: cx + rx * Math.sin(th * agDeg), y: cy - ry * c, r: v('r', 18) * (1 - .12 * c), a: v('a', 1) * (1 - .12 * Math.max(0, c)), back: c > 0, el: { cx, cy, rx, ry, th } };
    }
    case 'compass': { const q = cpBadge(i); if (o.r != null) q.r = o.r; if (o.a != null) q.a = o.a; return q; }
    case 'column': case 'row': {
      if (!K.ord) {
        if (Array.isArray(o.order)) K.ord = o.order;
        else if (o.order === 'y' || o.order === 'x') {
          const k = o.order, v = [0, 1, 2, 3, 4].map((j) => agPos(n - 1, j, K.b)[k]);
          const rk = [0, 1, 2, 3, 4].sort((p, q) => v[p] - v[q]); K.ord = []; rk.forEach((j, r) => { K.ord[j] = r; });
        } else K.ord = [0, 1, 2, 3, 4];
      }
      const r = v('r', 36), a = v('a', 1);
      return f === 'column' ? { x: v('x', 960), y: v('y0', 540) + K.ord[i] * v('gap', 60), r, a } : { x: v('cx', 960) + (K.ord[i] - 2) * v('gap', 60), y: v('y', 540), r, a };
    }
    case 'merge': {
      const c = E.inOut(clamp((db - (o.dur ?? 1.2) - (o.stag ?? .08) * 4) / .4 + 1)), fan = (i - 2) * 6 * (1 - c), r = v('r', 44);
      return { x: v('x', 960) + fan, y: v('y', 540) + Math.abs(i - 2) * 3 * (1 - c), r: i ? r * (1 - .05 * c) : r, a: v('a', 1), merged: c };
    }
    case 'off': { const q = agPos(n - 1, i, b); return Object.assign({}, q, { r: q.r * .4, a: 0, el: null }); }
  }
  return { x: 960, y: 540, r: 40, a: 0 };
}
// the formation chain up to key n, at beat b (live blends of live formations)
function agPos(n, i, b) {
  if (n < 0) return null;
  const K = AGD_KEYS[n], o = K.o, to = agForm(n, i, b), dur = o.dur ?? 1.2, st = (o.stag ?? .08) * i;
  const prev = n > 0 ? agPos(n - 1, i, b) : null;
  if (!prev || prev.a <= 0 && K.form !== 'off') {             // nothing before: pop in (E.back)
    const p = clamp((b - K.b - st) / Math.max(.3, dur)), pe = ease.back(p);
    return Object.assign({}, to, { r: to.r * Math.max(0, pe), a: to.a * Math.min(1, p * 2) });
  }
  const p = clamp((b - K.b - st) / Math.max(1e-3, dur));
  if (p >= 1) return to;
  const e = (o.ease || E.inOut)(p);
  let q;
  if (o.polar) {
    const [pcx, pcy] = o.polar, ell = (s) => s.el || { cx: pcx, cy: pcy, rx: Math.hypot(s.x - pcx, s.y - pcy), ry: Math.hypot(s.x - pcx, s.y - pcy), th: Math.atan2(s.x - pcx, -(s.y - pcy)) / agDeg };
    const A = ell(prev), B = ell(to), cx = lerp(A.cx, B.cx, e), cy = lerp(A.cy, B.cy, e), rx = lerp(A.rx, B.rx, e), ry = lerp(A.ry, B.ry, e);
    const th = A.th + agWrap(B.th - A.th) * e;
    q = { x: cx + rx * Math.sin(th * agDeg), y: cy - ry * Math.cos(th * agDeg), el: { cx, cy, rx, ry, th } };
  } else q = { x: lerp(prev.x, to.x, e), y: lerp(prev.y, to.y, e) };
  q.y -= (o.arc || 0) * 4 * e * (1 - e);
  q.r = lerp(prev.r, to.r, e); q.a = lerp(prev.a, to.a, e); q.back = e < .5 ? prev.back : to.back;
  q.merged = to.merged != null ? to.merged * e : prev.merged ? prev.merged * (1 - e) : 0;
  return q;
}
function agSort() { if (!AGD_SORTED) { AGD_KEYS.sort((a, b) => a.b - b.b); AGD_SORTED = true; } }
AGD.pos = (i, b) => {
  agSort();
  let n = -1; for (let k = 0; k < AGD_KEYS.length; k++) if (AGD_KEYS[k].b <= b) n = k;
  let q = n < 0 ? { x: 960, y: 540, r: 0, a: 0 } : Object.assign({}, agPos(n, i, b));
  for (const f of AGD_FOL) {
    if (b < f.b0 || b >= f.b1) continue;
    const w = Math.min(E.inOut(clamp((b - f.b0) / f.blend)), E.inOut(clamp((f.b1 - b) / f.blend))), v = f.fn(i, b, q);
    if (!v) continue;
    for (const k of ['x', 'y', 'r', 'a']) if (v[k] != null) q[k] = lerp(q[k], v[k], w);
  }
  for (const u of AGD_PUL) if (u.i === i && b >= u.b && b < u.b + u.dur) q.r *= 1 + (u.k - 1) * Math.sin(Math.PI * (b - u.b) / u.dur);
  return q;
};
AGD.centroid = (b) => {
  const P = [0, 1, 2, 3, 4].map((i) => AGD.pos(i, b)).filter((p) => p.a > .02);
  if (!P.length) return { x: 960, y: 540, rho: 0 };
  const x = P.reduce((s, p) => s + p.x, 0) / P.length, y = P.reduce((s, p) => s + p.y, 0) / P.length;
  return { x, y, rho: Math.max(...P.map((p) => Math.hypot(p.x - x, p.y - y))) };
};
// static points of a formation (live params read at its own key beat 0); used for the deprecated point presets
AGD.pts = (form, o) => [0, 1, 2, 3, 4].map((i) => {
  const v = (k, d) => agV(o, k, d, 0, i), k = (Array.isArray(o.order) ? o.order[i] : i) - 2;
  if (form === 'ring') { const B = (v('ph', 0) + 72 * i) * agDeg, R = v('R', 0); return [v('cx', 960) + R * Math.sin(B), v('cy', 540) - R * Math.cos(B)]; }
  if (form === 'arc') return [v('cx', 960) + k * v('gap', 108), v('cy', 560) + v('sag', 0) * (k / 2) * (k / 2)];
  if (form === 'row') return [v('cx', 960) + k * v('gap', 60), v('y', 540)];
  return [v('x', 960), v('y0', 540) + (k + 2) * v('gap', 60)];
});
// v17 point presets, kept as aliases of the compact ones until every scene has switched (STORYBOARD v17.1 V3.6)
AGD.P.scatterA = AGD.pts('ring', AGD.P.cluster);
AGD.P.arc = AGD.pts('arc', AGD.P.arcB);
AGD.P.scatterC = AGD.pts('ring', AGD.P.cluster);

// cubic from P to T with horizontal tangents; returns point at u
function agCubic(P, T, bend) { const dx = (T[0] - P[0]) * bend; return [P, [P[0] + dx, P[1]], [T[0] - dx, T[1]], T]; }
function agAt(c, u) { const v = 1 - u; return [0, 1].map((k) => v * v * v * c[0][k] + 3 * v * v * u * c[1][k] + 3 * v * u * u * c[2][k] + u * u * u * c[3][k]); }
const agMix = (i) => 'color-mix(in oklab, ' + AGC[i] + ' 50%, #fff)';
let agFrame = -1, agCache = [];
function applyAgents(t) {
  const b = t / BEAT; agSort();
  const P = [0, 1, 2, 3, 4].map((i) => AGD.pos(i, b)); agCache = P; agFrame = b;
  let back = '', front = '', defs = '';
  for (const g of AGD_BACK) if (b >= g.b0 && b < g.b1) { try { back += g.fn(b) || ''; } catch (e) { console.error('AGD.back', e); g.b1 = -1; } }
  // links
  for (const L of AGD_LINKS) {
    if (b < L.b0 || b >= L.b1) continue;
    const o = L.o, p = P[L.i], T = typeof L.to === 'function' ? L.to(b) : L.to, c = agCubic([p.x, p.y], T, o.bend ?? .4);
    const vis = Math.min(E.out(clamp((b - L.b0) / (o.draw ?? .35))), 1 - E.in(clamp((b - (L.b1 - (o.out ?? .3))) / (o.out ?? .3))));
    if (vis <= .002) continue;
    const d = 'M' + c[0].map((v) => v.toFixed(1)).join(' ') + 'C' + c.slice(1).map((q) => q.map((v) => v.toFixed(1)).join(' ')).join(' ');
    const col = o.color || agMix(L.i), w = o.width ?? 2;
    if (o.dash) {
      defs += '<mask id="agm' + L.id + '" maskUnits="userSpaceOnUse" x="0" y="0" width="1920" height="1080"><path d="' + d + '" pathLength="1" fill="none" stroke="#fff" stroke-width="' + (w + 6) + '" stroke-dasharray="' + vis.toFixed(4) + ' 2"/></mask>';
      front += '<path d="' + d + '" fill="none" stroke="' + col + '" stroke-opacity=".7" stroke-width="' + w + '" stroke-linecap="round" stroke-dasharray="' + o.dash + '" mask="url(#agm' + L.id + ')"/>';
    } else front += '<path d="' + d + '" pathLength="1" fill="none" stroke="' + col + '" stroke-opacity=".7" stroke-width="' + w + '" stroke-linecap="round" stroke-dasharray="' + vis.toFixed(4) + ' 2"/>';
    if (o.pulse) for (let k = 0; k < o.pulse; k++) {
      const u = (((b - L.b0) - k / o.pulse) % 1 + 1) % 1; if (u > vis || b - L.b0 < k / o.pulse) continue;
      const q = agAt(c, u), fa = Math.sin(Math.PI * u);
      front += '<circle cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="9" fill="' + col + '" opacity="' + (.35 * fa).toFixed(3) + '"/><circle cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="3.2" fill="#fff" opacity="' + (.95 * fa).toFixed(3) + '"/>';
    }
  }
  // send trails (chat → dot)
  for (const c of AGD_CHATS) for (const s of c.sends) {
    const u = (b - s.b) / .3; if (u < 0 || u >= 1) continue;
    const p = P[s.i], A = [c.o.x + c.o.w / 2 - 45, c.o.y], h = E.inOut(u), tl = E.inOut(Math.max(0, u - .35) / .65);
    const x0 = lerp(A[0], p.x, tl), y0 = lerp(A[1], p.y, tl), x1 = lerp(A[0], p.x, h), y1 = lerp(A[1], p.y, h);
    front += '<line x1="' + x0.toFixed(1) + '" y1="' + y0.toFixed(1) + '" x2="' + x1.toFixed(1) + '" y2="' + y1.toFixed(1) + '" stroke="#fff" stroke-opacity=".4" stroke-width="2.5" stroke-linecap="round"/><circle cx="' + x1.toFixed(1) + '" cy="' + y1.toFixed(1) + '" r="4" fill="#fff" opacity=".55"/>';
  }
  // glows
  for (const g of AGD_GLOW) {
    if (b < g.b0 - .3 || b >= g.b1 + .3) continue;
    const v = g.v * Math.min(E.inOut(clamp((b - g.b0 + .3) / .3)), E.inOut(clamp((g.b1 + .3 - b) / .3))), p = P[g.i];
    if (v > .002 && p.a > .002) front += '<circle cx="' + p.x.toFixed(1) + '" cy="' + p.y.toFixed(1) + '" r="' + (p.r * 2.6).toFixed(1) + '" fill="url(#agg' + g.i + ')" opacity="' + (v * p.a).toFixed(3) + '"/>';
  }
  // bubble stems (o.stem): tail → dot centre, under the badges
  for (const u of AGD_BUB) {
    if (!u.o.stem) continue;
    const q = agBub(u, b, P[u.i]); if (!q.live) continue;
    const p = P[u.i], v = q.sc * Math.min(1, p.a + .2);
    if (v <= .002) continue;
    const ex = lerp(p.x, q.ax, Math.max(0, q.sc)), ey = lerp(p.y, q.ay, Math.max(0, q.sc));
    front += '<line x1="' + p.x.toFixed(1) + '" y1="' + p.y.toFixed(1) + '" x2="' + ex.toFixed(1) + '" y2="' + ey.toFixed(1) + '" stroke="#fff" stroke-opacity="' + (.3 * Math.min(1, v)).toFixed(3) + '" stroke-width="1.5" stroke-linecap="round"/>';
  }
  // badges: cc last (on top, for 'merge'); far orbit half into #agdBack
  for (const i of [4, 3, 2, 1, 0]) {
    const p = P[i]; if (p.a <= .002 || p.r <= .3) continue;
    const s = '<g opacity="' + Math.min(1, p.a).toFixed(3) + '">' + agBadge(i, p.x, p.y, p.r) + '</g>';
    if (p.back) back += s; else front += s;
  }
  const m = P[0].merged || 0;
  if (m > .01) {
    const K = AGD_KEYS.filter((k) => k.form === 'merge' && k.b <= b).pop(), sp = K ? agV(K.o, 'spin', 6, b, 0) * (b - K.b) : 0, p = P[0], rr = p.r + 7;
    for (let i = 0; i < 5; i++) { const a0 = sp + i * 72 + 3, a1 = sp + i * 72 + 69, q0 = [p.x + rr * Math.sin(a0 * agDeg), p.y - rr * Math.cos(a0 * agDeg)], q1 = [p.x + rr * Math.sin(a1 * agDeg), p.y - rr * Math.cos(a1 * agDeg)];
      front += '<path d="M' + q0[0].toFixed(1) + ' ' + q0[1].toFixed(1) + 'A' + rr.toFixed(1) + ' ' + rr.toFixed(1) + ' 0 0 1 ' + q1[0].toFixed(1) + ' ' + q1[1].toFixed(1) + '" fill="none" stroke="' + AGC[i] + '" stroke-width="1.5" opacity="' + (m * Math.min(1, p.a)).toFixed(3) + '"/>'; }
  }
  const gd = AGC.map((c, i) => '<radialGradient id="agg' + i + '"><stop offset="0" style="stop-color:' + c + ';stop-opacity:.55"/><stop offset="1" style="stop-color:' + c + ';stop-opacity:0"/></radialGradient>').join('');
  $('#agdBack').innerHTML = back;
  $('#agd').innerHTML = '<defs>' + gd + defs + '</defs>' + front;
  agBubbles(b, P); agChats(b, t);
}
// a bubble's end: its b1, or .2 beats after a newer bubble pops on the same dot (o.replace, default true on both)
function agBubEnd(u) {
  let e = u.b1;
  if (u.o.replace === false) return e;
  for (const w of AGD_BUB) if (w !== u && w.i === u.i && w.o.replace !== false && w.b0 > u.b0 && w.b0 + .2 < e) e = w.b0 + .2;
  return e;
}
// live state of bubble u at beat b on dot p: tail anchor (ax, ay), dx, dy, scale sc, shrink pout, end
function agBub(u, b, p) {
  const end = agBubEnd(u), live = b >= u.b0 && b < end;
  const dx = typeof u.o.dx === 'function' ? u.o.dx(b) : u.o.dx ?? 0, dy0 = typeof u.o.dy === 'function' ? u.o.dy(b) : u.o.dy, dy = dy0 ?? -p.r - 18;
  const pin = ease.back(clamp((b - u.b0) / .25)), pout = E.in(clamp((b - (end - .2)) / .2));
  return { live, end, dx, dy, ax: p.x + dx, ay: p.y + dy, pout, sc: Math.max(0, pin) * (1 - pout) };
}
function agBubbles(b, P) {
  const box = $('#agdb');
  for (const u of AGD_BUB) {
    const live = b >= u.b0 && b < agBubEnd(u);
    if (live && !u.el) { u.el = document.createElement('div'); u.el.className = 'agb ' + (u.o.kind || 'ask'); u.el.innerHTML = (u.o.kind === 'fix' ? '<i>⟲</i>' : '') + '<span></span>'; u.el.lastChild.textContent = u.text; box.appendChild(u.el); }
    if (!live && u.el) { u.el.remove(); u.el = null; }
    if (!u.el) continue;
    const p = P[u.i], { dx, dy, ax, ay, pout, sc } = agBub(u, b, p);
    const up = dy > 0, w = u.el.offsetWidth, h = u.el.offsetHeight;
    // the tail sits at the anchor; the box is centred on it, shifted sideways with dx so the tail leans toward the dot
    const tx = clamp(.5 - dx / Math.max(1, w), .15, .85);
    u.el.classList.toggle('up', up); u.el.classList.toggle('dn', !up); u.el.style.setProperty('--tx', (tx * 100).toFixed(1) + '%');
    const left = ax - w * tx, top = up ? ay + 8 : ay - h - 8;
    const ox = p.x - left, oy = p.y - top;                     // grows out of / back into the dot centre
    u.el.style.transformOrigin = (lerp(w * tx, ox, pout)).toFixed(1) + 'px ' + (lerp(up ? 0 : h, oy, pout)).toFixed(1) + 'px';
    u.el.style.transform = 'translate(' + left.toFixed(1) + 'px,' + top.toFixed(1) + 'px) scale(' + sc.toFixed(3) + ')';
    u.el.style.opacity = (Math.min(1, clamp((b - u.b0) / .12)) * (1 - pout) * Math.min(1, p.a + .2)).toFixed(3);
  }
}
const AG_SEND = '<svg viewBox="0 0 24 24"><path d="M12 19V5M5.5 11.5L12 5l6.5 6.5" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
AGD.chat = (b0, b1, o) => {
  const c = { b0, b1, o, types: [], sends: [], el: null };
  c.type = (b, text, dur) => { c.types.push({ b, text, dur }); return c; };
  c.send = (b, i, so = {}) => { const ty = c.types.filter((x) => x.b <= b).pop(); c.sends.push({ b, i }); if (ty) AGD.bubble(i, b + .15, so.until ?? b + 2, ty.text, so); return c; };
  AGD_CHATS.push(c); return c;
};
function agChats(b, t) {
  for (const c of AGD_CHATS) {
    const live = b >= c.b0 && b < c.b1;
    if (live && !c.el) { c.el = document.createElement('div'); c.el.className = 'agchat'; c.el.innerHTML = '<span class="pl">+</span><span class="tx"></span><span class="snd">' + AG_SEND + '</span>'; c.el.style.width = c.o.w + 'px'; $('#agdb').appendChild(c.el); }
    if (!live && c.el) { c.el.remove(); c.el = null; }
    if (!c.el) continue;
    const o = c.o;
    if (o.from || o.to) {
      // grows out of / shrinks back into a point (e.g. the dots' centroid): centre and scale blend, origin at the box centre
      let x = o.x, y = o.y, s = 1, a = 1;
      if (o.from) { const f = o.from(b), e = E.out(clamp((b - c.b0) / .6)); x = lerp(f.x, x, e); y = lerp(f.y, y, e); s = lerp(.15, 1, e); a = clamp((b - c.b0) / .25); }
      else { const pin = E.out(clamp((b - c.b0) / .4)); y += 40 * (1 - pin); a = pin; }
      if (o.to) { const T = o.to(b), e = E.in(clamp((b - (c.b1 - .4)) / .4)); x = lerp(x, T.x, e); y = lerp(y, T.y, e); s *= lerp(1, .15, e); a *= 1 - e; }
      else { const pout = E.in(clamp((b - (c.b1 - .4)) / .4)); y += 40 * pout; a *= 1 - pout; }
      c.el.style.transformOrigin = '50% 50%';
      c.el.style.transform = 'translate(' + (x - o.w / 2).toFixed(1) + 'px,' + (y - 44).toFixed(1) + 'px) scale(' + s.toFixed(4) + ')';
      c.el.style.opacity = a.toFixed(3);
    } else {
      const pin = E.out(clamp((b - c.b0) / .4)), pout = E.in(clamp((b - (c.b1 - .4)) / .4));
      c.el.style.transform = 'translate(' + (o.x - o.w / 2).toFixed(1) + 'px,' + (o.y - 44 + 40 * (1 - pin) + 40 * pout).toFixed(1) + 'px)';
      c.el.style.opacity = (pin * (1 - pout)).toFixed(3);
    }
    const ty = c.types.filter((x) => x.b <= b).pop(), sd = c.sends.filter((x) => x.b <= b).pop();
    const tx = c.el.querySelector('.tx'), cleared = !ty || (sd && sd.b >= ty.b);
    const n = cleared ? 0 : Math.floor([...ty.text].length * clamp((b - ty.b) / Math.max(.01, ty.dur)) + 1e-6);
    const s = cleared ? '' : [...ty.text].slice(0, n).join(''), blink = Math.floor(t * 2.4) % 2 === 0;
    const key = (cleared ? 'P' : 'T' + s) + (blink ? 1 : 0);
    if (tx._k !== key) {
      tx._k = key; tx.classList.toggle('ph', cleared);
      tx.innerHTML = '';
      if (cleared) tx.textContent = '给 Agent 发消息…';
      else { tx.appendChild(document.createTextNode(s)); const car = document.createElement('span'); car.className = 'car'; car.style.opacity = (n < [...ty.text].length || blink) ? '1' : '0'; tx.appendChild(car); }
    }
    const ps = sd ? clamp((b - sd.b) / .15) : 1, snd = c.el.querySelector('.snd');
    snd.style.transform = 'scale(' + (ps < 1 ? lerp(.9, 1, E.out(ps)) : 1).toFixed(3) + ')';
  }
}

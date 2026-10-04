/* AGD — the one set of five Agent dots that runs through the whole film (STORYBOARD.md「共享 API (a)」「转场关键帧」).
   Every dot is always its Agent's logo badge (agBadge), never a plain dot. All beats are the calling scene's own beats:
   each call is stored + SHIFT of its scene, and every callback / live param below receives that scene's beats (promo.js
   CTX_SH), so AGD.pos / AGD.centroid inside it need no conversion.

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
   AGD.blink(sel, b, o)      v18.6「圆形 + 闪烁」(R2): sel i | [i, …] | 'all'; at b a soft Agent-coloured glow flash (sine,
                             o.v .8, o.glowDur dur + .1) + an r pulse ×o.k (1.1, keep ≤ 1.12) over o.dur (.3) beats, sine, no
                             overshoot; o.stag (0) beats per position in sel. Composes with AGD.pulse / AGD.glow (r multiplies).
   AGD.noStretch(b0, b1, sel) v18.6: no velocity stretch for dot(s) sel ('all') in [b0, b1), whatever shapes they morph
                             through — the clean way to keep a beat range tail-free (10-intro / 15-redesign: noStretch(0, end)).
                             Per dot from b on: AGD.morph(b, sel, 'dot', { vs: 0, dur: .01 }) also works, but a later morph back
                             to plain 'dot' restores vs 1. v18.7 D3: AGD.STRETCH is false film-wide, so this is a no-op now.
   AGD.chat(b0, b1, { x, y, w, from, to }) → c   app-style input box (88 px high, centre x, y), rises 40 px + fades in
                             .4 beats from b0, sinks out over the last .4 beats. from: (b) => { x, y } (e.g. AGD.centroid):
                             instead grows out of that point (scale .15 → 1, E.out .6 beats, a 1 by .25 beats); to: (b) =>
                             { x, y }: shrinks back into that point over the last .4 beats (E.in). c.type(b, text, dur): types it evenly over dur beats.
                             c.send(b, i, o): button press at b, box clears, the text pops from dot i as
                             AGD.bubble(i, b + .15, o.until ?? b + 2, text, o); v18.7 R2: no light trail — dot i blinks
                             at b + .15 (k 1.08, .35 beat) unless o.blink === false or the scene blinks it within .25 beat.
                             c.type(b, text, dur, { i, caret }) tints the box's caret with Agent i's colour while that line
                             shows; caret: false hides the box caret for that line.
   AGD.caretRide(i, b0, b1, c, o)  v18.7: dot i is c's typing caret in [b0, b1): each frame it sits on the box caret's
                             position (badge left edge on it: o.dx = r), round, radius o.r (20), no stretch, blending in /
                             out over o.blend (.25) beats; the box caret is hidden meanwhile. Keep the window inside a typed
                             line (no caret in a cleared box → the dot stays on its formation).
   AGD.open(b, dur = .45, o) / AGD.seal(b, dur = .45, o)  v18.7 D2: the merged badge opens into five dots / closes from
                             them by its own arcs. open: cc's badge stays the centre badge (k eases from the merged ~1.1 to 1,
                             logo always visible) and its own (orange) arc shortens + fades on its rim; each other Agent's
                             72° arc slides along cc's rim toward its dot, leaves the rim straight out and shortens to a
                             point while that Agent's round logo badge grows out of it (r ×.3 → 1, alpha 0 until it has left
                             the rim) — never five badges inside a ring. seal: the exact reverse (badges fly in and turn into
                             their arcs around cc's badge). The arcs follow cc's LIVE position. Inside the window no dot draws
                             its own arcs; the scene's morph keys decide dot 0 outside it (open: off 'orb' by b + dur; seal:
                             'orb' or a merge from b + dur).
   Render rule: while any dot shows the merge arcs, every higher-index dot whose centre comes within (arc radius + its own
                             radius) fades by distance, gone at the rim — no merge shows five badges inside the ring.
   AGD.beatPulse(b, K, len)  0..1 sine bump of len beats (.16) after each beat in K (e.g. typeOn's character beats).

   v17.7 morph — the dots' SHAPES (STORYBOARD「v17.7 Agent 点形态与动画」F1 / F2). Position stays with key / follow / pulse;
   a morph only changes how dot i is drawn. With no AGD.morph call anywhere the film draws exactly as v17.6 (plain agBadge,
   no stretch, old merge arcs).
   AGD.morph(b, sel, shape, o)  sel: i | [i, …] | 'all'; shape: a name below or a { params } object (over 'dot'). From
                             b (+ o.stag .04 per position in sel) each dot blends over o.dur (.5) beats with o.ease (E.inOut)
                             from its LIVE current shape (a newer morph never restarts from 'dot') to the new one. o.hold:
                             at b + dur + hold go back to o.to ('dot') over o.back (?? dur). Any param below in o overrides
                             the named shape, and may be live: (b, i) => value (scene beats, like key params).
   AGD.shape(i, b)           the resolved params of dot i at b (numbers; rot / tipDir / tailDir in degrees) + sx / sdir
                             (velocity stretch) — read at hand-overs, beats like AGD.pos.
   params (lengths in units of the badge radius r; one outline = 64 samples of a rounded rect w × h, corner rad, with a
     soft tip (×(1 + .6·tip·cos¹⁰) toward tipDir) and a bubble tail (+tail·cos²⁴ toward tailDir), Catmull-Rom closed):
     w h rad tip tipDir tail tailDir · rot (deg, screen, clockwise; or 'vel' travel direction | 'tan' formation tangent |
     'rad' away from the formation centre | 'in' toward it | [x, y] toward a point | (b, i) => deg or [x, y]); o.aim =
     [x, y] | (b, i) => [x, y] is rot toward a point · tipDir / tailDir: a number is local (turns with rot), a direction
     spec as for rot is a screen direction · fill (0..1 badge black → Agent colour) · ring (stroke × 1.1 px) · warm (0..1
     stroke → #f3a35c) · ls la (logo scale / opacity; the logo is always upright) · lx ly (logo offset, turns with rot) ·
     k (overall scale) · hpx (px: sets h = hpx / r, caret height) · rays (5 Agent-coloured rays, .7 r, 20°/beat) + rayDir
     (screen deg) / rayGain (the ray nearest rayDir × (1 + rayGain)) · micro (5 mini Agent badges r .3 on a .5 circle round the logo point,
     6°/beat; legacy) · arcs (5 Agent-coloured 72° arcs at R + arcR px (7), arcW px wide (1.5)) · core (0..1 faint white inner
     light) · halo (0..1 soft blurred five-colour glow along the arcs) · glow (Agent glow) · tick (0..1 drawn ✓ right of the
     dot, 1.3 r) + tickW (2 px) · stem (px: a thin line on from the tip) · vs (velocity-stretch weight).
   shapes: dot · caret (w .42 h 3 rad .21 fill 1, no logo) · pill (w 2.9, logo in the tail-end cap; aim it) · tail (w 2.2,
     tail .7 up — tailDir 90 for down) · bead (w 2.5 h 1.8, rot 'tan') · petal (long axis local x, tip toward rot 'in',
     fill .3) · bullet (rad .62 ring 1.4; add tick: 1) · pin (h 2.9, tip up, + stem) · pointer (pin, rot −28) · spark
     (rays 1 glow .6) · head (w 3.4 h 1.6, tail-end tip, rot 'vel', glow .5) · orb — v18.7 D2 the v17.6 merge: dot 0's own
     agBadge (cc logo fully visible) × k 1.1 (≤ 1.18; k may be live for a breath) + five Agent-coloured 72° arcs at R + 7,
     1.5 px; micro / core / halo / la / ring / arcR / arcW / fill are LOCKED for 'orb' (older v18.6 disc params are ignored).
     Any round shape (only k / arcs / glow differ from 'dot') is drawn with the real agBadge.
   D3 (v18.7): tail · pill · pin · pointer · head · spark · petal · bullet are tail-like — still drawn, but AGD.morph to any
     of them logs console.warn('AGD.morph D3: …') at registration (visible in render.mjs's log). Legal: dot · caret · bead · orb.
   Automatic (only once any morph is registered): velocity stretch is OFF (AGD.STRETCH = false, D3; when true, dot-like
     shapes (vs) stretch along their travel by 1 + min(.18, v/4000)); a 'dot' inside a merge becomes the orb as the merge
     closes (dots 1–4 hide under dot 0, which draws the arcs); with a tail showing, AGD.bubble (no o.dy) anchors at the
     tail tip and a chat send's light trail ends there.
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
#agdBack,#agd,#agdTop{position:absolute;inset:0;width:1920px;height:1080px;pointer-events:none;overflow:visible}
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
  if (!$('#agdTop')) mk('agdTop', fxEl);                    // v18.7: over the input boxes — a dot riding a box caret
})();
const AGD_KEYS = [], AGD_FOL = [], AGD_PUL = [], AGD_LINKS = [], AGD_BUB = [], AGD_GLOW = [], AGD_CHATS = [], AGD_BACK = [], AGD_BLINK = [], AGD_NOST = [];
let AGD_SORTED = false;
const agWrap = (d) => ((d % 360) + 540) % 360 - 180;       // to (−180, 180]
const agDeg = Math.PI / 180;
// v17.3 SHIFT: every beat is stored + SH of the registering scene (sh); its callbacks get that scene's own beats (agCall)
const agCall = (sh, fn, b, ...a) => inCtx(sh, () => fn(b - sh, ...a));
AGD.key = (b, form, o = {}) => { AGD_KEYS.push({ b: b + SH, sh: SH, form, o }); AGD_SORTED = false; };
AGD.follow = (b0, b1, fn, o = {}) => AGD_FOL.push({ b0: b0 + SH, b1: b1 + SH, sh: SH, fn, blend: o.blend ?? .6 });
AGD.pulse = (i, b, k, dur = .4) => AGD_PUL.push({ i, b: b + SH, k, dur });
AGD.link = (b0, b1, i, to, o = {}) => AGD_LINKS.push({ b0: b0 + SH, b1: b1 + SH, sh: SH, i, to, o, id: AGD_LINKS.length });
AGD.bubble = (i, b0, b1, text, o = {}) => AGD_BUB.push({ i, b0: b0 + SH, b1: b1 + SH, sh: SH, text, o, el: null });
AGD.glow = (i, b0, b1, v = 1) => AGD_GLOW.push({ i, b0: b0 + SH, b1: b1 + SH, v });
// v18.6 R2「圆形 + 闪烁」: a short soft Agent-coloured glow flash + a slight sine r pulse (no overshoot) on dot(s) sel at b
AGD.blink = (sel, b, o = {}) => {
  const L = sel === 'all' ? [0, 1, 2, 3, 4] : Array.isArray(sel) ? sel : [sel], dur = o.dur ?? .3;
  L.forEach((i, n) => { const bb = b + (o.stag ?? 0) * n; AGD.pulse(i, bb, o.k ?? 1.1, dur); AGD_BLINK.push({ i, b: bb + SH, dur: o.glowDur ?? dur + .1, v: o.v ?? .8 }); });
};
// v18.6: no velocity stretch for dot(s) sel in [b0, b1) (scene beats), whatever shapes they morph through
AGD.noStretch = (b0, b1, sel = 'all') => AGD_NOST.push({ b0: b0 + SH, b1: b1 + SH, L: sel === 'all' ? [0, 1, 2, 3, 4] : Array.isArray(sel) ? sel : [sel] });
// a scene's own drawing under the mark and the dots: fn(b) → SVG string, drawn into #agdBack in [b0, b1)
AGD.back = (b0, b1, fn) => AGD_BACK.push({ b0: b0 + SH, b1: b1 + SH, sh: SH, fn });
// v18.7 R1: the one circle opens / closes by its own rim (header「v18.7 open / seal」); o.ease (E.inOut)
const AGD_SHELL = [], AGD_RIDES = [];
AGD.open = (b, dur = .45, o = {}) => AGD_SHELL.push({ b0: b + SH, b1: b + dur + SH, open: true, ease: o.ease || E.inOut, sh: SH });
AGD.seal = (b, dur = .45, o = {}) => AGD_SHELL.push({ b0: b + SH, b1: b + dur + SH, open: false, ease: o.ease || E.inOut, sh: SH });

// one formation, evaluated live at beat b → { x, y, r, a, back, el } (el: ellipse descriptor for polar blends, orbit only)
// a formation parameter, live: o[k] may be a number or (b, i) => number
const agV = (o, k, d, b, i, sh = 0) => { const x = o[k]; return typeof x === 'function' ? agCall(sh, x, b, i) : x ?? d; };
function agForm(n, i, b) {
  const K = AGD_KEYS[n], o = K.o, f = K.form, db = b - K.b, v = (k, d) => agV(o, k, d, b, i, K.sh);
  switch (f) {
    case 'pts': {
      const h = hash01(i, 5), dr = v('drift', 12), px = 9 + 5 * hash01(i, 6), py = 9 + 5 * hash01(i, 7), q = typeof o.pts === 'function' ? agCall(K.sh, o.pts, b, i) : o.pts[i];
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
  agSort(); b += CTX_SH + SH;                               // b in the calling scene's beats (registration: SH, callbacks: CTX_SH)
  const c0 = CTX_SH, s0 = SH; CTX_SH = 0; SH = 0;
  try { return agPosF(i, b); } finally { CTX_SH = c0; SH = s0; }
};
function agPosF(i, b) {
  let n = -1; for (let k = 0; k < AGD_KEYS.length; k++) if (AGD_KEYS[k].b <= b) n = k;
  let q = n < 0 ? { x: 960, y: 540, r: 0, a: 0 } : Object.assign({}, agPos(n, i, b));
  for (const f of AGD_FOL) {
    if (b < f.b0 || b >= f.b1) continue;
    const w = Math.min(E.inOut(clamp((b - f.b0) / f.blend)), E.inOut(clamp((f.b1 - b) / f.blend))), v = agCall(f.sh, (bb) => f.fn(i, bb, q), b);
    if (!v) continue;
    for (const k of ['x', 'y', 'r', 'a']) if (v[k] != null) q[k] = lerp(q[k], v[k], w);
  }
  for (const u of AGD_PUL) if (u.i === i && b >= u.b && b < u.b + u.dur) q.r *= 1 + (u.k - 1) * Math.sin(Math.PI * (b - u.b) / u.dur);
  return q;
}
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

/* ---------- v17.7 morph (header「v17.7 morph」) ---------- */
const AG_DOT = { w: 2, h: 2, rad: 1, tip: 0, tipDir: 0, tail: 0, tailDir: -90, rot: 0, fill: 0, ring: 1, warm: 0, ls: 1, la: 1, lx: 0, ly: 0,
  k: 1, rays: 0, rayDir: 0, rayGain: 0, micro: 0, arcs: 0, arcR: 7, arcW: 1.5, core: 0, halo: 0, glow: 0, tick: 0, tickW: 2, stem: 0, vs: 1 };
const AG_SHAPES = {
  dot: {},
  caret: { w: .42, h: 3, rad: .21, fill: 1, ls: 0, la: 0, vs: 0 },
  pill: { w: 2.9, lx: -.45, vs: 0 },
  tail: { w: 2.2, tail: .7, tailDir: -90, ls: .9, vs: 0 },
  bead: { w: 2.5, h: 1.8, rad: .9, rot: 'tan', ls: .82 },
  petal: { w: 2.7, h: 1.9, rad: .95, tip: .8, tipDir: 0, rot: 'in', fill: .3, ls: .75, lx: -.25, vs: 0 },
  bullet: { rad: .62, ring: 1.4, vs: 0 },
  pin: { h: 2.9, tip: 1, tipDir: -90, ly: .45, vs: 0 },
  pointer: { h: 2.5, tip: .9, tipDir: -90, rot: -28, ly: .4, vs: 0 },
  spark: { rays: 1, glow: .6, ls: .9, vs: 0 },
  head: { w: 3.4, h: 1.6, rad: .8, tip: .9, tipDir: 180, rot: 'vel', glow: .5, ls: .7, lx: .5, vs: 0 },
  // v18.7 D2: merged = ONE 17-series badge — dot 0's own logo badge (agLogo, cc fully visible) ringed by the five
  // Agent-coloured 72° arcs at r + 7, 1.5 px (the v17.6 merge); no blank disc, no core / halo, no micro badges
  orb: { k: 1.1, micro: 0, arcs: 1, arcR: 7, arcW: 1.5, core: 0, halo: 0, ring: 1, la: 1, vs: 0 }
};
// D2: these are fixed for 'orb' whatever a scene passes (older scenes still send the v18.6 disc params)
const AG_ORB_LOCK = { micro: 0, arcR: 7, arcW: 1.5, core: 0, halo: 0, ring: 1, la: 1, ls: 1, fill: 0, warm: 0, rays: 0 };
// D3: shapes with a tail-like outline — still drawn (so a leftover call is visible), but every call warns in the render log
const AG_BANNED = new Set(['tail', 'pill', 'pin', 'pointer', 'head', 'spark', 'petal', 'bullet']);
AGD.SHAPES = AG_SHAPES;
AGD.STRETCH = false;                                         // D3: no velocity stretch anywhere (set true only to compare)
const AGD_MORPH = [], AGM_KEYS = new Set([...Object.keys(AG_DOT), 'aim', 'hpx']), AGM_DIR = new Set(['rot', 'tipDir', 'tailDir', 'aim']);
let AGM_BY = null;
const agOn = () => AGD_MORPH.length > 0;
AGD.morph = (b, sel, shape, o = {}) => {
  const L = sel === 'all' ? [0, 1, 2, 3, 4] : Array.isArray(sel) ? sel : [sel];
  const name = typeof shape === 'string' ? shape : 'dot', over = {};
  if (!AG_SHAPES[name]) console.warn('AGD.morph: unknown shape ' + name);
  if (AG_BANNED.has(name)) console.warn('AGD.morph D3: tail-like shape \'' + name + '\' at scene beat ' + (+b.toFixed(2)) + ' (dot ' + JSON.stringify(sel) + ') — use dot / caret / bead / orb + AGD.blink');
  if (typeof shape === 'object') for (const k in shape) if (AGM_KEYS.has(k)) over[k] = shape[k];
  for (const k in o) if (AGM_KEYS.has(k)) over[k] = o[k];
  const dur = o.dur ?? .5, st = o.stag ?? .04, ease = o.ease || E.inOut;
  L.forEach((i, n) => {
    const b0 = b + SH + st * n;
    AGD_MORPH.push({ i, b: b0, sh: SH, name, over, dur, ease });
    if (o.hold != null) AGD_MORPH.push({ i, b: b0 + dur + o.hold, sh: SH, name: o.to || 'dot', over: {}, dur: o.back ?? dur, ease });
  });
  AGM_BY = null;
};
AGD.beatPulse = (b, K, len = .16) => { let v = 0; for (const k of K) { const u = (b - k) / len; if (u >= 0 && u < 1) v = Math.max(v, Math.sin(Math.PI * u)); } return v; };
function agmBy() {
  if (!AGM_BY) { AGM_BY = [[], [], [], [], []]; AGD_MORPH.slice().sort((p, q) => p.b - q.b).forEach((m) => AGM_BY[m.i] && AGM_BY[m.i].push(m)); }
  return AGM_BY;
}
// frame cache F: { vel: [], cen, P } — velocity per dot, formation centre (absolute beats throughout)
function agFV(c) {
  const F = c.F;
  if (!F.vel[c.i]) {
    // speed from the last .05 beat only; the direction falls back to longer look-backs while the dot rests (a 'head'
    // keeps pointing where it last went). Look-backs to before the dot was visible do not count.
    F.vel[c.i] = { ang: 0, sp: 0 };
    for (const d of [.05, .2, .6]) {
      const q = agPosF(c.i, c.b - d), dx = c.p.x - q.x, dy = c.p.y - q.y;
      if (q.a <= .002) break;
      if (dx * dx + dy * dy > 2.25) { F.vel[c.i] = { ang: Math.atan2(dy, dx) / agDeg, sp: d === .05 ? Math.hypot(dx, dy) / d : 0 }; break; }
    }
  }
  return F.vel[c.i];
}
function agKeyAt(b) { let n = -1; for (let k = 0; k < AGD_KEYS.length; k++) if (AGD_KEYS[k].b <= b) n = k; return n < 0 ? null : AGD_KEYS[n]; }
function agFC(c) {
  const K = agKeyAt(c.b);
  if (K && (K.form === 'ring' || K.form === 'orbit')) return { x: agV(K.o, 'cx', 960, c.b, c.i, K.sh), y: agV(K.o, 'cy', 540, c.b, c.i, K.sh) };
  if (!c.F.cen) {
    const P = (c.F.P || [0, 1, 2, 3, 4].map((j) => agPosF(j, c.b))).filter((p) => p.a > .02);
    c.F.cen = P.length ? { x: P.reduce((s, p) => s + p.x, 0) / P.length, y: P.reduce((s, p) => s + p.y, 0) / P.length } : { x: 960, y: 540 };
  }
  return c.F.cen;
}
// formation tangent (screen deg) of dot i: analytic on ring / orbit / arc / row / column once the key has landed,
// blended from the travel direction while it blends in; mod 180 (beads are symmetric)
function agTan(c) {
  const v = agFV(c), K = agKeyAt(c.b);
  if (!K) return v.ang;
  const o = K.o, i = c.i, V = (k, d) => agV(o, k, d, c.b, i, K.sh), db = c.b - K.b;
  let t = null;
  if (K.form === 'ring') t = V('ph', 0) + 72 * i + V('spin', 0) * db;
  else if (K.form === 'orbit') { const th = (V('ph', 0) + 72 * i + V('spin', 0) * db) * agDeg; t = Math.atan2(V('ry', 0) * Math.sin(th), V('rx', 0) * Math.cos(th)) / agDeg; }
  else if (K.form === 'arc') { const kk = (Array.isArray(o.order) ? o.order[i] : i) - 2; t = Math.atan2(V('sag', 0) * kk / 2, V('gap', 108)) / agDeg; }
  else if (K.form === 'row') t = 0;
  else if (K.form === 'column') t = 90;
  if (t == null) return v.ang;
  const e = E.inOut(clamp((c.b - K.b - (o.stag ?? .08) * i) / Math.max(1e-3, o.dur ?? 1.2)));
  if (e >= 1 || v.sp < 1) return t;
  let d = agWrap(t - v.ang); if (d > 90) d -= 180; else if (d < -90) d += 180;
  return v.ang + d * e;
}
function agDir(s, c, sh) {
  if (typeof s === 'number') return s;
  if (typeof s === 'function') s = agCall(sh, s, c.b, c.i);
  if (typeof s === 'number') return s;
  if (Array.isArray(s)) return Math.atan2(s[1] - c.p.y, s[0] - c.p.x) / agDeg;
  if (s === 'vel') return agFV(c).ang;
  if (s === 'tan') return agTan(c);
  if (s === 'rad' || s === 'in') { const C = agFC(c), a = Math.atan2(c.p.y - C.y, c.p.x - C.x) / agDeg; return s === 'in' ? a + 180 : a; }
  return 0;
}
function agResolve(name, over, sh, c) {
  const S = Object.assign({}, AG_DOT, AG_SHAPES[name] || {}, over);
  if (S.aim != null) S.rot = S.aim;
  for (const k in S) if (typeof S[k] === 'function' && !AGM_DIR.has(k)) S[k] = agCall(sh, S[k], c.b, c.i);
  S.rot = agDir(S.rot, c, sh);
  for (const k of ['tipDir', 'tailDir']) if (typeof S[k] !== 'number') S[k] = agDir(S[k], c, sh) - S.rot;
  if (S.hpx > 0) S.h = S.hpx / Math.max(1, c.r);
  delete S.aim; delete S.hpx;
  if (name === 'orb') { Object.assign(S, AG_ORB_LOCK); S.k = Math.min(S.k, 1.18); }
  return name === 'dot' && c.merged > .001 ? agMixS(S, agResolve('orb', {}, sh, c), c.merged) : S;
}
const agIso = (s) => Math.abs(s.w - s.h) < .02 && s.tip < .01 && s.tail < .01 && Math.abs(s.lx) < .01 && Math.abs(s.ly) < .01;
function agMixS(A, B, e) {
  if (e <= 0) return A; if (e >= 1) return B;
  const S = {};
  for (const k in AG_DOT) S[k] = lerp(A[k], B[k], e);
  // a round shape has no direction: it takes the other end's, so a dot grows into a pill along its aim without spinning
  let ra = A.rot, rb = B.rot; if (agIso(A)) ra = rb; else if (agIso(B)) rb = ra;
  S.rot = ra + agWrap(rb - ra) * e;
  for (const [d, w] of [['tipDir', 'tip'], ['tailDir', 'tail']]) {
    let ta = ra + A[d], tb = rb + B[d]; if (A[w] < .01) ta = tb; else if (B[w] < .01) tb = ta;
    S[d] = ta + agWrap(tb - ta) * e - S.rot;
  }
  S.rayDir = A.rayDir + agWrap(B.rayDir - A.rayDir) * e;
  return S;
}
// shape of dot i at absolute beat b, position p
function agShapeF(i, b, p, F) {
  const L = agmBy()[i], c = { i, b, p, r: p.r, merged: agOn() ? p.merged || 0 : 0, F };
  let n = -1; for (let k = 0; k < L.length; k++) { if (L[k].b <= b) n = k; else break; }
  const at = (n) => {
    if (n < 0) return agResolve('dot', {}, 0, c);
    const M = L[n], T = agResolve(M.name, M.over, M.sh, c), u = clamp((b - M.b) / Math.max(1e-3, M.dur));
    return u >= 1 ? T : agMixS(at(n - 1), T, M.ease(u));
  };
  const S = at(n); S.sx = 1; S.sdir = 0;
  // v18.8 D3: a squashed badge ('bead', or any blend toward it) stays ≤ 1.3 : 1 — ry ≥ .77 r, rx ≤ 1.3 r and w / h ≤ 1.3,
  // whatever w / h a scene passes (20-orbit's w 2.85 / perspective h 1.17 read as a sideways pill). Upright shapes (caret) are untouched.
  if (S.w > S.h + 1e-3 && S.h < 2) { S.h = Math.max(S.h, 1.54); S.w = Math.min(S.w, 2.6, 1.3 * S.h); }
  if (agOn() && AGD.STRETCH && S.vs > .001 && p.r > .3 && !AGD_NOST.some((z) => b >= z.b0 && b < z.b1 && z.L.includes(i))) {
    const v = agFV(c); S.sx = 1 + Math.min(.18, v.sp / 4000) * E.sine(clamp((v.sp - 300) / 300)) * Math.min(1, S.vs); S.sdir = v.ang;
  }
  return S;
}
AGD.shape = (i, b) => {
  agSort(); b += CTX_SH + SH;
  const c0 = CTX_SH, s0 = SH; CTX_SH = 0; SH = 0;
  try { return agShapeF(i, b, agPosF(i, b), { vel: [] }); } finally { CTX_SH = c0; SH = s0; }
};
// radial distance (units r) of a rounded rect (half extents a, bb, corner c) along local angle phi
function agRR(phi, a, bb, c) {
  const dx = Math.abs(Math.cos(phi)), dy = Math.abs(Math.sin(phi)), ka = a - c, kb = bb - c;
  if (dx > 1e-9) { const t = a / dx; if (dy * t <= kb + 1e-9) return t; }
  if (dy > 1e-9) { const t = bb / dy; if (dx * t <= ka + 1e-9) return t; }
  const dk = dx * ka + dy * kb; return dk + Math.sqrt(Math.max(0, dk * dk - ka * ka - kb * kb + c * c));
}
function agRho(S, phi) {
  const a = Math.max(.01, S.w / 2), bb = Math.max(.01, S.h / 2), c = clamp(S.rad, 0, Math.min(a, bb));
  let r = agRR(phi, a, bb, c);
  if (S.tip > 1e-3) r *= 1 + .6 * S.tip * Math.pow(Math.max(0, Math.cos(phi - S.tipDir * agDeg)), 10);
  if (S.tail > 1e-3) r += S.tail * Math.pow(Math.max(0, Math.cos(phi - S.tailDir * agDeg)), 24);
  return r;
}
const AGN_SKIP = new Set(['rot', 'tipDir', 'tailDir', 'rayDir', 'tickW', 'arcR', 'arcW', 'vs']);
const AGR_FREE = new Set([...AGN_SKIP, 'k', 'arcs', 'glow', 'core', 'halo', 'micro']);
function agRound(S) { for (const k in AG_DOT) if (!AGR_FREE.has(k) && Math.abs(S[k] - AG_DOT[k]) > 1e-3) return false; return S.sx < 1.0005 && S.core < .002 && S.halo < .002 && S.micro < .002; }
function agNear(S) { for (const k in AG_DOT) if (!AGN_SKIP.has(k) && Math.abs(S[k] - AG_DOT[k]) > 1e-3) return false; return S.sx < 1.0005; }
// local (units r, before rot) → stage px: rot, then the velocity stretch (screen frame), then scale and translate
function agXf(S, x, y, R) {
  const ro = S.rot * agDeg, cr = Math.cos(ro), sr = Math.sin(ro), sd = S.sdir * agDeg, ux = Math.cos(sd), uy = Math.sin(sd), sx = S.sx;
  return (lx, ly) => {
    let X = lx * cr - ly * sr, Y = lx * sr + ly * cr;
    if (sx !== 1) { const pu = (X * ux + Y * uy) * sx, pn = (-X * uy + Y * ux) / sx; X = pu * ux - pn * uy; Y = pu * uy + pn * ux; }
    return [x + X * R, y + Y * R];
  };
}
function agTailTip(p) {
  const S = p.S; if (!S || S.tail < .02 || p.r <= .3) return null;
  const T = agXf(S, p.x, p.y, p.r * S.k), ph = S.tailDir * agDeg, rho = agRho(S, ph), q = T(rho * Math.cos(ph), rho * Math.sin(ph));
  return { x: q[0], y: q[1], w: clamp(S.tail / .5) };
}
const f1 = (v) => v.toFixed(1);
let AGGLYPH = null;
const agArc = (x, y, rr, a0, a1) => 'M' + f1(x + rr * Math.sin(a0 * agDeg)) + ' ' + f1(y - rr * Math.cos(a0 * agDeg)) + 'A' + f1(rr) + ' ' + f1(rr) + ' 0 0 1 ' + f1(x + rr * Math.sin(a1 * agDeg)) + ' ' + f1(y - rr * Math.cos(a1 * agDeg));
// dot i drawn as shape S at (x, y), badge radius r; b absolute beats, sp merge-arc spin (deg). 'dot' → agBadge, unchanged
function agShape(i, x, y, r, S, b, sp) {
  if (agNear(S)) return agBadge(i, x, y, r);
  // D1 / D2: a round badge (only size, arcs, glow differ from 'dot') is drawn as the real agBadge — the merge is v17.6's
  if (agRound(S)) {
    const R = r * S.k;
    let s = S.glow > .002 ? '<circle cx="' + f1(x) + '" cy="' + f1(y) + '" r="' + f1(R * 2.6) + '" fill="url(#agg' + i + ')" opacity="' + Math.min(1, S.glow).toFixed(3) + '"/>' : '';
    s += agBadge(i, x, y, R);
    if (S.arcs > .002) for (let m = 0; m < 5; m++) s += '<path d="' + agArc(x, y, R + S.arcR, sp + m * 72 + 3, sp + m * 72 + 69) + '" fill="none" stroke="' + AGC[m] + '" stroke-width="' + S.arcW.toFixed(2) + '" stroke-linecap="round" opacity="' + Math.min(1, S.arcs).toFixed(3) + '"/>';
    return s;
  }
  AGGLYPH = AGGLYPH || decks[0].W.eval('agGlyph');
  const R = r * S.k, T = agXf(S, x, y, R);
  let s = '';
  if (S.glow > .002) s += '<circle cx="' + f1(x) + '" cy="' + f1(y) + '" r="' + f1(R * 2.6) + '" fill="url(#agg' + i + ')" opacity="' + Math.min(1, S.glow).toFixed(3) + '"/>';
  if (S.rays > .002) for (let m = 0; m < 5; m++) {
    const a = 20 * b + 72 * m - 90, g = 1 + S.rayGain * Math.pow(Math.max(0, Math.cos((a - S.rayDir) * agDeg)), 8), c = Math.cos(a * agDeg), d = Math.sin(a * agDeg);
    const r0 = R * 1.18, r1 = r0 + .7 * R * Math.min(1, S.rays) * g;
    s += '<line x1="' + f1(x + r0 * c) + '" y1="' + f1(y + r0 * d) + '" x2="' + f1(x + r1 * c) + '" y2="' + f1(y + r1 * d) + '" stroke="' + AGC[m] + '" stroke-width="2.4" stroke-linecap="round" opacity="' + Math.min(1, S.rays).toFixed(3) + '"/>';
  }
  if (S.stem > .5) {
    const ph = S.tipDir * agDeg, rho = agRho(S, ph), q = T(rho * Math.cos(ph), rho * Math.sin(ph)), a = (S.rot + S.tipDir) * agDeg;
    s += '<line x1="' + f1(q[0]) + '" y1="' + f1(q[1]) + '" x2="' + f1(q[0] + S.stem * Math.cos(a)) + '" y2="' + f1(q[1] + S.stem * Math.sin(a)) + '" stroke="#fff" stroke-opacity=".45" stroke-width="1.5" stroke-linecap="round"/>';
  }
  // the outline: 64 samples on the w × h ellipse parameter (even along the rim even for a thin caret), Catmull-Rom closed
  const a = Math.max(.01, S.w / 2), bb = Math.max(.01, S.h / 2), N = 64, Q = [];
  for (let j = 0; j < N; j++) { const t = 2 * Math.PI * j / N, ph = Math.atan2(bb * Math.sin(t), a * Math.cos(t)), rho = agRho(S, ph); Q.push(T(rho * Math.cos(ph), rho * Math.sin(ph))); }
  let d = 'M' + f1(Q[0][0]) + ' ' + f1(Q[0][1]);
  for (let j = 0; j < N; j++) {
    const p0 = Q[(j + N - 1) % N], p1 = Q[j], p2 = Q[(j + 1) % N], p3 = Q[(j + 2) % N];
    d += 'C' + f1(p1[0] + (p2[0] - p0[0]) / 6) + ' ' + f1(p1[1] + (p2[1] - p0[1]) / 6) + ' ' + f1(p2[0] - (p3[0] - p1[0]) / 6) + ' ' + f1(p2[1] - (p3[1] - p1[1]) / 6) + ' ' + f1(p2[0]) + ' ' + f1(p2[1]);
  }
  if (S.halo > .002 && S.arcs > .002) for (let m = 0; m < 5; m++) s += '<path d="' + agArc(x, y, R + S.arcR, sp + m * 72 + 8, sp + m * 72 + 64) + '" fill="none" stroke="' + AGC[m] + '" stroke-width="' + f1(R * .55) + '" stroke-linecap="round" filter="url(#agbl)" opacity="' + (.3 * Math.min(1, S.halo) * Math.min(1, S.arcs)).toFixed(3) + '"/>';
  const fill = S.fill > .002 ? 'color-mix(in oklab, ' + AGC[i] + ' ' + (100 * Math.min(1, S.fill)).toFixed(1) + '%, #0e0f12)' : '#0e0f12';
  const stroke = S.warm > .002 ? 'color-mix(in oklab, ' + AGC[i] + ' ' + (100 * (1 - Math.min(1, S.warm))).toFixed(1) + '%, #f3a35c)' : AGC[i];
  s += '<path d="' + d + 'Z" fill="' + fill + '" stroke="' + stroke + '" stroke-width="' + (1.1 * S.ring).toFixed(2) + '" stroke-opacity="' + Math.min(1, S.ring).toFixed(3) + '" stroke-linejoin="round"/>';
  if (S.core > .002) s += '<circle cx="' + f1(x) + '" cy="' + f1(y) + '" r="' + f1(R) + '" fill="url(#agcore)" opacity="' + (.3 * Math.min(1, S.core)).toFixed(3) + '"/>';
  const ro = S.rot * agDeg, gx = x + (S.lx * Math.cos(ro) - S.ly * Math.sin(ro)) * R, gy = y + (S.lx * Math.sin(ro) + S.ly * Math.cos(ro)) * R;
  const la = S.la;                                          // D2: the logo always shows (the merge is cc's badge)
  if (la * S.ls > .01) {
    const lf = clamp((S.fill - .35) / .4), col = lf > .002 ? 'color-mix(in oklab, ' + AGC[i] + ' ' + (100 * (1 - lf)).toFixed(1) + '%, #0e0f12)' : AGC[i];
    s += '<g opacity="' + Math.min(1, la).toFixed(3) + '">' + AGGLYPH(AGID[i], +gx.toFixed(1), +gy.toFixed(1), 1.3 * R * S.ls, col) + '</g>';
  }
  if (S.micro > .002) {
    let m2 = '';
    for (let m = 0; m < 5; m++) { const a2 = (6 * b + 72 * m - 90) * agDeg; m2 += agBadge(m, gx + .5 * R * Math.cos(a2), gy + .5 * R * Math.sin(a2), .3 * R); }
    s += '<g opacity="' + Math.min(1, S.micro).toFixed(3) + '">' + m2 + '</g>';
  }
  if (S.arcs > .002) for (let m = 0; m < 5; m++) s += '<path d="' + agArc(x, y, R + S.arcR, sp + m * 72 + 3, sp + m * 72 + 69) + '" fill="none" stroke="' + AGC[m] + '" stroke-width="' + S.arcW.toFixed(2) + '" stroke-linecap="round" opacity="' + Math.min(1, S.arcs).toFixed(3) + '"/>';
  if (S.tick > .002) {
    const tx = x + 1.3 * R, w = S.tickW;
    s += '<path d="M' + f1(tx) + ' ' + f1(y + .02 * R) + 'L' + f1(tx + .32 * R) + ' ' + f1(y + .34 * R) + 'L' + f1(tx + .95 * R) + ' ' + f1(y - .4 * R) + '" pathLength="1" fill="none" stroke="' + AGC[i] + '" stroke-width="' + w.toFixed(2) + '" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="' + Math.min(1, S.tick).toFixed(4) + ' 2"/>';
  }
  return s;
}

// cubic from P to T with horizontal tangents; returns point at u
function agCubic(P, T, bend) { const dx = (T[0] - P[0]) * bend; return [P, [P[0] + dx, P[1]], [T[0] - dx, T[1]], T]; }
function agAt(c, u) { const v = 1 - u; return [0, 1].map((k) => v * v * v * c[0][k] + 3 * v * v * u * c[1][k] + 3 * v * u * u * c[2][k] + u * u * u * c[3][k]); }
const agMix = (i) => 'color-mix(in oklab, ' + AGC[i] + ' 50%, #fff)';
let agFrame = -1, agCache = [];
function applyAgents(t) {
  const b = t / BEAT; agSort(); agSendBlinks();
  // v18.7: input boxes first, so AGD.caretRide reads this frame's caret
  agChats(b, t);
  const P = [0, 1, 2, 3, 4].map((i) => agPosF(i, b)); agCache = P; agFrame = b;
  // v17.7: each dot's shape this frame (P[i].S); merge-arc spin as in the old merge drawing
  const mspAt = (bb) => { const K = AGD_KEYS.filter((k) => k.form === 'merge' && k.b <= bb).pop(); return K ? agV(K.o, 'spin', 6, bb, 0, K.sh) * (bb - K.b) : 6 * bb; };
  const msp = mspAt(b);
  const F = { vel: [], P };
  if (agOn()) for (let i = 0; i < 5; i++) P[i].S = agShapeF(i, b, P[i], F);
  // v18.7 R1 open / seal: while the rim opens or closes, no dot is drawn as the orb (the shell below draws it)
  const SHL = AGD_SHELL.filter((z) => b >= z.b0 && b < z.b1).map((z) => agShellAt(z, b, msp, P));
  if (SHL.length) for (let i = 0; i < 5; i++) {
    const p = P[i]; if (!p.S) continue;
    if (p.merged) { p.S = agShapeF(i, b, Object.assign({}, p, { merged: 0 }), F); p.merged = 0; }
    // D2: the shell draws the five arcs; cc stays the centre badge (its size easing from the merged k to 1)
    const S = p.S; if (S.arcs > .002 || !i) Object.assign(S, { arcs: 0, halo: 0, core: 0, micro: 0, k: i ? 1 : SHL[0].k0, ring: Math.max(1, S.ring), la: Math.max(1, S.la) });
  }
  let back = '', front = '', defs = '', top = '';
  for (const g of AGD_BACK) if (b >= g.b0 && b < g.b1) { try { back += agCall(g.sh, g.fn, b) || ''; } catch (e) { console.error('AGD.back', e); g.b1 = -1; } }
  // links
  for (const L of AGD_LINKS) {
    if (b < L.b0 || b >= L.b1) continue;
    const o = L.o, p = P[L.i], T = typeof L.to === 'function' ? agCall(L.sh, L.to, b) : L.to, c = agCubic([p.x, p.y], T, o.bend ?? .4);
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
  // v18.7 R2: no send trail any more — c.send blinks the receiving dot instead (agSendBlinks)
  // glows
  for (const g of AGD_GLOW) {
    if (b < g.b0 - .3 || b >= g.b1 + .3) continue;
    const v = g.v * Math.min(E.inOut(clamp((b - g.b0 + .3) / .3)), E.inOut(clamp((g.b1 + .3 - b) / .3))), p = P[g.i];
    if (v > .002 && p.a > .002) front += '<circle cx="' + p.x.toFixed(1) + '" cy="' + p.y.toFixed(1) + '" r="' + (p.r * 2.6).toFixed(1) + '" fill="url(#agg' + g.i + ')" opacity="' + (v * p.a).toFixed(3) + '"/>';
  }
  for (const g of AGD_BLINK) {
    const u = (b - g.b) / g.dur; if (u < 0 || u >= 1) continue;
    const p = P[g.i], v = g.v * Math.sin(Math.PI * u) * p.a;
    if (v > .002) front += '<circle cx="' + p.x.toFixed(1) + '" cy="' + p.y.toFixed(1) + '" r="' + (p.r * 2.4).toFixed(1) + '" fill="url(#agg' + g.i + ')" opacity="' + Math.min(1, v).toFixed(3) + '"/>';
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
  // v18.7 R1: the opening / closing shell (dark disc, core, halo fade in its first / last 40 %; five rim arcs travel to
  // their dots, shrinking to a point), drawn under the badges
  for (const z of SHL) front += agShellSVG(z, P);
  // v18.7 R1 render rule: while an orb shows, any other dot whose centre comes within (orb radius + its own radius)
  // fades by distance (gone at the rim), so no merge ever shows five dots inside the one circle; a shell gates all five.
  // Only a lower-index orb gates a dot (inside a merge every dot resolves to the orb; dot 0 is the one that shows)
  const ORBS = [];
  for (let j = 0; j < 5; j++) { const p = P[j], S = p.S; if (S && S.arcs > .002 && p.a > .002) ORBS.push({ j, x: p.x, y: p.y, R: p.r * S.k + S.arcR, v: Math.min(1, S.arcs) * Math.min(1, p.a) }); }
  const gate = (i) => {
    const p = P[i], ri = Math.max(1, p.r * (p.S ? p.S.k : 1)); let g = 1;
    for (const o of ORBS) if (o.j < i) g *= 1 - o.v * (1 - clamp((Math.hypot(p.x - o.x, p.y - o.y) - o.R) / ri));
    if (i) for (const z of SHL) g *= z.tg * clamp((Math.hypot(p.x - z.cx, p.y - z.cy) - z.Rr + ri) / ri);
    return g;
  };
  // badges: cc last (on top, for 'merge'); far orbit half into #agdBack
  for (const i of [4, 3, 2, 1, 0]) {
    const p = P[i]; if (p.a <= .002 || p.r <= .3) continue;
    // v17.7: inside a closed merge only dot 0 draws (as the orb, or whatever it was morphed into)
    const a = (p.S && i && p.merged ? p.a * (1 - E.inOut(clamp((p.merged - .6) / .4))) : p.a) * gate(i); if (a <= .002) continue;
    const pr = i ? p.r * SHL.reduce((m, z) => m * z.gs, 1) : p.r;
    const s = '<g opacity="' + Math.min(1, a).toFixed(3) + '">' + (p.S ? agShape(i, p.x, p.y, pr, p.S, b, msp) : agBadge(i, p.x, p.y, pr)) + '</g>';
    if (AGD_RIDES.some((z) => z.i === i && b >= z.b0 && b < z.b1)) top += s; else if (p.back) back += s; else front += s;
  }
  const m = P[0].merged || 0;
  if (m > .01 && !agOn()) {
    const K = mK, sp = K ? msp : 0, p = P[0], rr = p.r + 7;
    for (let i = 0; i < 5; i++) { const a0 = sp + i * 72 + 3, a1 = sp + i * 72 + 69, q0 = [p.x + rr * Math.sin(a0 * agDeg), p.y - rr * Math.cos(a0 * agDeg)], q1 = [p.x + rr * Math.sin(a1 * agDeg), p.y - rr * Math.cos(a1 * agDeg)];
      front += '<path d="M' + q0[0].toFixed(1) + ' ' + q0[1].toFixed(1) + 'A' + rr.toFixed(1) + ' ' + rr.toFixed(1) + ' 0 0 1 ' + q1[0].toFixed(1) + ' ' + q1[1].toFixed(1) + '" fill="none" stroke="' + AGC[i] + '" stroke-width="1.5" opacity="' + (m * Math.min(1, p.a)).toFixed(3) + '"/>'; }
  }
  const gd = AGC.map((c, i) => '<radialGradient id="agg' + i + '"><stop offset="0" style="stop-color:' + c + ';stop-opacity:.55"/><stop offset="1" style="stop-color:' + c + ';stop-opacity:0"/></radialGradient>').join('') +
    '<radialGradient id="agcore"><stop offset="0" stop-color="#fff" stop-opacity=".35"/><stop offset=".55" stop-color="#fff" stop-opacity=".06"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>' +
    '<filter id="agbl" filterUnits="userSpaceOnUse" x="0" y="0" width="1920" height="1080"><feGaussianBlur stdDeviation="5"/></filter>';
  $('#agdBack').innerHTML = back;
  $('#agd').innerHTML = '<defs>' + gd + defs + '</defs>' + front;
  $('#agdTop').innerHTML = top;
  agBubbles(b, P);
}
// v18.7 shell state at absolute beat b (D2): e = 1 − closed (0 = the merged badge, 1 = five dots). The centre is cc's live
// badge (dot 0 stays the centre badge); k0 its size (merged k → 1); tg / gs gate and grow dots 1–4 out of their arcs
function agShellAt(z, b, sp, P) {
  if (!z.at) {
    const ob = z.open ? z.b0 - 1e-3 : z.b1 + 1e-3, p = agPosF(0, ob), S = agOn() ? agShapeF(0, ob, p, { vel: [] }) : Object.assign({}, AG_DOT, AG_SHAPES.orb);
    z.at = { k: S.arcs > .002 ? S.k : AG_SHAPES.orb.k, a: Math.min(1, p.a), far: [0, 1, 2, 3, 4].map((i) => agPosF(i, z.open ? z.b1 : z.b0)) };
  }
  const A = z.at, u = clamp((b - z.b0) / (z.b1 - z.b0)), w = z.open ? u : 1 - u, e = z.ease(w);
  const k0 = lerp(A.k, 1, E.inOut(clamp(e / .7))), R = P[0].r * k0;
  return { z, A, u, w, e, sp, k0, cx: P[0].x, cy: P[0].y, R, Rr: R + AG_SHAPES.orb.arcR, tg: E.inOut(clamp((e - .4) / .5)), gs: lerp(.3, 1, E.out(clamp((e - .4) / .6))) };   // QA r7: dots grow out of the shrinking arcs (no ring-only gap, no full-size pop)
}
function agShellSVG(H, P) {
  const { A, e, sp, cx, cy, Rr } = H, W = AG_SHAPES.orb.arcW;
  let s = '';
  for (let m = 0; m < 5; m++) {
    const t0 = sp + m * 72 + 36;
    if (!m) {
      // cc's own arc stays on cc's rim: it shortens to its midpoint and fades into the centre badge
      const h = 33 * (1 - E.inOut(clamp(e / .7))), aa = (1 - E.inOut(clamp((e - .1) / .6))) * A.a;
      if (h > .3 && aa > .002) s += '<path d="' + agArc(cx, cy, Rr, t0 - h, t0 + h) + '" fill="none" stroke="' + AGC[0] + '" stroke-width="' + W.toFixed(2) + '" stroke-linecap="round" opacity="' + aa.toFixed(3) + '"/>';
      continue;
    }
    // each other arc first slides along cc's rim toward its own dot's direction while the gaps open (no crossing paths),
    // then leaves the rim straight out to its dot, shortening to a point as that Agent's round badge grows out of it
    const far = A.far[m], tf = Math.hypot(far.x - cx, far.y - cy) > 1 ? Math.atan2(far.x - cx, -(far.y - cy)) / agDeg : t0;
    const th = t0 + agWrap(tf - t0) * E.inOut(clamp(e / .45)), h = 33 * (1 - e), tr = th * agDeg, go = E.inOut(clamp((e - .2) / .8)), hl = E.inOut(clamp((e - .6) / .4));
    const M0 = [cx + Rr * Math.sin(tr), cy - Rr * Math.cos(tr)], T = [lerp(far.x, P[m].x, hl), lerp(far.y, P[m].y, hl)];
    const Q = [lerp(M0[0], T[0], go), lerp(M0[1], T[1], go)], O = [Q[0] - Rr * Math.sin(tr), Q[1] + Rr * Math.cos(tr)];
    const aa = (1 - E.inOut(clamp((e - .6) / .3))) * A.a; if (aa <= .002) continue;
    const d = h > .3 ? agArc(O[0], O[1], Rr, th - h, th + h) : 'M' + f1(Q[0] - .1) + ' ' + f1(Q[1]) + 'L' + f1(Q[0] + .1) + ' ' + f1(Q[1]);
    s += '<path d="' + d + '" fill="none" stroke="' + AGC[m] + '" stroke-width="' + lerp(W, W * 1.6, e).toFixed(2) + '" stroke-linecap="round" opacity="' + aa.toFixed(3) + '"/>';
  }
  return s;
}
// v18.7 R2: every c.send blinks the receiving dot as its bubble pops (send + .15), unless the scene already blinks that
// dot within .25 beat of it (no doubled pulse)
const AGD_SBL = [];
let AGD_SBL_DONE = false;
function agSendBlinks() {
  if (AGD_SBL_DONE) return; AGD_SBL_DONE = true;
  for (const s of AGD_SBL) {
    if (AGD_BLINK.some((g) => g.i === s.i && Math.abs(g.b - s.b) < .25)) continue;
    AGD_PUL.push({ i: s.i, b: s.b, k: 1.08, dur: .35 }); AGD_BLINK.push({ i: s.i, b: s.b, dur: .45, v: .8 });
  }
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
  let dx = typeof u.o.dx === 'function' ? agCall(u.sh, u.o.dx, b) : u.o.dx ?? 0, dy0 = typeof u.o.dy === 'function' ? agCall(u.sh, u.o.dy, b) : u.o.dy, dy = dy0 ?? -p.r - 18;
  // v17.7: a dot showing a bubble tail (morph 'tail') hands the bubble its tail tip (+4 px), unless o.dy is given
  const tt = dy0 == null ? agTailTip(p) : null;
  if (tt) { const gx = tt.x - p.x, gy = tt.y - p.y; if (u.o.dx == null) dx = lerp(dx, gx, tt.w); dy = lerp(dy, gy + (gy > 0 ? 4 : -4), tt.w); }
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
  const c = { b0: b0 + SH, b1: b1 + SH, sh: SH, o, types: [], sends: [], el: null };
  c.type = (b, text, dur, to = {}) => { c.types.push({ b: b + SH, text, dur, ci: to.i, caret: to.caret !== false }); return c; };
  c.send = (b, i, so = {}) => {
    const ty = c.types.filter((x) => x.b <= b + SH).pop(); c.sends.push({ b: b + SH, i });
    if (ty) AGD.bubble(i, b + .15, so.until ?? b + 2, ty.text, so);
    if (so.blink !== false) AGD_SBL.push({ i, b: b + .15 + SH });          // v18.7 R2: blink, no light trail
    return c;
  };
  c.rides = [];
  AGD_CHATS.push(c); return c;
};
// v18.7: dot i IS the box's typing caret in [b0, b1) — every frame it sits on c's caret (its left edge on the caret line,
// o.dx = r), a round badge of radius o.r (20), no stretch; the box's own caret is hidden meanwhile. Blends in / out over
// o.blend (.25) beats; outside a typed line (no caret in the box) the dot keeps its formation position
AGD.caretRide = (i, b0, b1, c, o = {}) => {
  const r = o.r ?? 20, dx = o.dx ?? r;
  c.rides.push({ b0: b0 + SH, b1: b1 + SH, i }); AGD_RIDES.push({ b0: b0 + SH, b1: b1 + SH, i });
  AGD.follow(b0, b1, (j) => {
    if (j !== i || !c.el) return null;
    const car = c.el.querySelector('.car'); if (!car) return null;
    const q = car.getBoundingClientRect(), st = stage.getBoundingClientRect(), z = st.width / 1920;
    return { x: (q.left + q.width / 2 - st.left) / z + dx, y: (q.top + q.height / 2 - st.top) / z, r };
  }, { blend: o.blend ?? .25 });
  AGD.noStretch(b0, b1, i);
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
      if (o.from) { const f = agCall(c.sh, o.from, b), e = E.out(clamp((b - c.b0) / .6)); x = lerp(f.x, x, e); y = lerp(f.y, y, e); s = lerp(.15, 1, e); a = clamp((b - c.b0) / .25); }
      else { const pin = E.out(clamp((b - c.b0) / .4)); y += 40 * (1 - pin); a = pin; }
      if (o.to) { const T = agCall(c.sh, o.to, b), e = E.in(clamp((b - (c.b1 - .4)) / .4)); x = lerp(x, T.x, e); y = lerp(y, T.y, e); s *= lerp(1, .15, e); a *= 1 - e; }
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
    const tx = c.el.querySelector('.tx'), cleared = !ty || !!(sd && sd.b >= ty.b);
    const n = cleared ? 0 : Math.floor([...ty.text].length * clamp((b - ty.b) / Math.max(.01, ty.dur)) + 1e-6);
    const s = cleared ? '' : [...ty.text].slice(0, n).join(''), blink = Math.floor(t * 2.4) % 2 === 0;
    const ride = c.rides.some((z) => b >= z.b0 && b < z.b1), hide = ride || (ty && !ty.caret);
    const key = (cleared ? 'P' : 'T' + s) + (blink ? 1 : 0) + (hide ? 'h' : '');
    if (tx._k !== key) {
      tx._k = key; tx.classList.toggle('ph', cleared);
      tx.innerHTML = '';
      if (cleared) tx.textContent = '给 Agent 发消息…';
      else { tx.appendChild(document.createTextNode(s)); const car = document.createElement('span'); car.className = 'car'; if (ty.ci != null) car.style.background = AGC[ty.ci]; car.style.opacity = !hide && (n < [...ty.text].length || blink) ? '1' : '0'; tx.appendChild(car); }
    }
    const ps = sd ? clamp((b - sd.b) / .15) : 1, snd = c.el.querySelector('.snd');
    snd.style.transform = 'scale(' + (ps < 1 ? lerp(.9, 1, E.out(ps)) : 1).toFixed(3) + ')';
  }
}

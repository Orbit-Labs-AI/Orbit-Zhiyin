/* 10-intro 1a–1c（b0–14.8 for the dots, b15.75 for the type and icons） — STORYBOARD.md v17.2 (copy + entrances), v17.1「V1」
   「V2 T0–T3′」「V4」, v17「1a」「1b」「1c」.
   The opening is one causal chain (v17.2): 用 AI Agent，正在成为每个人的日常 → 从想法到交付 (the picture of it) → We Are
   Redesigning Everything / 人们正在用 Agent 重新设计一切 → (15-redesign) 但，交互本身也需要被重新定义 → So … Assistant.
   Pacing (v17 pace pass): every change is slow enough to follow — words wipe in over .45 beat, typing runs ≈ 4
   characters a beat (v17.7, one key at a time), bubbles rise out of their dot over .6 beat, icons fly 1 beat — and
   nothing freezes: the type keeps a slow push, bubbles float, the dots drift / breathe and the halo turns.
   Readability (v17.3, +3 beats: 1.2 at b3.3, .8 at b8.9, 1.0 at b13.0 — the old b11.8 hand-off became b14.8).
   v17.4, +3.9 more: the beats in the code and in the comments below stay on the v17.3 grid and go through T() — +1.8 at
   b4.4 (1a's read), +.6 at b6.4 (1b, before the first send), +.6 at b9.8 (1b, the icons spin on the halo while the last
   bubbles are read), +.9 at b13.0 (1c's read); the hand-off is T(14.8) = b18.7 (15-redesign's b11.8 under SHIFT +6.9),
   the scene ends b19.65. The few beats inside an inserted span are written on the new grid (marked). Every line stays
   whole ≥ max(2, 1.2 + .18 / CJK char + .09 / Latin char) beats, a shot's big headline × 1.3: 「正在成为每个人的日常」
   3.94 (b2.66–6.6), 「用 AI Agent，」 5.1, 「从想法到交付」 ≈ 3.6, every bubble 2.0–2.6, 「We Are Redesigning」 3.45
   (b15.25–18.7), 「Everything」 2.9, the gloss 3.65 (b15.6–19.25).
   v17.5 word-by-word rhythm (length unchanged): every word / phrase opens fast (.24 beat) and lands with a small settle
   (1.07× → 1, blur 6 → 0 by +.4), then sits still until the next one, about half a beat apart: 「用」 b0.4 · 「AI Agent，」
   0.72 · 「正在」 1.1 · 「成为」 1.5 · 「每个人的」 1.95 · 「日常」 stamp 2.3 (hit 2.6) · 「从想法」 T(5.2) · 「到交付」 +.35 · We / Are /
   Redesigning / Everything on CB0 + 0 / .5 / 1.0 / 1.5; the pen and the caret step on in the gap after each landing.
   The five dots are one tight group the eye follows, and the content comes out of it:
   1a 用 AI Agent，/ 正在成为每个人的日常（b0–5.4）：a cluster (R 60) pops in the middle of the black and 「用 AI Agent，」
      floats up out of it; from b0.8 the dots are a ∪ pen under the headline, gliding under each word just before it wipes
      in; 「日常」 (orange) comes last and settles like a stamp (b2.36, lands on b2.66); the pen drifts back to the centre
      (b3.2–4.4) and rises with the line's exit (b4.8–5.4).
   1b 从想法到交付（b5.2–10.8）：the pen turns over into the narrow ∩ arc (b4.8); the input box grows out of the dots (b5.2)
      and shrinks back into them (b9.3–9.7); 2 typed sends + each dot's own prompt, one bubble slot per dot in two layers;
      b8.95 (after the last send) 12 App icons spray from the dots and the box along arcs (1 beat) onto the halo (960, 520,
      rx 760, ry 380).
   1c We Are Redesigning Everything（b10.6–15.75）：the arc folds into a caret (b10.2) that leads the type word by word, then
      walks an L to the right of 「Everything」 and rests there; each word draws the 3 nearest icons 40 px in; b12.3 the
      icons slowly turn outward and shrink to .7, b14.7 they fly out along the radius. b12.3 (with 「Everything」) the gloss
      「人们正在用 Agent 重新设计一切」 fades in under it. The b14.8 AGD key (caret → arc; 15-redesign's b11.8, v17.4: film
      b18.7 under SHIFT +6.9) belongs to 15-redesign; this scene writes no key after b10.2.
   The icons are drawn in #agdBack (AGD.back, under the Agent dots), so they burst from behind the dots and the box.
   v17.7 typing (length unchanged): every prompt typed into a box (1b here, 1d in 15-redesign) goes in one character at a
   time at a human pace (typeOn below); 1b types two prompts (记账 App, 路演稿) and 「生成产品官网」 is ds's own bubble.
   v17.7 shapes (AGD.morph, length unchanged): orb b0.2 → split .35–.8 · pen beads b0.8 (lead pill 1.46 / 1.91, stamp
   press 2.45–2.9) · beads → dots 6.6 · box pull-out pills 6.75 · caret on the receiving dot while typing (bobs on typeOn's
   key beats) → tail .2 before each send · own prompts dot → tail .15 before their pop · sparks 11.15 → box-in pills
   11.65 → dots 12.0 · five-colour segmented caret 13.2 (ripples on word landings, 4° lean on each step, fill breathes
   from 15.4) — 15-redesign lays it down at 18.7. */
/* typeOn(c, k0, text, seed) → the scene beats of its characters: the k-th character of text appears in AGD.chat box c
   at K[k] (K[0] = k0, then .22–.28 beat apart, jitter from hash01(k, seed)) — the caret stays solid while it types and
   blinks once the line is whole; ci (optional) = the Agent this prompt is sent to, whose colour the box caret takes. AGD's c.type() types evenly over dur; an every() drive re-times that record each frame
   (a pure function of the beat) so the shown count follows K. Shared with 15-redesign (scene files load in name order). */
function typeOn(c, k0, text, seed, ci) {
  const n = [...text].length, K = [k0], s0 = k0 - .01;
  for (let k = 1; k < n; k++) K.push(K[k - 1] + .22 + .06 * hash01(k, seed));
  // a sentinel send long before the film: AGD toggles the box's placeholder grey with `!ty || (sd && …)`, which is
  // undefined (a bare toggle, flipping grey / white on every key) until the box's first real send
  if (!c.sends.length) c.sends.push({ b: -99, i: 0 });
  c.type(s0, text, K[n - 1] - s0, { i: ci });              // ci: Agent i that will take this prompt tints the box caret (v17.7)
  const rec = c.types[c.types.length - 1];
  // shown = floor(n · (b − s0) / dur): dur = n·e / (m + .5) shows exactly m (< n keeps the caret solid); whole → .001
  every(s0, K[n - 1] + .01, (p, b) => {
    const m = K.filter((v) => v <= b + 1e-6).length, e = b - s0;
    if (m >= n) rec.dur = .001; else if (e > 0) rec.dur = n * e / (m + .5);
  });
  return K;
}
scene('10-intro', () => {
  css(`
.ln.lt.in-s{font-size:46px;color:rgba(255,255,255,.74)}
.ln.in-big{font-size:120px;overflow:visible}
.ln.sv .w.in-hot{background:none;color:var(--a1)}
.ln.lt.in-gloss{font-size:44px;color:rgba(255,255,255,.74)}
.in-t1{font-size:132px}
.in-w1{font-size:120px}
.in-ev{font-size:150px;color:var(--a1)}
`);
  const D2R = Math.PI / 180;
  // v17.4 readability inserts (header): a v17.3-grid beat → this scene's beat
  const T = (b) => b + (b >= 4.4 ? 1.8 : 0) + (b >= 6.4 ? .6 : 0) + (b >= 9.8 ? .6 : 0) + (b >= 13.0 ? .9 : 0);
  // Words wipe in left → right over o.dur beats (.45): each word grows its own width, so a centred line re-centres
  // smoothly instead of jumping, and the glyphs past the growing edge stay clipped. The block keeps a slow push
  // (o.push = scale gained over the text's life) so it never sits frozen; o.fit = max width; it leaves over o.out beats
  // (blur + fade, o.up px upwards, o.spread = letters drift apart). o.stamp = index of a word that lands like a stamp
  // instead: its slot opens over .35 beat (the line re-centres as smoothly as for a wipe) while the glyphs come down
  // unclipped from 1.3× to .97× (E.io, .3 beat — the hit) and settle back to 1 (E.io, .3 beat); opacity and blur only
  // ever go one way, so nothing flashes.
  const STAMP = (u) => (u < .3 ? lerp(1.3, .97, E.inOut(u / .3)) : lerp(.97, 1, E.inOut(clamp((u - .3) / .3))));
  // v17.5 (word-by-word rhythm): a word now opens fast (o.dur, default .24 beat, E.out) and lands with a small settle —
  // the glyphs come in at 1.07× out of a 6 px blur and come to rest at 1 by dur + .16 — then sit still (the block's slow
  // push keeps going) for the rest of its half-beat slot before the next word: each word reads as one step.
  const SET = .16;
  const wipe = (o) => (el, tl, life) => {
    const ws = [...el.querySelectorAll('.w')], dur = o.dur ?? .24;
    if (!el._ww || !el._ww.some((v) => v > 0)) { ws.forEach((w) => { w.style.display = ''; w.style.width = ''; }); el._ww = ws.map((w) => w.offsetWidth); }
    ws.forEach((w, i) => {
      if (i === o.stamp) {
        const u = (tl - BB(o.at[i])) / BEAT, p = E.out(clamp(u / .35)), a = clamp(u / .2);
        w.style.display = u > 0 ? '' : 'none';
        w.style.width = p < 1 ? (el._ww[i] * p).toFixed(1) + 'px' : '';
        w.style.clipPath = '';
        w.style.opacity = E.out(a).toFixed(3);
        w.style.filter = u < .3 ? 'blur(' + ((1 - clamp(u / .3)) * 6).toFixed(1) + 'px)' : 'none';
        w.style.transform = u < .6 ? 'scale(' + STAMP(clamp(u)).toFixed(4) + ')' : '';
        w.style.transformOrigin = '50% 58%';
        return;
      }
      const u = (tl - BB(o.at[i])) / BEAT, p = E.out(clamp(u / dur)), z = E.out(clamp(u / (dur + SET)));
      w.style.display = p > 0 ? '' : 'none';
      w.style.width = p < 1 ? (el._ww[i] * p).toFixed(1) + 'px' : '';
      w.style.clipPath = p < 1 ? 'inset(-40% 0 -40% -20%)' : '';
      w.style.opacity = Math.min(1, p * 1.5).toFixed(3);
      w.style.filter = p < .999 ? 'blur(' + ((1 - p) * 6).toFixed(1) + 'px)' : 'none';
      w.style.transform = z < .999 ? 'scale(' + lerp(1.07, 1, z).toFixed(4) + ')' : '';
      w.style.transformOrigin = '50% 58%';
    });
    const q = E.inOut(clamp((tl - (life - BB(o.out))) / BB(o.out)));
    const sc = (o.fit ? Math.min(1, o.fit / Math.max(1, el.offsetWidth)) : 1) * (1 + (o.push || 0) * tl / life);
    el.style.transform = 'translate(-50%,-50%) translateY(' + (-(o.up || 0) * q).toFixed(1) + 'px) scale(' + sc.toFixed(4) + ')';
    el.style.transformOrigin = '50% 50%';
    leave(el, 1 - q, o.spread);
  };

  // Live word geometry for the pen (1a) and the caret (1c): the layout widths of a line's .w words (offsetWidth, the
  // same numbers wipe() reads), measured off-screen and cached once the fonts are in, so the dots follow the type as it
  // is set — pure functions of the beat, no dependence on the frame order.
  const wordsOf = (cls, html) => {
    let W = null;
    return () => {
      if (W) return W;
      const k = document.createElement('div'); k.className = 'k'; k.style.cssText = 'left:0;top:0;visibility:hidden';
      k.innerHTML = '<span class="ln ' + cls + '"><span>' + html + '</span></span>'; fxEl.appendChild(k);
      const ws = [...k.querySelectorAll('.w')].map((w) => w.offsetWidth); k.remove();
      if (document.fonts.status === 'loaded' && ws.every((v) => v > 0)) W = ws;
      return ws;
    };
  };
  const sum = (W, n) => W.slice(0, n).reduce((s, v) => s + v, 0);
  // piecewise glide: from x0, E.inOut to each [b0, b1, to] in turn (to may be a function of the beat)
  const glide = (b, x0, segs) => segs.reduce((x, [b0, b1, to]) => lerp(x, typeof to === 'function' ? to(b) : to, E.inOut(clamp((b - b0) / (b1 - b0)))), x0);

  /* ---------- 1a（b0–5.4） ---------- */
  // T0 (b0.2–0.98): a tight cluster in the middle of the black, popping in one after another (E.back .3 beats, stag .12):
  // cc (960, 500) / cx (1017, 541) / gm (995, 609) / ds (925, 609) / cp (903, 541), turning 8°/beat
  // v17.7 F3 1a: the film opens on ONE — an orb (dot 0, r 30: the five mini badges ≈ 21 px) pops at b0.2 with dots 1–4
  // stacked under it (a .001, so the split blends them out of it instead of popping them), and splits into the R 60
  // cluster b0.35–.8 while the orb melts back into cc's badge: 一 → 五 from the first beat (the close ends on the orb again)
  AGD.key(0.2, 'pts', { pts: [[960, 560], [960, 560], [960, 560], [960, 560], [960, 560]], drift: 0, r: 30, a: (b, i) => (i ? .001 : 1), dur: .3 });
  AGD.morph(0, 0, 'orb', { dur: .01 });
  // v18.1 (b): the split lays the five out as a point-down pentagon whose left → right order is the pen's (dot i →
  // pen slot i), so at b0.8–1.1 every dot drops to its own slot without crossing another — the bottom vertex (gm)
  // falls straight to the middle slot, the side ones (cc / cp) to the ends. ph(b, i) puts dot i at RING_A[i] degrees
  const RING_A = [252, 324, 180, 36, 108];
  AGD.key(0.35, 'ring', { ...AGD.P.cluster, ph: (b, i) => RING_A[i] - 72 * i, dur: .4, stag: .02 });
  AGD.morph(0.3, 0, 'dot', { dur: .25 });            // melted by b0.55, before dots 1–4 are half out (no orb + badges double image)
  // 1a.2: 「用 AI Agent，」 (the subject, small) floats up out of the cluster from b0.4 — characters blur in while the line
  // rises 18 px onto y 430 (the cluster's top edge is y 466); the headline 「正在成为每个人的日常」 wipes in a word on
  // b1.1 / 1.52 / 1.94 (.45 beat each, ≤ 1600; 「正在」 waits until the pen has left the type band, so the small line reads
  // alone first) and 「日常」 (orange) stamps in on b2.36 and hits on b2.66. 1a.3: both lines leave
  // b4.8–5.4 — fade + blur, drifting up 60 px; until then both keep a slow push (+6 %). Whole headline readable
  // b2.66–4.8 (2.14 beats), the small line b1.5–4.8
  const up60 = (tl, life) => -60 * E.inOut(clamp((tl - (life - BB(.6))) / BB(.6)));
  // v18.1: the small line is the subject alone, 「AI Agent，」 (「用 AI Agent，正在成为…」 used a verb phrase as the
  // subject); it steps in on b0.5 as the orb splits (landing with the settle), whole by b0.9
  txt(0.4, T(5.4), [['lt in-s', '<span class="w">AI Agent，</span>']], { x: 960, y: 430, align: 'c' }, {
    anim: wipe({ at: [.1], push: .06, up: 60, out: .6 }),
    // v17.7: it floats up out of the splitting cluster — from 40 px lower (the top dot's crown) over 1 beat
    tick: (el, tl) => { el.style.transform += ' translateY(' + (40 * (1 - E.out(clamp(tl / BB(1.0))))).toFixed(1) + 'px)'; }
  });
  const HEAD = ['hv sv in-big', '<span class="w">正在</span><span class="w">成为</span><span class="w">每个人的</span><span class="w in-hot">日常</span>'];
  const HB0 = .5, HB1 = T(5.4), HAT = [.6, 1.0, 1.45, 1.8];       // v17.5: b1.1 / 1.5 / 1.95, 「日常」 stamps b2.3, hits b2.6
  txt(HB0, HB1, [HEAD], { x: 960, y: 540, align: 'c' }, { anim: wipe({ at: HAT, stamp: 3, fit: 1600, push: .06, up: 60, out: .6 }) });
  // T0′ the pen (b0.8–4.8): a ∪ arc (gap 56, sag −14, r 28) 112 px under the headline, centred under the newest word. A
  // centred line re-centres as a word grows, so word k sits at 960 + (width of the words before it) / 2 for its whole
  // wipe (× the push); the pen glides there (E.io .42) and arrives .08 beat before the word starts, stays under 「日常」
  // through the hit, then drifts slowly back to 960 while the line is read (b3.2–4.4) and rises with the line's exit
  // (652 → 592, same ease and beats as up60)
  const headW = wordsOf(HEAD[0], HEAD[1]);
  const headC = (k) => (b) => {
    const W = headW(), p = sum(W, k);
    return 960 + p / 2 * Math.min(1, 1600 / sum(W, k + 1)) * (1 + .06 * clamp((b - HB0) / (HB1 - HB0)));
  };
  const penX = (b) => glide(b, 960, [1, 2, 3].map((k) => [HB0 + HAT[k] - .26, HB0 + HAT[k] - .02, headC(k)]).concat([[3.2, T(4.4), 960]]));   // v17.5: steps in the gap after each word lands
  const penY = (b) => 652 - 60 * E.inOut(clamp((b - (HB1 - .6)) / .6));
  // front-loaded (smoothstep into a cubic ease-out, zero speed at both ends) so the cluster clears the type band
  // (y 480–600) while 「每天」 is still wiping in: at b1.0 the dots are ≈ 75 % of the way down
  const PEN_E = (p) => { const s = p * p * (3 - 2 * p); return 1 - Math.pow(1 - s, 3); };
  // v18.1 (b): no stagger — with one shared ease the pentagon → ∪ blend keeps every pair's left → right order, so the top
  // pair (cx / ds) comes down beside the side pair (cc / cp) instead of sliding over it (v17.5's .025 per index made ds
  // pass in front of cp at b0.95)
  AGD.key(0.8, 'arc', { cx: penX, cy: penY, gap: 56, sag: -14, r: 28, dur: .5, stag: 0, ease: PEN_E });
  // every dot breathes (1.06, .5 beats) as each word lands; under 「日常」 the pen gives a firmer press (1.1) on the hit,
  // b2.66; while the whole line is read it keeps breathing softly (1.04) about every .65 beat (new grid) until the exit
  for (const k of [0, 1, 2]) for (let i = 0; i < 5; i++) AGD.pulse(i, HB0 + HAT[k] + .2 + .03 * i, 1.06, .5);   // v17.5: on each landing
  for (const b of [3.55, 4.2, 4.85, 5.5, 6.15]) for (let i = 0; i < 5; i++) AGD.pulse(i, b + .03 * i, 1.04, .5);
  // v17.7 F3 1a: the pen's dots are beads on an invisible ∪ thread (rot 'tan'; only 2.0 r long — the pen's gap is 56 =
  // two radii, so they flatten across the thread instead of stretching along it), logo .86 (≈ 31 px)
  const BEAD = { w: 2.0, h: 1.72, rad: .86, ls: .86 };
  AGD.morph(0.8, 'all', 'bead', { ...BEAD, dur: .5, stag: .025 });
  // the lead (rightmost, cp) dot stretches into a pill aimed at the growing word's right edge as 「成为」 / 「每个人的」 wipe
  // in (.12 beat out, .2 back), as if it pushed the word out
  const headR = (k) => { const W = headW(), s = sum(W, k + 1); return [960 + s / 2 * Math.min(1, 1600 / s), 540]; };
  for (const k of [1, 2]) {
    const w = HB0 + HAT[k];
    AGD.morph(w - .04, 4, 'pill', { w: 2.4, aim: () => headR(k), dur: .12 });
    AGD.morph(w + .2, 4, 'bead', { ...BEAD, dur: .2 });
  }
  // 「日常」's stamp: all five press flat on the hit (b2.45–2.6, the glyphs 1.3 → .97) and come back with the settle (to b2.9)
  AGD.morph(HB0 + HAT[3] + .15, 'all', 'bead', { ...BEAD, w: 2.2, h: 1.5, dur: .15, stag: 0 });
  AGD.morph(HB0 + HAT[3] + .3, 'all', 'bead', { ...BEAD, dur: .3, stag: .02 });
  // T1 (b4.8 → 5.96): the ∪ pen turns over into the ∩ arc in place (the centre moves 16 px) and opens to gap 112:
  // cc (736, 632) / cx (848, 614) / gm (960, 608) / ds (1072, 614) / cp (1184, 632); from b5.8 the dots drift ≤ 6 px
  const drift = (b) => 6 * E.inOut(clamp((b - T(5.8)) / 1.0));
  AGD.key(T(4.8), 'arc', {
    ...AGD.P.arcB, dur: 1.0, stag: .04,
    cx: (b, i) => AGD.P.arcB.cx + drift(b) * Math.sin(2 * Math.PI * (b / 8 + .23 * i)),
    cy: (b, i) => AGD.P.arcB.cy + .6 * drift(b) * Math.sin(2 * Math.PI * (b / 10 + .37 * i))
  });
  // v17.7: the beads round back into full badges as the pen turns over
  AGD.morph(T(4.8), 'all', 'dot', { dur: .7, stag: .04 });

  /* ---------- 1b（b5.2–10.8） ---------- */
  // the box grows out of the dots' centre (≈ 960, 615) from b5.2 and lands at (960, 760) by b5.8; after the last send
  // it shrinks back into the arc (b9.3–9.7), as the icons reach the halo
  const c = AGD.chat(T(5.2), T(9.7), { x: 960, y: 760, w: 980, from: AGD.centroid, to: AGD.centroid });
  // masked rise b5.3–6.3, slow push (+4 %); leaves b8.8–9.4, up ≈ 40 px, before the top icons cross y ≈ 316
  // v17.5: 「从想法」 / 「到交付」 step in (b7.0 / 7.35 film), whole by b7.59 (readable 3.6 as before)
  txt(T(5.2), T(9.4), [['hv sv in-t1', '<span class="w">从想法</span><span class="w">到交付</span>']], { x: 960, y: 250, align: 'c' },
    { anim: wipe({ at: [0, .35], push: .04, up: 40, out: .6 }) });
  // T2: every dot has one bubble slot, in two layers so nothing overlaps: lower (dy −r − 18, y ≈ 508–572) cc tail x 560 /
  // gm 960 / cp 1360; upper (dy −r − 104, y ≈ 404–468) cx 740 / ds 1180, with a stem down to the dot. A second bubble on
  // the same dot replaces the first (AGD's default: the old one shrinks into the dot as the new one pops); each stays
  // whole ≥ max(1.4, .9 + .12 / character) beats (v17.3). Every bubble's tail rises 26 px out of the dot over .6 beats,
  // then floats on away from it at 5 px/beat.
  const BR = AGD.P.arcB.r, SLOT = [[-176, -BR - 18], [-108, -BR - 104, true], [0, -BR - 18], [108, -BR - 104, true], [176, -BR - 18]];
  const rise = (b0, base) => (b) => base + 26 * (1 - E.out(clamp((b - b0) / .6))) - 5 * Math.max(0, b - b0);
  const slot = (i, b0, o = {}) => ({ dx: SLOT[i][0], dy: rise(b0, SLOT[i][1]), stem: !!SLOT[i][2], ...o });
  // v17.7 (new grid): two prompts typed one character at a time (typeOn, ≈ .25 beat each, the caret solid while it
  // types) — 「做一个记账 App」 b7.2–9.16 (the box still growing under the first key), sent .22 after the last key;
  // 「写份路演稿」 from .17 after that send, b9.55–10.54, sent b10.76 (pops b10.91, .44 before the icons burst). 「生成产品
  // 官网」 is no longer typed: it is ds's own bubble. A dot that carries a send hosts at most one earlier, short prompt,
  // so every bubble gets its full reading time (whole from pop + .25 to its replacement / retract): 爬虫 7.8–9.8 (2.0),
  // 图标 8.1–10.2 (2.1), 数据看板 8.35–10.1 (1.75), 会议纪要 9.05–11.95 (2.9), 记账 App 9.78–11.8 (2.0), 产品官网
  // 10.35–13.2 (2.85), 小游戏 10.7–12.8 (2.1), 路演稿 11.16–13.05 (1.9)
  const K1 = typeOn(c, 7.2, '做一个记账 App', 31, 0), S1 = K1[K1.length - 1] + .22;
  c.send(S1, 0, slot(0, S1 + .15, { until: 12.0 }));
  const K2 = typeOn(c, S1 + .17, '写份路演稿', 32, 1), S2 = K2[K2.length - 1] + .22;
  c.send(S2, 1, slot(1, S2 + .15, { until: 13.25 }));
  // the dots' own prompts (kind 'ask'); everything still up retracts in turn b12.0–13.4 after the icons burst (the
  // last, on ds, as the caret fold starts)
  AGD.bubble(1, T(5.75), T(7.6), '写个爬虫', slot(1, T(5.75)));
  AGD.bubble(2, T(6.05), T(8.0), '画一套图标', slot(2, T(6.05)));
  AGD.bubble(3, T(6.3), T(8.45), '做个数据看板', slot(3, T(6.3)));
  AGD.bubble(4, 8.8, T(9.75), '整理会议纪要', slot(4, 8.8));                    // new grid
  AGD.bubble(3, 10.1, T(10.4), '生成产品官网', slot(3, 10.1));                  // new grid
  AGD.bubble(2, 10.45, T(10.0), '做个小游戏', slot(2, 10.45));                  // new grid
  // each dot glows and breathes as a bubble leaves it (new grid)
  for (const [i, b] of [[1, T(5.75)], [2, T(6.05)], [3, T(6.3)], [4, 8.8], [0, S1 + .15], [3, 10.1], [2, 10.45], [1, S2 + .15]]) {
    AGD.glow(i, b, b + .6, .8); AGD.pulse(i, b, 1.08, .5);
  }

  /* v17.7 F3 1b — the dots' shapes lead every element of the shot */
  // the box is pulled out of the dots: .25 beat before it grows (b7.0) all five stretch into pills aimed at its centre,
  // and round back (.4) once it is half grown
  AGD.morph(T(5.2) - .25, [0, 2, 3, 4], 'pill', { w: 2.8, aim: [960, 760], dur: .25, stag: .02 });
  AGD.morph(T(5.2) + .12, [2, 3, 4], 'dot', { dur: .4, stag: .02 });
  // v18.1 1a → 1b: the eye is led from the old line to the new one — while the headline lifts and blurs (b6.6–7.2) dot 1
  // (cx, the arc's second from the left, right under it) stretches into a pill aimed up at 「从」 (the first character of
  // 「从想法」 as it lands, centred alone), full on b7.0 as the word wipes in, and lets go (.3) as 「到交付」 starts (b7.35)
  const t1W = wordsOf('hv sv in-t1', '<span class="w">从想法</span><span class="w">到交付</span>');
  AGD.morph(T(5.2) - .25, 1, 'pill', { w: 4.0, aim: () => [960 - t1W()[0] / 2 + 66, 250], dur: .25 });
  AGD.morph(T(5.2) + .35, 1, 'dot', { dur: .3 });
  // typing: the dot that will take the prompt stands on the arc as a caret (38 px, the box caret's height) that bobs on
  // every key — the pulse reads typeOn's character beats, the same grid as the key sounds — while the box caret takes its
  // colour; .2 beat before the send the caret swells into a bubble tail aimed at its slot, the bubble pops from the tail
  // tip (c.send's light trail ends there) and the tail rounds back into the badge
  const anchor = (b, i) => { const p = AGD.pos(i, b); return [p.x + SLOT[i][0], p.y + SLOT[i][1]]; };
  const caretAt = (i, b0, K, S, back) => {
    AGD.morph(b0, i, 'caret', { hpx: (b) => 38 * (1 + .06 * AGD.beatPulse(b, K, .2)), dur: .4 });
    AGD.morph(S - .2, i, 'tail', { tail: .8, tailDir: anchor, dur: .2 });
    if (back) AGD.morph(S + .15 + .3, i, 'dot', { dur: .35 });
  };
  caretAt(0, T(5.2) + .12, K1, S1, true);          // dot 0 goes straight from the pull-out pill to the caret
  caretAt(1, S1 + .1, K2, S2, false);              // dot 1's tail flows on into the spark (b11.15)
  // the dots' own prompts: dot → tail (.15) → the bubble pops from its tip → back to the badge (hold .3)
  for (const [i, b] of [[1, T(5.75)], [2, T(6.05)], [3, T(6.3)], [4, 8.8], [3, 10.1], [2, 10.45]])
    AGD.morph(b - .15, i, 'tail', { tail: .8, tailDir: anchor, dur: .15, hold: .3, back: .3 });

  /* ---------- 1b.3 – 1c: the App icons ---------- */
  // 12 rounded tiles (88 px, dark glass, white line glyphs drawn here — no third-party marks), in ring order θ = 30k.
  // Phase: at b≈12.5 the two top slots straddle 12 o'clock.
  const G = [
    'M-10-16h13l9 9v23h-22z M3-16v9h9 M-5-4h5 M-5 3h12 M-5 10h12',                                             // document
    'M-17-12h34v22h-34z M0 10v6 M-7 16h14 M-4-6.5l9 5.5-9 5.5z',                                                 // slides
    'M-7-11l-11 11 11 11 M7-11l11 11-11 11 M3.5-16l-7 32',                                                      // code
    'M0-16a16 16 0 1 0 .01 0z M-16 0h32 M0-16c-9 9-9 23 0 32 M0-16c9 9 9 23 0 32',                               // web
    'M-17 15h34 M-11 11v-9 M-3.5 11v-19 M4 11v-13 M11.5 11v-24',                                                // bar chart
    'M-17-13h34v26h-34z M-17 9l10-10 9 9 6-5 9 8 M8-5.5a3.5 3.5 0 1 0 .01 0z',                                  // image
    'M-16-13h32v26h-32z M-16-4h32 M-16 5h32 M-5-13v26 M6-13v26',                                                // table
    'M-17-13h34v26h-34z M-10-5l6 5-6 5 M1 6h9',                                                                  // terminal
    'M-17-11h34v22h-34z M-17-11l17 13 17-13',                                                                    // mail
    'M-16-11h32v26h-32z M-16-3h32 M-9-16v8 M9-16v8 M-8 6h.01 M0 6h.01 M8 6h.01',                                 // calendar
    'M-4 12v-24l15-4v24 M-8.5 7.5a4.5 4.5 0 1 0 .01 0z M6.5 3.5a4.5 4.5 0 1 0 .01 0z',                            // music
    'M0-17l15 8v17l-15 8-15-8v-17z M-15-9l15 8 15-8 M0-1v17'                                                     // cube
  ];
  const ORDER = [0, 4, 7, 2, 9, 1, 8, 3, 10, 5, 11, 6];          // which glyph sits at ring slot k
  // B0 = first launch (b8.95, v17.7: .44 beat after the last send pops), FL = flight beats; the ring phase is referenced to b8.6
  // (PH0, v17.2's b6.6 + 2), so the halo stands at the same angles at each event as before the v17.3 shift
  const HC = [960, 520], HRX = 760, HRY = 380, SPIN = 4, B0 = T(8.95), FL = 1.0, PH0 = T(8.6);
  const SRC = [2, 3, 3, 4, 4, 5, 5, 0, 0, 1, 1, 2];              // slot k sprays from dot i (5 = the input box), nearest bearing
  const T0 = SRC.map((s, k) => (s === 5 ? B0 : B0 + .08) + .3 * hash01(k, 21));   // launch beats (box first); all land by b10.35
  const R0 = SRC.map((s, k) => (k % 2 ? 1 : -1) * (16 + 10 * hash01(k, 23)));  // tilt in flight, settles with a small bounce
  const th = (k, b) => 30 * k + SPIN * (b - PH0);
  const halo = (deg) => [HC[0] + HRX * Math.sin(deg * D2R), HC[1] - HRY * Math.cos(deg * D2R)];
  // 1c.3: as each word lands, the 3 nearest icons are drawn 40 px toward it and spring back. Word centres follow the
  // line as K.words refits it (We alone → We Are → the full line, 1150 px; Everything on the second line).
  const WORDS = [[10.8, 960, 470], [11.3, 1067, 470], [11.8, 1182, 470], [12.3, 960, 615]].map(([w0, x, y]) => {
    const w = T(w0), d = SRC.map((_, k) => { const q = halo(th(k, w)); return [Math.hypot(q[0] - x, q[1] - y), k]; }).sort((a, b) => a[0] - b[0]);
    return { w, x, y, near: d.slice(0, 3).map((e) => e[1]) };
  });
  const pullF = (u) => (u <= 0 || u >= 1 ? 0 : u < .28 ? E.out(u / .28) : 1 - ease.back((u - .28) / .72));
  function icon(k, b) {
    const t0 = T0[k]; if (b < t0) return null;
    const p = clamp((b - t0) / FL);
    let [x, y] = halo(th(k, b)), s = 1, rot = 0, a = 1;
    if (p < 1) {                                                  // flight: quadratic arc bowed away from the ring centre
      const S = SRC[k] < 5 ? (() => { const q = AGD.pos(SRC[k], t0); return [q.x, q.y]; })() : [960, 760];
      const dx = x - S[0], dy = y - S[1], L = Math.hypot(dx, dy) || 1, mx = (S[0] + x) / 2, my = (S[1] + y) / 2;
      let nx = -dy / L, ny = dx / L; if (nx * (mx - HC[0]) + ny * (my - HC[1]) < 0) { nx = -nx; ny = -ny; }
      const C = [mx + nx * .2 * L, my + ny * .2 * L], e = E.out(p), v = 1 - e;
      x = v * v * S[0] + 2 * v * e * C[0] + e * e * x; y = v * v * S[1] + 2 * v * e * C[1] + e * e * y;
      s = lerp(.3, 1, ease.back(p)); rot = R0[k] * (1 - E.out(p)); a = Math.min(1, p * 3);
    } else {
      const q = clamp((b - t0 - FL) / .4); rot = -R0[k] * .3 * Math.pow(Math.sin(Math.PI * q), 2);
    }
    // icons near a dot ease aside (soft, continuous), never under it (v17's scatter crossed the halo; the compact v17.1
    // group stays inside it, so this rarely fires)
    const wr = clamp((b - t0 - FL) / .3);
    if (wr > 0) for (let i = 0; i < 5; i++) {
      const d = AGD.pos(i, b); if (d.a <= .01) continue;
      const ux = x - d.x, uy = y - d.y, l = Math.hypot(ux, uy) || 1, push = Math.max(0, 115 - l);
      if (push > 0) { const f = wr * push * push / 115; x += ux / l * f; y += uy / l * f; }
    }
    for (const W of WORDS) if (W.near.includes(k)) {
      const f = pullF((b - W.w) / .9); if (!f) continue;
      const ux = W.x - x, uy = W.y - y, l = Math.hypot(ux, uy) || 1; x += ux / l * 40 * f; y += uy / l * 40 * f;
      // v17.7: and lean (≤ 12°) toward it while drawn in
      rot += f * clamp((Math.atan2(ux, -uy) / D2R - rot + 540) % 360 - 180, -12, 12);
    }
    a *= lerp(1, .6, E.inOut(clamp((b - T(10.6)) / .6)));            // 1c.1: down to 60 % (b10.6–11.2)
    const q2 = E.inOut(clamp((b - T(12.3)) / (T(14.8) - T(12.3))));                  // 1c.3: turn to face outward, shrink to .7 (slowly, b12.3–14.8)
    if (q2 > 0) { const az = Math.atan2(x - HC[0], -(y - HC[1])) / D2R; rot = lerp(rot, az, q2); s *= lerp(1, .7, q2); }
    const q3 = E.in(clamp((b - T(14.7)) / .9));                      // 1c.4: fly out along the radius and fade (b14.7–15.6)
    if (q3 > 0) { x = HC[0] + (x - HC[0]) * (1 + 1.4 * q3); y = HC[1] + (y - HC[1]) * (1 + 1.4 * q3); a *= 1 - q3; }
    return { x, y, s, rot, a };
  }
  const DEFS = '<defs><linearGradient id="inIcG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b2e35" stop-opacity=".94"/>' +
    '<stop offset="1" stop-color="#14161a" stop-opacity=".94"/></linearGradient></defs>';
  AGD.back(B0, T(15.6), (b) => {
    let s = DEFS;
    // the halo itself: a faint ellipse that draws in as the icons land, dims with them and fades before they fly out
    const hv = E.inOut(clamp((b - T(9.2)) / 1.0)), ha = .09 * lerp(1, .6, E.inOut(clamp((b - T(10.6)) / .6))) * (1 - E.inOut(clamp((b - T(14.5)) / .6)));
    if (hv > 0 && ha > .002) s += '<path d="M960 140A760 380 0 0 1 960 900A760 380 0 0 1 960 140" fill="none" stroke="#fff" stroke-opacity="' + ha.toFixed(3) + '" stroke-width="1.5" pathLength="1" stroke-dasharray="' + hv.toFixed(4) + ' 2"/>';
    for (let k = 0; k < 12; k++) {
      const q = icon(k, b); if (!q || q.a <= .002) continue;
      s += '<g transform="translate(' + q.x.toFixed(1) + ' ' + q.y.toFixed(1) + ') rotate(' + q.rot.toFixed(2) + ') scale(' + q.s.toFixed(4) + ')" opacity="' + q.a.toFixed(3) + '">' +
        '<rect x="-44" y="-44" width="88" height="88" rx="22" fill="url(#inIcG)" stroke="#fff" stroke-opacity=".17" stroke-width="1.5"/>' +
        '<path d="M-30-43.2h60" stroke="#fff" stroke-opacity=".08" stroke-width="1.5"/>' +
        '<path d="' + G[ORDER[k]] + '" fill="none" stroke="#fff" stroke-opacity=".92" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" transform="scale(1.02)"/></g>';
    }
    return s;
  });
  // v17.7 F3 1b: the burst's source — .2 beat before the first icon leaves (b11.35) all five open into sparks (five
  // Agent-coloured rays grow over .4 beat, turning); as the box sinks into the arc (b11.7–12.1) the rays fold back into
  // pills aimed at it, so the box is drawn in by them, and the badges round back by b12.35
  AGD.morph(B0 - .2, 'all', 'spark', { dur: .4, stag: .03 });
  AGD.morph(T(9.3) - .05, 'all', 'pill', { w: 2.4, aim: (b) => [960, Math.min(760, AGD.centroid(b).y + 150)], dur: .3, stag: .02 });
  AGD.morph(T(9.3) + .3, 'all', 'dot', { dur: .4, stag: .02 });

  /* ---------- 1c（b10.6–15.75） ---------- */
  // 1c.2: two lines, one word wiping in per half beat (b10.8 We / 11.3 Are / 11.8 Redesigning / 12.3 Everything, .45–.5
  // beat each), slow push meanwhile; 1c.4: the letters drift apart as both lines leave (b14.8–15.6). Whole: 「We Are
  // Redesigning」 b12.25–14.8 (2.55 beats), 「Everything」 b12.8–14.8 (2.0)
  const W1 = ['xl sv in-w1', '<span class="w">We</span><span class="w"> Are</span><span class="w"> Redesigning</span>'];
  const CB0 = T(10.8), CB1 = T(15.6), CAT = [0, .5, 1.0];
  // 1c → 1d: as 15-redesign's caret lies down (b14.8) its arc path runs through the 30 px gap between this line's
  // descenders (y ≈ 530) and 「Everything」's ascenders (≈ 560) while both are still ≥ 50 % opaque, so this line lifts 48 px
  // out of the dots' way with their own front-loaded ease (PEN_E = 15-redesign's H3E, b14.8–15.4; 「Everything」 stays,
  // the gloss is under it)
  txt(CB0, CB1, [W1], { x: 960, y: 470, align: 'c' }, {
    anim: wipe({ at: CAT, fit: 1150, push: .04, out: .8, spread: true }),
    tick: (el, tl, life) => { el.style.transform += ' translateY(' + (-48 * PEN_E(clamp((tl - (life - BB(.8))) / BB(.6)))).toFixed(1) + 'px)'; }
  });
  // T3 / T3′ the caret (b10.2–14.8): the arc folds into a short column (gap 34, r 16, ≈ 168 px tall like the 120 px type;
  // cc on top, cp at the bottom, paths don't cross) standing 52 px right of the line's right edge once the next word is
  // in (fit 1150, × the push), so each word wipes in to its left; it steps on (E.io .4) .1 beat before each word:
  // ≈ 1100 (We) → 1222 (We Are) → 1587 (We Are Redesigning). Then an L, down first, outside the first line's right end:
  // y 470 → 615 (b11.95–12.3), x → 1400 (b12.1–12.5), and 「Everything」 (y 615, x ≈ 580–1340) wipes in on its left.
  // b12.5–14.8 it rests at (1400, 615), breathing every ≈ .5 beat (the icons keep turning, the type keeps its push);
  // 15-redesign's arc key (its b11.8 + SHIFT 3 = b14.8) takes it from there (T4).
  const w1W = wordsOf(W1[0], W1[1]);
  const w1R = (k) => (b) => {
    const s = sum(w1W(), k + 1);
    return 960 + s / 2 * Math.min(1, 1150 / s) * (1 + .04 * clamp((b - CB0) / (CB1 - CB0))) + 52;
  };
  const caretX = (b) => glide(b, w1R(0)(b), [[CB0 + CAT[1] - .26, CB0 + CAT[1] - .02, w1R(1)], [CB0 + CAT[2] - .26, CB0 + CAT[2] - .02, w1R(2)], [T(12.1), T(12.5), 1400]]);   // v17.5: steps after each word lands
  const caretY = (b) => glide(b, 470, [[T(11.95), T(12.3), 615]]);
  // v17.7 F3 1c: the five dots fold (stag .03, as the key) into ONE five-colour segmented caret — segments 24 px tall,
  // 26 apart (128 px ≈ the 132 px type), cc on top: the logos fade, the colours top to bottom are the five Agents
  AGD.key(T(10.2), 'column', { x: caretX, y0: (b) => caretY(b) - 52, gap: 26, r: 16, dur: .55, stag: .03, arc: 20 });
  // as each word lands the segments ripple top to bottom (h × 1.08); the caret leans 4° into each step to the right
  // (−4° on the step back left to 1400) and stands up again; at rest (from b15.4) it breathes — its fill dims to .7
  // and back on a 1-beat sine, never a hard blink — until 15-redesign lays it down (b18.7)
  const RIP = [11.0, 11.5, 12.0, 12.5].map(T);
  const STEPS = [[CB0 + CAT[1] - .26, CB0 + CAT[1] - .02, 1], [CB0 + CAT[2] - .26, CB0 + CAT[2] - .02, 1], [T(12.1), T(12.5), -1]];
  const REST = T(12.5);
  AGD.morph(T(10.2), 'all', 'caret', {
    hpx: (b, i) => 24 * (1 + .08 * AGD.beatPulse(b, RIP.map((w) => w + .05 * i), .45)),
    rot: (b) => STEPS.reduce((r, [b0, b1, s]) => r + 4 * s * Math.sin(Math.PI * clamp((b - b0) / (b1 - b0))), 0),
    fill: (b) => 1 - .3 * E.inOut(clamp((b - REST) / .5)) * (.5 - .5 * Math.cos(2 * Math.PI * (b - REST))),
    dur: .55, stag: .03
  });
  // it leaves over b14.8–15.4 (.6, not .8): the lower dots rise across its 「ng」 on their way left (b15.0–15.3), so it is
  // under half opacity by b15.1 instead of .77
  txt(T(12.3), T(15.4), [['xl in-ev', '<span class="w">Everything</span>']], { x: 960, y: 615, align: 'c' },
    { anim: wipe({ at: [0], dur: .26, push: .03, out: .6, spread: true }) });
  // the gloss (v17.2): 「人们正在用 Agent 重新设计一切」 fades in with 「Everything」 (v17.4: from b12.3, not 12.5; .3 beat, rising
  // 14 px out of a light blur, whole by b12.6) at y 728 under it, and leaves a touch after the English (b15.35–15.75, .4 beat,
  // gone before 15-redesign's box passes y 728) so it reads 3.65 beats; 15-redesign's first type (b15.8) is not under it
  // v18.1: it no longer outlives the type — it leaves with the headline's exit (E.inOut from b18.7) .1 beat behind,
  // blurring to 6 px, gone by b19.3 together with 「Everything」
  txt(T(12.3), T(15.4), [['lt in-gloss', '人们正在用 Agent 重新设计一切']], { x: 960, y: 728, align: 'c' }, {
    anim: (el, tl, life) => {
      const p = E.out(clamp((tl - BB(.1)) / BB(.2))), q = E.inOut(clamp((tl - (life - BB(.5))) / BB(.5)));   // v17.5: .1 after Everything, whole by +.3 as before
      // v17.7: wiped right → left out of the caret's foot (it stands just right of the line's end), not risen
      el.style.transform = 'translate(-50%,-50%) translateY(' + (-20 * q).toFixed(1) + 'px)';
      el.style.clipPath = p < .999 ? 'inset(-30% 0 -30% ' + (100 * (1 - p)).toFixed(2) + '%)' : '';
      leave(el, Math.min(1, p * 2) * (1 - q));
      if (p < .999 && q < .001) el.style.filter = 'blur(' + ((1 - p) * 5).toFixed(1) + 'px)';
      else if (q > 0) el.style.filter = q < .999 ? 'blur(' + (6 * q).toFixed(1) + 'px)' : 'none';
    }
  });
});

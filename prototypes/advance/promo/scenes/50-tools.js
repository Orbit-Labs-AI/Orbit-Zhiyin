/* 50-tools 5（b55.0–75.2；v17.3 轨迹段加长 3 拍，b61.1 起的一切 +3；v17.5 为读清阶段胶囊再加 3 拍：阶段节点重排，b64.1 起的一切 +3） — STORYBOARD.md v17「5 会话轨迹 + 生成工坊」，点位按 v17.1 V1 / T11–T13.
   5.1 短列的 5 个点合并为一（AGD merge (330, 540)）→ 5.2–5.3 会话轨迹卡（deck 0），合并点细线连到卡后骑在播放头下方走过
   5 个阶段 → 5.4 传送带换成生成工坊（deck 1），点滑到「开始生成」上 → 5.5 点就是光标，按下（只有 bloom，无指针）→
   5.6 点退到运行卡左缘外 56 px 当生成源，连线与 pulse 流向运行卡，SKILL.md 一行行写出 → 5.7 工坊卡朝点缩小轻转淡出，
   点回到画面中心 (960, 540)。b75.2 起 60-close 从中心螺旋放出成环。
   旧镜头（.mt-ph 胶囊、播放头、DIAG 传送带）来自 git show 78841089^:prototypes/advance/promo/scenes/50-montage.js。
   生成过程用 App 自己的 studioStep / refreshStudio，但按成片拍逐帧推进（App 自带的定时器约 8 秒跑完，这里压到 b68.95–73.75，SKILL.md 逐字写出）。 */
scene('50-tools', () => {
  css(`
.mt-ph{display:inline-flex;align-items:center;gap:14px;font:600 44px var(--sans);color:#fff;padding:10px 26px 12px;border-radius:999px;background:rgba(10,11,13,.9);border:1px solid rgba(255,255,255,.22)}
.mt-ph i{width:14px;height:14px;border-radius:50%;background:#fff}
.mt-ph b{font-weight:600}
.mt-ph.warn b{color:#f3c56b}.mt-ph.warn i{background:#f3c56b}
.mt-ph.crit b{color:#ff8a7a}.mt-ph.crit i{background:#ff8a7a}
.mt-ph.good b{color:#7fd6a4}.mt-ph.good i{background:#7fd6a4}
.mt-stem{display:block;width:2px;height:34px;margin:0 auto;background:linear-gradient(rgba(255,255,255,.7),rgba(255,255,255,0))}
.ln.t5h{font-size:72px}
.ln.t5h>span:has(.sw){background:none;color:#fff}
.ln.t5h .sw>span{background:linear-gradient(180deg,#fff 35%,#b4b8c2);-webkit-background-clip:text;background-clip:text;color:transparent}
.ln.t5o>span{color:var(--a1)}
.mt-ph.gh{font-size:26px;gap:9px;padding:6px 16px 8px;background:rgba(10,11,13,.82)}
.mt-ph.gh i{width:9px;height:9px}
/* v18.2: the eyebrows read as「03 · 会话轨迹」/「04 · 生成工坊」in the same mono as 01 / 02 (24 px, α .7); the swap slots
   do not clip (the old line rises and blurs out, the new one rises in) and each word sits on the slot's centre */
.ln.eb.t5e{font-size:24px;color:rgba(255,255,255,.7)}
.ln.t5s .sw{overflow:visible}
.ln.t5s .sw>span{left:50%}
`);
  // tag() writes 'scale(k) translate(…)'; swapping the order keeps a counter-scaled tag on its edge (v16 50-montage)
  const fixTag = (el) => { el.style.transform = el.style.transform.replace(/^(scale\([^)]*\))\s*(translate\([^)]*\))$/, '$2 $1'); };
  const advLight = (d) => { const W = decks[d].W; if (W.eval('S.ed') !== 'advance') W.eval("S.ed='advance';store.set('edition','advance');document.querySelector('#win').dataset.ed='advance'"); W.setTheme('light'); };
  const WIRE = 'rgba(255,255,255,.43)';                     // AGD draws links at stroke-opacity .7 → white 30 %

  /* ---------- 5.1 merge (b55.0–56.4) and the merged dot's path to the b75.2 hand-off (v17.1 V1, T11–T13) ----------
     ONE merge key with live x / y / r (a second merge key would fan the dots out again). The dot is where the eye is:
     (330, 540) (ds is already there, the column closes on it) → b56.8–57.4 under the playhead, then rides it (card
     bottom + 46) → b67.4–68.65 onto 开始生成 (it is the pointer; pressed at the b68.8 click) → b69.0–69.6 56 px left of the
     run card (the generator) → b74.1–75.2 screen centre (960, 540), where 60-close's spiral starts. All E.inOut. */
  const io = (b, b0, d) => E.inOut(clamp((b - b0) / d)), mix = (P, Q, e) => [lerp(P[0], Q[0], e), lerp(P[1], Q[1], e)];
  const MERGE = [330, 540], HOME = [960, 540], BACK = 73.9;   // v18.1: the orb leaves for the centre at b73.9 (was 74.1)
  const CX = 67.3, HOV = 68.5, PRESS = 68.8, BOFF = 69.4;   // v18.2: card exit; hover (.3 beat) before the press; button gone
  const PADS = () => 22 * decks[0].C.s;                     // the timeline panel's margin (promo-card, 22 frame px) on screen
  // under the playhead, card-fixed: the card's exit (b67.3, .45 beat, E.in, moves only ax by −240) is taken back out,
  // so the dot keeps riding the playhead's creep instead of being dragged up-left and then turning back to the button.
  // Right under the timeline the card's own status line (已发生 n / 143) and legend fill the space, so the dot rides 46 px
  // below the card's bottom edge at the playhead's x: it covers none of the app's text (T11′: pill above, dot below)
  const rideXY = (b) => {
    const p = elXY(0, TL + ' .vz-playhead', .5, 1), y = elXY(0, TL, .5, 1)[1] + PADS() + 46, e = E.in(clamp((b - CX) / .45));
    return [p[0] + 240 * e, y];
  };
  // b56.8–57.4 (330, 540) → under the playhead around the card's lower-left corner: y leads (56.8–57.2), x follows
  // (56.95–57.4), so the dot drops past the card's left edge and turns along its bottom instead of cutting across its rows
  const toRide = (b) => { const R = rideXY(b); return [lerp(MERGE[0], R[0], io(b, 56.95, .45)), lerp(MERGE[1], R[1], io(b, 56.8, .4))]; };
  // 开始生成's centre where placeBtn puts it (run card header, 18 px in, 16 px down) — still valid after b69.05, when the
  // button goes back to the task card (its size is kept from before)
  let BW = [150, 46];
  const btnXY = (b) => {
    const D = decks[1].D, rc = D && runCard(D); if (!rc) return HOME;
    const el = b < BOFF && startBtn(D); if (el) { const r = el.getBoundingClientRect(); if (r.width) BW = [r.width, r.height]; }
    // v18.2: the tip lands 70 % across the (now large) button, right of its label, so the pointer never covers 开始生成
    const c = rc.getBoundingClientRect(); return stageXY(1, c.right - 18 - BW[0] * .3, c.top + 16 + BW[1] / 2);
  };
  const genXY = () => { const p = skillEdge(); return [p[0] - 56, p[1]]; };
  // b74.1–75.2 the return to the centre starts from where the generator was at b74.1 (held, not live): the cards then shrink
  // about the dot and travel with it, so a live genXY would already be at the centre by ≈ b74.8 and the dot would sit still
  // there for almost a beat; held, it lands on (960, 540) exactly at the b75.2 hand-off (E.inOut, zero speed both ends)
  let G0 = null;
  const backXY = (b) => { if (!G0) G0 = genXY(); return mix(G0, HOME, io(b, BACK, 1.3)); };
  // v17.7: on 开始生成 the dot is a pointer (rot −28, tip up): its TIP, not its centre, lands on the button centre. The
  // pointer's tip sits 1.25·(1 + .6·.9)·1.15 = 2.21 r from the centre toward −118° (r 26 → (−27, −50.9) px), so the centre is
  // carried that far down-right of the button while the pointer forms (b67.4–68.65) and eased back out as it becomes the
  // generator (b69.0–69.6): continuous, the hand-off positions are unchanged
  const PTR = [27, 50.9], ptrE = (b) => io(b, 67.4, 1.25) - io(b, 69.0, .6);
  // b69.0–69.6 button → generator: a straight line would cut across the run card's step list, so x leads (the dot runs
  // left along the header, lifted over the card's top edge) and y follows once it is past the card's left edge
  // v18.1: only SKILL.md is shown, so the generator sits 56 px left of its code block; button → there in one eased glide
  // (the camera moves from the button to SKILL.md over the same beats)
  const toGen = (b) => mix(btnXY(b), genXY(), io(b, 69.0, .9));
  let MB = -1, MP = MERGE;                                  // per-frame memo: the live params are read 5× a frame
  const mergeXY = (b) => {
    if (b === MB) return MP; MB = b; if (b < BACK) G0 = null;
    const q = b < 56.8 ? MERGE : b >= 75.2 ? HOME
      : b < 67.4 ? toRide(b)
      : b < 68.95 ? mix(rideXY(b), btnXY(b), io(b, 67.4, 1.25))
      : b < BACK ? toGen(b)
      : backXY(b);
    const e = b >= 67.4 && b < 69.6 ? ptrE(b) : 0;
    // v18.2 hover: the pointer sinks 3 px onto the button over the .3 beat before the press, and lets go after it
    const sk = 3 * (io(b, HOV, .3) - io(b, PRESS + .05, .2));
    return MP = e || sk ? [q[0] + PTR[0] * e, q[1] + PTR[1] * e + sk] : q;
  };
  const mergeR = (b) => b < 69.0 ? lerp(44, 26, io(b, 56.8, .6)) : b < BACK ? lerp(26, 36, io(b, 69.0, .6)) : lerp(36, 40, io(b, BACK, 1.3));
  // v17.7 hand-off: the column closes in 1.0 beat (stag .03) and dots 1–4 fade as they slip under cc (b55.3–55.75), so
  // their logos never stack half-offset under it; the orb forms b55.72–56.12 and is whole before the b56.2 pill. Their a
  // comes back at b56.4–56.5, where the merge already hides them, so 60-close's split blends from visible dots
  // hand-off QA v18.1: fade b55.15–55.5 (was 55.3–55.75) — with the orb forming from b55.3 the stack under it still read
  // as four extra discs below the orb at b55.4–55.6 (film 86.4–86.6); now they are gone before the orb is whole
  const mergeA = (b, i) => i ? 1 - io(b, 55.15, .35) + io(b, 56.4, .1) : 1;
  AGD.key(55.0, 'merge', { x: (b) => mergeXY(b)[0], y: (b) => mergeXY(b)[1], r: (b) => mergeR(b), a: mergeA, dur: 1.0, stag: .03 });

  /* ---------- top copy: three lines, swapped in place at 5.4, out at b74.4 ---------- */
  const sw = (a, b) => '<span class="sw"><span>' + a + '</span><span>' + b + '</span></span>';
  // slower rise (1.2 beats) and swap (.75); the block keeps a slow push (+.3 % / beat) instead of a dead hold
  // v18.2 the swap is sequential, not a cross: the old line leaves in .3 beat (E.in, up 20 px, blur 8) and the new one comes
  // in .25 beat after the old one started leaving (.55 beat, E.out, from 20 px below, blur 8 → 0): never two lines on top
  const seq = (at) => (el, tl) => el.querySelectorAll('.sw').forEach((s) => {
    const [a, n] = s.children, po = E.in(clamp((tl - BB(at)) / BB(.3))), pi = E.out(clamp((tl - BB(at + .25)) / BB(.55)));
    const set = (w, q, dy) => { w.style.opacity = q.toFixed(3); w.style.transform = 'translate(-50%,' + dy.toFixed(1) + 'px)'; w.style.filter = q < .999 ? 'blur(' + ((1 - q) * 8).toFixed(1) + 'px)' : 'none'; };
    set(a, 1 - po, -20 * po); set(n, pi, 20 * (1 - pi));
    s.style.width = Math.max(a.offsetWidth, n.offsetWidth) + 'px'; s.style.height = a.offsetHeight + 'px';
  });
  const line = (b0, cls, a, b, y, swapAt) => txt(b0, 75.0, [[cls + ' t5s', sw(a, b)]], { x: 960, y, align: 'c' },
    { anim: K.all(mask(0, 1.2, .6), seq(swapAt - b0)),
      tick: (el, tl) => { el.style.transform = 'translate(-50%,-50%) scale(' + (1 + .003 * (tl / BEAT + b0 - 56.4)).toFixed(4) + ')'; } });
  line(56.4, 'eb t5e', '03 · 会话轨迹', '04 · 生成工坊', 110, 67.3);
  line(56.6, 'hv sv t5h', '回放每一次协作', '交给本地 Agent，写成 Skill', 190, 67.45);
  line(57.0, 'lt acc t5o', '卡在哪一步，一眼看清', '边写边验', 270, 67.6);

  /* ---------- 5.2–5.3 trajectory (deck 0, b55.09–68.2) ----------
     v18.1: only the timeline itself is shown (svg.vz-t-timeline on its own white panel, promo-card), framed ≈ 1300 px wide (QA: 1440 cut the panel at the right edge)
     (640 frame px × 2.25): lane names and axis (11 px) read at ≈ 25 px, phase labels (10 px) at ≈ 22 px. The whole card
     (930 × 414) would not fit at that size. The panel sits right of the merged orb (its left edge ≈ 70 px right of it) and
     grows out of the orb: the camera is anchored on the orb's screen point (330, 540) and scales .94 → 1 about it. */
  const TL = '.tl-card svg.vz-t-timeline', PH = (D) => D.querySelector(TL + ' .vz-playhead');
  const panel = () => { const el = find(0, TL); if (el) el.classList.add('promo-solo', 'promo-card'); };
  tween(0, 55.09, 0, { o: 0 });                             // 40-recs takes deck 0 to o 0 at b55.08 (its OUT4 − .02)
  at(55.09, () => {
    advLight(0); const a = app(0); a.go('sessions');
    if (a.S.sess.playing) a.W.eval('stopPlay()');
    a.S.sess.ph = 0; a.W.eval('tlFrame(false)'); solo(0, TL); panel();
  });
  let PAN = 0;                                              // frame px the camera drifts with the playhead
  const TW = 1300, TLX = 400, TCY = 652;                    // timeline width / left edge / centre y on screen at rest
  const trajCam = () => {
    const r = rectOf(0, TL), s = Math.min(TW / r.w, 2.4); PAN = r.w * .035;
    const cx = TLX + r.w * s / 2, x = r.x + r.w / 2 - PAN + (MERGE[0] - cx) / s, y = r.y + r.h / 2 + (MERGE[1] - TCY) / s;
    return { x, y, s, ax: MERGE[0], ay: MERGE[1], rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0 };
  };
  // grows from the orb (left): s .94 → 1 about the orb's point while it clears (b55.09–56.4, E.out); no slide from the right
  // QA: opacity is left to the separate fade below (with o here the E.out tween had the panel half-visible under the % at b55.2)
  tween(0, 55.09, 1.31, () => { const c = trajCam(); delete c.o; return c; }, E.out, (T) => ({ s: T.s * .94, bl: 6 }));
  // its opacity on a slower in-out (.1 at b55.4, whole by b56.1) so it does not stack on 40-recs' fading % payoff
  // QA: starts at b55.35 (film 86.25), once 40-recs' % payoff has cleared — earlier the half-faded panel sat under it
  tween(0, 55.35, .8, { o: 1 }, E.inOut);
  // then the slow drift with the playhead (2 · PAN left) and a 3 % push about the orb's point
  tween(0, 56.6, 11.0, () => ({ x: decks[0].C.x + 2 * PAN, s: decks[0].C.s * 1.03 }), E.sine);
  // the merged dot owns this session: a thin wire to the panel's left edge, drawn .5 beat and taken back by b57.3 as the dot
  // leaves for the playhead (T11′)
  const panelL = () => { const p = elXY(0, TL, 0, .5); return [p[0] - PADS(), p[1]]; };
  AGD.link(56.4, 57.3, 0, panelL, { color: WIRE, width: 1.5, draw: .5, out: .3 });
  // the failing deploy (crit, playhead 24 → 36 min over b62.3–65.0): the riding dot glows once while its pill is up
  AGD.glow(0, 62.65, 63.95, .8);
  // playhead through the five phases (0–6–9–24–36–42 min): one smooth monotone curve through the phase knots (no stop at
  // a knot). v17.5: each pill is readable (pop .3 beat done → next knot) for: 探索 1.9 (it pops at b55.4 while the card
  // lands, readable from b55.9), 规划 1.9, 实施 2.0, 部署 2.4 (the key line), 验证 1.8 until the conveyor (b67.1); the
  // playhead never stops (slower inside the long phases) and is still creeping when the card leaves
  const KN = [[55.9, 0], [57.8, 6], [60.0, 9], [62.3, 24], [65.0, 36], [67.5, 42]];
  const KM = KN.map((k, i) => {                              // d3 monotoneX tangents; flat start, secant at the end
    if (i === 0) return 0;
    const s0 = (k[1] - KN[i - 1][1]) / (k[0] - KN[i - 1][0]); if (i === KN.length - 1) return s0;
    const h0 = k[0] - KN[i - 1][0], h1 = KN[i + 1][0] - k[0], s1 = (KN[i + 1][1] - k[1]) / h1, p = (s0 * h1 + s1 * h0) / (h0 + h1);
    return (Math.sign(s0) + Math.sign(s1)) * Math.min(Math.abs(s0), Math.abs(s1), .5 * Math.abs(p));
  });
  const phAt = (b) => {
    if (b <= KN[0][0]) return 0;
    for (let i = 1; i < KN.length; i++) if (b <= KN[i][0]) {
      const [b0, v0] = KN[i - 1], [b1, v1] = KN[i], h = b1 - b0, u = (b - b0) / h, u2 = u * u, u3 = u2 * u;
      return (2 * u3 - 3 * u2 + 1) * v0 + (u3 - 2 * u2 + u) * h * KM[i - 1] + (3 * u2 - 2 * u3) * v1 + (u3 - u2) * h * KM[i];
    }
    return 42;
  };
  const PHASES = [[0, '探索', ''], [6, '规划', ''], [9, '实施 · 纠偏 2 次', 'warn'], [24, '部署 · 连续失败 4 次', 'crit'], [36, '验证 ✓', 'good']];
  const phaseOf = (m) => PHASES.filter((x) => m >= x[0] - .01).pop();
  // the route change re-renders the timeline (keep it on its panel) and plays the page's own enter fades, which would hide
  // the first .35 beat of the growth from the orb: they are finished at once
  drive(0, 55.09, 55.4, () => { panel(); decks[0].D.getAnimations().forEach((x) => { if (isFinite(x.effect?.getComputedTiming().endTime)) x.finish(); }); });
  drive(0, 55.4, 67.6, (p, b) => { const a = app(0); a.S.sess.ph = Math.min(41.95, phAt(b)); a.W.eval('tlFrame(true)'); panel(); });
  // each phase pill pops in over .3 beat (rise + scale from .9), then stays readable ≥ 1.8 beats while it rides the playhead
  tag(0, 55.4, 67.75, PH, 'top', [['', '<span class="mt-ph"><i></i><b></b></span><span class="mt-stem"></span>']], {
    at: .5, gap: 10, anim: (el, tl, life, t) => {
      const b = t / BEAT, f = phaseOf(phAt(b)), pill = el.querySelector('.mt-ph');
      if (el.dataset.p !== f[1]) { el.dataset.p = f[1]; pill.className = 'mt-ph ' + f[2]; pill.querySelector('b').textContent = f[1]; el._t = b; }
      const k = E.out(clamp((b - (el._t ?? b)) / .3)), q = exitQ(tl, life, .45), inn = E.out(clamp(tl / BB(.5)));
      pill.style.transform = 'translateY(' + ((1 - k) * 22).toFixed(1) + 'px) scale(' + (.9 + .1 * k).toFixed(3) + ')'; pill.style.opacity = (Math.min(1, .2 + k) * q * inn).toFixed(3);
      el.querySelector('.mt-stem').style.opacity = (q * inn).toFixed(3); fixTag(el);
    }
  });
  // v18.1: a phase the pin has left stays behind as a small chip at .45 over the middle of its own band (the app's .vz-phase,
  // same order as PHASES), sitting on the panel's top edge under the live pill's stem: the five phases read as a trail.
  // Each chip fades in (.4 beat) as the next phase's pill pops at the following knot
  PHASES.slice(0, 4).forEach((f, i) => {
    const band = (D) => {
      const e = D.querySelectorAll(TL + ' .vz-phase')[i], sv = D.querySelector(TL); if (!e || !sv) return null;
      const r = e.getBoundingClientRect(), t = sv.getBoundingClientRect(), x = r.left + r.width / 2;
      return { getBoundingClientRect: () => ({ left: x, right: x, top: t.top, bottom: t.top, width: 0, height: 0 }) };
    };
    tag(0, KN[i + 1][0], 67.75, band, 'top', [['', '<span class="mt-ph gh ' + f[2] + '"><i></i><b>' + f[1].split(' ')[0] + '</b></span>']], {
      at: .5, gap: 6, anim: (el, tl, life) => {
        const k = E.out(clamp(tl / BB(.4))), q = exitQ(tl, life, .45);
        el.style.opacity = (.45 * k * q).toFixed(3); fixTag(el);
      }
    });
  });
  // 5.4 v18.2: the card leaves with the old title (b67.3, .45 beat, E.in): 240 px left, blur 10, gone — a short clean exit
  // instead of the 1-beat diagonal that left a grey blurred slab crossing the frame; its pills go with it (until b67.75)
  tween(0, CX, .45, () => { const C = decks[0].C; return { ax: C.ax - 240, bl: 10 }; }, E.in);
  // QA v18.2: α on its own shorter in-out (.35 beat) — with α on the same E.in the card was still ≈ .7 opaque at blur 7–10
  // (b67.65–67.75) and read as a grey slab for 3–4 frames; now it is mostly gone before the blur builds up
  tween(0, CX, .35, { o: 0 }, E.inOut);

  /* ---------- 5.4–5.7 studio (deck 1, b56.1–75.2) ---------- */
  const runCard = (D) => { const s = D.querySelector('#main .st-steps'); return s ? s.closest('.card') : D.querySelectorAll('#main .card.pad.col')[1]; };
  const skillCard = (D) => { const s = D.querySelector('#main .st-acts'); return s ? s.closest('.card') : smallest(D, '#main .card.col', 'SKILL.md'); };
  const startBtn = (D) => D.querySelector('#main [data-act="studioStart"]');   // sits in the task card; shown on its own
  const SOLO1 = [skillCard, startBtn];                   // v18.1: SKILL.md alone (no side-by-side run card)
  const remark1 = () => { for (const s of SOLO1) { const el = find(1, s); if (el) el.classList.add('promo-solo'); } };
  let SR = null;                                            // run + SKILL.md cards as they are once the run is done (frame px)
  tween(1, 56.0, 0, { o: 0 });
  at(56.1, () => {
    advLight(1); const a = app(1); a.W.eval('clearTimeout(RUNT)');
    Object.assign(a.S.studio, { run: null, agent: 'cc', type: 'Skill', tpl: 'v1' });   // the app's defaults: Claude Code writes a Skill
    a.go('studio');
    // both cards grow while the run writes (steps, log, SKILL.md lines): frame them at their final size, measured unseen
    a.S.studio.run = { tpl: 'v1', pos: 5, step: 5, lines: 14, log: ['›', '›', '›', '›', '›', '›', '›', '›'], done: true, stopped: false, installed: null };
    a.W.refreshStudio(); SR = rectOf(1, skillCard);
    if (!decks[1].D.getElementById('promoX')) { const st = decks[1].D.createElement('style'); st.id = 'promoX'; st.textContent = '.promo-x .promo-solo{box-shadow:none!important}'; decks[1].D.head.appendChild(st); }
    a.S.studio.run = null; a.W.refreshStudio(); solo(1, SOLO1);
  });
  // 开始生成 lives in the task card (left column, not shown): until the click it is moved onto the run card's header, where
  // the app puts the 停止 button once the run starts (re-applied every frame: the app re-renders #main)
  // position: fixed — a translate left it inside the task card, whose overflow: auto clipped it away (it was never seen)
  let BN = null;                                            // the button's own size, measured once in its row
  const BTN0 = ['position', 'left', 'top', 'width', 'height', 'zIndex', 'margin', 'transition', 'transform', 'boxShadow', 'transformOrigin'];
  const placeBtn = () => {
    const D = decks[1].D, b = startBtn(D), rc = runCard(D); if (!b || !rc) return;
    if (!BN || b.style.position !== 'fixed') { BTN0.forEach((k) => { b.style[k] = ''; }); const r = b.getBoundingClientRect(); if (!BN && r.width) BN = [r.width, r.height]; }
    if (!BN) return;
    const c = rc.getBoundingClientRect();
    Object.assign(b.style, { transition: 'none', position: 'fixed', zIndex: '3', margin: '0', width: BN[0] + 'px', height: BN[1] + 'px',
      left: (c.right - 18 - BN[0]).toFixed(1) + 'px', top: (c.top + 16).toFixed(1) + 'px' });
    b.classList.add('promo-solo');
  };
  // after the press the app's own 停止 takes its place in the header: the (now disabled) button fades out .15–.3 beat after
  // the click, then goes back to the task card unseen
  // v18.2 a real press: .3 beat of hover first (the face lightens, a white tint over the dark primary fill), then at the
  // click the button dips to .94 (.06 beat) and springs back (.14 beat) before it gives way to 停止
  // the pressed button stays on as the camera pulls away and fades with it (b69.0–69.4, E.in), so the press bloom never
  // hangs on bare black
  const btnFx = (b) => {
    placeBtn(); const el = startBtn(decks[1].D); if (!el) return;
    el.style.opacity = (1 - E.in(clamp((b - 69.0) / (BOFF - 69.0)))).toFixed(3);
    const h = io(b, HOV, .3), d = E.out(clamp((b - PRESS) / .06)) - E.inOut(clamp((b - PRESS - .06) / .14));
    // the press itself: an orange ring leaves the button's edge (0 → 4 frame px ≈ 22 px on screen, .6 beat) instead of a bloom disc over the label
    const rp = clamp((b - PRESS) / .6), ring = b >= PRESS ? 'rgba(242,122,72,' + (.8 * (1 - E.out(rp))).toFixed(3) + ') 0 0 0 ' + (4 * E.out(rp)).toFixed(2) + 'px' : '';
    const hv = h * (1 - io(b, PRESS + .1, .3)), tint = hv > .001 ? 'inset 0 0 0 999px rgba(255,255,255,' + Math.max(0, .15 * hv - .05 * d).toFixed(3) + ')' : '';
    // (inline !important: the solo rule sets box-shadow !important; its own edge + drop shadow are kept in the list)
    if (tint || ring) el.style.setProperty('box-shadow', [tint, ring, '0 0 0 .5px rgba(255,255,255,.14)', '0 30px 90px rgba(0,0,0,.55)'].filter(Boolean).join(','), 'important');
    else el.style.removeProperty('box-shadow');
    el.style.transformOrigin = '50% 50%'; el.style.transform = d > .001 ? 'scale(' + (1 - .06 * d).toFixed(4) + ')' : '';
  };
  drive(1, 56.15, BOFF, (p, b) => btnFx(b));
  // QA: SKILL.md stays hidden through the push-in (it sat cut off at the frame's right edge beside the button) and fades
  // in on the glide (b68.95–69.55)
  const skFx = (b) => { const el = skillCard(decks[1].D); if (el) el.style.opacity = clamp((b - 68.95) / .6).toFixed(3); };
  drive(1, 56.15, 69.6, (p, b) => skFx(b));
  at(69.6, () => { const el = skillCard(decks[1].D); if (el) el.style.opacity = ''; });
  at(BOFF, () => { SOLO1.pop(); const b = startBtn(decks[1].D); if (b) { b.classList.remove('promo-solo'); BTN0.forEach((k) => { b.style[k] = ''; }); b.style.opacity = ''; } });
  // v18.1 one shot: a push-in on 开始生成 alone (b67.3–68.8, the dot slides on and presses it), then the camera glides to
  // SKILL.md (b69.0–70.1), framed at 1.9× from its top edge: the frontmatter and step lines (11.5 px mono) read at ≈ 22 px;
  // the card's lower part (checks, actions) runs off the bottom of the frame
  // v18.2 framed 2.5× closer than before (s 2.3 → 5.5 → ×1.05): the 13 px label reads at ≈ 65 px and the button is the shot
  const BZ = 5.5;
  const btnCam = () => { const r = rectOf(1, startBtn); return { x: r.x + r.w / 2, y: r.y + r.h / 2, s: BZ, ax: 960, ay: 600, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0 }; };
  const studioCam = () => { const r = SR || rectOf(1, skillCard); return { x: r.x + r.w / 2, y: r.y, s: 1.9, ax: 1000, ay: 318, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0 }; };
  // in from the right as the card leaves to the left (mirrored, 240 px, a touch of depth; starts b67.75, once the card is
  // gone, so the button never lies over it), then a slow linear push 1 → 1.05 that is still moving through the hover and
  // the press (b68.55–69.05; the glide to SKILL.md takes over at b69.0)
  tween(1, CX + .45, .9, btnCam, E.quart, (T) => ({ ax: T.ax + 240, s: T.s * .9, o: 0, bl: 10 }));
  tween(1, 68.55, .5, () => ({ s: decks[1].C.s * 1.05 }), E.lin);
  tween(1, 69.0, 1.1, studioCam, E.inOut);
  // continuous push (+3 % over 3.8 beats, linear) so the file never holds still while it is written and read
  tween(1, 70.1, 3.8, () => ({ s: decks[1].C.s * 1.03 }), E.lin);
  // 5.5 the merged dot is the pointer: it has slid onto 开始生成 (mergeXY, b67.4–68.65) and presses it — no pointer; v18.2:
  // no bloom either (it sat on the label), the button itself hovers, dips and rings (drive above), and the dot dips (.88); the app's own timers are cleared, the run is driven below
  clickAt(1, 68.8, startBtn, (a, el) => { a.click(el); a.W.eval('clearTimeout(RUNT)'); remark1(); }, { cursor: false });
  AGD.pulse(0, 68.8, .88, .3);
  // 5.6 the app's run (v1: pack · analyse · draft · self-check · replay + judge · review), on the film's beats: ≥ .45 beat per
  // step, SKILL.md typed character by character at an even rate over b70.05–72.65 (2.6 beats; the finished file then reads
  // 1.45 beats before the exit), new log lines fade/rise in
  const RUN = [[68.95, 0], [69.45, 1], [69.95, 2], [72.85, 3], [73.3, 4], [73.75, 5]], L0 = 70.05, L1 = 72.65;
  let GL = null, GW = null;                                 // SKILL.md lines (code points) and cumulative typing weights
  const genW = () => {
    if (!GL) { GL = decks[1].W.eval('GEN[S.studio.type].lines.map((l) => l[0])').map((s) => [...s]); GW = [0]; GL.forEach((c) => GW.push(GW[GW.length - 1] + 2 + c.length)); }
    return GW;
  };
  drive(1, 68.8, 73.85, (p, b) => {
    const W = decks[1].W, D = decks[1].D, run = W.eval('S.studio.run'); if (!run) return;
    W.eval('clearTimeout(RUNT)');
    let k = run._k ?? -1;
    const k0 = k;
    while (k + 1 < RUN.length && b >= RUN[k + 1][0]) { k++; W.studioStep(RUN[k][1]); W.eval('clearTimeout(RUNT)'); }
    run._k = k;
    // QA v18.2: studioStep re-renders #main AFTER this frame's button / SKILL.md drives ran — at b68.95 the frame showed the
    // button gone and SKILL.md fully opaque at the frame's edge (one-frame pop); re-apply both on the new nodes
    if (k !== k0) { if (b < BOFF) btnFx(b); if (b < 69.6) skFx(b); }
    if (run.step === 2 && !run.done) {
      genW();
      const u = GW[GW.length - 1] * clamp((b - L0) / (L1 - L0));
      let i = 0; while (i < GL.length - 1 && u >= GW[i + 1]) i++;
      const n = u <= 0 ? 0 : u >= GW[GW.length - 1] ? GL.length : i + 1;
      if (n !== run.lines) { run.lines = n; W.refreshStudio(); }
      if (n && n < GL.length || n === GL.length && u < GW[GW.length - 1]) {   // the line being written: only its typed characters
        const rows = skillCard(D)?.querySelectorAll('.code > div'), t = rows && rows[n - 1]?.querySelector('.t');
        const c = Math.round(GL[n - 1].length * clamp((u - GW[n - 1] - 1) / Math.max(1, GL[n - 1].length)));
        if (t) t.textContent = GL[n - 1].slice(0, c).join('') || ' ';
      }
    }
    const L = run.log.length;
    if (run._ln == null) { run._ln = 0; run._ln0 = 0; run._lt = b; }
    if (L !== run._ln) { run._ln0 = run._ln; run._ln = L; run._lt = b; }
    const lg = D.querySelector('#studioLog');
    if (lg) [...lg.children].slice(1, 1 + L).forEach((d, j) => {
      if (j < run._ln0) return;
      const q = E.out(clamp((b - run._lt - (j - run._ln0) * .15) / .5));
      d.style.opacity = q.toFixed(3); d.style.transform = 'translateY(' + ((1 - q) * 8).toFixed(1) + 'px)';
    });
    remark1();                                              // refreshStudio replaced the solo cards this frame
  });
  // the merged dot is the generator: once it has backed off to 56 px left of the run card (b69.0–69.6), its wire grows from it
  // and carries pulses into the card while SKILL.md is written (no separate guide line: the dot itself was on the button)
  const skillEdge = () => elXY(1, (D) => skillCard(D)?.querySelector('.code') || skillCard(D), 0, .5);
  AGD.link(69.35, 73.9, 0, skillEdge, { color: '#fff', width: 2.5, pulse: 3, draw: .45, out: .3 });
  AGD.glow(0, 68.95, 73.75, 1);

  /* ---------- v17.7 the merged dot's shapes (STORYBOARD「v17.7」F3 5). Only dot 0 draws inside the merge; every shape keeps
     the five mini Agent badges (micro 1, no cc logo) so the merged dot always reads as「all five」. Each morph goes with the
     element it serves: wire → pill, playhead → pin, 开始生成 → pointer, SKILL.md → spark; back to 'dot' (= the orb while
     merged, so 60-close's split starts from a plain merge) when the generator is done. ---------- */
  const M5 = { micro: 1, la: 0, k: 1.15 };                  // the orb's size: the mini badges stay as large as in the orb
  // b56.25 the orb stretches into a pill aimed at the card's left edge as the wire is drawn out of its tip (b56.4–56.9)…
  // (g) v18.1: the orb takes over while dots 1–4 slip under cc (b55.3–55.75), so the logo → five-badge change reads as the
  // five dots going into one; from b55.75 it is one steady orb that goes straight into the pill (no cross-fade at b56.0–56.2)
  AGD.morph(55.3, 0, 'orb', { dur: .45 });
  AGD.morph(56.2, 0, 'pill', { ...M5, w: 2.6, aim: panelL, dur: .4 });
  // …and rounds back as the wire is taken back (b57.0–57.3) and the dot drops to the playhead
  AGD.morph(56.9, 0, 'dot', { dur: .35 });
  // b57.1 under the playhead it becomes a pin, tip up, its tip just touching the card's bottom edge (the dot rides 46 px
  // below it: 1.2 · (1 + .6 · .5) · 1.15 r = 1.79 × 26 ≈ 47 px). Before each phase pill pops (playhead knots 57.8 / 60.0 /
  // 62.3 / 65.0) the pin's tip pushes up into the card's margin (h 2.4 → 2.8 over .2 beat, back over .3) — it「pins」the phase.
  // While the deploy keeps failing (crit, b62.3–65.0) its outline turns warm orange (mixed, not swapped); no shake.
  const PINS = KN.slice(1, 5).map((k) => k[0]);
  const stab = (b) => Math.max(0, ...PINS.map((K) => io(b, K - .35, .2) - io(b, K - .15, .3)));
  AGD.morph(57.1, 0, 'pin', { ...M5, w: 1.8, h: (b) => 2.4 + .4 * stab(b), tip: .5, ly: .3, ring: 1.2,
    warm: (b) => io(b, 62.15, .35) - io(b, 64.8, .4), dur: .45 });
  // b67.6 on the way to 开始生成 the pin tilts into a pointer (rot −28, en route .6 beat); mergeXY carries its tip onto the
  // button centre. The b68.8 press is AGD.pulse(0, 68.8, .88, .3) below: the whole pointer dips and comes back
  AGD.morph(67.6, 0, 'pointer', { ...M5, ring: 1.2, dur: .6 });
  // b68.95 the pointer opens into the spark (the generator) as it backs off to the run card's left edge. Its five rays turn
  // slowly (kept short, .62: the run card is only 56 px away and its step list must stay clear); the one facing the card
  // (rayDir 0) lengthens each time the app starts a new SKILL.md line — the line starts
  // come from the app's own GEN lines and the typing schedule above (L0–L1, GW weights), soft .35-beat bumps
  const lineB = () => { const W = genW(), T = W[W.length - 1]; return W.slice(0, -1).map((w) => L0 + (L1 - L0) * (w + 1) / T); };
  let LB = null;
  const rayG = (b) => { LB = LB || lineB(); return .5 * AGD.beatPulse(b, LB, .35); };
  AGD.morph(68.95, 0, 'spark', { ...M5, rays: (b) => .62 * (io(b, 68.95, .5) - io(b, 73.75, .45)), rayDir: 0, rayGain: rayG, dur: .5 });
  // b73.75 done: the rays draw back in and it is the orb again, carried to the centre (b74.1–75.2) for 60-close
  AGD.morph(73.75, 0, 'dot', { dur: .5 });
  // 5.7 out (v18.1): at b73.9 the orb leaves for the centre (1.3 beats, E.inOut, lands on (960, 540) at the b75.2 hand-off)
  // and SKILL.md goes into it at once — the camera is re-anchored on the orb (same picture), the anchor travels with the orb,
  // and the card scales 1 → .7 about it, blurs 0 → 8 px and fades out over .8 beat (E.in). No static hold; the card's drop
  // shadow (the dark 'glass' slab under the blur) is taken off for the exit
  at(BACK, () => decks[1].D.documentElement.classList.add('promo-x'));
  at(75.25, () => decks[1].D.documentElement.classList.remove('promo-x'));
  tween(1, BACK, 0, () => { const C = decks[1].C, [px, py] = mergeXY(BACK); return { x: C.x + (px - C.ax) / C.s, y: C.y + (py - C.ay) / C.s, ax: px, ay: py }; });
  tween(1, BACK, 1.3, { ax: HOME[0], ay: HOME[1] }, E.inOut);
  // v18.2: the card is drawn INTO the orb — it shrinks to .6 about the orb's live point on an in-out (most of the shrink
  // happens while it is still clearly visible), and its blur and fade trail it (E.in), so it reads as swallowed, not faded
  tween(1, BACK, .9, () => ({ s: decks[1].C.s * .6 }), E.inOut);
  // QA v18.2: α on its own in-out (.7 beat) — on the blur's E.in the white card was still ≈ .5 opaque at blur 6–8 (b74.6–74.75)
  // and read as a translucent light slab; now it is nearly gone by the time the blur is heavy
  tween(1, BACK, .9, { bl: 8 }, E.in);
  tween(1, BACK, .7, { o: 0 }, E.inOut);
});

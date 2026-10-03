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
`);
  // tag() writes 'scale(k) translate(…)'; swapping the order keeps a counter-scaled tag on its edge (v16 50-montage)
  const fixTag = (el) => { el.style.transform = el.style.transform.replace(/^(scale\([^)]*\))\s*(translate\([^)]*\))$/, '$2 $1'); };
  const DIAG = [760, 430];                                  // conveyor push on screen (lower right → upper left), v16
  const advLight = (d) => { const W = decks[d].W; if (W.eval('S.ed') !== 'advance') W.eval("S.ed='advance';store.set('edition','advance');document.querySelector('#win').dataset.ed='advance'"); W.setTheme('light'); };
  const WIRE = 'rgba(255,255,255,.43)';                     // AGD draws links at stroke-opacity .7 → white 30 %

  /* ---------- 5.1 merge (b55.0–56.4) and the merged dot's path to the b75.2 hand-off (v17.1 V1, T11–T13) ----------
     ONE merge key with live x / y / r (a second merge key would fan the dots out again). The dot is where the eye is:
     (330, 540) (ds is already there, the column closes on it) → b56.8–57.4 under the playhead, then rides it (card
     bottom + 46) → b67.4–68.65 onto 开始生成 (it is the pointer; pressed at the b68.8 click) → b69.0–69.6 56 px left of the
     run card (the generator) → b74.1–75.2 screen centre (960, 540), where 60-close's spiral starts. All E.inOut. */
  const io = (b, b0, d) => E.inOut(clamp((b - b0) / d)), mix = (P, Q, e) => [lerp(P[0], Q[0], e), lerp(P[1], Q[1], e)];
  const MERGE = [330, 540], HOME = [960, 540];
  // under the playhead, card-fixed: the conveyor exit (b67.1, 1 beat, E.inOut, moves only ax / ay by −DIAG) is taken back out,
  // so the dot keeps riding the playhead's creep instead of being dragged up-left and then turning back to the button.
  // Right under the timeline the card's own status line (已发生 n / 143) and legend fill the space, so the dot rides 46 px
  // below the card's bottom edge at the playhead's x: it covers none of the app's text (T11′: pill above, dot below)
  const rideXY = (b) => {
    const p = elXY(0, TL + ' .vz-playhead', .5, 1), y = elXY(0, '.tl-card', .5, 1)[1] + 46, e = io(b, 67.1, 1.0);
    return [p[0] + DIAG[0] * e, y + DIAG[1] * e];
  };
  // b56.8–57.4 (330, 540) → under the playhead around the card's lower-left corner: y leads (56.8–57.2), x follows
  // (56.95–57.4), so the dot drops past the card's left edge and turns along its bottom instead of cutting across its rows
  const toRide = (b) => { const R = rideXY(b); return [lerp(MERGE[0], R[0], io(b, 56.95, .45)), lerp(MERGE[1], R[1], io(b, 56.8, .4))]; };
  // 开始生成's centre where placeBtn puts it (run card header, 18 px in, 16 px down) — still valid after b69.05, when the
  // button goes back to the task card (its size is kept from before)
  let BW = [150, 46];
  const btnXY = (b) => {
    const D = decks[1].D, rc = D && runCard(D); if (!rc) return HOME;
    const el = b < 69.05 && startBtn(D); if (el) { const r = el.getBoundingClientRect(); if (r.width) BW = [r.width, r.height]; }
    const c = rc.getBoundingClientRect(); return stageXY(1, c.right - 18 - BW[0] / 2, c.top + 16 + BW[1] / 2);
  };
  const genXY = () => { const p = runEdge(); return [p[0] - 56, p[1]]; };
  // b74.1–75.2 the return to the centre starts from where the generator was at b74.1 (held, not live): the cards then shrink
  // about the dot and travel with it, so a live genXY would already be at the centre by ≈ b74.8 and the dot would sit still
  // there for almost a beat; held, it lands on (960, 540) exactly at the b75.2 hand-off (E.inOut, zero speed both ends)
  let G0 = null;
  const backXY = (b) => { if (!G0) G0 = genXY(); return mix(G0, HOME, io(b, 74.1, 1.1)); };
  let MB = -1, MP = MERGE;                                  // per-frame memo: the live params are read 5× a frame
  const mergeXY = (b) => {
    if (b === MB) return MP; MB = b; if (b < 74.1) G0 = null;
    return MP = b < 56.8 ? MERGE : b >= 75.2 ? HOME
      : b < 67.4 ? toRide(b)
      : b < 68.95 ? mix(rideXY(b), btnXY(b), io(b, 67.4, 1.25))
      : b < 74.1 ? mix(btnXY(b), genXY(), io(b, 69.0, .6))
      : backXY(b);
  };
  const mergeR = (b) => b < 69.0 ? lerp(44, 26, io(b, 56.8, .6)) : b < 74.1 ? lerp(26, 36, io(b, 69.0, .6)) : lerp(36, 40, io(b, 74.1, 1.1));
  AGD.key(55.0, 'merge', { x: (b) => mergeXY(b)[0], y: (b) => mergeXY(b)[1], r: (b) => mergeR(b), dur: 1.2, stag: .05 });

  /* ---------- top copy: three lines, swapped in place at 5.4, out at b74.4 ---------- */
  const sw = (a, b) => '<span class="sw"><span>' + a + '</span><span>' + b + '</span></span>';
  // slower rise (1.2 beats) and swap (.75); the block keeps a slow push (+.3 % / beat) instead of a dead hold
  const line = (b0, cls, a, b, y, swapAt) => txt(b0, 75.0, [[cls, sw(a, b)]], { x: 960, y, align: 'c' },
    { anim: K.all(mask(0, 1.2, .6), K.swap({ at: [swapAt - b0], dur: .75, out: 0 })),
      tick: (el, tl) => { el.style.transform = 'translate(-50%,-50%) scale(' + (1 + .003 * (tl / BEAT + b0 - 56.4)).toFixed(4) + ')'; } });
  line(56.4, 'eb', '会话轨迹', '生成工坊', 110, 67.3);
  line(56.6, 'hv sv t5h', '回放每一次协作', '交给本地 Agent，写成 Skill', 190, 67.45);
  line(57.0, 'lt acc t5o', '卡在哪一步，一眼看清', '边写边验', 270, 67.6);

  /* ---------- 5.2–5.3 trajectory card (deck 0, b55.12–68.2; enters b55.2 while the dots still merge, H12) ---------- */
  const TL = '.tl-card svg.vz-t-timeline', PH = (D) => D.querySelector(TL + ' .vz-playhead');
  tween(0, 55.12, 0, { o: 0 });                             // 40-recs has faded deck 0 out by b55.1
  at(55.12, () => {
    advLight(0); const a = app(0); a.go('sessions');
    if (a.S.sess.playing) a.W.eval('stopPlay()');
    a.S.sess.ph = 0; a.W.eval('tlFrame(false)'); solo(0, '.tl-card');
  });
  let PAN = 0;                                              // frame px the camera drifts with the playhead
  const trajCam = () => { const T = framing(0, '.tl-card', [1100, 640, 1360, 560], { max: 1.6 }); PAN = rectOf(0, '.tl-card').w * .05; T.x -= PAN; T.mx = 0; return T; };
  tween(0, 55.2, 1.3, trajCam, E.quart, IN.fromR);
  tween(0, 56.6, 11.0, () => ({ x: decks[0].C.x + 2 * PAN, s: decks[0].C.s * 1.04 }), E.sine);
  // the merged dot owns this session: a thin wire to the card's left edge, drawn .5 beat and taken back by b57.3 as the dot
  // leaves for the playhead (T11′)
  AGD.link(56.4, 57.3, 0, () => elXY(0, '.tl-card', 0, .5), { color: WIRE, width: 1.5, draw: .5, out: .3 });
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
  drive(0, 55.4, 67.6, (p, b) => { const a = app(0); a.S.sess.ph = Math.min(41.95, phAt(b)); a.W.eval('tlFrame(true)'); });
  // each phase pill pops in over .3 beat (rise + scale from .9), then stays readable ≥ 1.8 beats while it rides the playhead
  tag(0, 55.4, 67.9, PH, 'top', [['', '<span class="mt-ph"><i></i><b></b></span><span class="mt-stem"></span>']], {
    at: .5, gap: 10, anim: (el, tl, life, t) => {
      const b = t / BEAT, f = phaseOf(phAt(b)), pill = el.querySelector('.mt-ph');
      if (el.dataset.p !== f[1]) { el.dataset.p = f[1]; pill.className = 'mt-ph ' + f[2]; pill.querySelector('b').textContent = f[1]; el._t = b; }
      const k = E.out(clamp((b - (el._t ?? b)) / .3)), q = exitQ(tl, life, .45), inn = E.out(clamp(tl / BB(.5)));
      pill.style.transform = 'translateY(' + ((1 - k) * 22).toFixed(1) + 'px) scale(' + (.9 + .1 * k).toFixed(3) + ')'; pill.style.opacity = (Math.min(1, .2 + k) * q * inn).toFixed(3);
      el.querySelector('.mt-stem').style.opacity = (q * inn).toFixed(3); fixTag(el);
    }
  });
  // 5.4 conveyor: the card leaves along the diagonal (1 beat, eased both ends) while the studio arrives from the opposite side
  tween(0, 67.1, 1.0, () => { const C = decks[0].C; return { ax: C.ax - DIAG[0], ay: C.ay - DIAG[1], o: 0, bl: 8, mx: 24 }; }, E.inOut);

  /* ---------- 5.4–5.7 studio (deck 1, b56.1–75.2) ---------- */
  const runCard = (D) => { const s = D.querySelector('#main .st-steps'); return s ? s.closest('.card') : D.querySelectorAll('#main .card.pad.col')[1]; };
  const skillCard = (D) => { const s = D.querySelector('#main .st-acts'); return s ? s.closest('.card') : smallest(D, '#main .card.col', 'SKILL.md'); };
  const startBtn = (D) => D.querySelector('#main [data-act="studioStart"]');   // sits in the task card; shown on its own
  const SOLO1 = [runCard, skillCard, startBtn];
  const remark1 = () => { for (const s of SOLO1) { const el = find(1, s); if (el) el.classList.add('promo-solo'); } };
  let SR = null;                                            // run + SKILL.md cards as they are once the run is done (frame px)
  tween(1, 56.0, 0, { o: 0 });
  at(56.1, () => {
    advLight(1); const a = app(1); a.W.eval('clearTimeout(RUNT)');
    Object.assign(a.S.studio, { run: null, agent: 'cc', type: 'Skill', tpl: 'v1' });   // the app's defaults: Claude Code writes a Skill
    a.go('studio');
    // both cards grow while the run writes (steps, log, SKILL.md lines): frame them at their final size, measured unseen
    a.S.studio.run = { tpl: 'v1', pos: 5, step: 5, lines: 14, log: ['›', '›', '›', '›', '›', '›', '›', '›'], done: true, stopped: false, installed: null };
    a.W.refreshStudio(); SR = rectOf(1, [runCard, skillCard]);
    a.S.studio.run = null; a.W.refreshStudio(); solo(1, SOLO1);
  });
  // 开始生成 lives in the task card (left column, not shown): until the click it is moved onto the run card's header, where
  // the app puts the 停止 button once the run starts (re-applied every frame: the app re-renders #main)
  const placeBtn = () => {
    const D = decks[1].D, b = startBtn(D), rc = runCard(D); if (!b || !rc) return;
    b.style.transition = 'none'; b.style.transform = ''; const r = b.getBoundingClientRect(), c = rc.getBoundingClientRect();
    b.style.transition = 'none'; b.style.position = 'relative'; b.style.zIndex = '3'; b.style.transform = 'translate(' + (c.right - 18 - r.right).toFixed(1) + 'px,' + (c.top + 16 - r.top).toFixed(1) + 'px)';
  };
  drive(1, 56.15, 69.05, placeBtn);
  at(69.05, () => { SOLO1.pop(); const b = startBtn(decks[1].D); if (b) { b.classList.remove('promo-solo'); b.style.transform = ''; } });
  // box [1100, 640, 1300, 600]: top edge y 340 and width kept; the cards then grow down into the free space below the box
  // (to y ≤ 1065 when done) instead of being shrunk to fit their final height into 600 px. The anchor sits 362 px below the
  // top edge (≈ the cards' middle when done), so the slow push below and the exit both scale about the middle
  const studioCam = () => {
    const r = SR || rectOf(1, [runCard, skillCard]), s = Math.min(1300 / r.w, 725 / r.h, 1.6);
    return { x: r.x + r.w / 2, y: r.y + 362 / s, s, ax: 1100, ay: 702, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0 };
  };
  tween(1, 67.3, 1.2, studioCam, E.quart, (T) => ({ ax: T.ax + DIAG[0], ay: T.ay + DIAG[1], o: 0, bl: 8, mx: 24 }));
  // continuous push (+3 % over 5.8 beats, linear) so the cards never hold still; bottom edge stays ≤ 1076
  tween(1, 68.3, 5.8, () => ({ s: decks[1].C.s * 1.03 }), E.lin);
  // 5.5 the merged dot is the pointer: it has slid onto 开始生成 (mergeXY, b67.4–68.65) and presses it — no pointer, only the
  // orange bloom, and the dot dips (.88) with the press; the app's own timers are cleared, the run is driven below
  clickAt(1, 68.8, startBtn, (a, el) => { a.click(el); a.W.eval('clearTimeout(RUNT)'); remark1(); }, { bloom: 'var(--a1)', cursor: false });
  AGD.pulse(0, 68.8, .88, .3);
  // 5.6 the app's run (v1: pack · analyse · draft · self-check · replay + judge · review), on the film's beats: ≥ .45 beat per
  // step, SKILL.md typed character by character at an even rate over b70.05–72.65 (2.6 beats; the finished file then reads
  // 1.45 beats before the exit), new log lines fade/rise in
  const RUN = [[68.95, 0], [69.45, 1], [69.95, 2], [72.85, 3], [73.3, 4], [73.75, 5]], L0 = 70.05, L1 = 72.65;
  let GL = null, GW = null;                                 // SKILL.md lines (code points) and cumulative typing weights
  drive(1, 68.8, 73.85, (p, b) => {
    const W = decks[1].W, D = decks[1].D, run = W.eval('S.studio.run'); if (!run) return;
    W.eval('clearTimeout(RUNT)');
    let k = run._k ?? -1;
    while (k + 1 < RUN.length && b >= RUN[k + 1][0]) { k++; W.studioStep(RUN[k][1]); W.eval('clearTimeout(RUNT)'); }
    run._k = k;
    if (run.step === 2 && !run.done) {
      if (!GL) { GL = W.eval('GEN[S.studio.type].lines.map((l) => l[0])').map((s) => [...s]); GW = [0]; GL.forEach((c) => GW.push(GW[GW.length - 1] + 2 + c.length)); }
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
  const runEdge = () => elXY(1, runCard, 0, .5);
  AGD.link(69.35, 74.3, 0, runEdge, { color: '#fff', width: 2.5, pulse: 3, draw: .45, out: .3 });
  AGD.glow(0, 68.95, 73.75, 1);
  // 5.7 out: the cards shrink into the dot, turn slightly and fade (clear by b75.1) while the dot returns to the centre. The
  // camera is first re-anchored on the dot (same picture: the frame point under the dot becomes the anchor), then the anchor
  // travels with the dot to (960, 540) on the dot's own curve (1.1 beats, E.inOut: the dot stays on the anchor); the cards
  // shrink to .4 about it so they visibly go into the dot rather than just fading in place; the copy leaves at b74.4
  tween(1, 74.1, 0, () => { const C = decks[1].C, [px, py] = mergeXY(74.1); return { x: C.x + (px - C.ax) / C.s, y: C.y + (py - C.ay) / C.s, ax: px, ay: py }; });
  tween(1, 74.1, 1.1, { ax: HOME[0], ay: HOME[1] }, E.inOut);
  tween(1, 74.1, 1.0, () => { const C = decks[1].C; return { s: C.s * .4, rz: C.rz - 8, o: 0, bl: 8 }; }, E.inOut);
});

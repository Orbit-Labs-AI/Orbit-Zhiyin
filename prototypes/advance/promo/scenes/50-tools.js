/* 50-tools 5（b55.0–70.0） — STORYBOARD.md v17「5 会话轨迹 + 生成工坊」.
   5.1 竖列的 5 个点合并为一（AGD merge 220, 540）→ 5.2–5.3 会话轨迹卡（deck 0）播放头走过 5 个阶段，合并点细线连到卡 →
   5.4 传送带换成生成工坊（deck 1）→ 5.5 光标点「开始生成」→ 5.6 SKILL.md 一行行写出，合并点（cc 在上）到运行卡的线变亮、
   流动 → 5.7 工坊卡缩小轻转淡出。b68.9 起 60-close 从合并点展开（与工坊卡淡出重叠）。
   旧镜头（.mt-ph 胶囊、播放头、DIAG 传送带）来自 git show 78841089^:prototypes/advance/promo/scenes/50-montage.js。
   生成过程用 App 自己的 studioStep / refreshStudio，但按成片拍逐帧推进（App 自带的定时器约 8 秒跑完，这里压到 b63.35–67.6）。 */
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

  /* ---------- 5.1 merge (b55.0–56.4) ---------- */
  AGD.key(55.0, 'merge', { x: 220, y: 540, r: 44, dur: 1.2, stag: .05 });

  /* ---------- top copy: three lines, swapped in place at 5.4, out at b68.4 ---------- */
  const sw = (a, b) => '<span class="sw"><span>' + a + '</span><span>' + b + '</span></span>';
  const line = (b0, cls, a, b, y, swapAt) => txt(b0, 69.0, [[cls, sw(a, b)]], { x: 960, y, align: 'c' },
    { anim: K.all(mask(0, .9, .6), K.swap({ at: [swapAt - b0], dur: .45, out: 0 })) });
  line(56.4, 'eb', '会话轨迹', '生成工坊', 110, 61.7);
  line(56.6, 'hv sv t5h', '回放每一次协作', '交给本地 Agent，写成 Skill', 190, 61.85);
  line(57.0, 'lt acc t5o', '卡在哪一步，一眼看清', '边写边验', 270, 62.0);

  /* ---------- 5.2–5.3 trajectory card (deck 0, b55.12–62.2; enters b55.4 while the dots still merge, H12) ---------- */
  const TL = '.tl-card svg.vz-t-timeline', PH = (D) => D.querySelector(TL + ' .vz-playhead');
  tween(0, 55.12, 0, { o: 0 });                             // 40-recs has faded deck 0 out by b55.1
  at(55.12, () => {
    advLight(0); const a = app(0); a.go('sessions');
    if (a.S.sess.playing) a.W.eval('stopPlay()');
    a.S.sess.ph = 0; a.W.eval('tlFrame(false)'); solo(0, '.tl-card');
  });
  let PAN = 0;                                              // frame px the camera drifts with the playhead
  const trajCam = () => { const T = framing(0, '.tl-card', [1100, 640, 1360, 560], { max: 1.6 }); PAN = rectOf(0, '.tl-card').w * .05; T.x -= PAN; T.mx = 0; return T; };
  tween(0, 55.4, 1.0, trajCam, E.quart, IN.fromR);
  tween(0, 57.0, 4.6, () => ({ x: decks[0].C.x + 2 * PAN, s: decks[0].C.s * 1.04 }), E.sine);
  // the merged dot owns this session: a thin wire to the card's left edge
  AGD.link(56.4, 61.9, 0, () => elXY(0, '.tl-card', 0, .5), { color: WIRE, width: 1.5, draw: .4, out: .3 });
  // playhead through the five phases (0–6–9–24–36–42 min), ~.9 beat each, .4 more at the failing deploy
  const KN = [[57.0, 0], [57.8, 6], [58.6, 9], [59.4, 24], [59.8, 25], [60.8, 36], [61.5, 42]];
  const phAt = (b) => { if (b <= KN[0][0]) return 0; for (let i = 1; i < KN.length; i++) if (b <= KN[i][0]) { const [b0, v0] = KN[i - 1], [b1, v1] = KN[i]; return lerp(v0, v1, E.sine((b - b0) / (b1 - b0))); } return 42; };
  const PHASES = [[0, '探索', ''], [6, '规划', ''], [9, '实施 · 纠偏 2 次', 'warn'], [24, '部署 · 连续失败 4 次', 'crit'], [36, '验证 ✓', 'good']];
  const phaseOf = (m) => PHASES.filter((x) => m >= x[0] - .01).pop();
  drive(0, 56.9, 61.6, (p, b) => { const a = app(0); a.S.sess.ph = Math.min(41.95, phAt(b)); a.W.eval('tlFrame(true)'); });
  tag(0, 57.0, 61.9, PH, 'top', [['', '<span class="mt-ph"><i></i><b></b></span><span class="mt-stem"></span>']], {
    at: .5, gap: 10, anim: (el, tl, life, t) => {
      const b = t / BEAT, f = phaseOf(phAt(b)), pill = el.querySelector('.mt-ph');
      if (el.dataset.p !== f[1]) { el.dataset.p = f[1]; pill.className = 'mt-ph ' + f[2]; pill.querySelector('b').textContent = f[1]; el._t = b; }
      const k = E.out(clamp((b - (el._t ?? b)) / .25)), q = exitQ(tl, life, .3), inn = E.out(clamp(tl / BB(.35)));
      pill.style.transform = 'translateY(' + ((1 - k) * 18).toFixed(1) + 'px)'; pill.style.opacity = (Math.min(1, .35 + k) * q * inn).toFixed(3);
      el.querySelector('.mt-stem').style.opacity = (q * inn).toFixed(3); fixTag(el);
    }
  });
  // 5.4 conveyor: the card leaves along the diagonal while the studio arrives from the opposite side
  tween(0, 61.6, .6, () => { const C = decks[0].C; return { ax: C.ax - DIAG[0], ay: C.ay - DIAG[1], o: 0, bl: 8, mx: 30 }; }, E.in);

  /* ---------- 5.4–5.7 studio (deck 1, b56.1–69.2) ---------- */
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
  drive(1, 56.15, 63.45, placeBtn);
  at(63.45, () => { SOLO1.pop(); const b = startBtn(decks[1].D); if (b) { b.classList.remove('promo-solo'); b.style.transform = ''; } });
  // box [1100, 640, 1300, 600]: top edge y 340 and width kept; the cards then grow down into the free space below the box
  // (to y ≤ 1065 when done) instead of being shrunk to fit their final height into 600 px
  const studioCam = () => {
    const r = SR || rectOf(1, [runCard, skillCard]), s = Math.min(1300 / r.w, 725 / r.h, 1.6);
    return { x: r.x + r.w / 2, y: r.y, s, ax: 1100, ay: 340, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0 };
  };
  tween(1, 61.7, .9, studioCam, E.quart, (T) => ({ ax: T.ax + DIAG[0], ay: T.ay + DIAG[1], o: 0, bl: 8, mx: 30 }));
  tween(1, 62.6, 5.6, () => ({ s: decks[1].C.s * 1.015 }), E.sine);
  // 5.5 the pointer glides to 开始生成 and presses it (orange bloom); the app's own timers are cleared, the run is driven below
  clickAt(1, 63.2, startBtn, (a, el) => { a.click(el); a.W.eval('clearTimeout(RUNT)'); remark1(); }, { bloom: 'var(--a1)', glide: .8 });
  // 5.6 the app's run (v1: pack · analyse · draft · self-check · replay + judge · review), on the film's beats
  const RUN = [[63.35, 0], [63.7, 1], [64.05, 2], [66.45, 3], [66.95, 4], [67.6, 5]], L0 = 64.15, L1 = 66.3;
  drive(1, 63.2, 67.7, (p, b) => {
    const W = decks[1].W, run = W.eval('S.studio.run'); if (!run) return;
    W.eval('clearTimeout(RUNT)');
    let k = run._k ?? -1;
    while (k + 1 < RUN.length && b >= RUN[k + 1][0]) { k++; W.studioStep(RUN[k][1]); W.eval('clearTimeout(RUNT)'); }
    run._k = k;
    if (run.step === 2 && !run.done) {
      const n = Math.round(W.eval('GEN[S.studio.type].lines.length') * clamp((b - L0) / (L1 - L0)));
      if (n !== run.lines) { run.lines = n; W.refreshStudio(); }
    }
    remark1();                                              // refreshStudio replaced the solo cards this frame
  });
  // the merged dot is the generator: its wire to the run card brightens and carries pulses while SKILL.md is written
  const runEdge = () => elXY(1, runCard, 0, .5);
  AGD.link(62.5, 63.65, 0, runEdge, { color: WIRE, width: 1.5, draw: .4, out: .25 });
  AGD.link(63.4, 68.3, 0, runEdge, { color: '#fff', width: 2.5, pulse: 3, draw: .35, out: .3 });
  AGD.glow(0, 63.4, 67.6, 1);
  AGD.pulse(0, 63.3, 1.06, .5);
  // 5.7 out: shrink, slight turn, fade (deck 1 is clear by b69.1); the copy leaves at b68.4 (txt above)
  // E.inOut: E.in left the cards at o .5 at b69.0 and cut them to 0 within .2 beat; now they are nearly clear by b68.9, when the dots start to fan out (H13)
  tween(1, 68.1, 1.0, () => { const C = decks[1].C; return { s: C.s * .8, rz: C.rz - 8, o: 0, bl: 8, y: C.y + 360 / C.s, ay: C.ay + 360 }; }, E.inOut);   // about the cards' middle, not the top anchor
});

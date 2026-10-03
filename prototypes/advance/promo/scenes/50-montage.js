/* 其他功能（b83.6–93.5）：只留轨迹回放与生成工坊两项，各一个清楚的画面（问本地 Agent、桌面小组件、提醒、⌘K、
   Lite / Advance、深色模式不再出现）. Shots: STORYBOARD.md. Decks 0 / 1 take turns. */
scene('50-montage', () => {
  css(`
.mt-ph{display:inline-flex;align-items:center;gap:14px;font:600 44px var(--sans);color:#fff;padding:10px 26px 12px;border-radius:999px;background:rgba(10,11,13,.9);border:1px solid rgba(255,255,255,.22)}
.mt-ph i{width:14px;height:14px;border-radius:50%;background:#fff}
.mt-ph b{font-weight:600}
.mt-ph.warn b{color:#f3c56b}.mt-ph.warn i{background:#f3c56b}
.mt-ph.crit b{color:#ff8a7a}.mt-ph.crit i{background:#ff8a7a}
.mt-ph.good b{color:#7fd6a4}.mt-ph.good i{background:#7fd6a4}
.mt-stem{display:block;width:2px;height:34px;margin:0 auto;background:linear-gradient(rgba(255,255,255,.7),rgba(255,255,255,0))}
.mt-a1>span{color:var(--a1)}
.mt-sw .sw>span{color:var(--a1)}
.tag .ln.mt-eb{font-size:32px}
.tag .ln.mt-eb2{font-size:26px}
.tag .ln.mt-ed{font-size:64px}
`);
  // tag() writes 'scale(k) translate(…)', which scales about the anchor after moving the box away from it, so a
  // counter-scaled tag drifts off its edge; swapping the order keeps the anchor on the edge (see report)
  const fixTag = (el) => { el.style.transform = el.style.transform.replace(/^(scale\([^)]*\))\s*(translate\([^)]*\))$/, '$2 $1'); };
  const tg = (st, extra) => K.all(mask(st, .9, .5), fixTag, extra || (() => {}));
  const PLANE = { rx: 40, ry: 0, rz: -12, mx: 0 };              // the tilted plane both conveyor shots share
  const DIAG = [760, 430];                               // its push direction on screen (lower right → upper left)

  /* ---------- 6.1 trajectory on a tilted plane (deck 0, b83.6–88.9) ---------- */
  const TL = '.tl-card svg.vz-t-timeline', PH = (D) => D.querySelector(TL + ' .vz-playhead');
  // both copies are ours from b83: start from transparent cameras whatever the scenes before left behind
  tween(0, 83.0, 0, { o: 0 }); tween(1, 83.0, 0, { o: 0 });
  at(82.7, () => {
    const a = app(0); a.W.closeModal(); a.go('sessions');
    if (a.S.sess.playing) a.W.eval('stopPlay()');
    a.S.sess.ph = 0; a.W.eval('tlFrame(false)'); solo(0, '.tl-card');
  });
  // the playhead runs through the five phases of the featured session (0–6–9–24–36–42 min), each phase ≥ 0.6 beat
  const KN = [[84.2, 0], [84.8, 6], [85.4, 9], [86.2, 24], [87.2, 36], [88.0, 42]];
  const phAt = (b) => { if (b <= KN[0][0]) return 0; for (let i = 1; i < KN.length; i++) if (b <= KN[i][0]) { const [b0, v0] = KN[i - 1], [b1, v1] = KN[i]; return lerp(v0, v1, E.sine((b - b0) / (b1 - b0))); } return 42; };
  const PHASES = [[0, '探索', ''], [6, '规划', ''], [9, '实施 · 纠偏 2 次', 'warn'], [24, '部署 · 连续失败 4 次', 'crit'], [36, '验证 ✓', 'good']];
  const phaseOf = (m) => PHASES.filter((x) => m >= x[0] - .01).pop();
  drive(0, 83.4, 88.6, (p, b) => { const a = app(0); a.S.sess.ph = Math.min(41.95, phAt(b)); a.W.eval('tlFrame(true)'); });
  const trajCam = () => Object.assign(framing(0, TL, [960, 600, 1500, 700], { max: 1.6, px: .08 }), PLANE);
  tween(0, 83.6, .6, trajCam, E.quart, (T) => ({ ax: T.ax + DIAG[0], ay: T.ay + DIAG[1], o: 0, bl: 8, mx: 30 }));
  // the camera rides with the playhead (eased follow, so it starts calmly and catches up)
  drive(0, 84.2, 88.4, (p, b, D) => {
    const ph = PH(D); if (!ph) return; const r = ph.getBoundingClientRect(), C = decks[0].C;
    C.x = lerp(C.x, r.left + r.width / 2 + 120, .14); C.s = lerp(C.s, trajCam().s * 1.12, .03);
  });
  tag(0, 84.0, 86.4, '.tl-card', 'top', [['eb mt-eb', '03 · 轨迹回放'], ['md sv', '卡在哪一刻，一眼看清']], { at: 0, gap: 40, anim: tg(.25) });
  tag(0, 84.2, 88.5, PH, 'top', [['', '<span class="mt-ph"><i></i><b></b></span><span class="mt-stem"></span>']], {
    at: .5, gap: 10, anim: (el, tl, life, t) => {
      const b = t / BEAT, f = phaseOf(phAt(b)), pill = el.querySelector('.mt-ph');
      if (el.dataset.p !== f[1]) { el.dataset.p = f[1]; pill.className = 'mt-ph ' + f[2]; pill.querySelector('b').textContent = f[1]; el._t = b; }
      const k = E.out(clamp((b - (el._t ?? b)) / .25)), q = exitQ(tl, life, .3), inn = E.out(clamp(tl / BB(.35)));
      pill.style.transform = 'translateY(' + ((1 - k) * 18).toFixed(1) + 'px)'; pill.style.opacity = (Math.min(1, .35 + k) * q * inn).toFixed(3);
      el.querySelector('.mt-stem').style.opacity = (q * inn).toFixed(3); fixTag(el);
    }
  });
  // conveyor: the plane leaves along its own diagonal while the next one arrives behind it
  tween(0, 88.4, .55, () => { const C = decks[0].C; return { ax: C.ax - DIAG[0], ay: C.ay - DIAG[1], o: 0, bl: 8, mx: 30 }; }, E.in);

  /* ---------- 6.2 studio (deck 1, b88.4–92.25) ---------- */
  const runCard = (D) => D.querySelectorAll('#main .card.pad.col')[1];
  const skillCard = (D) => smallest(D, '#main .card.col', 'SKILL.md');
  // the run starts while deck 1 is still dark so SKILL.md is being written line by line (b88.4–92) when the plane arrives
  at(83.4, () => { const a = app(1); a.W.closeModal(); a.go('studio'); a.click('[data-act="studioStart"]'); solo(1, [runCard, skillCard]); });
  const studioCam = () => Object.assign(framing(1, [runCard, skillCard], [900, 600, 1300, 760], { max: 1.6 }), PLANE);
  tween(1, 88.45, .55, studioCam, E.quart, (T) => ({ ax: T.ax + DIAG[0], ay: T.ay + DIAG[1], o: 0, bl: 8, mx: 30 }));
  tween(1, 89.0, 3.7, () => { const C = decks[1].C; return { s: C.s * 1.06, ax: C.ax - 40, ay: C.ay - 20 }; }, E.sine);
  tag(1, 88.9, 92.8, skillCard, 'right', [['eb mt-eb', '生成工坊'], ['gap'], ['md sv', '交给本地 Agent'], ['md sv', '写成 Skill'], ['md mt-a1', '边写边验']], { gap: 46, anim: tg(.12) });

  /* ---------- 6.3 out: the studio drops back and fades as the close's compass turns in (b92.7–93.5) ---------- */
  tween(1, 92.7, .8, () => { const C = decks[1].C; return { s: C.s * .8, rz: C.rz - 12, o: 0, bl: 8 }; }, E.in);
});

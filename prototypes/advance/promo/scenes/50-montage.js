/* 其他功能快剪（b83.6–101.4）：轨迹回放 → 生成工坊 → 问本地 Agent → 「还有 ___」换词蒙太奇
   Shots, keyframes and hand-offs: STORYBOARD.md. Getting faster: trajectory 4.8 beats → studio 3.6 → Ask 4.4 →
   one word every 1.2 beats. Decks 0 / 1 take turns; #hole0 / #hole1 clip-paths are used for the dark-mode wipe. */
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
  tag(0, 84.0, 86.4, '.tl-card', 'top', [['eb', '03 · 轨迹回放'], ['md sv', '卡在哪一刻，一眼看清']], { at: 0, gap: 40, anim: tg(.25) });
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
  at(86.6, () => { const a = app(1); a.W.closeModal(); a.go('studio'); a.click('[data-act="studioStart"]'); solo(1, [runCard, skillCard]); });
  const studioCam = () => Object.assign(framing(1, [runCard, skillCard], [900, 600, 1300, 760], { max: 1.6 }), PLANE);
  tween(1, 88.45, .55, studioCam, E.quart, (T) => ({ ax: T.ax + DIAG[0], ay: T.ay + DIAG[1], o: 0, bl: 8, mx: 30 }));
  tween(1, 89.0, 3.0, () => { const C = decks[1].C; return { s: C.s * 1.06, ax: C.ax - 40, ay: C.ay - 20 }; }, E.sine);
  tag(1, 88.9, 92.1, skillCard, 'right', [['eb', '生成工坊'], ['gap'], ['md sv', '交给本地 Agent'], ['md sv', '写成 Skill'], ['md mt-a1', '边写边验']], { gap: 46, anim: tg(.12) });

  /* ---------- 6.3–6.4 3D whip → Ask (deck 1 out, deck 0 in, b92.0–95.4) ---------- */
  tween(1, 92.0, .25, () => { const C = decks[1].C; return { ry: C.ry - 70, ax: C.ax - 900, mx: 80, o: 0 }; }, E.in);
  const Q = '我上周为什么总在返工？';
  at(90.0, () => {
    const a = app(0); a.go('overview'); a.W.openAsk('persona'); solo(0, '#modal');
    const inp = a.D.querySelector('#askIn'); if (inp) { inp.value = ''; inp.focus(); }
  });
  const inRect = () => decks[0].D.querySelector('#askIn').getBoundingClientRect();
  const typedN = (b) => Math.min(Q.length, Math.max(0, Math.floor((b - 92.3) / 1.55 * Q.length + .001)));
  drive(0, 92.25, 94.0, (p, b, D) => { const i = D.querySelector('#askIn'); if (!i) return; const v = Q.slice(0, typedN(b)); if (i.value !== v) i.value = v; });
  // the caret: the input's left padding + the width of the typed text (measured once per value)
  const caretX = (D) => {
    const i = D.querySelector('#askIn'), r = i.getBoundingClientRect(), cs = getComputedStyle(i);
    const cv = caretX.cv || (caretX.cv = document.createElement('canvas').getContext('2d'));
    cv.font = cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
    return r.left + parseFloat(cs.paddingLeft) + cv.measureText(i.value).width;
  };
  const modalR = () => decks[0].D.querySelector('#modal').getBoundingClientRect();
  // the camera: 2.4× on the caret, pulling out to about 1.2× on the whole modal as the question is typed
  const askCam = (b) => {
    const D = decks[0].D; if (!D.querySelector('#askIn')) return {};
    const r = inRect(), m = modalR(), k = E.inOut(lp(b, 92.3, 1.7));
    const s = lerp(3.2, Math.min(1.7, 1500 / m.width), k);
    const x = lerp(caretX(D) - 60, m.left + m.width / 2, k), y = lerp(r.top + r.height / 2, r.top + r.height / 2 - 40, k);
    return { x, y, s, ax: 960, ay: lerp(560, 600, k), rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0 };
  };
  tween(0, 92.08, .3, () => askCam(92.3), E.out, (T) => ({ ry: 60, ax: T.ax + 900, mx: 80, o: 0 }));
  drive(0, 92.38, 94.0, (p, b, D) => { if (D.querySelector('#askIn')) Object.assign(decks[0].C, askCam(b)); });
  clickAt(0, 94.4, '[data-act="askSend"]', (a) => {
    a.W.eval('askStream(' + JSON.stringify(Q) + ', askAnswer("persona", 2))');
    const i = a.D.querySelector('#askIn'); if (i) i.value = '';
  }, { bloom: 'var(--ai)', glide: .5 });
  // after the press: push in on the answer's first lines
  tween(0, 94.55, .6, () => Object.assign(framing(0, '#askA', [240, 620, 1500, 520], { s: 3, px: 0, py: 0 })), E.inOut);
  tag(0, 93.2, 94.9, '#modal', 'bottom', [['eb ai', '04 · 问你自己的本地 Agent'], ['lt', '数据不出本机 · 0 B 上传']], { at: .5, gap: 34, anim: tg(.2) });
  tween(0, 94.95, .35, () => OUT.down(decks[0].C), E.in);

  /* ---------- 6.5–6.9 「还有 ___」 (b95.2–101.4) ---------- */
  const WORDS = ['桌面小组件', '及时提醒', '⌘K', 'Lite / Advance', '深色模式'];
  const SW_AT = [1.2, 2.4, 3.6, 4.8];                          // beats after b95.2: 96.4 / 97.6 / 98.8 / 100.0
  const swapV = K.swap({ at: SW_AT, dur: .3, out: 0 }), swapS = K.swap({ at: SW_AT, dur: .45, mode: 'scr', out: 0 });
  txt(95.2, 101.45, [['hv mt-sw', '还有 <span class="sw">' + WORDS.map((w) => '<span>' + w + '</span>').join('') + '</span>']], { x: 960, y: 220, align: 'c' }, {
    anim: (el, tl, life, t) => {
      let cur = 0; SW_AT.forEach((b, i) => { if (tl >= BB(b)) cur = i + 1; });
      (cur % 2 ? swapS : swapV)(el, tl, life, t);
      const inn = E.out(clamp(tl / BB(.4)));
      const b = t / BEAT, q = E.inOut(lp(b, 101.0, .4));     // the whole group turns and shrinks into the centre
      el.style.transform = 'translate(-50%,-50%) translate(0,' + ((1 - inn) * 40 + q * 320).toFixed(1) + 'px) rotate(' + (q * 80).toFixed(2) + 'deg) scale(' + lerp(1, .3, q).toFixed(3) + ')';
      el.style.opacity = (inn * (1 - q)).toFixed(3); el.style.filter = q > .001 ? 'blur(' + (q * 6).toFixed(1) + 'px)' : (inn < .999 ? 'blur(' + ((1 - inn) * 8).toFixed(1) + 'px)' : 'none');
    }
  });
  const BOXC = [960, 690, 1500, 560];
  const upOut = (d) => () => { const C = decks[d].C; return { ay: C.ay - 110, o: 0, bl: 10 }; };
  const fromBelow = (T) => ({ ay: T.ay + 160, o: 0, bl: 10 });
  // 6.5 desktop widgets pop up (deck 1)
  at(94.0, () => { const a = app(1); a.W.closeModal(); a.S.widgets = true; a.go('overview'); solo(1, '#widgets'); });
  tween(1, 95.25, .5, () => framing(1, '#widgets', BOXC, { max: 2.2 }), ease.back, (T) => ({ s: T.s * .55, o: 0, bl: 6 }));
  tween(1, 95.7, .7, () => ({ s: decks[1].C.s * 1.03 }), E.sine);
  tween(1, 96.15, .35, upOut(1), E.in);
  // 6.6 a notification slides in (deck 0)
  at(95.75, () => { const a = app(0); a.W.closeModal(); a.D.querySelectorAll('#notes .nt').forEach((n) => n.remove()); a.go('overview'); });
  at(96.15, () => { const a = app(0); a.W.simEvent('waiting'); solo(0, '#notes .nt'); });
  tween(0, 96.4, .5, () => framing(0, '#notes .nt', BOXC, { max: 2.4 }), E.quart, fromBelow);
  tween(0, 96.9, .7, () => ({ s: decks[0].C.s * 1.03 }), E.sine);
  tween(0, 97.35, .35, upOut(0), E.in);
  // 6.7 ⌘K palette, typing 「部署」 (deck 1)
  at(97.2, () => { const a = app(1); a.W.openPalette(); solo(1, '#modal'); });
  drive(1, 97.75, 98.4, (p, b, D) => { const q = D.querySelector('#palQ'); if (!q) return; const s = '部署'.slice(0, Math.floor(p * 2.99)); if (q.value !== s) { q.value = s; q.dispatchEvent(new Event('input', { bubbles: true })); } });
  tween(1, 97.6, .5, () => framing(1, '#modal', BOXC, { max: 1.8, py: .45 }), E.quart, fromBelow);
  tween(1, 98.55, .35, upOut(1), E.in);
  // 6.8 the edition switch, flanked by its two names; the pointer picks Lite (deck 0)
  at(98.3, () => { const a = app(0); a.D.querySelectorAll('#notes .nt').forEach((n) => n.remove()); a.W.closeModal(); a.go('overview'); solo(0, '.edsw'); });
  tween(0, 98.8, .5, () => framing(0, '.edsw', [960, 700, 700, 200], { max: 3.4 }), E.quart, fromBelow);
  tag(0, 98.9, 100.15, '.edsw', 'left', [['md sv', 'Lite']], { gap: 44, anim: tg(0) });
  tag(0, 98.9, 100.15, '.edsw', 'right', [['md sv', 'Advance']], { gap: 44, anim: tg(0) });
  // the press does what edSet() does first (the thumb slides to Lite); the page swap that follows would re-render the
  // sidebar with an entrance fade and lose the switch for the rest of the shot
  clickAt(0, 99.4, '[data-act="edition"][data-v="lite"]', (a) => { a.D.querySelector('#win').dataset.ed = 'lite'; a.D.querySelectorAll('.edsw [data-act="edition"]').forEach((x) => x.setAttribute('aria-checked', String(x.dataset.v === 'lite'))); }, { glide: .45 });
  tween(0, 99.9, .35, upOut(0), E.in);
  // 6.9 dark mode: a light copy (deck 1) is wiped diagonally left → right to reveal a dark copy beneath it (deck 0)
  at(99.3, () => { const a = app(1); a.W.closeModal(); a.go('overview'); solo(1, '#widgets'); });
  tween(1, 100.0, .45, () => framing(1, '#widgets', BOXC, { max: 2.2 }), E.quart, fromBelow);
  at(100.26, () => { const a = app(0); a.W.setTheme('dark'); a.S.widgets = true; a.render(); solo(0, '#widgets'); });
  drive(0, 100.27, 101.0, (p, b) => { Object.assign(decks[0].C, decks[1].C); if (b < 100.4) decks[0].C.o = 0; });
  let WX = null;
  every(100.38, 100.95, (p) => {
    if (!WX) WX = [elXY(1, '#widgets', 0, .5)[0] - 320, elXY(1, '#widgets', 1, .5)[0] + 320];
    const X = lerp(WX[0], WX[1], E.inOut(p)), h = $('#hole1');   // the light copy keeps only what is right of the edge
    h.style.clipPath = p >= 1 ? 'polygon(0 0,0 0,0 0)' : 'polygon(' + (X + 280).toFixed(1) + 'px 0,2400px 0,2400px 1080px,' + (X - 280).toFixed(1) + 'px 1080px)';
  });
  // b101–101.4: the group turns and shrinks into the centre (the close scene's compass comes in from b100.6)
  tween(1, 101.0, .4, () => ({ rz: 80, s: decks[1].C.s * .3, ax: 960, ay: 540, o: 0, bl: 6 }), E.inOut);
  tween(0, 101.0, .4, () => ({ rz: 80, s: decks[0].C.s * .3, ax: 960, ay: 540, o: 0, bl: 6 }), E.inOut);

  /* ---------- hand-off: both copies back to Advance + light, holes open ---------- */
  at(101.55, () => {
    for (const d of [0, 1]) {
      const a = app(d); a.W.closeModal(); a.D.querySelectorAll('#notes .nt').forEach((n) => n.remove());
      a.S.widgets = false; a.W.setTheme('light'); a.W.edSet('advance'); a.D.querySelector('#win').dataset.ed = a.S.ed; a.render();
      $('#hole' + d).style.clipPath = 'none';
    }
  });
});

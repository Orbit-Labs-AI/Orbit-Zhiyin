/* 02 推荐 → 效率（b55.7–86.6）：穿越门 → 三张建议逐张落下、停住、离开，上方的预计省时随每张落定滚动 → 看清改动，
   再确认应用 → 直接看前后对比 → 把时间还给你自己. Shots and hand-offs: STORYBOARD.md (KF 5.1–5.13).
   5a  three real cards of deck 0 (Skill paper-audit, Prompt acceptance, Hook retry-breaker) drop one at a time into the
       same place under a fixed headline, hold ≈ 1.6 s each and leave downwards; the last one stays. The headline's
       number rolls as each card lands (the cards' own monthly estimates), the words only say what it is.
   5b  the Hook lifts, its install button is pressed, deck 0 turns away while deck 1's install sheet turns in; the sheet
       holds ≈ 2 s, then the app's real 下一步 / 确认写入 run and the applied state holds ≈ 1 s.
   5c  straight to the before/after rows of the same recommendation (no seven-day strip): after-dots slide and the
       green pills count; ≈ 3 s to read.
   5d  the card falls back; 「把时间 / 还给 / 你 / 自己」 lands on the drop at b82.2. */
scene('40-recs', () => {
  css(`
.r-or{color:var(--a1)}
.ln.r-tot{overflow:visible}
.ln.r-tot>span{display:inline-flex;align-items:baseline;gap:22px}
.r-tot .r-n{font-variant-numeric:tabular-nums}
.r-tot .r-u{font-size:72px;font-weight:600;letter-spacing:0;color:var(--a1)}
.r-fly{position:absolute;left:0;top:0;font:700 54px var(--mono);color:var(--a1);white-space:nowrap;will-change:transform,opacity;text-shadow:0 4px 24px rgba(0,0,0,.6)}
.ln.r-eb>span{display:inline-flex;align-items:baseline;gap:20px}
.r-eb .r-ebl{font-family:var(--mono);font-size:24px;letter-spacing:.3em;color:rgba(255,255,255,.6)}
.r-eb .r-ebn{font-size:48px;font-weight:700;color:var(--a1);letter-spacing:-.01em}
.k .eb.r-or{color:var(--a1)}
.r-day{font:600 30px var(--mono);color:#fff;letter-spacing:.06em}
.r-dim{color:rgba(255,255,255,.62)}
.r-mn{font-size:40px;color:rgba(255,255,255,.72)}
.ln.r-mv{overflow:visible}
.ln.r-mv>span{display:inline-flex;align-items:center;gap:.3em}
.r-mv .st{color:rgba(255,255,255,.5);font-weight:500}
.r-mv .r-ar{color:rgba(255,255,255,.5);font-weight:400}
.r-mv b{font-weight:700;color:#fff;font-variant-numeric:tabular-nums}
.r-mv .r-un{font-size:40px;font-weight:400;color:rgba(255,255,255,.72)}
.k .pill.r-g{font-size:40px;color:#7fd6a4;background:rgba(127,214,164,.13);border:1.5px solid rgba(127,214,164,.55);margin-left:.25em}
.ln.r-vd{overflow:visible}
.k .pill.r-ok{font:700 40px var(--sans);color:#fff;background:var(--a1);box-shadow:0 14px 40px rgba(226,96,43,.35)}
.ln.r5{overflow:visible}
.ln.r5>span{display:grid;grid-template-columns:auto auto;column-gap:34px;align-items:start;text-align:left}
.r5 .r5-pre{grid-row:1;grid-column:1;display:flex;flex-direction:column;align-items:flex-end;gap:10px;padding-top:58px;font:500 30px var(--mono);letter-spacing:.24em;color:rgba(255,255,255,.72)}
.r5 .r5-pre span{display:block;will-change:transform,opacity}
.r5 .r5-num{grid-row:1;grid-column:2;font-family:var(--display);font-size:300px;line-height:.92;letter-spacing:-.02em;transform-origin:30% 60%;
  background:linear-gradient(180deg,#fff 35%,#b4b8c2);-webkit-background-clip:text;background-clip:text;color:transparent;will-change:transform,opacity,filter}
.r5 .r5-u{grid-row:2;grid-column:2;font-size:120px;font-weight:700;line-height:1.1;color:var(--a1);will-change:transform,opacity}
`);
  const RB = 'retry-breaker';
  // tag() scales a top/bottom tag about its own (at·100%) point and then shifts it by at·100% of its scaled width, which
  // lands it (1 − s)·at·width off its anchor whenever at > 0; scaling about the corner puts it back on the anchor
  const pin = (f) => (el, tl, life, t) => { el.style.transformOrigin = '0 0'; if (f) f(el, tl, life, t); };
  const card = (D, id) => D.querySelector('.rcard[data-id="' + id + '"]');
  // both copies stay in the Advance edition, light theme (hand-off contract)
  const advLight = (d) => { const W = decks[d].W; if (W.eval('S.ed') !== 'advance') W.eval("S.ed='advance';store.set('edition','advance');document.querySelector('#win').dataset.ed='advance'"); W.setTheme('light'); };
  // the engine's .promo-card ring loses to the solo shadow rule; give a solo'd promo-card its paper margin back
  const paperCss = (D) => { if (D.getElementById('r-paper')) return; const s = D.createElement('style'); s.id = 'r-paper'; s.textContent = 'html body .promo-solo.promo-card{box-shadow:0 0 0 22px var(--surface),0 30px 90px 22px rgba(0,0,0,.55)!important;border-radius:6px}'; D.head.appendChild(s); };

  // solo() scrolls targets into view, which also scrolls the clipped window and the desk: undo it on every ancestor
  // the app's entrance animations (fill: both) would override the cards' inline transforms: drop them
  const still = (D) => D.getAnimations().forEach((a) => { const t = a.effect && a.effect.target; if (t && t.closest && t.closest('.recs')) a.cancel(); });
  const unscroll = (D) => { for (let e = D.querySelector('#content'); e; e = e.parentElement) { if (e.scrollTop) e.scrollTop = 0; if (e.scrollLeft) e.scrollLeft = 0; } };


  /* ---------- 5a three cards drop under a fixed headline (b54.8–66.4) ---------- */
  const IDS = ['paper-audit', 'acceptance', RB];
  const LAND = [57.0, 62.0, 67.0], HOLD = 4.4, DROP = .6;                  // card i: drops from LAND − DROP, leaves at LAND + HOLD
  // later beats move with the longer card holds (A), the longer install sheet (B), applied state (C) and before/after (D)
  const dA = 4.0, dB = dA + 1.5, dC = dB + 1, dD = dC + 2;
  const CARDBOX = [960, 690, 1760, 440];
  let BASE = {}, SAVE = [0, 0, 0], FR = null;
  at(54.8, () => {
    advLight(0);
    const a = app(0); a.S.recs.sel = RB; a.S.recs.tab = 'why'; a.S.recs.dim = 'all'; a.S.recs.peek = null; a.go('recs');
    const D = a.D; paperCss(D); still(D); unscroll(D);
    IDS.forEach((id) => { const c = card(D, id); if (!c) { console.warn('promo 40-recs: no card', id); return; } c.style.transform = 'none'; c.style.filter = 'none'; const r = c.getBoundingClientRect(); BASE[id] = { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height }; });
    SAVE = IDS.map((id) => { const v = +a.W.eval('recX(' + JSON.stringify(id) + ').save'); return isFinite(v) ? v : 0; });
    solo(0, IDS.map((id) => (DD) => card(DD, id))); unscroll(D);
  });
  // all three cards are moved onto the place of the first one (in the app's own px); the camera frames that place
  const P0 = () => BASE[IDS[0]] || { x: 800, y: 400, w: 380, h: 170 };
  const frameCards = () => { const p = P0(), [cx, cy, w, h] = CARDBOX, s = Math.min(w / p.w, h / p.h); return { x: p.x, y: p.y, s, ax: cx, ay: cy, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0 }; };
  tween(0, 55.2, 0, () => (FR = frameCards()), E.lin, () => ({}));
  tween(0, 57.4, 7.6 + dA, () => ({ s: decks[0].C.s * 1.02 }), E.sine);
  drive(0, 54.85, 67.2 + dA, (p, b, D) => {
    unscroll(D); still(D);
    const p0 = P0(), lift = E.inOut(lp(b, 65.6 + dA, .7));
    IDS.forEach((id, i) => {
      const el = card(D, id), B = BASE[id]; if (!el || !B) return;
      const inn = E.out(lp(b, LAND[i] - DROP, DROP)), out = i < 2 ? E.in(lp(b, LAND[i] + HOLD, DROP)) : 0;
      const dy = -B.h * 1.1 * (1 - inn) + B.h * 1.1 * out, mine = id === RB;
      el.style.transform = 'translate(' + (p0.x - B.x).toFixed(1) + 'px,' + (p0.y - B.y + dy).toFixed(1) + 'px) scale(' + (mine ? 1 + .06 * lift : 1).toFixed(4) + ')';
      el.style.opacity = (Math.min(1, inn * 1.6) * (1 - out)).toFixed(3);
      el.style.filter = (1 - inn) + out > .02 ? 'blur(' + (((1 - inn) + out) * 5).toFixed(1) + 'px)' : 'none';
      el.style.zIndex = String(i + 1);
    });
  });
  // headline: the eyebrow, the rolling estimate and one line that says what the number is
  txt(56.0, 66.4 + dA, [['eb', '02 · 推荐 · 按协作人格定制']], { x: 960, y: 120, align: 'c' }, { outB: .5 });
  const cum = (b) => SAVE.reduce((v, h, i) => v + h * E.out(lp(b, LAND[i], 1.4)), 0);   // rolls for ≈ 0.7 s as each card lands
  txt(56.4, 66.4 + dA, [['xl sv r-tot', '<span class="r-n">0.0</span><span class="r-u">h / 月</span>']], { x: 960, y: 290, align: 'c' }, {
    anim: K.rise({ in: .8, out: .5 }),
    tick: (el, tl, life, t) => { const n = el.querySelector('.r-n'); if (n) n.textContent = cum(t / BEAT).toFixed(1); }
  });
  txt(56.8, 66.4 + dA, [['lt', '每条建议都标明预计省下的时间']], { x: 960, y: 440, align: 'c' }, { outB: .5 });
  // the type of each card, beside it while it holds
  IDS.forEach((id, i) => {
    const kind = { 'paper-audit': 'Skill · 把流程写成技能', acceptance: 'Prompt · 更好的开场', 'retry-breaker': 'Hook · 自动拦住重复失败' }[id];
    tag(0, LAND[i] - .2, i < 2 ? LAND[i] + HOLD : 66.2 + dA, (D) => card(D, id), 'bottom', [['lt r-or', kind]], { gap: 34, at: .5, outB: .3, tick: pin() });
  });

  /* ---------- 5b lift → press → flip into the install sheet; read; 下一步 → 确认写入 → 已应用 (b65.6–75.2) ---------- */
  tween(0, 65.6 + dA, .9, () => ({ s: decks[0].C.s * 1.06, ay: 620 }), E.inOut);
  clickAt(0, 66.6 + dA, (D) => { const c = card(D, RB); return c && c.querySelector('[data-act="install"]'); }, () => {}, { bloom: 'var(--a1)', glide: .9 });
  tween(0, 66.7 + dA, .32, () => ({ ry: 90, s: decks[0].C.s * .96 }), E.in);
  tween(0, 67.04 + dA, 0, { o: 0 }, E.lin);
  at(65.6 + dA, () => {
    advLight(1);
    const a = app(1); a.S.recs.sel = RB; a.S.recs.tab = 'why'; a.go('recs');
    if (a.W.eval('S.installed.has("' + RB + '")')) a.W.eval('S.installed.delete("' + RB + '")');
    a.W.openInstall(RB); solo(1, '#modal');
  });
  const SHEET = [960, 420, 1180, 640];
  tween(1, 67.02 + dA, .36, () => framing(1, '#modal', SHEET), E.out, () => ({ ry: -90, o: 1 }));
  tween(1, 67.4 + dA, 7.4 + dC - dA, () => ({ s: decks[1].C.s * 1.03 }), E.sine);
  const press = (a, el) => { a.W.eval('INST && (INST.t = 0)'); a.click(el); };   // runs the app's own flow; a jump in time must not trip its double-click guard
  clickAt(1, 71.8 + dB, '#modal .btn.p', press, { glide: 1.0 });
  clickAt(1, 73.0 + dB, '#modal .btn.p', press, { glide: .6 });
  txt(67.0 + dA, 75.2 + dC, [['hv sv', '看清改动，再确认应用'], ['md r-or', '<span class="sw"><span>一键安装 · 随时撤销</span><span>已应用 · 自动对比前后效果</span></span>']], { x: 960, y: 928, align: 'c' }, {
    anim: K.all(K.rise({ st: .25, out: .5 }), K.swap({ at: [73.3 + dB - 67.0 - dA], dur: .35 }))
  });

  /* ---------- 5c before / after of the same recommendation, no seven-day strip (b74.6–81.6) ---------- */
  const METS = (D) => { const m = D.querySelector('.rc-metric'); return m && m.parentElement; };
  at(74.6 + dC, () => {
    const a = app(0), S = a.S;
    S.recs.sel = RB; S.recs.tab = 'track'; S.recs.peek = RB;
    S.installed.set(RB, { days: 7, at: 0, target: a.W.eval('RECI["' + RB + '"].target'), scope: 'global' });
    a.go('recs'); paperCss(a.D);
    solo(0, METS); unscroll(a.D);
  });
  tween(1, 75.0 + dC, .7, () => ({ s: decks[1].C.s * .9, o: 0, bl: 8 }), E.in);
  const ROW = [76.4 + dC, 77.2 + dC, 78.0 + dC], SLIDE = .9;
  drive(0, 74.62 + dC, 81.6 + dD, (p, b, D) => {
    const mets = METS(D); if (!mets) return;
    mets.classList.add('promo-card'); unscroll(D);
    D.querySelectorAll('.rc-metric').forEach((m, i) => {
      m.querySelectorAll('.rc-mh > .mono, .rc-mh > .rc-d, .rc-mh > .rc-ci').forEach((e) => e.style.setProperty('visibility', 'hidden', 'important'));
      const svg = m.querySelector('svg.vz-t-dumbbell'); if (!svg) return;
      const A = svg.querySelector('circle.vz-pt[data-s="0"]'), Bp = svg.querySelector('circle.vz-pt[data-s="1"]'), ln = svg.querySelector('line.vz-dline'), val = svg.querySelector('text.vz-val');
      if (!A || !Bp) return;
      if (Bp.dataset.cx == null) { Bp.dataset.cx = Bp.getAttribute('cx'); A.dataset.cx = A.getAttribute('cx'); }
      const a0 = +A.dataset.cx, b0 = +Bp.dataset.cx, q = E.inOut(lp(b, ROW[i], SLIDE)), x = lerp(a0, b0, q);
      Bp.setAttribute('cx', x.toFixed(2)); if (ln) ln.setAttribute('x2', x.toFixed(2));
      if (val) val.style.opacity = E.out(lp(b, ROW[i] + SLIDE, .4)).toFixed(3);
    });
  });
  const MET = [660, 560, 1000, 700];
  tween(0, 75.2 + dC, 1.0, () => framing(0, METS, MET, { max: 3 }), E.quart, IN.depth);
  tween(0, 76.2 + dC, 5.0 + dD - dC, () => ({ s: decks[0].C.s * 1.025 }), E.sine);
  txt(75.4 + dC, 81.2 + dD, [['lt', '装上之后，自动对比前后效果']], { x: 960, y: 205, align: 'c' }, { anim: K.blurIn({ out: .5 }) });
  // row figures from the app's own statistics (trackStats: 23 → 7 段, 58 → 17 分钟, 12 → 5 次)
  let ST = [];
  try { ST = decks[0].W.eval('trackStats(RECI["' + RB + '"]).rows').map((m) => ({ name: m.name, a: m.a, b: m.b, unit: m.unit, rel: m.rel })); } catch (e) { console.error('promo 40-recs: trackStats', e); }
  ST.forEach((m, i) => {
    const b0 = ROW[i] - .5;
    tag(0, b0, 81.2 + dD, (D) => D.querySelectorAll('.rc-metric')[i], 'right', [['lt r-mn', m.name], ['md r-mv', '<span class="r-ar">安装前 → 安装后</span><span class="pill r-g">' + (m.rel < 0 ? '↓ ' : '↑ ') + '<b data-to="' + Math.round(Math.abs(m.rel) * 100) + '">0</b>%</span>']], {
      gap: 84, at: .5, tick: (el) => { el.style.textAlign = 'left'; },
      anim: K.all(mask(.14, .9, .5), K.pop(.5, 0, .3), K.count(.5, SLIDE + .4))
    });
  });
  tag(0, 76.0 + dC, 81.2 + dD, METS, 'bottom', [['eb', '同一批项目 · 安装前后对比']], { gap: 80, at: 0 });
  tag(0, 79.2 + dC, 81.2 + dD, METS, 'top', [['r-vd', '<span class="pill r-ok">✓ 有效</span>']], {
    gap: 78, at: 1, tick: pin(), anim: K.all(K.pop(0, 0, .3), (el, tl, life) => { el.style.opacity = exitQ(tl, life, .5).toFixed(3); })
  });

  /* ---------- 5e 把时间还给你 (b81.2–86.6) ---------- */
  tween(0, 81.2 + dD, .8, () => { const C = decks[0].C; return { rx: 58, s: C.s * .62, ay: C.ay + 300, o: 0, bl: 6 }; }, E.in);
  const PRE = [81.6 + dD, 81.9 + dD], HIT = 82.2 + dD, UNIT = 82.4 + dD, F3 = 3 / 60 / BEAT;    // three frames, in beats
  txt(81.5 + dD, 86.6 + dD, [['r5', '<span class="r5-pre"><span>把时间</span><span>还给</span></span><span class="r5-num">你</span><span class="r5-u">自己</span>']], { x: 960, y: 452, align: 'c' }, {
    anim: (el, tl, life, t) => {
      const b = t / BEAT;
      el.querySelectorAll('.r5-pre span').forEach((s, i) => { const q = clamp((b - PRE[i]) / (2 / 60 / BEAT)); s.style.opacity = q.toFixed(3); s.style.transform = 'translateY(' + ((1 - E.out(lp(b, PRE[i], .25))) * 14).toFixed(1) + 'px)'; });
      const n = el.querySelector('.r5-num'), q = lp(b, HIT, .22);
      n.style.opacity = (b >= HIT ? Math.min(1, .35 + q * 4) : 0).toFixed(3);
      n.style.transform = 'scale(' + lerp(1.16, 1, E.out(q)).toFixed(4) + ')';
      n.style.filter = q < 1 ? 'blur(' + ((1 - E.out(q)) * 6).toFixed(1) + 'px)' : 'none';
      n.style.fontWeight = Math.round(lerp(200, 900, clamp((b - HIT) / F3)));
      const u = el.querySelector('.r5-u'), qu = E.out(lp(b, UNIT, .35));
      u.style.opacity = qu.toFixed(3); u.style.transform = 'translateY(' + ((1 - qu) * 40).toFixed(1) + 'px)';
      leave(el, exitQ(tl, life, .55), true);
    }
  });
  txt(83.4 + dD, 86.6 + dD, [['lt', '按协作人格定制 · 一键安装 · 前后对比验证']], { x: 960, y: 858, align: 'c' }, { anim: K.blurIn({ spread: .6, out: .55, spread2: true }) });
  glowAt(HIT, .9, .5);
  glowAt(83.2 + dD, 0, 2.2);
});
